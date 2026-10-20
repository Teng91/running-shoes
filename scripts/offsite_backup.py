"""Pull a Fly SQLite snapshot to private off-volume storage and prove restorability.

No cloud SDK, uploaded credential, production restore, or automatic local retention.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.database_backup import drill_backup, verify_backup

REMOTE_DIRECTORY = "/data/backups/offsite"
SNAPSHOT_NAME = re.compile(r"shoes-\d{8}T\d{12}Z\.db")


def _fly_command(arguments: list[str], *, stage: str) -> str:
    try:
        result = subprocess.run(
            arguments, capture_output=True, text=True, input="", timeout=300, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Fly {stage} failed; check CLI authentication and machine availability") from exc
    if result.returncode:
        # Never forward arbitrary remote output or credentials into logs/manifests.
        raise RuntimeError(f"Fly {stage} failed; check CLI authentication and machine availability")
    return result.stdout


def pull_backup(app: str, output_dir: Path, *, machine: str | None = None) -> Path:
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", app):
        raise ValueError("invalid Fly app name")
    if machine is not None and not re.fullmatch(r"[a-f0-9]{14,16}", machine):
        raise ValueError("invalid Fly machine ID")
    output_dir = output_dir.expanduser().resolve()
    if any((parent / ".git").exists() or parent.name == ".git" for parent in (output_dir, *output_dir.parents)):
        raise ValueError("offsite backups must be stored outside Git repositories")
    executable = shutil.which("flyctl") or shutil.which("fly")
    if not executable:
        raise ValueError("Fly CLI is required; install and authenticate it before pulling backups")
    flags = ["-a", app] + (["--machine", machine] if machine else [])
    command = (
        "python scripts/database_backup.py create --source /data/shoes.db "
        f"--output-dir {REMOTE_DIRECTORY} --keep 14"
    )
    output = _fly_command([executable, "ssh", "console", *flags, "-C", command], stage="snapshot")
    prefix = "Backup created and verified: "
    paths = [line[len(prefix):].strip() for line in output.splitlines() if line.startswith(prefix)]
    if len(paths) != 1:
        raise ValueError("Fly did not return one verified snapshot path")
    remote_path = paths[0]
    name = remote_path.removeprefix(REMOTE_DIRECTORY + "/")
    if not SNAPSHOT_NAME.fullmatch(name) or remote_path != f"{REMOTE_DIRECTORY}/{name}":
        raise ValueError("unexpected remote snapshot path")

    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    final_dir = output_dir / f"{app}-{name.removesuffix('.db')}-{uuid.uuid4().hex[:8]}"
    # Staging stays on the output filesystem so publication is one directory rename.
    with tempfile.TemporaryDirectory(prefix=".offsite-staging-", dir=output_dir) as directory:
        staging = Path(directory)
        snapshot = staging / name
        for suffix in ("", ".sha256"):
            local = staging / (name + suffix)
            _fly_command(
                [executable, "ssh", "sftp", "get", remote_path + suffix, str(local), *flags],
                stage="download",
            )
            local.chmod(0o600)
        sidecar = snapshot.with_suffix(".db.sha256")
        if not re.fullmatch(r"[a-fA-F0-9]{64}\s+" + re.escape(name) + r"\s*", sidecar.read_text(encoding="ascii")):
            raise ValueError("snapshot checksum is missing or malformed")
        metadata = verify_backup(snapshot)
        result = drill_backup(snapshot)
        manifest = {
            "format_version": 1,
            "app": app,
            "snapshot": name,
            "sha256": metadata["sha256"],
            "created_at": datetime.now(UTC).isoformat(),
            "restore_drill": result["restore_drill"],
            "schema_version": result["schema_version"],
            "logical_sha256": result["logical_sha256"],
            "row_counts": result["row_counts"],
        }
        manifest_path = staging / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest_path.chmod(0o600)
        staging.rename(final_dir)
        # TemporaryDirectory's old path no longer exists; it never cleans the published backup.
    if os.name != "nt":
        final_dir.chmod(0o700)
    return final_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", default="running-shoes")
    parser.add_argument("--machine", help="required when selecting among multiple Fly machines")
    parser.add_argument("--output-dir", type=Path, required=True, help="private storage outside Fly and Git")
    args = parser.parse_args()
    try:
        path = pull_backup(args.app, args.output_dir, machine=args.machine)
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"Offsite backup failed: {exc}", file=sys.stderr)
        return 1
    print(f"Offsite backup verified and isolated restore drill passed: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
