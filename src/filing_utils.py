"""Shared helpers for filing/trade payload normalization."""

from __future__ import annotations

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


def action_verb(action: str) -> str:
    """Convert action labels to human-readable past tense."""
    normalized = normalize_action(action)
    if normalized == "BUY":
        return "bought"
    if normalized == "SELL":
        return "sold"
    return "traded"
