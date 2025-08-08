#!/usr/bin/env python3
"""
Preview the generated tweet (and optional chart) without requiring new trades today.

Usage examples:

  # Preview using the most recent trade in the database (no posting)
  python scripts/preview_tweet.py --from-db

  # Preview with a sample fabricated trade
  python scripts/preview_tweet.py --sample

  # Also generate and save a chart image (path printed to console)
  python scripts/preview_tweet.py --from-db --chart

  # Actually post the tweet (uses your monthly write quota!)
  python scripts/preview_tweet.py --from-db --post
"""

import os
import sys
import argparse
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Ensure we can import from src/
ROOT = os.path.dirname(os.path.dirname(__file__))
SRC = os.path.join(ROOT, "src")
sys.path.append(SRC)

from twitter_client import TwitterClient  # noqa: E402

load_dotenv()


def get_recent_trade_from_db():
    try:
        from db import cursor  # noqa: E402
        cursor.execute(
            """
            SELECT ticker, disclosure_date, transaction_date, member_name,
                   transaction_type, amount, asset_description, district, owner
            FROM trades
            ORDER BY rowid DESC
            LIMIT 1
            """
        )
        row = cursor.fetchone()
        if not row:
            return None
        ticker, disclosure_date, transaction_date, member_name, tx_type, amount, asset_desc, district, owner = row
        first, last = (member_name or " ").split(" ", 1) if member_name else ("", "")
        return {
            "symbol": (ticker or "").upper(),
            "disclosureDate": disclosure_date or "",
            "transactionDate": transaction_date or "",
            "firstName": first,
            "lastName": last,
            "type": tx_type or "",
            "amount": amount or "",
            "assetDescription": asset_desc or "",
            "district": district or "",
            "owner": owner or "",
            # Best-effort source guess not stored; default to house
            "source": "house",
        }
    except Exception:
        return None


def get_sample_trade():
    ten_days_ago = (datetime.utcnow() - timedelta(days=10)).strftime("%Y-%m-%d")
    return {
        "symbol": "AAPL",
        "disclosureDate": datetime.utcnow().strftime("%Y-%m-%d"),
        "transactionDate": ten_days_ago,
        "firstName": "Jane",
        "lastName": "Doe",
        "type": "BUY",
        "amount": "$50,001 - $100,000",
        "assetDescription": "Apple Inc - Consumer Tech",
        "district": "FL25",
        "owner": "Self",
        "source": "house",
    }


def main():
    parser = argparse.ArgumentParser(description="Preview the new tweet format and optional chart.")
    src = parser.add_mutually_exclusive_group()
    src.add_argument("--from-db", action="store_true", help="Use the most recent trade in the database")
    src.add_argument("--sample", action="store_true", help="Use a fabricated sample trade")
    parser.add_argument("--chart", action="store_true", help="Also generate and save a chart image")
    parser.add_argument("--post", action="store_true", help="Actually post the tweet to Twitter (uses quota)")
    args = parser.parse_args()

    if not (args.from_db or args.sample):
        args.from_db = True

    trade = get_recent_trade_from_db() if args.from_db else get_sample_trade()
    if not trade:
        print("No recent trades found in DB. Falling back to sample.")
        trade = get_sample_trade()

    client = TwitterClient()

    # Build tweet text (engaging style is default if TWITTER_STYLE=engaging)
    tweet_text = client._format_trade_tweet_engaging(trade)
    print("\n==== TWEET PREVIEW ====")
    print(tweet_text)
    print(f"\nLength: {len(tweet_text)} / 280 characters\n")

    image_path = None
    if args.chart:
        image_path = client._build_chart_for_symbol(trade.get("symbol", ""), trade.get("transactionDate"))
        if image_path:
            print(f"Chart saved to: {image_path}")
        else:
            print("Chart could not be generated (missing data or plotting not available).")

    if args.post:
        print("\nPosting to Twitter...")
        try:
            client.post_trade_tweet(trade)
            print("Posted successfully.")
        except Exception as e:
            print(f"Failed to post: {e}")
    else:
        print("(Not posted. Use --post to publish.)")


if __name__ == "__main__":
    main()


