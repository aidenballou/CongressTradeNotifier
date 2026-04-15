"""Tests for scheduler window evaluation."""

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from scheduler.evaluate_window import get_current_window, is_trading_day, WINDOWS

ET = ZoneInfo("America/New_York")


def test_is_trading_day():
    """Test trading day detection."""
    # Monday
    monday = datetime(2024, 1, 1, 10, 0, tzinfo=ET)  # Jan 1, 2024 is a Monday
    assert is_trading_day(monday) is True

    # Saturday
    saturday = datetime(2024, 1, 6, 10, 0, tzinfo=ET)  # Jan 6, 2024 is a Saturday
    assert is_trading_day(saturday) is False

    # Sunday
    sunday = datetime(2024, 1, 7, 10, 0, tzinfo=ET)  # Jan 7, 2024 is a Sunday
    assert is_trading_day(sunday) is False


def test_get_current_window_exact_times():
    """Test window detection at exact window times."""
    # Morning window
    morning = datetime(2024, 1, 1, 8, 35, 0, tzinfo=ET)
    assert get_current_window(morning) == "MORNING"

    # Midday window
    midday = datetime(2024, 1, 1, 12, 10, 0, tzinfo=ET)
    assert get_current_window(midday) == "MIDDAY"

    # Power hour window
    power_hour = datetime(2024, 1, 1, 15, 50, 0, tzinfo=ET)
    assert get_current_window(power_hour) == "POWER_HOUR"

    # Evening window
    evening = datetime(2024, 1, 1, 19, 30, 0, tzinfo=ET)
    assert get_current_window(evening) == "EVENING"


def test_get_current_window_within_tolerance():
    """Test window detection within tolerance (14 min)."""
    morning_plus = datetime(2024, 1, 1, 8, 40, 0, tzinfo=ET)
    assert get_current_window(morning_plus) == "MORNING"

    morning_minus = datetime(2024, 1, 1, 8, 22, 0, tzinfo=ET)
    assert get_current_window(morning_minus) == "MORNING"

    midday_plus = datetime(2024, 1, 1, 12, 24, 0, tzinfo=ET)
    assert get_current_window(midday_plus) == "MIDDAY"

    morning_edge = datetime(2024, 1, 1, 8, 49, 0, tzinfo=ET)
    assert get_current_window(morning_edge) == "MORNING"


def test_get_current_window_outside_tolerance():
    """Test window detection outside tolerance (14 min)."""
    too_late = datetime(2024, 1, 1, 8, 50, 0, tzinfo=ET)
    assert get_current_window(too_late) is None

    between = datetime(2024, 1, 1, 10, 0, 0, tzinfo=ET)
    assert get_current_window(between) is None


def test_get_current_window_none():
    """Test that times far from windows return None."""
    # Random time
    random_time = datetime(2024, 1, 1, 14, 30, 0, tzinfo=ET)
    assert get_current_window(random_time) is None
