import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts import offsite_backup
from scripts.database_backup import create_backup, drill_backup, logical_summary
from unit_tests.test_database_backup import make_database, usernames


def remote_fixture(tmp_path, monkeypatch, failure=None):
    source = tmp_path / "source.db"
    make_database(source, "PrivateExampleUser")
    snapshot = create_backup(source, tmp_path / "remote")
    remote = offsite_backup.REMOTE_DIRECTORY + "/" + snapshot.name
    calls = []
    monkeypatch.setattr(offsite_backup.shutil, "which", lambda name: "/usr/bin/flyctl")

    def command(arguments, *, stage):
        calls.append((arguments, stage))
        if failure == stage:
            raise RuntimeError("simulated CLI failure")
        if stage == "snapshot":
            path = "/data/shoes.db" if failure == "unsafe_path" else remote
            return f"Backup created and verified: {path}\n"
        destination = Path(arguments[5])
        original = snapshot.with_suffix(".db.sha256") if arguments[4].endswith(".sha256") else snapshot
        if failure == "missing_checksum" and destination.suffix == ".sha256":
            return ""
        shutil.copyfile(original, destination)
        if failure == "tampered" and destination.suffix == ".db":
            with destination.open("ab") as file:
                file.write(b"tamper")
        if failure == "malformed_checksum" and destination.suffix == ".sha256":
            destination.write_text("not a checksum", encoding="ascii")
        return "downloaded\n"

    monkeypatch.setattr(offsite_backup, "_fly_command", command)
    return source, snapshot, calls


def test_offsite_pull_publishes_only_verified_restore_drilled_private_copy(tmp_path, monkeypatch):
    source, snapshot, calls = remote_fixture(tmp_path, monkeypatch)
    output = tmp_path / "outside-fly"
    result = offsite_backup.pull_backup("running-shoes", output, machine="d8917edb352038")
    manifest = json.loads((result / "manifest.json").read_text())
    assert manifest["restore_drill"] == "passed"
    assert manifest["logical_sha256"] == logical_summary(source)["logical_sha256"]
    assert usernames(result / snapshot.name) == ["PrivateExampleUser"]
    assert "PrivateExampleUser" not in json.dumps(manifest)
    assert "not-a-real-hash" not in json.dumps(manifest)
    assert len(calls) == 3
    assert all("--machine" in arguments for arguments, _ in calls)
    assert not list(output.glob(".offsite-staging-*"))
    if os.name != "nt":
        assert result.stat().st_mode & 0o777 == 0o700
        assert all(path.stat().st_mode & 0o777 == 0o600 for path in result.iterdir())


@pytest.mark.parametrize("failure", [
    "snapshot", "download", "missing_checksum", "malformed_checksum", "tampered", "unsafe_path",
])
def test_failed_offsite_pull_never_publishes_or_removes_existing_backup(tmp_path, monkeypatch, failure):
    source, _, _ = remote_fixture(tmp_path, monkeypatch, failure)
    output = tmp_path / "outside-fly"
    output.mkdir()
    sentinel = output / "previous-backup.txt"
    sentinel.write_text("keep", encoding="utf-8")
    with pytest.raises((OSError, ValueError, RuntimeError)):
        offsite_backup.pull_backup("running-shoes", output)
    assert list(output.iterdir()) == [sentinel]
    assert usernames(source) == ["PrivateExampleUser"]


@pytest.mark.parametrize("app,machine", [("../bad", None), ("--bad", None), ("a;bad", None), ("ok", "not-a-machine")])
def test_offsite_rejects_unsafe_targets_before_commands(tmp_path, monkeypatch, app, machine):
    monkeypatch.setattr(offsite_backup, "_fly_command", lambda *args, **kwargs: pytest.fail("must not run CLI"))
    with pytest.raises(ValueError, match="invalid Fly"):
        offsite_backup.pull_backup(app, tmp_path / "output", machine=machine)


def test_offsite_refuses_a_git_checkout_destination(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(offsite_backup, "_fly_command", lambda *args, **kwargs: pytest.fail("must not run CLI"))
    with pytest.raises(ValueError, match="outside Git"):
        offsite_backup.pull_backup("running-shoes", tmp_path / "backups")


def test_cli_failure_does_not_echo_arbitrary_remote_output(monkeypatch):
    monkeypatch.setattr(offsite_backup.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(
        args[0], 1, "private-user-record", "private-credential-value"
    ))
    with pytest.raises(RuntimeError) as error:
        offsite_backup._fly_command(["flyctl"], stage="download")
    assert "private" not in str(error.value)


def test_drill_restores_all_rows_and_schema_only_in_temporary_directory(tmp_path):
    source = tmp_path / "source.db"
    make_database(source)
    backup = create_backup(source, tmp_path / "backups")
    result = drill_backup(backup)
    assert result["restore_drill"] == "passed"
    assert result["row_counts"]["users"] == 1
    assert result["schema_version"] == 0
    assert result["logical_sha256"] == logical_summary(source)["logical_sha256"]
    assert not (tmp_path / "restored.db").exists()
    assert usernames(source) == ["Joy"]


@pytest.mark.parametrize("damage", ["rows", "index"])
def test_drill_rejects_a_restore_that_loses_rows_or_schema(tmp_path, monkeypatch, damage):
    from scripts import database_backup

    source = tmp_path / "source.db"
    make_database(source)
    backup = create_backup(source, tmp_path / "backups")
    restore = database_backup.restore_backup

    def corrupt_restore(backup, destination, **kwargs):
        import sqlite3
        from contextlib import closing

        restore(backup, destination, **kwargs)
        # sqlite3's context manager only commits; close explicitly so Windows can
        # delete the drill's temporary directory.
        with closing(sqlite3.connect(destination)) as connection, connection:
            connection.execute("DELETE FROM users" if damage == "rows" else "DROP INDEX idx_runs_user_date")

    monkeypatch.setattr(database_backup, "restore_backup", corrupt_restore)
    with pytest.raises(ValueError, match="does not match"):
        drill_backup(backup)
    assert usernames(source) == ["Joy"]
