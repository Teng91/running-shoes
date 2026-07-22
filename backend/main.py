import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from backend.database import engine, Base, SessionLocal, get_db
from backend import models, schemas, llm, agent
from backend.auth import (
    verify_password, get_password_hash,
    create_access_token, get_current_user,
)


# ── Seed default data (only when SEED_DATA=true) ──────────────
def seed_default_data():
    if os.environ.get("SEED_DATA", "").lower() != "true":
        return
    db = SessionLocal()
    try:
        # Ensure Joy exists (so seed data always belongs to her)
        joy_user = db.query(models.User).filter(models.User.username == "Joy").first()
        if not joy_user:
            migration_password = os.environ.get("MIGRATION_PASSWORD")
            if not migration_password:
                raise RuntimeError(
                    "MIGRATION_PASSWORD must be set when SEED_DATA=true so the "
                    "Joy account has a known password."
                )
            joy_user = models.User(username="Joy", hashed_password=get_password_hash(migration_password))
            db.add(joy_user)
            db.commit()
            db.refresh(joy_user)

        if db.query(models.Shoe).count() == 0:
            defaults = [
                models.Shoe(user_id=joy_user.id, brand="Mizuno", model="Wave Sky 7", date="2024-09-15", size="us13/31cm", price=2390, orig_price=4780, mileage=540, expected_mileage=800, monthly_km=60),
                models.Shoe(user_id=joy_user.id, brand="Mizuno", model="Wave Rider 29", date="2025-12-12", size="us12/30cm", price=2505, orig_price=3980, mileage=293, expected_mileage=800, monthly_km=60),
                models.Shoe(user_id=joy_user.id, brand="Mizuno", model="Wave Sky 9", date="2025-12-30", size="us13/31cm", price=3080, orig_price=4980, mileage=125, expected_mileage=800, monthly_km=60),
                models.Shoe(user_id=joy_user.id, brand="New Balance", model="Rebel v5", date="2026-02-20", size="us11/29cm", price=2300, orig_price=4280, mileage=102, expected_mileage=500, monthly_km=30),
                models.Shoe(user_id=joy_user.id, brand="Adidas", model="Boston 12", date="2026-04-21", size="us11.5/29.5cm", price=1680, orig_price=4290, mileage=61, expected_mileage=800, monthly_km=30),
                models.Shoe(user_id=joy_user.id, brand="PUMA", model="Nitro Elite 3", date="2026-06-25", size="us11.5/29.5cm", price=3310, orig_price=5980, mileage=0, expected_mileage=500, monthly_km=20),
                models.Shoe(user_id=joy_user.id, brand="Asics", model="Gel-Excite 8", date="2024-01-05", size="us11/29cm", price=1780, orig_price=2280, mileage=625, expected_mileage=600, monthly_km=0, is_retired=True),
                models.Shoe(user_id=joy_user.id, brand="FILA", model="Bon Voyage", date="2025-08-10", size="us11/29cm", price=2200, orig_price=2880, mileage=418, expected_mileage=400, monthly_km=0, is_retired=True),
            ]
            db.add_all(defaults)
            db.commit()

        if db.query(models.MonthlyMileage).filter(models.MonthlyMileage.user_id == joy_user.id).count() == 0:
            mileage_data = [
                (2023, 1, 2.91), (2023, 2, 2.87), (2023, 3, 29.42), (2023, 4, 56.65),
                (2023, 5, 41.05), (2023, 6, 6.67), (2023, 7, 6.05), (2023, 8, 4.04),
                (2023, 9, 11.67), (2023, 10, 23.34), (2023, 11, 12.08), (2023, 12, 0),
                (2024, 1, 0), (2024, 2, 8.27), (2024, 3, 3.96), (2024, 4, 6.38),
                (2024, 5, 4.3), (2024, 6, 3.48), (2024, 7, 0), (2024, 8, 70.11),
                (2024, 9, 53.21), (2024, 10, 37.43), (2024, 11, 47.91), (2024, 12, 17.42),
                (2025, 1, 0), (2025, 2, 23.15), (2025, 3, 56.34), (2025, 4, 32.7),
                (2025, 5, 50.64), (2025, 6, 43.39), (2025, 7, 79.2), (2025, 8, 81.07),
                (2025, 9, 51.97), (2025, 10, 67.49), (2025, 11, 102.49), (2025, 12, 196.32),
                (2026, 1, 125.71), (2026, 2, 135.91), (2026, 3, 130.13), (2026, 4, 78.41),
                (2026, 5, 149.12), (2026, 6, 128.2),
            ]
            entries = [
                models.MonthlyMileage(user_id=joy_user.id, year=y, month=m, km=km)
                for y, m, km in mileage_data
            ]
            db.add_all(entries)
            db.commit()
    finally:
        db.close()


