"""SQLite event loading for standalone copy-trade backtests."""

from __future__ import annotations

from datetime import date, datetime
import sqlite3
from typing import Iterable, List, Optional

from .models import TradeEvent


SUPPORTED_ACTIONS = {"purchase", "sale", "sale (partial)", "sale (full)"}


def parse_date(value: object) -> Optional[date]:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except Exception:
        return None


def parse_amount(amount: object) -> float:
    if amount is None:
        return 0.0
    if isinstance(amount, (int, float)):
        return float(amount)

    cleaned = str(amount).replace("$", "").replace(",", "").strip()
    if not cleaned:
        return 0.0
    parts = [part.strip() for part in cleaned.split(" - ")]
    try:
        values = [float(part) for part in parts if part]
    except ValueError:
        return 0.0
    if len(values) == 2:
        return (values[0] + values[1]) / 2.0
    if len(values) == 1:
        return values[0]
    return 0.0


def load_trade_events(db_path: str) -> List[TradeEvent]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, ticker, disclosure_date, transaction_date, member_name,
                   transaction_type, amount, amount_value, asset_description
            FROM trades
            WHERE ticker IS NOT NULL
              AND ticker != ''
              AND disclosure_date IS NOT NULL
              AND transaction_type IS NOT NULL
            ORDER BY disclosure_date ASC, id ASC
            """
        ).fetchall()
    finally:
        conn.close()

    events: List[TradeEvent] = []
    for row in rows:
        disclosure_date = parse_date(row["disclosure_date"])
        if disclosure_date is None:
            continue

        action = str(row["transaction_type"] or "").strip()
        if action.lower() not in SUPPORTED_ACTIONS:
            continue

        amount_value = row["amount_value"]
        parsed_amount = float(amount_value) if amount_value not in (None, "") else parse_amount(row["amount"])
        events.append(
            TradeEvent(
                id=int(row["id"]),
                ticker=str(row["ticker"]).strip().upper(),
                disclosure_date=disclosure_date,
                transaction_date=parse_date(row["transaction_date"]),
                member_name=str(row["member_name"] or "").strip(),
                transaction_type=action,
                amount_text=str(row["amount"] or ""),
                amount_value=parsed_amount,
                asset_description=str(row["asset_description"] or ""),
            )
        )
    return events


def filter_events(
    events: Iterable[TradeEvent],
    members: Optional[set[str]] = None,
    tickers: Optional[set[str]] = None,
) -> List[TradeEvent]:
    filtered: List[TradeEvent] = []
    normalized_members = {m.strip().lower() for m in members or set() if m.strip()}
    normalized_tickers = {t.strip().upper() for t in tickers or set() if t.strip()}
    for event in events:
        if normalized_members and event.member_name.lower() not in normalized_members:
            continue
        if normalized_tickers and event.ticker.upper() not in normalized_tickers:
            continue
        filtered.append(event)
    return filtered

