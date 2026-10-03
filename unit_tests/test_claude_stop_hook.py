import io
import json

from scripts import claude_stop_hook


def test_layout_checks_only_run_for_layout_files():
    assert claude_stop_hook.needs_layout_check({"frontend/index.html"}) is True
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
