"""
txt_processor.py — Ingests curated .txt knowledge files into the vector DB.

TXT files are treated as HIGHER PRIORITY than PDF chunks because they contain
hand-curated, project-specific knowledge written for this assistant.  Priority
is implemented by tagging chunks with source_type='txt' in chunks_metadata;
the retriever then applies a distance boost to surface TXT chunks first.

Usage:
    python src/ingestion/txt_processor.py

Conventions:
    - Source directory  : data/raw_txts/
    - Chunk size        : 900 chars (middle of the requested 800-1000 range)
    - Chunk overlap     : 100 chars (same as PDF processor)
    - page_number       : stored as -1 (TXT files have no pages)
    - Already-processed files are tracked in the processed_files table and
      skipped on subsequent runs (same as PDF processor).
"""

import os
import re
import sys
import sqlite3
import sqlite_vec
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from core.config import EMBEDDING_MODEL, DB_PATH, RAW_TXT_DIR

# TXT-specific chunking settings (user requested 800-1000 chars)
TXT_CHUNK_SIZE    = 900   # chars per chunk
TXT_CHUNK_OVERLAP = 100   # chars of overlap
TXT_MIN_CHUNK_LEN = 60    # shorter chunks are discarded

SOURCE_TYPE = 'txt'       # tag written to chunks_metadata.source_type


# ---------------------------------------------------------------------------
# Text cleaning
# ---------------------------------------------------------------------------

def _clean_txt(text: str) -> str:
    """
    Light cleanup for raw .txt files:
    - Normalise Windows line endings
    - Collapse runs of 3+ blank lines to two (keep paragraph structure)
    - Strip leading/trailing whitespace per line (remove accidental indentation)
    - Remove zero-width or exotic Unicode spaces
    """
    # Normalise newlines
    text = text.replace('\r\n', '\n').replace('\r', '\n')

    # Remove zero-width spaces and soft hyphens
    text = re.sub(r'[\u00ad\u200b\u200c\u200d\ufeff]', '', text)

    # Strip trailing whitespace from every line
    lines = [line.rstrip() for line in text.split('\n')]
    text = '\n'.join(lines)

    # Collapse 3+ consecutive blank lines into exactly two
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


def _is_garbage_chunk(text: str) -> bool:
    """
    Returns True if the chunk is too short or too noisy to be useful.
    TXT files are generally cleaner than PDFs, so the filter is lighter.
    """
    stripped = text.strip()

    if len(stripped) < TXT_MIN_CHUNK_LEN:
        return True

    # Reject if over 60 % of characters are non-alphanumeric
    alphanum_ratio = sum(c.isalnum() or c.isspace() for c in stripped) / max(len(stripped), 1)
    if alphanum_ratio < 0.40:
        return True

    return False


# ---------------------------------------------------------------------------
# Main ingestion function
# ---------------------------------------------------------------------------

