import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import cast

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from sqlalchemy import Table, inspect, text
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend import agent, llm, models, schemas
from backend.auth import (
    create_access_token,
    get_current_user,
    get_password_hash,
    verify_password,
)
from backend.database import Base, SessionLocal, engine, get_db

logger = logging.getLogger(__name__)


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
                models.Shoe(user_id=joy_user.id, brand="Mizuno", model="Wave Sky 7", date="2024-09-15", size="us13/31cm", price=2390, orig_price=4780, mileage=540, expected_mileage=800, monthly_km=60, categories=["Daily"]),
                models.Shoe(user_id=joy_user.id, brand="Mizuno", model="Wave Rider 29", date="2025-12-12", size="us12/30cm", price=2505, orig_price=3980, mileage=293, expected_mileage=800, monthly_km=60, categories=["Daily"]),
                models.Shoe(user_id=joy_user.id, brand="Mizuno", model="Wave Sky 9", date="2025-12-30", size="us13/31cm", price=3080, orig_price=4980, mileage=125, expected_mileage=800, monthly_km=60, categories=["Daily"]),
                models.Shoe(user_id=joy_user.id, brand="New Balance", model="Rebel v5", date="2026-02-20", size="us11/29cm", price=2300, orig_price=4280, mileage=102, expected_mileage=500, monthly_km=30, categories=["Speed"]),
                models.Shoe(user_id=joy_user.id, brand="Adidas", model="Boston 12", date="2026-04-21", size="us11.5/29.5cm", price=1680, orig_price=4290, mileage=61, expected_mileage=800, monthly_km=30, categories=["Tempo"]),
                models.Shoe(user_id=joy_user.id, brand="PUMA", model="Nitro Elite 3", date="2026-06-25", size="us11.5/29.5cm", price=3310, orig_price=5980, mileage=0, expected_mileage=500, monthly_km=20, categories=["Race"]),
                models.Shoe(user_id=joy_user.id, brand="Asics", model="Gel-Excite 8", date="2024-01-05", size="us11/29cm", price=1780, orig_price=2280, mileage=625, expected_mileage=600, monthly_km=0, is_retired=True, categories=["Daily"]),
                models.Shoe(user_id=joy_user.id, brand="FILA", model="Bon Voyage", date="2025-08-10", size="us11/29cm", price=2200, orig_price=2880, mileage=418, expected_mileage=400, monthly_km=0, is_retired=True, categories=["Daily"]),
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
        user_table = cast(Table, models.User.__table__)
        Base.metadata.create_all(bind=engine, tables=[user_table])

        migration_password = os.environ.get("MIGRATION_PASSWORD")
        if not migration_password:
            # Don't crash the app — log warning and skip migration.
            # Admin can run migration manually later via CLI.
            logger.warning(
                "MIGRATION_PASSWORD not set — skipping legacy schema migration. "
                "Existing shoes will remain unassigned until migration is run manually."
            )
        else:
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

    # Incremental migration for SQLite databases created before shoe categories
    # were changed from a single string to a JSON array of multiple purposes.
    # create_all() does not alter existing tables, so we need ALTER TABLE here.
    shoe_columns = {column["name"] for column in inspect(engine).get_columns("shoes")}
    with engine.begin() as conn:
        if "categories" not in shoe_columns:
            if "category" in shoe_columns:
                # Legacy DB: migrate single-string category → JSON array, then drop old column
                conn.execute(text("ALTER TABLE shoes ADD COLUMN categories TEXT NOT NULL DEFAULT '[]'"))
                conn.execute(text("UPDATE shoes SET categories = json_array(category) WHERE category IS NOT NULL AND category != ''"))
                conn.execute(text("ALTER TABLE shoes DROP COLUMN category"))
            else:
                # Table exists but has no category column at all — add the new one
                conn.execute(text("ALTER TABLE shoes ADD COLUMN categories TEXT NOT NULL DEFAULT '[]'"))
        # Other was a temporary category; remove it from any JSON arrays.
        # Use a compatible approach: find ids with 'Other' and update individually.
        # This avoids "UPDATE ... FROM json_each" which requires SQLite 3.38+.
        # Use `shoes.id` (our primary key) to avoid ambiguous column in join.
        rows_with_other = conn.execute(text("""
            SELECT shoes.id FROM shoes,
            json_each(categories)
            WHERE json_each.value = 'Other'
        """)).fetchall()
        for (sid,) in rows_with_other:
            conn.execute(text("""
                UPDATE shoes
                SET categories = json_remove(categories,
                    (SELECT '$[' || key || ']'
                     FROM json_each(categories)
                     WHERE value = 'Other'
                     LIMIT 1))
                WHERE id = :sid
            """), {"sid": sid})

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
frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
frontend_dir.mkdir(exist_ok=True)


