"""Cross-platform repository task runner.

This module is the single source of truth for local development, coding-agent
verification, and CI. Invoke it with any Python 3.11+ launcher, for example
``python3 scripts/task.py <task>`` on Unix or ``py -3 scripts/task.py <task>``
on Windows.
"""

from __future__ import annotations

import argparse
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
        Command(
            "Dependency vulnerability audit",
            (python, "-m", "pip_audit", "--require-hashes", "-r", "requirements.txt"),
        ),
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


def run_frontend_layout(*, optional: bool = False) -> None:
    if not layout_dependencies_available():
        message = (
            "Playwright or its Chromium/WebKit binaries are unavailable. Install them with "
            "'npm install --no-save --package-lock=false playwright' and "
            "'npx playwright install chromium webkit'."
        )
        if optional:
            print(f"\n==> Frontend layout tests\nWARNING: {message}\nWARNING: Skipped.")
            return
        raise TaskError(message)
    run_checked(Command("Frontend layout tests", ("node", "unit_tests/frontend_layout.cjs")))


def run_frontend_e2e(*, optional: bool = False) -> None:
    if not layout_dependencies_available():
        message = (
            "Playwright browser binaries are unavailable. Install them with "
            "'npm install --no-save --package-lock=false playwright' and "
            "'npx playwright install chromium webkit'."
        )
        if optional:
            print(f"\n==> Frontend browser E2E\nWARNING: {message}\nWARNING: Skipped.")
            return
        raise TaskError(message)
    run_checked(Command(
        "Frontend browser E2E",
        ("node", "unit_tests/frontend_e2e.cjs"),
        environment=(("PROJECT_PYTHON", project_python()),),
    ))


def run_frontend_pwa(*, optional: bool = False) -> None:
    if not layout_dependencies_available():
        message = "Playwright Chromium/WebKit binaries are required for frontend-pwa."
        if optional:
            print(f"\n==> PWA upgrade tests\nWARNING: {message}\nWARNING: Skipped.")
            return
        raise TaskError(message)
    run_checked(Command("PWA upgrade/offline tests", ("node", "unit_tests/frontend_pwa.cjs")))


def run_task(task: str) -> None:
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
        run_checked(
            Command(
                "Dependency vulnerability audit",
                (python, "-m", "pip_audit", "--require-hashes", "-r", "requirements.txt"),
            )
        )
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
    else:
        raise TaskError(f"Unknown task: {task}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", nargs="?", default="verify", choices=PUBLIC_TASKS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        run_task(arguments.task)
    except TaskError as error:
        print(f"Task '{arguments.task}' failed: {error}", file=sys.stderr)
        return 1
    print(f"\nTask '{arguments.task}' completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
