import io
import json

from scripts import claude_stop_hook


def test_layout_checks_only_run_for_layout_files():
    assert claude_stop_hook.needs_layout_check({"frontend/index.html"}) is True
    assert claude_stop_hook.needs_layout_check({"frontend/app.js"}) is True
    assert claude_stop_hook.needs_layout_check({"frontend/app-runs.js"}) is True
    assert claude_stop_hook.needs_layout_check({"frontend/app-shoes.js"}) is True
    assert claude_stop_hook.needs_layout_check({"frontend/styles.css"}) is True
    assert claude_stop_hook.needs_layout_check({"backend/main.py"}) is False


def test_cache_path_sanitizes_the_session_id(monkeypatch, tmp_path):
    monkeypatch.setattr(claude_stop_hook, "CACHE_ROOT", tmp_path)
    path = claude_stop_hook.cache_path("session/../../unsafe")
    assert path.parent == tmp_path
    assert "/" not in path.name
    assert ".." not in path.name


def test_project_stop_hook_uses_local_launcher():
    settings_path = claude_stop_hook.ROOT / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    command = settings["hooks"]["Stop"][0]["hooks"][0]["command"]

    assert "claude_stop_hook_launcher.cjs" in command


def test_blocking_payload_returns_a_stop_decision():
    payload = json.loads(claude_stop_hook.blocking_payload("tests failed"))
    assert payload["decision"] == "block"
    assert "tests failed" in payload["reason"]


def test_main_allows_a_clean_worktree(monkeypatch):
    monkeypatch.setattr(claude_stop_hook, "changed_files", lambda: set())
    monkeypatch.setattr(claude_stop_hook.sys, "stdin", io.StringIO('{"session_id":"clean"}'))
    assert claude_stop_hook.main() == 0


def test_main_blocks_a_failed_verification(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(claude_stop_hook, "CACHE_ROOT", tmp_path)
    monkeypatch.setattr(claude_stop_hook, "changed_files", lambda: {"backend/main.py"})
    monkeypatch.setattr(claude_stop_hook, "worktree_fingerprint", lambda _files: "fingerprint")
    monkeypatch.setattr(claude_stop_hook, "run_verification", lambda _files: (False, "pytest failed"))
    monkeypatch.setattr(claude_stop_hook.sys, "stdin", io.StringIO('{"session_id":"failed"}'))

    assert claude_stop_hook.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["decision"] == "block"
    assert "pytest failed" in payload["reason"]


def test_main_reuses_a_cached_success(monkeypatch, tmp_path):
    monkeypatch.setattr(claude_stop_hook, "CACHE_ROOT", tmp_path)
    monkeypatch.setattr(claude_stop_hook, "changed_files", lambda: {"backend/main.py"})
    monkeypatch.setattr(claude_stop_hook, "worktree_fingerprint", lambda _files: "same")
    monkeypatch.setattr(
        claude_stop_hook,
        "run_verification",
        lambda _files: (_ for _ in ()).throw(AssertionError("verification should be cached")),
    )
    cache = claude_stop_hook.cache_path("cached")
    claude_stop_hook.save_cache(cache, "same", True, "")
    monkeypatch.setattr(claude_stop_hook.sys, "stdin", io.StringIO('{"session_id":"cached"}'))

    assert claude_stop_hook.main() == 0


def test_main_retries_a_cached_failure_and_never_reblocks_an_active_stop(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(claude_stop_hook, "CACHE_ROOT", tmp_path)
    monkeypatch.setattr(claude_stop_hook, "changed_files", lambda: {"backend/main.py"})
    monkeypatch.setattr(claude_stop_hook, "worktree_fingerprint", lambda _files: "same")
    cache = claude_stop_hook.cache_path("retry")
    claude_stop_hook.save_cache(cache, "same", False, "pip-audit could not reach PyPI")
    runs: list[set[str]] = []

    def verify(files: set[str]) -> tuple[bool, str]:
        runs.append(files)
        return True, ""

    monkeypatch.setattr(claude_stop_hook, "run_verification", verify)
    monkeypatch.setattr(claude_stop_hook.sys, "stdin", io.StringIO('{"session_id":"retry","stop_hook_active":true}'))
    assert claude_stop_hook.main() == 0
    assert capsys.readouterr().out == "" and runs == [], "an unchanged failure is not replayed in a loop"

    monkeypatch.setattr(claude_stop_hook.sys, "stdin", io.StringIO('{"session_id":"retry"}'))
    assert claude_stop_hook.main() == 0
    assert capsys.readouterr().out == "" and len(runs) == 1, "a later stop re-runs a transient failure"
    assert claude_stop_hook.load_cache(cache)["passed"] is True


def test_read_event_decodes_utf8_regardless_of_the_console_code_page(monkeypatch):
    message = "已推上去 ✅ ⏸ 部署 \\ \"引號\""
    payload = json.dumps({"session_id": "utf8", "last_assistant_message": message}, ensure_ascii=False)
    # Windows wraps stdin with the locale code page; the hook must still read UTF-8 bytes.
    stdin = io.TextIOWrapper(io.BytesIO(payload.encode("utf-8")), encoding="cp950", errors="replace")
    monkeypatch.setattr(claude_stop_hook.sys, "stdin", stdin)

    assert claude_stop_hook.read_event()["last_assistant_message"] == message


def test_layout_check_is_skipped_when_browsers_cannot_launch(monkeypatch):
    import subprocess

    commands = []
    monkeypatch.setattr(claude_stop_hook.shutil, "which", lambda _name: "/usr/bin/node")
    monkeypatch.setattr(claude_stop_hook.subprocess, "run", lambda command, **_kwargs: (
        commands.append(command) or subprocess.CompletedProcess(command, 1)))
    assert claude_stop_hook.layout_dependencies_available() is False
    assert commands == [("node", "scripts/browser_probe.cjs")]

    monkeypatch.setattr(claude_stop_hook, "run_check", lambda check: (True, ""))
    assert claude_stop_hook.run_verification({"frontend/styles.css"}) == (True, "")
