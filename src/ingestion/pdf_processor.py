import os
import sqlite3
import sqlite_vec
from langchain_community.document_loaders import PyPDFDirectoryLoader
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings

raw_pdf_dir = "data/raw_pdfs"
db_path = "db/survival_knowledge.db"

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
                print(f"[+] Found new file. Reading: {filename}")
                file_path = os.path.join(raw_pdf_dir, filename)
                loader = PyPDFLoader(file_path)
                new_documents.extend(loader.load())
                new_filenames.append(filename)
                
    if not new_documents:
        print("(!!!) No new PDF files found. Database is up to date.")
        db.close()
        return
    
    print(f"(*) Found {len(new_documents)} pages of document. Chunking...")
    
    # Chunking texts in documents
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size = 1000, chunk_overlap=150 #Make overlap for taking care of sense of context
    )
    chunks = text_splitter.split_documents(new_documents)
    print(f"(*) Documents splitted into {len(chunks)} meaningful pieces.")
    
    # Loading offline embedding model
    print("(*) Loading embedding model (download in first try, after that it gonna be offline)")
    embeddings_model = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    
    texts = [chunk.page_content for chunk in chunks]
    vectors = embeddings_model.embed_documents(texts)
    
    # Save to SQL Vector DB without langchain
    print("(*) Calculating Vectors and save to the SQLite database with sqlite-vec.")
    # db connection and loading vec file extension
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    
    # vector size of all-MiniLM-L6-v2 is 384
    db.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS survival_vectors USING vec0(
            chunk_id INTEGER PRIMARY KEY,
            text TEXT,
            embedding float[384]
        );
    """)
    
    cursor = db.cursor()
    for text, vector in zip(texts, vectors):
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