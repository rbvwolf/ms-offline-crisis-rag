import os
import re
import sys
import sqlite3
import sqlite_vec
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings

# Add src/ to path so we can import from core.config
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from core.config import (
    EMBEDDING_MODEL, DB_PATH, RAW_PDF_DIR,
    MIN_CHUNK_LENGTH, CHUNK_SIZE, CHUNK_OVERLAP
)


def _is_garbage_chunk(text):
    """
    Returns True if the chunk is a header, footer, page number, or otherwise
    too noisy to be useful for retrieval.
    """
    stripped = text.strip()

    # Too short to carry real information
    if len(stripped) < MIN_CHUNK_LENGTH:
        return True

    # Matches "X / Y" or "X/Y" page number patterns anywhere in the chunk
    if re.search(r'\b\d+\s*/\s*\d+\b', stripped):
        return True

    # More than 60% of characters are non-alphanumeric (encoding artifacts, table lines)
    alphanum_ratio = sum(c.isalnum() or c.isspace() for c in stripped) / max(len(stripped), 1)
    if alphanum_ratio < 0.40:
        return True

    return False


def ingest_pdfs_to_sqlite():
    print("(*) Connecting to DB and checking processed files")
    db = sqlite3.connect(DB_PATH)

    # Track which files have already been processed
    db.execute("""
        CREATE TABLE IF NOT EXISTS processed_files (
            filename TEXT PRIMARY KEY,
            processed_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Stores source file and page number for each chunk (for citations)
    db.execute("""
        CREATE TABLE IF NOT EXISTS chunks_metadata (
            chunk_id INTEGER PRIMARY KEY,
            source_file TEXT,
            page_number INTEGER
        )
    """)
    db.commit()

    cursor = db.cursor()
    cursor.execute("SELECT filename FROM processed_files")
    processed_set = set(row[0] for row in cursor.fetchall())

    new_documents = []
    new_filenames = []

    print("(*) Scanning raw_pdfs folder")
    for filename in os.listdir(RAW_PDF_DIR):
        if filename.endswith(".pdf"):
            if filename in processed_set:
                print(f"[-] Skipping (Already processed): {filename}")
            else:
                file_path = os.path.join(RAW_PDF_DIR, filename)
                try:
                    print(f"[+] Found new file. Reading: {filename}")
                    loader = PyPDFLoader(file_path)
                    pages = loader.load()
                    new_documents.extend(pages)
                    new_filenames.append(filename)
                except Exception as e:
                    print(f"[-] Skipping corrupt/unreadable file: {filename} | Error: {e}")

    if not new_documents:
        print("(!!!) No new PDF files found. Database is up to date.")
        db.close()
        return

    print(f"(*) Found {len(new_documents)} pages of document. Chunking...")

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
    )
    raw_chunks = text_splitter.split_documents(new_documents)
    print(f"(*) Documents split into {len(raw_chunks)} raw pieces.")

    # Filter garbage chunks and preserve source metadata from LangChain Document objects
    clean_chunks = []  # list of (text, source_file, page_number)
    skipped = 0
    for chunk in raw_chunks:
        text = chunk.page_content
        if _is_garbage_chunk(text):
            skipped += 1
        else:
            source_file = os.path.basename(chunk.metadata.get('source', 'Bilinmeyen'))
            page_number = chunk.metadata.get('page', -1)
            clean_chunks.append((text, source_file, page_number))

    print(f"(*) After quality filter: {len(clean_chunks)} usable chunks ({skipped} garbage chunks removed)")

    print(f"(*) Loading embedding model: {EMBEDDING_MODEL}")
    embeddings_model = HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        encode_kwargs={'normalize_embeddings': True}
    )

    clean_texts = [t for t, s, p in clean_chunks]
    vectors = embeddings_model.embed_documents(clean_texts)

    print("(*) Saving vectors to SQLite database with sqlite-vec")
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)

    # vector size of paraphrase-multilingual-MiniLM-L12-v2 is 384
    db.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS survival_vectors USING vec0(
            chunk_id INTEGER PRIMARY KEY,
            text TEXT,
            embedding float[384]
        );
    """)

    cursor = db.cursor()
    for (text, source_file, page_number), vector in zip(clean_chunks, vectors):
        cursor.execute(
            "INSERT INTO survival_vectors(text, embedding) VALUES (?, ?)",
            (text, sqlite_vec.serialize_float32(vector))
        )
        chunk_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO chunks_metadata(chunk_id, source_file, page_number) VALUES (?, ?, ?)",
            (chunk_id, source_file, page_number)
        )

    for filename in new_filenames:
        cursor.execute("INSERT INTO processed_files (filename) VALUES (?)", (filename,))

    db.commit()
    db.close()
    print(f"(*) Successful. Vector database saved and updated to: {DB_PATH}")


if __name__ == "__main__":
    ingest_pdfs_to_sqlite()