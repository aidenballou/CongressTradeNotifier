"""Idempotent posting guard via posted_content_log table."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import List, Optional

try:
    from db import conn, cursor
except ImportError:  # pragma: no cover
    from src.db import conn, cursor


def _content_hash(content_type: str, bundle_id: Optional[str], date: str, window: str) -> str:
    """Generate deterministic hash for content posting."""
    payload = f"{content_type}|{bundle_id or ''}|{date}|{window}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def has_been_posted(content_type: str, bundle_id: Optional[str], date: str, window: str) -> bool:
    """Check if this exact content has already been posted."""
    content_hash = _content_hash(content_type, bundle_id, date, window)
    cursor.execute(
        "SELECT 1 FROM posted_content_log WHERE hash = ? LIMIT 1",
        (content_hash,),
    )
    return cursor.fetchone() is not None


def record_post(content_type: str, bundle_id: Optional[str], date: str, window: str, now_et: datetime) -> None:
    """Record a successful post in the log."""
    content_hash = _content_hash(content_type, bundle_id, date, window)
    created_at = now_et.astimezone().isoformat()

    cursor.execute(
        """
        INSERT OR IGNORE INTO posted_content_log
        (content_type, bundle_id, date, window, hash, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (content_type, bundle_id, date, window, content_hash, created_at),
    )
    conn.commit()


def record_posted_tweet_ids(
    content_type: str,
    bundle_id: Optional[str],
    date: str,
    window: str,
    tweet_ids: List[str],
    now_et: datetime,
) -> None:
    """Store tweet IDs for a posted thread so engagement can be sampled later."""
    content_hash = _content_hash(content_type, bundle_id, date, window)
    posted_at = now_et.astimezone().isoformat()
    cursor.execute(
        """
        INSERT OR REPLACE INTO posted_thread_ids (content_hash, tweet_ids_json, posted_at)
        VALUES (?, ?, ?)
        """,
        (content_hash, json.dumps(tweet_ids), posted_at),
    )
    conn.commit()


def count_posts_today(date: str) -> int:
    """Count total posts for a given date."""
    cursor.execute(
        "SELECT COUNT(*) FROM posted_content_log WHERE date = ?",
        (date,),
    )
    row = cursor.fetchone()
    return row[0] if row else 0


def has_daily_tape_today(date: str) -> bool:
    """Check if daily tape was posted today."""
    cursor.execute(
        "SELECT 1 FROM posted_content_log WHERE date = ? AND content_type = 'DAILY_TAPE' LIMIT 1",
        (date,),
    )
    return cursor.fetchone() is not None


def has_seven_day_theme_today(date: str) -> bool:
    """Check if seven day theme was posted today."""
    cursor.execute(
        "SELECT 1 FROM posted_content_log WHERE date = ? AND content_type = 'SEVEN_DAY_THEME' LIMIT 1",
        (date,),
    )
    return cursor.fetchone() is not None


def has_window_posted_today(date: str, window: str) -> bool:
    """Check if this window has already posted something today."""
    cursor.execute(
        "SELECT 1 FROM posted_content_log WHERE date = ? AND window = ? LIMIT 1",
        (date, window),
    )
    return cursor.fetchone() is not None


def has_member_spotlight_recent(member_name: str, days: int = 7) -> bool:
    """Check if this member had a spotlight within the last N days."""
    cursor.execute(
        """
        SELECT 1 FROM posted_content_log
        WHERE content_type = 'MEMBER_SPOTLIGHT'
          AND bundle_id = ?
          AND date >= date('now', ?)
        LIMIT 1
        """,
        (member_name, f"-{days} days"),
    )
    return cursor.fetchone() is not None


def has_email_sent_today(date: str) -> bool:
    """Check if the daily email summary was already sent for this date."""
    cursor.execute(
        "SELECT 1 FROM posted_content_log WHERE date = ? AND content_type = 'EMAIL_DAILY' LIMIT 1",
        (date,),
    )
    return cursor.fetchone() is not None


def record_email_sent(date: str, now_et: datetime) -> None:
    """Record that the daily email summary was sent for this date."""
    record_post("EMAIL_DAILY", None, date, "EMAIL_DAILY", now_et)
