import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from emailer import send_summary
from filing_utils import filter_postable_trades, member_name, normalize_action
from insider import find_recent_insider_activity
from insights import build_highlights_text, compute_trade_insights
from notifier import run_delta
from posting_strategy import dispatch_due_threads, enqueue_signal_threads
from scheduler.dedupe_guard import has_been_posted, has_email_sent_today, record_email_sent
from scheduler.select_content import run_scheduler

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


def _truncate(text: str, limit: int = 280) -> str:
    compact = "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def _human_amount(value: float) -> str:
    if value >= 1_000_000:
        scaled = value / 1_000_000
        return f"${scaled:.1f}M".replace(".0M", "M")
    if value >= 1_000:
        scaled = value / 1_000
        return f"${scaled:.1f}K".replace(".0K", "K")
    return f"${value:,.0f}"


def _amount_bounds(trade: dict) -> tuple[float, float] | None:
    raw = str(trade.get("amount") or trade.get("amount_range") or "")
    values = [float(value.replace(",", "")) for value in re.findall(r"[\d,]+(?:\.\d+)?", raw)]
    if values:
        return min(values), max(values)
    try:
        value = float(trade.get("amount_value") or 0)
    except (TypeError, ValueError):
        return None
    return (value, value) if value > 0 else None


def _format_amount_range(trade: dict) -> str:
    bounds = _amount_bounds(trade)
    if not bounds:
        return "amount undisclosed"
    low, high = bounds
    if low == high:
        return _human_amount(high)
    return f"{_human_amount(low)}–{_human_amount(high)}"


def _member_label(trade: dict) -> str:
    name = member_name(trade) or "A member of Congress"
    source = str(trade.get("source") or "").lower()
    if source == "house":
        return f"Rep. {name}"
    if source == "senate":
        return f"Sen. {name}"
    return name


def _parse_trade_date(value: object) -> datetime | None:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def _timing_line(trades: list[dict]) -> str:
    transaction_dates = [
        parsed for trade in trades if (parsed := _parse_trade_date(trade.get("transactionDate")))
    ]
    lags = []
    for trade in trades:
        transaction_date = _parse_trade_date(trade.get("transactionDate"))
        disclosure_date = _parse_trade_date(trade.get("disclosureDate"))
        if transaction_date and disclosure_date:
            lags.append(max((disclosure_date - transaction_date).days, 0))
    if not transaction_dates or not lags:
        return ""

    earliest = min(transaction_dates)
    latest = max(transaction_dates)
    date_text = earliest.strftime("%b %d").replace(" 0", " ")
    if latest != earliest:
        latest_text = latest.strftime("%b %d").replace(" 0", " ")
        date_text = f"{date_text}–{latest_text}"

    lag_text = str(min(lags))
    if max(lags) != min(lags):
        lag_text = f"{min(lags)}–{max(lags)}"
    trade_word = "Trade" if len(trades) == 1 else "Trades"
    return f"{trade_word} made {date_text}; filed {lag_text} day{'s' if lag_text != '1' else ''} later."


def _format_fallback_root(trades_today: list[dict], today: str) -> str:
    trades = filter_postable_trades(trades_today)
    if not trades:
        return ""

    trades.sort(
        key=lambda trade: (
            -((_amount_bounds(trade) or (0, 0))[1]),
            str(trade.get("symbol") or ""),
        )
    )
    members = list(dict.fromkeys(_member_label(trade) for trade in trades))
    actions = [normalize_action(str(trade.get("type") or trade.get("transaction_type") or "")) for trade in trades]

    if len(trades) == 1:
        trade = trades[0]
        action = "purchase" if actions[0] == "BUY" else "sale"
        ticker = str(trade.get("symbol") or trade.get("ticker") or "").replace("$", "").upper()
        lines = [
            f"{members[0]} disclosed a stock {action}: ${ticker} — {_format_amount_range(trade)}."
        ]
    elif len(trades) <= 3 and len(members) == 1:
        if len(set(actions)) == 1:
            action = "purchases" if actions[0] == "BUY" else "sales"
            lines = [f"{members[0]} disclosed {len(trades)} stock {action}:"]
        else:
            lines = [f"{members[0]} disclosed {len(trades)} stock trades:"]
        for index, trade in enumerate(trades):
            ticker = str(trade.get("symbol") or trade.get("ticker") or "").replace("$", "").upper()
            ticker = f"${ticker}" if index == 0 else ticker
            action_prefix = ""
            if len(set(actions)) > 1:
                action_prefix = "Bought " if actions[index] == "BUY" else "Sold "
            lines.append(f"• {action_prefix}{ticker} — {_format_amount_range(trade)}")
    else:
        buys = actions.count("BUY")
        sales = actions.count("SELL")
        largest = trades[0]
        largest_ticker = str(largest.get("symbol") or largest.get("ticker") or "").replace("$", "").upper()
        actor = members[0] if len(members) == 1 else f"{len(members)} members of Congress"
        lines = [
            f"{actor} disclosed {len(trades)} stock trades: {buys} buys, {sales} sales.",
            f"Largest: {'bought' if actions[0] == 'BUY' else 'sold'} ${largest_ticker} — {_format_amount_range(largest)}.",
        ]

    bounds = [_amount_bounds(trade) for trade in trades]
    known_bounds = [bound for bound in bounds if bound]
    if len(trades) > 1 and known_bounds:
        total_low = sum(bound[0] for bound in known_bounds)
        total_high = sum(bound[1] for bound in known_bounds)
        lines.append(f"Combined disclosed range: {_human_amount(total_low)}–{_human_amount(total_high)}.")

    timing = _timing_line(trades)
    if timing:
        lines.append(timing)

    suffix = "#CongressTrades"
    return f"{_truncate(chr(10).join(lines), 280 - len(suffix) - 1)}\n{suffix}"


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

    tweet_text = _format_fallback_root(trades_today, today)
    if not tweet_text:
        result["reason"] = "no_postable_disclosures"
        return result

    result["attempted"] = True
    thread = [
        {
            "text": tweet_text,
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


if __name__ == "__main__":
    main()
