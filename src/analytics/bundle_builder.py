"""Build bundles from database and filter unposted content."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List

try:
    from db import cursor
    from filing_utils import is_postable_congress_trade
except ImportError:  # pragma: no cover
    from src.db import cursor
    from src.filing_utils import is_postable_congress_trade


def _split_member_name(member_name: str) -> tuple[str, str]:
    """Split full member name into first and last parts."""
    if not member_name:
        return ("", "")
    first, last = (member_name.split(" ", 1) + [""])[:2]
    return first, last


def _trade_row_to_dict(row: tuple[Any, ...]) -> Dict[str, Any]:
    """Map a trades table row into the canonical trade dictionary shape."""
    member_name = str(row[9] or "")
    first, last = _split_member_name(member_name)
    return {
        "symbol": row[0],
        "ticker": row[0],
        "disclosureDate": row[1],
        "disclosure_date": row[1],
        "transactionDate": row[2],
        "transaction_date": row[2],
        "district": row[3],
        "owner": row[4],
        "assetDescription": row[5],
        "asset_description": row[5],
        "assetType": row[6],
        "amount": row[7],
        "type": row[8],
        "transaction_type": row[8],
        "member_name": member_name,
        "firstName": first,
        "lastName": last,
        "comment": row[10],
    }


def fetch_recent_trades(days: int = 400, now_et: datetime | None = None) -> List[Dict[str, Any]]:
    """Read recent history from SQLite for signal and context calculations."""

    if now_et is None:
        from zoneinfo import ZoneInfo
        ET = ZoneInfo("America/New_York")
        now_et = datetime.now(ET)

    start_date = (now_et - timedelta(days=days)).strftime("%Y-%m-%d")
    cursor.execute(
        """
        SELECT ticker, disclosure_date, transaction_date, district, owner,
               asset_description, asset_type, amount, transaction_type,
               member_name, comment
        FROM trades
        WHERE disclosure_date >= ?
        ORDER BY disclosure_date DESC
        """,
        (start_date,),
    )

    rows = cursor.fetchall()
    history: List[Dict[str, Any]] = []
    for row in rows:
        history.append(_trade_row_to_dict(row))

    return history


def build_bundles_from_db(now_et: datetime, hours: int = 24) -> List[Dict[str, Any]]:
    """Query trades table and group by member+disclosure_date into bundles.

    Note: uses date-level filtering (disclosure_date >= start_date) so the actual
    window may include earlier trades from the start day. This is intentional to
    avoid missing filings near midnight boundaries.
    """

    start_date = (now_et - timedelta(hours=hours)).strftime("%Y-%m-%d")
    cursor.execute(
        """
        SELECT ticker, disclosure_date, transaction_date, district, owner,
               asset_description, asset_type, amount, transaction_type,
               member_name, comment
        FROM trades
        WHERE disclosure_date >= ?
        ORDER BY disclosure_date DESC, transaction_date DESC
        """,
        (start_date,),
    )

    rows = cursor.fetchall()
    trades: List[Dict[str, Any]] = []
    for row in rows:
        trade = _trade_row_to_dict(row)
        if is_postable_congress_trade(trade):
            trades.append(trade)

    # Group by member + disclosure_date
    grouped: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        key = (
            str(trade.get("firstName", "")).strip(),
            str(trade.get("lastName", "")).strip(),
            str(trade.get("disclosureDate", "")).strip(),
        )
        grouped[key].append(trade)

    bundles: List[Dict[str, Any]] = []
    for (first, last, disclosure_date), filing_trades in grouped.items():
        filing_trades = sorted(
            filing_trades,
            key=lambda item: str(item.get("transactionDate") or item.get("disclosureDate") or ""),
        )
        primary = filing_trades[0]
        bundles.append(
            {
                "firstName": first,
                "lastName": last,
                "member_name": f"{first} {last}".strip(),
                "disclosureDate": disclosure_date,
                "transactionDate": primary.get("transactionDate") or disclosure_date,
                "source": primary.get("source"),
                "trades": filing_trades,
            }
        )

    return bundles


def bundle_id(bundle: Dict[str, Any]) -> str:
    """Generate deterministic bundle ID: SHA256 of member_name|disclosure_date."""
    member_name = bundle.get("member_name", "")
    disclosure_date = bundle.get("disclosureDate", "")
    payload = f"{member_name}|{disclosure_date}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def filter_unposted(bundles: List[Dict[str, Any]], date: str) -> List[Dict[str, Any]]:
    """Filter out bundles that have already been posted (ALERT content_type)."""

    if not bundles:
        return []

    # Keep `date` for caller compatibility; ALERT dedupe must be cross-day.
    _ = date

    # Get all posted ALERT bundle_ids across all dates.
    cursor.execute(
        """
        SELECT DISTINCT bundle_id
        FROM posted_content_log
        WHERE content_type = 'ALERT' AND bundle_id IS NOT NULL
        """
    )
    posted_bundle_ids = {row[0] for row in cursor.fetchall()}

    unposted = []
    for bundle in bundles:
        bid = bundle_id(bundle)
        if bid not in posted_bundle_ids:
            unposted.append(bundle)

    return unposted
