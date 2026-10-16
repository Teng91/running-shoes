import sqlite3

import pytest
from sqlalchemy import create_engine

from backend.database import Base
from scripts.database_backup import create_backup, restore_backup, verify_backup


def make_database(path, username="Joy"):
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO users (username, hashed_password, token_version, created_at) "
            "VALUES (?, ?, 0, CURRENT_TIMESTAMP)",
            (username, "not-a-real-hash"),
        )
    engine.dispose()


def usernames(path):
    connection = sqlite3.connect(path)
    try:
        return [row[0] for row in connection.execute("SELECT username FROM users")]
    finally:
        connection.close()


def test_create_and_verify_backup_with_checksum(tmp_path):
    source = tmp_path / "source.db"
    make_database(source)
    backup = create_backup(source, tmp_path / "backups", keep=2)

    metadata = verify_backup(backup)

    assert metadata["sha256"]
    assert backup.with_suffix(".db.sha256").is_file()
    assert usernames(backup) == ["Joy"]


def test_backup_retention_removes_only_old_managed_snapshots(tmp_path):
    source = tmp_path / "source.db"
    make_database(source)
    backup_dir = tmp_path / "backups"
    create_backup(source, backup_dir, keep=1)
    newest = create_backup(source, backup_dir, keep=1)

    assert list(backup_dir.glob("shoes-*.db")) == [newest]
    assert source.exists()


def test_restore_requires_confirmation_and_preserves_previous_database(tmp_path):
    source = tmp_path / "source.db"
    destination = tmp_path / "destination.db"
    make_database(source, "BackupUser")
    make_database(destination, "CurrentUser")
    backup = create_backup(source, tmp_path / "backups")

    with pytest.raises(ValueError, match="RESTORE"):
        restore_backup(backup, destination, confirmation="no")

    safety = restore_backup(backup, destination, confirmation="RESTORE")

    assert usernames(destination) == ["BackupUser"]
    assert safety is not None
    assert usernames(safety) == ["CurrentUser"]


def test_verify_rejects_a_corrupt_database(tmp_path):
    broken = tmp_path / "broken.db"
    broken.write_bytes(b"not sqlite")

    with pytest.raises((ValueError, sqlite3.DatabaseError)):
        verify_backup(broken)

