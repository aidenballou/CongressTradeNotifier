"""Trade classification engine for identifying high-signal congressional filings."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
import re
from statistics import median
from typing import Any, Dict, Iterable, List, Literal, Optional, Tuple

try:
    from amounts import parse_amount
except ImportError:  # pragma: no cover
    from src.amounts import parse_amount

SignalStrength = Literal["LOW", "MEDIUM", "HIGH"]
SignalType = Literal["ROTATION", "CONVICTION", "FIRST_BUY", "FIRST_SELL", "CLUSTER", "OTHER"]

GROWTH_KEYWORDS = {
    "tech",
    "software",
    "semiconductor",
    "ai",
    "cloud",
    "internet",
    "communication services",
    "consumer discretionary",
}
DEFENSIVE_KEYWORDS = {
    "consumer staples",
    "utilities",
    "healthcare",
    "defensive",
}
COMMITTEE_KEYWORDS = {
    "committee",
    "oversight",
    "appropriations",
    "armed services",
    "finance committee",
    "energy and commerce",
}


def _parse_date(value: str) -> Optional[datetime]:
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except Exception:
        return None


def _normalize_action(action: str) -> str:
    norm = (action or "").strip().lower()
    if norm in {"buy", "purchase"}:
        return "BUY"
    if norm in {"sell", "sale"}:
        return "SELL"
    return norm.upper() if norm else "OTHER"


def _member_name(trade: Dict[str, Any]) -> str:
    if trade.get("member_name"):
        return str(trade.get("member_name")).strip()
    first = str(trade.get("firstName", "")).strip()
    last = str(trade.get("lastName", "")).strip()
    return f"{first} {last}".strip()


def _extract_trades(filing: Dict[str, Any]) -> List[Dict[str, Any]]:
    trades = filing.get("trades")
    if isinstance(trades, list) and trades:
        return trades
    return [filing]


def _trade_key(trade: Dict[str, Any]) -> Tuple[str, str, str, str, str]:
    return (
        _member_name(trade),
        str(trade.get("symbol") or trade.get("ticker") or "").upper(),
        str(trade.get("transactionDate") or trade.get("transaction_date") or ""),
        str(trade.get("disclosureDate") or trade.get("disclosure_date") or ""),
        str(trade.get("amount") or ""),
    )


def _history_excluding_filing(
    filing: Dict[str, Any],
    recent_trades: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    filing_keys = {_trade_key(trade) for trade in _extract_trades(filing)}
    history: List[Dict[str, Any]] = []
    for trade in recent_trades:
        if _trade_key(trade) in filing_keys:
            continue
        history.append(trade)
    return history


def _sector_bucket(trade: Dict[str, Any]) -> str:
    text = " ".join(
        [
            str(trade.get("assetDescription") or trade.get("asset_description") or ""),
            str(trade.get("symbol") or trade.get("ticker") or ""),
            str(trade.get("comment") or ""),
        ]
    ).lower()

    if any(_contains_keyword(text, keyword) for keyword in GROWTH_KEYWORDS):
        return "growth"
    if any(_contains_keyword(text, keyword) for keyword in DEFENSIVE_KEYWORDS):
        return "defensive"
    return "other"


def _contains_keyword(text: str, keyword: str) -> bool:
    if not keyword:
        return False
    if len(keyword) <= 3:
        return re.search(rf"\b{re.escape(keyword)}\b", text) is not None
    return keyword in text


def _action_side(trade: Dict[str, Any]) -> str:
    return _normalize_action(str(trade.get("type") or trade.get("transaction_type") or ""))


def _trade_date(trade: Dict[str, Any]) -> Optional[datetime]:
    return _parse_date(
        str(trade.get("transactionDate") or trade.get("transaction_date") or trade.get("disclosureDate") or trade.get("disclosure_date") or "")
    )


def analyze_filing(
    filing: Dict[str, Any],
    recent_trades: List[Dict[str, Any]],
    now_et: datetime,
    exclude_first_trade_in_ticker: bool = False,
) -> Dict[str, Any]:
    """Classify a filing and score conviction for posting eligibility."""

    trades = _extract_trades(filing)
    history = _history_excluding_filing(filing, recent_trades)

    member = _member_name(trades[0]) if trades else "Unknown member"
    symbols = [str(t.get("symbol") or t.get("ticker") or "").upper() for t in trades if str(t.get("symbol") or t.get("ticker") or "").strip()]

    buy_growth = 0
    sell_defensive = 0
    for trade in trades:
        side = _action_side(trade)
        bucket = _sector_bucket(trade)
        if side == "BUY" and bucket == "growth":
            buy_growth += 1
        if side == "SELL" and bucket == "defensive":
            sell_defensive += 1
    rotation = buy_growth > 0 and sell_defensive > 0

    unusual_ratios: List[float] = []
    for trade in trades:
        member_name = _member_name(trade)
        ticker = str(trade.get("symbol") or trade.get("ticker") or "").upper()
        amount = parse_amount(str(trade.get("amount") or ""))
        if amount <= 0:
            continue

        member_ticker_history = [
            parse_amount(str(h.get("amount") or ""))
            for h in history
            if _member_name(h) == member_name
            and str(h.get("symbol") or h.get("ticker") or "").upper() == ticker
            and parse_amount(str(h.get("amount") or "")) > 0
        ]
        if not member_ticker_history:
            continue

        med = median(member_ticker_history)
        if med <= 0:
            continue
        unusual_ratios.append(amount / med)

    unusual_ratio = max(unusual_ratios) if unusual_ratios else 1.0
    unusual_trade_size = unusual_ratio >= 3.0

    first_buy_in_ticker = False
    first_sell_in_ticker = False
    for trade in trades:
        member_name = _member_name(trade)
        ticker = str(trade.get("symbol") or trade.get("ticker") or "").upper()
        trade_dt = _trade_date(trade)
        side = _action_side(trade)
        if not member_name or not ticker:
            continue

        prior = [
            h
            for h in history
            if _member_name(h) == member_name
            and str(h.get("symbol") or h.get("ticker") or "").upper() == ticker
            and (_trade_date(h) or datetime.min) < (trade_dt or now_et)
        ]
        if not prior:
            if side == "BUY":
                first_buy_in_ticker = True
            elif side == "SELL":
                first_sell_in_ticker = True
            break
    first_trade_in_ticker = first_buy_in_ticker or first_sell_in_ticker

    cluster_detected = False
    for trade in trades:
        ticker = str(trade.get("symbol") or trade.get("ticker") or "").upper()
        side = _action_side(trade)
        event_dt = _trade_date(trade)
        if not ticker or side not in {"BUY", "SELL"} or event_dt is None:
            continue

        members = {_member_name(trade)}
        window_start = event_dt - timedelta(days=3)
        window_end = event_dt + timedelta(days=3)
        for h in history:
            if str(h.get("symbol") or h.get("ticker") or "").upper() != ticker:
                continue
            if _action_side(h) != side:
                continue
            h_dt = _trade_date(h)
            if h_dt is None or h_dt < window_start or h_dt > window_end:
                continue
            member_name = _member_name(h)
            if member_name:
                members.add(member_name)
        if len(members) >= 3:
            cluster_detected = True
            break

    repeat_buys = False
    for trade in trades:
        if _action_side(trade) != "BUY":
            continue
        member_name = _member_name(trade)
        ticker = str(trade.get("symbol") or trade.get("ticker") or "").upper()
        event_dt = _trade_date(trade) or now_et

        for h in history:
            if _member_name(h) != member_name:
                continue
            if str(h.get("symbol") or h.get("ticker") or "").upper() != ticker:
                continue
            if _action_side(h) != "BUY":
                continue
            h_dt = _trade_date(h)
            if h_dt and event_dt - timedelta(days=365) <= h_dt <= event_dt:
                repeat_buys = True
                break
        if repeat_buys:
            break

    opposite_trade = False
    for trade in trades:
        member_name = _member_name(trade)
        ticker = str(trade.get("symbol") or trade.get("ticker") or "").upper()
        side = _action_side(trade)
        event_dt = _trade_date(trade) or now_et
        if side not in {"BUY", "SELL"}:
            continue

        candidate = [
            h
            for h in history
            if _member_name(h) == member_name
            and str(h.get("symbol") or h.get("ticker") or "").upper() == ticker
            and _action_side(h) in {"BUY", "SELL"}
            and (_trade_date(h) or datetime.min) < event_dt
            and (_trade_date(h) or datetime.min) >= event_dt - timedelta(days=180)
        ]
        if not candidate:
            continue

        latest = max(candidate, key=lambda item: _trade_date(item) or datetime.min)
        if _action_side(latest) != side:
            opposite_trade = True
            break

    committee_relevance = False
    for trade in trades:
        comment = str(trade.get("comment") or "").lower()
        if any(keyword in comment for keyword in COMMITTEE_KEYWORDS):
            committee_relevance = True
            break

    news_recency = {
        "isRecentToNews": False,
        "note": "News/earnings proximity not yet integrated.",
    }

    score = 0
    if rotation:
        score += 4
    if cluster_detected:
        score += 3
    if unusual_trade_size:
        score += 3 if unusual_ratio >= 5.0 else 2
    if first_trade_in_ticker and not exclude_first_trade_in_ticker:
        score += 2
    if repeat_buys:
        score += 1
    if opposite_trade:
        score += 1
    if committee_relevance:
        score += 1

    if score >= 5:
        signal_strength: SignalStrength = "HIGH"
    elif score >= 3:
        signal_strength = "MEDIUM"
    else:
        signal_strength = "LOW"

    if rotation:
        signal_type: SignalType = "ROTATION"
    elif cluster_detected:
        signal_type = "CLUSTER"
    elif first_buy_in_ticker:
        signal_type = "FIRST_BUY"
    elif first_sell_in_ticker:
        signal_type = "FIRST_SELL"
    elif unusual_trade_size or repeat_buys or opposite_trade:
        signal_type = "CONVICTION"
    else:
        signal_type = "OTHER"

    if signal_type == "ROTATION":
        summary = f"{member} rotated into growth names while trimming defensive exposure."
    elif signal_type == "CLUSTER":
        ticker_text = symbols[0] if symbols else "the same ticker"
        summary = f"Multiple members lined up on {ticker_text} in a tight window."
    elif signal_type == "FIRST_BUY":
        ticker_text = symbols[0] if symbols else "a new name"
        summary = f"{member} initiated a fresh position in {ticker_text}."
    elif signal_type == "FIRST_SELL":
        ticker_text = symbols[0] if symbols else "a name"
        summary = f"{member} recorded a first exit in {ticker_text}."
    elif signal_type == "CONVICTION" and unusual_trade_size:
        summary = f"Trade size ran about {unusual_ratio:.1f}x above the member's median in that ticker."
    elif signal_type == "CONVICTION" and repeat_buys:
        summary = f"{member} keeps adding to the same position, signaling ongoing conviction."
    elif signal_type == "CONVICTION" and opposite_trade:
        summary = f"{member} flipped direction in the same ticker within six months."
    else:
        summary = "Activity was notable but lacked a strong directional signal."

    diagnostics = {
        "score": score,
        "rotation": rotation,
        "buyGrowthCount": buy_growth,
        "sellDefensiveCount": sell_defensive,
        "unusualTradeSize": unusual_trade_size,
        "unusualRatio": round(unusual_ratio, 2),
        "firstTradeInTicker": first_trade_in_ticker,
        "firstBuyInTicker": first_buy_in_ticker,
        "firstSellInTicker": first_sell_in_ticker,
        "clusteredTrades": cluster_detected,
        "repeatBuys": repeat_buys,
        "oppositeTrade": opposite_trade,
        "committeeRelevance": committee_relevance,
        "newsRecency": news_recency,
        "symbols": symbols,
    }

    return {
        "signalStrength": signal_strength,
        "signalType": signal_type,
        "summarySentence": summary,
        "diagnostics": diagnostics,
    }
