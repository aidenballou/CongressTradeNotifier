"""Tests for deduplication guard."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from scheduler.dedupe_guard import (
    count_posts_today,
    has_been_posted,
    has_daily_tape_today,
    has_window_posted_today,
    record_post,
)

ET = ZoneInfo("America/New_York")


@pytest.fixture
def clean_db():
    """Clean posted_content_log table before each test."""
    try:
        from db import conn, cursor
    except ImportError:
        from src.db import conn, cursor

    cursor.execute("DELETE FROM posted_content_log")
    conn.commit()
    yield
    cursor.execute("DELETE FROM posted_content_log")
    conn.commit()


def test_record_and_check_post(clean_db):
    """Test recording and checking posts."""
    now_et = datetime.now(ET)
    today = now_et.strftime("%Y-%m-%d")

    # Initially not posted
    assert has_been_posted("ALERT", "test_bundle_123", today, "MORNING") is False

    # Record post
    record_post("ALERT", "test_bundle_123", today, "MORNING", now_et)

    # Now should be posted
    assert has_been_posted("ALERT", "test_bundle_123", today, "MORNING") is True


def test_different_content_types_dont_conflict(clean_db):
    """Test that different content types don't conflict."""
    now_et = datetime.now(ET)
    today = now_et.strftime("%Y-%m-%d")

    record_post("ALERT", "bundle_1", today, "MORNING", now_et)
    record_post("DAILY_TAPE", None, today, "MORNING", now_et)

    # Both should be recorded
    assert has_been_posted("ALERT", "bundle_1", today, "MORNING") is True
    assert has_been_posted("DAILY_TAPE", None, today, "MORNING") is True


def test_same_content_different_window(clean_db):
    """Test that same content in different windows is allowed."""
    now_et = datetime.now(ET)
    today = now_et.strftime("%Y-%m-%d")

    record_post("ALERT", "bundle_1", today, "MORNING", now_et)

    # Same bundle in different window should not be considered posted
    assert has_been_posted("ALERT", "bundle_1", today, "MIDDAY") is False


def test_count_posts_today(clean_db):
    """Test counting posts for a day."""
    now_et = datetime.now(ET)
    today = now_et.strftime("%Y-%m-%d")

    assert count_posts_today(today) == 0

    record_post("ALERT", "bundle_1", today, "MORNING", now_et)
    assert count_posts_today(today) == 1

    record_post("DAILY_TAPE", None, today, "MIDDAY", now_et)
    assert count_posts_today(today) == 2


def test_has_daily_tape_today(clean_db):
    """Test checking if daily tape was posted today."""
    now_et = datetime.now(ET)
    today = now_et.strftime("%Y-%m-%d")

    assert has_daily_tape_today(today) is False

    record_post("DAILY_TAPE", None, today, "MORNING", now_et)
    assert has_daily_tape_today(today) is True

    # Other content types don't count
    record_post("ALERT", "bundle_1", today, "MIDDAY", now_et)
    assert has_daily_tape_today(today) is True  # Still True


def test_has_window_posted_today(clean_db):
    """Test checking if a window has posted today."""
    now_et = datetime.now(ET)
    today = now_et.strftime("%Y-%m-%d")

    assert has_window_posted_today(today, "MORNING") is False

    record_post("ALERT", "bundle_1", today, "MORNING", now_et)
    assert has_window_posted_today(today, "MORNING") is True
    assert has_window_posted_today(today, "MIDDAY") is False
