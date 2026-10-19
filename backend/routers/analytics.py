"""Dashboard and per-shoe analytics HTTP routes."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend import analytics, models
from backend.auth import get_current_user
from backend.database import get_db

router = APIRouter(tags=["analytics"])


@router.get("/api/analytics/dashboard")
def dashboard_analytics(
    year: int = Query(..., ge=1900, le=2100),
    month: int = Query(..., ge=1, le=12),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return analytics.dashboard_analytics(db, current_user.id, year, month)


@router.get("/api/shoes/{shoe_id}/analytics")
def get_shoe_analytics(
    shoe_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = analytics.shoe_analytics(db, current_user.id, shoe_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Shoe not found")
    return result
