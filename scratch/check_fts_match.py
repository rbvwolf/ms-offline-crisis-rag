import sqlite3
db = sqlite3.connect('db/survival_knowledge.db')
query = '"mors" OR "alfabesi" OR "nokta" OR "cizgi" OR "harf" OR "kodu" OR "sos" OR "sinyal"'
results = db.execute('SELECT chunk_id, bm25(chunks_fts) as score FROM chunks_fts WHERE text MATCH ? ORDER BY score LIMIT 50', (query,)).fetchall()
for i, r in enumerate(results):
    print(f"{i}: id={r[0]} score={r[1]}")
