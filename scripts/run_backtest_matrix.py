#!/usr/bin/env python3
"""Run a standalone matrix of congressional copy-trade backtests."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
import sys
from typing import Iterable, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from backtesting.events import filter_events, load_trade_events
from backtesting.market_data import YFinancePriceDataProvider
from backtesting.metrics import summarize, write_outputs
from backtesting.models import StrategyConfig, SummaryMetrics
from backtesting.strategies import simulate_events


@dataclass(frozen=True)
class MatrixCase:
    name: str
    config: StrategyConfig


def default_cases(capital: float, position_size: float) -> List[MatrixCase]:
    return [
        MatrixCase("stock_long_only_5d", StrategyConfig("stock_long_only", capital, position_size, hold_days=5)),
        MatrixCase("stock_long_only_20d", StrategyConfig("stock_long_only", capital, position_size, hold_days=20)),
        MatrixCase("stock_long_only_60d", StrategyConfig("stock_long_only", capital, position_size, hold_days=60)),
        MatrixCase("stock_long_short_20d_1x", StrategyConfig("stock_long_short", capital, position_size, hold_days=20)),
        MatrixCase("stock_long_short_20d_2x", StrategyConfig("stock_long_short", capital, position_size, hold_days=20, leverage=2.0)),
        MatrixCase("stock_long_short_20d_3x", StrategyConfig("stock_long_short", capital, position_size, hold_days=20, leverage=3.0)),
        MatrixCase("stock_amount_weighted_20d", StrategyConfig("stock_long_short", capital, position_size, hold_days=20, amount_weighted=True)),
        MatrixCase("stock_long_short_60d_1x", StrategyConfig("stock_long_short", capital, position_size, hold_days=60)),
        MatrixCase("option_90d_atm_hold20", StrategyConfig("option_copy", capital, position_size, hold_days=20, option_dte=90, option_moneyness=1.0)),
        MatrixCase("option_90d_10pct_otm_hold20", StrategyConfig("option_copy", capital, position_size, hold_days=20, option_dte=90, option_moneyness=1.10)),
        MatrixCase("option_365d_atm_hold60", StrategyConfig("option_copy", capital, position_size, hold_days=60, option_dte=365, option_moneyness=1.0)),
        MatrixCase("option_365d_10pct_otm_hold60", StrategyConfig("option_copy", capital, position_size, hold_days=60, option_dte=365, option_moneyness=1.10)),
    ]


def write_matrix_summary(path: Path, rows: Iterable[tuple[str, SummaryMetrics]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["case_name"] + list(SummaryMetrics.__dataclass_fields__.keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(fields)
        for name, summary in rows:
            writer.writerow([name] + [getattr(summary, field) for field in SummaryMetrics.__dataclass_fields__])


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a matrix of standalone copy-trade backtests.")
    parser.add_argument("--db", default="trades.sqlite3")
    parser.add_argument("--capital", type=float, default=100_000.0)
    parser.add_argument("--position-size", type=float, default=0.02)
    parser.add_argument("--entry-delay-days", type=int, default=1)
    parser.add_argument("--benchmark", default="SPY")
    parser.add_argument("--output-dir", default="outputs/backtests/matrix")
    parser.add_argument("--price-cache-dir", default=".cache/backtesting/prices")
    parser.add_argument("--members", default=None)
    parser.add_argument("--tickers", default=None)
    args = parser.parse_args()

    members = {item.strip() for item in args.members.split(",")} if args.members else set()
    tickers = {item.strip() for item in args.tickers.split(",")} if args.tickers else set()
    events = filter_events(load_trade_events(args.db), members=members, tickers=tickers)
    if not events:
        print("No eligible trade events found.")
        return 1

    cases = [
        MatrixCase(case.name, StrategyConfig(**{**case.config.__dict__, "entry_delay_days": args.entry_delay_days}))
        for case in default_cases(args.capital, args.position_size)
    ]
    max_horizon = max(max(case.config.hold_days, case.config.option_dte) for case in cases) + args.entry_delay_days + 10
    max_vol_days = max(case.config.option_vol_days for case in cases)
    start = min(event.disclosure_date for event in events) - timedelta(days=max(max_vol_days + 10, 80))
    end = max(event.disclosure_date for event in events) + timedelta(days=max_horizon)
    symbols = {event.ticker for event in events}
    symbols.add(args.benchmark.upper())

    provider = YFinancePriceDataProvider(symbols=symbols, start=start, end=end, cache_dir=args.price_cache_dir)
    provider.load()

    output_root = Path(args.output_dir)
    summary_rows: List[tuple[str, SummaryMetrics]] = []
    for case in cases:
        trades, skipped = simulate_events(events, provider, case.config, benchmark_symbol=args.benchmark.upper())
        summary = summarize(case.name, trades, skipped, args.capital)
        summary_rows.append((case.name, summary))
        write_outputs(str(output_root / case.name), summary, trades, args.capital)
        print(
            f"{case.name}: return={summary.total_return_pct:.2f}% "
            f"trades={summary.trades} skipped={summary.skipped} "
            f"win_rate={summary.win_rate_pct:.1f}% max_dd={summary.max_drawdown_pct:.2f}%"
        )

    write_matrix_summary(output_root / "matrix_summary.csv", summary_rows)
    print(f"Wrote matrix summary: {output_root / 'matrix_summary.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

