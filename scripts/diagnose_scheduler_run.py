#!/usr/bin/env python3
"""Lightweight scheduler diagnosis helper.

Usage:
  python scripts/diagnose_scheduler_run.py --timestamp 2026-02-13T21:58:00Z
  python scripts/diagnose_scheduler_run.py --timestamp 2026-02-13T21:58:00Z --trades-json /tmp/trades.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from scheduler.evaluate_window import get_current_window, is_trading_day


def _parse_timestamp(value: str) -> datetime:
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ET)
    return dt.astimezone(ET)


def _load_trades(path: str | None) -> list[dict[str, Any]]:
    if not path:
        return []
    payload = json.loads(Path(path).read_text())
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    raise ValueError("trades-json must be a JSON list of trade objects")


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose scheduler window decisions for a timestamp.")
    parser.add_argument("--timestamp", required=True, help="ISO timestamp, e.g. 2026-02-13T21:58:00Z")
    parser.add_argument("--trades-json", help="Optional JSON file of trades for same-day disclosure count")
    args = parser.parse_args()

    now_et = _parse_timestamp(args.timestamp)
    now_utc = now_et.astimezone(timezone.utc)
    trades = _load_trades(args.trades_json)

    today = now_et.strftime("%Y-%m-%d")
    same_day = [t for t in trades if str(t.get("disclosureDate", "")) == today]
    window = get_current_window(now_et)
    trading_day = is_trading_day(now_et)

    if window is None:
        reason = "not_in_window"
    elif not trading_day:
        reason = "not_trading_day"
    else:
        reason = "window_eligible"

    print(f"timestamp_et={now_et.isoformat(timespec='seconds')}")
    print(f"timestamp_utc={now_utc.isoformat(timespec='seconds')}")
    print(f"window={window}")
    print(f"trading_day={trading_day}")
    print(f"same_day_disclosures={len(same_day)}")
    print(f"expected_reason={reason}")


if __name__ == "__main__":
    main()
