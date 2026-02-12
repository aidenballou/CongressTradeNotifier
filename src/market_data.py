"""Market data helpers for historical return calculations."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

import requests

BASE_URL = "https://financialmodelingprep.com/api/v3"


@lru_cache(maxsize=512)
def _fetch_historical(symbol: str, start: str, end: str) -> List[Dict[str, Any]]:
    """Fetch historical daily candles from FMP and return sorted rows."""

    api_key = os.getenv("FMP_API_KEY")
    if not api_key or not symbol:
        return []

    url = (
        f"{BASE_URL}/historical-price-full/{symbol.upper()}"
        f"?from={start}&to={end}&apikey={api_key}"
    )
    try:
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            return []
        payload = response.json() or {}
        rows = payload.get("historical") or []
    except Exception:
        return []

    clean_rows: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if "date" not in row or "close" not in row:
            continue
        clean_rows.append(row)

    clean_rows.sort(key=lambda item: item.get("date", ""))
    return clean_rows


def _parse_date(date_str: str) -> Optional[datetime]:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except Exception:
        return None


def get_close_on_or_after(symbol: str, target_date: str) -> Tuple[Optional[float], Optional[str]]:
    """Return first close on/after target date."""

    target = _parse_date(target_date)
    if target is None:
        return None, None

    start = (target - timedelta(days=7)).strftime("%Y-%m-%d")
    end = (target + timedelta(days=30)).strftime("%Y-%m-%d")
    rows = _fetch_historical(symbol, start, end)

    for row in rows:
        row_date = _parse_date(str(row.get("date", "")))
        if row_date is None or row_date < target:
            continue
        try:
            return float(row["close"]), str(row["date"])
        except Exception:
            continue

    if rows:
        try:
            return float(rows[0]["close"]), str(rows[0]["date"])
        except Exception:
            return None, None

    return None, None


def get_return_after_window(symbol: str, entry_date: str, window_days: int = 30) -> Optional[float]:
    """Return raw percentage return over a window from entry date."""

    entry_dt = _parse_date(entry_date)
    if entry_dt is None:
        return None

    entry_close, actual_entry_date = get_close_on_or_after(symbol, entry_date)
    if entry_close is None or entry_close <= 0 or not actual_entry_date:
        return None

    actual_dt = _parse_date(actual_entry_date)
    if actual_dt is None:
        return None

    target_exit = (actual_dt + timedelta(days=window_days)).strftime("%Y-%m-%d")
    exit_close, _ = get_close_on_or_after(symbol, target_exit)
    if exit_close is None:
        return None

    return ((exit_close - entry_close) / entry_close) * 100.0


def directional_return(action: str, raw_return_pct: Optional[float]) -> Optional[float]:
    """Convert raw return into PnL-aligned return for buy/sell actions."""

    if raw_return_pct is None:
        return None

    action_norm = (action or "").strip().lower()
    if action_norm in {"sell", "sale"}:
        return -raw_return_pct
    return raw_return_pct


SECTOR_TO_PROXY = {
    "tech": "XLK",
    "financials": "XLF",
    "healthcare": "XLV",
    "energy": "XLE",
    "industrials": "XLI",
    "consumer staples": "XLP",
    "utilities": "XLU",
    "consumer discretionary": "XLY",
    "real estate": "XLRE",
    "communication services": "XLC",
    "materials": "XLB",
    "defensive": "XLP",
}


def sector_proxy_return(sector: str, entry_date: str, window_days: int = 30) -> Optional[float]:
    """Return proxy ETF performance for a named sector."""

    symbol = SECTOR_TO_PROXY.get((sector or "").strip().lower())
    if not symbol:
        return None
    return get_return_after_window(symbol, entry_date, window_days=window_days)
