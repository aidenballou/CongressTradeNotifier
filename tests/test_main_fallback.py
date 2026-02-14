from datetime import datetime
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

import main as main_module  # noqa: E402

ET = ZoneInfo("America/New_York")


def _trade_for_today():
    today = datetime.now(ET).strftime("%Y-%m-%d")
    return {
        "firstName": "Byron",
        "lastName": "Donalds",
        "symbol": "HWM",
        "type": "Sale",
        "amount": "$1,001 - $15,000",
        "transactionDate": "2026-01-08",
        "disclosureDate": today,
        "link": "https://example.com",
    }


def test_main_uses_fallback_when_scheduler_skips(monkeypatch):
    trade = _trade_for_today()
    enqueue_calls = []

    monkeypatch.setattr(main_module, "run_delta", lambda: ([trade], {"fetched": 1, "skipped": 0, "inserted": 1}))
    monkeypatch.setattr(main_module, "find_recent_insider_activity", lambda _trades: {})
    monkeypatch.setattr(main_module, "compute_trade_insights", lambda _trades: {"total_trades": 1})
    monkeypatch.setattr(main_module, "build_highlights_text", lambda _insights: "summary")
    monkeypatch.setattr(main_module, "send_summary", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        main_module,
        "run_scheduler",
        lambda _now: {"posted": False, "reason": "not_in_window", "window": None, "content_type": None, "posted_count": 0},
    )
    monkeypatch.setattr(main_module, "has_been_posted", lambda *_args: False)
    monkeypatch.setattr(
        main_module,
        "enqueue_signal_threads",
        lambda filings, now_et, force_due_now=False: enqueue_calls.append((filings, now_et, force_due_now)) or 1,
    )
    monkeypatch.setattr(main_module, "dispatch_due_threads", lambda _now: {"posted": 1})

    main_module.main()

    assert len(enqueue_calls) == 1
    filings = enqueue_calls[0][0]
    assert len(filings) == 1
    assert filings[0]["signalType"] == "FALLBACK_SUMMARY"
    assert enqueue_calls[0][2] is True


def test_main_skips_fallback_when_scheduler_already_posted(monkeypatch):
    trade = _trade_for_today()
    enqueue_calls = []

    monkeypatch.setattr(main_module, "run_delta", lambda: ([trade], {"fetched": 1, "skipped": 0, "inserted": 1}))
    monkeypatch.setattr(main_module, "find_recent_insider_activity", lambda _trades: {})
    monkeypatch.setattr(main_module, "compute_trade_insights", lambda _trades: {"total_trades": 1})
    monkeypatch.setattr(main_module, "build_highlights_text", lambda _insights: "summary")
    monkeypatch.setattr(main_module, "send_summary", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        main_module,
        "run_scheduler",
        lambda _now: {"posted": True, "reason": "posted", "window": "MORNING", "content_type": "ALERT", "posted_count": 1},
    )
    monkeypatch.setattr(main_module, "has_been_posted", lambda *_args: False)
    monkeypatch.setattr(
        main_module,
        "enqueue_signal_threads",
        lambda filings, now_et, force_due_now=False: enqueue_calls.append((filings, now_et, force_due_now)) or 1,
    )
    monkeypatch.setattr(main_module, "dispatch_due_threads", lambda _now: {"posted": 0})

    main_module.main()

    assert enqueue_calls == []


def test_main_skips_fallback_when_no_disclosures(monkeypatch):
    enqueue_calls = []

    monkeypatch.setattr(main_module, "run_delta", lambda: ([], {"fetched": 0, "skipped": 0, "inserted": 0}))
    monkeypatch.setattr(main_module, "send_summary", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        main_module,
        "run_scheduler",
        lambda _now: {"posted": False, "reason": "not_in_window", "window": None, "content_type": None, "posted_count": 0},
    )
    monkeypatch.setattr(main_module, "has_been_posted", lambda *_args: False)
    monkeypatch.setattr(
        main_module,
        "enqueue_signal_threads",
        lambda filings, now_et, force_due_now=False: enqueue_calls.append((filings, now_et, force_due_now)) or 1,
    )
    monkeypatch.setattr(main_module, "dispatch_due_threads", lambda _now: {"posted": 0})

    main_module.main()

    assert enqueue_calls == []


def test_main_fallback_respects_dedupe(monkeypatch):
    trade = _trade_for_today()
    enqueue_calls = []

    monkeypatch.setattr(main_module, "run_delta", lambda: ([trade], {"fetched": 1, "skipped": 0, "inserted": 1}))
    monkeypatch.setattr(main_module, "find_recent_insider_activity", lambda _trades: {})
    monkeypatch.setattr(main_module, "compute_trade_insights", lambda _trades: {"total_trades": 1})
    monkeypatch.setattr(main_module, "build_highlights_text", lambda _insights: "summary")
    monkeypatch.setattr(main_module, "send_summary", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        main_module,
        "run_scheduler",
        lambda _now: {"posted": False, "reason": "not_in_window", "window": None, "content_type": None, "posted_count": 0},
    )
    monkeypatch.setattr(main_module, "has_been_posted", lambda *_args: True)
    monkeypatch.setattr(
        main_module,
        "enqueue_signal_threads",
        lambda filings, now_et, force_due_now=False: enqueue_calls.append((filings, now_et, force_due_now)) or 1,
    )
    monkeypatch.setattr(main_module, "dispatch_due_threads", lambda _now: {"posted": 1})

    main_module.main()

    assert enqueue_calls == []
