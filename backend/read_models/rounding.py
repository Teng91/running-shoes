"""Shared presentation rounding for aggregate statistics."""


def round_metric(value: float | None, digits: int = 2) -> float:
    """Round an aggregate (treating missing SQL sums as zero) to a stable precision."""
    return round(float(value or 0), digits)
