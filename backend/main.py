from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from backend.database import engine, Base, get_db
from backend import models, schemas

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Running Shoes API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    db.commit()
    db.refresh(shoe)
    return shoe


@app.put("/api/shoes/{shoe_id}", response_model=schemas.ShoeOut)
def update_shoe(shoe_id: int, payload: schemas.ShoeUpdate, db: Session = Depends(get_db)):
    shoe = db.query(models.Shoe).filter(models.Shoe.id == shoe_id).first()
    if not shoe:
        raise HTTPException(status_code=404, detail="Shoe not found")
    for k, v in payload.model_dump().items():
        setattr(shoe, k, v)
    db.commit()
    db.refresh(shoe)
    return shoe


@app.delete("/api/shoes/{shoe_id}")
def delete_shoe(shoe_id: int, db: Session = Depends(get_db)):
    shoe = db.query(models.Shoe).filter(models.Shoe.id == shoe_id).first()
    if not shoe:
        raise HTTPException(status_code=404, detail="Shoe not found")
    db.delete(shoe)
    db.commit()
    return {"ok": True}
