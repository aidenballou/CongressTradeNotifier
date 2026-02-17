"""
Engagement metrics: sample, store, and compute baselines by content type and window.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    from db import conn, cursor
except ImportError:
    from src.db import conn, cursor

logger = logging.getLogger(__name__)

SNAPSHOT_WINDOWS = ("1h", "24h")
WINDOW_MINUTES = {"1h": 60, "24h": 1440}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str) -> datetime:
    if not value:
        raise ValueError("empty posted_at")
    if value.endswith("Z"):
        value = value.replace("Z", "+00:00")
    return datetime.fromisoformat(value)


def sample_due_threads(twitter_client: Any) -> int:
    """
    For each posted thread that is past a snapshot window (1h or 24h) and not yet
    sampled for that window, fetch metrics from Twitter and store in engagement_metrics.
    Returns number of (content_hash, tweet_id, window) rows inserted/updated.
    """
    now = _utc_now()
    updated = 0

    cursor.execute(
        """
        SELECT t.content_hash, t.tweet_ids_json, t.posted_at
        FROM posted_thread_ids t
        ORDER BY t.posted_at ASC
        """
    )
    rows = cursor.fetchall()

    for content_hash, tweet_ids_json, posted_at_str in rows:
        try:
            posted_at = _parse_iso(posted_at_str)
        except Exception as e:
            logger.warning("Skip thread %s: invalid posted_at %s: %s", content_hash[:8], posted_at_str, e)
            continue

        try:
            tweet_ids = json.loads(tweet_ids_json)
        except Exception as e:
            logger.warning("Skip thread %s: invalid tweet_ids_json: %s", content_hash[:8], e)
            continue

        if not tweet_ids:
            continue

        for window_label, minutes in WINDOW_MINUTES.items():
            cutoff = posted_at + timedelta(minutes=minutes)
            if now < cutoff:
                continue

            cursor.execute(
                """
                SELECT 1 FROM engagement_metrics
                WHERE content_hash = ? AND snapshot_window = ? LIMIT 1
                """,
                (content_hash, window_label),
            )
            if cursor.fetchone():
                continue

            metrics_map = twitter_client.get_tweet_metrics(tweet_ids)
            sampled_at = now.isoformat()

            for tweet_id in tweet_ids:
                m = metrics_map.get(tweet_id) or {}
                like_count = m.get("like_count", 0) or 0
                retweet_count = m.get("retweet_count", 0) or 0
                reply_count = m.get("reply_count", 0) or 0
                quote_count = m.get("quote_count", 0) or 0
                impression_count = m.get("impression_count")

                cursor.execute(
                    """
                    INSERT OR REPLACE INTO engagement_metrics
                    (content_hash, tweet_id, snapshot_window, sampled_at,
                     like_count, retweet_count, reply_count, quote_count, impression_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        content_hash,
                        tweet_id,
                        window_label,
                        sampled_at,
                        like_count,
                        retweet_count,
                        reply_count,
                        quote_count,
                        impression_count,
                    ),
                )
                updated += 1

            if not metrics_map and tweet_ids:
                logger.debug("No metrics returned for thread %s window %s", content_hash[:8], window_label)

    conn.commit()
    return updated


def engagement_score(like_count: int, retweet_count: int, reply_count: int, quote_count: int) -> float:
    """
    Simple weighted engagement score for ranking (reply > retweet > like > quote).
    """
    return (
        3.0 * reply_count
        + 2.0 * retweet_count
        + 1.0 * like_count
        + 1.5 * quote_count
    )


