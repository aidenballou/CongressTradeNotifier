"""Detect high-conviction corporate-insider buying setups and compose tweet threads.

This module sits on top of :mod:`insider` and targets three setups that tend to
outperform on financial Twitter:

* ``CLUSTER_BUY`` — two or more distinct insiders opening open-market buys on the
  same ticker within a short window.
* ``CSUITE_BUY`` — a single CEO/CFO/COO/President open-market purchase of
  meaningful size.
* ``UNUSUAL_SIZE_BUY`` — any single open-market buy above a large-size threshold.

Only ``P-Purchase`` transactions count. Insider *sales* are intentionally ignored
because they are dominated by 10b5-1 plans, tax withholding and diversification
and produce low-signal tweets.
"""

from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

try:
    from insider import fetch_insider_trades_window
except ImportError:  # pragma: no cover
    from src.insider import fetch_insider_trades_window


MAX_TWEET_LEN = 280

# Signal thresholds (override via env for tuning without a code change).
CLUSTER_MIN_INSIDERS = int(os.getenv("INSIDER_CLUSTER_MIN_INSIDERS", "2"))
CLUSTER_MIN_VALUE = float(os.getenv("INSIDER_CLUSTER_MIN_VALUE", "250000"))
CSUITE_MIN_VALUE = float(os.getenv("INSIDER_CSUITE_MIN_VALUE", "250000"))
LARGE_SINGLE_BUY_VALUE = float(os.getenv("INSIDER_LARGE_SINGLE_VALUE", "1000000"))
LOOKBACK_DAYS_DEFAULT = int(os.getenv("INSIDER_LOOKBACK_DAYS", "7"))


@dataclass
class InsiderSignal:
    """A normalized insider-buy setup worth tweeting about."""

    sub_type: str  # CLUSTER_BUY / CSUITE_BUY / UNUSUAL_SIZE_BUY
    ticker: str
    trades: List[Dict[str, Any]] = field(default_factory=list)
    total_value: float = 0.0
    total_shares: float = 0.0
    unique_insiders: int = 0
    earliest_date: Optional[datetime] = None
    latest_date: Optional[datetime] = None
    score: float = 0.0
    headline_insider: Optional[Dict[str, Any]] = None

    def bundle_id(self) -> str:
        """Stable, human-readable id for dedupe.

        Format: ``INSIDER|{sub_type}|{TICKER}|{YYYY}-W{WW}``. Keeping the ticker
        in plaintext lets :func:`has_insider_alert_recent` use a cheap LIKE match
        so we don't re-alert the same ticker from a different sub-type within the
        dedupe window (e.g. a cluster buy followed days later by a larger single buy).
        """

        anchor = self.earliest_date or self.latest_date or datetime.utcnow()
        iso_year, iso_week, _ = anchor.isocalendar()
        return f"INSIDER|{self.sub_type}|{self.ticker}|{iso_year}-W{iso_week:02d}"


def _format_amount(value: float) -> str:
    """Compact dollar formatting matching the rest of the composer."""

    value = float(value or 0)
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.1f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"${value / 1_000:.0f}K"
    return f"${value:,.0f}"


def _trim(text: str, limit: int = MAX_TWEET_LEN) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def _short_title(title: str) -> str:
    """Collapse noisy FMP ``typeOfOwner`` strings into a short role label."""

    if not title:
        return "insider"
    lowered = title.lower()
    if "chief executive" in lowered:
        return "CEO"
    if "chief financial" in lowered:
        return "CFO"
    if "chief operating" in lowered:
        return "COO"
    if "chief technology" in lowered:
        return "CTO"
    if "chief investment" in lowered:
        return "CIO"
    if "chairman" in lowered:
        return "Chairman"
    if "president" in lowered:
        return "President"
    if "director" in lowered:
        return "Director"
    if "10 percent owner" in lowered or "10% owner" in lowered:
        return "10% owner"
    if "officer" in lowered:
        return "officer"
    # Fall back to the raw string but keep it short.
    short = title.split(":", 1)[-1].strip()
    return short[:40] or "insider"


