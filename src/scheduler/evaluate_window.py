"""Window detection for scheduled publishing."""

from __future__ import annotations

from datetime import datetime, time
from typing import Optional
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
WINDOWS = {
    "MORNING": time(8, 35),
    "MIDDAY": time(12, 10),
    "POWER_HOUR": time(15, 50),
    "EVENING": time(19, 30),
}


def is_trading_day(now_et: datetime) -> bool:
    """Check if current date is a weekday (Monday-Friday)."""
    weekday = now_et.weekday()
    return weekday < 5  # 0=Monday, 4=Friday


def get_current_window(now_et: datetime) -> Optional[str]:
    """Return the latest posting window due today.

    GitHub schedules are best-effort and can run hours late. A due window remains
    eligible until the next target arrives; per-window database guards prevent a
    delayed run from posting the same window twice.
    """

    now_et = now_et.astimezone(ET)
    current_time = now_et.time()

    due = [name for name, target in WINDOWS.items() if current_time >= target]
    return due[-1] if due else None
