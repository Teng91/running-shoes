"""Authentication and account HTTP endpoints."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.auth import get_current_user
from backend.dependencies import get_db
from backend.mailer import Mailer, MailError
from backend.rate_limits import (
    enforce_auth_rate_limit,
    enforce_mail_limits,
    record_login_failure,
    reject_locked_account,
)
from backend.routers.errors import service_errors
from backend.services import accounts, email_codes

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/registration", response_model=schemas.RegistrationOut)
def registration(request: Request):
    """Public: whether the sign-up form needs an invite code or is closed (SPEC-075)."""
    settings = request.app.state.settings
    return {"mode": settings.registration_mode, "mail_enabled": request.app.state.mailer is not None}


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
            "is_admin": request.app.state.settings.is_admin(current_user.username), "email": current_user.email}


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


MAIL_OFF = "Email is not configured"


def _mailer(request: Request) -> Mailer:
    mailer = request.app.state.mailer
    if mailer is None:
        raise HTTPException(status_code=503, detail=MAIL_OFF)
    return mailer


@router.post("/email/request")
def request_email_binding(request: Request, payload: schemas.EmailBindRequest,
                          current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Email a code to the new address; it is bound only after the code is confirmed (SPEC-079)."""
    send = _mailer(request)
    enforce_mail_limits(request, f"user:{current_user.id}")
    try:
        with service_errors():
            return email_codes.request_email_binding(db, current_user, payload.email, send=send,
                                                     secret_key=request.app.state.settings.secret_key)
    except MailError as error:
        raise HTTPException(status_code=503, detail=str(error)) from None


@router.post("/email/confirm")
def confirm_email_binding(request: Request, payload: schemas.EmailCodeConfirm,
                          current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    enforce_auth_rate_limit(request)
    with service_errors():
        return email_codes.confirm_email_binding(db, current_user, payload.code,
                                                 secret_key=request.app.state.settings.secret_key)


@router.post("/email/remove")
def remove_email(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    with service_errors():
        return email_codes.remove_email(db, current_user)


@router.post("/password-reset/request")
def request_password_reset(request: Request, payload: schemas.PasswordResetRequest, background: BackgroundTasks,
                           db: Session = Depends(get_db)):
    """Same answer and timing whether or not the account exists: mail is sent after the response."""
    mailer = _mailer(request)
    enforce_auth_rate_limit(request)
    enforce_mail_limits(request, "reset:" + payload.identifier.strip().casefold())

    def send_later(to: str, subject: str, body: str) -> None:
        def deliver() -> None:
            try:
                mailer(to, subject, body)
            except MailError:
                pass  # Already logged without the address; the answer stays the same.
        background.add_task(deliver)

    with service_errors():
        return email_codes.request_password_reset(db, payload.identifier, send=send_later,
                                                  secret_key=request.app.state.settings.secret_key)


@router.post("/password-reset/confirm")
def confirm_password_reset(request: Request, payload: schemas.PasswordResetConfirm, db: Session = Depends(get_db)):
    enforce_auth_rate_limit(request)
    with service_errors():
        return email_codes.reset_password(db, payload.identifier, payload.code, payload.new_password,
                                          secret_key=request.app.state.settings.secret_key)
