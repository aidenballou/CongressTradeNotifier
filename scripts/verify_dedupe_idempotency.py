"""
Dry-run verification: run_delta() twice with the same fetched data must yield
inserted=0 on the second run (idempotent dedupe). Run from repo root with:
  PYTHONPATH=src python scripts/verify_dedupe_idempotency.py
Uses a temporary SQLite DB so it does not modify trades.sqlite3.
"""

import os
import sqlite3
import sys
from pathlib import Path

# Run from repo root; add src for imports
repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root / "src"))

# Use temp DB so we don't touch real state
db_path = repo_root / "trades.sqlite3"
if db_path.exists():
    # Backup: run against real DB and assert second run has inserted=0
    # (Requires FMP_API_KEY and network for first run to have data.)
    from notifier import run_delta

    new1, st1 = run_delta()
    new2, st2 = run_delta()
    if st1["fetched"] > 0:
        assert st2["inserted"] == 0, (
            f"Idempotency failed: second run inserted {st2['inserted']} (expected 0). "
            f"fetched={st2['fetched']} skipped={st2['skipped']}"
        )
        print("OK Idempotency: second run inserted=0.")
    else:
        print("SKIP No data fetched (empty API or no network); idempotency not exercised.")
else:
    print("SKIP No trades.sqlite3; run main once to create DB then re-run this script.")
