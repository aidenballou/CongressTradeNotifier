"""Compose 2-tweet engagement threads for high-signal filings."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    from filing_utils import (
        extract_trades as _extract_trades,
        filter_postable_trades,
        is_postable_congress_trade,
        member_name as _member_name,
        normalize_action,
    )
except ImportError:  # pragma: no cover
    from src.filing_utils import (
        extract_trades as _extract_trades,
        filter_postable_trades,
        is_postable_congress_trade,
        member_name as _member_name,
        normalize_action,
    )


MAX_TWEET_LEN = 280
BANNED_PREFIXES = (
    "Daily Tape:",
    "7-Day Theme:",
    "Member Spotlight:",
    "Context:",
    "Most bought:",
    "Most sold:",
    "Net:",
)
VAGUE_CLAIMS = (
    "insiders buy for only one reason",
    "all buys buy vs sell bias",
    "congress just leaned",
)


def _trim(text: str, limit: int = MAX_TWEET_LEN) -> str:
    value = " ".join((text or "").split())
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _parse_date(value: Any) -> Optional[datetime]:
    if not value:
        return None
    raw = str(value).strip()
    candidates = (
        (raw[:10], "%Y-%m-%d"),
        (raw[:10], "%m/%d/%Y"),
        (raw[:19], "%Y-%m-%dT%H:%M:%S"),
    )
    for candidate, fmt in candidates:
        try:
            return datetime.strptime(candidate, fmt)
        except ValueError:
            continue
    return None


def _ticker_text(ticker: Any) -> str:
    symbol = str(ticker or "").replace("$", "").upper().strip()
    return f"${symbol}" if symbol else ""


def _trade_amount_text(trade: Dict[str, Any]) -> str:
    value = trade.get("amount_value")
    try:
        numeric_value = float(value or 0)
    except (TypeError, ValueError):
        numeric_value = 0.0
    if numeric_value > 0:
        return f"about {_format_amount(numeric_value)}"
    raw = str(trade.get("amount") or trade.get("amount_range") or "").strip()
    numbers = [float(value.replace(",", "")) for value in re.findall(r"[\d,]+(?:\.\d+)?", raw)]
    if not numbers:
        return raw
    if len(numbers) == 1:
        return _format_amount(numbers[0])
    return f"{_format_amount(min(numbers))}-{_format_amount(max(numbers))}"


def validate_social_copy(
    tweet: str,
    ticker_data_exists: bool = False,
    amount_data_exists: bool = False,
    allow_no_filings: bool = False,
) -> bool:
    """Return True only for post-ready social copy."""
    text = " ".join((tweet or "").split())
    if not text or len(text) > MAX_TWEET_LEN:
        return False
    if any(text.startswith(prefix) for prefix in BANNED_PREFIXES):
        return False
    lowered = text.lower()
    if any(claim in lowered for claim in VAGUE_CLAIMS):
        return False
    if " buy vs sell bias" in lowered or " sell vs buy bias" in lowered:
        return False
    if any(phrase in lowered for phrase in ("undisclosed amount", "undisclosed ticker", "disclosed asset")):
        return False
    if re.search(r"\breported a\s+(trade|traded)\b", lowered):
        return False
    if len(text) < 45 and not allow_no_filings:
        return False
    if ticker_data_exists and not re.search(r"\$[A-Z][A-Z0-9.\-]{0,9}\b", text):
        return False
    if amount_data_exists and not re.search(r"\$[0-9]", text):
        return False
    return True


def _pick_symbol(trades: List[Dict[str, Any]]) -> str:
    for trade in trades:
        symbol = str(trade.get("symbol") or trade.get("ticker") or "").upper().strip()
        if symbol:
            return symbol
    return ""


def _format_amount(value: float) -> str:
    """Format dollar values as $XM/$XK/$X."""
    if value >= 1_000_000:
        return f"${value/1_000_000:.1f}M"
    if value >= 1_000:
        return f"${value/1_000:.0f}K"
    return f"${value:.0f}"


def _congress_timing_text(trades: List[Dict[str, Any]], disclosure_date: Any = None) -> str:
    dated_trades = []
    for trade in trades:
        trade_date = _parse_date(trade.get("transactionDate") or trade.get("transaction_date"))
        filed_date = _parse_date(
            trade.get("disclosureDate")
            or trade.get("disclosure_date")
            or disclosure_date
        )
        if trade_date and filed_date:
            dated_trades.append((trade_date, max((filed_date - trade_date).days, 0)))
    if not dated_trades:
        return ""

    if len(dated_trades) == 1:
        trade_date, lag = dated_trades[0]
        lag_text = "the same day" if lag == 0 else f"{lag} day{'s' if lag != 1 else ''} later"
        return f"Trade date: {trade_date.strftime('%b %-d, %Y')}. Filed {lag_text}."

    dates = [item[0] for item in dated_trades]
    lags = [item[1] for item in dated_trades]
    date_text = min(dates).strftime("%b %-d")
    if max(dates) != min(dates):
        date_text = f"{date_text}-{max(dates).strftime('%b %-d')}"
    lag_text = str(min(lags))
    if max(lags) != min(lags):
        lag_text = f"{min(lags)}-{max(lags)}"
    return f"Disclosure timing: Trades made {date_text}; filed {lag_text} day{'s' if lag_text != '1' else ''} later."


def _congress_alert_pages(trades: List[Dict[str, Any]]) -> List[str]:
    """Format one member's disclosure as one or more complete alert posts."""

    trades = filter_postable_trades(trades)
    if not trades:
        return []

    member = _member_name(trades[0]) or "Unknown"
    if len(trades) == 1:
        trade = trades[0]
        action = normalize_action(str(trade.get("type") or trade.get("transaction_type") or ""))
        verb = "buying" if action == "BUY" else "selling"
        ticker = _ticker_text(trade.get("symbol") or trade.get("ticker"))
        amount = _trade_amount_text(trade)
        return [
            f"🚨 BREAKING: Congress member {member} just disclosed {verb} {amount} of {ticker}."
        ]

    trade_lines = []
    for trade in trades:
        action = normalize_action(str(trade.get("type") or trade.get("transaction_type") or ""))
        verb = "Bought" if action == "BUY" else "Sold"
        ticker = str(trade.get("symbol") or trade.get("ticker") or "").replace("$", "").upper().strip()
        trade_lines.append((verb, _trade_amount_text(trade), ticker))

    pages: List[str] = []
    remaining = list(trade_lines)
    while remaining:
        header = (
            f"🚨 BREAKING: Congress member {member} just disclosed {len(trades)} trades:"
            if not pages
            else f"More trades from Congress member {member}:"
        )
        lines = [header]
        included = 0
        for verb, amount, ticker in remaining:
            ticker_text = f"${ticker}" if included == 0 else ticker
            line = f"• {verb} {amount} of {ticker_text}"
            if len("\n".join(lines + [line])) > MAX_TWEET_LEN:
                break
            lines.append(line)
            included += 1
        if included == 0:
            return []
        pages.append("\n".join(lines))
        remaining = remaining[included:]
    return pages


