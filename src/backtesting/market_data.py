"""Historical daily close data providers for backtesting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
import re
from typing import Dict, Iterable, List, Optional, Protocol

from .models import PriceBar


class PriceDataProvider(Protocol):
    def get_bars(self, symbol: str) -> List[PriceBar]:
        ...


@dataclass
class InMemoryPriceDataProvider:
    bars_by_symbol: Dict[str, List[PriceBar]]

    def get_bars(self, symbol: str) -> List[PriceBar]:
        return sorted(self.bars_by_symbol.get(symbol.upper(), []), key=lambda bar: bar.date)


class YFinancePriceDataProvider:
    """Daily close provider backed by yfinance.

    This is intentionally scoped to the standalone backtester. It is not used by
    the operational ingestion/posting pipeline.
    """

    def __init__(self, symbols: Iterable[str], start: date, end: date, cache_dir: str = ".cache/backtesting/prices"):
        self.symbols = sorted({s.upper() for s in symbols if s})
        self.start = start
        self.end = end
        self.cache_dir = Path(cache_dir)
        self._bars_by_symbol: Dict[str, List[PriceBar]] = {}

    def load(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        missing = [symbol for symbol in self.symbols if not self._load_cached(symbol)]
        if not missing:
            return

        try:
            import yfinance as yf
        except Exception as exc:
            raise RuntimeError("yfinance is required for price downloads") from exc

        # yfinance end is exclusive; add a day so the requested end can appear.
        yahoo_symbols = [_to_yahoo_symbol(symbol) for symbol in missing]
        yahoo_to_original = dict(zip(yahoo_symbols, missing))
        df = yf.download(
            tickers=" ".join(yahoo_symbols),
            start=self.start.isoformat(),
            end=(self.end + timedelta(days=1)).isoformat(),
            auto_adjust=True,
            group_by="ticker",
            progress=False,
            threads=True,
        )
        for yahoo_symbol in yahoo_symbols:
            symbol = yahoo_to_original[yahoo_symbol]
            bars = _extract_yfinance_bars(df, yahoo_symbol, multiple=len(missing) > 1)
            self._bars_by_symbol[symbol] = bars
            self._write_cached(symbol, bars)

    def get_bars(self, symbol: str) -> List[PriceBar]:
        symbol = symbol.upper()
        if symbol not in self._bars_by_symbol:
            self._load_cached(symbol)
        return self._bars_by_symbol.get(symbol, [])

    def _cache_path(self, symbol: str) -> Path:
        safe_symbol = re.sub(r"[^A-Za-z0-9_.-]+", "_", symbol.upper())
        return self.cache_dir / f"{safe_symbol}_{self.start.isoformat()}_{self.end.isoformat()}.csv"

    def _load_cached(self, symbol: str) -> bool:
        path = self._cache_path(symbol)
        if not path.exists():
            return False
        bars: List[PriceBar] = []
        for line in path.read_text(encoding="utf-8").splitlines()[1:]:
            raw_date, raw_close = line.split(",", 1)
            try:
                bars.append(PriceBar(date=date.fromisoformat(raw_date), close=float(raw_close)))
            except ValueError:
                continue
        self._bars_by_symbol[symbol] = bars
        return bool(bars)

    def _write_cached(self, symbol: str, bars: List[PriceBar]) -> None:
        path = self._cache_path(symbol)
        lines = ["date,close"]
        lines.extend(f"{bar.date.isoformat()},{bar.close:.6f}" for bar in bars)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _extract_yfinance_bars(df: object, symbol: str, multiple: bool) -> List[PriceBar]:
    try:
        close_series = df[symbol]["Close"] if multiple else df["Close"]
    except Exception:
        return []

    bars: List[PriceBar] = []
    try:
        items = close_series.dropna().items()
    except Exception:
        return []
    for index, close in items:
        try:
            bar_date = index.date()
            bars.append(PriceBar(date=bar_date, close=float(close)))
        except Exception:
            continue
    return sorted(bars, key=lambda bar: bar.date)


def _to_yahoo_symbol(symbol: str) -> str:
    cleaned = symbol.upper().strip()
    if cleaned.startswith("$") and cleaned.endswith("USD"):
        return f"{cleaned[1:-3]}-USD"
    return cleaned.replace("/", "-")


def bar_on_or_after(bars: List[PriceBar], target: date, offset_trading_days: int = 0) -> Optional[PriceBar]:
    candidates = [bar for bar in bars if bar.date >= target]
    if not candidates:
        return None
    index = min(max(offset_trading_days, 0), len(candidates) - 1)
    return candidates[index]


def close_before(bars: List[PriceBar], target: date) -> Optional[PriceBar]:
    previous = [bar for bar in bars if bar.date < target]
    return previous[-1] if previous else None
