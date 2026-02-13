"""Compose 3-tweet engagement threads for high-signal filings."""

from __future__ import annotations

from typing import Any, Dict, List

try:
    from filing_utils import action_verb, extract_trades as _extract_trades, member_name as _member_name
except ImportError:  # pragma: no cover
    from src.filing_utils import action_verb, extract_trades as _extract_trades, member_name as _member_name


MAX_TWEET_LEN = 280


def _trim(text: str, limit: int = MAX_TWEET_LEN) -> str:
    value = " ".join((text or "").split())
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _trade_blurb(trades: List[Dict[str, Any]]) -> str:
    segments = []
    for trade in trades[:4]:
        symbol = str(trade.get("symbol") or trade.get("ticker") or "").upper()
        action = action_verb(str(trade.get("type") or trade.get("transaction_type") or ""))
        if symbol:
            segments.append(f"{action} {symbol}")
    if not segments:
        return "made a notable move"
    if len(segments) == 1:
        return segments[0]
    return ", ".join(segments[:-1]) + f", and {segments[-1]}"


def _pick_symbol(trades: List[Dict[str, Any]]) -> str:
    for trade in trades:
        symbol = str(trade.get("symbol") or trade.get("ticker") or "").upper().strip()
        if symbol:
            return symbol
    return ""