def compose_congress_alert_thread(filing: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build a factual member-specific alert and keep the chart on its root."""

    trades = filter_postable_trades(_extract_trades(filing))
    pages = _congress_alert_pages(trades)
    if not pages:
        return []

    symbol = _pick_symbol(trades)
    media_date = str(trades[0].get("transactionDate") or trades[0].get("transaction_date") or "")
    thread = [
        {
            "text": text,
            "media_symbol": symbol if index == 0 else None,
            "media_trade_date": media_date if index == 0 else None,
        }
        for index, text in enumerate(pages)
    ]
    timing = _congress_timing_text(trades, filing.get("disclosureDate"))
    if timing and len(thread) == 1:
        thread.append({"text": timing, "media_symbol": None, "media_trade_date": None})
    return thread


def compose_thread(
    filing: Dict[str, Any],
    signal: Dict[str, Any],
    insight: Dict[str, Any],
    context: Dict[str, Any],
    stats: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Build the member-specific congressional alert selected by the scheduler."""

    return compose_congress_alert_thread(filing)


def compose_daily_tape_thread(tape: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Turn the daily-tape candidate into an individual member alert."""

    total_filings = tape.get("total_filings", 0)
    largest_trade = tape.get("largest_trade")
    most_bought = tape.get("most_bought_ticker")

    if total_filings == 0:
        tweet1 = _trim("No new congressional filings hit the tape in the last 24 hours.")
        return [{"text": tweet1, "media_symbol": None, "media_trade_date": None}]

    if largest_trade and is_postable_congress_trade(largest_trade):
        return compose_congress_alert_thread(
            {
                "disclosureDate": largest_trade.get("disclosure_date"),
                "trades": [largest_trade],
            }
        )

    if most_bought and most_bought.get("ticker"):
        ticker = _ticker_text(most_bought["ticker"])
        value = most_bought.get("value", 0.0)
        member = tape.get("top_buyer_member") or "Congress"
        tweet1 = _trim(
            f"{ticker} was the top congressional buy in this batch. "
            f"{member} reported about {_format_amount(value)} in purchases. "
            "Watch whether this is a one-off or part of a broader sector trade."
        )
        return [{"text": tweet1, "media_symbol": most_bought["ticker"], "media_trade_date": None}]

    return []


def compose_seven_day_theme_thread(theme: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Compose a single strong weekly/pattern post when a real cluster exists."""

    top_5 = [
        item
        for item in theme.get("top_5_tickers_by_value", [])
        if item.get("ticker") and float(item.get("value") or 0) > 0
    ]
    clusters = theme.get("cluster_tickers", [])

    if not top_5:
        tweet1 = _trim("No significant congressional trading cluster stood out over the last week.")
        return [{"text": tweet1, "media_symbol": None, "media_trade_date": None}]

    top_cluster = theme.get("top_cluster") or (clusters[0] if clusters else None)
    buyer = theme.get("top_buyer_member") or "not concentrated in one member"
    cluster_value = float((top_cluster or {}).get("value") or 0)
    if top_cluster and cluster_value <= 0:
        cluster_value = next(
            (float(item.get("value") or 0) for item in top_5 if item.get("ticker") == top_cluster.get("ticker")),
            0.0,
        )
    if top_cluster and cluster_value > 0:
        cluster_ticker = _ticker_text(top_cluster.get("ticker"))
        member_count = top_cluster.get("member_count", 0)
        next_names = ", ".join(
            f"{item['ticker']} ({_format_amount(float(item.get('value') or 0))})"
            for item in top_5
            if item.get("ticker") and item.get("ticker") != top_cluster.get("ticker")
        )
        tweet1 = _trim(
            f"Congress clustered around {cluster_ticker}: {member_count} members reported "
            f"about {_format_amount(cluster_value)} in trades this week. "
            f"{f'Next by disclosed value: {next_names}. ' if next_names else ''}"
            f"Biggest reported buyer: {buyer}."
        )
        media_symbol = top_cluster.get("ticker")
    else:
        leader = top_5[0]
        ticker = _ticker_text(leader.get("ticker"))
        next_names = ", ".join(
            f"{item['ticker']} ({_format_amount(float(item.get('value') or 0))})"
            for item in top_5[1:3]
            if item.get("ticker")
        )
        tweet1 = _trim(
            f"{ticker} led congressional trading this week at about {_format_amount(leader.get('value', 0.0))}. "
            f"{f'Next by disclosed value: {next_names}. ' if next_names else ''}"
            f"Biggest reported buyer: {buyer}."
        )
        media_symbol = leader.get("ticker")

    return [{"text": tweet1, "media_symbol": media_symbol, "media_trade_date": None}]


def compose_member_spotlight_thread(spotlight: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Compose a single factual member spotlight."""

    if not spotlight:
        return []

    return compose_congress_alert_thread(
        {
            "disclosureDate": spotlight.get("disclosure_date"),
            "trades": [
                {
                    "member_name": spotlight.get("member_name") or spotlight.get("member", "A member"),
                    "ticker": spotlight.get("ticker", ""),
                    "amount_value": spotlight.get("amount_value", 0.0),
                    "transaction_type": spotlight.get("transaction_type", ""),
                    "transaction_date": spotlight.get("transaction_date"),
                    "disclosure_date": spotlight.get("disclosure_date"),
                }
            ],
        }
    )
