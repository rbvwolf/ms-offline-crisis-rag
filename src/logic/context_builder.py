import os
import re

import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from core.config import MAX_DISTANCE, MAX_CONTEXT_CHARS, MIN_USEFUL_WORDS

# Maximum allowed distance spread from the best chunk.
_MAX_RELATIVE_DISTANCE = 0.25  # allows complementary context chunks into prompt


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

        # Relative gate: skip chunks that are further than relative_cap
        if distance > relative_cap:
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

        # Citation metadata object: contains source, page, type, distance, and text
        src_name = source_file or "rehber.txt"
        name = os.path.splitext(src_name)[0]
        if len(name) > 45:
            name = name[:45] + "..."
        
        if source_type == 'txt':
            label = f"[TXT] {name}"
        elif page_number >= 0:
            label = f"[PDF] {name} (s.{page_number + 1})"
        else:
            label = f"[PDF] {name}"

        # Avoid duplicate citations for the exact same source & page
        if not any(c['source'] == src_name and c.get('page') == page_number for c in citations):
            citations.append({
                "source": src_name,
                "label": label,
                "page": page_number + 1 if page_number >= 0 else None,
                "source_type": source_type,
                "text": cleaned,
                "distance": round(float(distance), 4)
            })

    return "\n\n".join(chunks), citations
