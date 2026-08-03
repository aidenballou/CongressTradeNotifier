from datetime import datetime
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import pytest

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


def test_fallback_tweet_includes_direction_amounts_and_reporting_lag():
    trades = [
        {
            "firstName": "Gilbert",
            "lastName": "Cisneros",
            "source": "house",
            "symbol": "RBC",
            "type": "Sale",
            "amount": "$1,001 - $15,000",
            "transactionDate": "2026-06-30",
            "disclosureDate": "2026-07-03",
        },
        {
            "firstName": "Gilbert",
            "lastName": "Cisneros",
            "source": "house",
            "symbol": "SFTBY",
            "type": "Sale",
            "amount": "$1,001 - $15,000",
            "transactionDate": "2026-06-30",
            "disclosureDate": "2026-07-03",
        },
    ]

    tweet = main_module._format_fallback_root(trades, "2026-07-03")

    assert tweet == (
        "Rep. Gilbert Cisneros disclosed 2 stock sales:\n"
        "• $RBC — $1K–$15K\n"
        "• SFTBY — $1K–$15K\n"
        "Combined disclosed range: $2K–$30K.\n"
        "Trades made Jun 30; filed 3 days later.\n"
        "#CongressTrades"
    )
    assert len(tweet) <= 280
    assert tweet.count("$") == 7  # Six dollar amounts plus one X cashtag.


def test_fallback_tweet_summarizes_large_batches_with_facts():
    trades = [
        {
            "firstName": "Gilbert",
            "lastName": "Cisneros",
            "source": "house",
            "symbol": symbol,
            "type": action,
            "amount": amount,
            "transactionDate": transaction_date,
            "disclosureDate": "2026-07-03",
        }
        for symbol, action, amount, transaction_date in [
            ("LLY", "Purchase", "$50,001 - $100,000", "2026-06-10"),
            ("IBM", "Purchase", "$15,001 - $50,000", "2026-06-16"),
            ("MSFT", "Sale", "$15,001 - $50,000", "2026-06-16"),
            ("RBC", "Sale", "$1,001 - $15,000", "2026-06-30"),
        ]
    ]

    tweet = main_module._format_fallback_root(trades, "2026-07-03")

    assert "Rep. Gilbert Cisneros disclosed 4 stock trades: 2 buys, 2 sales." in tweet
    assert "Largest: bought $LLY — $50K–$100K." in tweet
    assert "Combined disclosed range: $81K–$215K." in tweet
    assert "Trades made Jun 10–Jun 30; filed 3–23 days later." in tweet
    assert len(tweet) <= 280


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
        lambda _now: {
            "posted": False,
            "reason": "no_high_quality_content",
            "window": "MORNING",
            "content_type": None,
            "posted_count": 0,
        },
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


def test_main_fails_loudly_on_scheduler_logic_error(monkeypatch):
    monkeypatch.setattr(main_module, "run_delta", lambda: ([], {"fetched": 0, "skipped": 0, "inserted": 0}))
    monkeypatch.setattr(
        main_module,
        "run_scheduler",
        lambda _now: {
            "posted": False,
            "reason": "invalid_social_copy",
            "window": "MORNING",
            "content_type": "INSIDER_ALERT",
            "posted_count": 0,
        },
    )

    with pytest.raises(RuntimeError, match="Scheduler failed: invalid_social_copy"):
        main_module.main()


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
