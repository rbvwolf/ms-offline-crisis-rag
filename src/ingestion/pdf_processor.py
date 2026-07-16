import os
import re
import sqlite3
import sqlite_vec
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings

raw_pdf_dir = "data/raw_pdfs"
db_path = "db/survival_knowledge.db"

# Must stay in sync with retriever.py and generator.py
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

# Minimum meaningful content length for a chunk (chars)
MIN_CHUNK_LENGTH = 80


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
    db = sqlite3.connect(db_path)

    # Creating new table to track processed files
    db.execute("""
        CREATE TABLE IF NOT EXISTS processed_files (
            filename TEXT PRIMARY KEY,
            processed_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.commit()

    # Fetch already processed files from DB
    cursor = db.cursor()
    cursor.execute("SELECT filename FROM processed_files")
    processed_set = set(row[0] for row in cursor.fetchall())

    new_documents = []
    new_filenames = []

    print("(*) Scanning raw_pdfs folder")
    for filename in os.listdir(raw_pdf_dir):
        if filename.endswith(".pdf"):
            if filename in processed_set:
                print(f"[-] Skipping (Already processed): {filename}")
            else:
                file_path = os.path.join(raw_pdf_dir, filename)
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

    # Chunking texts in documents
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=750, chunk_overlap=100
    )
    raw_chunks = text_splitter.split_documents(new_documents)
    print(f"(*) Documents split into {len(raw_chunks)} raw pieces.")

    # Filter out garbage chunks (headers, footers, page numbers, encoding artifacts)
    clean_texts = []
    skipped = 0
    for chunk in raw_chunks:
        text = chunk.page_content
        if _is_garbage_chunk(text):
            skipped += 1
        else:
            clean_texts.append(text)

    print(f"(*) After quality filter: {len(clean_texts)} usable chunks ({skipped} garbage chunks removed)")

    # Loading offline embedding model
    print(f"(*) Loading embedding model: {EMBEDDING_MODEL}")
    embeddings_model = HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        encode_kwargs={'normalize_embeddings': True}
    )

    vectors = embeddings_model.embed_documents(clean_texts)

    # Save to SQL Vector DB without langchain
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
    for text, vector in zip(clean_texts, vectors):
        cursor.execute(
            "INSERT INTO survival_vectors(text, embedding) VALUES (?, ?)",
            (text, sqlite_vec.serialize_float32(vector))
        )

    for filename in new_filenames:
        cursor.execute("INSERT INTO processed_files (filename) VALUES (?)", (filename,))

    db.commit()
    db.close()
    print(f"(*) Successful. Vector database saved and updated to: {db_path}")


if __name__ == "__main__":
    ingest_pdfs_to_sqlite()