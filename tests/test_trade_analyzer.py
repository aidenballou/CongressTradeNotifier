import sys
from datetime import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from trade_analyzer import analyze_filing


def test_analyze_filing_rotation_high_signal():
    filing = {
        "firstName": "Pat",
        "lastName": "Mason",
        "disclosureDate": "2026-01-12",
        "trades": [
            {
                "firstName": "Pat",
                "lastName": "Mason",
                "symbol": "NVDA",
                "type": "Purchase",
                "amount": "$250,001 - $500,000",
                "assetDescription": "NVIDIA tech semiconductor",
                "transactionDate": "2026-01-10",
            },
            {
                "firstName": "Pat",
                "lastName": "Mason",
                "symbol": "WMT",
                "type": "Sale",
                "amount": "$15,001 - $50,000",
                "assetDescription": "consumer staples retailer",
                "transactionDate": "2026-01-10",
            },
        ],
    }

    history = [
        {
            "firstName": "Pat",
            "lastName": "Mason",
            "symbol": "NVDA",
            "type": "Purchase",
            "amount": "$1,001 - $15,000",
            "assetDescription": "NVIDIA tech semiconductor",
            "transactionDate": "2025-12-01",
            "disclosureDate": "2025-12-03",
        },
        {
            "firstName": "Pat",
            "lastName": "Mason",
            "symbol": "NVDA",
            "type": "Purchase",
            "amount": "$1,001 - $15,000",
            "assetDescription": "NVIDIA tech semiconductor",
            "transactionDate": "2025-11-01",
            "disclosureDate": "2025-11-04",
        },
    ]

    result = analyze_filing(filing, history, datetime(2026, 1, 12))

    assert result["signalStrength"] == "HIGH"
    assert result["signalType"] == "ROTATION"
    assert result["diagnostics"]["rotation"] is True


def test_analyze_filing_first_buy_detected():
    filing = {
        "firstName": "Ava",
        "lastName": "Cole",
        "disclosureDate": "2026-01-12",
        "trades": [
            {
                "firstName": "Ava",
                "lastName": "Cole",
                "symbol": "PLTR",
                "type": "Purchase",
                "amount": "$1,001 - $15,000",
                "assetDescription": "software",
                "transactionDate": "2026-01-11",
            }
        ],
    }

    history = [
        {
            "firstName": "Ava",
            "lastName": "Cole",
            "symbol": "MSFT",
            "type": "Purchase",
            "amount": "$1,001 - $15,000",
            "assetDescription": "software",
            "transactionDate": "2025-11-11",
            "disclosureDate": "2025-11-13",
        }
    ]

    result = analyze_filing(filing, history, datetime(2026, 1, 12))

    assert result["diagnostics"]["firstTradeInTicker"] is True
    assert result["signalType"] == "FIRST_BUY"


def test_analyze_filing_first_sell_not_first_buy():
    """First trade in ticker that is a SELL must be FIRST_SELL with exit narrative, not FIRST_BUY."""
    filing = {
        "firstName": "Sam",
        "lastName": "Reed",
        "disclosureDate": "2026-02-11",
        "trades": [
            {
                "firstName": "Sam",
                "lastName": "Reed",
                "symbol": "WMT",
                "type": "Sale",
                "amount": "$15,001 - $50,000",
                "assetDescription": "Walmart consumer staples",
                "transactionDate": "2026-02-10",
            }
        ],
    }

    history = [
        {
            "firstName": "Sam",
            "lastName": "Reed",
            "symbol": "TGT",
            "type": "Purchase",
            "amount": "$1,001 - $15,000",
            "assetDescription": "Target",
            "transactionDate": "2025-06-01",
            "disclosureDate": "2025-06-03",
        }
    ]

    result = analyze_filing(filing, history, datetime(2026, 2, 11))

    assert result["diagnostics"]["firstSellInTicker"] is True
    assert result["diagnostics"]["firstBuyInTicker"] is False
    assert result["signalType"] == "FIRST_SELL"
    assert "first exit" in result["summarySentence"].lower() or "exit" in result["summarySentence"].lower()
    assert "initiated a fresh position" not in result["summarySentence"]


def test_analyze_filing_cluster_detection():
    filing = {
        "firstName": "June",
        "lastName": "Park",
        "disclosureDate": "2026-02-10",
        "trades": [
            {
                "firstName": "June",
                "lastName": "Park",
                "symbol": "SMCI",
                "type": "Purchase",
                "amount": "$15,001 - $50,000",
                "assetDescription": "server tech",
                "transactionDate": "2026-02-09",
            }
        ],
    }

    history = [
        {
            "firstName": "Ben",
            "lastName": "Hall",
            "symbol": "SMCI",
            "type": "Purchase",
            "amount": "$1,001 - $15,000",
            "assetDescription": "server tech",
            "transactionDate": "2026-02-07",
            "disclosureDate": "2026-02-08",
        },
        {
            "firstName": "Mia",
            "lastName": "West",
            "symbol": "SMCI",
            "type": "Purchase",
            "amount": "$1,001 - $15,000",
            "assetDescription": "server tech",
            "transactionDate": "2026-02-08",
            "disclosureDate": "2026-02-09",
        },
    ]

    result = analyze_filing(filing, history, datetime(2026, 2, 10))

    assert result["diagnostics"]["clusteredTrades"] is True


