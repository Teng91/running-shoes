"""User-scoped highlights: run-log summary, shoe suggestion, milestones, year review and distance mix."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend import goals, models
from backend.read_models.rounding import round_metric
from backend.read_models.trends import run_streaks, trends_end
from backend.shoe_metrics import shoe_metrics

# Cumulative distance milestones; after the list, every 1000 km is a milestone.
TOTAL_MILESTONES_KM = (100, 250, 500, 1000)
SHOE_MILESTONES_KM = (100, 300, 500, 800)
RECENT_DAYS = 30
NEAR_END_PERCENT = 90.0
# Distance buckets (km): short, medium, long, half-marathon training and beyond.
DISTANCE_BUCKETS = ((0.0, 5.0, "<5"), (5.0, 10.0, "5–10"), (10.0, 15.0, "10–15"),
                    (15.0, 21.1, "15–21"), (21.1, None, "≥21"))


def _active_shoes(db: Session, user_id: int) -> list[models.Shoe]:
    return (
        db.query(models.Shoe)
        .filter(models.Shoe.user_id == user_id, models.Shoe.is_deleted.is_(False),
                models.Shoe.is_retired.is_(False))
        .order_by(models.Shoe.id)
        .all()
    )


def _run_days(db: Session, user_id: int, end: date) -> list[date]:
    rows = (
        db.query(models.Run.date)
        .filter(models.Run.user_id == user_id, models.Run.date <= end.isoformat(), models.Run.km > 0)
        .distinct()
        .all()
    )
    return sorted(date.fromisoformat(day) for (day,) in rows)


def _km_between(db: Session, user_id: int, start: date, end: date) -> tuple[float, int]:
    km, count = (
        db.query(func.coalesce(func.sum(models.Run.km), 0.0), func.count(models.Run.id))
        .filter(models.Run.user_id == user_id, models.Run.date >= start.isoformat(),
                models.Run.date <= end.isoformat())
        .one()
    )
    return float(km or 0), int(count)


def next_total_milestone(total_km: float) -> tuple[float | None, float]:
    """Return (last reached milestone, next milestone) for a cumulative distance."""
    reached = None
    for mark in TOTAL_MILESTONES_KM:
        if total_km >= mark:
            reached = float(mark)
        else:
            return reached, float(mark)
    thousands = int(total_km // 1000) * 1000
    return float(thousands), float(thousands + 1000)


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


def _records(db: Session, user_id: int, end: date) -> dict:
    longest = (
        db.query(models.Run.date, models.Run.km, models.Run.shoe_id)
        .filter(models.Run.user_id == user_id, models.Run.date <= end.isoformat())
        .order_by(models.Run.km.desc(), models.Run.date)
        .first()
    )
    daily = (
        db.query(models.Run.date, func.sum(models.Run.km))
        .filter(models.Run.user_id == user_id, models.Run.date <= end.isoformat())
        .group_by(models.Run.date)
        .all()
    )
    weeks: dict[date, float] = {}
    months: dict[tuple[int, int], float] = {}
    for day_text, km in daily:
        day = date.fromisoformat(day_text)
        monday = day - timedelta(days=day.weekday())
        weeks[monday] = weeks.get(monday, 0.0) + float(km or 0)
        months[(day.year, day.month)] = months.get((day.year, day.month), 0.0) + float(km or 0)
    week = max(weeks.items(), key=lambda item: (item[1], -item[0].toordinal()), default=None)
    month = max(months.items(), key=lambda item: (item[1], -item[0][0], -item[0][1]), default=None)
    return {
        "longest_run": {"date": longest[0], "km": round_metric(longest[1]), "shoe_id": longest[2]} if longest else None,
        "biggest_week": {"week_start": week[0].isoformat(), "km": round_metric(week[1])} if week else None,
        "biggest_month": {"year": month[0][0], "month": month[0][1], "km": round_metric(month[1])} if month else None,
    }


def _achievements(db: Session, user_id: int, as_of: date, total_km: float, records: dict) -> list[dict]:
    """Milestones reached and records set within the last RECENT_DAYS days, newest first."""
    since = as_of - timedelta(days=RECENT_DAYS - 1)
    recent_km, _ = _km_between(db, user_id, since, as_of)
    items: list[dict] = []
    before = total_km - recent_km
    reached, _ = next_total_milestone(total_km)
    if reached is not None and before < reached:
        items.append({"kind": "total", "km": reached})
    recent_by_shoe = dict(
        db.query(models.Run.shoe_id, func.sum(models.Run.km))
        .filter(models.Run.user_id == user_id, models.Run.date >= since.isoformat(),
                models.Run.date <= as_of.isoformat())
        .group_by(models.Run.shoe_id)
        .all()
    )
    for shoe in _active_shoes(db, user_id):
        recent = float(recent_by_shoe.get(shoe.id) or 0)
        crossed = [mark for mark in SHOE_MILESTONES_KM if shoe.mileage - recent < mark <= shoe.mileage]
        if crossed:
            items.append({"kind": "shoe", "shoe_id": shoe.id, "km": float(crossed[-1])})
    longest = records["longest_run"]
    if longest and date.fromisoformat(longest["date"]) >= since:
        items.append({"kind": "longest_run", "km": longest["km"], "date": longest["date"]})
    week = records["biggest_week"]
    if week and date.fromisoformat(week["week_start"]) + timedelta(days=6) >= since:
        items.append({"kind": "biggest_week", "km": week["km"], "week_start": week["week_start"]})
    return items


def home_summary(db: Session, user_id: int, as_of: date) -> dict:
    """Run-log header: this week, current streak, monthly goal, next shoe and milestones."""
    monday = as_of - timedelta(days=as_of.weekday())
    week_km, week_runs = _km_between(db, user_id, monday, as_of)
    month_km, _ = _km_between(db, user_id, as_of.replace(day=1), as_of)
    total_km, _ = _km_between(db, user_id, date(1900, 1, 1), as_of)
    goal = goals.goal_values(db, user_id)
    monthly_goal = goal["monthly_km"]
    reached, upcoming = next_total_milestone(total_km)
    records = _records(db, user_id, as_of)
    return {
        "as_of": as_of.isoformat(),
        "week": {"start": monday.isoformat(), "km": round_metric(week_km), "runs": week_runs},
        "streak_days": run_streaks(_run_days(db, user_id, as_of), as_of)["current_days"],
        "month_goal": {
            "active": as_of.year >= goal["start_year"],
            "km": round_metric(month_km),
            "goal_km": monthly_goal,
            "percent": round_metric(month_km / monthly_goal * 100, 1) if monthly_goal > 0 else 0.0,
        },
        "total": {
            "km": round_metric(total_km),
            "reached_km": reached,
            "next_km": upcoming,
            "remaining_km": round_metric(upcoming - total_km),
        },
        "records": records,
        "achievements": _achievements(db, user_id, as_of, total_km, records),
        "suggestion": shoe_suggestion(db, user_id, as_of),
    }


def year_review(db: Session, user_id: int, year: int, as_of: date) -> dict:
    """Calendar-year summary from the run log; a future year has no data."""
    end = trends_end(year, as_of)
    goal = goals.goal_values(db, user_id)
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
    previous_km, _ = _km_between(db, user_id, date(year - 1, 1, 1), date(year - 1, 12, 31))
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
        "goal": {
            "active": goal_active,
            "yearly_km": goal["yearly_km"],
            "percent": round_metric(total / goal["yearly_km"] * 100, 1) if goal_active and goal["yearly_km"] > 0 else None,
        },
    }


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
