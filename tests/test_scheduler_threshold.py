"""Tests for dynamic threshold computation."""

import pytest

from scheduler.dynamic_threshold import compute_threshold


def test_compute_threshold_multiple_bundles():
    """Test threshold with 2+ bundles."""
    assert compute_threshold(2) == 7
    assert compute_threshold(3) == 7
    assert compute_threshold(10) == 7


def test_compute_threshold_single_bundle():
    """Test threshold with 1 bundle."""
    assert compute_threshold(1) == 5


def test_compute_threshold_no_bundles():
    """Test threshold with 0 bundles (alerts disabled)."""
    assert compute_threshold(0) is None


def test_compute_threshold_edge_cases():
    """Test edge cases."""
    assert compute_threshold(-1) is None  # Negative should be treated as 0
    assert compute_threshold(100) == 7  # Large number