# index.html 內含 inline JS，必須用 no-cache 讓瀏覽器每次都向伺服器
# 驗證（FileResponse 內建 ETag/Last-Modified，未變更會回 304 很省），
# 否則使用者會一直卡在舊版前端。
def _index_response():
    return FileResponse(
        frontend_dir / "index.html",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc):
    """Return index.html for 404s so SPA-style routing works,
    but return proper JSON for API errors (4xx/5xx)."""
    if exc.status_code == 404:
        path = request.url.path
        if path.startswith(("/api/", "/docs", "/openapi.json")):
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
    username = payload.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username cannot be empty")
    if len(username) > 50:
        raise HTTPException(status_code=400, detail="Username must be 50 characters or fewer")
    if db.query(models.User).filter(models.User.username == username).first():
        raise HTTPException(status_code=400, detail="Username already registered")
    user = models.User(
        username=username,
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
        models.Shoe.is_retired.is_(False),
        models.Shoe.user_id == current_user.id,
    ).all()


@app.get("/api/shoes/retired", response_model=list[schemas.ShoeOut])
def list_retired(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return db.query(models.Shoe).filter(
        models.Shoe.is_retired.is_(True),
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
    new_km = update_data.get("km", entry.km)
    if new_km < 0:
        raise HTTPException(status_code=400, detail="Km must be non-negative")

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


# ── Export Routes ─────────────────────────────────────────────────
def _generate_shoe_rows(shoes: list[models.Shoe], include_retired_status: bool = True):
    """Generate CSV rows for shoes with all fields."""
    for s in shoes:
        status = "已退役" if s.is_retired else "使用中"
        discount = round(s.price / s.orig_price * 100, 2) if s.orig_price > 0 else 0
        cost_per_km = round(s.price / s.mileage, 2) if s.mileage > 0 else 0
        expected_cost = round(s.price / s.expected_mileage, 2) if s.expected_mileage > 0 else 0
        life_pct = round(s.mileage / s.expected_mileage * 100, 2) if s.expected_mileage > 0 else 0

        row = {
            "品牌": s.brand,
            "鞋款": s.model,
            "購買日期": s.date,
            "尺寸": s.size,
            "買價": int(s.price),
            "原價": int(s.orig_price),
            "折數(%)": discount,
            "跑鞋里程(km)": s.mileage,
            "預期里程(km)": s.expected_mileage,
            "每km成本": cost_per_km,
            "預期每km成本": expected_cost,
            "生命進度(%)": life_pct,
            "月跑量(km)": s.monthly_km,
            "類別": ", ".join(s.categories) if s.categories else "",
        }
        if include_retired_status:
            row["狀態"] = status
        yield row


def _get_export_filename(format: str, mode: str) -> str:
    """Generate export filename with timestamp."""
    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    return f"running_shoes_{mode}_{timestamp}.{format}"


@app.get("/api/export")
def export_shoes(
    format: str = Query("xlsx", pattern="^(csv|xlsx)$"),
    mode: str = Query("active", pattern="^(all|active|retired)$"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """匯出跑鞋資料為 CSV 或 XLSX。

    - format: csv 或 xlsx (預設 xlsx)
    - mode: all(全部) | active(現役) | retired(退役) (預設 active)
    """
    # 查詢鞋款
    query = db.query(models.Shoe).filter(models.Shoe.user_id == current_user.id)
    if mode == "active":
        query = query.filter(models.Shoe.is_retired == False)  # noqa: E712
    elif mode == "retired":
        query = query.filter(models.Shoe.is_retired == True)  # noqa: E712
    # mode == "all" 不加額外過濾
    shoes = query.order_by(models.Shoe.is_retired, models.Shoe.date.desc()).all()

    if not shoes:
        raise HTTPException(status_code=404, detail="沒有可匯出的跑鞋資料")

    include_status = mode != "retired"  # 退役模式不需要狀態欄（全是已退役）
    rows = list(_generate_shoe_rows(shoes, include_retired_status=include_status))

    if format == "csv":
        # 生成 CSV
        import csv
        import io
        csv_output = io.StringIO()
        if rows:
            writer = csv.DictWriter(csv_output, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

        return StreamingResponse(
            io.BytesIO(csv_output.getvalue().encode("utf-8-sig")),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{_get_export_filename("csv", mode)}"'
            },
        )

    elif format == "xlsx":
        # 生成 XLSX (需要 openpyxl)
        import io
        try:
            import openpyxl
            from openpyxl.styles import Alignment, Font, PatternFill
            from openpyxl.utils import get_column_letter
        except ImportError as exc:
            raise HTTPException(
                status_code=500,
                detail="伺服器缺少 openpyxl 套件，無法匯出 XLSX",
            ) from exc

        wb = openpyxl.Workbook()
        ws = wb.active
        if ws is None:
            raise RuntimeError("openpyxl did not create an active worksheet")
        ws.title = "跑鞋資料"

        if rows:
            headers = list(rows[0].keys())
            # 寫入標題列
            header_font = Font(bold=True, color="FFFFFF")
            header_fill = PatternFill(start_color="3B82F6", end_color="3B82F6", fill_type="solid")
            header_alignment = Alignment(horizontal="center")

            for col_idx, header in enumerate(headers, 1):
                cell = ws.cell(row=1, column=col_idx, value=header)
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = header_alignment

            # 寫入資料列
            for row_idx, row in enumerate(rows, 2):
                for col_idx, header in enumerate(headers, 1):
                    ws.cell(row=row_idx, column=col_idx, value=row[header])

            # 自動調整欄寬
            for col_idx in range(1, len(headers) + 1):
                ws.column_dimensions[get_column_letter(col_idx)].width = 18

        xlsx_output = io.BytesIO()
        wb.save(xlsx_output)
        xlsx_output.seek(0)

        return StreamingResponse(
            xlsx_output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{_get_export_filename("xlsx", mode)}"'
            },
        )


# ── Spending Routes ────────────────────────────────────────────
@app.get("/api/spending/monthly")
def monthly_spending(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """回傳每月鞋款支出統計（依購買日期 grouped）。"""
    shoes = db.query(models.Shoe).filter(
        models.Shoe.user_id == current_user.id,
    ).all()

    buckets: dict[tuple[int, int], dict] = {}
    for s in shoes:
        if not s.date:
            continue
        try:
            year = int(s.date[:4])
            month = int(s.date[5:7])
        except (ValueError, IndexError):
            continue
        key = (year, month)
        if key not in buckets:
            buckets[key] = {"year": year, "month": month, "total_paid": 0.0, "total_orig": 0.0}
        buckets[key]["total_paid"] += s.price
        buckets[key]["total_orig"] += s.orig_price or 0

    result = sorted(buckets.values(), key=lambda x: (x["year"], x["month"]))
    return result


# ── Agent / Chat Routes ────────────────────────────────────────
@app.get("/api/agent/providers")
def list_agent_providers():
    """回傳 provider/model 清單（含 key 是否已設定）。"""
    return llm.list_providers()


@app.post("/api/agent/models/refresh")
def refresh_agent_models(
    current_user: models.User = Depends(get_current_user),
):
    """強制刷新 OpenRouter 免費模型快取，回傳更新後的 provider/model 清單。"""
    return llm.list_providers(force=True)


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
