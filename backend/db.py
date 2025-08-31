import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "csp.sqlite"

def get_conn():
    return sqlite3.connect(DB_PATH)

def init_db():
    con = get_conn()
    cur = con.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS seen (
        offer_id TEXT PRIMARY KEY
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS saved_searches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        query TEXT NOT NULL,
        email TEXT
    )""")
    con.commit()
    con.close()
