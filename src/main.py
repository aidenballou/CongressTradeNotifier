from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from emailer import send_summary
from insider import find_recent_insider_activity
from insights import build_highlights_text, compute_trade_insights
from notifier import run_delta
from scheduler.select_content import run_scheduler

# Load environment variables
load_dotenv()

ET = ZoneInfo("America/New_York")
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
