"""Compose 3-tweet engagement threads for high-signal filings."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

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
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw[: len(fmt)], fmt)
        except ValueError:
            continue
    return None


def _format_date(value: Any) -> str:
    parsed = _parse_date(value)
    if parsed:
        return parsed.strftime("%b %-d, %Y")
    return str(value or "").strip()


def _days_between(start: Any, end: Any) -> Optional[int]:
    start_date = _parse_date(start)
    end_date = _parse_date(end)
    if not start_date or not end_date:
        return None
    return max((end_date - start_date).days, 0)


def _filed_delay_phrase(trade_date: Any, disclosure_date: Any) -> str:
    days = _days_between(trade_date, disclosure_date)
    if days is None:
        return ""
    if days == 0:
        return "Filed the same day."
    if days == 1:
        return "Filed 1 day later."
    return f"Filed {days} days later."


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
        return _format_amount(numeric_value)
    raw = str(trade.get("amount") or trade.get("amount_range") or "").strip()
    return raw if raw.startswith("$") else raw


def _action_label(action: Any) -> str:
    raw = str(action or "")
    verb = action_verb(raw)
    if verb == "bought":
        return "BUY"
    if verb == "sold":
        return "SELL"
    return "TRADE"


def _action_past(action: Any) -> str:
    return action_verb(str(action or ""))


def _clean_hook(hook: str) -> str:
    value = " ".join((hook or "").split())
    if not value:
        return ""
    lowered = value.lower()
    if any(claim in lowered for claim in VAGUE_CLAIMS):
        return ""
    if len(value) > 120:
        return ""
    return value.rstrip(".")


def _reason_it_matters(
    trade: Dict[str, Any],
    signal: Optional[Dict[str, Any]] = None,
    insight: Optional[Dict[str, Any]] = None,
    context: Optional[Dict[str, Any]] = None,
) -> str:
    days = _days_between(
        trade.get("transactionDate") or trade.get("transaction_date"),
        trade.get("disclosureDate") or trade.get("disclosure_date"),
    )
    if days is not None and days >= 30:
        return "late filing"

    signal_type = str((signal or {}).get("signalType") or "").replace("_", " ").strip().lower()
    if signal_type and signal_type != "other":
        return f"{signal_type} signal"

    hook = _clean_hook(str((insight or {}).get("hook") or ""))
    if hook:
        return hook

    if str((context or {}).get("combinedSummary") or "").strip():
        return "historical comparison available"
    return "largest trade in the batch"


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
    if len(text) < 45 and not allow_no_filings:
        return False
    if ticker_data_exists and not re.search(r"\$[A-Z][A-Z0-9.\-]{0,9}\b", text):
        return False
    if amount_data_exists and not re.search(r"\$[0-9]", text):
        return False
    return True


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
    symbol = _pick_symbol(trades)
    primary_trade = trades[0] if trades else {}
    amount = _trade_amount_text(primary_trade)
    action = _action_label(primary_trade.get("type") or primary_trade.get("transaction_type"))
    trade_date = primary_trade.get("transactionDate") or primary_trade.get("transaction_date")
    disclosure_date = filing.get("disclosureDate") or primary_trade.get("disclosureDate") or primary_trade.get("disclosure_date")
    primary_trade = {**primary_trade, "disclosureDate": disclosure_date}

    interpretation = str(insight.get("interpretation") or "")
    question = str(insight.get("question") or "")
    last_outcome = str(context.get("lastTradeOutcome") or "").strip()

    signal_type = str(signal.get("signalType") or "OTHER")
    score = stats.get("score") or signal.get("diagnostics", {}).get("score") or "-"

    seed = f"{member}|{symbol}|{signal_type}|{filing.get('disclosureDate', '')}"
    mode = _stable_mode(seed)

    # Tweet 1: concrete filing facts first, with interpretation only after the required facts.
    symbol_text = _ticker_text(symbol)
    amount_clause = f" worth about {amount}" if amount else ""
    trade_date_clause = f" Trade date: {_format_date(trade_date)}." if trade_date else ""
    filed_clause = f" {_filed_delay_phrase(trade_date, disclosure_date)}" if trade_date and disclosure_date else ""
    reason = _reason_it_matters(primary_trade, signal=signal, insight=insight, context=context)
    tweet1 = (
        f"{member} reported a {action} in {symbol_text or 'a disclosed asset'}{amount_clause}."
        f"{trade_date_clause}{filed_clause} Why it matters: {reason}."
    )

    if last_outcome and len(tweet1) + len(last_outcome) + 2 <= MAX_TWEET_LEN:
        tweet1 = f"{tweet1} {last_outcome}"

    tweet1 = _quality_check_tweet1(tweet1)
    if not validate_social_copy(tweet1, ticker_data_exists=bool(symbol), amount_data_exists=bool(amount)):
        tweet1 = _trim(f"{member} reported a {action} in {symbol_text or 'a disclosed asset'}{amount_clause}. Why it matters: {reason}.")

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

    thread = [
        {
            "text": tweet1,
            "media_symbol": symbol or None,
            "media_trade_date": media_date or None,
        }
    ]
    if interpretation and validate_social_copy(tweet2):
        thread.append({"text": tweet2, "media_symbol": None, "media_trade_date": None})
    if (historical or last_outcome) and validate_social_copy(tweet3):
        thread.append({"text": tweet3, "media_symbol": None, "media_trade_date": None})
    return thread


def compose_daily_tape_thread(tape: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Compose a strong single-tweet summary of the last 24h activity."""

    total_filings = tape.get("total_filings", 0)
    largest_trade = tape.get("largest_trade")
    most_bought = tape.get("most_bought_ticker")

    if total_filings == 0:
        tweet1 = _trim("No new congressional filings hit the tape in the last 24 hours.")
        return [{"text": tweet1, "media_symbol": None, "media_trade_date": None}]

    if largest_trade:
        ticker = _ticker_text(largest_trade.get("ticker"))
        member = largest_trade.get("member_name") or "A member"
        amount = _trade_amount_text(largest_trade)
        action = _action_past(largest_trade.get("action_normalized") or largest_trade.get("transaction_type"))
        delay = largest_trade.get("days_to_file")
        if delay is None:
            delay = _days_between(largest_trade.get("transaction_date"), largest_trade.get("disclosure_date"))
        if delay is None:
            delay_clause = ""
        elif delay == 1:
            delay_clause = " Filed 1 day after the trade."
        else:
            delay_clause = f" Filed {delay} days after the trade."
        tweet1 = _trim(
            f"Today's congressional tape: {total_filings} filing{'s' if total_filings != 1 else ''}. "
            f"Most notable: {member} reported a {action} in {ticker or 'a disclosed asset'}"
            f"{f' worth about {amount}' if amount else ''}.{delay_clause}"
        )
        if not validate_social_copy(tweet1, ticker_data_exists=bool(ticker), amount_data_exists=bool(amount)):
            tweet1 = _trim(
                f"{member} reported a {action} in {ticker or 'a disclosed asset'}"
                f"{f' worth about {amount}' if amount else ''}. Why it matters: largest trade in today's batch."
            )
        return [{"text": tweet1, "media_symbol": largest_trade.get("ticker") or None, "media_trade_date": largest_trade.get("transaction_date") or None}]

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

    tweet1 = _trim(f"Today's congressional tape: {total_filings} filing{'s' if total_filings != 1 else ''}. No single ticker stood out enough for a stronger read.")
    return [{"text": tweet1, "media_symbol": None, "media_trade_date": None}]


