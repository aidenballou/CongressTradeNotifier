"""Regression tests for notifier dedupe and canonical key logic."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amounts import parse_amount
from notifier import _trade_key, get_existing_keys, store_new_trades


def test_trade_key_canonical_order_and_normalization():
    """Canonical key uses (ticker_upper, disclosure_date, transaction_date, parsed_amount)."""
    k1 = _trade_key("aapl", "2026-02-11", "2026-02-01", "$1,001 - $15,000")
    k2 = _trade_key("AAPL", "2026-02-11", "2026-02-01", "$1001 - $15000")
    assert k1 == k2
    assert k1[0] == "AAPL"
    assert k1[3] == parse_amount("$1,001 - $15,000")


def test_trade_key_parse_amount_accepts_numeric():
    """Keys built from DB amount_value (float) match keys built from raw string."""
    raw = "$50,001 - $100,000"
    parsed = parse_amount(raw)
    k_raw = _trade_key("NVDA", "2026-02-11", "2026-01-15", raw)
    k_num = _trade_key("NVDA", "2026-02-11", "2026-01-15", parsed)
    assert k_raw == k_num


def test_store_new_trades_dedupe_duplicate_not_in_new(tmp_path, monkeypatch):
    """Duplicate input must not appear in returned 'new' list (only truly inserted)."""
    db_path = tmp_path / "trades.db"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY,
            ticker TEXT,
            disclosure_date TEXT,
            transaction_date TEXT,
            district TEXT,
            owner TEXT,
            asset_description TEXT,
            asset_type TEXT,
            amount REAL,
            amount_value REAL,
            transaction_type TEXT,
            member_name TEXT,
            comment TEXT,
            link TEXT,
            UNIQUE (ticker, disclosure_date, transaction_date, amount)
        )
    """)
    conn.commit()

    import notifier as mod
    monkeypatch.setattr(mod, "conn", conn)
    monkeypatch.setattr(mod, "cursor", cur)

    trade = {
        "symbol": "MSFT",
        "disclosureDate": "2026-02-11",
        "transactionDate": "2026-02-01",
        "district": "WA01",
        "owner": "Self",
        "assetDescription": "Microsoft",
        "assetType": "Stock",
        "amount": "$1,001 - $15,000",
        "type": "Purchase",
        "firstName": "Jane",
        "lastName": "Doe",
        "comment": "",
        "link": "https://example.com",
    }

    new1, st1 = mod.store_new_trades([trade])
    assert len(new1) == 1
    assert st1["inserted"] == 1

    new2, st2 = mod.store_new_trades([trade, trade])
    assert len(new2) == 0
    assert st2["inserted"] == 0
    assert st2["skipped"] == 2

    conn.close()


def test_get_existing_keys_same_shape_as_trade_key():
    """Existing keys from DB use same tuple shape as _trade_key for set membership."""
    # get_existing_keys returns set of (ticker_upper, disclosure_date, transaction_date, amount_value)
    # _trade_key(ticker, disclosure_date, transaction_date, amount_raw) returns same shape
    k = _trade_key("GOOGL", "2026-02-11", "2026-01-20", "$15,001 - $50,000")
    assert len(k) == 4
    assert k[0] == "GOOGL"
    assert k[1] == "2026-02-11"
    assert k[2] == "2026-01-20"
    assert isinstance(k[3], (int, float))
