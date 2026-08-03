"""Tests for scheduler window evaluation."""

from datetime import datetime
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


def test_get_current_window_catches_up_delayed_runs():
    """Observed delayed GitHub runs must still process the latest due window."""
    assert get_current_window(datetime(2024, 1, 1, 11, 13, tzinfo=ET)) == "MORNING"
    assert get_current_window(datetime(2024, 1, 1, 13, 19, tzinfo=ET)) == "MIDDAY"
    assert get_current_window(datetime(2024, 1, 1, 16, 38, tzinfo=ET)) == "POWER_HOUR"
    assert get_current_window(datetime(2024, 1, 1, 20, 45, tzinfo=ET)) == "EVENING"


def test_get_current_window_does_not_run_before_first_target():
    assert get_current_window(datetime(2024, 1, 1, 8, 34, tzinfo=ET)) is None


def test_get_current_window_advances_only_after_next_target():
    assert get_current_window(datetime(2024, 1, 1, 12, 9, tzinfo=ET)) == "MORNING"
    assert get_current_window(datetime(2024, 1, 1, 12, 10, tzinfo=ET)) == "MIDDAY"
