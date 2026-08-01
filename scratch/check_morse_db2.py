import sqlite3
db = sqlite3.connect('db/survival_knowledge.db')
c = db.cursor()
c.execute("SELECT cm.chunk_id, cm.source_type, f.text FROM chunks_metadata cm JOIN chunks_fts f ON cm.chunk_id = f.chunk_id WHERE cm.source_file = '11_telsiz_pmr_ve_mors_alfabesi.txt'")
rows = c.fetchall()
print(f"Found {len(rows)} chunks.")
for r in rows:
    print(r[0], r[1], repr(r[2][:50]))
