"""Metrics and CSV output for standalone backtests."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from .models import SimulatedTrade, SummaryMetrics


def summarize(strategy: str, trades: List[SimulatedTrade], skipped: int, capital: float) -> SummaryMetrics:
    total_pnl = sum(trade.pnl for trade in trades)
    returns = [trade.return_pct for trade in trades]
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value < 0]
    gross_profit = sum(trade.pnl for trade in trades if trade.pnl > 0)
    gross_loss = abs(sum(trade.pnl for trade in trades if trade.pnl < 0))
    benchmark_returns = [trade.benchmark_return_pct for trade in trades if trade.benchmark_return_pct is not None]
    return SummaryMetrics(
        strategy=strategy,
        trades=len(trades),
        skipped=skipped,
        total_pnl=total_pnl,
        total_return_pct=(total_pnl / capital) * 100.0 if capital else 0.0,
        win_rate_pct=(len(wins) / len(trades)) * 100.0 if trades else 0.0,
        average_return_pct=_avg(returns),
        average_win_pct=_avg(wins),
        average_loss_pct=_avg(losses),
        profit_factor=(gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0),
        max_drawdown_pct=max_drawdown_pct(trades, capital),
        benchmark_return_pct=_avg(benchmark_returns) if benchmark_returns else None,
    )


def max_drawdown_pct(trades: List[SimulatedTrade], capital: float) -> float:
    equity = capital
    peak = capital
    max_drawdown = 0.0
    for trade in sorted(trades, key=lambda item: (item.exit_date, item.event_id)):
        equity += trade.pnl
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = min(max_drawdown, (equity - peak) / peak)
    return max_drawdown * 100.0


def equity_curve(trades: List[SimulatedTrade], capital: float) -> List[Tuple[date, float]]:
    equity = capital
    points: List[Tuple[date, float]] = []
    for trade in sorted(trades, key=lambda item: (item.exit_date, item.event_id)):
        equity += trade.pnl
        points.append((trade.exit_date, equity))
    return points


def write_outputs(output_dir: str, summary: SummaryMetrics, trades: List[SimulatedTrade], capital: float) -> None:
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    _write_summary(path / "summary.csv", summary)
    _write_trades(path / "trades.csv", trades)
    _write_equity(path / "equity_curve.csv", equity_curve(trades, capital))


def _write_summary(path: Path, summary: SummaryMetrics) -> None:
    fields = list(summary.__dataclass_fields__.keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(fields)
        writer.writerow([getattr(summary, field) for field in fields])


def _write_trades(path: Path, trades: Iterable[SimulatedTrade]) -> None:
    fields = list(SimulatedTrade.__dataclass_fields__.keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(fields)
        for trade in trades:
            writer.writerow([getattr(trade, field) for field in fields])


def _write_equity(path: Path, points: Iterable[Tuple[date, float]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "equity"])
        for point_date, equity in points:
            writer.writerow([point_date.isoformat(), equity])


def _avg(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0