def get_thread_engagement_for_content_hash(content_hash: str, window: str = "24h") -> Optional[Dict[str, Any]]:
    """
    Aggregate engagement for a thread at a given snapshot window.
    Returns dict with like_count, retweet_count, reply_count, quote_count, impression_count, score
    or None if no data.
    """
    cursor.execute(
        """
        SELECT like_count, retweet_count, reply_count, quote_count, impression_count
        FROM engagement_metrics
        WHERE content_hash = ? AND snapshot_window = ?
        """,
        (content_hash, window),
    )
    rows = cursor.fetchall()
    if not rows:
        return None
    total_likes = sum(r[0] for r in rows)
    total_rt = sum(r[1] for r in rows)
    total_replies = sum(r[2] for r in rows)
    total_quotes = sum(r[3] for r in rows)
    impressions = [r[4] for r in rows if r[4] is not None]
    return {
        "like_count": total_likes,
        "retweet_count": total_rt,
        "reply_count": total_replies,
        "quote_count": total_quotes,
        "impression_count": sum(impressions) if impressions else None,
        "score": engagement_score(total_likes, total_rt, total_replies, total_quotes),
    }


def get_baselines_by_content_and_window(
    min_samples: int = 3,
    window: str = "24h",
) -> List[Tuple[str, str, float, int]]:
    """
    Compute average engagement score by (content_type, window_label) for threads
    that have engagement_metrics at the given snapshot window.
    Returns list of (content_type, window_label, avg_score, sample_count).
    """
    cursor.execute(
        """
        SELECT p.content_type, p.window,
               SUM(e.like_count) AS likes, SUM(e.retweet_count) AS rts,
               SUM(e.reply_count) AS replies, SUM(e.quote_count) AS quotes
        FROM engagement_metrics e
        JOIN posted_content_log p ON p.hash = e.content_hash
        WHERE e.snapshot_window = ?
        GROUP BY e.content_hash, p.content_type, p.window
        """,
        (window,),
    )
    rows = cursor.fetchall()

    by_key: Dict[Tuple[str, str], List[float]] = {}
    for content_type, window_label, likes, rts, replies, quotes in rows:
        key = (content_type, window_label)
        score = engagement_score(likes or 0, rts or 0, replies or 0, quotes or 0)
        by_key.setdefault(key, []).append(score)

    result: List[Tuple[str, str, float, int]] = []
    for (content_type, window_label), scores in by_key.items():
        if len(scores) < min_samples:
            continue
        avg = sum(scores) / len(scores)
        result.append((content_type, window_label, avg, len(scores)))
    result.sort(key=lambda x: -x[2])
    return result


def get_engagement_priors_for_scheduler(
    content_type: str,
    window_label: str,
    snapshot_window: str = "24h",
    min_samples: int = 2,
) -> float:
    """
    Return a prior engagement score (0.0–1.0 scale) for use in scheduler ranking.
    If we have baseline data for this (content_type, window), return normalized score;
    otherwise return 0.5 (neutral).
    """
    baselines = get_baselines_by_content_and_window(min_samples=min_samples, window=snapshot_window)
    if not baselines:
        return 0.5
    scores = [b[2] for b in baselines]
    max_score = max(scores) if scores else 1.0
    for ct, wl, avg, _ in baselines:
        if ct == content_type and wl == window_label:
            return min(1.0, avg / max_score) if max_score > 0 else 0.5
    return 0.5


def engagement_health_report(snapshot_window: str = "24h", min_samples: int = 2) -> str:
    """
    Build a short log-friendly summary of top and bottom performing (content_type, window) patterns.
    Use as scheduler artifact or weekly report.
    """
    baselines = get_baselines_by_content_and_window(min_samples=min_samples, window=snapshot_window)
    if not baselines:
        return "[Engagement] no baselines yet (need 24h metrics)"
    top = baselines[:3]
    bottom = baselines[-2:] if len(baselines) >= 2 else []
    lines = ["[Engagement] baselines (24h):"]
    for ct, wl, avg, n in top:
        lines.append(f"  top: {ct}/{wl} avg_score={avg:.1f} n={n}")
    for ct, wl, avg, n in bottom:
        if (ct, wl) not in [(x[0], x[1]) for x in top]:
            lines.append(f"  low: {ct}/{wl} avg_score={avg:.1f} n={n}")
    return " ".join(lines)
