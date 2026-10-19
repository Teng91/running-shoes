"""Monthly shoe spending HTTP route."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend import models
from backend.auth import get_current_user
from backend.database import get_db

router = APIRouter(tags=["spending"])


@router.get("/api/spending/monthly")
def monthly_spending(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    shoes = db.query(models.Shoe).filter(
        models.Shoe.user_id == current_user.id,
        models.Shoe.is_deleted.is_(False),
    ).all()
    buckets: dict[tuple[int, int], dict[str, int | float]] = {}
    for shoe in shoes:
        if not shoe.date:
            continue
        try:
            year = int(shoe.date[:4])
            month = int(shoe.date[5:7])
        except (ValueError, IndexError):
            continue
        bucket = buckets.setdefault((year, month), {
            "year": year, "month": month, "total_paid": 0.0, "total_orig": 0.0,
        })
        bucket["total_paid"] += shoe.price
        bucket["total_orig"] += shoe.orig_price or 0
    return sorted(buckets.values(), key=lambda item: (item["year"], item["month"]))
