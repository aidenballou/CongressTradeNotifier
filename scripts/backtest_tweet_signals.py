#!/usr/bin/env python3
"""
Backtest which filings would be tweeted (HIGH signal) from the SQLite DB,
optionally excluding the "first trade in ticker" score contribution.

Usage:
  python scripts/backtest_tweet_signals.py
  python scripts/backtest_tweet_signals.py --csv out.csv
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
import sqlite3
import sys
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

# Allow importing from src when run as script from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trade_analyzer import analyze_filing


ET = ZoneInfo("America/New_York")


def _parse_ymd(value: str) -> Optional[date]:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except Exception:
        return None


def _ymd(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def _split_name(member_name: str) -> Tuple[str, str]:
    member_name = str(member_name or "").strip()
    if not member_name:
        return ("", "")
    first, last = (member_name.split(" ", 1) + [""])[:2]
    return (first, last)


def _trade_row_to_dict(row: Tuple[Any, ...]) -> Dict[str, Any]:
    """
    Mirrors the dict shape built by src/main.py::_fetch_recent_trades, but for any row.
    """
    (
        ticker,
        disclosure_date,
        transaction_date,
        district,
        owner,
        asset_description,
        asset_type,
        amount,
        transaction_type,
        member_name,
        comment,
    ) = row

    member_name = str(member_name or "")
    first, last = _split_name(member_name)

    return {
        "symbol": ticker,
        "ticker": ticker,
        "disclosureDate": disclosure_date,
        "disclosure_date": disclosure_date,
        "transactionDate": transaction_date,
        "transaction_date": transaction_date,
        "district": district,
        "owner": owner,
        "assetDescription": asset_description,
        "asset_description": asset_description,
        "assetType": asset_type,
        "amount": amount,
        "type": transaction_type,
        "transaction_type": transaction_type,
        "member_name": member_name,
        "firstName": first,
        "lastName": last,
        "comment": comment,
    }


def _load_all_trades(db_path: str) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT ticker, disclosure_date, transaction_date, district, owner,
                   asset_description, asset_type, amount, transaction_type,
                   member_name, comment
            FROM trades
            ORDER BY disclosure_date ASC, transaction_date ASC
            """
        )
        rows = cur.fetchall()
        return [_trade_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def _bundle_filings_from_db_trades(trades: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Bundle trades into filing-like units keyed by member_name + disclosureDate.
    """
    grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for t in trades:
        member = str(t.get("member_name") or "").strip()
        disc = str(t.get("disclosureDate") or t.get("disclosure_date") or "").strip()
        grouped.setdefault((member, disc), []).append(t)

    filings: List[Dict[str, Any]] = []
    for (member, disc), filing_trades in grouped.items():
        filing_trades = sorted(
            filing_trades,
            key=lambda item: str(item.get("transactionDate") or item.get("disclosureDate") or ""),
        )
        first, last = _split_name(member)
        primary = filing_trades[0] if filing_trades else {}
        filings.append(
            {
                "firstName": first,
                "lastName": last,
                "member_name": member,
                "disclosureDate": disc,
                "transactionDate": primary.get("transactionDate") or disc,
                "source": primary.get("source"),
                "trades": filing_trades,
            }
        )

    filings.sort(key=lambda f: str(f.get("disclosureDate") or ""))
    return filings


@dataclass(frozen=True)
class BacktestRow:
    disclosure_date: str
    member_name: str
    signal_type: str
    score: int
    summary: str


def _now_et_for_disclosure(disclosure_date: str) -> datetime:
    d = _parse_ymd(disclosure_date)
    if d is None:
        return datetime.now(ET)
    # Use noon ET as a stable point-in-day for backtest comparisons.
    return datetime(d.year, d.month, d.day, 12, 0, 0, tzinfo=ET)


def _history_window_for_filing(
    all_trades_sorted: List[Dict[str, Any]],
    filing_disclosure: str,
    days: int = 400,
) -> List[Dict[str, Any]]:
    filing_day = _parse_ymd(filing_disclosure)
    if filing_day is None:
        return []
    start = filing_day - timedelta(days=days)
    start_s = _ymd(start)
    end_s = filing_disclosure

    # Past-only history: start_s <= disclosureDate < end_s
    history: List[Dict[str, Any]] = []
    for t in all_trades_sorted:
        disc = str(t.get("disclosureDate") or t.get("disclosure_date") or "")
        if not disc:
            continue
        if disc < start_s:
            continue
        if disc >= end_s:
            break
        history.append(t)
    return history


def run_backtest(db_path: str, write_csv: Optional[str]) -> int:
    trades = _load_all_trades(db_path)
    filings = _bundle_filings_from_db_trades(trades)

    high_rows: List[BacktestRow] = []
    for filing in filings:
        disc = str(filing.get("disclosureDate") or "")
        now_et = _now_et_for_disclosure(disc)
        history = _history_window_for_filing(trades, disc, days=400)
        result = analyze_filing(
            filing,
            history,
            now_et,
            exclude_first_trade_in_ticker=True,
        )
        if result.get("signalStrength") != "HIGH":
            continue
        diagnostics = result.get("diagnostics") or {}
        score = int(diagnostics.get("score") or 0)
        member = str(filing.get("member_name") or f"{filing.get('firstName', '')} {filing.get('lastName', '')}").strip()
        high_rows.append(
            BacktestRow(
                disclosure_date=disc,
                member_name=member,
                signal_type=str(result.get("signalType") or ""),
                score=score,
                summary=str(result.get("summarySentence") or ""),
            )
        )

    print(f"DB: {db_path}")
    print(f"Filings processed: {len(filings)}")
    print(f'HIGH (tweet-eligible) with first-trade excluded: {len(high_rows)}')

    if write_csv:
        with open(write_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["disclosure_date", "member_name", "signal_type", "score", "summary"])
            for row in high_rows:
                w.writerow([row.disclosure_date, row.member_name, row.signal_type, row.score, row.summary])
        print(f"Wrote CSV: {write_csv}")

    # Also print a small preview to stdout
    for row in high_rows[:25]:
        print(f"{row.disclosure_date} | {row.member_name} | {row.signal_type} | score={row.score} | {row.summary}")
    if len(high_rows) > 25:
        print(f"... {len(high_rows) - 25} more")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="trades.sqlite3", help="Path to SQLite DB (default: trades.sqlite3)")
    parser.add_argument("--csv", default=None, help="Optional path to write CSV output")
    args = parser.parse_args()
    return run_backtest(db_path=args.db, write_csv=args.csv)


if __name__ == "__main__":
    raise SystemExit(main())

