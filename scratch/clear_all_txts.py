import sqlite3
import sqlite_vec

def clear_txts():
    db = sqlite3.connect('db/survival_knowledge.db')
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    c = db.cursor()
    
    # Get all chunk_ids for txts
    c.execute("SELECT chunk_id FROM chunks_metadata WHERE source_type = 'txt'")
    chunk_ids = [row[0] for row in c.fetchall()]
    
    if chunk_ids:
        print(f"Deleting {len(chunk_ids)} txt chunks...")
        placeholders = ','.join('?' for _ in chunk_ids)
        c.execute(f"DELETE FROM chunks_metadata WHERE chunk_id IN ({placeholders})", chunk_ids)
        c.execute(f"DELETE FROM chunks_fts WHERE chunk_id IN ({placeholders})", chunk_ids)
        c.execute(f"DELETE FROM survival_vectors WHERE chunk_id IN ({placeholders})", chunk_ids)
    
    c.execute("DELETE FROM processed_files WHERE filename LIKE '%.txt'")
    db.commit()
    db.close()
    print("Done clearing txts.")

if __name__ == '__main__':
    clear_txts()
