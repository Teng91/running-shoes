"""User-scoped highlights: next-shoe suggestion, year review and distance mix."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend import models
from backend.read_models import goal_progress
from backend.read_models.rounding import round_metric
from backend.read_models.trends import run_streaks, trends_end
from backend.shoe_metrics import REPLACE_SOON_USAGE_PERCENT, shoe_metrics

NEAR_END_PERCENT = REPLACE_SOON_USAGE_PERCENT
# Distance buckets (km) in 5 km steps; 20 km and longer share the last bucket.
DISTANCE_BUCKETS = ((0.0, 5.0, "<5"), (5.0, 10.0, "5–10"), (10.0, 15.0, "10–15"),
                    (15.0, 20.0, "15–20"), (20.0, None, "≥20"))


def _active_shoes(db: Session, user_id: int) -> list[models.Shoe]:
    return (
        db.query(models.Shoe)
        .filter(models.Shoe.user_id == user_id, models.Shoe.is_deleted.is_(False),
                models.Shoe.is_retired.is_(False))
        .order_by(models.Shoe.id)
        .all()
    )


def _km_between(db: Session, user_id: int, start: date, end: date) -> tuple[float, int]:
    km, count = (
        db.query(func.coalesce(func.sum(models.Run.km), 0.0), func.count(models.Run.id))
        .filter(models.Run.user_id == user_id, models.Run.date >= start.isoformat(),
                models.Run.date <= end.isoformat())
        .one()
    )
    return float(km or 0), int(count)


def shoe_suggestion(db: Session, user_id: int, as_of: date) -> list[dict]:
    """Rank active shoes to wear next: longest rested first, worn-out pairs last."""
    shoes = _active_shoes(db, user_id)
    last_runs = dict(
        db.query(models.Run.shoe_id, func.max(models.Run.date))
        .filter(models.Run.user_id == user_id, models.Run.date <= as_of.isoformat())
        .group_by(models.Run.shoe_id)
        .all()
    )
    candidates: list[tuple[tuple[bool, int, float, int], dict]] = []
    for shoe in shoes:
        metrics = shoe_metrics(shoe)
        last = last_runs.get(shoe.id)
        rest = max(0, (as_of - date.fromisoformat(last)).days) if last else None
        usage = float(metrics["usage_percent"] or 0)
        remaining = float(metrics["remaining_mileage_km"] or 0)
        near_end = usage >= NEAR_END_PERCENT
        # Never-worn pairs count as fully rested; worn-out pairs are only suggested last.
        key = (near_end, -(rest if rest is not None else 10**6), -remaining, shoe.id)
        candidates.append((key, {
            "shoe_id": shoe.id,
            "days_since_last_run": rest,
            "remaining_km": remaining,
            "usage_percent": usage,
            "near_end": near_end,
        }))
    candidates.sort(key=lambda item: item[0])
    return [row for _, row in candidates[:3]]


def home_summary(db: Session, user_id: int, as_of: date) -> dict:
    """Run-log data: which active shoe to wear next."""
    return {"as_of": as_of.isoformat(), "suggestion": shoe_suggestion(db, user_id, as_of)}


def year_review(db: Session, user_id: int, year: int, as_of: date) -> dict:
    """Calendar-year summary from the run log; a future year has no data."""
    end = trends_end(year, as_of)
    goal = goal_progress.goal_values(db, user_id)
    base = {"year": year, "end_date": end.isoformat() if end else None, "complete": end == date(year, 12, 31)}
    start = date(year, 1, 1)
    if end is None:
        return {**base, "has_runs": False}
    runs = (
        db.query(models.Run.date, models.Run.km, models.Run.shoe_id)
        .filter(models.Run.user_id == user_id, models.Run.date >= start.isoformat(),
                models.Run.date <= end.isoformat())
        .all()
    )
    if not runs:
        return {**base, "has_runs": False}
    total = sum(float(km) for _, km, _ in runs)
    days = sorted({date.fromisoformat(day) for day, km, _ in runs if km > 0})
    by_shoe: dict[int, list[float]] = {}
    for _, km, shoe_id in runs:
        by_shoe.setdefault(shoe_id, []).append(float(km))
    top_id, top_km = max(((sid, sum(kms)) for sid, kms in by_shoe.items()), key=lambda item: (item[1], -item[0]))
    records = _records_in(runs)
    bought = (
        db.query(func.count(models.Shoe.id), func.coalesce(func.sum(models.Shoe.price), 0.0))
        .filter(models.Shoe.user_id == user_id, models.Shoe.is_deleted.is_(False),
                models.Shoe.date >= start.isoformat(), models.Shoe.date <= date(year, 12, 31).isoformat())
        .one()
    )
    # Compare the same calendar span: a year still in progress is measured
    # against the previous year through the same day, never its full total.
    previous_end = _same_day_previous_year(end)
    previous_km, _ = _km_between(db, user_id, date(year - 1, 1, 1), previous_end)
    elapsed = (end - start).days + 1
    goal_active = year >= goal["start_year"]
    return {
        **base,
        "has_runs": True,
        "total_km": round_metric(total),
        "run_count": len(runs),
        "run_days": len(days),
        "active_day_percent": round_metric(len(days) / elapsed * 100, 1),
        "average_km": round_metric(total / len(runs)),
        "longest_streak_days": run_streaks(days, end)["longest_days"],
        **records,
        "top_shoe": {"shoe_id": top_id, "km": round_metric(top_km), "runs": len(by_shoe[top_id])},
        "shoes_bought": int(bought[0]),
        "shoe_spend": round_metric(bought[1]),
        "cost_per_km": round_metric(float(bought[1]) / total) if total > 0 else None,
        "previous_year_km": round_metric(previous_km) if previous_km > 0 else None,
        "previous_year_end": previous_end.isoformat(),
        "goal": {
            "active": goal_active,
            "yearly_km": goal["yearly_km"],
            "percent": round_metric(total / goal["yearly_km"] * 100, 1) if goal_active and goal["yearly_km"] > 0 else None,
        },
    }


def _same_day_previous_year(day: date) -> date:
    """The same month/day one year earlier; 29 February maps to 28 February."""
    return day.replace(year=day.year - 1, day=min(day.day, 28 if day.month == 2 else day.day))


def _records_in(runs: list) -> dict:
    longest = min(runs, key=lambda row: (-float(row[1]), row[0]))
    weeks: dict[date, float] = {}
    months: dict[int, float] = {}
    for day_text, km, _ in runs:
        day = date.fromisoformat(day_text)
        monday = day - timedelta(days=day.weekday())
        weeks[monday] = weeks.get(monday, 0.0) + float(km)
        months[day.month] = months.get(day.month, 0.0) + float(km)
    week = max(weeks.items(), key=lambda item: (item[1], -item[0].toordinal()))
    month = max(months.items(), key=lambda item: (item[1], -item[0]))
    return {
        "longest_run": {"date": longest[0], "km": round_metric(longest[1]), "shoe_id": longest[2]},
        "biggest_week": {"week_start": week[0].isoformat(), "km": round_metric(week[1])},
        "biggest_month": {"month": month[0], "km": round_metric(month[1])},
    }


def shoe_distance_mix(db: Session, user_id: int) -> dict:
    """Run counts per distance bucket for each active shoe with logged runs."""
    rows = (
        db.query(models.Run.shoe_id, models.Run.km)
        .join(models.Shoe, (models.Shoe.id == models.Run.shoe_id) & (models.Shoe.user_id == user_id))
        .filter(models.Run.user_id == user_id, models.Shoe.is_deleted.is_(False),
                models.Shoe.is_retired.is_(False))
        .all()
    )
    shoes: dict[int, dict] = {}
    for shoe_id, km in rows:
        entry = shoes.setdefault(shoe_id, {"shoe_id": shoe_id, "counts": [0] * len(DISTANCE_BUCKETS),
                                           "runs": 0, "km": 0.0, "longest_km": 0.0})
        value = float(km)
        index = next(i for i, (low, high, _) in enumerate(DISTANCE_BUCKETS)
                     if value >= low and (high is None or value < high))
        entry["counts"][index] += 1
        entry["runs"] += 1
        entry["km"] += value
        entry["longest_km"] = max(entry["longest_km"], value)
    result = []
    for entry in sorted(shoes.values(), key=lambda item: (-item["km"], item["shoe_id"])):
        result.append({**entry, "km": round_metric(entry["km"]), "longest_km": round_metric(entry["longest_km"]),
                       "average_km": round_metric(entry["km"] / entry["runs"])})
    return {"buckets": [label for _, _, label in DISTANCE_BUCKETS], "shoes": result}
