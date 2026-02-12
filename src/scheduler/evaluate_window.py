"""Window detection for scheduled publishing."""

from __future__ import annotations

from datetime import datetime, time
from typing import Optional
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
TOLERANCE_MINUTES = 8

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
    """Return window name if current time is within tolerance of any window, else None."""

    now_et = now_et.astimezone(ET)
    current_time = now_et.time()

    for window_name, target_time in WINDOWS.items():
        # Calculate minutes difference
        current_minutes = current_time.hour * 60 + current_time.minute
        target_minutes = target_time.hour * 60 + target_time.minute

        diff_minutes = abs(current_minutes - target_minutes)
        # Handle wrap-around (e.g., 23:59 vs 00:01)
        if diff_minutes > 720:  # More than 12 hours, wrap around
            diff_minutes = 1440 - diff_minutes

        if diff_minutes <= TOLERANCE_MINUTES:
            return window_name

    return None
