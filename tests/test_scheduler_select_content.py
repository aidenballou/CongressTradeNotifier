"""Tests for scheduler content selection behavior."""

from datetime import datetime
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

import scheduler.select_content as select_content

ET = ZoneInfo("America/New_York")
VALID_COPY = "Jade Stone reported a BUY in $NVDA worth about $75K. Why it matters: high-signal filing."


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
    # Insider-alert fallback must also be empty for this test to isolate threshold behavior.
    monkeypatch.setattr(select_content, "find_top_insider_signal", lambda: None)
    monkeypatch.setattr(select_content, "has_insider_alert_recent", lambda *_a, **_k: False)

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
    monkeypatch.setattr(select_content, "compute_threshold", lambda _count, _window=None: 7)
    monkeypatch.setattr(select_content, "has_window_posted_today", lambda *_args: False)
    monkeypatch.setattr(select_content, "has_been_posted", lambda *_args: False)
    monkeypatch.setattr(select_content, "bundle_id", lambda bundle: bundle["id"])
    monkeypatch.setattr(select_content, "_compose_for_decision", lambda *_args, **_kwargs: [{"text": VALID_COPY}])
    monkeypatch.setattr(select_content, "enqueue_signal_threads", lambda *_args, **_kwargs: 1)
    monkeypatch.setattr(select_content, "dispatch_due_threads", lambda *_args, **_kwargs: {"posted": 1})
    monkeypatch.setattr(
        select_content,
        "_log_decision",
        lambda *_args, **_kwargs: recorded.append("logged"),
    )

    result = select_content.run_scheduler(now_et)

    assert result is not None
    assert result["posted"] is True
    assert result["window"] == "MIDDAY"
    assert result["content_type"] == "ALERT"
    assert result["bundle_id"] == "bundle_b"
    assert result["reason"] == "posted"
    assert len(recorded) == 1


def test_run_scheduler_enqueues_selected_content_as_due_now(monkeypatch):
    """Regression: selected window content should be queue-due in the same run."""
    enqueue_calls = []
    now_et = datetime(2024, 1, 2, 8, 35, tzinfo=ET)

    monkeypatch.setattr(select_content, "get_current_window", lambda _now: "MORNING")
    monkeypatch.setattr(select_content, "is_trading_day", lambda _now: True)
    monkeypatch.setattr(select_content, "count_posts_today", lambda _today: 0)
    monkeypatch.setattr(select_content, "build_bundles_from_db", lambda _now, hours=24: [{"id": "bundle_a"}])
    monkeypatch.setattr(select_content, "filter_unposted", lambda bundles, _today: bundles)
    monkeypatch.setattr(select_content, "fetch_recent_trades", lambda days, now_et: [])
    monkeypatch.setattr(select_content, "_score_and_rank_bundles", lambda *_args: [({"id": "bundle_a"}, {}, 9)])
    monkeypatch.setattr(select_content, "compute_threshold", lambda _count, _window=None: 7)
    monkeypatch.setattr(select_content, "has_window_posted_today", lambda *_args: False)
    monkeypatch.setattr(select_content, "has_been_posted", lambda *_args: False)
    monkeypatch.setattr(select_content, "bundle_id", lambda bundle: bundle["id"])
    monkeypatch.setattr(
        select_content,
        "_compose_for_decision",
        lambda *_args, **_kwargs: [{"text": VALID_COPY, "media_symbol": None, "media_trade_date": None}],
    )
    monkeypatch.setattr(
        select_content,
        "enqueue_signal_threads",
        lambda filings, posted_at, **kwargs: enqueue_calls.append((filings, posted_at, kwargs)) or 1,
    )
    monkeypatch.setattr(select_content, "dispatch_due_threads", lambda *_args, **_kwargs: {"posted": 1})
    result = select_content.run_scheduler(now_et)

    assert result is not None
    assert result["posted"] is True
    assert result["reason"] == "posted"
    assert len(enqueue_calls) == 1
    assert enqueue_calls[0][2].get("force_due_now") is True


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
    # Also suppress the insider-alert fallback for this focused test.
    monkeypatch.setattr(select_content, "find_top_insider_signal", lambda: None)
    monkeypatch.setattr(select_content, "has_insider_alert_recent", lambda *_a, **_k: False)

    decision = select_content._select_for_morning(
        scored_bundles=[],
        threshold=None,
        today="2024-01-02",
        now_et=datetime(2024, 1, 2, 8, 35, tzinfo=ET),
    )

    assert decision is None


