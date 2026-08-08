import os
import re

import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from core.config import MAX_DISTANCE, MAX_CONTEXT_CHARS, MIN_USEFUL_WORDS

# Maximum allowed distance spread from the best chunk.
# E.g. if best chunk is 0.78, no chunk worse than 0.78+0.10 = 0.88 is used.
_MAX_RELATIVE_DISTANCE = 0.12  # strict relative distance filter to prevent noise chunks


def clean_chunk_text(text: str) -> str:
    """
    Strips PDF artifacts from a chunk before it is sent to the LLM:
    - Hyphenated line breaks (e.g. 'ha-\nreket' -> 'hareket')
    - PDF font extraction spaces around Turkish diacritics ('a ğır' -> 'ağır', 'bulundu ğu' -> 'bulunduğu')
    - Leading page numbers like '35\n' or '2 / 50\n'
    - Weird PDF bullet points (Ø, ● etc.)
    - Collapsed whitespace
    """
    text = re.sub(r'-\n\s*', '', text)
    text = re.sub(r'^\s*\d+\s*\n', '', text)
    text = text.replace('Ø', '-')

    # Fix PDF font extraction spaces before/after Turkish diacritics
    text = re.sub(r'(\b\w{1,8})\s+([ğşütıoöçĞŞÜTİÖÇ][a-zçğıöşü]*\b)', r'\1\2', text)
    text = text.replace("bulundu ğu", "bulunduğu")
    text = text.replace("a ğır", "ağır")
    text = text.replace("çalı şma", "çalışma")
    text = text.replace("Çalı şma", "Çalışma")
    text = text.replace("ba şlığı", "başlığı")
    text = text.replace("Şiddet Dağılım Yanı", "Şiddet Dağılışı")

    text = re.sub(r'\n+', ' ', text)
    text = re.sub(r' {2,}', ' ', text)
    return text.strip()


def build_context(retrieved_docs: list) -> tuple[str, list]:
    """
    Takes raw retrieval results and produces:
      - context_text: a clean, capped string ready to be injected into the prompt
      - citations: unique source labels for display after the answer

    Filters applied in order:
      1. Absolute distance threshold (MAX_DISTANCE)
      2. Relative distance: no chunk more than _MAX_RELATIVE_DISTANCE worse than best
      3. Empty / unparseable chunks
      4. Minimum useful word count (MIN_USEFUL_WORDS)
      5. Fingerprint-based deduplication (first 80 chars)
      6. MAX_CONTEXT_CHARS hard cap
    """
    if not retrieved_docs:
        return "", []

    # Determine best (lowest) distance to set relative filter
    best_distance = min(row[1] for row in retrieved_docs)
    relative_cap = best_distance + _MAX_RELATIVE_DISTANCE

    chunks = []
    citations = []
    seen_fingerprints: set = set()
    total_chars = 0

    for row in retrieved_docs:
        text, distance = row[0], row[1]
        source_file = row[2] if len(row) > 2 else None
        page_number = row[3] if len(row) > 3 else -1
        source_type = row[4] if len(row) > 4 else 'pdf'

        # Absolute gate
        if distance > MAX_DISTANCE:
            continue

        # Relative gate: skip chunks that are much further than the best hit
        # We exempt TXT chunks from this gate because they are hand-curated
        # priority knowledge and should not be dropped just because a PDF scored better.
        if source_type != 'txt' and distance > relative_cap:
            continue


        cleaned = clean_chunk_text(text)
        if not cleaned:
            continue

        # Skip headers / page-number fragments
        if len(cleaned.split()) < MIN_USEFUL_WORDS:
            continue

        # Deduplication by text fingerprint
        fingerprint = cleaned[:80].lower()
        if fingerprint in seen_fingerprints:
            continue
        seen_fingerprints.add(fingerprint)

        # Hard character cap
        if total_chars + len(cleaned) > MAX_CONTEXT_CHARS:
            remaining = MAX_CONTEXT_CHARS - total_chars
            if remaining > 100:
                chunks.append(cleaned[:remaining])
            break

        chunks.append(cleaned)
        total_chars += len(cleaned)

        # Citation label — always shown for both TXT and PDF sources
        if source_file:
            name = os.path.splitext(source_file)[0]
            if len(name) > 45:
                name = name[:45] + "..."
            if source_type == 'txt':
                label = f"[TXT] {name}"
            elif page_number >= 0:
                label = f"[PDF] {name} (s.{page_number + 1})"
            else:
                label = f"[PDF] {name}"
            if label not in citations:
                citations.append(label)
        elif source_type == 'pdf':
            # PDF chunk without a recorded filename — still note it as a PDF source
            label = "[PDF] Bilinmeyen kaynak"
            if label not in citations:
                citations.append(label)

    return "\n\n".join(chunks), citations