def test_exclude_first_trade_in_ticker_drops_strength_when_decisive():
    """
    Construct a case where cluster (+3) + first-trade (+2) is the only path to HIGH (5).
    Excluding first-trade must drop score to 3 -> MEDIUM.
    """
    filing = {
        "firstName": "Ava",
        "lastName": "Cole",
        "disclosureDate": "2026-02-10",
        "trades": [
            {
                "firstName": "Ava",
                "lastName": "Cole",
                "symbol": "SMCI",
                "type": "Purchase",
                "amount": "$1,001 - $15,000",
                "assetDescription": "server tech",
                "transactionDate": "2026-02-09",
            }
        ],
    }

    history = [
        # Other members cluster in same direction around the event date (±3d window)
        {
            "firstName": "Ben",
            "lastName": "Hall",
            "symbol": "SMCI",
            "type": "Purchase",
            "amount": "$1,001 - $15,000",
            "assetDescription": "server tech",
            "transactionDate": "2026-02-08",
            "disclosureDate": "2026-02-09",
        },
        {
            "firstName": "Mia",
            "lastName": "West",
            "symbol": "SMCI",
            "type": "Purchase",
            "amount": "$1,001 - $15,000",
            "assetDescription": "server tech",
            "transactionDate": "2026-02-07",
            "disclosureDate": "2026-02-08",
        },
        # Ava has history, but not in SMCI, so first trade in ticker remains true
        {
            "firstName": "Ava",
            "lastName": "Cole",
            "symbol": "MSFT",
            "type": "Purchase",
            "amount": "$1,001 - $15,000",
            "assetDescription": "software",
            "transactionDate": "2025-12-01",
            "disclosureDate": "2025-12-03",
        },
    ]

    baseline = analyze_filing(filing, history, datetime(2026, 2, 10))
    assert baseline["diagnostics"]["clusteredTrades"] is True
    assert baseline["diagnostics"]["firstTradeInTicker"] is True
    assert baseline["diagnostics"]["score"] == 5
    assert baseline["signalStrength"] == "HIGH"

    excluded = analyze_filing(
        filing,
        history,
        datetime(2026, 2, 10),
        exclude_first_trade_in_ticker=True,
    )
    assert excluded["diagnostics"]["clusteredTrades"] is True
    assert excluded["diagnostics"]["firstTradeInTicker"] is True
    assert excluded["diagnostics"]["score"] == 3
    assert excluded["signalStrength"] == "MEDIUM"


def test_exclude_first_trade_in_ticker_does_not_affect_other_high_signals():
    """
    A filing that is HIGH due to rotation (+4) + repeat buys (+1) should remain HIGH.
    Ensure neither ticker is a first-trade for the member to avoid first-trade confounding.
    """
    filing = {
        "firstName": "Pat",
        "lastName": "Mason",
        "disclosureDate": "2026-01-12",
        "trades": [
            {
                "firstName": "Pat",
                "lastName": "Mason",
                "symbol": "NVDA",
                "type": "Purchase",
                "amount": "$15,001 - $50,000",
                "assetDescription": "NVIDIA tech semiconductor",
                "transactionDate": "2026-01-10",
            },
            {
                "firstName": "Pat",
                "lastName": "Mason",
                "symbol": "WMT",
                "type": "Sale",
                "amount": "$15,001 - $50,000",
                "assetDescription": "consumer staples retailer",
                "transactionDate": "2026-01-10",
            },
        ],
    }

    history = [
        # Prior NVDA buy within a year -> repeat buys
        {
            "firstName": "Pat",
            "lastName": "Mason",
            "symbol": "NVDA",
            "type": "Purchase",
            "amount": "$1,001 - $15,000",
            "assetDescription": "NVIDIA tech semiconductor",
            "transactionDate": "2025-12-01",
            "disclosureDate": "2025-12-03",
        },
        # Prior WMT trade so the sell is not a first trade in ticker
        {
            "firstName": "Pat",
            "lastName": "Mason",
            "symbol": "WMT",
            "type": "Purchase",
            "amount": "$1,001 - $15,000",
            "assetDescription": "consumer staples retailer",
            "transactionDate": "2025-10-01",
            "disclosureDate": "2025-10-03",
        },
    ]

    baseline = analyze_filing(filing, history, datetime(2026, 1, 12))
    assert baseline["diagnostics"]["rotation"] is True
    assert baseline["diagnostics"]["repeatBuys"] is True
    assert baseline["diagnostics"]["score"] >= 5
    assert baseline["signalStrength"] == "HIGH"

    excluded = analyze_filing(
        filing,
        history,
        datetime(2026, 1, 12),
        exclude_first_trade_in_ticker=True,
    )
    assert excluded["signalStrength"] == "HIGH"
