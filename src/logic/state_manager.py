"""
state_manager.py — Persistent user state (inventory, profile) for the Offline Crisis Assistant.

Inventory extraction is done with Python regex — NO second LLM call is made.
The LLM is only shown the resulting state block injected into the prompt.

Public API used by generator.py:
    sm = StateManager()
    items = sm.try_extract_inventory(user_text)   -> dict or {}
    sm.update_inventory_direct(items)             -> persist to disk
    sm.is_inventory_query(user_text)              -> bool
    sm.get_readable_inventory()                   -> Turkish string for display
    sm.get_context_block()                        -> injected into system prompt
    sm.clear()                                    -> wipe state
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from core.config import USER_STATE_PATH

# ---------------------------------------------------------------------------
# Module-level patterns for Python-side inventory extraction (no LLM needed)
# ---------------------------------------------------------------------------

_UNITS = (
    r'(?:litre|lt|litr|kilogram|kg|gram|gr\b|paket|adet|tane|'
    r'şise|kutu|kilo|ml|torba|çuval|cuval|kap|porsiyon|sise)'
)

# Turkish words that should NOT become inventory item names.
# Includes verb roots produced by aggressive suffix-stripping:
#   aldım -> ald, buldum -> buld, verdim -> verd, geldim -> geld, etc.
_STOP_WORDS = {
    # Conjunctions / particles
    've', 'de', 'da', 'bir', 'iki', 'uc', 'dort', 'bes',
    'alti', 'yedi', 'sekiz', 'dokuz', 'on', 'bu', 'an',
    'simdi', 'var', 'yok', 'varmis', 'mevcut', 'bulunuyor', 'varmidir',
    'kadar', 'ile', 'icin', 'gibi', 'ya', 'ne', 'nasil',
    'nerede', 'ben', 'biz', 'sen', 'siz', 'bende', 'bizde',
    'evet', 'hayir', 'tamam', 'olur', 'peki', 'iyi', 'kotu',
    # Verb roots left after suffix-stripping (false positives)
    'ald', 'buld', 'verd', 'geld', 'gitt', 'yapt', 'getird',
    'got', 'al', 'gel', 'git', 'ver', 'yap', 'bak', 'tut',
    'bul', 'cek', 'koy', 'cik', 'gir', 'don', 'dol', 'kok',
    # Other false-positive fragments
    'tane', 'kisi', 'sahip', 'elimd', 'buld',
}

# Exact lowercase phrases that trigger the inventory SHOW command.
# Checked BEFORE try_extract_inventory and before RAG.
_EXPLICIT_SHOW_TRIGGERS = {
    'envanter', 'envanterim', 'envanteri',
    'envanter ne durumda', 'envanterim ne durumda',
    'envanter listele', 'envanteri goster', 'envanterimi goster',
    'elimde ne var', 'elimde neler var', 'elimde neler',
    'yanımda ne var', 'yanimda ne var', 'yanımda neler', 'yanimda neler',
    'ne var elimde', 'ne var yanımda', 'ne var yanimda',
    'malzemelerim neler', 'malzemelerim ne',
    'ne var bende', 'bende ne var',
    'stogumda ne var', 'stokta ne var',
}

# Prefix-based show triggers (starts-with check)
_SHOW_PREFIXES = ('envanterim', 'envanter goster', 'envanter listele',
                  'envanter ne', 'envanterimi')

# Post-response artifact patterns to strip (phi-3.5-mini adds these)
_ARTIFACT_PATTERNS = [
    re.compile(r'\n+\[?Pe[sş]i\]?\s*:.*$', re.IGNORECASE | re.MULTILINE),
    re.compile(r'\n+(?:Sonraki\s+adim|Sonraki\s+adım|Next\s+step|Follow\s*-?up)\s*:.*$',
               re.IGNORECASE | re.MULTILINE),
    re.compile(r'\n+(?:Not|Dikkat|Ozet|Özet|Note|Warning)\s*:.*$',
               re.IGNORECASE | re.MULTILINE),
    re.compile(r'<INVENTORY>.*?</INVENTORY>', re.DOTALL | re.IGNORECASE),
    re.compile(r'\n*\[BITTI\].*$', re.DOTALL),
]


def _normalize_item(name: str) -> str:
    """Lowercase and strip common Turkish noun suffixes to get the root form."""
    name = name.lower().strip()
    name = re.sub(
        r'(?:lar|ler|lerin|im|ım|um|üm|in|ın|un|ün|'
        r'a|e|ye|ya|dan|den|tan|ten|da|de|ta|te)$',
        '', name
    )
    return (
        name.replace('ı', 'i').replace('İ', 'i')
            .replace('ğ', 'g').replace('Ğ', 'g')
            .replace('ü', 'u').replace('Ü', 'u')
            .replace('ş', 's').replace('Ş', 's')
            .replace('ö', 'o').replace('Ö', 'o')
            .replace('ç', 'c').replace('Ç', 'c')
    )


def _norm_cmd(text: str) -> str:
    """Normalize text for command matching (lowercase + ASCII Turkish chars)."""
    return (
        text.lower().strip()
            .replace('ı', 'i').replace('İ', 'i').replace('ğ', 'g')
            .replace('ü', 'u').replace('ş', 's').replace('ö', 'o')
            .replace('ç', 'c').replace('Ğ', 'g').replace('Ü', 'u')
            .replace('Ş', 's').replace('Ö', 'o').replace('Ç', 'c')
    )


def _parse_item_list(text: str, default_qty: str = '1 adet') -> dict:
    """
    Parses a comma/semicolon-separated item list with optional quantities.
    Handles 'item number unit', 'number unit item', 'item number', and bare names.

    Examples:
      'su 5 litre, bisküvi 2 paket'  -> {'su': '5 litre', 'biskuvi': '2 paket'}
      '5 litre su'                   -> {'su': '5 litre'}
      'pil, çakmak'                  -> {'pil': '1 adet', 'cakmak': '1 adet'}
    """
    result = {}
    for part in re.split(r'[,;]', text):
        part = part.strip()
        if not part:
            continue

        # A: item + number + unit  (e.g. 'su 5 litre')
        m = re.match(
            r'^([a-zçğışöüA-ZÇĞİŞÖÜ][\w\s]*?)\s+(\d+[\.,]?\d*)\s*(' + _UNITS + r')',
            part, re.IGNORECASE | re.UNICODE
        )
        if m:
            key = _normalize_item(m.group(1).strip())
            if key and len(key) >= 2:
                result[key] = f"{m.group(2)} {m.group(3)}"
            continue

        # B: number + unit + item  (e.g. '5 litre su')
        m = re.match(
            r'^(\d+[\.,]?\d*)\s*(' + _UNITS + r')\s+([a-zçğışöüA-ZÇĞİŞÖÜ][\w\s]*)',
            part, re.IGNORECASE | re.UNICODE
        )
        if m:
            key = _normalize_item(m.group(3).strip())
            if key and len(key) >= 2:
                result[key] = f"{m.group(1)} {m.group(2)}"
            continue

        # C: item + number only  (e.g. 'pil 6')
        m = re.match(
            r'^([a-zçğışöüA-ZÇĞİŞÖÜ][\w\s]*?)\s+(\d+)$',
            part, re.IGNORECASE | re.UNICODE
        )
        if m:
            key = _normalize_item(m.group(1).strip())
            if key and len(key) >= 2:
                result[key] = f"{m.group(2)} adet"
            continue

        # D: bare name, no quantity
        m = re.match(r'^([a-zçğışöüA-ZÇĞİŞÖÜ][\w\s]{1,})$', part, re.IGNORECASE | re.UNICODE)
        if m:
            key = _normalize_item(m.group(1).strip())
            if key and len(key) >= 2 and key not in _STOP_WORDS:
                result[key] = default_qty

    return result


def parse_explicit_inventory_command(text: str):
    """
    Detects and parses explicit inventory management commands typed by the user.
    Returns (command_type: str, data: dict) or (None, {}) if not a command.

    Recognised patterns (case-insensitive, Turkish-char-tolerant):
      'envanter'                           -> ('show', {})
      'envanter ne durumda'                -> ('show', {})
      'envanter ekle su 5 litre'           -> ('add',  {'su': '5 litre'})
      'envanter ekle: su 5 lt, pil 6'      -> ('add',  {'su': '5 lt', 'pil': '6 adet'})
      'envanter guncelle su 3 litre'       -> ('add',  {'su': '3 litre'})
      'envanter sil su'                    -> ('delete', {'su': '0'})
    """
    t = _norm_cmd(text)

    # Show
    if t in _EXPLICIT_SHOW_TRIGGERS:
        return 'show', {}
    if any(t.startswith(p) for p in _SHOW_PREFIXES):
        if 'ekle' not in t and 'sil' not in t and 'guncelle' not in t:
            return 'show', {}

    # Add / Update
    add_m = re.match(
        r'envanter(?:e)?\s+(?:ekle|guncelle|kaydet)\s*:?\s*(.+)', t, re.IGNORECASE
    )
    if add_m:
        items = _parse_item_list(add_m.group(1))
        return ('add', items) if items else (None, {})

    # Delete (can be exact amount or ALL)
    del_m = re.match(r'envanter\s+sil\s*:?\s*(.+)', t, re.IGNORECASE)
    if del_m:
        items = _parse_item_list(del_m.group(1).strip(), default_qty='ALL')
        return ('delete', items) if items else (None, {})

    return None, {}


class StateManager:
    """
    Manages the user's persistent inventory and situational profile.

    The state dict has two keys:
      - "inventory": {"item_name": "amount_or_description", ...}
      - "profile":   {"kisi_sayisi": "4", "cocuk_var": "evet", ...}
    """

    def __init__(self):
        self._state = {"inventory": {}, "profile": {}}
        self._load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self):
        """Load state from disk if the file exists."""
        if os.path.exists(USER_STATE_PATH):
            try:
                with open(USER_STATE_PATH, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                # Merge safely: only keep known top-level keys
                for key in ("inventory", "profile"):
                    if key in loaded and isinstance(loaded[key], dict):
                        self._state[key] = loaded[key]
                print(f"(*) User state loaded: {self._summary()}")
            except Exception as e:
                print(f"[-] Could not load user state: {e}. Starting fresh.")

    def _save(self):
        """Persist current state to disk."""
        try:
            os.makedirs(os.path.dirname(USER_STATE_PATH), exist_ok=True)
            with open(USER_STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(self._state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[-] Could not save user state: {e}")

    def _summary(self) -> str:
        inv = self._state["inventory"]
        prof = self._state["profile"]
        parts = []
        if inv:
            parts.append(f"envanter={list(inv.keys())}")
        if prof:
            parts.append(f"profil={list(prof.keys())}")
        return ", ".join(parts) if parts else "bos"

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update_inventory_direct(self, items: dict):
        """
        Merge pre-parsed items into the inventory and persist to disk.
        If the item already exists with a numeric quantity, ADD to it.
        Items with value '0', 'sifir', or 'tukendi' are removed.
        Called by Python-level extraction -- no LLM involvement.
        """
        for key, val in items.items():
            key = str(key).strip().lower()
            val_str = str(val).strip()

            if val_str.lower() in ('0', 'sifir', 'tukendi', ''):
                self._state['inventory'].pop(key, None)
                continue

            existing = self._state['inventory'].get(key)
            if existing:
                # Try to add numerically if both have parseable numbers
                m_new = re.match(r'^(\d+[\.,]?\d*)\s*(.*)$', val_str, re.IGNORECASE)
                m_ex  = re.match(r'^(\d+[\.,]?\d*)\s*(.*)$', existing,  re.IGNORECASE)
                if m_new and m_ex:
                    new_num = float(m_new.group(1).replace(',', '.'))
                    ex_num  = float(m_ex.group(1).replace(',', '.'))
                    # Use the new value's unit; fall back to existing unit if new has none
                    unit = m_new.group(2).strip() or m_ex.group(2).strip()
                    total = ex_num + new_num
                    total_str = f"{total:g}"
                    self._state['inventory'][key] = f"{total_str} {unit}".strip()
                    continue
            # No existing entry or non-numeric: just set
            self._state['inventory'][key] = val_str

        self._save()
        print(f"(*) Inventory saved: {self._state['inventory']}")

    def remove_inventory_direct(self, items: dict):
        """
        Subtracts quantities or removes items completely if requested.
        `items` maps item_key -> amount_to_remove (e.g. '2 adet', '3 litre') or 'ALL'.
        """
        for key, remove_val in items.items():
            key = str(key).strip().lower()
            if key not in self._state['inventory']:
                continue

            if str(remove_val).upper() == 'ALL':
                self._state['inventory'].pop(key, None)
                continue

            # Parse the amount to remove
            m_rem = re.match(r'^(\d+[\.,]?\d*)\s*(.*)$', str(remove_val).strip(), re.IGNORECASE)
            if not m_rem:
                self._state['inventory'].pop(key, None)
                continue

            rem_num = float(m_rem.group(1).replace(',', '.'))
            rem_unit = m_rem.group(2).strip()

            # Parse the existing amount
            existing_val = self._state['inventory'][key]
            m_ex = re.match(r'^(\d+[\.,]?\d*)\s*(.*)$', existing_val, re.IGNORECASE)
            if not m_ex:
                # Could not parse existing number, fallback to remove all
                self._state['inventory'].pop(key, None)
                continue

            ex_num = float(m_ex.group(1).replace(',', '.'))
            ex_unit = m_ex.group(2).strip()

            new_num = ex_num - rem_num
            if new_num <= 0:
                self._state['inventory'].pop(key, None)
            else:
                # Format to remove .0 if it's an integer
                new_num_str = f"{new_num:g}"
                self._state['inventory'][key] = f"{new_num_str} {ex_unit}".strip()

        self._save()
        print(f"(*) Inventory after removal: {self._state['inventory']}")

    def update_profile(self, profile_dict: dict):
        """Merge profile info (person count, child presence, etc.)."""
        self._state['profile'].update(profile_dict)
        self._save()

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def has_state(self) -> bool:
        return bool(self._state['inventory'] or self._state['profile'])

    def is_inventory_query(self, text: str) -> bool:
        """Returns True if the user is asking about their saved inventory."""
        cmd, _ = parse_explicit_inventory_command(text)
        return cmd == 'show'

    def get_readable_inventory(self) -> str:
        """Returns a human-readable Turkish string of the current inventory."""
        inv = self._state['inventory']
        prof = self._state['profile']
        if not inv and not prof:
            return "Envanterinizde kayitli bir sey yok."
        lines = []
        if inv:
            lines.append("Kaydedilmis malzemeleriniz:")
            for item, amount in inv.items():
                lines.append(f"  - {item}: {amount}")
        if prof:
            lines.append("Durum bilgisi:")
            for key, val in prof.items():
                lines.append(f"  - {key}: {val}")
        return "\n".join(lines)

    def try_extract_inventory(self, text: str) -> dict:
        """
        Attempts to extract inventory items from natural language using regex.
        Returns a dict {item_key: 'qty unit'} or empty dict.
        Does NOT call the LLM — 100% offline, zero battery cost.

        Handles patterns like:
          '10 litre su var'       -> {su: '10 litre'}
          'su varmis 10 litre'    -> {su: '10 litre'}
          '2 paket biskuvi var'   -> {biskuvi: '2 paket'}
          '2 de biskuvim var'     -> {biskuvi: '2 adet'}
          '10 litreyim su'        -> {su: '10 litre'}
        """
        result = {}

        # Pattern 1: number + unit + item  e.g. '10 litre su'
        for m in re.finditer(
            r'(\d+[\.,]?\d*)\s*(' + _UNITS + r')[a-z]*\s+([a-z\u00e7\u011f\u0131\u015f\u00f6\u00fcA-Z\u00c7\u011e\u0130\u015e\u00d6\u00dc]{2,})',
            text, re.IGNORECASE | re.UNICODE
        ):
            qty, unit, item = m.group(1), m.group(2), m.group(3)
            key = _normalize_item(item)
            if key and key not in _STOP_WORDS and len(key) >= 2:
                result[key] = f"{qty} {unit}"

        # Pattern 2: item (with suffix) + number + unit  e.g. 'suyum 10 litre'
        for m in re.finditer(
            r'([a-z\u00e7\u011f\u0131\u015f\u00f6\u00fcA-Z\u00c7\u011e\u0130\u015e\u00d6\u00dc]{3,})\s+(\d+[\.,]?\d*)\s*(' + _UNITS + r')',
            text, re.IGNORECASE | re.UNICODE
        ):
            item, qty, unit = m.group(1), m.group(2), m.group(3)
            key = _normalize_item(item)
            if key and key not in _STOP_WORDS and len(key) >= 2:
                result[key] = f"{qty} {unit}"

        # Pattern 3: item + one_word + number + unit  e.g. 'su varmis 10 litre'
        for m in re.finditer(
            r'([a-z\u00e7\u011f\u0131\u015f\u00f6\u00fcA-Z\u00c7\u011e\u0130\u015e\u00d6\u00dc]{2,})\s+\w+\s+(\d+[\.,]?\d*)\s*(' + _UNITS + r')',
            text, re.IGNORECASE | re.UNICODE
        ):
            item, qty, unit = m.group(1), m.group(2), m.group(3)
            key = _normalize_item(item)
            if key and key not in _STOP_WORDS and len(key) >= 2:
                result.setdefault(key, f"{qty} {unit}")  # don't overwrite pattern1/2 results

        # Pattern 4: number + item (no unit) + var/varmis  e.g. '2 biskuvim var'
        for m in re.finditer(
            r'(\d+)\s+(?:\w+\s+)?([a-z\u00e7\u011f\u0131\u015f\u00f6\u00fcA-Z\u00c7\u011e\u0130\u015e\u00d6\u00dc]{3,})\w*\s*(?:var|varmis|varm\u0131\u015f|mevcut|bulunuyor)',
            text, re.IGNORECASE | re.UNICODE
        ):
            qty, item = m.group(1), m.group(2)
            key = _normalize_item(item)
            if key and key not in _STOP_WORDS and len(key) >= 2:
                result.setdefault(key, f"{qty} adet")

        return result

    def get_context_block(self) -> str:
        """
        Returns a short text block injected into the LLM system prompt so
        the model knows what resources the user has.
        Returns empty string if no state is recorded yet.
        """
        if not self.has_state():
            return ''

        lines = ['<KULLANICI_DURUMU>']
        inv = self._state['inventory']
        prof = self._state['profile']

        if inv:
            lines.append('Eldeki malzemeler:')
            for item, amount in inv.items():
                lines.append(f'  - {item}: {amount}')

        if prof:
            lines.append('Durum bilgisi:')
            for key, val in prof.items():
                lines.append(f'  - {key}: {val}')

        lines.append('</KULLANICI_DURUMU>')
        return '\n'.join(lines)

    def clear(self):
        """Wipe all state (inventory + profile) from memory and disk."""
        self._state = {'inventory': {}, 'profile': {}}
        self._save()
        print('(*) User state cleared.')


def deduplicate_paragraphs(text: str) -> str:
    """
    Removes near-duplicate paragraphs and sentences from LLM output (common in SLMs like Phi-3.5).
    Compares word sets of each sentence to prune redundant repeats, while preserving list items.
    """
    paragraphs = text.split('\n')
    cleaned_paragraphs = []
    seen_word_sets = []
    seen_exact = set()

    for para in paragraphs:
        stripped = para.strip()
        if not stripped:
            cleaned_paragraphs.append('')
            continue

        # For list items, only perform exact string deduplication so list items aren't discarded
        is_list_item = stripped.startswith('-') or bool(re.match(r'^\d+[\.\)]', stripped))
        if is_list_item:
            norm_item = re.sub(r'\s+', ' ', stripped.lower())
            if norm_item in seen_exact:
                continue
            seen_exact.add(norm_item)
            cleaned_paragraphs.append(stripped)
            continue

        sentences = re.split(r'(?<=[.!?])\s+', stripped)
        valid_sentences = []

        for sent in sentences:
            s_stripped = sent.strip()
            if not s_stripped:
                continue
            norm_s = re.sub(r'\s+', ' ', s_stripped.lower())
            if norm_s in seen_exact:
                continue

            words = set(re.findall(r'\w+', s_stripped.lower()))
            if len(words) >= 4:
                is_dup = False
                for prev_words in seen_word_sets:
                    intersection = len(words & prev_words)
                    smaller_len = min(len(words), len(prev_words))
                    if smaller_len > 0 and (intersection / smaller_len) >= 0.75:
                        is_dup = True
                        break
                if is_dup:
                    continue
                seen_word_sets.append(words)

            seen_exact.add(norm_s)
            valid_sentences.append(s_stripped)

        if valid_sentences:
            cleaned_paragraphs.append(' '.join(valid_sentences))

    result = '\n'.join(cleaned_paragraphs)
    return re.sub(r'\n{3,}', '\n\n', result).strip()


def fix_turkish_pdf_spacing(text: str) -> str:
    """Fixes PDF extraction artifacts where spaces are inserted before/after Turkish diacritics."""
    text = re.sub(r'(\b\w{1,8})\s+([ğşütıoöçĞŞÜTİÖÇ][a-zçğıöşü]*\b)', r'\1\2', text)
    text = text.replace("bulundu ğu", "bulunduğu")
    text = text.replace("a ğır", "ağır")
    text = text.replace("Çalı şma", "Çalışma")
    text = text.replace("Şiddet Dağılım Yanı", "Şiddet Dağılışı")
    text = text.replace("Şimdi Yanı", "")
    text = text.replace("Yanıt Formatı ve Kurallı:", "")
    text = text.replace("Mors alfabesi veya sinyal soruları:", "")
    text = text.replace("Programını kullanmaktadır:", "")
    text = text.replace("Programını kullanmaktadır", "")
    return text


def _strip_quoted_echoes(text: str) -> str:
    """
    Strips lines where the LLM repeats a bullet point inside quotes
    (e.g. '- "Kesinlikle panik yapmayın..."' right after '- Kesinlikle panik yapmayın...').
    Also removes 'extrar:' or artifact headers.
    """
    lines = text.split('\n')
    clean_lines = []
    prev_clean = ""
    for line in lines:
        stripped = line.strip()
        if stripped.lower() in ('extrar:', 'extra:', 'alinti:', 'alıntı:', 'cit:'):
            continue
        if stripped.startswith('- "') or (stripped.startswith('"') and stripped.endswith('"')):
            unquoted = stripped.lstrip('- ').strip('"').strip()
            if prev_clean and len(unquoted) >= 10:
                if unquoted[:25].lower() in prev_clean.lower() or prev_clean[:25].lower() in unquoted.lower():
                    continue
        clean_lines.append(line)
        if stripped:
            prev_clean = stripped
    return '\n'.join(clean_lines)


def _strip_form_hallucinations(text: str) -> str:
    """
    Phi-3.5-mini sometimes generates 'X: Evet', 'X: Hayır', 'X: Kes' lines
    that mimic a questionnaire/checklist form — these are hallucinations that
    appear when the model sees structured context.  Strip them.
    """
    lines = text.split('\n')
    clean_lines = []
    _FORM_SUFFIXES = (': Evet', ': Hayır', ': Kes', ': hayır', ': evet', ': kes')
    _FORM_KEYWORDS = ('süzün:', 'yapi lan', 'yapılan', 'programini', 'programını')
    for line in lines:
        stripped = line.strip()
        if any(stripped.endswith(s) for s in _FORM_SUFFIXES):
            continue
        if any(kw in stripped.lower() for kw in _FORM_KEYWORDS):
            continue
        clean_lines.append(line)
    return '\n'.join(clean_lines)


def clean_llm_response(text: str, user_question: str = "") -> str:
    """
    Module-level helper used by generator.py.
    Removes phi-3.5-mini artifact annotations, markdown bold asterisks,
    fixes PDF diacritic spacing, strips quoted echoes, nonsense hallucinations,
    mangled Morse notations, and deduplicates repetitive paragraphs.
    Applied AFTER streaming completes, before storing in chat history.
    """
    for pattern in _ARTIFACT_PATTERNS:
        text = pattern.sub('', text)
    text = text.replace('**', '')
    text = fix_turkish_pdf_spacing(text)
    text = _strip_quoted_echoes(text)
    text = _strip_form_hallucinations(text)

    # Concatenated Turkish word fixes
    word_fixes = {
        r'kadartutunduğunuz': 'kadar tutunduğunuz',
        r'yanınaçökün': 'yanına çökün',
        r'ışıkçakması': 'ışık çakması',
        r'mors alfabe,': 'Mors alfabesi,',
        r'mors alfabe için': 'Mors alfabesi için',
        r'sınır listesi': 'sinyal listesi',
    }
    for old_w, new_w in word_fixes.items():
        text = re.sub(old_w, new_w, text, flags=re.IGNORECASE)

    # Nonsense hallucination filtering
    nonsense_patterns = [
        r'yalanları söyler',
        r'kötülük için yalanları',
        r'Hazırlık durumunu söyledikçe',
        r'sıkıca bir durumda kalın',
        r'Amatörler, bu m',
    ]

    lines = text.split('\n')
    clean_lines = []
    q_lower = user_question.lower() if user_question else ""
    is_mors = any(k in q_lower for k in ("mors", "sos", "sinyal", "telsiz"))

    for line in lines:
        stripped = line.strip()
        # Skip hallucinated nonsense lines
        if any(re.search(p, stripped, re.IGNORECASE) for p in nonsense_patterns):
            continue
        # Skip trailing SOS ritmi lines on non-Morse queries
        if not is_mors and re.search(r'\(.*SOS.*3 kısa.*\)', stripped, re.IGNORECASE):
            continue
        
        # Correct mangled Morse notation if this is a Morse query
        if is_mors:
            stripped = re.sub(r'^[-\s–—]*S\s*\(.*?\)', '- S = . . . (3 Kısa Sinyal)', stripped, flags=re.IGNORECASE)
            stripped = re.sub(r'^[-\s–—]*O\s*\(.*?\)', '- O = - - - (3 Uzun Sinyal)', stripped, flags=re.IGNORECASE)
            stripped = re.sub(r'^[-\s–—]*M\s*\(.*?\)', '- M = - - (2 Uzun Sinyal)', stripped, flags=re.IGNORECASE)
            stripped = re.sub(r'^[-\s–—]*R\s*\(.*?\)', '- R = . - . (Kısa Uzun Kısa)', stripped, flags=re.IGNORECASE)
            stripped = re.sub(r'^[-\s–—]*SOS\s*\(.*?\)', '- SOS = . . .  - - -  . . . (3 Kısa, 3 Uzun, 3 Kısa Sinyal)', stripped, flags=re.IGNORECASE)

        clean_lines.append(stripped)

    text = '\n'.join(clean_lines)
    text = deduplicate_paragraphs(text)
    return text.strip()
