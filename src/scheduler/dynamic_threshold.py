"""Dynamic threshold computation based on bundle count and optional engagement priors."""

from __future__ import annotations

from typing import Optional


def compute_threshold(bundles_today: int, window: Optional[str] = None) -> Optional[int]:
    """
    Compute alert threshold based on number of bundles available today.
    Stricter defaults so only higher-quality signals get ALERT treatment.
    Optionally nudge up when ALERT has underperformed in this window (engagement prior).
    
    Returns:
        - 8 if bundles_today >= 2 (more selective)
        - 6 if bundles_today == 1 (standard HIGH threshold)
        - None if bundles_today == 0 (alerts disabled)
        - +1 if window provided and engagement prior for ALERT in this window is low
    """
    base = None
    if bundles_today >= 2:
        base = 8
    elif bundles_today == 1:
        base = 6
    else:
        return None

    if base is None or window is None:
        return base

    try:
        from analytics.engagement import get_engagement_priors_for_scheduler
    except ImportError:
        from src.analytics.engagement import get_engagement_priors_for_scheduler
    prior = get_engagement_priors_for_scheduler("ALERT", window, min_samples=2)
    if prior < 0.4:
        return base + 1
    return base
