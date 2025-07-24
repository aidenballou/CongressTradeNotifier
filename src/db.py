import sqlite3

conn = sqlite3.connect("trades.sqlite3", check_same_thread=False)
cursor = conn.cursor()
cursor.execute("""
  CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY,
    ticker TEXT,
    disclosure_date TEXT,
    transaction_date TEXT,
    district TEXT,
    owner TEXT,
    asset_description TEXT,
    asset_type TEXT,
    amount REAL,
    transaction_type TEXT,
    member_name TEXT,
    comment TEXT,
    link TEXT,
    UNIQUE (ticker, disclosure_date, transaction_date, amount)
  );
""")
cursor.execute("""
  CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT
  );
""")
conn.commit()