"""Release checks exercise synthetic responses, never a live origin or DB."""

import json
import mimetypes
from unittest.mock import Mock

import pytest

from scripts import release_check, task
from scripts.build_frontend import FRONTEND, ROOT, shell_asset_paths


def fixture_fetcher():
    manifest = json.loads((FRONTEND / "assets.json").read_text(encoding="utf-8"))
    assets = {url: name for url, name in shell_asset_paths(manifest)}
    assets["/service-worker.js"] = "service-worker.js"
    contract = {}
    for entry in json.loads((ROOT / "unit_tests/api_contract.json").read_text(encoding="utf-8")):
        method, path = entry.split(" ", 1)
        contract.setdefault(path, {})[method.lower()] = {}

    def fetch(path):
        if path in assets:
            name = assets[path]
            kind = mimetypes.guess_type(name)[0] or "application/octet-stream"
            return 200, {"Content-Type": kind}, (FRONTEND / name).read_bytes()
        if path in ("/health/live", "/health/ready"):
            return 200, {}, json.dumps({"status": "ok", "schema_version": 9}).encode()
        if path == "/openapi.json":
            return 200, {}, json.dumps({"paths": contract}).encode()
        return 401, {}, b""
    return fetch


def test_release_check_accepts_only_matching_complete_public_shell():
    result = release_check.check_release(fixture_fetcher())
    expected_version = json.loads((FRONTEND / "assets.json").read_text(encoding="utf-8"))["version"]
    assert result["version"] == expected_version
    assert result["assets"] == 51


@pytest.mark.parametrize("failure", ["hash", "mime", "http", "schema", "api", "auth", "version", "module-mime"])
def test_release_check_fails_closed_on_broken_deployments(failure):
    good = fixture_fetcher()

    def broken(path):
        status, headers, body = good(path)
        if path.startswith("/app-api.js"):
            if failure == "hash":
                body += b"// altered"
            if failure == "mime":
                headers = {"Content-Type": "text/html"}
            if failure == "http":
                status = 503
        if failure == "schema" and path == "/health/ready":
            body = b'{"status":"ok","schema_version":1}'
        if failure == "api" and path == "/openapi.json":
            body = b'{"paths":{}}'
        if failure == "auth" and path.startswith("/api/runs/year-summary"):
            status = 200
        if failure == "version" and path == "/":
            expected_version = json.loads((FRONTEND / "assets.json").read_text(encoding="utf-8"))["version"]
            body = body.replace(f'content="{expected_version}"'.encode(), b'content="0.0.0"')
        if failure == "module-mime" and path.startswith("/runtime/feature-lifecycle.mjs"):
            headers = {"Content-Type": "text/html"}
        return status, headers, body
    with pytest.raises(ValueError):
        release_check.check_release(broken)


@pytest.mark.parametrize("origin", ["http://example.com", "https://user:secret@example.com", "https://example.com/path", "https://example.com?token=secret"])
def test_release_origin_rejects_insecure_or_credentialed_targets(origin):
    with pytest.raises(ValueError):
        release_check.validate_origin(origin)


def test_release_task_requires_explicit_origin_and_never_skips_browsers(monkeypatch):
    with pytest.raises(task.TaskError, match="requires --base-url"):
        task.run_task("release-check")
    monkeypatch.setattr(task, "layout_dependencies_available", lambda: False)
    monkeypatch.setattr(task, "browser_probe", lambda: (False, "webkit cannot start"))
    with pytest.raises(task.TaskError, match=r"release-check needs Playwright Chromium/WebKit .*webkit cannot start"):
        task.run_task("release-check", base_url="https://example.com")
    monkeypatch.setattr(task, "layout_dependencies_available", lambda: True)
    run = Mock()
    monkeypatch.setattr(task, "run_checked", run)
    task.run_task("release-check", base_url="https://example.com")
    assert run.call_count == 2
    assert run.call_args.args[0].arguments[-2:] == ("--base-url", "https://example.com")


def test_browser_gate_failure_makes_the_release_command_fail(monkeypatch):
    import subprocess

    monkeypatch.setattr("sys.argv", ["release_check", "--base-url", "http://127.0.0.1:8000"])
    monkeypatch.setattr(release_check, "check_release", lambda fetcher: {"version": "4.0.1", "cache": "test", "assets": 51})
    run = Mock(side_effect=subprocess.CalledProcessError(1, ["node", "release_browser.cjs"]))
    monkeypatch.setattr(release_check.subprocess, "run", run)
    assert release_check.main() == 1
