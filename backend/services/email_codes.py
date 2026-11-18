"""Email binding and password reset with one-time codes (SPEC-079).

Codes are 6 digits, valid for 10 minutes and 5 attempts, and stored only as an
HMAC keyed with the app's secret, so a leaked database does not reveal them.
Password-reset requests answer the same way whether or not the account exists.
"""

import hashlib
import hmac
import re
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func
from sqlalchemy.orm import Session

from backend import models
from backend.credentials import get_password_hash
from backend.services.accounts import MIN_PASSWORD_LENGTH, find_user
from backend.services.errors import Conflict, Invalid
from backend.services.transactions import write_transaction

CODE_MINUTES = 10
MAX_ATTEMPTS = 5
VERIFY_EMAIL = "verify_email"
RESET_PASSWORD = "reset_password"
BAD_CODE = "Incorrect or expired code"
BAD_EMAIL = "Invalid email address"
EMAIL_TAKEN = "Email already in use"
EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
PURPOSE_TEXT = {VERIFY_EMAIL: "綁定 email", RESET_PASSWORD: "重設密碼"}

Send = Callable[[str, str, str], None]


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def normalize_email(email: str) -> str:
    value = email.strip().lower()
    if len(value) > 254 or not EMAIL_PATTERN.fullmatch(value):
        raise Invalid(BAD_EMAIL)
    return value


def _digest(secret_key: str, user_id: int, purpose: str, code: str) -> str:
    message = f"{user_id}:{purpose}:{code}".encode()
    return hmac.new(secret_key.encode(), message, hashlib.sha256).hexdigest()


def _issue(db: Session, user_id: int, purpose: str, email: str, secret_key: str) -> str:
    """Replace any earlier code for this purpose; the caller sends the returned code."""
    code = f"{secrets.randbelow(1_000_000):06d}"
    with write_transaction(db):
        db.execute(delete(models.EmailCode).where(
            models.EmailCode.user_id == user_id, models.EmailCode.purpose == purpose))
        db.add(models.EmailCode(user_id=user_id, purpose=purpose, email=email,
                                code_hash=_digest(secret_key, user_id, purpose, code),
                                expires_at=_now() + timedelta(minutes=CODE_MINUTES), attempts=0))
    return code


def _send(send: Send, email: str, purpose: str, code: str) -> None:
    send(
        email,
        f"跑鞋追蹤驗證碼：{code}",
        f"你的驗證碼是 {code}，{CODE_MINUTES} 分鐘內有效，用途：{PURPOSE_TEXT[purpose]}。\n\n"
        "如果不是你本人操作，請忽略這封信，你的帳號不會有任何變更。\n",
    )


def _redeem(db: Session, user_id: int, purpose: str, code: str, secret_key: str) -> models.EmailCode:
    """Return the matching code row, counting a failed attempt; raises one generic error."""
    row = db.query(models.EmailCode).filter(
        models.EmailCode.user_id == user_id, models.EmailCode.purpose == purpose).first()
    if row is None or row.expires_at <= _now() or row.attempts >= MAX_ATTEMPTS:
        raise Invalid(BAD_CODE)
    if not hmac.compare_digest(row.code_hash, _digest(secret_key, user_id, purpose, code.strip())):
        row_id = row.id
        with write_transaction(db):
            db.query(models.EmailCode).filter(models.EmailCode.id == row_id).update(
                {models.EmailCode.attempts: models.EmailCode.attempts + 1}, synchronize_session=False)
        raise Invalid(BAD_CODE)
    return row


def _email_owner(db: Session, email: str) -> models.User | None:
    return db.query(models.User).filter(func.lower(models.User.email) == email).first()


def request_email_binding(db: Session, user: models.User, email: str, *, send: Send, secret_key: str) -> dict:
    address = normalize_email(email)
    owner = _email_owner(db, address)
    if owner is not None and owner.id != user.id:
        raise Conflict(EMAIL_TAKEN)
    code = _issue(db, user.id, VERIFY_EMAIL, address, secret_key)
    _send(send, address, VERIFY_EMAIL, code)
    return {"ok": True}


def confirm_email_binding(db: Session, user: models.User, code: str, *, secret_key: str) -> dict:
    row = _redeem(db, user.id, VERIFY_EMAIL, code, secret_key)
    address, user_id = row.email, user.id
    with write_transaction(db):
        owner = _email_owner(db, address)
        if owner is not None and owner.id != user_id:
            raise Conflict(EMAIL_TAKEN)
        db.query(models.User).filter(models.User.id == user_id).update(
            {models.User.email: address}, synchronize_session=False)
        db.execute(delete(models.EmailCode).where(
            models.EmailCode.user_id == user_id, models.EmailCode.purpose == VERIFY_EMAIL))
    return {"email": address}


def remove_email(db: Session, user: models.User) -> dict:
    user_id = user.id
    with write_transaction(db):
        db.query(models.User).filter(models.User.id == user_id).update(
            {models.User.email: None}, synchronize_session=False)
        db.execute(delete(models.EmailCode).where(models.EmailCode.user_id == user_id))
    return {"email": None}


def _account(db: Session, identifier: str) -> models.User | None:
    value = identifier.strip()
    if "@" in value:
        try:
            return _email_owner(db, normalize_email(value))
        except Invalid:
            return None
    return find_user(db, value)


def request_password_reset(db: Session, identifier: str, *, send: Send, secret_key: str) -> dict:
    """Always the same answer: whether the account or its email exists is never revealed."""
    user = _account(db, identifier)
    if user is not None and user.email:
        code = _issue(db, user.id, RESET_PASSWORD, user.email, secret_key)
        _send(send, user.email, RESET_PASSWORD, code)
    return {"ok": True}


def reset_password(db: Session, identifier: str, code: str, new_password: str, *, secret_key: str) -> dict:
    if len(new_password) < MIN_PASSWORD_LENGTH:
        raise Invalid(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    user = _account(db, identifier)
    if user is None:
        raise Invalid(BAD_CODE)
    user_id = user.id
    _redeem(db, user_id, RESET_PASSWORD, code, secret_key)
    hashed_password = get_password_hash(new_password)
    with write_transaction(db):
        db.query(models.User).filter(models.User.id == user_id).update(
            {models.User.hashed_password: hashed_password, models.User.token_version: models.User.token_version + 1},
            synchronize_session=False)
        db.execute(delete(models.EmailCode).where(models.EmailCode.user_id == user_id))
    return {"ok": True}
