"""Helpers for working with trade amount strings."""


def parse_amount(amount_str: str | float | int | None) -> float:
    """Parse amount ranges like "$1,001 - $15,000" and return an average as float."""

    if amount_str is None:
        return 0.0
    if isinstance(amount_str, (int, float)):
        return float(amount_str)
    if not amount_str:
        return 0.0

    cleaned = str(amount_str).replace("$", "").replace(",", "")
    parts = cleaned.split(" - ")

    if len(parts) == 2:
        try:
            min_val = float(parts[0].strip())
            max_val = float(parts[1].strip())
        except ValueError:
            return 0.0
        return (min_val + max_val) / 2

    if len(parts) == 1:
        try:
            return float(parts[0].strip())
        except ValueError:
            return 0.0

    return 0.0


__all__ = ["parse_amount"]
