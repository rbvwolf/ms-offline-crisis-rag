import sqlite3
import sqlite_vec
from langchain_huggingface import HuggingFaceEmbeddings

db_path = "db/survival_knowledge.db"

# Must match the model used during ingestion in pdf_processor.py
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

def retrieve_content(query, embeddings_model, k=3):
    print(f"(*) Analyzing user query: {query}")
    
    # 1. Load the EXACT SAME embedding model used in ingestion
    
    # 2. Convert the text query into a mathematical vector
    query_vector = embeddings_model.embed_query(query)
    
    # 3. Connect to DB and load vec extension
    print("(*) Connecting to vector database")
    db = sqlite3.connect(db_path)
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    
    cursor = db.cursor()
    
    # Serialize the query vector to float32 format for sqlite-vec
    serialized_query = sqlite_vec.serialize_float32(query_vector)
    
    # 4. Search the database using KNN
    print(f"(*) Searcing for the top {k} most relevant paragraphs")
    cursor.execute("""
        SELECT text, distance
        FROM survival_vectors
        WHERE embedding MATCH ? AND k = ?
        ORDER BY distance
    """, (serialized_query, k))
    
    results = cursor.fetchall()
    db.close()
    
    return results

if __name__ == "__main__":
    # Test the retriever system
    test_query = "Deprem anında ne yapmalıyım?"
    found_documents = retrieve_content(test_query, k=3)
    
    print("\n" + "=" * 50)
    print("Search Results")
    print("=" * 50)
    
    MAX_DISTANCE = 0.85
    
    for i, (text, distance) in enumerate(found_documents):
        if distance > MAX_DISTANCE:
            print(f"\n[-] Result {i+1} ignored because {distance:.4f} is too high.")
            continue
        print(f"\n--- Result {i+1} (Distance: {distance:.4f}) ---")
        print(text)