"""Cross-platform repository task runner.

This module is the single source of truth for local development, coding-agent
verification, and CI. Invoke it with any Python 3.11+ launcher, for example
``python3 scripts/task.py <task>`` on Unix or ``py -3 scripts/task.py <task>``
on Windows.
"""

from __future__ import annotations

import argparse
import functools
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_ROOT = ROOT / "venv"
TEST_SECRET_KEY = "test-only-harness-secret-key-not-for-production"

PUBLIC_TASKS = (
    "setup",
    "test-fast",
    "frontend-test",
    "frontend-layout",
    "frontend-e2e",
    "frontend-pwa",
    "eval-agent",
    "audit-deps",
    "architecture-check",
    "security-check",
    "docs-check",
    "verify",
    "verify-all",
    "release-check",
    "diagnostics-generate",
    "diagnostics-verify",
)


class TaskError(RuntimeError):
    """Raised when a task cannot be completed."""


@dataclass(frozen=True)
class Command:
    label: str
    arguments: tuple[str, ...]
    needs_test_secret: bool = False
    environment: tuple[tuple[str, str], ...] = ()


def project_python() -> str:
    """Return the repository virtual-environment Python when it exists."""
    candidates = (
        VENV_ROOT / "Scripts" / "python.exe",
        VENV_ROOT / "bin" / "python",
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return sys.executable


def command_environment(command: Command) -> dict[str, str]:
    environment = os.environ.copy()
    if command.needs_test_secret:
        environment.setdefault("SECRET_KEY", TEST_SECRET_KEY)
    environment.update(command.environment)
    return environment


def run_checked(command: Command) -> None:
    """Run one command with streaming output and fail the parent task on error."""
    print(f"\n==> {command.label}", flush=True)
    try:
        result = subprocess.run(
            command.arguments,
            cwd=ROOT,
            env=command_environment(command),
            check=False,
        )
    except OSError as error:
        raise TaskError(f"{command.label} could not run: {error}") from error
    if result.returncode:
        raise TaskError(f"{command.label} failed with exit code {result.returncode}.")


def backend_test_command() -> Command:
    return Command(
        "Python tests with branch coverage",
        (
            project_python(),
            "-m",
            "pytest",
            "-q",
            "--cov=backend",
            "--cov-branch",
            "--cov-fail-under=92",
            "--cov-report=term-missing:skip-covered",
        ),
        needs_test_secret=True,
    )


def dependency_audit_commands() -> tuple[Command, ...]:
    """Known-vulnerability scans of the locked Python and npm dependencies.

    SPEC-089: the vendored Chart.js and marked are pinned as npm devDependencies at the
    vendored versions, so the npm audit (lockfile only, no install) covers them too.
    """
    return (
        Command(
            "Dependency vulnerability audit",
            (project_python(), "-m", "pip_audit", "--require-hashes", "-r", "requirements.txt"),
        ),
        Command(
            "npm dependency vulnerability audit",
            (shutil.which("npm") or "npm", "audit", "--package-lock-only", "--audit-level=moderate"),
        ),
    )


def verification_commands() -> tuple[Command, ...]:
    """Return the canonical cross-platform verification command sequence."""
    python = project_python()
    return (
        Command("Generated frontend assets", (python, "scripts/build_frontend.py", "--check")),
        Command("Ruff", (python, "-m", "ruff", "check", "backend", "scripts", "unit_tests")),
        Command("mypy", (python, "-m", "mypy", "backend")),
        Command(
            "Architecture constraints",
            (python, "scripts/check_architecture.py"),
            needs_test_secret=True,
        ),
        Command("Secret scan", (python, "scripts/check_secrets.py")),
        *dependency_audit_commands(),
        Command(
            "README consistency",
            (python, "scripts/check_docs.py"),
            needs_test_secret=True,
        ),
        backend_test_command(),
        Command(
            "Frontend regression tests",
            ("node", "--test", "unit_tests/frontend_regressions.cjs"),
        ),
    )


BROWSER_SETUP_HINT = (
    "Install them with 'npm ci' and 'npx playwright install chromium webkit'; on Linux also "
    "add host libraries once with 'sudo npx playwright install-deps chromium webkit'."
)


@functools.lru_cache(maxsize=1)
def browser_probe() -> tuple[bool, str]:
    """Launch the pinned browsers once; downloaded binaries alone may not start."""
    if shutil.which("node") is None:
        return False, "Node.js is not installed."
    try:
        result = subprocess.run(
            ("node", "scripts/browser_probe.cjs"),
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, f"browser probe could not run: {error}"
    lines = [line.strip() for line in (result.stderr + result.stdout).splitlines() if line.strip()]
    return result.returncode == 0, lines[-1] if lines else "Playwright browsers are unavailable."


def layout_dependencies_available() -> bool:
    return browser_probe()[0]


def browser_unavailable_message(label: str) -> str:
    return f"{label} needs Playwright Chromium/WebKit that can start here: {browser_probe()[1]} {BROWSER_SETUP_HINT}"


def run_setup() -> None:
    if not any(
        candidate.is_file()
        for candidate in (VENV_ROOT / "Scripts" / "python.exe", VENV_ROOT / "bin" / "python")
    ):
        run_checked(Command("Create virtual environment", (sys.executable, "-m", "venv", str(VENV_ROOT))))
    run_checked(
        Command(
            "Install development dependencies",
            (project_python(), "-m", "pip", "install", "--require-hashes", "-r", "requirements-dev.txt"),
        )
    )


def run_verify() -> None:
    for command in verification_commands():
        run_checked(command)


def browser_command(label: str, script: str, timeout: int, *, environment=()) -> Command:
    return Command(label, (project_python(), "scripts/browser_runner.py", "--timeout", str(timeout),
                           "--label", Path(script).stem, "--", "node", script), environment=environment)


def run_frontend_layout(*, optional: bool = False) -> None:
    if not layout_dependencies_available():
        message = browser_unavailable_message("frontend-layout")
        if optional:
            print(f"\n==> Frontend layout tests\nWARNING: {message}\nWARNING: Skipped.")
            return
        raise TaskError(message)
    run_checked(browser_command("Frontend layout tests", "unit_tests/frontend_layout.cjs", 660))


def run_frontend_e2e(*, optional: bool = False) -> None:
    if not layout_dependencies_available():
        message = browser_unavailable_message("frontend-e2e")
        if optional:
            print(f"\n==> Frontend browser E2E\nWARNING: {message}\nWARNING: Skipped.")
            return
        raise TaskError(message)
    run_checked(browser_command(
        "Frontend browser E2E", "unit_tests/frontend_e2e.cjs", 420,
        environment=(("PROJECT_PYTHON", project_python()),),
    ))


def run_frontend_pwa(*, optional: bool = False) -> None:
    if not layout_dependencies_available():
        message = browser_unavailable_message("frontend-pwa")
        if optional:
            print(f"\n==> PWA upgrade tests\nWARNING: {message}\nWARNING: Skipped.")
            return
        raise TaskError(message)
    run_checked(browser_command("PWA upgrade/offline tests", "unit_tests/frontend_pwa.cjs", 300))


def run_task(task: str, *, base_url: str | None = None) -> None:
    python = project_python()
    if task == "setup":
        run_setup()
    elif task == "test-fast":
        run_checked(Command("Ruff", (python, "-m", "ruff", "check", "backend", "scripts", "unit_tests")))
        run_checked(backend_test_command())
    elif task == "frontend-test":
        run_checked(Command("Frontend regression tests", ("node", "--test", "unit_tests/frontend_regressions.cjs")))
    elif task == "frontend-layout":
        run_frontend_layout()
    elif task == "frontend-e2e":
        run_frontend_e2e()
    elif task == "frontend-pwa":
        run_frontend_pwa()
    elif task == "eval-agent":
        run_checked(
            Command(
                "Agent behavior evals",
                (python, "-m", "pytest", "-q", "unit_tests/test_agent_evals.py"),
                needs_test_secret=True,
            )
        )
    elif task == "audit-deps":
        for command in dependency_audit_commands():
            run_checked(command)
    elif task == "architecture-check":
        run_checked(
            Command(
                "Architecture constraints",
                (python, "scripts/check_architecture.py"),
                needs_test_secret=True,
            )
        )
    elif task == "security-check":
        run_checked(Command("Secret scan", (python, "scripts/check_secrets.py")))
    elif task == "docs-check":
        run_checked(Command("Generated frontend assets", (python, "scripts/build_frontend.py", "--check")))
        run_checked(
            Command(
                "README consistency",
                (python, "scripts/check_docs.py"),
                needs_test_secret=True,
            )
        )
    elif task == "verify":
        run_verify()
    elif task == "verify-all":
        run_verify()
        run_frontend_layout(optional=True)
        run_frontend_e2e(optional=True)
        run_frontend_pwa(optional=True)
    elif task == "diagnostics-generate":
        if not layout_dependencies_available():
            raise TaskError(browser_unavailable_message("diagnostics-generate"))
        run_checked(browser_command("Capture synthetic browser failure", "scripts/diagnostics_drill.cjs", 60))
        run_checked(Command("Verify captured diagnostics", (python, "scripts/verify_diagnostics.py")))
    elif task == "diagnostics-verify":
        run_checked(Command("Verify downloaded diagnostics", (python, "scripts/verify_diagnostics.py")))
    elif task == "release-check":
        if not base_url:
            raise TaskError("release-check requires --base-url (HTTPS or a loopback fixture)")
        if not layout_dependencies_available():
            raise TaskError(browser_unavailable_message("release-check"))
        run_checked(Command("Generated frontend assets", (python, "scripts/build_frontend.py", "--check")))
        run_checked(Command("Read-only release verification", (python, "scripts/release_check.py", "--base-url", base_url)))
    else:
        raise TaskError(f"Unknown task: {task}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", nargs="?", default="verify", choices=PUBLIC_TASKS)
    parser.add_argument("--base-url", help="explicit origin for read-only release-check")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        run_task(arguments.task, base_url=arguments.base_url)
    except TaskError as error:
        print(f"Task '{arguments.task}' failed: {error}", file=sys.stderr)
        return 1
    print(f"\nTask '{arguments.task}' completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
