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


@router.get("/registration", response_model=schemas.RegistrationOut)
def registration(request: Request):
    """Public: whether the sign-up form needs an invite code or is closed (SPEC-075)."""
    return {"mode": request.app.state.settings.registration_mode}


@router.post("/register", response_model=schemas.UserOut)
def register(request: Request, payload: schemas.UserCreate, db: Session = Depends(get_db)):
    enforce_auth_rate_limit(request)
    settings = request.app.state.settings
    with service_errors():
        return accounts.register(db, payload.username, payload.password,
                                 max_users=settings.max_registered_users,
                                 mode=settings.registration_mode, invite_code=payload.invite_code)


@router.post("/login", response_model=schemas.Token)
def login(request: Request, payload: schemas.UserLogin, db: Session = Depends(get_db)):
    enforce_auth_rate_limit(request)
    # Lockouts key on the case-folded name, like the account lookup (SPEC-075).
    account = payload.username.strip().casefold()
    reject_locked_account(request, account)
    try:
        with service_errors():
            return accounts.login(db, payload.username, payload.password,
                                  secret_key=request.app.state.settings.secret_key)
    except HTTPException as error:
        if error.status_code == 401:
            record_login_failure(request, account)
        raise


@router.get("/me", response_model=schemas.UserOut)
def read_current_user(request: Request, current_user: models.User = Depends(get_current_user)):
    return {"id": current_user.id, "username": current_user.username,
            "is_admin": request.app.state.settings.is_admin(current_user.username)}


@router.post("/delete-account")
def delete_account(request: Request, payload: schemas.AccountDelete,
                   current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Permanently delete the signed-in account after re-entering its password (SPEC-075)."""
    enforce_auth_rate_limit(request)
    with service_errors():
        return accounts.delete_account(db, current_user, payload.password)


@router.post("/change-password")
def change_password(request: Request, payload: schemas.UserChangePassword,
                    db: Session = Depends(get_db)):
    enforce_auth_rate_limit(request)
    account = payload.username.strip().casefold()
    reject_locked_account(request, account)
    try:
        with service_errors():
            return accounts.change_password(db, payload.username, payload.old_password,
                                            payload.new_password)
    except HTTPException as error:
        if error.status_code == 401:
            record_login_failure(request, account)
        raise
