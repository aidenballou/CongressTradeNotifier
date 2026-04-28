"""Data models for standalone copy-trade backtests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass(frozen=True)
class TradeEvent:
    id: int
    ticker: str
    disclosure_date: date
    transaction_date: Optional[date]
    member_name: str
    transaction_type: str
    amount_text: str
    amount_value: float
    asset_description: str

    @property
    def is_purchase(self) -> bool:
        return self.transaction_type.strip().lower() == "purchase"

    @property
    def is_sale(self) -> bool:
        return self.transaction_type.strip().lower().startswith("sale")


@dataclass(frozen=True)
class PriceBar:
    date: date
    close: float


@dataclass(frozen=True)
class StrategyConfig:
    strategy: str
    capital: float = 100_000.0
    position_size: float = 0.02
    hold_days: int = 20
    entry_delay_days: int = 1
    leverage: float = 1.0
    copy_sales: bool = False
    amount_weighted: bool = False
    option_dte: int = 90
    option_moneyness: float = 1.0
    option_vol_days: int = 60
    risk_free_rate: float = 0.04
    transaction_cost_bps: float = 5.0
    option_slippage_bps: float = 100.0


@dataclass(frozen=True)
class SimulatedTrade:
    event_id: int
    member_name: str
    ticker: str
    transaction_type: str
    instrument: str
    entry_date: date
    exit_date: date
    entry_price: float
    exit_price: float
    quantity: float
    notional: float
    pnl: float
    return_pct: float
    benchmark_return_pct: Optional[float]


@dataclass(frozen=True)
class SummaryMetrics:
    strategy: str
    trades: int
    skipped: int
    total_pnl: float
    total_return_pct: float
    win_rate_pct: float
    average_return_pct: float
    average_win_pct: float
    average_loss_pct: float
    profit_factor: float
    max_drawdown_pct: float
    benchmark_return_pct: Optional[float]

