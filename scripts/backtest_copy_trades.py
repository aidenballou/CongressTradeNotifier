#!/usr/bin/env python3
"""Run standalone congressional copy-trade strategy backtests.

This script is separate from tweet/content strategy code. It reads disclosures
from SQLite, downloads daily market prices, simulates the requested strategy,
and writes CSV artifacts under outputs/backtests by default.
"""

from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from backtesting.events import filter_events, load_trade_events
from backtesting.market_data import YFinancePriceDataProvider
from backtesting.metrics import summarize, write_outputs
from backtesting.models import StrategyConfig
from backtesting.strategies import simulate_events


def _csv_set(value: str | None) -> set[str]:
    if not value:
        return set()
    return {item.strip() for item in value.split(",") if item.strip()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest congressional copy-trade strategies.")
    parser.add_argument("--db", default="trades.sqlite3", help="SQLite database path.")
    parser.add_argument("--strategy", default="stock_long_only", choices=["stock_long_only", "stock_long_short", "option_copy"])
    parser.add_argument("--capital", type=float, default=100_000.0)
    parser.add_argument("--position-size", type=float, default=0.02, help="Fraction of starting capital per event.")
    parser.add_argument("--hold-days", type=int, default=20)
    parser.add_argument("--entry-delay-days", type=int, default=1, help="Trading-day offset after disclosure date.")
    parser.add_argument("--leverage", type=float, default=1.0, help="Stock notional leverage.")
    parser.add_argument("--copy-sales", action="store_true", help="Copy sales as bearish trades.")
    parser.add_argument("--amount-weighted", action="store_true")
    parser.add_argument("--option-dte", type=int, default=90)
    parser.add_argument("--option-moneyness", type=float, default=1.0, help="Strike / spot. Calls: 1.10 is 10%% OTM; puts: 0.90 is 10%% OTM.")
    parser.add_argument("--option-vol-days", type=int, default=60)
    parser.add_argument("--risk-free-rate", type=float, default=0.04)
    parser.add_argument("--transaction-cost-bps", type=float, default=5.0)
    parser.add_argument("--option-slippage-bps", type=float, default=100.0)
    parser.add_argument("--members", default=None, help="Comma-separated exact member-name filter.")
    parser.add_argument("--tickers", default=None, help="Comma-separated ticker filter.")
    parser.add_argument("--benchmark", default="SPY")
    parser.add_argument("--output-dir", default="outputs/backtests/latest")
    parser.add_argument("--price-cache-dir", default=".cache/backtesting/prices")
    args = parser.parse_args()

    events = load_trade_events(args.db)
    events = filter_events(events, members=_csv_set(args.members), tickers=_csv_set(args.tickers))
    if not events:
        print("No eligible trade events found.")
        return 1

    max_horizon = max(args.hold_days, args.option_dte) + args.entry_delay_days + 10
    start = min(event.disclosure_date for event in events) - timedelta(days=max(args.option_vol_days + 10, 80))
    end = max(event.disclosure_date for event in events) + timedelta(days=max_horizon)
    symbols = {event.ticker for event in events}
    symbols.add(args.benchmark.upper())

    provider = YFinancePriceDataProvider(symbols=symbols, start=start, end=end, cache_dir=args.price_cache_dir)
    provider.load()

    config = StrategyConfig(
        strategy=args.strategy,
        capital=args.capital,
        position_size=args.position_size,
        hold_days=args.hold_days,
        entry_delay_days=args.entry_delay_days,
        leverage=args.leverage,
        copy_sales=args.copy_sales,
        amount_weighted=args.amount_weighted,
        option_dte=args.option_dte,
        option_moneyness=args.option_moneyness,
        option_vol_days=args.option_vol_days,
        risk_free_rate=args.risk_free_rate,
        transaction_cost_bps=args.transaction_cost_bps,
        option_slippage_bps=args.option_slippage_bps,
    )
    trades, skipped = simulate_events(events, provider, config, benchmark_symbol=args.benchmark.upper())
    summary = summarize(args.strategy, trades, skipped, args.capital)
    write_outputs(args.output_dir, summary, trades, args.capital)

    print(f"Events: {len(events)}")
    print(f"Simulated trades: {summary.trades}")
    print(f"Skipped: {summary.skipped}")
    print(f"Total return: {summary.total_return_pct:.2f}%")
    print(f"Win rate: {summary.win_rate_pct:.1f}%")
    print(f"Max drawdown: {summary.max_drawdown_pct:.2f}%")
    print(f"Wrote: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

