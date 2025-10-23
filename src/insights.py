"""Utility functions for extracting high-level insights from trade data."""

from collections import Counter, defaultdict
from datetime import datetime
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

    insider_activity = insights.get("related_insider_activity") or {}
    if insider_activity:
        overlap_count = len(insider_activity)
        detail_strings = summarize_insider_activity(insider_activity)
        detail_suffix = f" {', '.join(detail_strings)}" if detail_strings else ""
        highlights.append(
            (
                f"<strong>Insider overlap:</strong> {overlap_count} ticker"
                f"{'s' if overlap_count != 1 else ''} also saw corporate insider trades"
                f" in the last two weeks.{detail_suffix}"
            )
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

    insider_activity = insights.get("related_insider_activity") or {}
    if insider_activity:
        overlap_count = len(insider_activity)
        detail_strings = summarize_insider_activity(insider_activity)
        detail_suffix = f" Details: {', '.join(detail_strings)}" if detail_strings else ""
        lines.append(
            (
                f"Insider overlap: {overlap_count} ticker"
                f"{'s' if overlap_count != 1 else ''} also saw corporate insider trades"
                f" in the last two weeks.{detail_suffix}"
            )
        )

    return "\n".join(lines)


def summarize_insider_activity(
    insider_activity: Dict[str, List[Dict[str, Any]]],
    *,
    max_items: int = 3,
) -> List[str]:
    """Return short textual summaries of insider trades for highlight sections."""

    def _parse_date(entry: Dict[str, Any]) -> Optional[datetime]:
        for key in ("transactionDate", "filingDate", "date"):
            value = entry.get(key)
            if not value:
                continue
            try:
                return datetime.strptime(value, "%Y-%m-%d")
            except Exception:
                continue
        return None

    def _format_shares(raw_value: Any) -> Optional[str]:
        if raw_value in (None, ""):
            return None
        try:
            shares = float(raw_value)
        except (TypeError, ValueError):
            return str(raw_value)
        if shares >= 1_000_000:
            return f"{shares / 1_000_000:.1f}M sh"
        if shares >= 1_000:
            return f"{shares / 1_000:.1f}K sh"
        if shares.is_integer():
            return f"{int(shares)} sh"
        return f"{shares:.0f} sh"

    def _format_price(raw_value: Any) -> Optional[str]:
        if raw_value in (None, ""):
            return None
        try:
            price = float(raw_value)
        except (TypeError, ValueError):
            return str(raw_value)
        return f"${price:,.2f}"

    entries: List[Tuple[datetime, str, Dict[str, Any]]] = []
    for symbol, trades in insider_activity.items():
        if not trades:
            continue
        # Choose the most recent trade per symbol for highlighting
        latest_trade = max(trades, key=lambda item: _parse_date(item) or datetime.min)
        entries.append((_parse_date(latest_trade) or datetime.min, symbol, latest_trade))

    # Sort descending by date so the freshest intel appears first
    entries.sort(key=lambda item: item[0], reverse=True)

    summaries: List[str] = []
    for _, symbol, trade in entries[:max_items]:
        name = trade.get("insiderName") or trade.get("reportingName") or "Insider"
        title = trade.get("insiderTitle") or trade.get("position") or trade.get("typeOfOwner")
        action = trade.get("transactionType") or trade.get("type") or "trade"
        date = trade.get("transactionDate") or trade.get("filingDate") or "recently"
        shares = _format_shares(
            trade.get("securitiesTransacted")
            or trade.get("shares")
            or trade.get("securities")
            or trade.get("sharesTraded")
        )
        price = _format_price(trade.get("price") or trade.get("sharePrice"))

        descriptor = name.strip()
        if title:
            descriptor = f"{descriptor} ({title})"

        details: List[str] = [descriptor, action.strip(), date]
        meta: List[str] = []
        if shares:
            meta.append(shares)
        if price:
            meta.append(price)

        if meta:
            details.append(f"[{', '.join(meta)}]")

        summaries.append(f"{symbol}: {' '.join(details)}")

    return summaries
