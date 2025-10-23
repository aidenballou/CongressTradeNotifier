"""Utility functions for extracting high-level insights from trade data."""

from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

from amounts import parse_amount


def _format_currency(value: float) -> str:
    """Return a human-friendly currency string (e.g. $125K, $2.4M)."""

    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.1f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"${value / 1_000:.1f}K"
    return f"${value:,.0f}"


def compute_trade_insights(trades: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Build a dictionary of summary insights for the provided trades."""

    trades = list(trades)
    insights: Dict[str, Any] = {
        "total_trades": len(trades),
        "total_estimated_volume": 0.0,
        "largest_trade": None,
        "most_active_member": None,
        "top_ticker": None,
        "unique_ticker_count": 0,
    }

    if not trades:
        return insights

    member_counts: Counter[str] = Counter()
    member_volume: defaultdict[str, float] = defaultdict(float)
    ticker_counts: Counter[str] = Counter()
    ticker_volume: defaultdict[str, float] = defaultdict(float)

    largest_trade: Optional[Dict[str, Any]] = None
    total_volume = 0.0

    for trade in trades:
        estimated_amount = parse_amount(trade.get("amount", ""))
        total_volume += estimated_amount

        trade_with_estimate = dict(trade)
        trade_with_estimate["estimated_amount"] = estimated_amount

        if largest_trade is None or estimated_amount > largest_trade.get("estimated_amount", 0):
            largest_trade = trade_with_estimate

        member_name = (f"{trade.get('firstName', '').strip()} {trade.get('lastName', '').strip()}").strip()
        if member_name:
            member_counts[member_name] += 1
            member_volume[member_name] += estimated_amount

        ticker = trade.get("symbol") or trade.get("assetDescription") or "Unknown"
        ticker_counts[ticker] += 1
        ticker_volume[ticker] += estimated_amount

    unique_tickers = {ticker for ticker in ticker_counts if ticker and ticker != "Unknown"}

    def _most_significant(counter: Counter[str], volume_lookup: Dict[str, float]) -> Optional[Tuple[str, int, float]]:
        if not counter:
            return None
        label, count = max(counter.items(), key=lambda item: (item[1], volume_lookup.get(item[0], 0.0)))
        return label, count, volume_lookup.get(label, 0.0)

    insights.update(
        {
            "total_estimated_volume": total_volume,
            "largest_trade": largest_trade,
            "most_active_member": _most_significant(member_counts, member_volume),
            "top_ticker": _most_significant(ticker_counts, ticker_volume),
            "unique_ticker_count": len(unique_tickers),
        }
    )

    return insights


def build_highlights_html(insights: Dict[str, Any]) -> str:
    """Return an HTML snippet describing the provided insights."""

    total_trades = insights.get("total_trades", 0)
    total_volume = _format_currency(insights.get("total_estimated_volume", 0.0))
    unique_ticker_count = insights.get("unique_ticker_count", 0)

    highlights: List[str] = [
        f"<strong>Total activity:</strong> {total_trades} trade{'s' if total_trades != 1 else ''} (~{total_volume})",
        f"<strong>Unique tickers:</strong> {unique_ticker_count}",
    ]

    largest_trade = insights.get("largest_trade")
    if largest_trade:
        highlights.append(
            "<strong>Largest disclosure:</strong> {member} {t_type} {symbol} on {date} (~{amount})".format(
                member=f"{largest_trade.get('firstName', '')} {largest_trade.get('lastName', '')}".strip(),
                t_type=largest_trade.get("type", ""),
                symbol=largest_trade.get("symbol", ""),
                date=largest_trade.get("transactionDate", largest_trade.get("disclosureDate", "")),
                amount=_format_currency(largest_trade.get("estimated_amount", 0.0)),
            )
        )

    member_info = insights.get("most_active_member")
    if member_info:
        member_name, count, volume = member_info
        highlights.append(
            f"<strong>Most active member:</strong> {member_name} ({count} trade{'s' if count != 1 else ''}, ~{_format_currency(volume)})"
        )

    ticker_info = insights.get("top_ticker")
    if ticker_info:
        ticker_symbol, count, volume = ticker_info
        highlights.append(
            f"<strong>Most popular ticker:</strong> {ticker_symbol} ({count} trade{'s' if count != 1 else ''}, ~{_format_currency(volume)})"
        )

    highlight_items = "".join(f"<li>{item}</li>" for item in highlights)

    return (
        "<div class=\"highlights\">"
        "  <h3>Daily Highlights</h3>"
        "  <ul>"
        f"    {highlight_items}"
        "  </ul>"
        "</div>"
    )


def build_highlights_text(insights: Dict[str, Any]) -> str:
    """Return a plain-text representation of the highlights for logging."""

    total_trades = insights.get("total_trades", 0)
    total_volume = _format_currency(insights.get("total_estimated_volume", 0.0))
    unique_ticker_count = insights.get("unique_ticker_count", 0)

    lines = [
        f"Total activity: {total_trades} trade{'s' if total_trades != 1 else ''} (~{total_volume})",
        f"Unique tickers: {unique_ticker_count}",
    ]

    largest_trade = insights.get("largest_trade")
    if largest_trade:
        lines.append(
            "Largest disclosure: {member} {t_type} {symbol} on {date} (~{amount})".format(
                member=f"{largest_trade.get('firstName', '')} {largest_trade.get('lastName', '')}".strip(),
                t_type=largest_trade.get("type", ""),
                symbol=largest_trade.get("symbol", ""),
                date=largest_trade.get("transactionDate", largest_trade.get("disclosureDate", "")),
                amount=_format_currency(largest_trade.get("estimated_amount", 0.0)),
            )
        )

    member_info = insights.get("most_active_member")
    if member_info:
        member_name, count, volume = member_info
        lines.append(
            f"Most active member: {member_name} ({count} trade{'s' if count != 1 else ''}, ~{_format_currency(volume)})"
        )

    ticker_info = insights.get("top_ticker")
    if ticker_info:
        ticker_symbol, count, volume = ticker_info
        lines.append(
            f"Most popular ticker: {ticker_symbol} ({count} trade{'s' if count != 1 else ''}, ~{_format_currency(volume)})"
        )

    return "\n".join(lines)
