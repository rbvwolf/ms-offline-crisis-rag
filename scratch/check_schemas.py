import sqlite3
db = sqlite3.connect('db/survival_knowledge.db')
schemas = db.execute("SELECT sql FROM sqlite_master WHERE type='table'").fetchall()
for s in schemas:
    print(s[0])
