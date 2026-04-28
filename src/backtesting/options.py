"""Synthetic option pricing for broad strategy comparisons."""

from __future__ import annotations

from datetime import date
from math import erf, exp, log, sqrt
from statistics import pstdev
from typing import List, Optional

from .models import PriceBar


def normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + erf(value / sqrt(2.0)))


def black_scholes_price(
    spot: float,
    strike: float,
    dte: int,
    volatility: float,
    risk_free_rate: float,
    option_kind: str,
) -> float:
    if spot <= 0 or strike <= 0:
        return 0.0
    years = max(dte, 0) / 365.0
    intrinsic = max(spot - strike, 0.0) if option_kind == "call" else max(strike - spot, 0.0)
    if years <= 0 or volatility <= 0:
        return intrinsic

    sigma_root_t = volatility * sqrt(years)
    d1 = (log(spot / strike) + (risk_free_rate + 0.5 * volatility * volatility) * years) / sigma_root_t
    d2 = d1 - sigma_root_t
    discounted_strike = strike * exp(-risk_free_rate * years)
    if option_kind == "call":
        return max(spot * normal_cdf(d1) - discounted_strike * normal_cdf(d2), intrinsic)
    return max(discounted_strike * normal_cdf(-d2) - spot * normal_cdf(-d1), intrinsic)


def realized_volatility(bars: List[PriceBar], as_of: date, lookback_days: int) -> Optional[float]:
    history = [bar for bar in bars if bar.date < as_of][-max(lookback_days + 1, 2) :]
    if len(history) < 2:
        return None

    returns: List[float] = []
    for previous, current in zip(history, history[1:]):
        if previous.close <= 0 or current.close <= 0:
            continue
        returns.append(log(current.close / previous.close))
    if len(returns) < 2:
        return None
    daily_vol = pstdev(returns)
    return max(daily_vol * sqrt(252.0), 0.01)

