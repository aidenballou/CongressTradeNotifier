import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from analytics.bundle_builder import bundle_id as congress_bundle_id
from emailer import send_summary
from filing_utils import filter_postable_trades, member_name
from insider import find_recent_insider_activity
from insights import build_highlights_text, compute_trade_insights
from notifier import run_delta
from posting_strategy import dispatch_due_threads, enqueue_signal_threads
from scheduler.dedupe_guard import has_been_posted, has_email_sent_today, record_email_sent
from scheduler.select_content import run_scheduler
from tweet_composer import compose_congress_alert_thread

# Load environment variables
load_dotenv()

ET = ZoneInfo("America/New_York")

# File-based email lock that survives DB resets. Written next to the DB.
_EMAIL_LOCK_DIR = Path(os.getenv("EMAIL_LOCK_DIR", "."))


def _email_lock_path(date: str) -> Path:
    return _EMAIL_LOCK_DIR / f".email_sent_{date}.lock"


def _has_email_lock(date: str) -> bool:
    return _email_lock_path(date).exists()


def _write_email_lock(date: str, now_et: datetime) -> None:
    _email_lock_path(date).write_text(now_et.isoformat())


def _env_enabled(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _group_congress_trades(trades: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = {}
    for trade in filter_postable_trades(trades):
        key = (
            (member_name(trade) or "Unknown").casefold(),
            str(trade.get("disclosureDate") or trade.get("disclosure_date") or ""),
        )
        grouped.setdefault(key, []).append(trade)

    filings = []
    for (_, disclosure_date), member_trades in grouped.items():
        name = member_name(member_trades[0]) or "Unknown"
        first = str(member_trades[0].get("firstName") or "").strip()
        last = str(member_trades[0].get("lastName") or "").strip()
        filings.append(
            {
                "firstName": first,
                "lastName": last,
                "member_name": name,
                "disclosureDate": disclosure_date,
                "trades": member_trades,
            }
        )
    return filings


def _format_fallback_root(trades_today: list[dict], today: str) -> str:
    filings = _group_congress_trades(trades_today)
    if not filings:
        return ""
    thread = compose_congress_alert_thread(filings[0])
    return str(thread[0]["text"]) if thread else ""


def _maybe_post_fallback_summary(
    trades_today: list[dict],
    now_et: datetime,
    scheduler_outcome: dict,
) -> dict:
    fallback_enabled = _env_enabled("SCHEDULER_FALLBACK_ENABLED", default=True)
    fallback_mode = os.getenv("SCHEDULER_FALLBACK_MODE", "summary").strip().lower() or "summary"
    scheduler_reason = str(scheduler_outcome.get("reason") or "")
    fallback_eligible_reasons = {
        "not_in_window",
        "no_content_selected",
        "no_high_quality_content",
    }
    result = {
        "enabled": fallback_enabled,
        "mode": fallback_mode,
        "attempted": False,
        "posted": False,
        "reason": "disabled" if not fallback_enabled else "not_eligible",
        "posted_count": 0,
        "failed_count": 0,
        "queued_count": 0,
    }

    if not fallback_enabled:
        return result
    if fallback_mode != "summary":
        result["reason"] = "unsupported_mode"
        return result
    if not trades_today:
        result["reason"] = "no_disclosures"
        return result
    if scheduler_reason not in fallback_eligible_reasons and not bool(scheduler_outcome.get("posted")):
        result["reason"] = f"ineligible_reason:{scheduler_reason}"
        return result

    today = now_et.strftime("%Y-%m-%d")
    queue_units = []
    for filing in _group_congress_trades(trades_today):
        bundle_id = congress_bundle_id(filing)
        if has_been_posted("ALERT", bundle_id, today, "FALLBACK"):
            continue
        thread = compose_congress_alert_thread(filing)
        if not thread:
            continue
        queue_units.append(
            {
                "disclosureDate": filing["disclosureDate"] or today,
                "signalType": "ALERT",
                "thread": thread,
                "filing": filing,
                "signal": {"summarySentence": "member_trade_alert"},
                "context": {"window": "FALLBACK", "bundle_id": bundle_id},
            }
        )

    if not queue_units:
        result["reason"] = "no_postable_disclosures"
        return result

    result["attempted"] = True
    result["queued_count"] = enqueue_signal_threads(queue_units, now_et, force_due_now=True)
    dispatch_summary = dispatch_due_threads(now_et)
    posted_now = int(dispatch_summary.get("posted", 0))
    failed_now = int(dispatch_summary.get("failed", 0))
    result["posted_count"] = posted_now
    result["failed_count"] = failed_now
    if failed_now > 0:
        result["reason"] = "posting_failed"
    elif posted_now > 0:
        result["posted"] = True
        result["reason"] = "posted"
    else:
        result["reason"] = "post_deferred"
    return result


def main():
    now_utc = datetime.now(timezone.utc)
    now_et = now_utc.astimezone(ET)
    print(
        "Starting main.py... "
        f"utc={now_utc.isoformat(timespec='seconds')} "
        f"et={now_et.isoformat(timespec='seconds')}"
    )

    new, delta_stats = run_delta()
    print(
        f"Delta: fetched={delta_stats.get('fetched', 0)} "
        f"skipped={delta_stats.get('skipped', 0)} inserted={delta_stats.get('inserted', 0)}"
    )
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

        email_already_sent = has_email_sent_today(today) or _has_email_lock(today)
        db_restored = os.getenv("DB_RESTORED", "true").strip().lower() == "true"
        if email_already_sent:
            print(f"Email already sent for {today}; skipping email send.")
        elif not db_restored and not _has_email_lock(today):
            print(
                f"WARNING: DB was not restored from a previous run. "
                f"Skipping email to avoid duplicate send. "
                f"Lock file and DB dedupe both absent for {today}."
            )
        else:
            print("Sending email...")
            send_summary(trades_today, insights)
            record_email_sent(today, now_et)
            _write_email_lock(today, now_et)
            print("Email sent!")
    else:
        print("No same-day disclosures for email summary.")

    # Run scheduler for scheduled publishing
    scheduler_result = run_scheduler(now_et)
    scheduler_posted = bool(scheduler_result.get("posted"))
    if scheduler_posted:
        print(f"Scheduler posted: {scheduler_result}")
    else:
        print(
            "Scheduler: no action "
            f"(reason={scheduler_result.get('reason')} window={scheduler_result.get('window')})"
        )

    fallback_result = _maybe_post_fallback_summary(
        trades_today=trades_today,
        now_et=now_et,
        scheduler_outcome=scheduler_result,
    )

    if fallback_result["posted"]:
        print("Fallback posted summary thread.")
    elif fallback_result["attempted"]:
        print(f"Fallback attempted but not posted (reason={fallback_result['reason']}).")

    if trades_today and not scheduler_posted and not fallback_result["posted"]:
        print(
            "WARNING: disclosures were emailed but no social post was published "
            f"(scheduler_reason={scheduler_result.get('reason')} fallback_reason={fallback_result['reason']})"
        )

    total_posted = int(scheduler_result.get("posted_count", 0)) + int(fallback_result.get("posted_count", 0))
    print(
        "Publish outcome: "
        f"disclosures={len(trades_today)} "
        f"scheduler_window={scheduler_result.get('window')} "
        f"scheduler_reason={scheduler_result.get('reason')} "
        f"posted_count={total_posted} "
        f"fallback_used={fallback_result['posted']}"
    )

    fatal_reasons = {"composition_failed", "invalid_social_copy", "posting_failed"}
    if scheduler_result.get("reason") in fatal_reasons:
        raise RuntimeError(f"Scheduler failed: {scheduler_result.get('reason')}")
    if fallback_result.get("reason") == "posting_failed":
        raise RuntimeError("Fallback posting failed")


if __name__ == "__main__":
    main()
