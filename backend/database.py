"""ORM base, SQLite connection policy and engine construction.

Importing this module has no side effects: the composition root (``create_app``)
builds the engine from injected settings, and request sessions come from
``backend.dependencies.get_db``.
"""

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase


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


def create_database_engine(database_url: str) -> Engine:
    """Create an engine; SQLite connections enforce declared relationships."""
    engine = create_engine(database_url, connect_args={"check_same_thread": False, "timeout": 30})
    if database_url.startswith("sqlite"):
        event.listen(engine, "connect", lambda connection, _record: configure_sqlite_connection(connection))
    return engine


class Base(DeclarativeBase):
    pass
