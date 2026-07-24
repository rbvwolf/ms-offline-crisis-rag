import os
import sys
import sqlite3
import sqlite_vec
from langchain_huggingface import HuggingFaceEmbeddings

# Add src/ to path so we can import from core.config
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from core.config import EMBEDDING_MODEL, DB_PATH, MAX_DISTANCE


def retrieve_content(query, embeddings_model, k=5):
    print(f"(*) Analyzing user query: {query}")

    query_vector = embeddings_model.embed_query(query)

    print("(*) Connecting to vector database")
    db = sqlite3.connect(DB_PATH)
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)

    # Ensure chunks_metadata table exists (safe migration for DBs ingested before this change)
    db.execute("""
        CREATE TABLE IF NOT EXISTS chunks_metadata (
            chunk_id INTEGER PRIMARY KEY,
            source_file TEXT,
            page_number INTEGER
        )
    """)

    cursor = db.cursor()
    serialized_query = sqlite_vec.serialize_float32(query_vector)

    print(f"(*) Searcing for the top {k} most relevant paragraphs")
    cursor.execute("""
        SELECT chunk_id, text, distance
        FROM survival_vectors
        WHERE embedding MATCH ? AND k = ?
        ORDER BY distance
    """, (serialized_query, k))

    raw_results = cursor.fetchall()

    # Enrich each result with source metadata (gracefully handles missing metadata)
    results = []
    for chunk_id, text, distance in raw_results:
        cursor.execute(
            "SELECT source_file, page_number FROM chunks_metadata WHERE chunk_id = ?",
            (chunk_id,)
        )
        meta = cursor.fetchone()
        source_file = meta[0] if meta else None
        page_number = meta[1] if meta else -1
        results.append((text, distance, source_file, page_number))

    db.close()
    return results


if __name__ == "__main__":
    # Standalone test
    test_query = "Deprem anında ne yapmalıyım?"

    print("(*) Loading embedding model for test...")
    test_embeddings = HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        model_kwargs={'local_files_only': True},
        encode_kwargs={'normalize_embeddings': True}
    )

    found_documents = retrieve_content(test_query, test_embeddings, k=3)

    print("\n" + "=" * 50)
    print("Search Results")
    print("=" * 50)

    for i, (text, distance, source_file, page_number) in enumerate(found_documents):
        if distance > MAX_DISTANCE:
            print(f"\n[-] Result {i+1} ignored (distance {distance:.4f} > {MAX_DISTANCE})")
            continue
        source_label = f"{source_file} (s.{page_number})" if source_file else "Bilinmeyen kaynak"
        print(f"\n--- Result {i+1} (Distance: {distance:.4f}) | {source_label} ---")
        print(text)