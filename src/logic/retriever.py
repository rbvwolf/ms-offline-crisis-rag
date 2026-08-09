"""
retriever.py — Hybrid search (Vector + FTS5 BM25) with Reciprocal Rank Fusion.

Architecture:
  open_db()          — open persistent connection, load sqlite-vec, ensure tables exist
  retrieve_content() — embed query → vector KNN search + FTS5 BM25 search → RRF fusion
                       → top-k results enriched with source metadata

Why Hybrid?
  - Vector search captures *semantic* similarity (great for paraphrases, synonyms).
  - FTS5 BM25 captures *exact keyword* matches (great for Morse, PMR, chemical names).
  - RRF combines both rank lists without needing score normalisation.
"""

import os
import re
import sys
import sqlite3
import sqlite_vec
from langchain_huggingface import HuggingFaceEmbeddings

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from core.config import (
    EMBEDDING_MODEL, DB_PATH, MAX_DISTANCE,
    VECTOR_K, FTS_K, RRF_K, TOP_K,
)


def _prepare_fts_query(raw_query: str) -> tuple[str, str]:
    """
    Converts a raw query into two FTS5 MATCH expressions: AND and OR versions.

    AND version:  all significant tokens must appear in the document.
                  High precision — avoids matching unrelated docs on a single word.
    OR version:   any token can match, scored by BM25.
                  High recall — fallback when AND yields nothing.

    The FTS5 table uses 'unicode61 remove_diacritics 2' tokenizer, which
    automatically normalises diacritics on both stored text and queries.
    We do NOT manually normalise Turkish chars — the tokenizer handles it.

    Returns (and_query, or_query).
    """
    text = raw_query.lower()
    text = re.sub(r'["\'\-\*\(\)\^]', ' ', text)
    text = re.sub(r'[^\w\s]', ' ', text, flags=re.UNICODE)

    _STOPWORDS = {
        've', 'veya', 'bir', 'bu', 'da', 'de', 'den', 'dan',
        'ile', 'icin', 'mi', 'mu', 'nasil', 'neden', 'nerede',
        'ama', 'fakat', 'ki', 'cok', 'az', 'daha',
    }
    tokens = [t for t in text.split() if len(t) >= 2 and t not in _STOPWORDS]

    if not tokens:
        return '', ''

    # AND: all tokens must appear (high precision)
    and_query = ' '.join(f'"{tok}"' for tok in tokens)
    # OR: any token can appear (high recall fallback)
    or_query = ' OR '.join(f'"{tok}"' for tok in tokens)
    return and_query, or_query


# ---------------------------------------------------------------------------
# DB connection
# ---------------------------------------------------------------------------

