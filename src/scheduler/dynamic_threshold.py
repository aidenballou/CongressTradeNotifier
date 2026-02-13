"""Dynamic threshold computation based on bundle count."""

from __future__ import annotations

from typing import Optional


def compute_threshold(bundles_today: int) -> Optional[int]:
    """
    Compute alert threshold based on number of bundles available today.
    
    Returns:
        - 7 if bundles_today >= 2 (more selective)
        - 5 if bundles_today == 1 (standard HIGH threshold)
        - None if bundles_today == 0 (alerts disabled)
    """
    if bundles_today >= 2:
        return 7
    elif bundles_today == 1:
        return 5
    else:
        return None
