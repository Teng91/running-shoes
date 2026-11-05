"""One retirement forecast policy for shoe lists, charts, and analytics."""

from collections.abc import Sequence
from datetime import date, timedelta
from typing import Literal, TypedDict

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend import models
from backend.clock import local_today


class ShoeForecast(TypedDict):
    forecast_retirement_date: str | None
    forecast_source: Literal["recent_90_days", "planned_monthly_km"]
    forecast_monthly_km: float
    actual_monthly_km_90_days: float
    remaining_mileage_km: float


def retirement_forecast(shoe: models.Shoe, km_90: float, as_of: date) -> ShoeForecast:
    actual_rate = round(km_90 / 90 * 30.4375, 2) if km_90 > 0 else 0.0
    remaining = round(max(0, shoe.expected_mileage - shoe.mileage), 2)
    rate = actual_rate or round(shoe.monthly_km, 2)
    forecast_date = None
    if remaining > 0 and rate > 0:
        try:
            forecast_date = (as_of + timedelta(days=round(remaining / rate * 30.4375))).isoformat()
        except (OverflowError, ValueError):
            # Legacy data may exceed current API bounds. Keep the list readable.
            pass
    return {
        "forecast_retirement_date": forecast_date,
        "forecast_source": "recent_90_days" if actual_rate > 0 else "planned_monthly_km",
        "forecast_monthly_km": rate,
        "actual_monthly_km_90_days": actual_rate,
        "remaining_mileage_km": remaining,
    }


def forecasts_for_shoes(
    db: Session, user_id: int, shoes: Sequence[models.Shoe], *, today: date | None = None
) -> dict[int, ShoeForecast]:
    """Batch recent mileage in one scoped query, never one query per shoe."""
    rows = [shoe for shoe in shoes if shoe.user_id == user_id and not shoe.is_deleted]
    if not rows:
        return {}
    as_of = today or local_today()
    totals = {shoe_id: value for shoe_id, value in db.query(models.Run.shoe_id, func.sum(models.Run.km)).filter(
        models.Run.user_id == user_id,
        models.Run.shoe_id.in_([shoe.id for shoe in rows]),
        models.Run.date >= (as_of - timedelta(days=89)).isoformat(),
        models.Run.date <= as_of.isoformat(),
    ).group_by(models.Run.shoe_id).all()}
    return {
        shoe.id: retirement_forecast(shoe, round(float(totals.get(shoe.id) or 0), 2), as_of)
        for shoe in rows
    }
