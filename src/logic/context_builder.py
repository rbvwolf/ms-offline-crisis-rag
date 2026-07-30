"""
context_builder.py — Chunk cleaning, deduplication, and context assembly.

Extracted from generator.py to keep that file focused on LLM orchestration.

Public API:
    context_text, citations = build_context(retrieved_docs)
"""

import os
import re

# We rely on config constants; import path is set by generator.py before this module loads.
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from core.config import MAX_DISTANCE, MAX_CONTEXT_CHARS, MIN_USEFUL_WORDS


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
      1. Distance threshold (MAX_DISTANCE)
      2. Empty / unparseable chunks
      3. Minimum useful word count (MIN_USEFUL_WORDS)
      4. Fingerprint-based deduplication (first 80 chars)
      5. MAX_CONTEXT_CHARS hard cap
    """
    chunks = []
    citations = []
    seen_fingerprints: set = set()
    total_chars = 0

    for row in retrieved_docs:
        text, distance = row[0], row[1]
        source_file = row[2] if len(row) > 2 else None
        page_number = row[3] if len(row) > 3 else -1

        if distance > MAX_DISTANCE:
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
