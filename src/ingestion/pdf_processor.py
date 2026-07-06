import os
import shutil
import sqlite3
import sqlite_vec
from langchain_community.document_loaders import PyPDFDirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings

raw_pdf_dir = "data/raw_pdfs"
db_path = "db/survival_knowledge.db"
processed_pdf_dir = "data/processed"

def ingest_pdfs_to_sqlite():
    print("(*) PDF files are scanning...")
    
    # Loading documents
    loader = PyPDFDirectoryLoader(raw_pdf_dir)
    documents = loader.load()
    
    if not documents:
        print("(!!!) Theres no PDF files in folder. Please add AFAD/Kızılay guides to the data/raw_pdfs folder.")
        return
    
    print(f"(*) Found {len(documents)} pages of document. Chunking...")
    
    # Chunking texts in documents
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size = 1000, chunk_overlap=150 #Make overlap for taking care of sense of context
    )
    chunks = text_splitter.split_documents(documents)
    print(f"(*) Documents splitted into {len(chunks)} meaningful pieces.")
    
    # Loading offline embedding model
    print("(*) Loading embedding model (download in first try, after that it gonna be offline)")
    embeddings_model = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    
    texts = [chunk.page_content for chunk in chunks]
    vectors = embeddings_model.embed_documents(texts)
    
    # Save to SQL Vector DB without langchain
    print("(*) Calculating Vectors and save to the SQLite database with sqlite-vec.")
    # db connection and loading vec file extension
    db = sqlite3.connect(db_path)
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
    for i, (text, vector) in enumerate(zip(texts, vectors)):
        cursor.execute(
            "INSERT INTO survival_vectors(chunk_id, text, embedding) VALUES (?, ?, ?)",
            (i, text, sqlite_vec.serialize_float32(vector))
        )
    db.commit()
    db.close()
    print(f"(*) Successful. Vector database saved and updated to: {db_path}")
    
    # Move processed pdfs to data/processed
    print(f"(*) Processed PDFs moving to archive ({processed_pdf_dir})")
    for filename in os.listdir(raw_pdf_dir):
        if filename.endswith(".pdf"):
            source_path = os.path.join(raw_pdf_dir, filename)
            dist_path = os.path.join(processed_pdf_dir, filename)
            shutil.move(source_path, dist_path)
            print(f"    -> Moved: {filename}")
    
if __name__ == "__main__":
    ingest_pdfs_to_sqlite()