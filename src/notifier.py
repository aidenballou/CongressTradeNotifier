from fmp_client import fetch_senate_trades, fetch_house_trades
from db import conn, cursor
import re

def parse_amount(amount_str):
    """Parse amount string like '$1,001 - $15,000' and return the average as float"""
    if not amount_str or amount_str == "":
        return 0.0
    
    # Remove $ and commas, split by dash
    cleaned = amount_str.replace('$', '').replace(',', '')
    parts = cleaned.split(' - ')
    
    if len(parts) == 2:
        try:
            min_val = float(parts[0].strip())
            max_val = float(parts[1].strip())
            return (min_val + max_val) / 2  # Return average
        except ValueError:
            return 0.0
    elif len(parts) == 1:
        try:
            return float(parts[0].strip())
        except ValueError:
            return 0.0
    else:
        return 0.0

def get_existing_keys():
    cursor.execute("SELECT ticker, transaction_date, disclosure_date, amount FROM trades")
    return set(cursor.fetchall())

def store_new_trades(trades):
    existing = get_existing_keys()
    new = []
    for t in trades:
        amount_value = parse_amount(t["amount"])
        key = (t["symbol"], t["disclosureDate"], t["transactionDate"], amount_value)
        if key not in existing:
            cursor.execute("""
              INSERT OR IGNORE INTO trades
              (ticker, disclosure_date, transaction_date, district, owner, asset_description, asset_type, amount, transaction_type, member_name, comment, link)
              VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (t["symbol"], t["disclosureDate"], t["transactionDate"], t["district"], t["owner"], t["assetDescription"], t["assetType"], t["amount"], t["type"], t["firstName"] + " " + t["lastName"], t["comment"], t["link"]))
            new.append(t)
    conn.commit()
    return new

def run_delta():
    all_trades = fetch_senate_trades() + fetch_house_trades()
    return store_new_trades(all_trades)