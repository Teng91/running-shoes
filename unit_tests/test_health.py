from fastapi.testclient import TestClient

from backend.dependencies import get_db
from backend.main import app


def test_health_probes_and_request_id(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            live = client.get("/health/live", headers={"X-Request-ID": "deploy-check-1"})
            ready = client.get("/health/ready")
    finally:
        app.dependency_overrides.clear()

    assert live.status_code == 200
    assert live.json() == {"status": "ok"}
    assert live.headers["x-request-id"] == "deploy-check-1"
    assert ready.status_code == 200
    assert ready.json()["schema_version"] >= 1
    assert len(ready.headers["x-request-id"]) == 32


def test_unsafe_request_id_is_replaced(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            response = client.get("/health/live", headers={"X-Request-ID": "bad id/with spaces"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["x-request-id"] != "bad id/with spaces"


def test_readiness_reports_503_for_missing_stale_or_unavailable_databases():
    """v4.7.1: every not-ready branch returns 503 instead of a false 200 or a 500."""
    from unittest.mock import MagicMock

    import pytest
    from fastapi import HTTPException
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import sessionmaker

    from backend.database import Base
    from backend.migrations import CURRENT_SCHEMA_VERSION
    from backend.routers.health import ready

    def detail(prepare):
        engine = create_engine("sqlite://")
        prepare(engine)
        with sessionmaker(bind=engine)() as session, pytest.raises(HTTPException) as error:
            ready(session)
        engine.dispose()
        assert error.value.status_code == 503
        return error.value.detail

    def stale(engine):
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE schema_metadata (key VARCHAR PRIMARY KEY, value VARCHAR)"))
            connection.execute(text("INSERT INTO schema_metadata VALUES ('schema_version', :v)"),
                               {"v": str(CURRENT_SCHEMA_VERSION - 1)})

    assert detail(lambda engine: None) == "database schema is incomplete"
    assert detail(Base.metadata.create_all) == "database schema is not initialized"
    assert detail(stale) == "database schema is not current"
    broken = MagicMock()
    broken.execute.side_effect = OperationalError("SELECT 1", {}, Exception("disk I/O error"))
    with pytest.raises(HTTPException) as error:
        ready(broken)
    assert (error.value.status_code, error.value.detail) == (503, "database is unavailable")
