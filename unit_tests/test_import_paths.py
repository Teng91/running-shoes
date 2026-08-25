"""Tests for behavior that is intentionally decided at module import time."""

import importlib
import os
import runpy
import sys
from unittest.mock import MagicMock, patch

from backend import auth, llm


def test_llm_applies_new_and_existing_or_model_env_defaults():
    original = os.environ.get("OR_MODEL")
    try:
        os.environ["OR_MODEL"] = "vendor/custom:free"
        importlib.reload(llm)
        assert llm.MODELS["openrouter"][0]["id"] == "vendor/custom:free"
        assert llm.MODELS["openrouter"][0]["display"].endswith("(env)")

        os.environ["OR_MODEL"] = "nvidia/nemotron-3-ultra-550b-a55b:free"
        importlib.reload(llm)
        assert llm.MODELS["openrouter"][0]["id"] == "nvidia/nemotron-3-ultra-550b-a55b:free"

        os.environ["OR_MODEL"] = "openrouter/free"
        importlib.reload(llm)
        assert all(model["id"] != "openrouter/free" for model in llm.MODELS["openrouter"])
    finally:
        if original is None:
            os.environ.pop("OR_MODEL", None)
        else:
            os.environ["OR_MODEL"] = original
        importlib.reload(llm)


def test_auth_requires_secret_key_in_production_at_import(monkeypatch):
    original_environment = os.environ.get("ENVIRONMENT")
    original_secret = os.environ.get("SECRET_KEY")
    exit_mock = MagicMock()
    try:
        os.environ["ENVIRONMENT"] = "production"
        os.environ.pop("SECRET_KEY", None)
        monkeypatch.setattr(sys, "exit", exit_mock)
        with patch("warnings.warn"):
            importlib.reload(auth)
        exit_mock.assert_called_once_with(1)
    finally:
        if original_environment is None:
            os.environ.pop("ENVIRONMENT", None)
        else:
            os.environ["ENVIRONMENT"] = original_environment
        if original_secret is None:
            os.environ.pop("SECRET_KEY", None)
        else:
            os.environ["SECRET_KEY"] = original_secret
        with patch("warnings.warn"):
            importlib.reload(auth)


def test_auth_import_with_secret_key_skips_fallback(monkeypatch):
    original_environment = os.environ.get("ENVIRONMENT")
    original_secret = os.environ.get("SECRET_KEY")
    try:
        os.environ["ENVIRONMENT"] = "production"
        os.environ["SECRET_KEY"] = "production-test-secret"
        exit_mock = MagicMock()
        monkeypatch.setattr(sys, "exit", exit_mock)
        importlib.reload(auth)
        assert auth.SECRET_KEY == "production-test-secret"
        exit_mock.assert_not_called()
    finally:
        if original_environment is None:
            os.environ.pop("ENVIRONMENT", None)
        else:
            os.environ["ENVIRONMENT"] = original_environment
        if original_secret is None:
            os.environ.pop("SECRET_KEY", None)
        else:
            os.environ["SECRET_KEY"] = original_secret
        with patch("warnings.warn"):
            importlib.reload(auth)


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
