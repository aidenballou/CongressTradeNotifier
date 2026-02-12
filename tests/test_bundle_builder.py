"""Tests for bundle builder dedupe behavior."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

try:
    from analytics.bundle_builder import bundle_id, filter_unposted
except ImportError:  # pragma: no cover
    from src.analytics.bundle_builder import bundle_id, filter_unposted

try:
    from scheduler.dedupe_guard import record_post
except ImportError:  # pragma: no cover
    from src.scheduler.dedupe_guard import record_post

ET = ZoneInfo("America/New_York")


@pytest.fixture
def clean_posted_content_log():
    """Isolate posted_content_log between tests."""
    try:
        from db import conn, cursor
    except ImportError:  # pragma: no cover
        from src.db import conn, cursor

    cursor.execute("DELETE FROM posted_content_log")
    conn.commit()
    yield cursor
    cursor.execute("DELETE FROM posted_content_log")
    conn.commit()


def _bundle(member_name: str, disclosure_date: str) -> dict:
    first, last = (member_name.split(" ", 1) + [""])[:2]
    return {
        "firstName": first,
        "lastName": last,
        "member_name": member_name,
        "disclosureDate": disclosure_date,
        "transactionDate": disclosure_date,
        "trades": [],
    }


def test_filter_unposted_excludes_bundle_posted_yesterday(clean_posted_content_log):
    now_et = datetime(2026, 2, 12, 9, 0, tzinfo=ET)
    yesterday = "2026-02-11"
    today = "2026-02-12"
    bundle = _bundle("Jane Doe", yesterday)
    bid = bundle_id(bundle)

    record_post("ALERT", bid, yesterday, "MIDDAY", now_et)

    kept = filter_unposted([bundle], today)
    assert kept == []


def test_filter_unposted_excludes_bundle_posted_today(clean_posted_content_log):
    now_et = datetime(2026, 2, 12, 9, 0, tzinfo=ET)
    today = "2026-02-12"
    bundle = _bundle("Alice Smith", today)
    bid = bundle_id(bundle)

    record_post("ALERT", bid, today, "MORNING", now_et)

    kept = filter_unposted([bundle], today)
    assert kept == []


def test_filter_unposted_keeps_never_posted_bundle(clean_posted_content_log):
    today = "2026-02-12"
    bundle = _bundle("Bob Jones", today)
    kept = filter_unposted([bundle], today)
    assert kept == [bundle]


def test_filter_unposted_ignores_non_alert_records(clean_posted_content_log):
    now_et = datetime(2026, 2, 12, 9, 0, tzinfo=ET)
    today = "2026-02-12"
    yesterday = "2026-02-11"
    bundle = _bundle("Cara White", yesterday)
    bid = bundle_id(bundle)

    record_post("DAILY_TAPE", bid, yesterday, "MIDDAY", now_et)

    kept = filter_unposted([bundle], today)
    assert kept == [bundle]


def test_filter_unposted_ignores_null_bundle_ids(clean_posted_content_log):
    now_et = datetime(2026, 2, 12, 9, 0, tzinfo=ET)
    today = "2026-02-12"
    bundle = _bundle("Drew Green", today)

    record_post("ALERT", None, today, "MORNING", now_et)

    kept = filter_unposted([bundle], today)
    assert kept == [bundle]
