"""Account use cases; transport adapters supply configuration and credentials."""
import secrets
from functools import cache

from sqlalchemy import delete, func
from sqlalchemy.orm import Session

from backend import clock, models
from backend.credentials import (
    create_access_token,
    get_password_hash,
    session_started_at,
    verify_password,
)
from backend.database import Base
from backend.services import invites
from backend.services.errors import CapacityExceeded, Conflict, Invalid, NotFound, Unauthorized
from backend.services.transactions import write_transaction
from backend.settings import account_name_key

MIN_PASSWORD_LENGTH = 8
REGISTRATION_CLOSED = "Registration is closed"
USERNAME_TAKEN = "Username already registered"
ADMIN_CANNOT_DELETE = "Admin accounts cannot be deleted"


def username_key(username: str) -> str:
    """The account identity of a typed name: trimmed, with ASCII letters lowered.

    SPEC-093: SQLite's lower(), which backs the unique uq_users_username_lower index, only
    folds A–Z. Python's lower() also folds letters such as "Ä", so "Ärger" could not log in
    with the name it registered. Matching SQLite keeps lookup, uniqueness and lockouts one rule.
    """
    return account_name_key(username)


def find_user(db: Session, username: str) -> models.User | None:
    """Usernames are case-insensitive (SPEC-075): "Runner" and "runner" are one account."""
    return db.query(models.User).filter(func.lower(models.User.username) == username_key(username)).first()


@cache
def _unknown_user_hash() -> str:
    # Unknown usernames still pay one bcrypt check, so response time does not
    # reveal which accounts exist.
    return get_password_hash("unknown-user-timing-equalizer")


