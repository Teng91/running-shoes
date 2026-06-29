from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from backend.database import engine, Base, SessionLocal, get_db
from backend import models, schemas


# ── Seed default data if DB is empty ──────────────────────────
def seed_default_data():
    db = SessionLocal()
    try:
        if db.query(models.Shoe).count() == 0:
            defaults = [
                models.Shoe(brand="Mizuno", model="Wave Sky 7", date="2024-09-15", size="us13/31cm", price=2390, orig_price=4780, mileage=540, expected_mileage=800, monthly_km=60),
                models.Shoe(brand="Mizuno", model="Wave Rider 29", date="2025-12-12", size="us12/30cm", price=2505, orig_price=3980, mileage=293, expected_mileage=800, monthly_km=60),
                models.Shoe(brand="Mizuno", model="Wave Sky 9", date="2025-12-30", size="us13/31cm", price=3080, orig_price=4980, mileage=125, expected_mileage=800, monthly_km=60),
                models.Shoe(brand="New Balance", model="Rebel v5", date="2026-02-20", size="us11/29cm", price=2300, orig_price=4280, mileage=102, expected_mileage=500, monthly_km=30),
                models.Shoe(brand="Adidas", model="Boston 12", date="2026-04-21", size="us11.5/29.5cm", price=1680, orig_price=4290, mileage=61, expected_mileage=800, monthly_km=30),
                models.Shoe(brand="PUMA", model="Nitro Elite 3", date="2026-06-25", size="us11.5/29.5cm", price=3310, orig_price=5980, mileage=0, expected_mileage=500, monthly_km=20),
                models.Shoe(brand="Asics", model="Gel-Excite 8", date="2024-01-05", size="us11/29cm", price=1780, orig_price=2280, mileage=625, expected_mileage=600, monthly_km=0, is_retired=True),
                models.Shoe(brand="FILA", model="Bon Voyage", date="2025-08-10", size="us11/29cm", price=2200, orig_price=2880, mileage=418, expected_mileage=400, monthly_km=0, is_retired=True),
            ]
            db.add_all(defaults)
            db.commit()
    finally:
        db.close()


# ── Lifespan: create tables & seed on startup ─────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
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


@app.exception_handler(StarletteHTTPException)
async def not_found_handler(request, exc):
    """Return index.html for any 404 so SPA-style routing works,
    but still 404 for /api/* paths."""
    if exc.status_code == 404:
        path = request.url.path
        if path.startswith("/api/") or path.startswith("/docs") or path.startswith("/openapi.json"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        file = frontend_dir / path.lstrip("/")
        if file.is_file():
            return FileResponse(file)
        return FileResponse(frontend_dir / "index.html")
    raise exc


# ── API Routes ────────────────────────────────────────────────
@app.get("/api/shoes/active", response_model=list[schemas.ShoeOut])
def list_active(db: Session = Depends(get_db)):
    return db.query(models.Shoe).filter(models.Shoe.is_retired == False).all()


@app.get("/api/shoes/retired", response_model=list[schemas.ShoeOut])
def list_retired(db: Session = Depends(get_db)):
    return db.query(models.Shoe).filter(models.Shoe.is_retired == True).all()


@app.post("/api/shoes", response_model=schemas.ShoeOut)
def create_shoe(payload: schemas.ShoeCreate, db: Session = Depends(get_db)):
    shoe = models.Shoe(**payload.model_dump())
    db.add(shoe)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(shoe)
    return shoe


@app.put("/api/shoes/{shoe_id}", response_model=schemas.ShoeOut)
def update_shoe(shoe_id: int, payload: schemas.ShoeUpdate, db: Session = Depends(get_db)):
    shoe = db.query(models.Shoe).filter(models.Shoe.id == shoe_id).first()
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
def delete_shoe(shoe_id: int, db: Session = Depends(get_db)):
    shoe = db.query(models.Shoe).filter(models.Shoe.id == shoe_id).first()
    if not shoe:
        raise HTTPException(status_code=404, detail="Shoe not found")
    db.delete(shoe)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"ok": True}
