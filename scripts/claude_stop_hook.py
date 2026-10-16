"""Run deterministic repository checks before Claude Code finishes a changed turn.

The hook is local-only: it reads Claude's hook event from stdin, runs the same
checks as the repository harness, and returns a blocking JSON decision when a
check fails. No prompt, diff, source file, or test output is sent to a service.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE_ROOT = ROOT / ".claude" / ".hook-cache"
TEST_SECRET_KEY = "test-only-harness-secret-key-not-for-production"
MAX_REASON_CHARS = 8_000

LAYOUT_FILES = {
    "frontend/app.js",
    "frontend/app-runs.js",
    "frontend/app-shoes.js",
    "frontend/index.html",
    "frontend/styles.css",
    "unit_tests/frontend_layout.cjs",
}


@dataclass(frozen=True)
class Check:
    label: str
    command: tuple[str, ...]


def run_git(*args: str) -> bytes:
    result = subprocess.run(
        ("git", *args),
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout


def changed_files() -> set[str]:
    tracked = run_git("diff", "--name-only", "-z", "HEAD")
    untracked = run_git("ls-files", "--others", "--exclude-standard", "-z")
    return {
        item.decode("utf-8", errors="surrogateescape")
        for item in (tracked + untracked).split(b"\0")
        if item
    }


def worktree_fingerprint(files: set[str]) -> str:
    digest = hashlib.sha256()
    digest.update(run_git("diff", "--binary", "HEAD"))
    tracked = set(
        item.decode("utf-8", errors="surrogateescape")
        for item in run_git("ls-files", "-z").split(b"\0")
        if item
    )
    for relative in sorted(files - tracked):
        digest.update(relative.encode("utf-8", errors="surrogateescape"))
        path = ROOT / relative
        if path.is_symlink():
            digest.update(os.readlink(path).encode("utf-8", errors="surrogateescape"))
        elif path.is_file():
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    digest.update(chunk)
    return digest.hexdigest()


def project_python() -> str:
    candidates = (
        ROOT / "venv" / "Scripts" / "python.exe",
        ROOT / "venv" / "bin" / "python",
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return sys.executable


def verification_checks() -> list[Check]:
    python = project_python()
    return [
        Check("Ruff", (python, "-m", "ruff", "check", "backend", "scripts", "unit_tests")),
        Check("mypy", (python, "-m", "mypy", "backend")),
        Check("Architecture constraints", (python, "scripts/check_architecture.py")),
        Check("Secret scan", (python, "scripts/check_secrets.py")),
        Check("README consistency", (python, "scripts/check_docs.py")),
        Check(
            "Python tests",
            (
                python,
                "-m",
                "pytest",
                "-q",
                "--cov=backend",
                "--cov-branch",
                "--cov-fail-under=92",
                "--cov-report=term-missing:skip-covered",
            ),
        ),
        Check("Frontend regression tests", ("node", "--test", "unit_tests/frontend_regressions.cjs")),
    ]


def needs_layout_check(files: set[str]) -> bool:
    return bool(files & LAYOUT_FILES)


def layout_dependencies_available() -> bool:
    if shutil.which("node") is None:
        return False
    script = (
        "const fs=require('fs'),p=require('playwright');"
        "process.exit(fs.existsSync(p.chromium.executablePath())"
        "&&fs.existsSync(p.webkit.executablePath())?0:1)"
    )
    result = subprocess.run(
        ("node", "-e", script),
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def run_check(check: Check) -> tuple[bool, str]:
    environment = os.environ.copy()
    environment["SECRET_KEY"] = TEST_SECRET_KEY
    try:
        result = subprocess.run(
            check.command,
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=240,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, f"{check.label} could not run: {error}"
    output = (result.stdout + result.stderr).strip()
    if result.returncode:
        detail = output[-MAX_REASON_CHARS:] if output else "no command output"
        return False, f"{check.label} failed (exit {result.returncode}):\n{detail}"
    return True, output


def run_verification(files: set[str]) -> tuple[bool, str]:
    for check in verification_checks():
        passed, detail = run_check(check)
        if not passed:
            return False, detail
    if needs_layout_check(files) and layout_dependencies_available():
        passed, detail = run_check(Check("Frontend layout tests", ("node", "unit_tests/frontend_layout.cjs")))
        if not passed:
            return False, detail
    return True, ""


def cache_path(session_id: str) -> Path:
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", session_id)[:120] or "unknown-session"
    return CACHE_ROOT / f"{safe_id}.json"


def load_cache(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_cache(path: Path, fingerprint: str, passed: bool, reason: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {"fingerprint": fingerprint, "passed": passed, "reason": reason},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError:
        # Cache failures must not change the verification result.
        return


def blocking_payload(reason: str) -> str:
    message = (
        "Repository verification failed. Fix the failure and run the relevant "
        f"harness command before finishing.\n\n{reason[:MAX_REASON_CHARS]}"
    )
    return json.dumps({"decision": "block", "reason": message}, ensure_ascii=False)


def read_event() -> dict[str, object]:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"Claude Stop hook received invalid JSON: {error}") from error
    if not isinstance(event, dict):
        raise RuntimeError("Claude Stop hook input must be a JSON object")
    return event


def main() -> int:
    try:
        event = read_event()
        files = changed_files()
        if not files:
            return 0
        fingerprint = worktree_fingerprint(files)
        path = cache_path(str(event.get("session_id") or "unknown-session"))
        cached = load_cache(path)
        if cached.get("fingerprint") == fingerprint:
            if cached.get("passed") is True:
                return 0
            reason = str(cached.get("reason") or "Previous verification failed without details.")
            print(blocking_payload(reason))
            return 0
        passed, reason = run_verification(files)
        save_cache(path, fingerprint, passed, reason)
        if not passed:
            print(blocking_payload(reason))
    except RuntimeError as error:
        print(blocking_payload(str(error)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
