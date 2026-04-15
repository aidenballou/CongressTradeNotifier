"""Compose 3-tweet engagement threads for high-signal filings."""

from __future__ import annotations

from typing import Any, Dict, List

try:
    from filing_utils import (
        action_verb,
        extract_trades as _extract_trades,
        member_name as _member_name,
        stable_mode as _stable_mode,
    )
except ImportError:  # pragma: no cover
    from src.filing_utils import (
        action_verb,
        extract_trades as _extract_trades,
        member_name as _member_name,
        stable_mode as _stable_mode,
    )


MAX_TWEET_LEN = 280


def _trim(text: str, limit: int = MAX_TWEET_LEN) -> str:
    value = " ".join((text or "").split())
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def _quality_check_tweet1(text: str) -> str:
    """Lightweight checks: trim to limit, reduce obvious repetition."""
    out = " ".join((text or "").split())
    if len(out) > MAX_TWEET_LEN:
        out = out[: MAX_TWEET_LEN - 1].rstrip() + "…"
    # Avoid duplicate phrase (e.g. "Flow recap: ... Flow recap:")
    if "Flow recap:" in out and out.count("Flow recap:") > 1:
        out = out.replace("Flow recap:", "", 1).strip()
        if out.startswith("Flow recap:"):
            out = out[len("Flow recap:") :].strip()
    if "Setup:" in out and out.count("Setup:") > 1:
        out = out.replace("Setup:", "", 1).strip()
        if out.startswith("Setup:"):
            out = out[len("Setup:") :].strip()
    return _trim(out)


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


def _format_amount(value: float) -> str:
    """Format dollar values as $XM/$XK/$X."""
    if value >= 1_000_000:
        return f"${value/1_000_000:.1f}M"
    if value >= 1_000:
        return f"${value/1_000:.0f}K"
    return f"${value:.0f}"


def compose_thread(
    filing: Dict[str, Any],
    signal: Dict[str, Any],
    insight: Dict[str, Any],
    context: Dict[str, Any],
    stats: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Build a 3-tweet thread: hook+action (tweet 1), context+question (tweet 2), history+stats (tweet 3)."""

    trades = _extract_trades(filing)
    member = _member_name(trades[0]) if trades else "A member"
    trade_blurb = _trade_blurb(trades)
    symbol = _pick_symbol(trades)

    hook = str(insight.get("hook") or "")
    interpretation = str(insight.get("interpretation") or "")
    question = str(insight.get("question") or "")
    last_outcome = str(context.get("lastTradeOutcome") or "").strip()

    signal_type = str(signal.get("signalType") or "OTHER")
    score = stats.get("score") or signal.get("diagnostics", {}).get("score") or "-"

    seed = f"{member}|{symbol}|{signal_type}|{filing.get('disclosureDate', '')}"
    mode = _stable_mode(seed)

    # Tweet 1: Hook + member action (the attention-grabber with chart)
    if mode == 0:
        tweet1 = f"{hook} {member} {trade_blurb}."
    elif mode == 1:
        tweet1 = f"{hook} Flow recap: {member} {trade_blurb}."
    else:
        tweet1 = f"{hook} Setup: {member} {trade_blurb}."

    if last_outcome and len(tweet1) + len(last_outcome) + 2 <= MAX_TWEET_LEN:
        tweet1 = f"{tweet1} {last_outcome}"

    tweet1 = _quality_check_tweet1(tweet1)

    # Tweet 2: Interpretation + engagement question (the market context)
    stat_line_options = [
        f"Signal score {score}/10 with {signal_type.lower()} characteristics.",
        f"Signal engine tagged this as {signal_type.lower()} with conviction score {score}.",
        f"Quant check: {signal_type.lower()} setup scored {score}, momentum not guaranteed.",
    ]
    stat_line = stat_line_options[mode]

    tweet2_base = f"{interpretation} {question}"
    tweet2_with_stat = f"{interpretation} {stat_line} {question}"
    if len(" ".join(tweet2_with_stat.split())) <= MAX_TWEET_LEN:
        tweet2 = _trim(tweet2_with_stat)
    else:
        tweet2 = _trim(tweet2_base)

    # Tweet 3: Historical context + closing framing
    historical = str(context.get("combinedSummary") or "")
    if last_outcome and not historical:
        historical = last_outcome
    tail_options = [
        "History helps frame it, not predict it.",
        "Use this as context, not certainty.",
        "Useful edge maybe, guaranteed edge never.",
    ]
    chart_note = f"Chart watch on {symbol or 'the lead ticker'}: {len(trades)} trade{'s' if len(trades) != 1 else ''} in filing."
    tweet3_candidate = f"{historical} {chart_note} {tail_options[mode]}"
    if len(" ".join(tweet3_candidate.split())) > MAX_TWEET_LEN:
        tweet3_candidate = f"{historical} {tail_options[mode]}"
    tweet3 = _trim(tweet3_candidate)

    media_date = str(trades[0].get("transactionDate") or trades[0].get("transaction_date") or "") if trades else None

    return [
        {
            "text": tweet1,
            "media_symbol": symbol or None,
            "media_trade_date": media_date or None,
        },
        {
            "text": tweet2,
            "media_symbol": None,
            "media_trade_date": None,
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
