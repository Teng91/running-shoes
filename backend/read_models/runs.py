"""User-scoped run lists, calendar summaries and import history, independent of transport."""

from calendar import monthrange

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend import models
from backend.read_models.run_statistics import month_bounds
from backend.run_metrics import pace_seconds_per_km


def month_run_summary(db: Session, user_id: int, year: int, month: int) -> dict:
    start, end = month_bounds(year, month)
    rows = (
        db.query(
            models.Run.date, models.Run.shoe_id, func.sum(models.Run.km), func.count(models.Run.id)
        )
        .filter(
            models.Run.user_id == user_id,
            models.Run.date >= start,
            models.Run.date <= end,
        )
        .group_by(models.Run.date, models.Run.shoe_id)
        .order_by(models.Run.date, models.Run.shoe_id)
        .all()
    )
    calendar: dict[str, dict] = {}
    shoes: dict[int, dict] = {}
    for day, shoe_id, km, count in rows:
        daily = calendar.setdefault(day, {"date": day, "km": 0.0, "count": 0, "shoes": []})
        daily["km"] = round(daily["km"] + km, 2)
        daily["count"] += count
        daily["shoes"].append({"shoe_id": shoe_id, "km": round(km, 2), "count": count})
        shoe = shoes.setdefault(shoe_id, {"shoe_id": shoe_id, "km": 0.0, "count": 0})
        shoe["km"] = round(shoe["km"] + km, 2)
        shoe["count"] += count
    timed_seconds, timed_km, timed_count = db.query(
        func.sum(models.Run.duration_seconds), func.sum(models.Run.km), func.count(models.Run.id)
    ).filter(
        models.Run.user_id == user_id,
        models.Run.date >= start,
        models.Run.date <= end,
        models.Run.duration_seconds.isnot(None),
    ).one()
    return {
        "year": year,
        "month": month,
        "total_km": round(sum(day["km"] for day in calendar.values()), 2),
        "run_count": sum(day["count"] for day in calendar.values()),
        "run_days": len(calendar),
        "calendar": list(calendar.values()),
        "shoe_usage": sorted(shoes.values(), key=lambda row: (-row["km"], row["shoe_id"])),
        # SPEC-060: time-weighted over the runs that have a moving time.
        "timed_run_count": int(timed_count or 0),
        "average_pace_seconds_per_km": pace_seconds_per_km(timed_seconds, timed_km),
    }


def year_run_summary(db: Session, user_id: int, year: int) -> dict:
    """Return a compact annual matrix without materializing individual runs."""
    month = func.substr(models.Run.date, 6, 2)
    rows = db.query(
        month, models.Run.shoe_id, func.sum(models.Run.km), func.count(models.Run.id)
    ).filter(
        models.Run.user_id == user_id,
        models.Run.date >= f"{year:04d}-01-01",
        models.Run.date <= f"{year:04d}-12-31",
    ).group_by(month, models.Run.shoe_id).order_by(month, models.Run.shoe_id).all()
    matrix: dict[int, list[float]] = {}
    totals = [0.0] * 12
    count = 0
    for number, shoe_id, km, run_count in rows:
        index = int(number) - 1
        matrix.setdefault(shoe_id, [0.0] * 12)[index] = round(km, 2)
        totals[index] += km
        count += run_count
    return {
        "year": year,
        "total_km": round(sum(totals), 2),
        "run_count": count,
        "monthly_km": [round(km, 2) for km in totals],
        "shoes": [{"shoe_id": shoe_id, "monthly_km": kms} for shoe_id, kms in matrix.items()],
    }


def list_runs(
    db: Session,
    user_id: int,
    *,
    year: int | None = None,
    month: int | None = None,
    day: int | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[models.Run]:
    """Newest-first runs for an optional year, month or day (callers validate the combination)."""
    query = db.query(models.Run).filter(models.Run.user_id == user_id)
    if year is not None:
        if month is None:
            start, end = f"{year:04d}-01-01", f"{year:04d}-12-31"
        else:
            start, end = month_bounds(year, month)
        query = query.filter(models.Run.date >= start, models.Run.date <= end)
        if month is not None and day is not None:
            query = query.filter(models.Run.date == f"{year:04d}-{month:02d}-{day:02d}")
    query = query.order_by(models.Run.date.desc(), models.Run.id.desc()).offset(offset)
    if limit is not None:
        query = query.limit(limit)
    return query.all()


def is_calendar_day(year: int, month: int, day: int) -> bool:
    return day <= monthrange(year, month)[1]


def recent_strava_imports(db: Session, user_id: int, limit: int = 10) -> list[models.StravaImport]:
    return (
        db.query(models.StravaImport)
        .filter(models.StravaImport.user_id == user_id)
        .order_by(models.StravaImport.imported_at.desc(), models.StravaImport.id.desc())
        .limit(limit)
        .all()
    )
