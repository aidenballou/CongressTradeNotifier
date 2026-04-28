import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from backtesting.events import load_trade_events
from backtesting.market_data import InMemoryPriceDataProvider, YFinancePriceDataProvider, _to_yahoo_symbol
from backtesting.metrics import summarize
from backtesting.models import PriceBar, StrategyConfig, TradeEvent
from backtesting.options import black_scholes_price
from backtesting.strategies import simulate_events


def _bars(start: date, closes: list[float]) -> list[PriceBar]:
    return [PriceBar(date=start + timedelta(days=i), close=close) for i, close in enumerate(closes)]


def test_load_trade_events_uses_disclosure_date_and_filters_exchange(tmp_path):
    db_path = tmp_path / "trades.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY,
            ticker TEXT,
            disclosure_date TEXT,
            transaction_date TEXT,
            member_name TEXT,
            transaction_type TEXT,
            amount TEXT,
            amount_value REAL,
            asset_description TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO trades VALUES
        (1, 'nvda', '2026-01-10', '2025-12-15', 'Pat Lee', 'Purchase', '$1,001 - $15,000', NULL, 'NVIDIA'),
        (2, 'msft', '2026-01-11', '2026-01-02', 'Pat Lee', 'Exchange', '$1,001 - $15,000', NULL, 'Microsoft')
        """
    )
    conn.commit()
    conn.close()

    events = load_trade_events(str(db_path))

    assert len(events) == 1
    assert events[0].ticker == "NVDA"
    assert events[0].disclosure_date == date(2026, 1, 10)
    assert events[0].transaction_date == date(2025, 12, 15)
    assert events[0].amount_value == 8000.5


def test_stock_long_only_skips_sales_and_accounts_for_costs():
    events = [
        TradeEvent(1, "AAA", date(2026, 1, 1), None, "A", "Purchase", "", 0, ""),
        TradeEvent(2, "BBB", date(2026, 1, 1), None, "B", "Sale", "", 0, ""),
    ]
    provider = InMemoryPriceDataProvider(
        {
            "AAA": _bars(date(2026, 1, 1), [100, 101, 102, 103, 104]),
            "BBB": _bars(date(2026, 1, 1), [100, 99, 98, 97, 96]),
            "SPY": _bars(date(2026, 1, 1), [100, 100, 100, 100, 100]),
        }
    )
    config = StrategyConfig(
        strategy="stock_long_only",
        capital=100_000,
        position_size=0.02,
        hold_days=2,
        entry_delay_days=0,
        transaction_cost_bps=0,
    )

    trades, skipped = simulate_events(events, provider, config)

    assert len(trades) == 1
    assert skipped == 1
    assert trades[0].pnl == 40
    assert trades[0].return_pct == 2


def test_stock_long_short_copies_sales_as_bearish():
    events = [TradeEvent(1, "BBB", date(2026, 1, 1), None, "B", "Sale", "", 0, "")]
    provider = InMemoryPriceDataProvider(
        {
            "BBB": _bars(date(2026, 1, 1), [100, 99, 98, 97]),
            "SPY": _bars(date(2026, 1, 1), [100, 100, 100, 100]),
        }
    )
    config = StrategyConfig(
        strategy="stock_long_short",
        capital=100_000,
        position_size=0.02,
        hold_days=2,
        entry_delay_days=0,
        transaction_cost_bps=0,
    )

    trades, skipped = simulate_events(events, provider, config)

    assert skipped == 0
    assert len(trades) == 1
    assert trades[0].pnl == 40
    assert trades[0].quantity < 0


def test_black_scholes_call_and_put_have_value():
    call = black_scholes_price(spot=100, strike=100, dte=90, volatility=0.30, risk_free_rate=0.04, option_kind="call")
    put = black_scholes_price(spot=100, strike=100, dte=90, volatility=0.30, risk_free_rate=0.04, option_kind="put")

    assert call > 0
    assert put > 0
    assert call > put


def test_yfinance_symbols_and_cache_paths_are_filesystem_safe(tmp_path):
    provider = YFinancePriceDataProvider(
        symbols=["BRK/B", "$BTCUSD"],
        start=date(2026, 1, 1),
        end=date(2026, 1, 31),
        cache_dir=str(tmp_path),
    )

    assert _to_yahoo_symbol("BRK/B") == "BRK-B"
    assert _to_yahoo_symbol("$BTCUSD") == "BTC-USD"
    assert provider._cache_path("BRK/B").parent == tmp_path
    assert provider._cache_path("BRK/B").name.startswith("BRK_B_")


def test_option_strategy_simulates_calls_with_realized_volatility():
    closes = [100, 101, 100, 102, 101, 103, 105, 107, 109, 111, 113, 115]
    event = TradeEvent(1, "AAA", date(2026, 1, 6), None, "A", "Purchase", "", 0, "")
    provider = InMemoryPriceDataProvider(
        {
            "AAA": _bars(date(2026, 1, 1), closes),
            "SPY": _bars(date(2026, 1, 1), [100] * len(closes)),
        }
    )
    config = StrategyConfig(
        strategy="option_copy",
        capital=100_000,
        position_size=0.02,
        hold_days=3,
        entry_delay_days=0,
        option_dte=90,
        option_moneyness=1.0,
        option_vol_days=4,
        option_slippage_bps=0,
    )

    trades, skipped = simulate_events([event], provider, config)

    assert skipped == 0
    assert len(trades) == 1
    assert trades[0].instrument == "call_90d_1.00m"
    assert trades[0].return_pct > 0


def test_summary_metrics_include_drawdown_and_win_rate():
    events = [
        TradeEvent(1, "AAA", date(2026, 1, 1), None, "A", "Purchase", "", 0, ""),
        TradeEvent(2, "CCC", date(2026, 1, 1), None, "C", "Purchase", "", 0, ""),
    ]
    provider = InMemoryPriceDataProvider(
        {
            "AAA": _bars(date(2026, 1, 1), [100, 110, 120]),
            "CCC": _bars(date(2026, 1, 1), [100, 95, 90]),
            "SPY": _bars(date(2026, 1, 1), [100, 100, 100]),
        }
    )
    config = StrategyConfig(strategy="stock_long_only", capital=100_000, position_size=0.02, hold_days=2, entry_delay_days=0, transaction_cost_bps=0)
    trades, skipped = simulate_events(events, provider, config)

    summary = summarize("stock_long_only", trades, skipped, capital=100_000)

    assert summary.trades == 2
    assert summary.win_rate_pct == 50
    assert summary.total_pnl == 200