def open_db():
    """
    Opens and returns a configured DB connection for the session.
    Loads the sqlite-vec extension and ensures all required tables exist
    (safe migration: CREATE IF NOT EXISTS never touches existing data).
    Call once at startup; pass the connection to retrieve_content().
    """
    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)

    # Chunks metadata (citation source, page, source type for priority)
    db.execute("""
        CREATE TABLE IF NOT EXISTS chunks_metadata (
            chunk_id INTEGER PRIMARY KEY,
            source_file TEXT,
            page_number INTEGER,
            source_type TEXT DEFAULT 'pdf'
        )
    """)

    # Migration: add source_type column to existing databases that lack it
    try:
        db.execute("ALTER TABLE chunks_metadata ADD COLUMN source_type TEXT DEFAULT 'pdf'")
        db.commit()
        print("(*) Migrated chunks_metadata: added source_type column")
    except Exception:
        pass  # Column already exists

    # FTS5 virtual table
    db.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            text,
            chunk_id UNINDEXED,
            tokenize = 'unicode61 remove_diacritics 2'
        )
    """)

    # Back-fill FTS5 for any chunks that were ingested without it
    db.execute("""
        INSERT INTO chunks_fts(text, chunk_id)
        SELECT sv.text, sv.chunk_id
        FROM survival_vectors sv
        WHERE NOT EXISTS (
            SELECT 1 FROM chunks_fts WHERE chunk_id = sv.chunk_id
        )
    """)

    # Back-fill chunks_metadata for any chunks ingested before this feature.
    # Gives them source_type='pdf' and NULL source_file as safe defaults.
    db.execute("""
        INSERT OR IGNORE INTO chunks_metadata(chunk_id, source_file, page_number, source_type)
        SELECT sv.chunk_id, NULL, -1, 'pdf'
        FROM survival_vectors sv
        WHERE NOT EXISTS (
            SELECT 1 FROM chunks_metadata cm WHERE cm.chunk_id = sv.chunk_id
        )
    """)
    db.commit()

    print(f"(*) Connected to vector database: {os.path.basename(DB_PATH)}")
    return db


# ---------------------------------------------------------------------------
# Hybrid retrieval
# ---------------------------------------------------------------------------

def _vector_search(query_vector: list, db, k: int) -> list[tuple[int, float]]:
    """
    KNN vector search via sqlite-vec.
    Returns [(chunk_id, distance), ...] sorted by distance (ascending = closer).
    """
    serialized = sqlite_vec.serialize_float32(query_vector)
    cursor = db.cursor()
    cursor.execute("""
        SELECT chunk_id, distance
        FROM survival_vectors
        WHERE embedding MATCH ? AND k = ?
        ORDER BY distance
    """, (serialized, k))
    return cursor.fetchall()


def _fts_search(fts_query: str, db, k: int) -> list[tuple[int, float]]:
    """
    FTS5 BM25 keyword search.
    Returns [(chunk_id, bm25_score), ...] sorted by relevance.
    Returns [] if the query is empty or invalid.
    """
    if not fts_query:
        return []
    try:
        cursor = db.cursor()
        cursor.execute("""
            SELECT chunk_id, bm25(chunks_fts) AS score
            FROM chunks_fts
            WHERE chunks_fts MATCH ?
            ORDER BY score
            LIMIT ?
        """, (fts_query, k))
        return cursor.fetchall()
    except sqlite3.OperationalError as e:
        print(f"[-] FTS5 search failed (query={fts_query!r}): {e}")
        return []


_MIN_FTS_AND_RESULTS = 2  # minimum AND hits before falling back to OR


def _smart_fts_search(raw_query: str, db, k: int) -> list[tuple[int, float]]:
    """
    AND-first FTS search with OR fallback.

    Strategy:
      1. Try the AND query (all tokens must appear in a document).
         This gives high-precision results — e.g. 'mors alfabesi' only
         matches docs containing BOTH words, not radio-amateur docs that
         only contain 'alfabesi'.
      2. If AND yields fewer than _MIN_FTS_AND_RESULTS results, fall back
         to OR (any token matches, scored by BM25). Recall is higher but
         the RRF fusion and distance gate filter out irrelevant docs.
    """
    and_q, or_q = _prepare_fts_query(raw_query)
    if not and_q:
        return []

    and_results = _fts_search(and_q, db, k)
    if len(and_results) >= _MIN_FTS_AND_RESULTS:
        print(f"(*) FTS5 AND search: query={and_q!r} -> {len(and_results)} results")
        return and_results

    # Fall back to OR
    or_results = _fts_search(or_q, db, k)
    strategy = 'AND->OR fallback' if and_results else 'OR (AND=0)'
    print(f"(*) FTS5 {strategy}: query={or_q!r} -> {len(or_results)} results")
    return or_results


import threading

# Thread lock for SQLite concurrent access protection across FastAPI worker threads
_db_lock = threading.Lock()


def _reciprocal_rank_fusion(
    vector_results: list[tuple[int, float]],
    fts_results: list[tuple[int, float]],
    rrf_k: int = RRF_K,
) -> list[tuple[int, float]]:
    """
    Reciprocal Rank Fusion (RRF).

    Each result list contributes  1 / (rrf_k + rank)  to a shared score.
    Ranks start at 1.  Items appearing in both lists get the sum of both
    contributions — naturally boosting agreement between the two signals.

    Returns [(chunk_id, rrf_score), ...] sorted descending (higher = better).
    """
    scores: dict[int, float] = {}

    for rank, (chunk_id, _) in enumerate(vector_results, start=1):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (rrf_k + rank)

    for rank, (chunk_id, _) in enumerate(fts_results, start=1):
        scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (rrf_k + rank)

    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


# Absolute vector distance cap for FTS-boosted chunks.
# Even with a keyword match, a chunk that is this far semantically is noise.
_FTS_HARD_VECTOR_CAP = 1.10

# Max chunks allowed from a single source file.
# Prevents one file (e.g. mors alphabet table) from flooding all TOP_K slots.
_MAX_CHUNKS_PER_FILE = 2


def _rrf_to_dist(rrf_score: float, max_dist: float = 0.85) -> float:
    """
    Maps an RRF score (higher = better) to a synthetic distance (lower = better).

    Scale factor 10.0 maps typical RRF scores to the [0.35, 0.84] distance range:
      rrf = 0.033 (rank-1 both lists) → dist ≈ 0.52  (strong match)
      rrf = 0.016 (rank-1 one list)   → dist ≈ 0.69  (decent match)
      rrf = 0.008 (rank-5 one list)   → dist ≈ 0.77  (weak match)
    """
    synthetic = max_dist - rrf_score * 10.0
    return round(max(0.35, min(max_dist - 0.02, synthetic)), 4)


def _enrich_results(fused: list, vector_dist_map: dict, fts_results: list, db: sqlite3.Connection, top_k: int, max_distance: float) -> list:
    """
    Fetches the actual text and metadata for the top RRF results.

    Distance policy:
      - Chunks in vector_dist_map: use real L2 distance.
      - Chunks beyond max_distance but in fts_chunk_ids: use RRF-scaled synthetic
        distance (_rrf_to_dist) instead of a hard clamp to avoid all showing 0.80.
      - Chunks with actual vector distance > _FTS_HARD_VECTOR_CAP: always skipped,
        even with an FTS keyword match (they are semantically unrelated noise).
      - Chunks only in FTS (not in vector results at all): use _rrf_to_dist;
        skip if synthetic dist >= max_distance.

    Source diversity:
      - _MAX_CHUNKS_PER_FILE caps how many chunks from the same file can appear.
        This prevents one file (e.g. a full alphabet table) from filling all slots.

    Returns [(text, distance, source_file, page_number, source_type), ...].
    """
    cursor = db.cursor()
    results = []
    fts_chunk_ids = {cid for cid, _ in fts_results}

    for chunk_id, rrf_score in fused:
        if chunk_id in vector_dist_map:
            vec_dist = vector_dist_map[chunk_id]

            # Hard cap: too far even for FTS keyword rescue
            if vec_dist > _FTS_HARD_VECTOR_CAP:
                continue

            # Beyond soft max_distance — only keep if FTS also matched
            if vec_dist > max_distance:
                if chunk_id not in fts_chunk_ids:
                    continue
                # Use RRF-based synthetic distance instead of clamping to 0.80
                vec_dist = _rrf_to_dist(rrf_score, max_distance)
        else:
            # FTS-only chunk (not in top vector candidates)
            if chunk_id not in fts_chunk_ids:
                continue
            vec_dist = _rrf_to_dist(rrf_score, max_distance)
            if vec_dist >= max_distance:
                continue  # RRF score too weak to trust

        try:
            cursor.execute("SELECT text FROM survival_vectors WHERE chunk_id = ?", (chunk_id,))
            row = cursor.fetchone()
            if not row or not row[0]:
                continue
            text = row[0]

            cursor.execute(
                "SELECT source_file, page_number, source_type FROM chunks_metadata WHERE chunk_id = ?",
                (chunk_id,)
            )
            meta = cursor.fetchone()
            source_file = meta[0] if meta else None
            page_number  = meta[1] if meta else -1
            source_type  = (meta[2] if meta else None) or 'pdf'

            results.append((text, vec_dist, source_file, page_number, source_type))
        except Exception as e:
            print(f"[-] Row enrichment warning for chunk_id={chunk_id}: {e}")
            continue

    # --- Source diversity: cap chunks per source file ---
    file_counts: dict[str, int] = {}
    filtered: list = []
    # Sort by distance ascending so we keep the best chunk from each file first
    results.sort(key=lambda r: r[1])
    for r in results:
        fname = r[2] or '__unknown__'
        if file_counts.get(fname, 0) < _MAX_CHUNKS_PER_FILE:
            filtered.append(r)
            file_counts[fname] = file_counts.get(fname, 0) + 1
    results = filtered

    # Separate TXT and PDF candidates
    txt_results = [r for r in results if r[4] == 'txt']
    pdf_results = [r for r in results if r[4] == 'pdf']

    txt_results.sort(key=lambda r: r[1])
    pdf_results.sort(key=lambda r: r[1])

    final_results = []
    # 1. Take curated TXT chunks first (up to top_k slots)
    final_results.extend(txt_results[:top_k])

    # 2. Only fill remaining slots with PDF chunks if we need more context
    if len(final_results) < top_k:
        remaining = top_k - len(final_results)
        final_results.extend(pdf_results[:remaining])

    return final_results


def retrieve_content(
    query: str,
    embeddings_model,
    db,
    k: int = TOP_K,
    query_vector: list | None = None,
) -> list[tuple[str, float, str | None, int]]:
    """
    Hybrid retrieval: Vector KNN + FTS5 BM25 → Reciprocal Rank Fusion → top-k.
    Thread-safe execution using _db_lock.
    """
    with _db_lock:
        print(f"(*) Analyzing user query: {query}")

        # --- 1. Embed query (or reuse cached vector) ---
        if query_vector is None:
            query_vector = embeddings_model.embed_query(query)

        # --- 2. Vector search (semantic) ---
        print(f"(*) Vector search: top {VECTOR_K} candidates")
        vec_results = _vector_search(query_vector, db, VECTOR_K)
        # Build distance map for quality gate later
        vector_dist_map: dict[int, float] = {cid: dist for cid, dist in vec_results}

        # --- 3. FTS5 BM25 search (keyword, AND-first with OR fallback) ---
        fts_results = _smart_fts_search(query, db, FTS_K)

        if not fts_results:
            print("(*) FTS5: no keyword matches -- using vector only")

        # --- 4. Reciprocal Rank Fusion ---
        fused = _reciprocal_rank_fusion(vec_results, fts_results, RRF_K)
        print(f"(*) RRF fused {len(fused)} unique candidates -> selecting top {k}")

        # --- 5. Enrich with text + metadata, apply distance gate ---
        results = _enrich_results(fused, vector_dist_map, fts_results, db, k, MAX_DISTANCE)
        print(f"(*) Final results after distance gate: {len(results)}")

        # Debug: show top results with source_type
        for row in results:
            text, dist, src, pg, *rest = row
            st = rest[0] if rest else 'pdf'
            label = f"{src}:p{pg}" if src else "?"
            snippet = text[:60].replace('\n', ' ')
            print(f"    dist={dist:.4f} type={st} [{label}] | {snippet!r}")

        return results


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    test_queries = [
        "Deprem anında ne yapmalıyım?",
        "mors alfabesi SOS sinyali",
        "su arıtma içme",
    ]

    print("(*) Loading embedding model for test...")
    test_embeddings = HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        model_kwargs={'local_files_only': True},
        encode_kwargs={'normalize_embeddings': True}
    )

    test_db = open_db()
    try:
        for q in test_queries:
            print(f"\n{'='*60}\nQuery: {q}\n{'='*60}")
            docs = retrieve_content(q, test_embeddings, test_db)
            for i, (text, dist, src, pg) in enumerate(docs, 1):
                src_label = f"{src} (s.{pg})" if src else "Bilinmeyen"
                print(f"\n  [{i}] dist={dist:.4f} | {src_label}")
                safe_text = text[:200].encode('ascii', 'replace').decode('ascii')
                print(f"  {safe_text}")
    finally:
        test_db.close()