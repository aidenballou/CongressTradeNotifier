import sys
import os
import subprocess
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from tweet_composer import (
    compose_daily_tape_thread,
    compose_member_spotlight_thread,
    compose_seven_day_theme_thread,
    compose_thread,
    validate_social_copy,
)


def _sample(signal_type="CONVICTION", symbol="NVDA", member="Jade Stone"):
    first, last = member.split(" ", 1)
    filing = {
        "firstName": first,
        "lastName": last,
        "disclosureDate": "2026-01-10",
        "trades": [
            {
                "firstName": first,
                "lastName": last,
                "symbol": symbol,
                "type": "Purchase",
                "amount_value": 75000,
                "amount": "$50,001 - $100,000",
                "transactionDate": "2026-01-08",
            }
        ],
    }
    signal = {"signalType": signal_type, "diagnostics": {"score": 7}}
    insight = {
        "hook": "Congress just rotated into AI again.",
        "interpretation": "That could keep semis bid, but momentum can reverse fast.",
        "question": "Front-run or fade?",
    }
    context = {"combinedSummary": "Last analog setup outperformed, but sample size is thin."}
    stats = {"score": 7}
    return filing, signal, insight, context, stats


def test_compose_thread_shape_and_limits():
    filing, signal, insight, context, stats = _sample()

    thread = compose_thread(filing, signal, insight, context, stats)

    assert len(thread) == 2
    assert all("text" in tweet for tweet in thread)
    assert all(len(tweet["text"]) <= 280 for tweet in thread)
    assert thread[0]["media_symbol"] == "NVDA"
    assert "$NVDA" in thread[0]["text"]
    assert "$75K" in thread[0]["text"]
    assert "reported a BUY" in thread[0]["text"]


def test_compose_thread_varies_structure():
    filing1, signal1, insight1, context1, stats1 = _sample(symbol="NVDA", member="Jade Stone")
    filing2, signal2, insight2, context2, stats2 = _sample(symbol="MSFT", member="Luke Drew")

    thread1 = compose_thread(filing1, signal1, insight1, context1, stats1)
    thread2 = compose_thread(filing2, signal2, insight2, context2, stats2)

    assert thread1[0]["text"] != thread2[0]["text"]


def test_compose_thread_stable_across_pythonhashseed():
    repo_root = Path(__file__).resolve().parents[1]
    src_path = str(repo_root / "src")
    code = """
from tweet_composer import compose_thread
filing = {
    "firstName": "Jade",
    "lastName": "Stone",
    "disclosureDate": "2026-01-10",
    "trades": [{"firstName": "Jade", "lastName": "Stone", "symbol": "NVDA", "type": "Purchase", "amount": "$50,001 - $100,000", "transactionDate": "2026-01-08"}],
}
signal = {"signalType": "CONVICTION", "diagnostics": {"score": 7}}
insight = {
    "hook": "Congress just rotated into AI again.",
    "interpretation": "That could keep semis bid, but momentum can reverse fast.",
    "question": "Front-run or fade?",
}
context = {"combinedSummary": "Last analog setup outperformed, but sample size is thin."}
stats = {"score": 7}
thread = compose_thread(filing, signal, insight, context, stats)
print(thread[0]["text"])
""".strip()
    env1 = os.environ.copy()
    env1["PYTHONPATH"] = src_path
    env1["PYTHONHASHSEED"] = "1"
    env2 = os.environ.copy()
    env2["PYTHONPATH"] = src_path
    env2["PYTHONHASHSEED"] = "2"

    out1 = subprocess.check_output([sys.executable, "-c", code], env=env1, text=True).strip()
    out2 = subprocess.check_output([sys.executable, "-c", code], env=env2, text=True).strip()
    assert out1 == out2


def test_daily_tape_root_avoids_dashboard_label_and_formats_ticker():
    tape = {
        "total_filings": 2,
        "largest_trade": {
            "ticker": "NVDA",
            "member_name": "Jade Stone",
            "transaction_type": "Purchase",
            "action_normalized": "BUY",
            "amount_value": 75000,
            "transaction_date": "2026-01-08",
            "disclosure_date": "2026-01-10",
            "days_to_file": 2,
        },
    }

    thread = compose_daily_tape_thread(tape)

    assert len(thread) == 1
    assert not thread[0]["text"].startswith("Daily Tape:")
    assert "$NVDA" in thread[0]["text"]
    assert "$75K" in thread[0]["text"]
    assert len(thread[0]["text"]) <= 280


def test_seven_day_theme_root_avoids_dashboard_label():
    theme = {
        "top_5_tickers_by_value": [
            {"ticker": "NVDA", "value": 125000.0},
            {"ticker": "MSFT", "value": 50000.0},
            {"ticker": "AAPL", "value": 30000.0},
        ],
        "cluster_tickers": [{"ticker": "NVDA", "member_count": 3}],
        "top_cluster": {"ticker": "NVDA", "member_count": 3},
        "top_buyer_member": "Jade Stone",
    }

    thread = compose_seven_day_theme_thread(theme)

    assert len(thread) == 1
    assert not thread[0]["text"].startswith("7-Day Theme:")
    assert "$NVDA" in thread[0]["text"]
    assert "$125K" in thread[0]["text"]
    assert "MSFT ($50K), AAPL ($30K)" in thread[0]["text"]
    assert "$MSFT" not in thread[0]["text"]
    assert len(thread[0]["text"]) <= 280


def test_member_spotlight_does_not_emit_context_reply():
    spotlight = {
        "member": "Jade Stone",
        "ticker": "MSFT",
        "amount_value": 55000.0,
        "transaction_type": "Sale",
        "transaction_date": "2026-01-08",
        "disclosure_date": "2026-01-11",
        "description": "large technology sale",
    }

    thread = compose_member_spotlight_thread(spotlight)

    assert len(thread) == 1
    assert not thread[0]["text"].startswith("Member Spotlight:")
    assert all(not tweet["text"].startswith("Context:") for tweet in thread)
    assert "$MSFT" in thread[0]["text"]
    assert "$55K" in thread[0]["text"]
    assert len(thread[0]["text"]) <= 280


def test_validate_social_copy_blocks_banned_and_metric_only_copy():
    assert not validate_social_copy("Daily Tape: 1 filing in the last 24h.")
    assert not validate_social_copy("Net: all buys buy vs sell bias.")
    assert not validate_social_copy("Jade Stone reported a BUY worth about $75K.", ticker_data_exists=True)
    assert not validate_social_copy("Jade Stone reported a BUY in $NVDA.", amount_data_exists=True)
    assert not validate_social_copy("Jade Stone reported a TRADE in $NVDA worth about $75K.")
    assert not validate_social_copy("Jade Stone reported a BUY in an undisclosed ticker worth about $75K.")


def test_compose_thread_skips_trade_without_action_or_amount():
    filing, signal, insight, context, stats = _sample()
    filing["trades"][0]["type"] = ""
    assert compose_thread(filing, signal, insight, context, stats) == []

    filing, signal, insight, context, stats = _sample()
    filing["trades"][0]["amount"] = ""
    filing["trades"][0]["amount_value"] = 0
    assert compose_thread(filing, signal, insight, context, stats) == []