def compose_thread(
    filing: Dict[str, Any],
    signal: Dict[str, Any],
    insight: Dict[str, Any],
    context: Dict[str, Any],
    stats: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Build a 3-tweet thread payload with varied structure."""

    trades = _extract_trades(filing)
    member = _member_name(trades[0]) if trades else "A member"
    trade_blurb = _trade_blurb(trades)
    symbol = _pick_symbol(trades)

    hook = str(insight.get("hook") or "")
    interpretation = str(insight.get("interpretation") or "")
    question = str(insight.get("question") or "")

    signal_type = str(signal.get("signalType") or "OTHER")
    score = stats.get("score") or signal.get("diagnostics", {}).get("score") or "-"

    seed = f"{member}|{symbol}|{signal_type}|{filing.get('disclosureDate', '')}"
    mode = abs(hash(seed)) % 3

    if mode == 0:
        tweet1 = f"{hook} {member} {trade_blurb}. {interpretation} {question}"
    elif mode == 1:
        tweet1 = f"{hook} Flow recap: {member} {trade_blurb}. {interpretation} {question}"
    else:
        tweet1 = f"{hook} Setup: {member} {trade_blurb}. {interpretation} {question}"

    stat_line_options = [
        f"Signal score {score}/10 with {signal_type.lower()} characteristics.",
        f"Signal engine tagged this as {signal_type.lower()} with conviction score {score}.",
        f"Quant check: {signal_type.lower()} setup scored {score}, momentum not guaranteed.",
    ]
    stat_line = stat_line_options[mode]

    tweet2 = _trim(
        f"Chart watch on {symbol or 'the lead ticker'}: {stat_line} Trade count in filing: {len(trades)}."
    )

    historical = str(context.get("combinedSummary") or context.get("lastTradeOutcome") or "")
    tail_options = [
        "History helps frame it, not predict it.",
        "Use this as context, not certainty.",
        "Useful edge maybe, guaranteed edge never.",
    ]
    tweet3 = _trim(f"{historical} {tail_options[mode]}")

    return [
        {
            "text": _trim(tweet1),
            "media_symbol": None,
            "media_trade_date": None,
        },
        {
            "text": tweet2,
            "media_symbol": symbol or None,
            "media_trade_date": str(trades[0].get("transactionDate") or trades[0].get("transaction_date") or "") or None,
        },
        {
            "text": tweet3,
            "media_symbol": None,
            "media_trade_date": None,
        },
    ]


def compose_daily_tape_thread(tape: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Compose 2-3 tweet thread summarizing last 24h activity."""

    total_filings = tape.get("total_filings", 0)
    largest_trade = tape.get("largest_trade")
    most_bought = tape.get("most_bought_ticker")
    most_sold = tape.get("most_sold_ticker")

    if total_filings == 0:
        tweet1 = _trim("Daily Tape: No new congressional filings in the last 24 hours.")
        return [{"text": tweet1, "media_symbol": None, "media_trade_date": None}]

    # Format amounts
    def _format_amount(amount_value: float) -> str:
        if amount_value >= 1_000_000:
            return f"${amount_value/1_000_000:.1f}M"
        elif amount_value >= 1_000:
            return f"${amount_value/1_000:.0f}K"
        else:
            return f"${amount_value:.0f}"

    tweet1_parts = [f"Daily Tape: {total_filings} filing{'s' if total_filings != 1 else ''} in the last 24h."]

    if largest_trade:
        ticker = largest_trade.get("ticker", "")
        member = largest_trade.get("member_name", "A member")
        value = largest_trade.get("amount_value", 0.0)
        if ticker and value > 0:
            tweet1_parts.append(f"Largest: {member} → {ticker} ({_format_amount(value)}).")

    tweet1 = _trim(" ".join(tweet1_parts))

    tweet2_parts = []
    if most_bought and most_bought.get("ticker"):
        ticker = most_bought["ticker"]
        value = most_bought.get("value", 0.0)
        tweet2_parts.append(f"Most bought: {ticker} ({_format_amount(value)}).")

    if most_sold and most_sold.get("ticker"):
        ticker = most_sold["ticker"]
        value = most_sold.get("value", 0.0)
        tweet2_parts.append(f"Most sold: {ticker} ({_format_amount(value)}).")

    if tweet2_parts:
        tweet2 = _trim(" ".join(tweet2_parts))
        return [
            {"text": tweet1, "media_symbol": None, "media_trade_date": None},
            {"text": tweet2, "media_symbol": None, "media_trade_date": None},
        ]

    return [{"text": tweet1, "media_symbol": None, "media_trade_date": None}]


def compose_seven_day_theme_thread(theme: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Compose 2-3 tweet thread with top tickers, clustering, buy/sell ratio."""

    top_5 = theme.get("top_5_tickers_by_value", [])
    clusters = theme.get("cluster_tickers", [])
    net_buy_sell = theme.get("net_buy_vs_sell", {})

    if not top_5:
        tweet1 = _trim("7-Day Theme: No significant activity in the last week.")
        return [{"text": tweet1, "media_symbol": None, "media_trade_date": None}]

    def _format_amount(amount_value: float) -> str:
        if amount_value >= 1_000_000:
            return f"${amount_value/1_000_000:.1f}M"
        elif amount_value >= 1_000:
            return f"${amount_value/1_000:.0f}K"
        else:
            return f"${amount_value:.0f}"

    # Top tickers
    top_tickers_str = ", ".join([f"{t['ticker']} ({_format_amount(t['value'])})" for t in top_5[:3]])
    tweet1 = _trim(f"7-Day Theme: Top tickers by volume — {top_tickers_str}.")

    tweet2_parts = []

    # Clustering
    if clusters:
        cluster_tickers_str = ", ".join([f"{c['ticker']} ({c['member_count']} members)" for c in clusters[:3]])
        tweet2_parts.append(f"Clusters: {cluster_tickers_str}.")

    # Buy/sell ratio
    net_buy = net_buy_sell.get("net_buy", 0.0)
    net_sell = net_buy_sell.get("net_sell", 0.0)
    if net_buy > 0 or net_sell > 0:
        if net_buy > net_sell:
            ratio = f"{net_buy/net_sell:.1f}x" if net_sell > 0 else "all buys"
            tweet2_parts.append(f"Net: {ratio} buy vs sell bias.")
        else:
            ratio = f"{net_sell/net_buy:.1f}x" if net_buy > 0 else "all sells"
            tweet2_parts.append(f"Net: {ratio} sell vs buy bias.")

    if tweet2_parts:
        tweet2 = _trim(" ".join(tweet2_parts))
        return [
            {"text": tweet1, "media_symbol": top_5[0]["ticker"] if top_5 else None, "media_trade_date": None},
            {"text": tweet2, "media_symbol": None, "media_trade_date": None},
        ]

    return [{"text": tweet1, "media_symbol": top_5[0]["ticker"] if top_5 else None, "media_trade_date": None}]


def compose_member_spotlight_thread(spotlight: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Compose 2-tweet thread: member name, trade, amount, short description."""

    if not spotlight:
        return []

    member = spotlight.get("member", "A member")
    ticker = spotlight.get("ticker", "")
    amount_value = spotlight.get("amount_value", 0.0)
    trans_type = spotlight.get("transaction_type", "")
    description = spotlight.get("description", "")

    def _format_amount(value: float) -> str:
        if value >= 1_000_000:
            return f"${value/1_000_000:.1f}M"
        elif value >= 1_000:
            return f"${value/1_000:.0f}K"
        else:
            return f"${value:.0f}"

    action = action_verb(str(trans_type or ""))

    tweet1 = _trim(f"Member Spotlight: {member} {action} {ticker} ({_format_amount(amount_value)}).")

    if description:
        tweet2 = _trim(f"Context: {description[:200]}.")
    else:
        tweet2 = _trim(f"Largest single trade in the last 24 hours.")

    return [
        {"text": tweet1, "media_symbol": ticker or None, "media_trade_date": None},
        {"text": tweet2, "media_symbol": None, "media_trade_date": None},
    ]
