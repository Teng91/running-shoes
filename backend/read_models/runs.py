"""Complete calendar/summary read model independent of detail pagination."""

from calendar import monthrange

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend import models


def month_run_summary(db: Session, user_id: int, year: int, month: int) -> dict:
    start = f"{year:04d}-{month:02d}-01"
    end = f"{year:04d}-{month:02d}-{monthrange(year, month)[1]:02d}"
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
    return {
        "year": year,
        "month": month,
        "total_km": round(sum(day["km"] for day in calendar.values()), 2),
        "run_count": sum(day["count"] for day in calendar.values()),
        "run_days": len(calendar),
        "calendar": list(calendar.values()),
        "shoe_usage": sorted(shoes.values(), key=lambda row: (-row["km"], row["shoe_id"])),
    }
