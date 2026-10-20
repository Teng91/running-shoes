"""Canonical shoe cost and lifecycle arithmetic (no HTTP or AI concerns)."""

from backend.models import Shoe


def shoe_metrics(shoe: Shoe) -> dict[str, float | None]:
    return {
        "discount_percent": round(shoe.price / shoe.orig_price * 100, 2)
        if shoe.orig_price > 0
        else None,
        "cost_per_km": round(shoe.price / shoe.mileage, 2) if shoe.mileage > 0 else None,
        "expected_cost_per_km": round(shoe.price / shoe.expected_mileage, 2)
        if shoe.expected_mileage > 0
        else None,
        "usage_percent": round(shoe.mileage / shoe.expected_mileage * 100, 2)
        if shoe.expected_mileage > 0
        else None,
        "remaining_mileage_km": round(max(0, shoe.expected_mileage - shoe.mileage), 2),
    }
