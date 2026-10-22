"""Authentication and account HTTP endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.auth import create_access_token, get_current_user, get_password_hash, verify_password
from backend.database import get_db
from backend.rate_limits import enforce_auth_rate_limit
from backend.services.transactions import write_transaction

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=schemas.UserOut)
def register(request: Request, payload: schemas.UserCreate, db: Session = Depends(get_db)):
    enforce_auth_rate_limit(request, db)
    if len(payload.password) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters")
    username = payload.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username cannot be empty")
    if len(username) > 50:
        raise HTTPException(status_code=400, detail="Username must be 50 characters or fewer")
    # Hash before taking the SQLite writer so bcrypt cannot block other writes.
    hashed_password = get_password_hash(payload.password)
    with write_transaction(db):
        if db.query(models.User).filter(models.User.username == username).first():
            raise HTTPException(status_code=400, detail="Username already registered")
        if db.query(models.User).count() >= request.app.state.settings.max_registered_users:
            raise HTTPException(status_code=403, detail="Registration capacity has been reached")
        user = models.User(username=username, hashed_password=hashed_password)
        db.add(user)
    db.refresh(user)
    return user


@router.post("/login", response_model=schemas.Token)
def login(request: Request, payload: schemas.UserLogin, db: Session = Depends(get_db)):
    enforce_auth_rate_limit(request, db)
    user = db.query(models.User).filter(models.User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    token = create_access_token(
        data={"sub": user.username, "token_version": user.token_version},
        secret_key=request.app.state.settings.secret_key,
    )
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me", response_model=schemas.UserOut)
def read_current_user(current_user: models.User = Depends(get_current_user)):
    return current_user


@router.post("/change-password")
def change_password(
    request: Request,
    payload: schemas.UserChangePassword,
    db: Session = Depends(get_db),
):
    enforce_auth_rate_limit(request, db)
    if len(payload.new_password) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters")
    user = db.query(models.User).filter(models.User.username == payload.username).first()
    if not user or not verify_password(payload.old_password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect username or old password")
    user_id, previous_hash, previous_version = user.id, user.hashed_password, user.token_version
    hashed_password = get_password_hash(payload.new_password)
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
            raise HTTPException(status_code=409, detail="密碼已被更新，請重新登入後再試")
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True}
