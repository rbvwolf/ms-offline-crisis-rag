import sqlite3
c=sqlite3.connect('db/survival_knowledge.db').cursor()
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
print(c.fetchall())
