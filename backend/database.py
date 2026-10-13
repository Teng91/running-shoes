import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# 本機開發預設存專案根目錄，Docker 部署透過 DB_DIR=/data 環境變數覆蓋
_DEFAULT_DB_DIR = str(Path(__file__).resolve().parent.parent)
DATABASE_DIR = os.environ.get("DB_DIR", _DEFAULT_DB_DIR)
os.makedirs(DATABASE_DIR, exist_ok=True)
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DATABASE_DIR}/shoes.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30},
)


def configure_sqlite_connection(dbapi_connection) -> None:
    """Apply integrity and concurrency pragmas to one SQLite connection."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        # WAL lets readers (including AI/report snapshots) coexist with
        # ordinary writes instead of producing avoidable "database locked"
        # errors.  NORMAL is the recommended durability/performance pair
        # for WAL; committed data remains crash-safe in the WAL file.
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
    """Enforce declared relationships instead of relying only on API checks."""
    if DATABASE_URL.startswith("sqlite"):
        configure_sqlite_connection(dbapi_connection)


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