# ── Lifespan: create tables & migrate ─────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # One-time migration: if old schema exists (shoes table without user_id), migrate
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()

    if "shoes" in existing_tables and "users" not in existing_tables:
        # Old schema: create users table, add user_id to shoes, assign to "Joy"
        Base.metadata.create_all(bind=engine, tables=[models.User.__table__])

        migration_password = os.environ.get("MIGRATION_PASSWORD")
        if not migration_password:
            raise RuntimeError(
                "MIGRATION_PASSWORD must be set to run the schema migration; "
                "it becomes the password for the legacy 'Joy' account."
            )
        db = SessionLocal()
        try:
            joy_user = models.User(
                username="Joy",
                hashed_password=get_password_hash(migration_password),
            )
            db.add(joy_user)
            db.commit()
            db.refresh(joy_user)

            # Add user_id column (SQLite allows ALTER TABLE ADD COLUMN without FK)
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE shoes ADD COLUMN user_id INTEGER"))
                conn.execute(
                    text("UPDATE shoes SET user_id = :uid"),
                    {"uid": joy_user.id},
                )
                conn.commit()
        finally:
            db.close()

    Base.metadata.create_all(bind=engine)
    seed_default_data()
    yield


app = FastAPI(title="Running Shoes API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Serve static frontend ─────────────────────────────────────
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
frontend_dir.mkdir(exist_ok=True)


# index.html 內含 inline JS，必須用 no-cache 讓瀏覽器每次都向伺服器
# 驗證（有 ETag，未變更會回 304 很省），否則使用者會一直卡在舊版前端。
def _index_response():
    return FileResponse(
        frontend_dir / "index.html",
        headers={"Cache-Control": "no-cache"},
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc):
    """Return index.html for 404s so SPA-style routing works,
    but return proper JSON for API errors (4xx/5xx)."""
    if exc.status_code == 404:
        path = request.url.path
        if path.startswith("/api/") or path.startswith("/docs") or path.startswith("/openapi.json"):
            return JSONResponse({"detail": exc.detail}, status_code=404)
        # Resolve and ensure the file lives inside frontend_dir — otherwise
        # a path like "/../shoes.db" could escape and serve arbitrary files.
        try:
            candidate = (frontend_dir / path.lstrip("/")).resolve()
        except (OSError, ValueError):
            return _index_response()
        if frontend_dir.resolve() in candidate.parents and candidate.is_file():
            return FileResponse(candidate)
        return _index_response()
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


# ── Auth Routes ───────────────────────────────────────────────
@app.post("/api/auth/register", response_model=schemas.UserOut)
def register(payload: schemas.UserCreate, db: Session = Depends(get_db)):
    if len(payload.password) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters")
    if db.query(models.User).filter(models.User.username == payload.username).first():
        raise HTTPException(status_code=400, detail="Username already registered")
    user = models.User(
        username=payload.username,
        hashed_password=get_password_hash(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.post("/api/auth/login", response_model=schemas.Token)
def login(payload: schemas.UserLogin, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == payload.username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect password")
    token = create_access_token(data={"sub": user.username})
    return {"access_token": token, "token_type": "bearer"}


@app.get("/api/auth/me", response_model=schemas.UserOut)
def read_current_user(current_user: models.User = Depends(get_current_user)):
    return current_user


@app.post("/api/auth/change-password")
def change_password(payload: schemas.UserChangePassword, db: Session = Depends(get_db)):
    if len(payload.new_password) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters")
    user = db.query(models.User).filter(models.User.username == payload.username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not verify_password(payload.old_password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect old password")
    user.hashed_password = get_password_hash(payload.new_password)
    db.commit()
    return {"ok": True}


# ── Shoe Routes ───────────────────────────────────────────────
@app.get("/api/shoes/active", response_model=list[schemas.ShoeOut])
def list_active(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.query(models.Shoe).filter(
        models.Shoe.is_retired == False,
        models.Shoe.user_id == current_user.id,
    ).all()


@app.get("/api/shoes/retired", response_model=list[schemas.ShoeOut])
def list_retired(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.query(models.Shoe).filter(
        models.Shoe.is_retired == True,
        models.Shoe.user_id == current_user.id,
    ).all()


@app.post("/api/shoes", response_model=schemas.ShoeOut)
def create_shoe(
    payload: schemas.ShoeCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    shoe = models.Shoe(**payload.model_dump(), user_id=current_user.id)
    db.add(shoe)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(shoe)
    return shoe


@app.put("/api/shoes/{shoe_id}", response_model=schemas.ShoeOut)
def update_shoe(
    shoe_id: int,
    payload: schemas.ShoeUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    shoe = db.query(models.Shoe).filter(
        models.Shoe.id == shoe_id,
        models.Shoe.user_id == current_user.id,
    ).first()
    if not shoe:
        raise HTTPException(status_code=404, detail="Shoe not found")
    update_data = payload.model_dump(exclude_unset=True)
    for k, v in update_data.items():
        setattr(shoe, k, v)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(shoe)
    return shoe


@app.delete("/api/shoes/{shoe_id}")
def delete_shoe(
    shoe_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    shoe = db.query(models.Shoe).filter(
        models.Shoe.id == shoe_id,
        models.Shoe.user_id == current_user.id,
    ).first()
    if not shoe:
        raise HTTPException(status_code=404, detail="Shoe not found")
    db.delete(shoe)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True}


# ── Monthly Mileage Routes ────────────────────────────────────
@app.get("/api/monthly-mileage", response_model=list[schemas.MonthlyMileageOut])
def list_monthly_mileage(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.query(models.MonthlyMileage).filter(
        models.MonthlyMileage.user_id == current_user.id,
    ).order_by(models.MonthlyMileage.year, models.MonthlyMileage.month).all()
    return rows


@app.post("/api/monthly-mileage", response_model=schemas.MonthlyMileageOut)
def create_monthly_mileage(
    payload: schemas.MonthlyMileageCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.month < 1 or payload.month > 12:
        raise HTTPException(status_code=400, detail="Month must be between 1 and 12")
    if payload.km < 0:
        raise HTTPException(status_code=400, detail="Km must be non-negative")

    existing = db.query(models.MonthlyMileage).filter(
        models.MonthlyMileage.user_id == current_user.id,
        models.MonthlyMileage.year == payload.year,
        models.MonthlyMileage.month == payload.month,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="該月份已有紀錄")

    entry = models.MonthlyMileage(**payload.model_dump(), user_id=current_user.id)
    db.add(entry)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(entry)
    return entry


@app.put("/api/monthly-mileage/{entry_id}", response_model=schemas.MonthlyMileageOut)
def update_monthly_mileage(
    entry_id: int,
    payload: schemas.MonthlyMileageUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    entry = db.query(models.MonthlyMileage).filter(
        models.MonthlyMileage.id == entry_id,
        models.MonthlyMileage.user_id == current_user.id,
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Monthly mileage not found")

    update_data = payload.model_dump(exclude_unset=True)
    new_month = update_data.get("month", entry.month)
    new_year = update_data.get("year", entry.year)
    if new_month < 1 or new_month > 12:
        raise HTTPException(status_code=400, detail="Month must be between 1 and 12")

    # Check uniqueness if year/month are changing
    if ("year" in update_data or "month" in update_data) and (
        new_year != entry.year or new_month != entry.month
    ):
        clash = db.query(models.MonthlyMileage).filter(
            models.MonthlyMileage.user_id == current_user.id,
            models.MonthlyMileage.year == new_year,
            models.MonthlyMileage.month == new_month,
            models.MonthlyMileage.id != entry_id,
        ).first()
        if clash:
            raise HTTPException(status_code=400, detail="該月份已有紀錄")

    for k, v in update_data.items():
        setattr(entry, k, v)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(entry)
    return entry


@app.delete("/api/monthly-mileage/{entry_id}")
def delete_monthly_mileage(
    entry_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    entry = db.query(models.MonthlyMileage).filter(
        models.MonthlyMileage.id == entry_id,
        models.MonthlyMileage.user_id == current_user.id,
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Monthly mileage not found")
    db.delete(entry)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True}


# ── Agent / Chat Routes ────────────────────────────────────────
@app.get("/api/agent/providers")
def list_agent_providers():
    """回傳 provider/model 清單（含 key 是否已設定）。"""
    return llm.list_providers()


@app.post("/api/agent/chat")
def agent_chat(
    payload: dict,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """SSE 串流：接收 user_message, history, provider, model，回傳 agent 事件。"""
    user_message = payload.get("user_message", "")
    history = payload.get("history", [])
    provider = payload.get("provider", "openrouter")
    model = payload.get("model")

    return StreamingResponse(
        agent.run_agent(
            user_message=user_message,
            history=history,
            provider=provider,
            model=model,
            db=db,
            user_id=current_user.id,
        ),
        media_type="text/event-stream",
    )


@app.post("/api/agent/chat/stream")
def agent_chat_stream(
    payload: dict,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """SSE 串流版：與 /api/agent/chat 相同，但 LLM token 會逐字即時送達。"""
    user_message = payload.get("user_message", "")
    history = payload.get("history", [])
    provider = payload.get("provider", "openrouter")
    model = payload.get("model")

    return StreamingResponse(
        agent.run_agent_stream(
            user_message=user_message,
            history=history,
            provider=provider,
            model=model,
            db=db,
            user_id=current_user.id,
        ),
        media_type="text/event-stream",
    )
