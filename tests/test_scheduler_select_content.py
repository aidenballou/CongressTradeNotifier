"""Tests for scheduler content selection behavior."""

from datetime import datetime
from zoneinfo import ZoneInfo

import scheduler.select_content as select_content

ET = ZoneInfo("America/New_York")


def test_midday_selects_first_remaining_candidate(monkeypatch):
    """MIDDAY should select the top ranked remaining bundle."""
    monkeypatch.setattr(select_content, "has_window_posted_today", lambda *_args: False)
    monkeypatch.setattr(select_content, "has_been_posted", lambda *_args: False)
    monkeypatch.setattr(select_content, "bundle_id", lambda bundle: bundle["id"])

    scored_bundles = [
        ({"id": "bundle_a"}, {"diagnostics": {"score": 10}}, 10),
        ({"id": "bundle_b"}, {"diagnostics": {"score": 9}}, 9),
        ({"id": "bundle_c"}, {"diagnostics": {"score": 8}}, 8),
    ]

    decision = select_content._select_for_midday(
        scored_bundles=scored_bundles,
        threshold=7,
        today="2024-01-02",
        now_et=datetime(2024, 1, 2, 12, 10, tzinfo=ET),
    )

    assert decision is not None
    assert decision.content_type == "ALERT"
    assert decision.bundle_id == "bundle_a"
    assert decision.score == 10
    assert decision.reason == "highest_remaining_bundle"


def test_midday_with_two_candidates_does_not_skip_post(monkeypatch):
    """Regression: two candidates should still allow MIDDAY to post top remaining."""
    monkeypatch.setattr(select_content, "has_window_posted_today", lambda *_args: False)
    monkeypatch.setattr(select_content, "has_been_posted", lambda *_args: False)
    monkeypatch.setattr(select_content, "bundle_id", lambda bundle: bundle["id"])

    scored_bundles = [
        ({"id": "bundle_a"}, {}, 8),
        ({"id": "bundle_b"}, {}, 4),
    ]

    decision = select_content._select_for_midday(
        scored_bundles=scored_bundles,
        threshold=7,
        today="2024-01-02",
        now_et=datetime(2024, 1, 2, 12, 10, tzinfo=ET),
    )

    assert decision is not None
    assert decision.bundle_id == "bundle_a"
    assert decision.score == 8


def test_midday_returns_none_when_top_remaining_below_threshold(monkeypatch):
    """MIDDAY should not pick a lower-ranked bundle when top remaining misses threshold."""
    monkeypatch.setattr(select_content, "has_window_posted_today", lambda *_args: False)
    monkeypatch.setattr(select_content, "has_been_posted", lambda *_args: False)
    monkeypatch.setattr(select_content, "bundle_id", lambda bundle: bundle["id"])

    scored_bundles = [
        ({"id": "bundle_a"}, {}, 6),
        ({"id": "bundle_b"}, {}, 10),
    ]

    decision = select_content._select_for_midday(
        scored_bundles=scored_bundles,
        threshold=7,
        today="2024-01-02",
        now_et=datetime(2024, 1, 2, 12, 10, tzinfo=ET),
    )

    assert decision is None


def test_midday_respects_window_already_posted(monkeypatch):
    """MIDDAY should no-op when that window has already posted."""
    monkeypatch.setattr(select_content, "has_window_posted_today", lambda *_args: True)
    monkeypatch.setattr(select_content, "has_been_posted", lambda *_args: False)
    monkeypatch.setattr(select_content, "bundle_id", lambda bundle: bundle["id"])

    decision = select_content._select_for_midday(
        scored_bundles=[({"id": "bundle_a"}, {}, 10)],
        threshold=7,
        today="2024-01-02",
        now_et=datetime(2024, 1, 2, 12, 10, tzinfo=ET),
    )

    assert decision is None


