import os
from pathlib import Path

from scripts import task


def test_public_tasks_cover_the_documented_harness():
    assert task.PUBLIC_TASKS == (
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
    )


def test_project_python_supports_windows_and_unix_virtual_environments(monkeypatch, tmp_path):
    monkeypatch.setattr(task, "VENV_ROOT", tmp_path)
    unix_python = tmp_path / "bin" / "python"
    unix_python.parent.mkdir()
    unix_python.touch()
    assert task.project_python() == str(unix_python)

    windows_python = tmp_path / "Scripts" / "python.exe"
    windows_python.parent.mkdir()
    windows_python.touch()
    assert task.project_python() == str(windows_python)


def test_test_secret_is_local_and_does_not_override_an_explicit_value(monkeypatch):
    command = task.Command("tests", ("python",), needs_test_secret=True)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    assert task.command_environment(command)["SECRET_KEY"] == task.TEST_SECRET_KEY

    monkeypatch.setenv("SECRET_KEY", "explicit-secret")
    assert task.command_environment(command)["SECRET_KEY"] == "explicit-secret"
    assert os.environ["SECRET_KEY"] == "explicit-secret"


def test_verify_all_reuses_verify_and_optionally_runs_browser_checks(monkeypatch):
    calls: list[object] = []
    monkeypatch.setattr(task, "run_verify", lambda: calls.append("verify"))
    monkeypatch.setattr(task, "run_frontend_layout", lambda *, optional=False: calls.append(optional))
    monkeypatch.setattr(task, "run_frontend_e2e", lambda *, optional=False: calls.append(("e2e", optional)))
    monkeypatch.setattr(task, "run_frontend_pwa", lambda *, optional=False: calls.append(("pwa", optional)))

    task.run_task("verify-all")

    assert calls == ["verify", True, ("e2e", True), ("pwa", True)]


def test_ci_and_docs_use_the_cross_platform_runner():
    repository_root = Path(__file__).resolve().parents[1]
    checked_paths = (
        repository_root / ".github" / "workflows" / "verify.yml",
        repository_root / ".github" / "pull_request_template.md",
        repository_root / "AGENTS.md",
        repository_root / "README.md",
        repository_root / "docs" / "testing-strategy.md",
    )
    combined = "\n".join(path.read_text(encoding="utf-8") for path in checked_paths)
    assert "scripts/task.py" in combined
    assert "task.ps1" not in combined
    assert "pwsh" not in combined.casefold()
