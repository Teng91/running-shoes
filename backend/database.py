import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# 本機開發預設存專案根目錄，Docker 部署透過 DB_DIR=/data 環境變數覆蓋
_DEFAULT_DB_DIR = str(Path(__file__).resolve().parent.parent)
DATABASE_DIR = os.environ.get("DB_DIR", _DEFAULT_DB_DIR)
os.makedirs(DATABASE_DIR, exist_ok=True)
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DATABASE_DIR}/shoes.db")

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
