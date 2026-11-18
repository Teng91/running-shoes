"""One retirement forecast policy for shoe lists, charts, and analytics."""

from collections.abc import Sequence
from datetime import date, timedelta
from typing import Literal, TypedDict

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from backend import models
from backend.clock import local_today


class ShoeForecast(TypedDict):
    forecast_retirement_date: str | None
    forecast_source: Literal["recent_90_days", "planned_monthly_km", "idle_90_days", "retired"]
    forecast_monthly_km: float
    actual_monthly_km_90_days: float
    remaining_mileage_km: float


def retirement_forecast(shoe: models.Shoe, km_90: float, as_of: date, *, has_runs: bool = False) -> ShoeForecast:
    """Recent 90-day use, else the planned monthly km for a pair never logged.

    A pair that has logged runs but none in 90 days (a race or hiking shoe worn now and
    then) has no usable rate: falling back to the planned monthly km would invent a
    date, so it gets none (SPEC-069).
    """
    actual_rate = round(km_90 / 90 * 30.4375, 2) if km_90 > 0 else 0.0
    remaining = round(max(0, shoe.expected_mileage - shoe.mileage), 2)
    if shoe.is_retired:
        # A retired pair has no future retirement date, whatever lifespan remains.
        return {
            "forecast_retirement_date": None,
            "forecast_source": "retired",
            "forecast_monthly_km": actual_rate,
            "actual_monthly_km_90_days": actual_rate,
            "remaining_mileage_km": remaining,
        }
    if not actual_rate and has_runs:
        return {
            "forecast_retirement_date": None,
            "forecast_source": "idle_90_days",
            "forecast_monthly_km": 0.0,
            "actual_monthly_km_90_days": 0.0,
            "remaining_mileage_km": remaining,
        }
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


ShoeResponseField = Literal[
    "forecast_retirement_date", "forecast_source", "forecast_monthly_km", "actual_monthly_km_90_days"
]
SHOE_RESPONSE_FIELDS: tuple[ShoeResponseField, ...] = (
    "forecast_retirement_date",
    "forecast_source",
    "forecast_monthly_km",
    "actual_monthly_km_90_days",
)


def shoe_response_fields(forecast: ShoeForecast) -> dict[str, object]:
    """Forecast values copied onto shoe list and mutation responses."""
    return {key: forecast[key] for key in SHOE_RESPONSE_FIELDS}


def forecasts_for_shoes(
    db: Session, user_id: int, shoes: Sequence[models.Shoe], *, today: date | None = None
) -> dict[int, ShoeForecast]:
    """Batch recent mileage in one scoped query, never one query per shoe."""
    rows = [shoe for shoe in shoes if shoe.user_id == user_id and not shoe.is_deleted]
    if not rows:
        return {}
    as_of = today or local_today()
    start = (as_of - timedelta(days=89)).isoformat()
    recent = func.sum(case((models.Run.date >= start, models.Run.km), else_=0))
    totals = {shoe_id: (km, count) for shoe_id, km, count in db.query(
        models.Run.shoe_id, recent, func.count(models.Run.id)
    ).filter(
        models.Run.user_id == user_id,
        models.Run.shoe_id.in_([shoe.id for shoe in rows]),
        models.Run.date <= as_of.isoformat(),
    ).group_by(models.Run.shoe_id).all()}
    forecasts = {}
    for shoe in rows:
        km_90, count = totals.get(shoe.id, (0, 0))
        forecasts[shoe.id] = retirement_forecast(shoe, round(float(km_90 or 0), 2), as_of, has_runs=bool(count))
    return forecasts
