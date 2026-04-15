from fmp_client import fetch_senate_trades, fetch_house_trades
from db import conn, cursor

from amounts import parse_amount


def _trade_key(ticker, disclosure_date, transaction_date, amount_raw):
    """Canonical key for dedupe: (ticker_upper, disclosure_date, transaction_date, parsed_amount)."""
    ticker_upper = str(ticker or "").strip().upper()
    disc = str(disclosure_date or "").strip()
    trans = str(transaction_date or "").strip()
    amount_val = parse_amount(str(amount_raw) if amount_raw is not None else "")
    return (ticker_upper, disc, trans, amount_val)


def get_existing_keys():
    """Return set of canonical trade keys already in DB (same tuple shape as _trade_key)."""
    cursor.execute(
        "SELECT ticker, transaction_date, disclosure_date, amount_value, amount FROM trades"
    )
    keys = set()
    for row in cursor.fetchall():
        ticker, trans_date, disc_date, amount_val, amount_raw = (
            row[0], row[1], row[2], row[3], row[4]
        )
        # Prefer parsed amount_value when present and nonzero
        if amount_val is not None and amount_val != 0:
            keys.add((str(ticker or "").strip().upper(), str(disc_date or "").strip(), str(trans_date or "").strip(), float(amount_val)))
        else:
            keys.add(_trade_key(ticker, disc_date, trans_date, amount_raw))
    return keys


def store_new_trades(trades):
    """Insert only trades whose canonical key is not in DB; return (new_list, stats)."""
    existing = get_existing_keys()
    new = []
    skipped = 0
    for t in trades:
        key = _trade_key(
            t.get("symbol"),
            t.get("disclosureDate"),
            t.get("transactionDate"),
            t.get("amount"),
        )
        if key in existing:
            skipped += 1
            continue
        amount_raw = t.get("amount")
        amount_val = parse_amount(amount_raw)
        cursor.execute(
            """
            INSERT OR IGNORE INTO trades
            (ticker, disclosure_date, transaction_date, district, owner, asset_description, asset_type, amount, amount_value, transaction_type, member_name, comment, link)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                t["symbol"],
                t["disclosureDate"],
                t["transactionDate"],
                t.get("district"),
                t.get("owner"),
                t.get("assetDescription"),
                t.get("assetType"),
                amount_raw,
                amount_val,
                t.get("type"),
                ((t.get("firstName") or "") + " " + (t.get("lastName") or "")).strip(),
                t.get("comment"),
                t.get("link"),
            ),
        )
        if cursor.rowcount > 0:
            new.append(t)
            existing.add(key)
    conn.commit()
    stats = {"inserted": len(new), "skipped": skipped, "fetched": len(trades)}
    return new, stats

def run_delta():
    all_trades = fetch_senate_trades() + fetch_house_trades()
    new, stats = store_new_trades(all_trades)
    return new, stats