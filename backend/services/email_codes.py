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
from backend.services.accounts import MIN_PASSWORD_LENGTH, find_user, username_key
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
# SPEC-083: how the password changed, as told in the notice.
CHANGED_BY_USER = "changed"
CHANGED_BY_EMAIL_CODE = "email_reset"
CHANGED_BY_ADMIN = "admin_reset"
NOTICE_HOW = {
    CHANGED_BY_USER: "在「資料與同步」輸入目前密碼後更改",
    CHANGED_BY_EMAIL_CODE: "在登入頁用 email 驗證碼重設",
    CHANGED_BY_ADMIN: "由管理員產生臨時密碼",
}

Send = Callable[[str, str, str], None]


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def normalize_email(email: str) -> str:
    value = email.strip().lower()
    if len(value) > 254 or not EMAIL_PATTERN.fullmatch(value):
        raise Invalid(BAD_EMAIL)
    return value


CODE_KEY_LABEL = b"running-shoes/email-code/v1"


def code_key(secret_key: str) -> bytes:
    """A key used only for email codes, derived from the app secret (SPEC-093).

    The same SECRET_KEY signs session tokens; deriving a purpose-bound key keeps the two
    uses apart, so neither kind of value can stand in for the other.
    """
    return hmac.new(secret_key.encode(), CODE_KEY_LABEL, hashlib.sha256).digest()


def _digest(secret_key: str, user_id: int, purpose: str, code: str) -> str:
    message = f"{user_id}:{purpose}:{code}".encode()
    return hmac.new(code_key(secret_key), message, hashlib.sha256).hexdigest()


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


def _redeem(db: Session, user_id: int, purpose: str, code: str, secret_key: str) -> str:
    """Spend one attempt, then compare; returns the code's email or raises one generic error.

    SPEC-085: the attempt is counted by a single conditional UPDATE before the comparison,
    so concurrent guesses cannot get past MAX_ATTEMPTS by all reading the same count.
    """
    current = (models.EmailCode.user_id == user_id, models.EmailCode.purpose == purpose)
    with write_transaction(db):
        spent = db.query(models.EmailCode).filter(
            *current, models.EmailCode.expires_at > _now(), models.EmailCode.attempts < MAX_ATTEMPTS,
        ).update({models.EmailCode.attempts: models.EmailCode.attempts + 1}, synchronize_session=False)
        row = db.query(models.EmailCode.code_hash, models.EmailCode.email).filter(*current).first() if spent else None
    if row is None or not hmac.compare_digest(row.code_hash, _digest(secret_key, user_id, purpose, code.strip())):
        raise Invalid(BAD_CODE)
    return str(row.email)


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
    address, user_id = _redeem(db, user.id, VERIFY_EMAIL, code, secret_key), user.id
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


def attempt_key(db: Session, identifier: str) -> str:
    """Rate-limit key for reset-code attempts: the account when it exists (SPEC-085).

    Username and email share one budget; an unknown identifier gets its own key, so
    the limit behaves the same whether or not the account exists. An unknown identifier is
    folded like the lookup itself (emails lowered, names A–Z only, SPEC-131), so spellings the
    lookup treats as one identifier share one budget.
    """
    user = _account(db, identifier)
    if user is not None:
        return f"user:{user.id}"
    value = identifier.strip()
    return "name:" + (value.lower() if "@" in value else username_key(value))


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


def notify_password_changed(db: Session, identifier: str, how: str, *, send: Send, when: datetime) -> bool:
    """Tell the bound email that the password changed (SPEC-083); no email, no notice."""
    user = _account(db, identifier)
    if user is None or not user.email:
        return False
    send(
        user.email,
        "跑鞋追蹤：你的密碼已變更",
        f"你的跑鞋追蹤帳號「{user.username}」的密碼在 {when:%Y-%m-%d %H:%M}（台灣時間）變更了。\n"
        f"方式：{NOTICE_HOW[how]}。所有裝置上的登入都已登出。\n\n"
        "如果是你本人操作，不用理會這封信。\n"
        "如果不是你，請立刻在登入頁按「忘記密碼？」用這個 email 重設密碼，並通知管理員。\n",
    )
    return True
