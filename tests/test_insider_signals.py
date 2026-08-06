"""Tests for insider-buy signal detection and tweet composition."""

from datetime import datetime, timedelta
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

import insider_signals
from tweet_composer import validate_social_copy


def _trade(
    symbol: str,
    insider_name: str,
    title: str,
    value: float,
    *,
    days_ago: int = 1,
    csuite: bool = False,
    director: bool = False,
    shares: float = 0,
    price: float = 0,
) -> dict:
    tx_date = datetime.utcnow() - timedelta(days=days_ago)
    shares = shares or (value / 10.0 if value else 0)
    price = price or 10.0
    return {
        "symbol": symbol,
        "insider_name": insider_name,
        "title": title,
        "title_lower": title.lower(),
        "transaction_code": "P-Purchase",
        "acquisition_disposition": "A",
        "shares": shares,
        "price": price,
        "value": value,
        "transaction_date": tx_date,
        "filing_date": tx_date,
        "is_open_market_buy": True,
        "is_csuite": csuite,
        "is_director": director,
        "is_ten_percent_owner": False,
        "url": "",
        "raw": {},
    }


def test_detect_cluster_buy_wins_over_csuite():
    """A ticker with 2+ insiders clustering should register as CLUSTER_BUY even with a CEO buy."""

    trades = [
        _trade("ACME", "ALICE SMITH", "Officer: Chief Executive Officer", 500_000, csuite=True),
        _trade("ACME", "BOB JONES", "Director", 150_000, director=True),
        _trade("ACME", "CAROL LEE", "Officer: SVP", 100_000),
    ]
    signals = insider_signals.detect_insider_signals(trades)
    assert len(signals) == 1
    assert signals[0].sub_type == "CLUSTER_BUY"
    assert signals[0].ticker == "ACME"
    assert signals[0].unique_insiders == 3
    assert signals[0].total_value == 750_000
    assert signals[0].bundle_id().startswith("INSIDER|CLUSTER_BUY|ACME|")


def test_detect_csuite_single_buy():
    trades = [
        _trade("NVDA", "JANE DOE", "Officer: Chief Financial Officer", 400_000, csuite=True),
    ]
    signals = insider_signals.detect_insider_signals(trades)
    assert len(signals) == 1
    sig = signals[0]
    assert sig.sub_type == "CSUITE_BUY"
    assert sig.ticker == "NVDA"
    assert sig.unique_insiders == 1


def test_csuite_below_threshold_is_ignored():
    trades = [
        _trade("NVDA", "JANE DOE", "Officer: Chief Financial Officer", 50_000, csuite=True),
    ]
    signals = insider_signals.detect_insider_signals(trades)
    assert signals == []


def test_detect_unusual_size_single_buy():
    trades = [
        _trade("XYZ", "SOMEONE", "VP of Sales", 1_500_000),
    ]
    signals = insider_signals.detect_insider_signals(trades)
    assert len(signals) == 1
    assert signals[0].sub_type == "UNUSUAL_SIZE_BUY"
    assert signals[0].ticker == "XYZ"


def test_signals_sorted_by_score():
    """Cluster signals should outrank single-buy signals of similar aggregate size."""

    trades = [
        _trade("AAA", "A", "Officer: Chief Executive Officer", 400_000, csuite=True),
        _trade("BBB", "B", "Director", 200_000),
        _trade("BBB", "C", "Officer: SVP", 200_000),
        _trade("CCC", "D", "Director", 1_200_000),
    ]
    signals = insider_signals.detect_insider_signals(trades)
    sub_types = [s.sub_type for s in signals]
    # All three setups should register — one per ticker.
    assert set(sub_types) == {"CLUSTER_BUY", "CSUITE_BUY", "UNUSUAL_SIZE_BUY"}
    # Cluster ranks first.
    assert signals[0].sub_type == "CLUSTER_BUY"


def test_compose_cluster_thread_includes_cashtag_and_chart():
    trades = [
        _trade("ACME", "ALICE SMITH", "Officer: Chief Executive Officer", 500_000, csuite=True),
        _trade("ACME", "BOB JONES", "Director", 150_000, director=True),
    ]
    signal = insider_signals.detect_insider_signals(trades)[0]
    thread = insider_signals.compose_insider_alert_thread(signal)

    assert len(thread) == 2
    assert thread[0]["media_symbol"] == "ACME"  # root carries chart
    assert thread[1]["media_symbol"] is None

    root_text = thread[0]["text"]
    assert "$ACME" in root_text
    assert "2 insiders" in root_text
    assert "$650K" in root_text or "$650,000" in root_text or "$650.0K" in root_text

    # All tweets must respect the 280-char ceiling.
    for tweet in thread:
        assert len(tweet["text"]) <= 280


def test_compose_csuite_thread_surfaces_role_and_size():
    trades = [
        _trade("TSLA", "ELON MUSK", "Officer: Chief Executive Officer", 2_000_000, csuite=True),
    ]
    signal = insider_signals.detect_insider_signals(trades)[0]
    thread = insider_signals.compose_insider_alert_thread(signal)

    root_text = thread[0]["text"]
    assert "CEO" in root_text
    assert "$TSLA" in root_text
    assert "$2.0M" in root_text


def test_every_insider_signal_type_composes_valid_social_copy():
    signal_inputs = [
        [
            _trade("ACME", "ALICE SMITH", "Officer: Chief Executive Officer", 500_000, csuite=True),
            _trade("ACME", "BOB JONES", "Director", 150_000, director=True),
        ],
        [_trade("NVDA", "JANE DOE", "Officer: Chief Financial Officer", 400_000, csuite=True)],
        [_trade("XYZ", "SOMEONE", "VP of Sales", 1_500_000)],
    ]

    for trades in signal_inputs:
        signal = insider_signals.detect_insider_signals(trades)[0]
        thread = insider_signals.compose_insider_alert_thread(signal)
        assert len(thread) == 2
        assert all(validate_social_copy(tweet["text"]) for tweet in thread), signal.sub_type


def test_bundle_id_is_stable_per_week():
    base_dt = datetime(2026, 4, 20)  # A Monday — well inside ISO week 17.
    trade = {
        **_trade("ACME", "A", "Director", 1_500_000, director=True),
        "transaction_date": base_dt,
        "filing_date": base_dt,
    }
    signal_a = insider_signals.detect_insider_signals([trade])[0]
    signal_b = insider_signals.detect_insider_signals([trade])[0]
    assert signal_a.bundle_id() == signal_b.bundle_id()
    assert "ACME" in signal_a.bundle_id()
