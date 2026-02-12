import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from tweet_composer import compose_thread


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

    assert len(thread) == 3
    assert all("text" in tweet for tweet in thread)
    assert all(len(tweet["text"]) <= 280 for tweet in thread)
    assert thread[1]["media_symbol"] == "NVDA"


def test_compose_thread_varies_structure():
    filing1, signal1, insight1, context1, stats1 = _sample(symbol="NVDA", member="Jade Stone")
    filing2, signal2, insight2, context2, stats2 = _sample(symbol="MSFT", member="Luke Drew")

    thread1 = compose_thread(filing1, signal1, insight1, context1, stats1)
    thread2 = compose_thread(filing2, signal2, insight2, context2, stats2)

    assert thread1[0]["text"] != thread2[0]["text"]
