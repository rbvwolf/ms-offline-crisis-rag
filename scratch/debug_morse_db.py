import sqlite3

db = sqlite3.connect('db/survival_knowledge.db')
c = db.cursor()
c.execute("SELECT rowid, source_type, source_file FROM chunks_metadata WHERE source_file='11_telsiz_pmr_ve_mors_alfabesi.txt'")
rows = c.fetchall()
print(f"Chunks found for Morse TXT: {len(rows)}")
for r in rows:
    print(r)

c.execute("SELECT id, file_name, text FROM fts_chunks WHERE text LIKE '%MORS ALFABESİ%'")
print(f"FTS Search for MORS ALFABESİ: {c.fetchall()}")
