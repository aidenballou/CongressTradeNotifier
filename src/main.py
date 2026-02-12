from collections import defaultdict
from datetime import datetime, timedelta
import os
from zoneinfo import ZoneInfo
from typing import Any, Dict, List

from dotenv import load_dotenv

from db import cursor
from emailer import send_summary
from insider import find_recent_insider_activity
from insights import build_highlights_text, compute_trade_insights
from notifier import run_delta
from scheduler.select_content import run_scheduler

# Load environment variables
load_dotenv()

ET = ZoneInfo("America/New_York")


def _bundle_filings(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Bundle trades into filing-like units keyed by member + disclosure date."""

    grouped: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        key = (
            str(trade.get("firstName", "")).strip(),
            str(trade.get("lastName", "")).strip(),
            str(trade.get("disclosureDate", "")).strip(),
        )
        grouped[key].append(trade)

    filings: List[Dict[str, Any]] = []
    for (first, last, disclosure_date), filing_trades in grouped.items():
        filing_trades = sorted(
            filing_trades,
            key=lambda item: str(item.get("transactionDate") or item.get("disclosureDate") or ""),
        )
        primary = filing_trades[0]
        filings.append(
            {
                "firstName": first,
                "lastName": last,
                "member_name": f"{first} {last}".strip(),
                "disclosureDate": disclosure_date,
                "transactionDate": primary.get("transactionDate") or disclosure_date,
                "source": primary.get("source"),
                "trades": filing_trades,
            }
        )

    return filings




def main():
    print("Starting main.py...")

    new, delta_stats = run_delta()
    print(
        f"Delta: fetched={delta_stats.get('fetched', 0)} "
        f"skipped={delta_stats.get('skipped', 0)} inserted={delta_stats.get('inserted', 0)}"
    )
    now_et = datetime.now(ET)
    today = now_et.strftime("%Y-%m-%d")
    trades_today = [t for t in new if t.get("disclosureDate") == today]
    print(f"Found {len(trades_today)} trades disclosed today ({today})")

    if trades_today:
        insider_activity = find_recent_insider_activity(trades_today)
        insights = compute_trade_insights(trades_today)
        if insider_activity:
            insights["related_insider_activity"] = insider_activity

        print("Daily highlights:")
        print(build_highlights_text(insights))

        print("Sending email...")
        send_summary(trades_today, insights)
        print("Email sent!")
    else:
        print("No same-day disclosures for email summary.")

    # Run scheduler for scheduled publishing
    scheduler_result = run_scheduler(now_et)
    if scheduler_result:
        print(f"Scheduler posted: {scheduler_result}")
    else:
        print("Scheduler: no action (not in window or nothing to post)")


if __name__ == "__main__":
    main()