def compose_seven_day_theme_thread(theme: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Compose a single strong weekly/pattern post when a real cluster exists."""

    top_5 = theme.get("top_5_tickers_by_value", [])
    clusters = theme.get("cluster_tickers", [])

    if not top_5:
        tweet1 = _trim("No significant congressional trading cluster stood out over the last week.")
        return [{"text": tweet1, "media_symbol": None, "media_trade_date": None}]

    top_cluster = theme.get("top_cluster") or (clusters[0] if clusters else None)
    top_tickers_str = ", ".join([_ticker_text(t["ticker"]) for t in top_5[:3] if t.get("ticker")])
    buyer = theme.get("top_buyer_member") or "not concentrated in one member"
    if top_cluster:
        cluster_ticker = _ticker_text(top_cluster.get("ticker"))
        member_count = top_cluster.get("member_count", 0)
        tweet1 = _trim(
            f"Congress clustered around {cluster_ticker} this week. "
            f"{member_count} members reported trades; top names: {top_tickers_str}. "
            f"Biggest reported buyer: {buyer}."
        )
    else:
        leader = top_5[0]
        ticker = _ticker_text(leader.get("ticker"))
        tweet1 = _trim(
            f"{ticker} led congressional trading this week at about {_format_amount(leader.get('value', 0.0))}. "
            f"Top names: {top_tickers_str}. Watch whether this becomes a broader sector cluster."
        )

    return [{"text": tweet1, "media_symbol": top_5[0]["ticker"] if top_5 else None, "media_trade_date": None}]


def compose_member_spotlight_thread(spotlight: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Compose a single factual member spotlight."""

    if not spotlight:
        return []

    member = spotlight.get("member", "A member")
    ticker = spotlight.get("ticker", "")
    amount_value = spotlight.get("amount_value", 0.0)
    trans_type = spotlight.get("transaction_type", "")
    description = spotlight.get("description", "")

    action = action_verb(str(trans_type or ""))
    trade_date = spotlight.get("transaction_date")
    disclosure_date = spotlight.get("disclosure_date")
    reason = description[:90].strip() if description else "largest trade in the batch"
    tweet1 = _trim(
        f"{member} reported a {action} in {_ticker_text(ticker) or 'a disclosed asset'} "
        f"worth about {_format_amount(amount_value)}. "
        f"Trade date: {_format_date(trade_date)}. Filed: {_format_date(disclosure_date)}. "
        f"Why it matters: {reason}."
    )

    return [{"text": tweet1, "media_symbol": ticker or None, "media_trade_date": trade_date or None}]
