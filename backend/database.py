from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from backend.settings import settings

DATABASE_DIR = str(settings.database_dir)
settings.database_dir.mkdir(parents=True, exist_ok=True)
DATABASE_URL = settings.database_url

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
