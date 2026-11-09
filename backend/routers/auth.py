"""Authentication and account HTTP endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.auth import get_current_user
from backend.dependencies import get_db
from backend.rate_limits import enforce_auth_rate_limit, record_login_failure, reject_locked_account
from backend.routers.errors import service_errors
from backend.services import accounts

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=schemas.UserOut)
def register(request: Request, payload: schemas.UserCreate, db: Session = Depends(get_db)):
    enforce_auth_rate_limit(request)
    with service_errors():
        return accounts.register(db, payload.username, payload.password,
                                 max_users=request.app.state.settings.max_registered_users)


@router.post("/login", response_model=schemas.Token)
def login(request: Request, payload: schemas.UserLogin, db: Session = Depends(get_db)):
    enforce_auth_rate_limit(request)
    reject_locked_account(request, payload.username)
    try:
        with service_errors():
            return accounts.login(db, payload.username, payload.password,
                                  secret_key=request.app.state.settings.secret_key)
    except HTTPException as error:
        if error.status_code == 401:
            record_login_failure(request, payload.username)
        raise


@router.get("/me", response_model=schemas.UserOut)
def read_current_user(current_user: models.User = Depends(get_current_user)):
    return current_user


@router.post("/change-password")
def change_password(request: Request, payload: schemas.UserChangePassword,
                    db: Session = Depends(get_db)):
    enforce_auth_rate_limit(request)
    reject_locked_account(request, payload.username)
    try:
        with service_errors():
            return accounts.change_password(db, payload.username, payload.old_password,
                                            payload.new_password)
    except HTTPException as error:
        if error.status_code == 401:
            record_login_failure(request, payload.username)
        raise