def test_run_scheduler_calls_dispatch_when_outside_window(monkeypatch):
    """Queue drain: dispatch_due_threads is called even when not in any posting window."""
    dispatch_calls = []
    monkeypatch.setattr(
        select_content,
        "dispatch_due_threads",
        lambda now_et: dispatch_calls.append(now_et) or {"posted": 0, "pending": 0, "deferred": 0, "failed": 0},
    )
    monkeypatch.setattr(select_content, "get_current_window", lambda _now: None)
    now_et = datetime(2024, 1, 2, 10, 0, tzinfo=ET)
    result = select_content.run_scheduler(now_et)
    assert result is not None
    assert result["posted"] is False
    assert result["reason"] == "not_in_window"
    assert result["posted_count"] == 0
    assert len(dispatch_calls) == 1
    assert dispatch_calls[0] == now_et


def test_run_scheduler_calls_dispatch_on_non_trading_day(monkeypatch):
    """Queue drain: dispatch_due_threads is called even on weekend/non-trading day."""
    dispatch_calls = []
    monkeypatch.setattr(
        select_content,
        "dispatch_due_threads",
        lambda now_et: dispatch_calls.append(now_et) or {"posted": 0, "pending": 0, "deferred": 0, "failed": 0},
    )
    monkeypatch.setattr(select_content, "get_current_window", lambda _now: "MORNING")
    monkeypatch.setattr(select_content, "is_trading_day", lambda _now: False)
    now_et = datetime(2024, 1, 6, 8, 35, tzinfo=ET)  # Saturday
    result = select_content.run_scheduler(now_et)
    assert result is not None
    assert result["posted"] is False
    assert result["reason"] == "not_trading_day"
    assert result["posted_count"] == 0
    assert len(dispatch_calls) == 1
    assert dispatch_calls[0] == now_et


def test_midday_falls_back_to_insider_alert_when_nothing_qualifies(monkeypatch):
    """MIDDAY with no qualifying congressional bundle should pick an INSIDER_ALERT."""

    class _FakeSignal:
        sub_type = "CLUSTER_BUY"
        ticker = "NVDA"
        score = 72.0

        def bundle_id(self):
            return "INSIDER|CLUSTER_BUY|NVDA|2026-W17"

    monkeypatch.setattr(select_content, "has_window_posted_today", lambda *_args: False)
    monkeypatch.setattr(select_content, "has_been_posted", lambda *_args: False)
    monkeypatch.setattr(select_content, "has_insider_alert_recent", lambda *_a, **_k: False)
    monkeypatch.setattr(select_content, "find_top_insider_signal", lambda: _FakeSignal())
    monkeypatch.setattr(select_content, "bundle_id", lambda bundle: bundle["id"])

    # Top bundle exists but score is below threshold so ALERT cannot post.
    scored_bundles = [({"id": "bundle_a"}, {}, 3)]
    decision = select_content._select_for_midday(
        scored_bundles=scored_bundles,
        threshold=7,
        today="2026-04-21",
        now_et=datetime(2026, 4, 21, 12, 10, tzinfo=ET),
    )

    assert decision is not None
    assert decision.content_type == "INSIDER_ALERT"
    assert decision.bundle_id == "INSIDER|CLUSTER_BUY|NVDA|2026-W17"
    assert decision.reason == "insider_cluster_buy"
    assert decision.insider_signal is not None


def test_insider_composition_reuses_selection_snapshot(monkeypatch):
    class _FakeSignal:
        ticker = "NVDA"

        def bundle_id(self):
            return "INSIDER|CSUITE_BUY|NVDA|2026-W17"

    signal = _FakeSignal()
    decision = select_content.ContentDecision(
        "INSIDER_ALERT",
        signal.bundle_id(),
        55,
        "insider_csuite_buy",
        insider_signal=signal,
    )
    monkeypatch.setattr(
        select_content,
        "find_top_insider_signal",
        lambda: (_ for _ in ()).throw(AssertionError("must not refetch")),
    )
    monkeypatch.setattr(select_content, "compose_insider_alert_thread", lambda selected: [{"text": selected.ticker}])

    assert select_content._compose_for_decision(decision, datetime(2026, 4, 21, 12, 10, tzinfo=ET)) == [
        {"text": "NVDA"}
    ]


