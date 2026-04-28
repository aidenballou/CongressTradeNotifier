"""Strategy simulation for standalone congressional copy-trade backtests."""

from __future__ import annotations

from datetime import timedelta
from typing import Iterable, List, Optional, Tuple

from .market_data import PriceDataProvider, bar_on_or_after
from .models import SimulatedTrade, StrategyConfig, TradeEvent
from .options import black_scholes_price, realized_volatility


def simulate_events(
    events: Iterable[TradeEvent],
    prices: PriceDataProvider,
    config: StrategyConfig,
    benchmark_symbol: str = "SPY",
) -> Tuple[List[SimulatedTrade], int]:
    simulated: List[SimulatedTrade] = []
    skipped = 0
    for event in events:
        trade = simulate_event(event, prices, config, benchmark_symbol=benchmark_symbol)
        if trade is None:
            skipped += 1
        else:
            simulated.append(trade)
    return simulated, skipped


def simulate_event(
    event: TradeEvent,
    prices: PriceDataProvider,
    config: StrategyConfig,
    benchmark_symbol: str = "SPY",
) -> Optional[SimulatedTrade]:
    strategy = config.strategy.lower()
    if strategy in {"stock", "stock_long_only", "stock_long_short"}:
        return _simulate_stock(event, prices, config, benchmark_symbol)
    if strategy in {"option", "options", "option_copy"}:
        return _simulate_option(event, prices, config, benchmark_symbol)
    raise ValueError(f"Unknown strategy: {config.strategy}")


def _direction(event: TradeEvent, copy_sales: bool) -> Optional[int]:
    if event.is_purchase:
        return 1
    if event.is_sale and copy_sales:
        return -1
    return None


def _allocation(event: TradeEvent, config: StrategyConfig) -> float:
    base = config.capital * config.position_size
    if not config.amount_weighted:
        return base
    if event.amount_value <= 0:
        return base
    # Keep amount weighting bounded so a single large disclosure cannot dominate.
    multiplier = min(max(event.amount_value / 25_000.0, 0.25), 5.0)
    return base * multiplier


def _simulate_stock(
    event: TradeEvent,
    prices: PriceDataProvider,
    config: StrategyConfig,
    benchmark_symbol: str,
) -> Optional[SimulatedTrade]:
    direction = _direction(event, copy_sales=config.copy_sales or config.strategy.lower() == "stock_long_short")
    if direction is None:
        return None

    bars = prices.get_bars(event.ticker)
    entry = bar_on_or_after(bars, event.disclosure_date, config.entry_delay_days)
    if entry is None:
        return None
    exit_target = entry.date + timedelta(days=config.hold_days)
    exit_bar = bar_on_or_after(bars, exit_target, 0)
    if exit_bar is None or entry.close <= 0:
        return None

    allocation = _allocation(event, config)
    notional = allocation * config.leverage
    quantity = direction * notional / entry.close
    gross_pnl = quantity * (exit_bar.close - entry.close)
    cost = notional * (config.transaction_cost_bps / 10_000.0) * 2.0
    pnl = gross_pnl - cost
    return_pct = (pnl / allocation) * 100.0 if allocation else 0.0
    benchmark_return = _benchmark_return(prices, benchmark_symbol, entry.date, exit_bar.date)

    return SimulatedTrade(
        event_id=event.id,
        member_name=event.member_name,
        ticker=event.ticker,
        transaction_type=event.transaction_type,
        instrument=f"stock_{config.leverage:g}x",
        entry_date=entry.date,
        exit_date=exit_bar.date,
        entry_price=entry.close,
        exit_price=exit_bar.close,
        quantity=quantity,
        notional=notional,
        pnl=pnl,
        return_pct=return_pct,
        benchmark_return_pct=benchmark_return,
    )


def _simulate_option(
    event: TradeEvent,
    prices: PriceDataProvider,
    config: StrategyConfig,
    benchmark_symbol: str,
) -> Optional[SimulatedTrade]:
    direction = _direction(event, copy_sales=True)
    if direction is None:
        return None

    bars = prices.get_bars(event.ticker)
    entry = bar_on_or_after(bars, event.disclosure_date, config.entry_delay_days)
    if entry is None or entry.close <= 0:
        return None

    option_kind = "call" if direction == 1 else "put"
    strike = entry.close * config.option_moneyness
    vol = realized_volatility(bars, entry.date, config.option_vol_days)
    if vol is None:
        return None

    hold_days = min(config.hold_days, config.option_dte)
    exit_target = entry.date + timedelta(days=hold_days)
    exit_bar = bar_on_or_after(bars, exit_target, 0)
    if exit_bar is None:
        return None

    entry_price = black_scholes_price(
        spot=entry.close,
        strike=strike,
        dte=config.option_dte,
        volatility=vol,
        risk_free_rate=config.risk_free_rate,
        option_kind=option_kind,
    )
    exit_price = black_scholes_price(
        spot=exit_bar.close,
        strike=strike,
        dte=max(config.option_dte - hold_days, 0),
        volatility=vol,
        risk_free_rate=config.risk_free_rate,
        option_kind=option_kind,
    )
    if entry_price <= 0:
        return None

    allocation = _allocation(event, config)
    slippage = config.option_slippage_bps / 10_000.0
    entry_fill = entry_price * (1.0 + slippage)
    exit_fill = max(exit_price * (1.0 - slippage), 0.0)
    contracts = allocation / (entry_fill * 100.0)
    pnl = contracts * 100.0 * (exit_fill - entry_fill)
    return_pct = (pnl / allocation) * 100.0 if allocation else 0.0
    benchmark_return = _benchmark_return(prices, benchmark_symbol, entry.date, exit_bar.date)

    return SimulatedTrade(
        event_id=event.id,
        member_name=event.member_name,
        ticker=event.ticker,
        transaction_type=event.transaction_type,
        instrument=f"{option_kind}_{config.option_dte}d_{config.option_moneyness:.2f}m",
        entry_date=entry.date,
        exit_date=exit_bar.date,
        entry_price=entry_fill,
        exit_price=exit_fill,
        quantity=contracts,
        notional=allocation,
        pnl=pnl,
        return_pct=return_pct,
        benchmark_return_pct=benchmark_return,
    )


def _benchmark_return(
    prices: PriceDataProvider,
    benchmark_symbol: str,
    entry_date,
    exit_date,
) -> Optional[float]:
    bars = prices.get_bars(benchmark_symbol)
    entry = bar_on_or_after(bars, entry_date, 0)
    exit_bar = bar_on_or_after(bars, exit_date, 0)
    if entry is None or exit_bar is None or entry.close <= 0:
        return None
    return ((exit_bar.close - entry.close) / entry.close) * 100.0

