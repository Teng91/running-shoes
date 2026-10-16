"""Create, verify, retain, and safely restore Running Shoes SQLite backups."""

import argparse
import hashlib
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

REQUIRED_TABLES = {"users", "shoes", "runs", "monthly_mileages"}


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_backup(path: Path, *, check_checksum: bool = True) -> dict[str, object]:
    path = path.resolve()
    if not path.is_file():
        raise ValueError(f"backup does not exist: {path}")
    checksum_path = path.with_suffix(path.suffix + ".sha256")
    digest = _sha256(path)
    if check_checksum and checksum_path.exists():
        expected = checksum_path.read_text(encoding="ascii").split()[0]
        if digest != expected:
            raise ValueError("backup checksum does not match")

    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        integrity = connection.execute("PRAGMA quick_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            raise ValueError(f"SQLite integrity check failed: {integrity}")
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        missing = REQUIRED_TABLES - tables
        if missing:
            raise ValueError(f"backup is missing required tables: {', '.join(sorted(missing))}")
    finally:
        connection.close()
    return {"path": str(path), "sha256": digest, "tables": sorted(tables)}


def _sqlite_snapshot(source: Path, destination: Path) -> None:
    source_connection = sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True)
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
    finally:
        destination_connection.close()
        source_connection.close()
    destination.chmod(0o600)


def create_backup(source: Path, output_dir: Path, *, keep: int = 14) -> Path:
    source = source.resolve()
    output_dir = output_dir.resolve()
    if not source.is_file():
        raise ValueError(f"source database does not exist: {source}")
    if keep < 1:
        raise ValueError("keep must be at least 1")
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"shoes-{_timestamp()}.db"
    _sqlite_snapshot(source, destination)
    metadata = verify_backup(destination, check_checksum=False)
    checksum_path = destination.with_suffix(destination.suffix + ".sha256")
    checksum_path.write_text(f"{metadata['sha256']}  {destination.name}\n", encoding="ascii")
    checksum_path.chmod(0o600)

    backups = sorted(output_dir.glob("shoes-*.db"), key=lambda path: path.stat().st_mtime)
    for stale in backups[:-keep]:
        if stale.resolve() == source:
            continue
        stale.unlink()
        stale.with_suffix(stale.suffix + ".sha256").unlink(missing_ok=True)
    return destination


def restore_backup(backup: Path, destination: Path, *, confirmation: str) -> Path | None:
    if confirmation != "RESTORE":
        raise ValueError("restore requires --confirm RESTORE")
    backup = backup.resolve()
    destination = destination.resolve()
    verify_backup(backup)
    destination.parent.mkdir(parents=True, exist_ok=True)

    safety_backup: Path | None = None
    if destination.exists():
        safety_backup = destination.with_name(
            f"{destination.stem}.pre-restore-{_timestamp()}{destination.suffix}"
        )
        _sqlite_snapshot(destination, safety_backup)
        verify_backup(safety_backup, check_checksum=False)

    temporary = destination.with_name(f".{destination.name}.restore-{os.getpid()}")
    temporary.unlink(missing_ok=True)
    try:
        _sqlite_snapshot(backup, temporary)
        verify_backup(temporary, check_checksum=False)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return safety_backup


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create")
    create.add_argument("--source", type=Path, required=True)
    create.add_argument("--output-dir", type=Path, required=True)
    create.add_argument("--keep", type=int, default=14)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--backup", type=Path, required=True)

    restore = subparsers.add_parser("restore")
    restore.add_argument("--backup", type=Path, required=True)
    restore.add_argument("--destination", type=Path, required=True)
    restore.add_argument("--confirm", required=True)

    args = parser.parse_args()
    if args.command == "create":
        path = create_backup(args.source, args.output_dir, keep=args.keep)
        print(f"Backup created and verified: {path}")
    elif args.command == "verify":
        metadata = verify_backup(args.backup)
        print(f"Backup verified: {metadata['path']} sha256={metadata['sha256']}")
    else:
        safety = restore_backup(args.backup, args.destination, confirmation=args.confirm)
        print(f"Backup restored to: {args.destination.resolve()}")
        if safety:
            print(f"Pre-restore safety snapshot: {safety}")


if __name__ == "__main__":
    main()