def test_insider_alert_skips_when_ticker_recently_posted(monkeypatch):
    """Dedupe: if we've already tweeted about this ticker in the last 7 days, skip."""

    class _FakeSignal:
        sub_type = "CSUITE_BUY"
        ticker = "AAPL"
        score = 55.0

        def bundle_id(self):
            return "INSIDER|CSUITE_BUY|AAPL|2026-W17"

    monkeypatch.setattr(select_content, "find_top_insider_signal", lambda: _FakeSignal())
    monkeypatch.setattr(select_content, "has_insider_alert_recent", lambda *_a, **_k: True)

    assert select_content._select_insider_alert("2026-04-21") is None


def test_insider_alert_returns_none_when_no_signal(monkeypatch):
    monkeypatch.setattr(select_content, "find_top_insider_signal", lambda: None)
    monkeypatch.setattr(select_content, "has_insider_alert_recent", lambda *_a, **_k: False)
    assert select_content._select_insider_alert("2026-04-21") is None


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
    # Suppress insider-alert fallback for this focused test.
    monkeypatch.setattr(select_content, "find_top_insider_signal", lambda: None)
    monkeypatch.setattr(select_content, "has_insider_alert_recent", lambda *_a, **_k: False)

    decision = select_content._select_for_evening(
        scored_bundles=[],
        threshold=None,
        today="2024-01-02",
        now_et=datetime(2024, 1, 2, 17, 5, tzinfo=ET),
    )

    assert decision is None


def test_morning_low_value_daily_tape_fallback_is_skipped(monkeypatch):
    monkeypatch.setattr(select_content, "has_window_posted_today", lambda *_args: False)
    monkeypatch.setattr(select_content, "has_daily_tape_today", lambda *_args: False)
    monkeypatch.setattr(select_content, "has_seven_day_theme_today", lambda *_args: True)
    monkeypatch.setattr(select_content, "_fallback_order_for_window", lambda _window: ["DAILY_TAPE"])
    monkeypatch.setattr(
        select_content,
        "build_daily_tape",
        lambda _now: {"total_filings": 1, "largest_trade": {"amount_value": 5000.0}},
    )

    decision = select_content._select_for_morning(
        scored_bundles=[],
        threshold=None,
        today="2024-01-02",
        now_et=datetime(2024, 1, 2, 8, 35, tzinfo=ET),
    )

    assert decision is None


def test_morning_high_value_daily_tape_fallback_is_selected(monkeypatch):
    monkeypatch.setattr(select_content, "has_window_posted_today", lambda *_args: False)
    monkeypatch.setattr(select_content, "has_daily_tape_today", lambda *_args: False)
    monkeypatch.setattr(select_content, "_fallback_order_for_window", lambda _window: ["DAILY_TAPE"])
    monkeypatch.setattr(
        select_content,
        "build_daily_tape",
        lambda _now: {"total_filings": 1, "largest_trade": {"amount_value": 50000.0}},
    )

    decision = select_content._select_for_morning(
        scored_bundles=[],
        threshold=None,
        today="2024-01-02",
        now_et=datetime(2024, 1, 2, 8, 35, tzinfo=ET),
    )

    assert decision is not None
    assert decision.content_type == "DAILY_TAPE"


def test_low_value_member_spotlight_is_disabled(monkeypatch):
    monkeypatch.setattr(select_content, "has_window_posted_today", lambda *_args: False)
    monkeypatch.setattr(select_content, "build_daily_tape", lambda _now: {"total_filings": 1})
    monkeypatch.setattr(
        select_content,
        "build_member_spotlight",
        lambda _now: {"member": "Jade Stone", "ticker": "NVDA", "amount_value": 5000.0},
    )
    monkeypatch.setattr(select_content, "find_top_insider_signal", lambda: None)
    monkeypatch.setattr(select_content, "has_insider_alert_recent", lambda *_a, **_k: False)

    decision = select_content._select_for_evening(
        scored_bundles=[],
        threshold=None,
        today="2024-01-02",
        now_et=datetime(2024, 1, 2, 17, 5, tzinfo=ET),
    )

    assert decision is None


