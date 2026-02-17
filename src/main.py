import hashlib
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from emailer import send_summary
from insider import find_recent_insider_activity
from insights import build_highlights_text, compute_trade_insights
from notifier import run_delta
from posting_strategy import dispatch_due_threads, enqueue_signal_threads
from scheduler.dedupe_guard import has_been_posted, has_email_sent_today, record_email_sent
from scheduler.select_content import run_scheduler

# Load environment variables
load_dotenv()

ET = ZoneInfo("America/New_York")


def _env_enabled(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _truncate(text: str, limit: int = 280) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def _format_fallback_root(trades_today: list[dict], today: str) -> str:
    tickers = []
    members = []
    for trade in trades_today:
        symbol = str(trade.get("symbol") or "").upper().strip()
        if symbol:
            tickers.append(symbol)
        member = f"{trade.get('firstName', '')} {trade.get('lastName', '')}".strip()
        if member:
            members.append(member)

    top_tickers = ", ".join(sorted(set(tickers))[:3]) or "multiple tickers"
    top_members = ", ".join(sorted(set(members))[:3]) or "multiple members"
    return _truncate(
        f"Congress disclosures update ({today}): {len(trades_today)} new filings. "
        f"Names: {top_members}. Tickers: {top_tickers}. #CongressTrades"
    )


def _fallback_bundle_id(trades_today: list[dict], today: str) -> str:
    parts = []
    for trade in trades_today:
        parts.append(
            "|".join(
                [
                    today,
                    str(trade.get("firstName", "")),
                    str(trade.get("lastName", "")),
                    str(trade.get("symbol", "")),
                    str(trade.get("type", "")),
                    str(trade.get("amount", "")),
                    str(trade.get("transactionDate", "")),
                    str(trade.get("disclosureDate", "")),
                    str(trade.get("link", "")),
                ]
            )
        )
    digest = hashlib.sha256("\n".join(sorted(parts)).encode("utf-8")).hexdigest()[:16]
    return f"fallback-{today}-{digest}"


def _maybe_post_fallback_summary(
    trades_today: list[dict],
    now_et: datetime,
    scheduler_outcome: dict,
) -> dict:
    fallback_enabled = _env_enabled("SCHEDULER_FALLBACK_ENABLED", default=True)
    fallback_mode = os.getenv("SCHEDULER_FALLBACK_MODE", "summary").strip().lower() or "summary"
    scheduler_reason = str(scheduler_outcome.get("reason") or "")
    fallback_eligible_reasons = {"not_in_window", "no_content_selected"}
    result = {
        "enabled": fallback_enabled,
        "mode": fallback_mode,
        "attempted": False,
        "posted": False,
        "reason": "disabled" if not fallback_enabled else "not_eligible",
        "posted_count": 0,
    }

    if not fallback_enabled:
        return result
    if fallback_mode != "summary":
        result["reason"] = "unsupported_mode"
        return result
    if not trades_today:
        result["reason"] = "no_disclosures"
        return result
    if bool(scheduler_outcome.get("posted")):
        result["reason"] = "scheduler_already_posted"
        return result
    if int(scheduler_outcome.get("posted_count", 0)) > 0:
        result["reason"] = "already_posted_this_run"
        return result
    if scheduler_reason not in fallback_eligible_reasons:
        result["reason"] = f"ineligible_reason:{scheduler_reason}"
        return result

    today = now_et.strftime("%Y-%m-%d")
    bundle_id = _fallback_bundle_id(trades_today, today)
    if has_been_posted("FALLBACK_SUMMARY", bundle_id, today, "FALLBACK"):
        result["reason"] = "already_posted"
        return result

    result["attempted"] = True
    thread = [
        {
            "text": _format_fallback_root(trades_today, today),
            "media_symbol": None,
            "media_trade_date": None,
        }
    ]
    queue_unit = {
        "disclosureDate": today,
        "signalType": "FALLBACK_SUMMARY",
        "thread": thread,
        "filing": {"disclosureDate": today, "trades": trades_today},
        "signal": {"summarySentence": "fallback_summary"},
        "context": {"window": "FALLBACK", "bundle_id": bundle_id},
    }
    enqueue_signal_threads([queue_unit], now_et, force_due_now=True)
    dispatch_summary = dispatch_due_threads(now_et)
    posted_now = int(dispatch_summary.get("posted", 0))
    result["posted_count"] = posted_now
    if posted_now > 0:
        result["posted"] = True
        result["reason"] = "posted"
    else:
        result["reason"] = "post_failed_or_deferred"
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

        if has_email_sent_today(today):
            print(f"Email already sent for {today}; skipping email send.")
        else:
            print("Sending email...")
            send_summary(trades_today, insights)
            record_email_sent(today, now_et)
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


if __name__ == "__main__":
    main()
