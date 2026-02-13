"""Queueing, scheduling, anti-spam, and dispatch strategy for tweet threads."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

try:
    from db import conn, cursor
    from scheduler.dedupe_guard import record_post
except ImportError:  # pragma: no cover
    from src.db import conn, cursor
    from src.scheduler.dedupe_guard import record_post

TwitterClient = None

ET = ZoneInfo("America/New_York")
ANTI_SPAM_SECONDS = 120
MAX_RETRIES = 3


def _get_twitter_client_cls():
    global TwitterClient
    if TwitterClient is not None:
        return TwitterClient
    try:
        from twitter_client import TwitterClient as twitter_client_cls
    except ImportError:  # pragma: no cover
        from src.twitter_client import TwitterClient as twitter_client_cls
    TwitterClient = twitter_client_cls
    return TwitterClient


def _to_iso(dt: datetime) -> str:
    return dt.astimezone(ET).replace(microsecond=0).isoformat()


def _from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(ET)


def _get_metadata(key: str) -> str | None:
    cursor.execute("SELECT value FROM metadata WHERE key = ?", (key,))
    row = cursor.fetchone()
    return row[0] if row else None


def _set_metadata(key: str, value: str) -> None:
    cursor.execute(
        "INSERT INTO metadata(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


def _next_business_morning(now_et: datetime) -> datetime:
    target = now_et.astimezone(ET)
    if target.weekday() >= 5:
        days = 7 - target.weekday()
        target = target + timedelta(days=days)
    elif target.hour >= 16:
        target = target + timedelta(days=1)
        if target.weekday() == 5:
            target = target + timedelta(days=2)
        elif target.weekday() == 6:
            target = target + timedelta(days=1)

    return target.replace(hour=9, minute=35, second=0, microsecond=0)


def _schedule_for(now_et: datetime) -> datetime:
    now_et = now_et.astimezone(ET)
    morning_cutoff = now_et.replace(hour=9, minute=35, second=0, microsecond=0)
    close_cutoff = now_et.replace(hour=16, minute=0, second=0, microsecond=0)

    if now_et < morning_cutoff:
        return morning_cutoff
    if now_et >= close_cutoff:
        return _next_business_morning(now_et)
    return now_et


def _stable_queue_key(unit: Dict[str, Any]) -> str:
    """Deterministic queue key stable across process restarts (sha256 over payload)."""
    disclosure_date = str(unit.get("disclosureDate") or "")
    signal_type = str(unit.get("signalType") or "OTHER")
    root = ""
    thread = unit.get("thread") or []
    if thread:
        root = str(thread[0].get("text") or "")
    payload = f"{disclosure_date}|{signal_type}|{root}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{disclosure_date}|{signal_type}|{digest[:16]}"


def _merge_units_for_day(day: str, units: List[Dict[str, Any]]) -> Dict[str, Any]:
    all_trades: List[Dict[str, Any]] = []
    all_symbols: List[str] = []
    all_members: List[str] = []
    summaries: List[str] = []

    for unit in units:
        filing = unit.get("filing") or {}
        trades = filing.get("trades") if isinstance(filing.get("trades"), list) else [filing]
        for trade in trades:
            all_trades.append(trade)
            symbol = str(trade.get("symbol") or trade.get("ticker") or "").upper().strip()
            if symbol:
                all_symbols.append(symbol)
            member = str(trade.get("member_name") or f"{trade.get('firstName', '')} {trade.get('lastName', '')}").strip()
            if member:
                all_members.append(member)

        signal = unit.get("signal") or {}
        summary = str(signal.get("summarySentence") or "")
        if summary:
            summaries.append(summary)

    unique_symbols = sorted(set(all_symbols))
    unique_members = sorted(set(all_members))
    lead_symbols = ", ".join(unique_symbols[:3]) if unique_symbols else "multiple names"

    root = (
        f"Congress just lined up around {lead_symbols}. "
        f"{len(unique_members)} members placed high-conviction trades in the same filing cycle. "
        "Could be real positioning, could be headline noise. Front-run or fade?"
    )
    tweet2 = (
        f"Stats check: {len(all_trades)} trades across {len(unique_symbols)} tickers. "
        f"Signal overlap: {len(units)} HIGH alerts collapsed into one narrative thread."
    )
    historical_hint = summaries[0] if summaries else "Recent analogs were mixed, so confidence should stay probabilistic."
    tweet3 = f"Historical lens: {historical_hint} Treat this as context, not certainty."

    thread = [
        {"text": root[:280], "media_symbol": None, "media_trade_date": None},
        {"text": tweet2[:280], "media_symbol": unique_symbols[0] if unique_symbols else None, "media_trade_date": None},
        {"text": tweet3[:280], "media_symbol": None, "media_trade_date": None},
    ]

    return {
        "disclosureDate": day,
        "signalType": "CLUSTER",
        "thread": thread,
        "filing": {
            "disclosureDate": day,
            "trades": all_trades,
        },
    }


def _apply_same_day_merge(units: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for unit in units:
        day = str(unit.get("disclosureDate") or unit.get("filing", {}).get("disclosureDate") or "")
        grouped.setdefault(day, []).append(unit)

    merged: List[Dict[str, Any]] = []
    for day, group in grouped.items():
        if day and len(group) > 1:
            merged.append(_merge_units_for_day(day, group))
        else:
            merged.extend(group)
    return merged


def enqueue_signal_threads(
    filings: List[Dict[str, Any]],
    now_et: datetime,
    *,
    force_due_now: bool = False,
) -> int:
    """Queue prepared HIGH-signal thread payloads for posting."""

    if not filings:
        return 0

    queued = 0
    units = _apply_same_day_merge(filings)

    for unit in units:
        thread = unit.get("thread") or []
        if not thread:
            continue

        queue_key = unit.get("queue_key") or _stable_queue_key(unit)
        schedule_time = now_et if force_due_now else _schedule_for(now_et)
        payload = {
            "thread": thread,
            "filing": unit.get("filing") or {},
            "signal": unit.get("signal") or {},
            "context": unit.get("context") or {},
            "content_type": unit.get("signalType") or "OTHER",
            "disclosure_date": (
                unit.get("disclosureDate")
                or (unit.get("filing") or {}).get("disclosureDate")
                or ""
            ),
            "created_at": _to_iso(now_et),
        }

        cursor.execute(
            """
            INSERT OR IGNORE INTO tweet_queue
            (queue_key, status, scheduled_for, payload_json, attempt_count, created_at, updated_at)
            VALUES (?, 'PENDING', ?, ?, 0, ?, ?)
            """,
            (
                queue_key,
                _to_iso(schedule_time),
                json.dumps(payload),
                _to_iso(now_et),
                _to_iso(now_et),
            ),
        )
        if cursor.rowcount > 0:
            queued += 1

    conn.commit()
    return queued


def _defer_queue_item(queue_id: int, scheduled_for: datetime, now_et: datetime) -> None:
    cursor.execute(
        """
        UPDATE tweet_queue
        SET status = 'PENDING', scheduled_for = ?, updated_at = ?
        WHERE id = ?
        """,
        (_to_iso(scheduled_for), _to_iso(now_et), queue_id),
    )
    conn.commit()


def dispatch_due_threads(now_et: datetime) -> Dict[str, Any]:
    """Dispatch due queued threads with anti-spam and retry semantics."""

    now_et = now_et.astimezone(ET)
    summary = {
        "pending": 0,
        "posted": 0,
        "deferred": 0,
        "failed": 0,
    }

    cursor.execute(
        """
        SELECT id, queue_key, scheduled_for, payload_json, attempt_count
        FROM tweet_queue
        WHERE status = 'PENDING' AND scheduled_for <= ?
        ORDER BY scheduled_for ASC, id ASC
        LIMIT 20
        """,
        (_to_iso(now_et),),
    )
    rows = cursor.fetchall()
    summary["pending"] = len(rows)

    if not rows:
        return summary

    client_cls = _get_twitter_client_cls()
    client = client_cls()

    for row in rows:
        queue_id, _queue_key, _scheduled_for, payload_json, attempt_count = row
        cursor.execute(
            "UPDATE tweet_queue SET status = 'POSTING', updated_at = ? WHERE id = ?",
            (_to_iso(now_et), queue_id),
        )
        conn.commit()

        try:
            payload = json.loads(payload_json)
            thread = payload.get("thread") or []
            if not thread:
                raise ValueError("Queue payload missing thread")

            last_root = _get_metadata("last_root_posted_at")
            if last_root:
                last_dt = _from_iso(last_root)
                minimum_next = last_dt + timedelta(seconds=ANTI_SPAM_SECONDS)
                if now_et < minimum_next:
                    _defer_queue_item(queue_id, minimum_next, now_et)
                    summary["deferred"] += 1
                    continue

            client.post_thread(thread, min_delay_seconds=20, max_delay_seconds=60)

            cursor.execute(
                """
                UPDATE tweet_queue
                SET status = 'POSTED', posted_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (_to_iso(now_et), _to_iso(now_et), queue_id),
            )
            conn.commit()
            _set_metadata("last_root_posted_at", _to_iso(now_et))
            content_type = str(payload.get("content_type") or "").strip()
            disclosure_date = str(payload.get("disclosure_date") or "").strip()
            if content_type and disclosure_date:
                context = payload.get("context") or {}
                window = str(context.get("window") or "QUEUE")
                bundle_id = context.get("bundle_id")
                record_post(
                    content_type=content_type,
                    bundle_id=str(bundle_id) if bundle_id else None,
                    date=disclosure_date,
                    window=window,
                    now_et=now_et,
                )
            summary["posted"] += 1

        except Exception as exc:
            attempts = int(attempt_count or 0) + 1
            if attempts >= MAX_RETRIES:
                cursor.execute(
                    """
                    UPDATE tweet_queue
                    SET status = 'FAILED', attempt_count = ?, last_error = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (attempts, str(exc)[:500], _to_iso(now_et), queue_id),
                )
                summary["failed"] += 1
            else:
                retry_time = now_et + timedelta(minutes=5 * attempts)
                cursor.execute(
                    """
                    UPDATE tweet_queue
                    SET status = 'PENDING', attempt_count = ?, scheduled_for = ?, last_error = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (attempts, _to_iso(retry_time), str(exc)[:500], _to_iso(now_et), queue_id),
                )
                summary["deferred"] += 1
            conn.commit()

    return summary


