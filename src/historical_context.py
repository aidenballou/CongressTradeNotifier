"""Historical context engine for signal threads."""

from __future__ import annotations

from datetime import datetime
from statistics import mean
from typing import Any, Dict, List, Optional

try:
    from db import cursor
except ImportError:  # pragma: no cover
    from src.db import cursor

try:
    from market_data import directional_return, get_return_after_window, sector_proxy_return
except ImportError:  # pragma: no cover
    from src.market_data import directional_return, get_return_after_window, sector_proxy_return


SECTOR_KEYWORDS = {
    "tech": ["tech", "software", "semiconductor", "cloud", "ai", "apple", "microsoft", "nvidia"],
    "financials": ["bank", "financial", "insurance", "jpmorgan", "goldman", "visa"],
    "healthcare": ["health", "pharma", "biotech", "medical"],
    "energy": ["energy", "oil", "gas", "renewable", "solar"],
    "industrials": ["industrial", "aerospace", "defense", "transport"],
    "consumer staples": ["staples", "beverage", "grocery", "household"],
    "utilities": ["utility", "electric", "water"],
    "consumer discretionary": ["retail", "consumer", "apparel", "travel", "entertainment"],
}


def _parse_date(value: str) -> Optional[datetime]:
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except Exception:
        return None


def _normalize_action(action: str) -> str:
    action_norm = (action or "").strip().lower()
    if action_norm in {"buy", "purchase"}:
        return "BUY"
    if action_norm in {"sell", "sale"}:
        return "SELL"
    return "OTHER"


def _extract_trades(filing: Dict[str, Any]) -> List[Dict[str, Any]]:
    trades = filing.get("trades")
    if isinstance(trades, list) and trades:
        return trades
    return [filing]


def _member_name(trade: Dict[str, Any]) -> str:
    if trade.get("member_name"):
        return str(trade.get("member_name")).strip()
    first = str(trade.get("firstName", "")).strip()
    last = str(trade.get("lastName", "")).strip()
    return f"{first} {last}".strip()


def _infer_sector(trade: Dict[str, Any]) -> str:
    text = " ".join(
        [
            str(trade.get("assetDescription") or trade.get("asset_description") or ""),
            str(trade.get("symbol") or trade.get("ticker") or ""),
        ]
    ).lower()
    for sector, keywords in SECTOR_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return sector
    return "tech"


def _fetch_member_rows(member_name: str) -> List[Dict[str, Any]]:
    if not member_name:
        return []

    cursor.execute(
        """
        SELECT ticker, transaction_date, disclosure_date, transaction_type, amount, asset_description, member_name
        FROM trades
        WHERE member_name = ?
        ORDER BY transaction_date DESC
        """,
        (member_name,),
    )

    rows = cursor.fetchall()
    results = []
    for row in rows:
        results.append(
            {
                "ticker": row[0],
                "transaction_date": row[1],
                "disclosure_date": row[2],
                "transaction_type": row[3],
                "amount": row[4],
                "asset_description": row[5],
                "member_name": row[6],
            }
        )
    return results


def _format_return(value: float) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.1f}%"


def _avg(values: List[float]) -> Optional[float]:
    if not values:
        return None
    return mean(values)


def build_historical_context(
    filing: Dict[str, Any],
    signal: Dict[str, Any],
    window_days: int = 30,
) -> Dict[str, str]:
    """Compute one-sentence historical context fields for a filing."""

    trades = _extract_trades(filing)
    primary_trade = trades[0]
    member = _member_name(primary_trade) or "This member"
    ticker = str(primary_trade.get("symbol") or primary_trade.get("ticker") or "").upper()
    action = _normalize_action(str(primary_trade.get("type") or primary_trade.get("transaction_type") or ""))
    entry_date = str(primary_trade.get("transactionDate") or primary_trade.get("transaction_date") or "")

    member_rows = _fetch_member_rows(member)

    last_trade_sentence = "No comparable trade history yet, so prior outcome confidence is limited."
    if ticker and entry_date:
        entry_dt = _parse_date(entry_date)
        prior_rows = [
            row
            for row in member_rows
            if str(row.get("ticker") or "").upper() == ticker
            and _parse_date(str(row.get("transaction_date") or ""))
            and (_parse_date(str(row.get("transaction_date") or "")) < (entry_dt or datetime.max))
        ]
        if prior_rows:
            prior = prior_rows[0]
            prior_action = _normalize_action(str(prior.get("transaction_type") or ""))
            prior_ret = get_return_after_window(
                str(prior.get("ticker") or ""),
                str(prior.get("transaction_date") or ""),
                window_days=window_days,
            )
            prior_dir_ret = directional_return(prior_action, prior_ret)
            if prior_dir_ret is not None:
                last_trade_sentence = (
                    f"The last comparable {ticker} call by {member} was {_format_return(prior_dir_ret)} over the next {window_days} days."
                )

    win_rate_sentence = f"{member} has limited scored history, so win-rate confidence is still low."
    scored_returns: List[float] = []
    for row in member_rows[:20]:
        row_ticker = str(row.get("ticker") or "")
        row_date = str(row.get("transaction_date") or "")
        row_action = _normalize_action(str(row.get("transaction_type") or ""))
        if not row_ticker or not row_date or row_action not in {"BUY", "SELL"}:
            continue
        raw_ret = get_return_after_window(row_ticker, row_date, window_days=window_days)
        dir_ret = directional_return(row_action, raw_ret)
        if dir_ret is not None:
            scored_returns.append(dir_ret)

    if scored_returns:
        wins = sum(1 for value in scored_returns if value > 0)
        win_rate = wins / len(scored_returns) * 100.0
        win_rate_sentence = (
            f"Across recent trades, {member}'s hit rate is about {win_rate:.0f}% over a {window_days}-day horizon."
        )

    avg_return_sentence = "Not enough similar signal history yet to establish a stable average move."
    signal_type = str(signal.get("signalType") or "OTHER")
    similar_returns: List[float] = []
    for row in member_rows[:30]:
        row_ticker = str(row.get("ticker") or "")
        row_date = str(row.get("transaction_date") or "")
        row_action = _normalize_action(str(row.get("transaction_type") or ""))
        if not row_ticker or not row_date or row_action != action:
            continue
        raw_ret = get_return_after_window(row_ticker, row_date, window_days=window_days)
        dir_ret = directional_return(row_action, raw_ret)
        if dir_ret is not None:
            similar_returns.append(dir_ret)

    avg_ret = _avg(similar_returns)
    if avg_ret is not None:
        avg_return_sentence = (
            f"For {signal_type.lower()} setups in this member's book, the average {window_days}-day move has been {_format_return(avg_ret)}."
        )

    sector = _infer_sector(primary_trade)
    sector_sentence = "Sector analog performance is mixed, so this setup still has two-way risk."
    if entry_date:
        sector_ret = sector_proxy_return(sector, entry_date, window_days=window_days)
        if sector_ret is not None:
            direction = "up" if sector_ret >= 0 else "down"
            magnitude = f"{abs(sector_ret):.1f}%"
            sector_sentence = (
                f"Comparable {sector} sector proxies were {direction} {magnitude} over similar windows."
            )

    combined_sentence = (
        f"Context check: {last_trade_sentence} {win_rate_sentence} {sector_sentence}"
    )

    return {
        "lastTradeOutcome": last_trade_sentence,
        "memberWinRate": win_rate_sentence,
        "avgReturnAfterTrades": avg_return_sentence,
        "sectorPerformanceAfterSimilarTrades": sector_sentence,
        "combinedSummary": combined_sentence,
    }
