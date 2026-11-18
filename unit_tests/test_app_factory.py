"""Regression tests for explicit app composition and typed settings."""

from dataclasses import replace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import main, models
from backend.app_factory import create_app
from backend.auth import decode_access_token
from backend.settings import Settings, settings


def _memory_database():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    return engine, sessionmaker(bind=engine)


def test_factory_lifespan_uses_injected_database_and_frontend(tmp_path):
    engine, sessions = _memory_database()
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("factory frontend", encoding="utf-8")
    config = replace(
        settings,
        seed_data=False,
        frontend_dir=frontend,
        secret_key="factory-specific-secret-at-least-32-bytes",
    )
    app = create_app(
        config,
        db_engine=engine,
        session_factory=sessions,
    )

    with TestClient(app) as client:
        assert client.get("/health/ready").status_code == 200
        assert client.get("/").text == "factory frontend"
        assert client.post("/api/auth/register", json={
            "username": "factory-user", "password": "pass1234",
        }).status_code == 200
        token = client.post("/api/auth/login", json={
            "username": "factory-user", "password": "pass1234",
        }).json()["access_token"]
        assert decode_access_token(
            token, secret_key=config.secret_key
        )["sub"] == "factory-user"

    with sessions() as db:
        assert db.query(models.User).count() == 1


def test_factory_seed_is_scoped_to_injected_database(tmp_path):
    engine, sessions = _memory_database()
    config = replace(
        settings,
        seed_data=True,
        migration_password="factory-seed-password",
        frontend_dir=tmp_path,
    )
    app = create_app(config, db_engine=engine, session_factory=sessions)

    with TestClient(app):
        pass

    with sessions() as db:
        assert db.query(models.User).filter_by(username="Demo").one()
        assert db.query(models.Shoe).count() == 8


def test_settings_parse_and_validate_runtime_values(tmp_path):
    config = Settings.from_env({
        "ENVIRONMENT": "production",
        "SECRET_KEY": "typed-test-secret",
        "DB_DIR": str(tmp_path),
        "FRONTEND_DIR": str(tmp_path / "web"),
        "FLY_APP_NAME": "running-shoes",
        "SEED_DATA": "TRUE",
        "MAX_RUNS_PER_USER": "0",
        "LLM_MAX_OUTPUT_TOKENS": "128",
    })

    assert config.is_production is True
    assert config.is_fly_runtime is True
    assert config.seed_data is True
    assert config.max_runs_per_user == 1
    assert config.llm_max_output_tokens == 256
    assert config.database_url.endswith("/shoes.db")


def test_main_is_only_the_asgi_entry_point():
    assert main.app is not None
    assert main.create_app is create_app
    for removed_alias in ("register", "create_shoe", "lifespan", "engine", "SessionLocal"):
        assert not hasattr(main, removed_alias)


def test_production_hides_the_interactive_api_console_but_keeps_the_contract(tmp_path):
    """SPEC-071: no Swagger/ReDoc on the public site; release-check still reads /openapi.json."""
    def get(environment, path):
        engine, sessions = _memory_database()
        frontend = tmp_path / environment
        frontend.mkdir(exist_ok=True)
        (frontend / "index.html").write_text("<!doctype html><title>shell</title>", encoding="utf-8")
        config = replace(settings, environment=environment, seed_data=False, frontend_dir=frontend,
                         secret_key="factory-specific-secret-at-least-32-bytes")
        with TestClient(create_app(config, db_engine=engine, session_factory=sessions)) as client:
            return client.get(path)

    for path in ("/docs", "/redoc"):
        hidden = get("production", path)
        assert hidden.status_code == 404
        assert hidden.headers["content-type"].startswith("application/json")
        assert get("development", path).status_code == 200
    assert "/api/runs/totals" in get("production", "/openapi.json").json()["paths"]