def _proper_name(name: str) -> str:
    """Convert FMP's ALL-CAPS ``LAST FIRST`` strings into ``First Last``."""

    if not name:
        return "An insider"
    cleaned = " ".join(part for part in name.replace(",", " ").split() if part)
    if not cleaned:
        return "An insider"
    # FMP often formats as "LAST FIRST MIDDLE" — if so, reorder to "First Last".
    parts = cleaned.split()
    if len(parts) >= 2 and cleaned.isupper():
        first_middle = " ".join(parts[1:]).title()
        last = parts[0].title()
        return f"{first_middle} {last}".strip()
    return cleaned.title() if cleaned.isupper() else cleaned


def _group_by_ticker(trades: Sequence[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        ticker = (trade.get("symbol") or "").upper().strip()
        if not ticker:
            continue
        grouped[ticker].append(trade)
    return grouped


def _select_headline_trade(trades: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Pick the most tweet-worthy trade from a group (C-suite preferred, then size)."""

    def sort_key(trade: Dict[str, Any]) -> tuple:
        return (
            1 if trade.get("is_csuite") else 0,
            1 if trade.get("is_director") else 0,
            float(trade.get("value") or 0),
        )

    return max(trades, key=sort_key)


def _build_signal(sub_type: str, ticker: str, trades: List[Dict[str, Any]]) -> InsiderSignal:
    dates = [t.get("transaction_date") for t in trades if t.get("transaction_date")]
    total_value = sum(float(t.get("value") or 0) for t in trades)
    total_shares = sum(float(t.get("shares") or 0) for t in trades)
    unique_insiders = len({(t.get("insider_name") or "").lower() for t in trades if t.get("insider_name")})

    # Engagement-weighted score: cluster > csuite > size, with a value kicker.
    base = {
        "CLUSTER_BUY": 40.0,
        "CSUITE_BUY": 30.0,
        "UNUSUAL_SIZE_BUY": 20.0,
    }.get(sub_type, 10.0)
    size_kicker = min(40.0, total_value / 250_000.0 * 5.0)
    diversity_kicker = min(20.0, max(0, unique_insiders - 1) * 10.0)
    score = base + size_kicker + diversity_kicker

    return InsiderSignal(
        sub_type=sub_type,
        ticker=ticker,
        trades=sorted(
            trades,
            key=lambda t: (float(t.get("value") or 0), t.get("transaction_date") or datetime.min),
            reverse=True,
        ),
        total_value=total_value,
        total_shares=total_shares,
        unique_insiders=unique_insiders or len(trades),
        earliest_date=min(dates) if dates else None,
        latest_date=max(dates) if dates else None,
        score=score,
        headline_insider=_select_headline_trade(trades),
    )


def detect_insider_signals(
    insider_trades: Sequence[Dict[str, Any]],
    *,
    cluster_min_insiders: int = CLUSTER_MIN_INSIDERS,
    cluster_min_value: float = CLUSTER_MIN_VALUE,
    csuite_min_value: float = CSUITE_MIN_VALUE,
    large_single_value: float = LARGE_SINGLE_BUY_VALUE,
) -> List[InsiderSignal]:
    """Classify a batch of open-market buys into tweetable signals.

    Each ticker produces at most one signal — the highest-priority one (cluster beats
    C-suite beats unusual-size) — so we never stack two insider alerts on the same name.
    """

    grouped = _group_by_ticker(insider_trades)
    signals: List[InsiderSignal] = []

    for ticker, trades in grouped.items():
        if not trades:
            continue
        eligible = [t for t in trades if float(t.get("value") or 0) > 0]
        if not eligible:
            continue

        unique_insider_names = {
            (t.get("insider_name") or "").strip().lower()
            for t in eligible
            if t.get("insider_name")
        }
        total_value = sum(float(t.get("value") or 0) for t in eligible)

        # 1) Cluster — multiple distinct insiders.
        if len(unique_insider_names) >= cluster_min_insiders and total_value >= cluster_min_value:
            signals.append(_build_signal("CLUSTER_BUY", ticker, eligible))
            continue

        # 2) C-suite single buy of meaningful size.
        csuite_trade = next(
            (
                t
                for t in sorted(eligible, key=lambda x: float(x.get("value") or 0), reverse=True)
                if t.get("is_csuite") and float(t.get("value") or 0) >= csuite_min_value
            ),
            None,
        )
        if csuite_trade is not None:
            signals.append(_build_signal("CSUITE_BUY", ticker, [csuite_trade]))
            continue

        # 3) Any unusually large single open-market buy.
        big_trade = next(
            (
                t
                for t in sorted(eligible, key=lambda x: float(x.get("value") or 0), reverse=True)
                if float(t.get("value") or 0) >= large_single_value
            ),
            None,
        )
        if big_trade is not None:
            signals.append(_build_signal("UNUSUAL_SIZE_BUY", ticker, [big_trade]))
            continue

    signals.sort(key=lambda s: s.score, reverse=True)
    return signals


def find_top_insider_signal(
    *,
    days: int = LOOKBACK_DAYS_DEFAULT,
    now: Optional[datetime] = None,
) -> Optional[InsiderSignal]:
    """Fetch recent insider buys and return the single most engaging setup.

    Returns ``None`` when the API returned no data or nothing cleared the thresholds.
    """

    insider_trades = fetch_insider_trades_window(days=days, now=now)
    if not insider_trades:
        return None
    signals = detect_insider_signals(insider_trades)
    return signals[0] if signals else None


# ---------------------------------------------------------------------------
# Tweet composition
# ---------------------------------------------------------------------------


def _window_phrase(signal: InsiderSignal) -> str:
    """Natural-language description of how recent the buying is."""

    if not signal.earliest_date or not signal.latest_date:
        return "recently"
    delta_days = max(0, (signal.latest_date - signal.earliest_date).days)
    if delta_days <= 1:
        return "in the last 24h"
    if delta_days <= 3:
        return f"in the last {delta_days} days"
    return f"over the last {delta_days} days"


def _hook_cluster(signal: InsiderSignal) -> str:
    insiders = signal.unique_insiders
    window = _window_phrase(signal)
    amount = _format_amount(signal.total_value)
    titles = []
    for trade in signal.trades[:3]:
        role = _short_title(trade.get("title", ""))
        if role and role not in titles:
            titles.append(role)
    role_blurb = ""
    if titles:
        if len(titles) == 1:
            role_blurb = f" ({titles[0]})"
        else:
            role_blurb = f" (incl. {', '.join(titles[:2])})"
    return (
        f"🚨 ${signal.ticker}: {insiders} insiders{role_blurb} just bought "
        f"{amount} combined on the open market {window}."
    )


def _hook_csuite(signal: InsiderSignal) -> str:
    trade = signal.headline_insider or signal.trades[0]
    role = _short_title(trade.get("title", ""))
    name = _proper_name(trade.get("insider_name", ""))
    amount = _format_amount(trade.get("value") or signal.total_value)
    return (
        f"🟢 ${signal.ticker}: {role} {name} just bought {amount} "
        f"of stock on the open market."
    )


def _hook_unusual_size(signal: InsiderSignal) -> str:
    trade = signal.headline_insider or signal.trades[0]
    role = _short_title(trade.get("title", ""))
    name = _proper_name(trade.get("insider_name", ""))
    amount = _format_amount(trade.get("value") or signal.total_value)
    return (
        f"📈 Unusual size on ${signal.ticker}: {name} ({role}) "
        f"bought {amount} in the open market."
    )


def _tweet1_hook(signal: InsiderSignal) -> str:
    if signal.sub_type == "CLUSTER_BUY":
        return _hook_cluster(signal)
    if signal.sub_type == "CSUITE_BUY":
        return _hook_csuite(signal)
    return _hook_unusual_size(signal)


def _tweet2_context(signal: InsiderSignal) -> str:
    trade = signal.headline_insider or signal.trades[0]
    shares = float(trade.get("shares") or 0)
    price = float(trade.get("price") or 0)
    trade_date = trade.get("transaction_date")
    pretty_date = trade_date.strftime("%b %d") if isinstance(trade_date, datetime) else "recently"

    if signal.sub_type == "CLUSTER_BUY":
        top_names = [
            _proper_name(t.get("insider_name", ""))
            for t in signal.trades[:3]
            if t.get("insider_name")
        ]
        names_blurb = ", ".join(top_names[:2]) if top_names else "multiple insiders"
        return _trim(
            f"Buyers include {names_blurb} — and they're spending personal cash, not "
            f"exercising options. Clustered insider buying has historically skewed "
            f"bullish. Coincidence, or are they seeing something the tape isn't?"
        )

    if signal.sub_type == "CSUITE_BUY":
        detail = (
            f"{shares:,.0f} shares at ~${price:,.2f} on {pretty_date}"
            if shares and price
            else f"filed {pretty_date}"
        )
        return _trim(
            f"When the top of the org chart puts real money on the line ({detail}), "
            f"it usually means one thing: they think the stock is worth more than "
            f"the market is pricing it. Signal, or optics?"
        )

    # UNUSUAL_SIZE_BUY
    detail = (
        f"{shares:,.0f} shares at ~${price:,.2f}" if shares and price else "size alone is unusual"
    )
    return _trim(
        f"This open-market purchase ({detail}) is materially larger than routine insider "
        f"activity. Size alone is not a thesis, but it makes follow-through worth tracking."
    )


def _tweet3_framing(signal: InsiderSignal) -> str:
    total = _format_amount(signal.total_value)
    window = _window_phrase(signal)
    if signal.sub_type == "CLUSTER_BUY":
        return _trim(
            f"Aggregate open-market buying on ${signal.ticker}: {total} across "
            f"{signal.unique_insiders} insiders {window}. Track the follow-through, "
            f"not the headline. Form 4 filings via SEC."
        )
    if signal.sub_type == "CSUITE_BUY":
        return _trim(
            f"Executive buying on ${signal.ticker} totals {total} {window}. "
            f"History helps frame it, not predict it. Source: SEC Form 4."
        )
    return _trim(
        f"Recap: ${signal.ticker} saw {total} of open-market insider buying {window}. "
        f"Treat this as context, not a trade trigger. Source: SEC Form 4."
    )


def compose_insider_alert_thread(signal: InsiderSignal) -> List[Dict[str, Any]]:
    """Build a 3-tweet thread for an :class:`InsiderSignal`.

    The root tweet carries the chart (via ``media_symbol``) so X renders the
    price context next to the hook — the configuration that has historically
    produced the highest engagement on the existing congressional alerts.
    """

    if not signal or not signal.ticker:
        return []

    headline_trade = signal.headline_insider or (signal.trades[0] if signal.trades else {})
    tx_date = headline_trade.get("transaction_date")
    media_date = tx_date.strftime("%Y-%m-%d") if isinstance(tx_date, datetime) else None

    tweet1 = _trim(_tweet1_hook(signal))
    tweet2 = _tweet2_context(signal)
    tweet3 = _tweet3_framing(signal)

    return [
        {
            "text": tweet1,
            "media_symbol": signal.ticker,
            "media_trade_date": media_date,
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


__all__ = [
    "InsiderSignal",
    "detect_insider_signals",
    "find_top_insider_signal",
    "compose_insider_alert_thread",
]
