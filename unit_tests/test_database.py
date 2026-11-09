"""SQLite durability and concurrency configuration regressions."""

import sqlite3

from backend.database import configure_sqlite_connection


def test_sqlite_connections_enable_wal_foreign_keys_and_busy_timeout(tmp_path):
    connection = sqlite3.connect(tmp_path / "configured.db")
    try:
        configure_sqlite_connection(connection)
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 30_000
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 1
    finally:
        connection.close()


def test_engines_opened_inside_a_test_are_disposed_afterwards(tmp_path):
    """SPEC-047: test engines close their SQLite connections instead of leaking to the GC."""
    import pytest
    from sqlalchemy import create_engine, text

    from unit_tests.conftest import disposing_engines

    with disposing_engines() as engines:
        engine = create_engine(f"sqlite:///{tmp_path / 'leak.sqlite'}")
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            raw = connection.connection.dbapi_connection
        assert engine.pool.checkedin() == 1, "the connection is pooled, not closed"
    assert engines == [engine]
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        raw.execute("SELECT 1")
