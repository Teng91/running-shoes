from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from backend import models, schemas
from backend.app_factory import create_app
from backend.services.errors import Conflict
from backend.services.operations import execute_operation
from unit_tests.token_helpers import token_for_name
from unit_tests.workspace_helpers import workspace as workspace


def shoe_command(**values):
    return schemas.MutationCommand(operation_id="operation-shoe-0001", kind="shoe.create",
                                    payload={"brand": "Test", "model": "Runner", "date": "2026-01-01", **values})


def test_operation_receipt_replays_and_rejects_changed_payload(workspace):
    with workspace.sessions() as db:
        result = execute_operation(db, 1, shoe_command(), workspace.config)
        assert execute_operation(db, 1, shoe_command(), workspace.config) == result
        with pytest.raises(Conflict):
            execute_operation(db, 1, shoe_command(mileage=20), workspace.config)
        execute_operation(db, 2, shoe_command(), workspace.config)
        assert db.query(models.Shoe).count() == 2


def test_concurrent_operation_key_commits_once(workspace):
    def create(_):
        with workspace.sessions() as db:
            return execute_operation(db, 1, shoe_command(), workspace.config)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, range(2)))
    assert results[0] == results[1]
    with workspace.sessions() as db:
        assert db.query(models.Shoe).count() == 1
        assert db.query(models.MutationReceipt).count() == 1
        assert db.query(models.AuditEvent).count() == 1


def test_canonical_and_legacy_http_contracts_are_isolated(workspace):
    app = create_app(workspace.config, db_engine=workspace.engine, session_factory=workspace.sessions)
    headers = {"Authorization": "Bearer " + token_for_name(workspace.sessions, "one", secret_key=workspace.config.secret_key or None)}
    with TestClient(app) as client:
        response = client.post("/api/operations", headers=headers, json=shoe_command().model_dump())
        assert response.status_code == 200
        shoe = response.json()
        versionless = {"operation_id": "operation-update-1", "kind": "shoe.update", "entity_id": shoe["id"], "payload": {"mileage": 20}}
        assert client.post("/api/operations", headers=headers, json=versionless).status_code == 422
        legacy_headers = {**headers, 'Idempotency-Key': 'legacy-ignored-key'}
        assert client.put(f'/api/shoes/{shoe["id"]}', headers=legacy_headers, json={"mileage": 10}).status_code == 200
        assert client.put('/api/running-goal', headers=legacy_headers, json={'monthly_km': 180, 'start_year': 2026}).status_code == 200
        conflict = client.post("/api/operations", headers=headers, json={**versionless, "expected_version": 0})
        assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "conflict"
        assert client.get("/api/history").status_code in (401, 403)
        assert client.post("/api/account-restore/preview", headers=headers, content=b'{"password":"private"}').status_code == 400
        assert client.post("/api/account-restore/preview", headers={**headers, "Content-Length": str(21 * 1024 * 1024)}, content=b'{}').status_code == 413


def test_receipt_and_audit_roll_back_on_commit_error(workspace, monkeypatch):
    with workspace.sessions() as db:
        def fail():
            raise RuntimeError("commit failed")
        monkeypatch.setattr(db, "commit", fail)
        with pytest.raises(RuntimeError):
            execute_operation(db, 1, shoe_command(), workspace.config)
    with workspace.sessions() as db:
        assert db.query(models.MutationReceipt).count() == db.query(models.Shoe).count() == db.query(models.AuditEvent).count() == 0
