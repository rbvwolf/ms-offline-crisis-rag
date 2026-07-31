import os
import re

import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from core.config import MAX_DISTANCE, MAX_CONTEXT_CHARS, MIN_USEFUL_WORDS

# Maximum allowed distance spread from the best chunk.
# E.g. if best chunk is 0.78, no chunk worse than 0.78+0.10 = 0.88 is used.
_MAX_RELATIVE_DISTANCE = 0.10


def clean_chunk_text(text: str) -> str:
    """
    Strips PDF artifacts from a chunk before it is sent to the LLM:
    - Hyphenated line breaks (e.g. 'ha-\\nreket' -> 'hareket')
    - Leading page numbers like '35\\n' or '2 / 50\\n'
    - Weird PDF bullet points (Ø, ● etc.)
    - Collapsed whitespace
    """
    text = re.sub(r'-\n\s*', '', text)
    text = re.sub(r'^\s*\d+\s*\n', '', text)
    text = text.replace('Ø', '-')
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

        # Absolute gate
        if distance > MAX_DISTANCE:
            continue

        # Relative gate: skip chunks that are much further than the best hit
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

        # Citation label
        if source_file:
            name = os.path.splitext(source_file)[0]
            if len(name) > 45:
                name = name[:45] + "..."
            label = f"{name} (s.{page_number + 1})" if page_number >= 0 else name
            if label not in citations:
                citations.append(label)

    return "\n\n".join(chunks), citations
