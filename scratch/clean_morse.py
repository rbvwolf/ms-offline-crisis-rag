import sqlite3

def clean_and_reingest():
    import sqlite_vec
    db = sqlite3.connect('db/survival_knowledge.db')
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    c = db.cursor()
    filename = '11_telsiz_pmr_ve_mors_alfabesi.txt'
    
    # Get all chunk_ids for this file
    c.execute("SELECT chunk_id FROM chunks_metadata WHERE source_file = ?", (filename,))
    chunk_ids = [row[0] for row in c.fetchall()]
    
    if chunk_ids:
        print(f"Deleting {len(chunk_ids)} chunks for {filename}...")
        # delete from chunks_metadata
        c.execute("DELETE FROM chunks_metadata WHERE source_file = ?", (filename,))
        # delete from chunks_fts
        placeholders = ','.join('?' for _ in chunk_ids)
        c.execute(f"DELETE FROM chunks_fts WHERE chunk_id IN ({placeholders})", chunk_ids)
        # delete from survival_vectors
        c.execute(f"DELETE FROM survival_vectors WHERE chunk_id IN ({placeholders})", chunk_ids)
    
    # Remove from processed_files table so txt_processor will pick it up
    c.execute("DELETE FROM processed_files WHERE filename = ?", (filename,))
    db.commit()
    db.close()
    print("Done. Ready to run txt_processor.py")

if __name__ == '__main__':
    clean_and_reingest()
