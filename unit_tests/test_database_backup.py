import sqlite3
import subprocess
import sys

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


def test_backup_retention_keeps_newest_when_snapshots_share_an_mtime(tmp_path, monkeypatch):
    """Back-to-back snapshots in one filesystem clock tick must still keep the newest."""
    import os

    from scripts import database_backup

    source = tmp_path / "source.db"
    make_database(source)
    stamps = iter(f"20261109T1000000000{index:02d}Z" for index in range(1, 4))
    monkeypatch.setattr(database_backup, "_timestamp", lambda: next(stamps))
    snapshot = database_backup._sqlite_snapshot

    def snapshot_in_same_tick(source_path, destination):
        snapshot(source_path, destination)
        os.utime(destination, ns=(1_000_000_000, 1_000_000_000))

    monkeypatch.setattr(database_backup, "_sqlite_snapshot", snapshot_in_same_tick)
    backup_dir = tmp_path / "backups"
    oldest = create_backup(source, backup_dir, keep=3)
    middle = create_backup(source, backup_dir, keep=3)
    newest = create_backup(source, backup_dir, keep=2)

    assert sorted(backup_dir.glob("shoes-*.db")) == [middle, newest]
    assert not oldest.with_suffix(".db.sha256").exists()


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


def test_restore_recovers_crashed_wal_without_replaying_old_data(tmp_path):
    source, destination = tmp_path / "source.db", tmp_path / "destination.db"
    make_database(source, "BackupUser")
    make_database(destination, "CurrentUser")
    backup = create_backup(source, tmp_path / "backups")
    subprocess.run(
        [sys.executable, "-c", """
import os, sqlite3, sys
connection = sqlite3.connect(sys.argv[1])
connection.execute('PRAGMA journal_mode=WAL')
connection.execute("UPDATE users SET username='CommittedBeforeCrash'")
connection.commit()
os._exit(0)
""", str(destination)],
        check=True,
    )
    assert destination.with_name(destination.name + "-wal").exists()

    safety = restore_backup(backup, destination, confirmation="RESTORE")

    assert usernames(destination) == ["BackupUser"]
    assert usernames(destination) == ["BackupUser"]  # Reopen must not replay old WAL.
    assert safety is not None
    assert usernames(safety) == ["CommittedBeforeCrash"]


@pytest.mark.parametrize("journal_mode", ["WAL", "DELETE"])
def test_restore_refuses_busy_database_and_preserves_data(tmp_path, journal_mode):
    source, destination = tmp_path / "source.db", tmp_path / "destination.db"
    make_database(source, "BackupUser")
    make_database(destination, "CurrentUser")
    backup = create_backup(source, tmp_path / "backups")
    active = sqlite3.connect(destination)
    try:
        active.execute(f"PRAGMA journal_mode={journal_mode}")
        active.execute("BEGIN IMMEDIATE")
        active.execute("UPDATE users SET username='Uncommitted'")
        with pytest.raises(ValueError, match=r"busy.*stop all"):
            restore_backup(backup, destination, confirmation="RESTORE")
        assert active.execute("SELECT username FROM users").fetchone()[0] == "Uncommitted"
        active.rollback()
    finally:
        active.close()
    assert usernames(destination) == ["CurrentUser"]


def test_restore_new_destination_and_reject_same_source(tmp_path):
    source, destination = tmp_path / "source.db", tmp_path / "new.db"
    make_database(source, "BackupUser")
    backup = create_backup(source, tmp_path / "backups")
    assert restore_backup(backup, destination, confirmation="RESTORE") is None
    assert usernames(destination) == ["BackupUser"]
    with pytest.raises(ValueError, match="different files"):
        restore_backup(backup, backup, confirmation="RESTORE")

