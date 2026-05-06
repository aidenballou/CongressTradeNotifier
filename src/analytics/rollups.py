"""Generate rollup content: daily tape, 7-day themes, member spotlights."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List

try:
    from db import cursor
    from amounts import parse_amount
    from filing_utils import is_postable_congress_trade, normalize_action
except ImportError:  # pragma: no cover
    from src.db import cursor
    from src.amounts import parse_amount
    from src.filing_utils import is_postable_congress_trade, normalize_action


def _days_between(start: str | None, end: str | None) -> int | None:
    if not start or not end:
        return None
    try:
        return max((datetime.strptime(end[:10], "%Y-%m-%d") - datetime.strptime(start[:10], "%Y-%m-%d")).days, 0)
    except ValueError:
        return None


def build_daily_tape(now_et: datetime) -> Dict[str, Any]:
    """Query last 24h of trades and build daily tape summary."""

    start_date = (now_et - timedelta(hours=24)).strftime("%Y-%m-%d")
    cursor.execute(
        """
        SELECT ticker, disclosure_date, transaction_date, member_name,
               transaction_type, amount, amount_value
        FROM trades
        WHERE disclosure_date >= ?
        ORDER BY disclosure_date DESC, transaction_date DESC
        """,
        (start_date,),
    )

    rows = cursor.fetchall()
    if not rows:
        return {
            "total_filings": 0,
            "largest_trade": None,
            "most_bought_ticker": None,
            "most_sold_ticker": None,
            "top_buyer_member": None,
            "top_seller_member": None,
            "ticker_member_counts": {},
            "top_cluster": None,
            "summary_trades": [],
        }

    # Group by member+disclosure_date to count filings
    filings = set()
    trades_by_ticker: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    largest_trade = None
    largest_value = 0.0

    for row in rows:
        ticker, disc_date, trans_date, member_name, trans_type, amount_raw, amount_val = row
        # Parse amount
        if amount_val is not None and amount_val > 0:
            value = float(amount_val)
        else:
            value = parse_amount(str(amount_raw) if amount_raw else "")

        trade_info = {
            "symbol": ticker or "",
            "ticker": ticker or "",
            "member_name": member_name or "",
            "type": trans_type or "",
            "transaction_type": trans_type or "",
            "action_normalized": normalize_action(trans_type or ""),
            "amount": amount_raw,
            "amount_value": value,
            "disclosure_date": disc_date,
            "transaction_date": trans_date,
            "days_to_file": _days_between(trans_date, disc_date),
        }
        if not is_postable_congress_trade(trade_info):
            continue

        key = (member_name or "", disc_date or "")
        filings.add(key)

        if ticker:
            trades_by_ticker[ticker].append(trade_info)

        if value > largest_value:
            largest_value = value
            largest_trade = trade_info

    # Find most bought/sold tickers
    ticker_buys: Dict[str, float] = defaultdict(float)
    ticker_sells: Dict[str, float] = defaultdict(float)
    buyer_members: Dict[str, float] = defaultdict(float)
    seller_members: Dict[str, float] = defaultdict(float)
    ticker_member_sets: Dict[str, set] = defaultdict(set)

    for ticker, trade_list in trades_by_ticker.items():
        for trade in trade_list:
            trans_type = (trade.get("transaction_type") or "").upper()
            value = trade.get("amount_value", 0.0)
            member = trade.get("member_name") or ""
            if member:
                ticker_member_sets[ticker].add(member)
            if "BUY" in trans_type or "PURCHASE" in trans_type:
                ticker_buys[ticker] += value
                if member:
                    buyer_members[member] += value
            elif "SELL" in trans_type or "SALE" in trans_type:
                ticker_sells[ticker] += value
                if member:
                    seller_members[member] += value

    most_bought = max(ticker_buys.items(), key=lambda x: x[1]) if ticker_buys else None
    most_sold = max(ticker_sells.items(), key=lambda x: x[1]) if ticker_sells else None
    top_buyer = max(buyer_members.items(), key=lambda x: x[1]) if buyer_members else None
    top_seller = max(seller_members.items(), key=lambda x: x[1]) if seller_members else None
    ticker_member_counts = {ticker: len(members) for ticker, members in ticker_member_sets.items()}
    top_cluster_ticker = max(ticker_member_counts.items(), key=lambda x: x[1]) if ticker_member_counts else None

    return {
        "total_filings": len(filings),
        "largest_trade": largest_trade,
        "most_bought_ticker": {"ticker": most_bought[0], "value": most_bought[1]} if most_bought else None,
        "most_sold_ticker": {"ticker": most_sold[0], "value": most_sold[1]} if most_sold else None,
        "top_buyer_member": top_buyer[0] if top_buyer else None,
        "top_seller_member": top_seller[0] if top_seller else None,
        "ticker_member_counts": ticker_member_counts,
        "top_cluster": {"ticker": top_cluster_ticker[0], "member_count": top_cluster_ticker[1]} if top_cluster_ticker else None,
        "summary_trades": list(trades_by_ticker.values())[:10],  # Top 10 tickers
    }


def build_seven_day_theme(now_et: datetime) -> Dict[str, Any]:
    """Query last 7 days and build theme summary."""

    start_date = (now_et - timedelta(days=7)).strftime("%Y-%m-%d")
    cursor.execute(
        """
        SELECT ticker, disclosure_date, transaction_date, member_name,
               transaction_type, amount, amount_value
        FROM trades
        WHERE disclosure_date >= ?
        ORDER BY disclosure_date DESC
        """,
        (start_date,),
    )

    rows = cursor.fetchall()
    if not rows:
        return {
            "top_5_tickers_by_value": [],
            "cluster_tickers": [],
            "net_buy_vs_sell": {"net_buy": 0.0, "net_sell": 0.0},
            "top_buyer_member": None,
            "top_seller_member": None,
            "ticker_member_counts": {},
            "top_cluster": None,
        }

    ticker_values: Dict[str, float] = defaultdict(float)
    ticker_members: Dict[str, set] = defaultdict(set)
    buyer_members: Dict[str, float] = defaultdict(float)
    seller_members: Dict[str, float] = defaultdict(float)
    total_buy = 0.0
    total_sell = 0.0

    for row in rows:
        ticker, disc_date, trans_date, member_name, trans_type, amount_raw, amount_val = row

        if amount_val is not None and amount_val > 0:
            value = float(amount_val)
        else:
            value = parse_amount(str(amount_raw) if amount_raw else "")

        trade_info = {
            "symbol": ticker or "",
            "ticker": ticker or "",
            "type": trans_type or "",
            "transaction_type": trans_type or "",
            "amount": amount_raw,
            "amount_value": value,
        }
        if not is_postable_congress_trade(trade_info):
            continue

        ticker_values[ticker] += value
        if member_name:
            ticker_members[ticker].add(member_name)

        trans_type_upper = (trans_type or "").upper()
        if "BUY" in trans_type_upper or "PURCHASE" in trans_type_upper:
            total_buy += value
            if member_name:
                buyer_members[member_name] += value
        elif "SELL" in trans_type_upper or "SALE" in trans_type_upper:
            total_sell += value
            if member_name:
                seller_members[member_name] += value

    # Top 5 tickers by value
    top_5 = sorted(ticker_values.items(), key=lambda x: x[1], reverse=True)[:5]
    top_5_tickers = [{"ticker": ticker, "value": value} for ticker, value in top_5]

    # Cluster tickers (2+ members)
    cluster_tickers = [
        {"ticker": ticker, "member_count": len(members)}
        for ticker, members in ticker_members.items()
        if len(members) >= 2
    ]
    cluster_tickers.sort(key=lambda x: x["member_count"], reverse=True)
    ticker_member_counts = {ticker: len(members) for ticker, members in ticker_members.items()}
    top_buyer = max(buyer_members.items(), key=lambda x: x[1]) if buyer_members else None
    top_seller = max(seller_members.items(), key=lambda x: x[1]) if seller_members else None

    return {
        "top_5_tickers_by_value": top_5_tickers,
        "cluster_tickers": cluster_tickers[:5],  # Top 5 clusters
        "net_buy_vs_sell": {"net_buy": total_buy, "net_sell": total_sell},
        "top_buyer_member": top_buyer[0] if top_buyer else None,
        "top_seller_member": top_seller[0] if top_seller else None,
        "ticker_member_counts": ticker_member_counts,
        "top_cluster": cluster_tickers[0] if cluster_tickers else None,
    }


def build_member_spotlight(now_et: datetime) -> Dict[str, Any] | None:
    """Query last 24h and find largest single trade for member spotlight."""

    start_date = (now_et - timedelta(hours=24)).strftime("%Y-%m-%d")
    cursor.execute(
        """
        SELECT ticker, disclosure_date, transaction_date, member_name,
               transaction_type, amount, amount_value, asset_description, comment
        FROM trades
        WHERE disclosure_date >= ?
        ORDER BY disclosure_date DESC, transaction_date DESC
        """,
        (start_date,),
    )

    rows = cursor.fetchall()
    if not rows:
        return None

    largest_trade = None
    largest_value = 0.0

    for row in rows:
        ticker, disc_date, trans_date, member_name, trans_type, amount_raw, amount_val, asset_desc, comment = row

        if amount_val is not None and amount_val > 0:
            value = float(amount_val)
        else:
            value = parse_amount(str(amount_raw) if amount_raw else "")

        if value > largest_value:
            candidate = {
                "member": member_name or "Unknown",
                "symbol": ticker or "",
                "ticker": ticker or "",
                "amount": amount_raw,
                "amount_value": value,
                "type": trans_type or "",
                "transaction_type": trans_type or "",
                "disclosure_date": disc_date,
                "transaction_date": trans_date,
                "description": asset_desc or comment or "",
            }
            if not is_postable_congress_trade(candidate):
                continue
            largest_value = value
            largest_trade = candidate

    return largest_trade
