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
    amount TEXT,
    transaction_type TEXT,
    member_name TEXT,
    comment TEXT,
    link TEXT,
    UNIQUE (ticker, disclosure_date, transaction_date, amount)
  );
""")

# Migration: add parsed amount column for stable dedupe/comparison
cursor.execute(
    "SELECT 1 FROM pragma_table_info('trades') WHERE name = 'amount_value'"
)
if cursor.fetchone() is None:
    cursor.execute("ALTER TABLE trades ADD COLUMN amount_value REAL")
    from amounts import parse_amount

    cursor.execute(
        "SELECT id, amount FROM trades WHERE amount_value IS NULL OR amount_value = 0"
    )
    for row in cursor.fetchall():
        aid, raw = row[0], row[1]
        val = parse_amount(str(raw) if raw is not None else "")
        cursor.execute("UPDATE trades SET amount_value = ? WHERE id = ?", (val, aid))
    conn.commit()

cursor.execute("""
  CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT
  );
""")
cursor.execute("""
  CREATE TABLE IF NOT EXISTS tweet_queue (
    id INTEGER PRIMARY KEY,
    queue_key TEXT UNIQUE,
    status TEXT NOT NULL DEFAULT 'PENDING',
    scheduled_for TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    posted_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
  );
""")
cursor.execute("""
  CREATE INDEX IF NOT EXISTS idx_tweet_queue_status_schedule
  ON tweet_queue(status, scheduled_for);
""")
cursor.execute("""
  CREATE TABLE IF NOT EXISTS posted_content_log (
    id INTEGER PRIMARY KEY,
    content_type TEXT NOT NULL,
    bundle_id TEXT,
    date TEXT NOT NULL,
    window TEXT NOT NULL,
    hash TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL
  );
""")
cursor.execute("""
  CREATE INDEX IF NOT EXISTS idx_posted_content_date
  ON posted_content_log(date);
""")
cursor.execute("""
  CREATE INDEX IF NOT EXISTS idx_posted_content_alert_bundle
  ON posted_content_log(content_type, bundle_id);
""")

# Posted thread tweet IDs for engagement backfill (keyed by content_hash from posted_content_log)
cursor.execute("""
  CREATE TABLE IF NOT EXISTS posted_thread_ids (
    content_hash TEXT PRIMARY KEY,
    tweet_ids_json TEXT NOT NULL,
    posted_at TEXT NOT NULL
  );
""")

# Engagement metrics per tweet at fixed time windows (e.g. +1h, +24h)
cursor.execute("""
  CREATE TABLE IF NOT EXISTS engagement_metrics (
    id INTEGER PRIMARY KEY,
    content_hash TEXT NOT NULL,
    tweet_id TEXT NOT NULL,
    snapshot_window TEXT NOT NULL,
    sampled_at TEXT NOT NULL,
    like_count INTEGER NOT NULL DEFAULT 0,
    retweet_count INTEGER NOT NULL DEFAULT 0,
    reply_count INTEGER NOT NULL DEFAULT 0,
    quote_count INTEGER NOT NULL DEFAULT 0,
    impression_count INTEGER,
    UNIQUE (content_hash, tweet_id, snapshot_window)
  );
""")
cursor.execute("""
  CREATE INDEX IF NOT EXISTS idx_engagement_content_hash
  ON engagement_metrics(content_hash);
""")
cursor.execute("""
  CREATE INDEX IF NOT EXISTS idx_engagement_snapshot_window
  ON engagement_metrics(snapshot_window);
""")
conn.commit()
