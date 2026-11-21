"""Shared presentation rounding for aggregate statistics."""

import math
from decimal import ROUND_HALF_UP, Decimal


def round_metric(value: float | None, digits: int = 2) -> float:
    """Round an aggregate (treating missing SQL sums as zero) to a stable precision.

    SPEC-093: halves round up, from the number as written (``repr``), the same rule the
    request schemas use for entered distances and prices. Python's ``round`` works on the
    binary value and rounds halves to even, so 2.675 became 2.67 while input gave 2.68.
    """
    number = float(value or 0)
    if not math.isfinite(number):
        return number
    return float(Decimal(repr(number)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP))
