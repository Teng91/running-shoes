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
