import sqlite3
from datetime import datetime

from src.analytics import rollups


def test_seven_day_theme_cluster_ties_break_by_disclosed_value(monkeypatch):
    connection = sqlite3.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE trades (
            ticker TEXT,
            disclosure_date TEXT,
            transaction_date TEXT,
            member_name TEXT,
            transaction_type TEXT,
            amount TEXT,
            amount_value REAL
        )
        """
    )
    connection.executemany(
        "INSERT INTO trades VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("KR", "2026-08-07", "2026-07-24", "David Taylor", "Purchase", "$1,001 - $15,000", 8000.5),
            ("KR", "2026-08-06", "2025-10-03", "Julie Johnson", "Purchase", "$1,001 - $15,000", 8000.5),
            ("AAPL", "2026-08-05", "2025-12-17", "Tommy Tuberville", "Sale", "$50,001 - $100,000", 75000.5),
            ("AAPL", "2026-08-04", "2026-07-21", "Shelley Moore Capito", "Sale", "$1,001 - $15,000", 8000.5),
        ],
    )
    monkeypatch.setattr(rollups, "cursor", connection.cursor())

    theme = rollups.build_seven_day_theme(datetime(2026, 8, 10))

    assert theme["top_cluster"] == {"ticker": "AAPL", "member_count": 2, "value": 83001.0}
    assert theme["cluster_tickers"][1] == {"ticker": "KR", "member_count": 2, "value": 16001.0}
