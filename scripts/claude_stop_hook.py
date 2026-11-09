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
    "frontend/app-boot.js",
    "frontend/app-state.js",
    "frontend/app-api.js",
    "frontend/app-auth.js",
    "frontend/app-core.js",
    "frontend/app-dashboard.js",
    "frontend/app-exports.js",
    "frontend/app-goals.js",
    "frontend/app-charts.js",
    "frontend/app-shoe-charts.js",
    "frontend/app-monthly-charts.js",
    "frontend/app-spending.js",
    "frontend/app-runs.js",
    "frontend/app-strava.js",
    "frontend/app-run-insights.js",
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
        Check("Repository harness", (python, "scripts/task.py", "verify")),
    ]


def needs_layout_check(files: set[str]) -> bool:
    return bool(files & LAYOUT_FILES)


def layout_dependencies_available() -> bool:
    """True only when Chromium and WebKit can launch; missing host libraries skip the check."""
    if shutil.which("node") is None:
        return False
    try:
        result = subprocess.run(
            ("node", "scripts/browser_probe.cjs"),
            cwd=ROOT,
            capture_output=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
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
            timeout=540,  # verify takes ~4-5 min on Windows; keep below the 600 s hook limit
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
    # Claude sends UTF-8; on Windows sys.stdin decodes with the locale code page
    # (e.g. cp950), which mangles CJK/emoji text and can swallow JSON quotes.
    raw = getattr(sys.stdin, "buffer", None)
    try:
        event = json.loads(raw.read().decode("utf-8") if raw is not None else sys.stdin.read())
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
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
            # The agent already received this failure for the unchanged worktree; blocking
            # again would loop forever. A later stop re-runs verification, because failures
            # such as an unreachable package index can be transient.
            if event.get("stop_hook_active") is True:
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
