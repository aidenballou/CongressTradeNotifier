"""Shared helpers for filing/trade payload normalization."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List


def extract_trades(filing: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return filing trades, or wrap a single trade-like filing."""
    trades = filing.get("trades")
    if isinstance(trades, list) and trades:
        return trades
    return [filing]


def member_name(trade: Dict[str, Any]) -> str:
    """Resolve a member name from either full or split-name fields."""
    if trade.get("member_name"):
        return str(trade.get("member_name")).strip()
    first = str(trade.get("firstName", "")).strip()
    last = str(trade.get("lastName", "")).strip()
    return f"{first} {last}".strip()


def normalize_action(action: str) -> str:
    """Normalize action labels to BUY/SELL or a stable uppercase fallback."""
    norm = (action or "").strip().lower()
    if norm in {"buy", "purchase"}:
        return "BUY"
    if norm in {"sell", "sale"}:
        return "SELL"
    return norm.upper() if norm else "OTHER"


def trade_amount_is_disclosed(trade: Dict[str, Any]) -> bool:
    """Return True when the trade has a usable disclosed dollar amount."""
    value = trade.get("amount_value")
    try:
        if value not in (None, "") and float(value) > 0:
            return True
    except (TypeError, ValueError):
        pass

    raw = str(trade.get("amount") or trade.get("amount_range") or "").strip()
    return bool(raw and re.search(r"\d", raw))


def trade_ticker_is_disclosed(trade: Dict[str, Any]) -> bool:
    """Return True when the trade has a concrete ticker symbol."""
    ticker = str(trade.get("symbol") or trade.get("ticker") or "").replace("$", "").strip()
    return bool(ticker)


def is_postable_congress_trade(trade: Dict[str, Any]) -> bool:
    """Congress trade posts need a ticker, BUY/SELL direction, and amount."""
    action = normalize_action(str(trade.get("type") or trade.get("transaction_type") or ""))
    return action in {"BUY", "SELL"} and trade_ticker_is_disclosed(trade) and trade_amount_is_disclosed(trade)


def filter_postable_trades(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep only congressional trades that are useful enough to post."""
    return [trade for trade in trades if is_postable_congress_trade(trade)]


def action_verb(action: str) -> str:
    """Convert action labels to human-readable past tense."""
    normalized = normalize_action(action)
    if normalized == "BUY":
        return "bought"
    if normalized == "SELL":
        return "sold"
    return "traded"


def stable_mode(seed: str, buckets: int = 3) -> int:
    """Map a seed to a deterministic bucket index."""
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % buckets
