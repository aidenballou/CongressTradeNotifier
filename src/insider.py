"""Helpers for enriching congressional trades with corporate insider activity."""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping

import requests
from dotenv import load_dotenv

# Ensure environment variables are loaded for local runs
load_dotenv()

API_KEY = os.getenv("FMP_API_KEY")
BASE_URL = "https://financialmodelingprep.com"


def fetch_latest_insider_trades(limit: int = 250) -> List[Dict[str, Any]]:
    """Fetch the latest corporate insider trading disclosures from FMP.

    Parameters
    ----------
    limit:
        Maximum number of insider trade records to request. The API currently
        supports up to 1,000 items per call. Smaller limits reduce payload size
        when running locally.
    """

    if not API_KEY:
        print("[Insider] Skipping fetch_latest_insider_trades: FMP_API_KEY is not set")
        return []

    url = f"{BASE_URL}/stable/insider-trading/latest?page=0&limit={limit}&apikey={API_KEY}"
    try:
        response = requests.get(url, timeout=15)
    except Exception as exc:  # pragma: no cover - defensive logging only
        print(f"[Insider] Request failed: {exc}")
        return []

    if response.status_code != 200:
        print(
            "[Insider] Unexpected status code",
            response.status_code,
            response.text[:200],
        )
        return []

    try:
        payload = response.json()
    except ValueError:
        print("[Insider] Failed to decode JSON response")
        return []

    if isinstance(payload, list):
        return payload

    print("[Insider] Unexpected payload type", type(payload))
    return []


def find_recent_insider_activity(
    trades: Iterable[Mapping[str, Any]],
    *,
    lookback_days: int = 14,
    insider_limit: int = 500,
) -> Dict[str, List[Dict[str, Any]]]:
    """Return insider trading activity that overlaps the provided trades.

    The function fetches a batch of the most recent corporate insider filings
    and filters for entries that share a ticker symbol with the congressional
    trades within the provided lookback window.
    """

    trades = list(trades)
    if not trades:
        return {}

    insider_trades = fetch_latest_insider_trades(limit=insider_limit)
    if not insider_trades:
        return {}

    # Build lookup for target symbols and most recent relevant dates
    target_symbols: Dict[str, datetime] = {}
    for trade in trades:
        symbol = (trade.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        try:
            disclosure_date = datetime.strptime(trade.get("disclosureDate"), "%Y-%m-%d")
        except Exception:
            disclosure_date = None
        try:
            transaction_date = datetime.strptime(trade.get("transactionDate"), "%Y-%m-%d")
        except Exception:
            transaction_date = None

        relevant_date = disclosure_date or transaction_date
        if relevant_date is None:
            continue

        # Track the most recent reference date per symbol
        if symbol not in target_symbols or relevant_date > target_symbols[symbol]:
            target_symbols[symbol] = relevant_date

    if not target_symbols:
        return {}

    cutoff_by_symbol: Dict[str, datetime] = {
        symbol: date - timedelta(days=lookback_days) for symbol, date in target_symbols.items()
    }

    related: MutableMapping[str, List[Dict[str, Any]]] = defaultdict(list)

    for insider_trade in insider_trades:
        symbol = (insider_trade.get("symbol") or "").strip().upper()
        if symbol not in target_symbols:
            continue

        raw_date = (
            insider_trade.get("transactionDate")
            or insider_trade.get("filingDate")
            or insider_trade.get("date")
        )
        try:
            trade_date = datetime.strptime(raw_date, "%Y-%m-%d") if raw_date else None
        except Exception:
            trade_date = None

        if trade_date is None:
            # Include undated filings as long as we have a symbol match; these are
            # rare but occasionally present in the API.
            related[symbol].append(insider_trade)
            continue

        if trade_date < cutoff_by_symbol[symbol]:
            continue

        related[symbol].append(insider_trade)

    return {symbol: entries for symbol, entries in related.items() if entries}