def ingest_txts_to_sqlite():
    if not os.path.isdir(RAW_TXT_DIR):
        print(f"(!) TXT directory not found: {RAW_TXT_DIR}")
        print("    Create the directory and place .txt files inside it.")
        return

    print("(*) Connecting to DB and checking processed files")
    db = sqlite3.connect(DB_PATH)

    # Ensure required tables exist (idempotent — safe to call multiple times)
    db.execute("""
        CREATE TABLE IF NOT EXISTS processed_files (
            filename TEXT PRIMARY KEY,
            processed_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS chunks_metadata (
            chunk_id INTEGER PRIMARY KEY,
            source_file TEXT,
            page_number INTEGER,
            source_type TEXT DEFAULT 'pdf'
        )
    """)

    # Migration: add source_type column if this is an older DB
    try:
        db.execute("ALTER TABLE chunks_metadata ADD COLUMN source_type TEXT DEFAULT 'pdf'")
        db.commit()
        print("(*) Migrated chunks_metadata: added source_type column")
    except Exception:
        pass  # Column already exists — fine

    db.commit()

    cursor = db.cursor()
    cursor.execute("SELECT filename FROM processed_files")
    processed_set = set(row[0] for row in cursor.fetchall())

    # Scan for new .txt files
    txt_files = [f for f in os.listdir(RAW_TXT_DIR) if f.lower().endswith('.txt')]
    if not txt_files:
        print(f"(!) No .txt files found in {RAW_TXT_DIR}")
        db.close()
        return

    new_filenames = []
    all_chunks = []  # list of (text, source_file)

    print(f"(*) Scanning {RAW_TXT_DIR}")
    for filename in txt_files:
        if filename in processed_set:
            print(f"[-] Skipping (already processed): {filename}")
            continue

        file_path = os.path.join(RAW_TXT_DIR, filename)
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                raw = f.read()
        except UnicodeDecodeError:
            try:
                with open(file_path, 'r', encoding='cp1254') as f:
                    raw = f.read()
                print(f"    (!) {filename}: UTF-8 failed, read as cp1254")
            except Exception as e:
                print(f"[-] Cannot read {filename}: {e}")
                continue

        cleaned = _clean_txt(raw)
        if len(cleaned) < TXT_MIN_CHUNK_LEN:
            print(f"[-] Skipping nearly empty file: {filename}")
            continue

        print(f"[+] Found new file: {filename} ({len(cleaned)} chars)")
        new_filenames.append(filename)

        # Split into chunks
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=TXT_CHUNK_SIZE,
            chunk_overlap=TXT_CHUNK_OVERLAP,
            separators=["\n\n", "\n- ", "\n* ", "\n", ". ", "! ", "? ", " ", ""],
            is_separator_regex=False,
        )
        raw_chunks = splitter.split_text(cleaned)

        for chunk_text in raw_chunks:
            if not _is_garbage_chunk(chunk_text):
                all_chunks.append((chunk_text, filename))
            # else: silently discard garbage

    if not all_chunks:
        print("(!) No new TXT content to ingest. Database is up to date.")
        db.close()
        return

    print(f"(*) {len(all_chunks)} clean chunks from {len(new_filenames)} file(s). Embedding...")

    # Load embedding model
    print(f"(*) Loading embedding model: {EMBEDDING_MODEL}")
    embeddings_model = HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        encode_kwargs={'normalize_embeddings': True}
    )

    texts = [t for t, _ in all_chunks]
    vectors = embeddings_model.embed_documents(texts)

    # Prepare vector DB
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)

    db.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS survival_vectors USING vec0(
            chunk_id INTEGER PRIMARY KEY,
            text TEXT,
            embedding float[384]
        );
    """)

    db.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            text,
            chunk_id UNINDEXED,
            tokenize = 'unicode61 remove_diacritics 2'
        );
    """)

    print("(*) Saving TXT chunks to database...")
    cursor = db.cursor()
    for (chunk_text, source_file), vector in zip(all_chunks, vectors):
        cursor.execute(
            "INSERT INTO survival_vectors(text, embedding) VALUES (?, ?)",
            (chunk_text, sqlite_vec.serialize_float32(vector))
        )
        chunk_id = cursor.lastrowid

        cursor.execute(
            "INSERT INTO chunks_metadata(chunk_id, source_file, page_number, source_type) VALUES (?, ?, ?, ?)",
            (chunk_id, source_file, -1, SOURCE_TYPE)
        )

        cursor.execute(
            "INSERT INTO chunks_fts(text, chunk_id) VALUES (?, ?)",
            (chunk_text, chunk_id)
        )

    for filename in new_filenames:
        cursor.execute("INSERT OR REPLACE INTO processed_files (filename) VALUES (?)", (filename,))

    db.commit()
    db.close()

    print(f"(*) Done. {len(all_chunks)} TXT chunks ingested as source_type='txt' (priority boosted).")
    print(f"    DB: {DB_PATH}")


if __name__ == "__main__":
    ingest_txts_to_sqlite()
