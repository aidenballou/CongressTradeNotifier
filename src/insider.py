"""Helpers for enriching congressional trades with corporate insider activity."""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional

import requests
from dotenv import load_dotenv

# Ensure environment variables are loaded for local runs
load_dotenv()

API_KEY = os.getenv("FMP_API_KEY")
BASE_URL = "https://financialmodelingprep.com"
PLAN_MAX_INSIDER_LIMIT = int(os.getenv("FMP_INSIDER_LIMIT_MAX", "100"))

# Transaction-type codes (Form 4). Only P-Purchase is treated as an open-market buy.
OPEN_MARKET_BUY_CODES = {"P-Purchase", "P"}
OPEN_MARKET_SELL_CODES = {"S-Sale", "S"}
# C-suite / top-officer keywords for title matching against typeOfOwner
CSUITE_KEYWORDS = (
    "chief executive",
    "chief financial",
    "chief operating",
    "president",
    "chairman",
    "chief investment",
    "chief medical",
    "chief technology",
)


def fetch_latest_insider_trades(limit: int = 100) -> List[Dict[str, Any]]:
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

    capped_limit = max(1, min(int(limit), PLAN_MAX_INSIDER_LIMIT))
    url = f"{BASE_URL}/stable/insider-trading/latest?page=0&limit={capped_limit}&apikey={API_KEY}"
    try:
        response = requests.get(url, timeout=15)
    except Exception as exc:  # pragma: no cover - defensive logging only
        print(f"[Insider] Request failed: {exc}")
        return []

    if response.status_code != 200:
        # Gracefully recover for common plan-limit mismatch errors.
        if response.status_code == 402 and capped_limit != PLAN_MAX_INSIDER_LIMIT:
            fallback_url = (
                f"{BASE_URL}/stable/insider-trading/latest"
                f"?page=0&limit={PLAN_MAX_INSIDER_LIMIT}&apikey={API_KEY}"
            )
            try:
                fallback = requests.get(fallback_url, timeout=15)
                if fallback.status_code == 200:
                    payload = fallback.json()
                    if isinstance(payload, list):
                        print(f"[Insider] Retried with limit={PLAN_MAX_INSIDER_LIMIT} after plan-limit response")
                        return payload
            except Exception:
                pass
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


def _parse_insider_date(raw: Any) -> Optional[datetime]:
    """Parse FMP insider dates that arrive as either YYYY-MM-DD or YYYY-MM-DD HH:MM:SS."""

    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def normalize_insider_trade(raw: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a canonical view of an FMP insider-trading record.

    FMP field names vary across plans and sometimes drift (e.g. ``acquistionOrDisposition``
    is misspelled by the API). This helper collapses those shapes into a stable form so
    downstream consumers do not have to care about the API's quirks.
    """

    symbol = str(raw.get("symbol") or "").strip().upper()
    name = str(
        raw.get("reportingName")
        or raw.get("insiderName")
        or raw.get("owner")
        or ""
    ).strip()
    title = str(
        raw.get("typeOfOwner")
        or raw.get("insiderTitle")
        or raw.get("position")
        or ""
    ).strip()
    transaction_code = str(raw.get("transactionType") or raw.get("type") or "").strip()
    acquisition = str(
        raw.get("acquistionOrDisposition")  # FMP's misspelling
        or raw.get("acquisitionOrDisposition")
        or ""
    ).strip().upper()

    try:
        shares = float(raw.get("securitiesTransacted") or raw.get("shares") or 0) or 0.0
    except (TypeError, ValueError):
        shares = 0.0
    try:
        price = float(raw.get("price") or raw.get("sharePrice") or 0) or 0.0
    except (TypeError, ValueError):
        price = 0.0

    transaction_date = _parse_insider_date(raw.get("transactionDate"))
    filing_date = _parse_insider_date(raw.get("filingDate") or raw.get("date"))

    title_lower = title.lower()
    is_open_market_buy = transaction_code in OPEN_MARKET_BUY_CODES and acquisition in {"", "A"}
    is_csuite = any(keyword in title_lower for keyword in CSUITE_KEYWORDS)
    is_director = "director" in title_lower
    is_ten_percent = "10 percent owner" in title_lower or "10% owner" in title_lower

    return {
        "symbol": symbol,
        "insider_name": name,
        "title": title,
        "title_lower": title_lower,
        "transaction_code": transaction_code,
        "acquisition_disposition": acquisition,
        "shares": shares,
        "price": price,
        "value": shares * price,
        "transaction_date": transaction_date,
        "filing_date": filing_date,
        "is_open_market_buy": is_open_market_buy,
        "is_csuite": is_csuite,
        "is_director": is_director,
        "is_ten_percent_owner": is_ten_percent,
        "url": str(raw.get("url") or raw.get("link") or "").strip(),
        "raw": dict(raw),
    }


def fetch_insider_trades_window(
    *,
    days: int = 7,
    max_pages: int = 5,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Fetch recent insider filings and return normalized open-market *buy* records.

    The FMP ``/stable/insider-trading/latest`` endpoint is paginated in pages of up to
    ``PLAN_MAX_INSIDER_LIMIT`` records, newest first. We walk pages until we see a
    transaction date older than ``now - days`` or we hit ``max_pages``.
    """

    if not API_KEY:
        print("[Insider] Skipping fetch_insider_trades_window: FMP_API_KEY is not set")
        return []

    now = now or datetime.utcnow()
    cutoff = now - timedelta(days=max(1, int(days)))

    per_page = PLAN_MAX_INSIDER_LIMIT
    out: List[Dict[str, Any]] = []
    for page in range(max(1, int(max_pages))):
        url = (
            f"{BASE_URL}/stable/insider-trading/latest"
            f"?page={page}&limit={per_page}&apikey={API_KEY}"
        )
        try:
            resp = requests.get(url, timeout=15)
        except Exception as exc:  # pragma: no cover - defensive logging only
            print(f"[Insider] Window fetch request failed (page={page}): {exc}")
            break

        if resp.status_code != 200:
            print(
                f"[Insider] Window fetch status={resp.status_code} body={resp.text[:160]} (page={page})"
            )
            break

        try:
            payload = resp.json()
        except ValueError:
            print(f"[Insider] Window fetch JSON decode failed (page={page})")
            break

        if not isinstance(payload, list) or not payload:
            break

        oldest_on_page: Optional[datetime] = None
        for raw in payload:
            normalized = normalize_insider_trade(raw)
            tx_date = normalized["transaction_date"] or normalized["filing_date"]
            if tx_date is None:
                continue
            if oldest_on_page is None or tx_date < oldest_on_page:
                oldest_on_page = tx_date
            if tx_date < cutoff:
                continue
            if not normalized["is_open_market_buy"]:
                continue
            if normalized["value"] <= 0:
                continue
            out.append(normalized)

        # Stop once the page's oldest record predates our window — older pages can't help.
        if oldest_on_page is not None and oldest_on_page < cutoff:
            break

    return out


def find_recent_insider_activity(
    trades: Iterable[Mapping[str, Any]],
    *,
    lookback_days: int = 14,
    insider_limit: int = 100,
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
