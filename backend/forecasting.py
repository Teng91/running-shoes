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
    forecast_source: Literal["recent_90_days", "no_runs", "idle_90_days", "retired"]
    forecast_monthly_km: float
    actual_monthly_km_90_days: float
    remaining_mileage_km: float


RATE_WINDOW_DAYS = 90
# SPEC-142: a pair first worn days ago is measured over at least two weeks, so one long
# run on its first day does not read as a month of that every day.
MIN_RATE_DAYS = 14


def rate_window_days(first_run: str | None, as_of: date) -> int:
    """Days of the 90-day window the pair has been in use: from its first run, 14 to 90."""
    if not first_run:
        return RATE_WINDOW_DAYS
    try:
        first = date.fromisoformat(first_run)
    except ValueError:
        return RATE_WINDOW_DAYS
    return min(RATE_WINDOW_DAYS, max(MIN_RATE_DAYS, (as_of - first).days + 1))


def retirement_forecast(
    shoe: models.Shoe, km_90: float, as_of: date, *, has_runs: bool = False, first_run: str | None = None
) -> ShoeForecast:
    """Retirement date from the last 90 days of use, the only rate there is.

    A pair that has logged runs but none in 90 days (a race or hiking shoe worn now and
    then) gets no date (SPEC-069); neither does a pair never logged, which used to fall
    back to a planned monthly km the form no longer asks for (SPEC-138). A pair first
    worn inside the window is averaged over the days since that first run (SPEC-142).
    """
    days = rate_window_days(first_run, as_of)
    actual_rate = round(km_90 / days * 30.4375, 2) if km_90 > 0 else 0.0
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
    if not actual_rate:
        return {
            "forecast_retirement_date": None,
            "forecast_source": "idle_90_days" if has_runs else "no_runs",
            "forecast_monthly_km": 0.0,
            "actual_monthly_km_90_days": 0.0,
            "remaining_mileage_km": remaining,
        }
    rate = actual_rate
    forecast_date = None
    if remaining > 0 and rate > 0:
        try:
            forecast_date = (as_of + timedelta(days=round(remaining / rate * 30.4375))).isoformat()
        except (OverflowError, ValueError):
            # Legacy data may exceed current API bounds. Keep the list readable.
            pass
    return {
        "forecast_retirement_date": forecast_date,
        "forecast_source": "recent_90_days",
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
    totals = {shoe_id: (km, count, first) for shoe_id, km, count, first in db.query(
        models.Run.shoe_id, recent, func.count(models.Run.id), func.min(models.Run.date)
    ).filter(
        models.Run.user_id == user_id,
        models.Run.shoe_id.in_([shoe.id for shoe in rows]),
        models.Run.date <= as_of.isoformat(),
    ).group_by(models.Run.shoe_id).all()}
    forecasts = {}
    for shoe in rows:
        km_90, count, first = totals.get(shoe.id, (0, 0, None))
        forecasts[shoe.id] = retirement_forecast(
            shoe, round(float(km_90 or 0), 2), as_of, has_runs=bool(count), first_run=first
        )
    return forecasts
