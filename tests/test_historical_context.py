import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

import historical_context


def test_build_historical_context_with_data(monkeypatch):
    filing = {
        "trades": [
            {
                "firstName": "Lena",
                "lastName": "Gray",
                "symbol": "AAPL",
                "type": "Purchase",
                "transactionDate": "2026-01-10",
                "assetDescription": "tech hardware",
            }
        ]
    }
    signal = {"signalType": "CONVICTION"}

    monkeypatch.setattr(
        historical_context,
        "_fetch_member_rows",
        lambda _member: [
            {
                "ticker": "AAPL",
                "transaction_date": "2025-12-01",
                "transaction_type": "Purchase",
            },
            {
                "ticker": "MSFT",
                "transaction_date": "2025-11-10",
                "transaction_type": "Purchase",
            },
        ],
    )

    def fake_ret(symbol, _date, window_days=30):
        if symbol == "AAPL":
            return 8.0
        if symbol == "MSFT":
            return 4.0
        return 2.0

    monkeypatch.setattr(historical_context, "get_return_after_window", fake_ret)
    monkeypatch.setattr(historical_context, "sector_proxy_return", lambda *_args, **_kwargs: 3.5)

    result = historical_context.build_historical_context(filing, signal, window_days=30)

    assert "last comparable AAPL call" in result["lastTradeOutcome"]
    assert "hit rate" in result["memberWinRate"]
    assert "average 30-day move" in result["avgReturnAfterTrades"]
    assert "sector proxies" in result["sectorPerformanceAfterSimilarTrades"]
    assert "Context check" in result["combinedSummary"]


def test_build_historical_context_fallback(monkeypatch):
    filing = {
        "trades": [
            {
                "firstName": "Lena",
                "lastName": "Gray",
                "symbol": "AAPL",
                "type": "Purchase",
                "transactionDate": "2026-01-10",
                "assetDescription": "tech hardware",
            }
        ]
    }
    signal = {"signalType": "OTHER"}

    monkeypatch.setattr(historical_context, "_fetch_member_rows", lambda _member: [])
    monkeypatch.setattr(historical_context, "sector_proxy_return", lambda *_args, **_kwargs: None)

    result = historical_context.build_historical_context(filing, signal, window_days=30)

    assert "No comparable trade history" in result["lastTradeOutcome"]
    assert "limited scored history" in result["memberWinRate"]
