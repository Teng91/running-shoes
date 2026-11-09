"""Tests for behavior that is intentionally decided at module import time."""

import importlib
import os
import runpy
import sys
from unittest.mock import MagicMock

import pytest

from backend import llm

settings_module = importlib.import_module("backend.settings")


def test_llm_does_not_inject_stale_or_model_env_defaults():
    original = os.environ.get("OR_MODEL")
    try:
        os.environ["OR_MODEL"] = "vendor/custom:free"
        importlib.reload(llm)
        assert llm.MODELS["openrouter"] == []

        os.environ["OR_MODEL"] = "nvidia/nemotron-3-ultra-550b-a55b:free"
        importlib.reload(llm)
        assert llm.MODELS["openrouter"] == []

        os.environ["OR_MODEL"] = "openrouter/free"
        importlib.reload(llm)
        assert all(model["id"] != "openrouter/free" for model in llm.MODELS["openrouter"])

        os.environ["OR_MODEL"] = "openai/paid-model"
        importlib.reload(llm)
        assert all(model["id"] != "openai/paid-model" for model in llm.MODELS["openrouter"])
    finally:
        if original is None:
            os.environ.pop("OR_MODEL", None)
        else:
            os.environ["OR_MODEL"] = original
        importlib.reload(llm)


def test_production_refuses_a_missing_or_short_secret_key(tmp_path):
    """SPEC-047: validation happens in the composition root, not as an import side effect."""
    from backend.app_factory import create_app
    from backend.settings import Settings, runtime_settings

    def production(secret):
        return Settings.from_env({"ENVIRONMENT": "production", "SECRET_KEY": secret, "DB_DIR": str(tmp_path)})

    with pytest.raises(RuntimeError, match="required in production"):
        create_app(production(""), frontend_dir=tmp_path)
    with pytest.raises(RuntimeError, match="at least 32 bytes"):
        runtime_settings(production("x" * 31))
    accepted = production("p" * 32)
    assert runtime_settings(accepted) is accepted


def test_development_without_secret_uses_a_long_fallback_and_warns(tmp_path):
    from backend.settings import (
        DEV_FALLBACK_SECRET_KEY,
        MIN_SECRET_KEY_BYTES,
        Settings,
        runtime_settings,
    )

    config = Settings.from_env({"ENVIRONMENT": "development", "DB_DIR": str(tmp_path)})
    with pytest.warns(UserWarning, match="fallback SECRET_KEY"):
        resolved = runtime_settings(config)
    assert resolved.secret_key == DEV_FALLBACK_SECRET_KEY
    assert len(DEV_FALLBACK_SECRET_KEY.encode()) >= MIN_SECRET_KEY_BYTES


def test_importing_backend_modules_performs_no_database_io(tmp_path):
    """SPEC-047: no engine, directory or secret check is created at import time."""
    import subprocess

    missing = tmp_path / "not-created"
    environment = {**os.environ, "DB_DIR": str(missing), "ENVIRONMENT": "production", "SECRET_KEY": ""}
    code = "import backend.database, backend.auth, backend.rate_limits, backend.routers.runs; print('ok')"
    result = subprocess.run((sys.executable, "-c", code), capture_output=True, text=True, env=environment, check=True)
    assert result.stdout.strip().splitlines()[-1] == "ok"
    assert not missing.exists()


def test_run_module_starts_uvicorn(monkeypatch):
    run = MagicMock()
    monkeypatch.setattr("uvicorn.run", run)
    runpy.run_module("backend.run", run_name="__main__")
    run.assert_called_once_with(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )


def test_importing_run_module_does_not_start_server(monkeypatch):
    run = MagicMock()
    monkeypatch.setattr("uvicorn.run", run)
    import backend.run as run_module

    importlib.reload(run_module)
    run.assert_not_called()


def test_backend_import_does_not_load_the_openai_sdk():
    """SPEC-046: the OpenAI SDK is loaded by the first AI request, not by a cold start."""
    import subprocess

    environment = {**os.environ, "SECRET_KEY": "import-path-test-only", "ENVIRONMENT": "development"}
    result = subprocess.run(
        (sys.executable, "-c", "import sys, backend.main; print('openai' in sys.modules)"),
        capture_output=True,
        text=True,
        env=environment,
        check=True,
    )
    assert result.stdout.strip().splitlines()[-1] == "False"
