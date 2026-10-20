"""Monthly shoe spending HTTP route."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend import models
from backend.auth import get_current_user
from backend.database import get_db
from backend.read_models.spending import spending_summary

router = APIRouter(tags=["spending"])


@router.get("/api/spending/monthly")
def monthly_spending(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return spending_summary(db, current_user.id)["monthly"]


@router.get("/api/spending/summary")
def get_spending_summary(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return spending_summary(db, current_user.id)
