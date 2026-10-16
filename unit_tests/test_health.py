from fastapi.testclient import TestClient

from backend.database import get_db
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
