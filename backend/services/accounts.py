"""Account use cases; transport adapters supply configuration and credentials."""
from sqlalchemy.orm import Session

from backend import models
from backend.credentials import create_access_token, get_password_hash, verify_password
from backend.services.errors import CapacityExceeded, Conflict, Invalid, Unauthorized
from backend.services.transactions import write_transaction


def register(db: Session, username: str, password: str, *, max_users: int):
    if len(password) < 4:
        raise Invalid("Password must be at least 4 characters")
    username = username.strip()
    if not username:
        raise Invalid("Username cannot be empty")
    if len(username) > 50:
        raise Invalid("Username must be 50 characters or fewer")
    # Hash before taking the SQLite writer so bcrypt cannot block other writes.
    hashed_password = get_password_hash(password)
    with write_transaction(db):
        if db.query(models.User).filter(models.User.username == username).first():
            raise Invalid("Username already registered")
        if db.query(models.User).count() >= max_users:
            raise CapacityExceeded("Registration capacity has been reached")
        user = models.User(username=username, hashed_password=hashed_password)
        db.add(user)
    db.refresh(user)
    return user


def login(db: Session, username: str, password: str, *, secret_key: str):
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user or not verify_password(password, user.hashed_password):
        raise Unauthorized("Incorrect username or password")
    token = create_access_token(
        {"sub": user.username, "token_version": user.token_version}, secret_key=secret_key,
    )
    return {"access_token": token, "token_type": "bearer"}


def change_password(db: Session, username: str, old_password: str, new_password: str):
    if len(new_password) < 4:
        raise Invalid("Password must be at least 4 characters")
    user = db.query(models.User).filter(models.User.username == username).first()
    if not user or not verify_password(old_password, user.hashed_password):
        raise Unauthorized("Incorrect username or old password")
    user_id, previous_hash, previous_version = user.id, user.hashed_password, user.token_version
    hashed_password = get_password_hash(new_password)
    try:
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
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True}
