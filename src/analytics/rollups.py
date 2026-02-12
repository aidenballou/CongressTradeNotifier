"""Generate rollup content: daily tape, 7-day themes, member spotlights."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List

try:
    from db import cursor
    from amounts import parse_amount
except ImportError:  # pragma: no cover
    from src.db import cursor
    from src.amounts import parse_amount


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
            "summary_trades": [],
        }

    # Group by member+disclosure_date to count filings
    filings = set()
    trades_by_ticker: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    largest_trade = None
    largest_value = 0.0

    for row in rows:
        ticker, disc_date, trans_date, member_name, trans_type, amount_raw, amount_val = row
        key = (member_name or "", disc_date or "")
        filings.add(key)

        # Parse amount
        if amount_val is not None and amount_val > 0:
            value = float(amount_val)
        else:
            value = parse_amount(str(amount_raw) if amount_raw else "")

        trade_info = {
            "ticker": ticker or "",
            "member_name": member_name or "",
            "transaction_type": trans_type or "",
            "amount": amount_raw,
            "amount_value": value,
            "disclosure_date": disc_date,
            "transaction_date": trans_date,
        }

        if ticker:
            trades_by_ticker[ticker].append(trade_info)

        if value > largest_value:
            largest_value = value
            largest_trade = trade_info

    # Find most bought/sold tickers
    ticker_buys: Dict[str, float] = defaultdict(float)
    ticker_sells: Dict[str, float] = defaultdict(float)

    for ticker, trade_list in trades_by_ticker.items():
        for trade in trade_list:
            trans_type = (trade.get("transaction_type") or "").upper()
            value = trade.get("amount_value", 0.0)
            if "BUY" in trans_type or "PURCHASE" in trans_type:
                ticker_buys[ticker] += value
            elif "SELL" in trans_type or "SALE" in trans_type:
                ticker_sells[ticker] += value

    most_bought = max(ticker_buys.items(), key=lambda x: x[1]) if ticker_buys else None
    most_sold = max(ticker_sells.items(), key=lambda x: x[1]) if ticker_sells else None

    return {
        "total_filings": len(filings),
        "largest_trade": largest_trade,
        "most_bought_ticker": {"ticker": most_bought[0], "value": most_bought[1]} if most_bought else None,
        "most_sold_ticker": {"ticker": most_sold[0], "value": most_sold[1]} if most_sold else None,
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
        }

    ticker_values: Dict[str, float] = defaultdict(float)
    ticker_members: Dict[str, set] = defaultdict(set)
    total_buy = 0.0
    total_sell = 0.0

    for row in rows:
        ticker, disc_date, trans_date, member_name, trans_type, amount_raw, amount_val = row
        if not ticker:
            continue

        if amount_val is not None and amount_val > 0:
            value = float(amount_val)
        else:
            value = parse_amount(str(amount_raw) if amount_raw else "")

        ticker_values[ticker] += value
        if member_name:
            ticker_members[ticker].add(member_name)

        trans_type_upper = (trans_type or "").upper()
        if "BUY" in trans_type_upper or "PURCHASE" in trans_type_upper:
            total_buy += value
        elif "SELL" in trans_type_upper or "SALE" in trans_type_upper:
            total_sell += value

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

    return {
        "top_5_tickers_by_value": top_5_tickers,
        "cluster_tickers": cluster_tickers[:5],  # Top 5 clusters
        "net_buy_vs_sell": {"net_buy": total_buy, "net_sell": total_sell},
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
            largest_value = value
            largest_trade = {
                "member": member_name or "Unknown",
                "ticker": ticker or "",
                "amount": amount_raw,
                "amount_value": value,
                "transaction_type": trans_type or "",
                "disclosure_date": disc_date,
                "transaction_date": trans_date,
                "description": asset_desc or comment or "",
            }

    return largest_trade