def test_run_scheduler_midday_picks_top_unposted_bundle(monkeypatch):
    """Scheduler should pick top-ranked candidate among unposted bundles at MIDDAY."""
    recorded = []
    now_et = datetime(2024, 1, 2, 12, 10, tzinfo=ET)

    monkeypatch.setattr(select_content, "get_current_window", lambda _now: "MIDDAY")
    monkeypatch.setattr(select_content, "is_trading_day", lambda _now: True)
    monkeypatch.setattr(select_content, "count_posts_today", lambda _today: 1)
    monkeypatch.setattr(
        select_content,
        "build_bundles_from_db",
        lambda _now, hours=24: [{"id": "bundle_a"}, {"id": "bundle_b"}, {"id": "bundle_c"}],
    )
    monkeypatch.setattr(
        select_content,
        "filter_unposted",
        lambda bundles, _today: [bundle for bundle in bundles if bundle["id"] != "bundle_a"],
    )
    monkeypatch.setattr(select_content, "fetch_recent_trades", lambda days, now_et: [])
    monkeypatch.setattr(
        select_content,
        "_score_and_rank_bundles",
        lambda bundles, _recent, _now: [
            (bundles[0], {}, 9),
            (bundles[1], {}, 8),
        ],
    )
    monkeypatch.setattr(select_content, "compute_threshold", lambda _count: 7)
    monkeypatch.setattr(select_content, "has_window_posted_today", lambda *_args: False)
    monkeypatch.setattr(select_content, "has_been_posted", lambda *_args: False)
    monkeypatch.setattr(select_content, "bundle_id", lambda bundle: bundle["id"])
    monkeypatch.setattr(select_content, "_compose_for_decision", lambda *_args: [{"text": "ok"}])
    monkeypatch.setattr(select_content, "post_thread_directly", lambda *_args: True)
    monkeypatch.setattr(
        select_content,
        "record_post",
        lambda content_type, bundle_id, date, window, posted_at: recorded.append(
            (content_type, bundle_id, date, window, posted_at)
        ),
    )

    result = select_content.run_scheduler(now_et)

    assert result is not None
    assert result["window"] == "MIDDAY"
    assert result["content_type"] == "ALERT"
    assert result["bundle_id"] == "bundle_b"
    assert result["reason"] == "highest_remaining_bundle"
    assert len(recorded) == 1
    assert recorded[0][0] == "ALERT"
    assert recorded[0][1] == "bundle_b"
    assert recorded[0][3] == "MIDDAY"


def test_morning_theme_fallback_skips_when_already_posted_today(monkeypatch):
    """MORNING should not pick SEVEN_DAY_THEME twice on the same day."""
    monkeypatch.setattr(select_content, "has_window_posted_today", lambda *_args: False)
    monkeypatch.setattr(select_content, "has_daily_tape_today", lambda *_args: True)
    monkeypatch.setattr(select_content, "has_seven_day_theme_today", lambda *_args: True)
    monkeypatch.setattr(
        select_content,
        "build_seven_day_theme",
        lambda _now: {"top_5_tickers_by_value": [{"ticker": "AAPL", "value": 1000.0}]},
    )

    decision = select_content._select_for_morning(
        scored_bundles=[],
        threshold=None,
        today="2024-01-02",
        now_et=datetime(2024, 1, 2, 8, 35, tzinfo=ET),
    )

    assert decision is None


def test_evening_no_filings_skips_theme_when_already_posted_today(monkeypatch):
    """EVENING no-filings path should not duplicate SEVEN_DAY_THEME."""
    monkeypatch.setattr(select_content, "has_window_posted_today", lambda *_args: False)
    monkeypatch.setattr(select_content, "has_seven_day_theme_today", lambda *_args: True)
    monkeypatch.setattr(select_content, "build_daily_tape", lambda _now: {"total_filings": 0})
    monkeypatch.setattr(
        select_content,
        "build_seven_day_theme",
        lambda _now: {"top_5_tickers_by_value": [{"ticker": "MSFT", "value": 1200.0}]},
    )

    decision = select_content._select_for_evening(
        scored_bundles=[],
        threshold=None,
        today="2024-01-02",
        now_et=datetime(2024, 1, 2, 17, 5, tzinfo=ET),
    )

    assert decision is None
