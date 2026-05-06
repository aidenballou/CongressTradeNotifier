#!/usr/bin/env python3
"""Test script to verify scheduler and preview/post tweets.

This script will:
1. Optionally create test data (if --create-test-data flag is used)
2. Run the scheduler for a specific window
3. Compose and POST actual tweets (you'll need to delete them manually)
4. Show what was posted

Usage:
    python scripts/test_scheduler_posting.py --window MORNING
    python scripts/test_scheduler_posting.py --window MORNING --create-test-data
    python scripts/test_scheduler_posting.py --window MORNING --dry-run  # Compose but don't post
"""

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from db import conn, cursor
from scheduler.select_content import run_scheduler
from scheduler.evaluate_window import WINDOWS
from analytics.bundle_builder import build_bundles_from_db
from analytics.rollups import build_daily_tape, build_seven_day_theme, build_member_spotlight
from tweet_composer import (
    compose_daily_tape_thread,
    compose_seven_day_theme_thread,
    compose_member_spotlight_thread,
)
from trade_analyzer import analyze_filing
from analytics.bundle_builder import fetch_recent_trades
from historical_context import build_historical_context
from insight_generator import generate_insight
from tweet_composer import compose_thread


ET = ZoneInfo("America/New_York")


def create_test_data():
    """Create some test trade data in the database."""
    print("Creating test trade data...")
    
    # Clear existing test data (optional - comment out if you want to keep real data)
    # cursor.execute("DELETE FROM trades WHERE member_name LIKE 'TEST%'")
    
    test_trades = [
        {
            "ticker": "AAPL",
            "disclosure_date": datetime.now(ET).strftime("%Y-%m-%d"),
            "transaction_date": (datetime.now(ET) - timedelta(days=1)).strftime("%Y-%m-%d"),
            "member_name": "TEST Senator Smith",
            "transaction_type": "BUY",
            "amount": "$50,001 - $100,000",
            "amount_value": 75000.0,
            "asset_description": "Apple Inc. Common Stock",
            "comment": "Large tech position",
        },
        {
            "ticker": "MSFT",
            "disclosure_date": datetime.now(ET).strftime("%Y-%m-%d"),
            "transaction_date": (datetime.now(ET) - timedelta(days=1)).strftime("%Y-%m-%d"),
            "member_name": "TEST Senator Smith",
            "transaction_type": "BUY",
            "amount": "$15,001 - $50,000",
            "amount_value": 32500.0,
            "asset_description": "Microsoft Corporation Common Stock",
            "comment": "Tech diversification",
        },
        {
            "ticker": "NVDA",
            "disclosure_date": (datetime.now(ET) - timedelta(days=2)).strftime("%Y-%m-%d"),
            "transaction_date": (datetime.now(ET) - timedelta(days=3)).strftime("%Y-%m-%d"),
            "member_name": "TEST Representative Jones",
            "transaction_type": "BUY",
            "amount": "$100,001 - $250,000",
            "amount_value": 175000.0,
            "asset_description": "NVIDIA Corporation Common Stock",
            "comment": "AI chip play",
        },
    ]
    
    inserted = 0
    for trade in test_trades:
        try:
            cursor.execute(
                """
                INSERT OR IGNORE INTO trades
                (ticker, disclosure_date, transaction_date, member_name,
                 transaction_type, amount, amount_value, asset_description, comment)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trade["ticker"],
                    trade["disclosure_date"],
                    trade["transaction_date"],
                    trade["member_name"],
                    trade["transaction_type"],
                    trade["amount"],
                    trade["amount_value"],
                    trade["asset_description"],
                    trade["comment"],
                ),
            )
            if cursor.rowcount > 0:
                inserted += 1
        except Exception as e:
            print(f"Error inserting {trade['ticker']}: {e}")
    
    conn.commit()
    print(f"Inserted {inserted} test trades")
    return inserted > 0


def preview_thread(thread, title="Thread Preview"):
    """Print a thread preview."""
    print(f"\n{'='*60}")
    print(f"{title}")
    print(f"{'='*60}")
    for i, tweet in enumerate(thread, 1):
        print(f"\nTweet {i}/{len(thread)}:")
        print(f"  Text: {tweet.get('text', '')}")
        if tweet.get('media_symbol'):
            print(f"  Media: Chart for {tweet['media_symbol']}")
        print(f"  Length: {len(tweet.get('text', ''))} chars")
    print(f"\n{'='*60}\n")


def run_window_check(window_name: str, dry_run: bool = False, force_time: datetime = None):
    """Test scheduler for a specific window."""
    print(f"\n{'='*60}")
    print(f"Testing scheduler for window: {window_name}")
    print(f"{'='*60}\n")
    
    # Get the window time
    window_time = WINDOWS.get(window_name)
    if not window_time:
        print(f"Error: Unknown window '{window_name}'. Valid windows: {list(WINDOWS.keys())}")
        return
    
    # Use forced time or create one at the window time
    if force_time:
        test_time = force_time
    else:
        # Create a datetime at the window time today
        now_et = datetime.now(ET)
        test_time = now_et.replace(
            hour=window_time.hour,
            minute=window_time.minute,
            second=0,
            microsecond=0
        )
        
        # If the window time has passed today, use it anyway (still within tolerance)
        if test_time > now_et:
            # Use yesterday's window time
            test_time = test_time - timedelta(days=1)
    
    now_et = datetime.now(ET)
    print(f"Using test time: {test_time.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Current time: {now_et.strftime('%Y-%m-%d %H:%M:%S %Z')}\n")
    
    # Check what bundles exist
    bundles = build_bundles_from_db(test_time, hours=24)
    print(f"Found {len(bundles)} bundles in last 24h")
    
    if bundles:
        for i, bundle in enumerate(bundles[:3], 1):
            member = bundle.get("member_name", "Unknown")
            date = bundle.get("disclosureDate", "?")
            tickers = [t.get("ticker") or t.get("symbol") for t in bundle.get("trades", [])]
            print(f"  Bundle {i}: {member} on {date} - {', '.join(set(tickers))}")
    
    # Check rollups
    tape = build_daily_tape(test_time)
    print(f"\nDaily Tape: {tape.get('total_filings', 0)} filings")
    
    theme = build_seven_day_theme(test_time)
    print(f"7-Day Theme: {len(theme.get('top_5_tickers_by_value', []))} top tickers")
    
    spotlight = build_member_spotlight(test_time)
    if spotlight:
        print(f"Member Spotlight: {spotlight.get('member', 'Unknown')} - {spotlight.get('ticker', '?')}")
    
    print("\n" + "-"*60)
    print("Running scheduler...")
    print("-"*60 + "\n")
    
    if dry_run:
        print("DRY RUN MODE - Composing threads but NOT posting\n")
        # Preview what would be posted by manually composing
        from scheduler.dedupe_guard import count_posts_today, has_window_posted_today, has_daily_tape_today
        from scheduler.dynamic_threshold import compute_threshold
        from analytics.bundle_builder import filter_unposted
        from trade_analyzer import analyze_filing
        
        today = test_time.strftime("%Y-%m-%d")
        posts_today = count_posts_today(today)
        print(f"Posts today: {posts_today}")
        
        if posts_today >= 3:
            print("Daily max reached - would skip")
            return
        
        unposted_bundles = filter_unposted(bundles, today)
        recent_trades = fetch_recent_trades(days=400, now_et=test_time)
        
        # Score bundles
        scored = []
        for bundle in unposted_bundles:
            signal = analyze_filing(bundle, recent_trades, test_time)
            score = signal.get("diagnostics", {}).get("score", 0)
            scored.append((bundle, signal, score))
        scored.sort(key=lambda x: x[2], reverse=True)
        
        threshold = compute_threshold(len(unposted_bundles))
        print(f"Unposted bundles: {len(unposted_bundles)}")
        print(f"Threshold: {threshold}")
        if scored:
            print(f"Top bundle score: {scored[0][2]}")
        
        # Preview what would be selected
        thread = None
        content_type = None
        
        if window_name == "MORNING":
            if scored and threshold is not None and scored[0][2] >= threshold:
                # Would post alert
                bundle, signal, score = scored[0]
                context = build_historical_context(bundle, signal, window_days=30)
                insight = generate_insight(bundle, signal, context)
                stats = signal.get("diagnostics", {})
                thread = compose_thread(bundle, signal, insight, context, stats)
                content_type = "ALERT"
            elif not has_daily_tape_today(today):
                tape = build_daily_tape(test_time)
                if tape.get("total_filings", 0) > 0:
                    thread = compose_daily_tape_thread(tape)
                    content_type = "DAILY_TAPE"
            else:
                theme = build_seven_day_theme(test_time)
                if theme.get("top_5_tickers_by_value"):
                    thread = compose_seven_day_theme_thread(theme)
                    content_type = "SEVEN_DAY_THEME"
        elif window_name == "MIDDAY":
            if scored and threshold is not None and scored[0][2] >= threshold:
                bundle, signal, score = scored[0]
                context = build_historical_context(bundle, signal, window_days=30)
                insight = generate_insight(bundle, signal, context)
                stats = signal.get("diagnostics", {})
                thread = compose_thread(bundle, signal, insight, context, stats)
                content_type = "ALERT"
        elif window_name == "POWER_HOUR":
            if posts_today == 0:
                tape = build_daily_tape(test_time)
                if not has_daily_tape_today(today):
                    thread = compose_daily_tape_thread(tape)
                    content_type = "DAILY_TAPE"
        elif window_name == "EVENING":
            tape = build_daily_tape(test_time)
            if tape.get("total_filings", 0) == 0:
                theme = build_seven_day_theme(test_time)
                if theme.get("top_5_tickers_by_value"):
                    thread = compose_seven_day_theme_thread(theme)
                    content_type = "SEVEN_DAY_THEME"
            else:
                spotlight = build_member_spotlight(test_time)
                if spotlight:
                    thread = compose_member_spotlight_thread(spotlight)
                    content_type = "MEMBER_SPOTLIGHT"
        
        if thread:
            preview_thread(thread, f"Would Post ({content_type})")
        else:
            print("\nNo content would be selected for this window")
    else:
        # Actually run the scheduler (will post)
        print("LIVE MODE - Will POST tweets!\n")
        result = run_scheduler(test_time)
        
        if result:
            print(f"\n✓ Scheduler posted: {result}")
            print("\n⚠️  REMINDER: Delete these test tweets manually from Twitter!")
        else:
            print("\n✗ Scheduler did not post (check logs above for reason)")


def main():
    parser = argparse.ArgumentParser(description="Test scheduler and preview/post tweets")
    parser.add_argument(
        "--window",
        choices=list(WINDOWS.keys()),
        default="MORNING",
        help="Window to test (default: MORNING)",
    )
    parser.add_argument(
        "--create-test-data",
        action="store_true",
        help="Create test trade data before running",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compose threads but don't post them",
    )
    parser.add_argument(
        "--force-time",
        type=str,
        help="Force a specific time (format: YYYY-MM-DD HH:MM, e.g., '2024-01-15 08:35')",
    )
    
    args = parser.parse_args()
    
    # Parse force_time if provided
    force_time = None
    if args.force_time:
        try:
            force_time = datetime.strptime(args.force_time, "%Y-%m-%d %H:%M")
            force_time = force_time.replace(tzinfo=ET)
        except ValueError:
            print(f"Error: Invalid time format. Use YYYY-MM-DD HH:MM (e.g., '2024-01-15 08:35')")
            sys.exit(1)
    
    print("="*60)
    print("Scheduler Test Script")
    print("="*60)
    
    if args.create_test_data:
        if not create_test_data():
            print("Warning: No test data created (may already exist)")
    
    run_window_check(args.window, dry_run=args.dry_run, force_time=force_time)
    
    print("\n" + "="*60)
    print("Test complete!")
    print("="*60)


if __name__ == "__main__":
    main()
