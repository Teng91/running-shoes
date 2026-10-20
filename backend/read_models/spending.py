"""Calendar-based spending calculations shared by all presentation adapters."""

from datetime import date

from sqlalchemy.orm import Session

from backend import models
from backend.forecasting import local_today


def spending_summary(db: Session, user_id: int, *, today: date | None = None) -> dict:
    as_of = today or local_today()
    shoes = (
        db.query(models.Shoe)
        .filter(
            models.Shoe.user_id == user_id,
            models.Shoe.is_deleted.is_(False),
        )
        .all()
    )
    buckets: dict[tuple[int, int], dict] = {}
    for shoe in shoes:
        try:
            purchase = date.fromisoformat(shoe.date)
        except (TypeError, ValueError):
            continue
        bucket = buckets.setdefault(
            (purchase.year, purchase.month),
            {
                "year": purchase.year,
                "month": purchase.month,
                "total_paid": 0.0,
                "total_orig": 0.0,
            },
        )
        bucket["total_paid"] += shoe.price or 0
        bucket["total_orig"] += shoe.orig_price or 0
    monthly = sorted(buckets.values(), key=lambda row: (row["year"], row["month"]))
    for row in monthly:
        row["total_paid"] = round(row["total_paid"], 2)
        row["total_orig"] = round(row["total_orig"], 2)
    paid = round(sum(shoe.price or 0 for shoe in shoes), 2)
    original = round(sum(shoe.orig_price or 0 for shoe in shoes), 2)
    first = monthly[0] if monthly else None
    # Future purchases retain their stored cost, but cannot create a negative divisor.
    span = (
        max(1, (as_of.year - first["year"]) * 12 + as_of.month - first["month"] + 1) if first else 0
    )
    highest = max(monthly, key=lambda row: row["total_paid"]) if monthly else None
    return {
        "as_of": as_of.isoformat(),
        "total_paid": paid,
        "total_original": original,
        "savings": round(original - paid, 2),
        "average_discount_percent": round(paid / original * 100, 1) if original > 0 else None,
        "average_monthly_paid": round(paid / span, 2) if span else 0.0,
        "start_month": f"{first['year']:04d}-{first['month']:02d}" if first else None,
        "month_span": span,
        "highest_month": {key: highest[key] for key in ("year", "month", "total_paid")}
        if highest
        else None,
        "monthly": monthly,
    }
