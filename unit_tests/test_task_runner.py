import os
import re
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
        "diagnostics-generate",
        "diagnostics-verify",
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


def test_browser_ci_pins_runtime_and_preserves_failure_diagnostics():
    import json

    root = Path(__file__).resolve().parents[1]
    package = json.loads((root / "package.json").read_text())
    lock = json.loads((root / "package-lock.json").read_text())
    version = package["devDependencies"]["playwright"]
    assert lock["packages"]["node_modules/playwright"]["version"] == version
    workflow = (root / ".github/workflows/verify.yml").read_text()
    for gate in ("frontend-layout", "frontend-e2e", "frontend-pwa"):
        browser_job = re.search(r'^  ' + gate + r':\n(.*?)(?=^  [a-z]|\Z)', workflow, re.M | re.S)[1]
        assert f"image: mcr.microsoft.com/playwright:v{version}-noble" in browser_job
        # The runner tool-cache Python is mounted into the container; a newer host Ubuntu
        # builds it against libraries the noble image lacks (pip then has no ssl module).
        assert "runs-on: ubuntu-24.04" in browser_job
        assert "options: --ipc=host" in browser_job
        assert "--with-deps" not in browser_job
        assert f"python scripts/task.py {gate}" in browser_job
        assert "include-hidden-files: true" in browser_job
    setup = (root / '.github/actions/browser-setup/action.yml').read_text()
    assert 'cache: pip' not in setup
    assert 'python -m pip install --require-hashes' in setup


def test_diagnostics_roundtrip_requires_capture_upload_download_and_content_verification():
    source = (Path(__file__).resolve().parents[1] / '.github/workflows/verify.yml').read_text()
    capture = source.split('  frontend-layout:', 1)[1].split('  diagnostics-roundtrip:', 1)[0]
    download = source.split('  diagnostics-roundtrip:', 1)[1]
    assert 'python scripts/task.py diagnostics-generate' in capture
    assert 'name: browser-diagnostics-roundtrip' in capture
    assert 'if-no-files-found: error' in capture
    assert 'needs: frontend-pwa' in download
    assert 'actions/download-artifact@v8' in download
    assert 'name: browser-diagnostics-roundtrip' in download
    assert 'python scripts/task.py diagnostics-verify' in download


def test_downloaded_diagnostics_validate_checksums_trace_contents_and_safe_paths(tmp_path):
    import hashlib
    import json
    from zipfile import ZipFile

    import pytest

    from scripts.verify_diagnostics import MARKER, verify

    (tmp_path / 'synthetic.png').write_bytes(b'\x89PNG\r\n\x1a\nsynthetic')
    (tmp_path / 'synthetic.txt').write_text(MARKER)
    with ZipFile(tmp_path / 'synthetic.zip', 'w') as archive:
        archive.writestr('trace.trace', '{"synthetic": "' + MARKER + '"}')
    entries = [{'name': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
               for path in sorted(tmp_path.iterdir())]
    manifest = {'format': 'synthetic-browser-diagnostics-v1', 'marker': MARKER, 'files': entries}
    target = tmp_path / 'manifest.json'
    target.write_text(json.dumps(manifest))
    assert len(verify(tmp_path)) == 3
    (tmp_path / 'synthetic.txt').write_text('tampered')
    with pytest.raises(ValueError, match='checksum'):
        verify(tmp_path)
    manifest['files'][0]['name'] = '../synthetic.png'
    target.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='unsafe'):
        verify(tmp_path)


def test_browser_jobs_are_independent_and_keep_timeout_diagnostics():
    root = Path(__file__).resolve().parents[1]
    source = (root / '.github/workflows/verify.yml').read_text()
    for gate in ('frontend-layout', 'frontend-e2e', 'frontend-pwa'):
        body = re.search(r'^  ' + gate + r':\n(.*?)(?=^  [a-z]|\Z)', source, re.M | re.S)[1]
        assert 'needs:' not in body
        assert 'uses: ./.github/actions/browser-setup' in body
        assert f'run: python scripts/task.py {gate}' in body
        assert 'if: always() && (failure() || cancelled())' in body
        assert f'name: {gate}-failure-diagnostics' in body
    commands = []
    from unittest.mock import patch
    with patch.object(task, 'layout_dependencies_available', return_value=True), patch.object(task, 'run_checked', commands.append):
        for gate in ('frontend-layout', 'frontend-e2e', 'frontend-pwa'):
            task.run_task(gate)
    assert len(commands) == 3
    for command in commands:
        assert 'scripts/browser_runner.py' in command.arguments
        assert '--timeout' in command.arguments


def test_browser_checks_require_browsers_that_launch(monkeypatch):
    """Downloaded Playwright binaries without host libraries must skip, not fail, optional runs."""
    import subprocess

    calls = []

    def fake_run(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1, stdout="", stderr=(
            "chromium cannot start: host system libraries are missing; "
            "run sudo npx playwright install-deps chromium webkit.\n"
        ))

    task.browser_probe.cache_clear()
    monkeypatch.setattr(task.shutil, "which", lambda _name: "/usr/bin/node")
    monkeypatch.setattr(task.subprocess, "run", fake_run)
    try:
        assert task.layout_dependencies_available() is False
        assert task.layout_dependencies_available() is False
        assert calls == [("node", "scripts/browser_probe.cjs")], "one launch probe per run"
        message = task.browser_unavailable_message("frontend-layout")
        assert "host system libraries are missing" in message
        assert "install-deps" in message
        task.run_frontend_layout(optional=True)  # warns and skips
    finally:
        task.browser_probe.cache_clear()