def register(db: Session, username: str, password: str, *, max_users: int,
             mode: str = "open", invite_code: str = "", admin_names: frozenset[str] = frozenset()):
    """Create an account; ``admin_names`` are the ``ADMIN_USERNAMES`` keys (``account_name_key``).

    SPEC-085/093: sign-up never lets anyone claim an admin name that is not registered yet
    (or no longer is), because admin rights follow the name. The only exception is the very
    first account of a new deployment, registered while ``REGISTRATION_MODE=open``; later
    admins register an ordinary account first and are then added to ``ADMIN_USERNAMES``.
    The answer is the same as for a taken name, so sign-up does not reveal which names are admins.

    SPEC-088: in invite mode the invite is checked before the name, so without a valid
    invite sign-up cannot be used to find out which names are taken.
    """
    if mode == "closed":
        raise Invalid(REGISTRATION_CLOSED)
    if mode == "invite" and not invite_code.strip():
        raise Invalid(invites.INVALID_INVITE)
    if len(password) < MIN_PASSWORD_LENGTH:
        raise Invalid(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    username = username.strip()
    if not username:
        raise Invalid("Username cannot be empty")
    if len(username) > 50:
        raise Invalid("Username must be 50 characters or fewer")
    # Hash before taking the SQLite writer so bcrypt cannot block other writes.
    hashed_password = get_password_hash(password)
    with write_transaction(db):
        if mode == "invite":
            # Same transaction: a refused registration rolls back and never spends the invite.
            invites.redeem_invite(db, invite_code)
        user_count = db.query(models.User).count()
        bootstrap = mode == "open" and user_count == 0
        if find_user(db, username) or (username_key(username) in admin_names and not bootstrap):
            raise Invalid(USERNAME_TAKEN)
        if user_count >= max_users:
            raise CapacityExceeded("Registration capacity has been reached")
        user = models.User(username=username, hashed_password=hashed_password)
        db.add(user)
    db.refresh(user)
    return user


def login(db: Session, username: str, password: str, *, secret_key: str):
    user = find_user(db, username)
    if user is None:
        verify_password(password, _unknown_user_hash())
        raise Unauthorized("Incorrect username or password")
    if not verify_password(password, user.hashed_password):
        raise Unauthorized("Incorrect username or password")
    token = create_access_token(
        {"sub": user.username, "token_version": user.token_version, "aid": user.backup_id},
        secret_key=secret_key,
    )
    return {"access_token": token, "token_type": "bearer"}


def renew_session(user: models.User, claims: dict, *, secret_key: str) -> dict:
    """A fresh 7-day token for a still-valid session, capped 30 days after sign-in (SPEC-143).

    The caller has verified ``claims`` against ``user``; the sign-in time is carried over, so
    renewing never extends a session past ``SESSION_MAX_AGE_DAYS``.
    """
    token = create_access_token(
        {"sub": user.username, "token_version": user.token_version, "aid": user.backup_id,
         "auth_time": session_started_at(claims)},
        secret_key=secret_key,
    )
    return {"access_token": token, "token_type": "bearer"}


def change_password(db: Session, username: str, old_password: str, new_password: str):
    if len(new_password) < MIN_PASSWORD_LENGTH:
        raise Invalid(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    user = find_user(db, username)
    if user is None:
        verify_password(old_password, _unknown_user_hash())
        raise Unauthorized("Incorrect username or old password")
    if not verify_password(old_password, user.hashed_password):
        raise Unauthorized("Incorrect username or old password")
    user_id, previous_hash, previous_version = user.id, user.hashed_password, user.token_version
    # Hash before taking the SQLite writer; the conditional update detects a
    # concurrent change made after the password was verified.
    hashed_password = get_password_hash(new_password)
    with write_transaction(db):
        changed = db.query(models.User).filter(
            models.User.id == user_id,
            models.User.hashed_password == previous_hash,
            models.User.token_version == previous_version,
        ).update(
            {
                models.User.token_version: models.User.token_version + 1,
                models.User.hashed_password: hashed_password,
            },
            synchronize_session=False,
        )
        if not changed:
            raise Conflict("密碼已被更新，請重新登入後再試")
    return {"ok": True}


def logout_everywhere(db: Session, user: models.User) -> dict:
    """SPEC-088: end every session of the account, this one included, keeping the password."""
    user_id = user.id
    with write_transaction(db, user_id, reason="account.logout_all"):
        db.query(models.User).filter(models.User.id == user_id).update(
            {models.User.token_version: models.User.token_version + 1}, synchronize_session=False,
        )
    return {"ok": True}


def set_timezone(db: Session, user: models.User, name: str) -> dict:
    """SPEC-147: the IANA zone that decides the account's today, months and run-date limit.

    Stored dates are calendar days and stay as they are; only what counts as today moves.
    """
    if not clock.is_timezone_name(name):
        raise Invalid("Unknown time zone")
    user_id = user.id
    with write_transaction(db, user_id, reason="account.timezone"):
        db.query(models.User).filter(models.User.id == user_id).update(
            {models.User.timezone: name}, synchronize_session=False,
        )
    zone = clock.zone(name)
    return {"timezone": zone.key, "today": clock.local_today(zone).isoformat()}


def account_rate_limit_keys(user_id: int) -> tuple[str, ...]:
    """Bucket keys that name this account in `backend.rate_limits` windows (SPEC-093).

    Per-account windows use the bare id; mail and code-attempt windows prefix it.
    """
    account = f"user:{user_id}"
    return (str(user_id), account, f"reset:{account}", f"verify_email:{account}", f"reset_password:{account}")


def _account_tables():
    """Every table holding per-account rows, children before parents (SPEC-075)."""
    return [table for table in reversed(Base.metadata.sorted_tables)
            if table.name != "users" and "user_id" in table.columns]


def delete_account(db: Session, user: models.User, password: str, *, is_admin: bool = False) -> dict:
    """Permanently remove the account and everything it owns, after re-checking the password.

    SPEC-085: an admin account cannot be deleted. Admin rights follow the name, so a freed
    name would let the next person who registers it manage invites and every password.
    """
    if is_admin:
        raise Invalid(ADMIN_CANNOT_DELETE)
    if not verify_password(password, user.hashed_password):
        # 400, not 401: a mistyped password must not look like an expired session and sign out.
        raise Invalid("Incorrect password")
    user_id = user.id
    with write_transaction(db, user_id, reason="account.delete"):
        for table in _account_tables():
            db.execute(delete(table).where(table.c.user_id == user_id))
        # Deleting audited rows wrote fresh audit events and a write context; clear them last.
        db.execute(delete(models.AuditEvent).where(models.AuditEvent.user_id == user_id))
        db.execute(delete(models.WriteContext).where(models.WriteContext.user_id == user_id))
        # SPEC-093: SQLite reuses the highest user id, so per-account throttling windows keyed
        # by the id must go too, or the next account would inherit today's AI and upload use.
        db.execute(delete(models.RateLimitBucket).where(
            models.RateLimitBucket.bucket_key.in_(account_rate_limit_keys(user_id))))
        db.execute(delete(models.User).where(models.User.id == user_id))
    db.expunge_all()
    return {"ok": True}


def admin_reset_password(db: Session, username: str) -> dict:
    """Give an account a one-off temporary password and sign out its sessions (SPEC-075)."""
    user = find_user(db, username)
    if user is None:
        raise NotFound("User not found")
    user_id, stored_name = user.id, user.username
    temporary = secrets.token_urlsafe(9)
    hashed_password = get_password_hash(temporary)
    with write_transaction(db):
        db.query(models.User).filter(models.User.id == user_id).update(
            {models.User.hashed_password: hashed_password, models.User.token_version: models.User.token_version + 1},
            synchronize_session=False,
        )
    return {"username": stored_name, "temporary_password": temporary}
