"""Dashboard and per-shoe analytics HTTP routes."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend import analytics, models
from backend.auth import get_current_user
from backend.clock import local_today
from backend.dependencies import get_db
from backend.read_models import highlights, pace, race_readiness, trends

router = APIRouter(tags=["analytics"])


@router.get("/api/analytics/dashboard")
def dashboard_analytics(
    year: int = Query(..., ge=1900, le=2100),
    month: int = Query(..., ge=1, le=12),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return analytics.dashboard_analytics(db, current_user.id, year, month)


@router.get("/api/analytics/race")
def race_readiness_analytics(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return race_readiness.race_readiness(db, current_user.id, local_today())


@router.get("/api/analytics/trends")
def training_trends(
    year: int = Query(..., ge=1900, le=2100),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return trends.training_trends(db, current_user.id, year, local_today())


@router.get("/api/analytics/shoe-timeline")
def shoe_timeline(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return trends.shoe_timeline(db, current_user.id, local_today())

@router.get("/api/analytics/home")
def home_summary(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return highlights.home_summary(db, current_user.id, local_today())


@router.get("/api/analytics/year-review")
def year_review(
    year: int = Query(..., ge=1900, le=2100),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return highlights.year_review(db, current_user.id, year, local_today())


@router.get("/api/analytics/shoe-distance-mix")
def shoe_distance_mix(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return highlights.shoe_distance_mix(db, current_user.id)


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


@router.get("/api/analytics/pace")
def pace_analysis(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return pace.pace_analysis(db, current_user.id, local_today())