def test_scheduler_blocks_invalid_social_copy_before_enqueue(monkeypatch):
    enqueue_calls = []
    now_et = datetime(2024, 1, 2, 8, 35, tzinfo=ET)

    monkeypatch.setattr(select_content, "get_current_window", lambda _now: "MORNING")
    monkeypatch.setattr(select_content, "is_trading_day", lambda _now: True)
    monkeypatch.setattr(select_content, "count_posts_today", lambda _today: 0)
    monkeypatch.setattr(select_content, "build_bundles_from_db", lambda _now, hours=24: [{"id": "bundle_a"}])
    monkeypatch.setattr(select_content, "filter_unposted", lambda bundles, _today: bundles)
    monkeypatch.setattr(select_content, "fetch_recent_trades", lambda days, now_et: [])
    monkeypatch.setattr(select_content, "_score_and_rank_bundles", lambda *_args: [({"id": "bundle_a"}, {}, 9)])
    monkeypatch.setattr(select_content, "compute_threshold", lambda _count, _window=None: 7)
    monkeypatch.setattr(select_content, "has_window_posted_today", lambda *_args: False)
    monkeypatch.setattr(select_content, "has_been_posted", lambda *_args: False)
    monkeypatch.setattr(select_content, "bundle_id", lambda bundle: bundle["id"])
    monkeypatch.setattr(select_content, "_compose_for_decision", lambda *_args, **_kwargs: [{"text": "Daily Tape: 1 filing."}])
    monkeypatch.setattr(select_content, "enqueue_signal_threads", lambda *args, **kwargs: enqueue_calls.append((args, kwargs)) or 1)
    monkeypatch.setattr(select_content, "dispatch_due_threads", lambda *_args, **_kwargs: {"posted": 0})

    result = select_content.run_scheduler(now_et)

    assert result["posted"] is False
    assert result["reason"] == "invalid_social_copy"
    assert enqueue_calls == []


def test_scheduler_drops_invalid_optional_reply_but_posts_valid_root(monkeypatch):
    enqueue_calls = []
    dispatch_results = iter([{"posted": 0}, {"posted": 1}])
    now_et = datetime(2024, 1, 2, 8, 35, tzinfo=ET)

    monkeypatch.setattr(select_content, "get_current_window", lambda _now: "MORNING")
    monkeypatch.setattr(select_content, "is_trading_day", lambda _now: True)
    monkeypatch.setattr(select_content, "count_posts_today", lambda _today: 0)
    monkeypatch.setattr(select_content, "build_bundles_from_db", lambda _now, hours=24: [{"id": "bundle_a"}])
    monkeypatch.setattr(select_content, "filter_unposted", lambda bundles, _today: bundles)
    monkeypatch.setattr(select_content, "fetch_recent_trades", lambda days, now_et: [])
    monkeypatch.setattr(select_content, "_score_and_rank_bundles", lambda *_args: [({"id": "bundle_a"}, {}, 9)])
    monkeypatch.setattr(select_content, "compute_threshold", lambda _count, _window=None: 7)
    monkeypatch.setattr(select_content, "has_window_posted_today", lambda *_args: False)
    monkeypatch.setattr(select_content, "has_been_posted", lambda *_args: False)
    monkeypatch.setattr(select_content, "bundle_id", lambda bundle: bundle["id"])
    monkeypatch.setattr(
        select_content,
        "_compose_for_decision",
        lambda *_args, **_kwargs: [
            {"text": VALID_COPY},
            {"text": "Context: internal dashboard copy"},
        ],
    )
    monkeypatch.setattr(
        select_content,
        "enqueue_signal_threads",
        lambda filings, *_args, **_kwargs: enqueue_calls.append(filings) or 1,
    )
    monkeypatch.setattr(select_content, "dispatch_due_threads", lambda *_args, **_kwargs: next(dispatch_results))

    result = select_content.run_scheduler(now_et)

    assert result["posted"] is True
    assert len(enqueue_calls) == 1
    assert enqueue_calls[0][0]["thread"] == [{"text": VALID_COPY}]


def test_scheduler_surfaces_permanent_queue_failure(monkeypatch):
    monkeypatch.setattr(select_content, "dispatch_due_threads", lambda _now: {"posted": 0, "failed": 1})

    result = select_content.run_scheduler(datetime(2024, 1, 2, 10, 0, tzinfo=ET))

    assert result["posted"] is False
    assert result["reason"] == "posting_failed"
