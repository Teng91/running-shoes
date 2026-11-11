"""Additional API coverage for exports, spending, agent routes, and failures."""

import asyncio
import builtins
import csv
import io
import re
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock

import openpyxl
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend import llm, models, rate_limits, schemas
from backend.auth import create_access_token, get_password_hash
from backend.dependencies import get_db
from backend.main import app
from backend.models import MonthlyMileage, Shoe
from backend.routers.exports import export_shoes
from backend.routers.monthly import (
    create_monthly_mileage,
    delete_monthly_mileage,
    update_monthly_mileage,
)
from backend.routers.runs import create_run, delete_run, update_run
from backend.routers.shoes import create_shoe, delete_shoe, update_shoe


@pytest.fixture
def client(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _limits(monkeypatch, **values):
    """Rate limits are injected settings, read per request (SPEC-047)."""
    monkeypatch.setattr(app.state, "settings", replace(app.state.settings, **values))


def _bucket(db, scope, key):
    db.expire_all()
    return db.query(models.RateLimitBucket).filter_by(scope=scope, bucket_key=key).one_or_none()


def _add_export_shoes(db, user_id):
    active = Shoe(
        user_id=user_id,
        brand="Mizuno",
        model="Wave Rider",
        date="2026-02-03",
        size="US 11",
        price=2000,
        orig_price=4000,
        mileage=500,
        expected_mileage=800,
        monthly_km=60,
        categories=["Daily", "Tempo"],
    )
    retired = Shoe(
        user_id=user_id,
        brand="ASICS",
        model="Old Shoe",
        date="2025-01-02",
        price=1500,
        orig_price=0,
        mileage=0,
        expected_mileage=0,
        monthly_km=0,
        is_retired=True,
        categories=[],
    )
    db.add_all([active, retired])
    db.commit()
    return active, retired


def test_export_csv_all_contains_calculated_fields(client, db, user_with_token):
    user, token = user_with_token
    _add_export_shoes(db, user.id)

    response = client.get("/api/export?format=csv&mode=all", headers=_auth(token))

    assert response.status_code == 200
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert re.search(
        r'attachment; filename="running_shoes_all_\d{8}_\d{6}\.csv"',
        response.headers["content-disposition"],
    )
    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert [row["鞋款"] for row in rows] == ["Wave Rider", "Old Shoe"]
    assert rows[0]["折數(%)"] == "50.0"
    assert rows[0]["每km成本"] == "4.0"
    assert rows[0]["預期每km成本"] == "2.5"
    assert rows[0]["生命進度(%)"] == "62.5"
    assert rows[0]["類別"] == "Daily, Tempo"
    assert rows[0]["狀態"] == "使用中"
    assert rows[1]["折數(%)"] == "0"
    assert rows[1]["每km成本"] == "0"
    assert rows[1]["預期每km成本"] == "0"
    assert rows[1]["狀態"] == "已退役"


def test_exports_preserve_decimal_prices(client, db, user_with_token):
    user, token = user_with_token
    db.add(Shoe(
        user_id=user.id,
        brand="Decimal",
        model="Price",
        date="2026-02-03",
        price=123.46,
        orig_price=200.99,
    ))
    db.commit()

    csv_response = client.get("/api/export?format=csv", headers=_auth(token))
    csv_row = next(csv.DictReader(io.StringIO(csv_response.content.decode("utf-8-sig"))))
    assert csv_row["買價"] == "123.46"
    assert csv_row["原價"] == "200.99"

    xlsx_response = client.get("/api/export?format=xlsx", headers=_auth(token))
    sheet = openpyxl.load_workbook(io.BytesIO(xlsx_response.content))["跑鞋資料"]
    headers = [cell.value for cell in sheet[1]]
    assert sheet.cell(2, headers.index("買價") + 1).value == 123.46
    assert sheet.cell(2, headers.index("原價") + 1).value == 200.99


def test_export_csv_retired_omits_status_column(client, db, user_with_token):
    user, token = user_with_token
    _add_export_shoes(db, user.id)

    response = client.get("/api/export?format=csv&mode=retired", headers=_auth(token))

    rows = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
    assert response.status_code == 200
    assert len(rows) == 1
    assert rows[0]["鞋款"] == "Old Shoe"
    assert "狀態" not in rows[0]


def test_export_xlsx_active_has_styled_sheet(client, db, user_with_token):
    user, token = user_with_token
    _add_export_shoes(db, user.id)

    response = client.get("/api/export?format=xlsx&mode=active", headers=_auth(token))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    workbook = openpyxl.load_workbook(io.BytesIO(response.content))
    sheet = workbook["跑鞋資料"]
    headers = [cell.value for cell in sheet[1]]
    assert "狀態" in headers
    assert sheet.cell(2, headers.index("鞋款") + 1).value == "Wave Rider"
    assert sheet["A1"].font.bold is True
    assert sheet.column_dimensions["A"].width == 18


def test_exports_escape_spreadsheet_formulas(client, db, user_with_token):
    user, token = user_with_token
    db.add(Shoe(
        user_id=user.id,
        brand="=HYPERLINK(\"https://evil.example\")",
        model="+cmd|' /C calc'!A0",
        date="2026-01-01",
        size=" @SUM(1+1)",
        categories=["Daily"],
    ))
    db.commit()

    csv_response = client.get("/api/export?format=csv", headers=_auth(token))
    csv_row = next(csv.DictReader(io.StringIO(csv_response.content.decode("utf-8-sig"))))
    assert csv_row["品牌"].startswith("'=")
    assert csv_row["鞋款"].startswith("'+")
    assert csv_row["尺寸"].startswith("' @")

    xlsx_response = client.get("/api/export?format=xlsx", headers=_auth(token))
    sheet = openpyxl.load_workbook(io.BytesIO(xlsx_response.content))["跑鞋資料"]
    headers = [cell.value for cell in sheet[1]]
    assert sheet.cell(2, headers.index("品牌") + 1).data_type == "s"
    assert sheet.cell(2, headers.index("品牌") + 1).value.startswith("'=")


@pytest.mark.parametrize(
    "url",
    [
        "/api/export?format=csv&mode=active",
        "/api/export?format=xlsx&mode=retired",
    ],
)
def test_export_returns_404_when_selection_is_empty(client, user_with_token, url):
    _, token = user_with_token
    response = client.get(url, headers=_auth(token))
    assert response.status_code == 404
    assert response.json()["detail"] == "沒有可匯出的跑鞋資料"


@pytest.mark.parametrize(
    "url",
    [
        "/api/export?format=pdf&mode=active",
        "/api/export?format=csv&mode=unknown",
    ],
)
def test_export_rejects_invalid_query_values(client, user_with_token, url):
    _, token = user_with_token
    assert client.get(url, headers=_auth(token)).status_code == 422


def test_monthly_spending_groups_sorts_and_skips_bad_dates(client, db, user_with_token):
    user, token = user_with_token
    db.add_all(
        [
            Shoe(user_id=user.id, brand="A", model="One", date="2026-02-01", price=100, orig_price=200),
            Shoe(user_id=user.id, brand="B", model="Two", date="2026-02-15", price=300, orig_price=0),
            Shoe(user_id=user.id, brand="C", model="Three", date="2025-12-01", price=50, orig_price=80),
            Shoe(user_id=user.id, brand="D", model="Bad", date="bad-date", price=999, orig_price=999),
            Shoe(user_id=user.id, brand="E", model="Empty", date="", price=999, orig_price=999),
        ]
    )
    db.commit()

    response = client.get("/api/spending/monthly", headers=_auth(token))

    assert response.status_code == 200
    assert response.json() == [
        {"year": 2025, "month": 12, "total_paid": 50.0, "total_orig": 80.0},
        {"year": 2026, "month": 2, "total_paid": 400.0, "total_orig": 200.0},
    ]


def test_agent_provider_routes_delegate_to_llm(client, user_with_token, monkeypatch):
    _, token = user_with_token
    list_providers = MagicMock(return_value=[{"id": "openrouter"}])
    monkeypatch.setattr("backend.routers.agent.llm.list_providers", list_providers)

    public_response = client.get("/api/agent/providers")
    authenticated_response = client.get("/api/agent/providers", headers=_auth(token))
    refresh_response = client.post("/api/agent/models/refresh", headers=_auth(token))

    assert public_response.status_code == 401
    assert authenticated_response.json() == [{"id": "openrouter"}]
    assert refresh_response.json() == [{"id": "openrouter"}]
    assert list_providers.call_args_list[0].kwargs == {}
    assert list_providers.call_args_list[1].kwargs == {"force": True}


def test_model_refresh_has_per_user_cooldown(
    client, db, user_with_token, monkeypatch
):
    _user, token = user_with_token
    monkeypatch.setattr("backend.routers.agent.llm.list_providers", MagicMock(return_value=[]))
    first = client.post("/api/agent/models/refresh", headers=_auth(token))
    second = client.post("/api/agent/models/refresh", headers=_auth(token))
    assert first.status_code == 200
    assert second.status_code == 429
    bucket = db.query(models.RateLimitBucket).filter_by(
        scope="model-refresh-global", bucket_key="global"
    ).one()
    assert bucket.event_count == 1


def test_model_refresh_has_global_limit_across_users(
    client, db, user_with_token, monkeypatch
):
    _first_user, first_token = user_with_token
    second_user = models.User(
        username="second-refresh-user",
        hashed_password=get_password_hash("pass1234"),
    )
    db.add(second_user)
    db.commit()
    second_token = create_access_token(data={"sub": second_user.username})
    _limits(monkeypatch, model_refresh_global_per_minute=1)
    monkeypatch.setattr("backend.routers.agent.llm.list_providers", MagicMock(return_value=[]))

    first = client.post("/api/agent/models/refresh", headers=_auth(first_token))
    second = client.post("/api/agent/models/refresh", headers=_auth(second_token))

    assert first.status_code == 200
    assert second.status_code == 429
    assert "模型列表更新" in second.json()["detail"]
    assert _bucket(db, "model-refresh-user", str(second_user.id)) is None


def test_registration_capacity_is_enforced(client, db, monkeypatch):
    monkeypatch.setattr(app.state, "settings", replace(app.state.settings, max_registered_users=1))
    db.add(models.User(
        username="existing",
        hashed_password=get_password_hash("pass1234"),
    ))
    db.commit()
    response = client.post(
        "/api/auth/register",
        headers={"Fly-Client-IP": "198.51.100.8"},
        json={"username": "new-user", "password": "pass1234"},
    )
    assert response.status_code == 403


def test_auth_endpoint_rate_limit_uses_client_ip(client, monkeypatch):
    _limits(monkeypatch, auth_rate_limit_per_minute=1)
    headers = {"Fly-Client-IP": "198.51.100.9"}
    first = client.post(
        "/api/auth/login", headers=headers,
        json={"username": "nobody", "password": "pass1234"},
    )
    second = client.post(
        "/api/auth/login", headers=headers,
        json={"username": "nobody", "password": "pass1234"},
    )
    assert first.status_code == 401
    assert second.status_code == 429


def test_auth_global_limit_rejects_before_creating_new_ip_bucket(
    client, db, monkeypatch
):
    _limits(monkeypatch, auth_rate_limit_per_minute=100)
    _limits(monkeypatch, auth_global_rate_limit_per_minute=1)
    _limits(monkeypatch, fly_app_name="running-shoes")

    payload = {"username": "nobody", "password": "pass1234"}
    first = client.post(
        "/api/auth/login",
        headers={"Fly-Client-IP": "198.51.100.21"},
        json=payload,
    )
    second = client.post(
        "/api/auth/login",
        headers={"Fly-Client-IP": "198.51.100.22"},
        json=payload,
    )

    assert first.status_code == 401
    assert second.status_code == 429
    assert _bucket(db, "auth-ip", "198.51.100.21") is not None
    assert _bucket(db, "auth-ip", "198.51.100.22") is None


def test_throttled_client_does_not_consume_global_auth_budget(client, db, monkeypatch):
    # Regression: an address over its own limit used to spend the global budget
    # on every rejected request, letting one client lock everyone out of login.
    _limits(monkeypatch, auth_rate_limit_per_minute=1)
    _limits(monkeypatch, auth_global_rate_limit_per_minute=3)
    _limits(monkeypatch, fly_app_name="running-shoes")
    payload = {"username": "nobody", "password": "pass1234"}
    attacker = {"Fly-Client-IP": "198.51.100.31"}
    responses = [client.post("/api/auth/login", headers=attacker, json=payload) for _ in range(5)]
    assert [r.status_code for r in responses] == [401, 429, 429, 429, 429]
    global_bucket = db.query(models.RateLimitBucket).filter_by(
        scope="auth-global", bucket_key="global"
    ).one()
    assert global_bucket.event_count == 1
    other = client.post("/api/auth/login", headers={"Fly-Client-IP": "198.51.100.32"}, json=payload)
    assert other.status_code == 401


def test_throttled_account_does_not_consume_global_agent_budget(db, monkeypatch):
    _limits(monkeypatch, agent_rate_limit_per_minute=1)
    request = SimpleNamespace(
        headers={}, client=SimpleNamespace(host="198.51.100.41"),
        app=SimpleNamespace(state=SimpleNamespace(
            settings=replace(app.state.settings, agent_rate_limit_per_minute=1), db_engine=db.get_bind(),
        )),
    )
    rate_limits.enforce_agent_request_limits(request, 4242)
    for _ in range(3):
        with pytest.raises(HTTPException) as exc_info:
            rate_limits.enforce_agent_request_limits(request, 4242)
        assert exc_info.value.status_code == 429
    global_bucket = db.query(models.RateLimitBucket).filter_by(
        scope="agent-global", bucket_key="global"
    ).one()
    assert global_bucket.event_count == 1


def test_repeated_password_failures_lock_only_that_account(client, db, monkeypatch):
    monkeypatch.setattr(rate_limits, "LOGIN_FAILURE_LIMIT", 2)
    db.add(models.User(username="victim", hashed_password=get_password_hash("correct-horse")))
    db.add(models.User(username="bystander", hashed_password=get_password_hash("correct-horse")))
    db.commit()
    wrong = {"username": "victim", "password": "wrong-pass"}
    assert client.post("/api/auth/login", json=wrong).status_code == 401
    assert client.post("/api/auth/login", json=wrong).status_code == 401
    locked = client.post("/api/auth/login", json={"username": "victim", "password": "correct-horse"})
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) > 60
    change = client.post("/api/auth/change-password", json={
        "username": "victim", "old_password": "correct-horse", "new_password": "new-password",
    })
    assert change.status_code == 429
    other = client.post("/api/auth/login", json={"username": "bystander", "password": "correct-horse"})
    assert other.status_code == 200


def test_failed_logins_lock_one_address_before_the_whole_account(client, db, monkeypatch):
    """SPEC-047: one address cannot lock the owner out; only many addresses lock the account."""
    monkeypatch.setattr(rate_limits, "LOGIN_FAILURE_LIMIT", 2)
    monkeypatch.setattr(rate_limits, "ACCOUNT_FAILURE_LIMIT", 3)
    _limits(monkeypatch, fly_app_name="running-shoes")
    db.add(models.User(username="owner", hashed_password=get_password_hash("correct-horse")))
    db.commit()
    wrong = {"username": "owner", "password": "wrong-pass"}
    right = {"username": "owner", "password": "correct-horse"}
    attacker, owner, second = ({"Fly-Client-IP": ip} for ip in ("198.51.100.61", "198.51.100.62", "198.51.100.63"))
    assert [client.post("/api/auth/login", headers=attacker, json=wrong).status_code for _ in range(3)] == [401, 401, 429]
    assert client.post("/api/auth/login", headers=owner, json=right).status_code == 200
    assert client.post("/api/auth/login", headers=second, json=wrong).status_code == 401
    locked = client.post("/api/auth/login", headers=owner, json=right)
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) > 60


def test_unknown_username_still_runs_a_password_hash_check(client, monkeypatch):
    from backend.services import accounts
    calls = []
    original = accounts.verify_password
    monkeypatch.setattr(accounts, "verify_password", lambda *args: calls.append(args) or original(*args))
    response = client.post("/api/auth/login", json={"username": "ghost", "password": "pass1234"})
    assert response.status_code == 401
    assert len(calls) == 1


def test_shoe_record_quota_is_enforced(client, db, user_with_token, monkeypatch):
    user, token = user_with_token
    monkeypatch.setattr(app.state, "settings", replace(app.state.settings, max_shoes_per_user=1))
    db.add(Shoe(user_id=user.id, brand="A", model="One", date="2026-01-01"))
    db.commit()
    response = client.post("/api/shoes", headers=_auth(token), json={
        "brand": "B", "model": "Two", "date": "2026-01-02",
    })
    assert response.status_code == 409


def test_agent_ip_and_global_limits_run_before_llm(client, user_with_token, monkeypatch):
    _user, token = user_with_token
    _limits(monkeypatch, agent_ip_rate_limit_per_minute=1)
    _limits(monkeypatch, agent_rate_limit_per_minute=10)
    _limits(monkeypatch, agent_global_rate_limit_per_minute=10)
    monkeypatch.setattr("backend.routers.agent.llm.resolve_allowed_model", MagicMock(return_value="free"))
    run_agent = MagicMock(return_value=iter(['data: {"type":"done"}\n\n']))
    monkeypatch.setattr("backend.routers.agent.agent_service.run_agent_stream", run_agent)
    headers = {**_auth(token), "Fly-Client-IP": "198.51.100.10"}
    first = client.post(
        "/api/agent/chat/stream", headers=headers, json={"user_message": "hi"}
    )
    second = client.post(
        "/api/agent/chat/stream", headers=headers, json={"user_message": "hi"}
    )
    assert first.status_code == 200
    assert second.status_code == 429
    assert run_agent.call_count == 1


def test_agent_global_limit_rejects_before_creating_ip_or_account_buckets(
    client, db, user_with_token, monkeypatch
):
    user, token = user_with_token
    _limits(monkeypatch, agent_global_rate_limit_per_minute=1)
    _limits(monkeypatch, agent_ip_rate_limit_per_minute=100)
    _limits(monkeypatch, agent_rate_limit_per_minute=100)
    _limits(monkeypatch, fly_app_name="running-shoes")
    monkeypatch.setattr("backend.routers.agent.llm.resolve_allowed_model", MagicMock(return_value="free"))
    monkeypatch.setattr(
        "backend.routers.agent.agent_service.run_agent_stream",
        MagicMock(return_value=iter(['data: {"type":"done"}\n\n'])),
    )

    first = client.post(
        "/api/agent/chat/stream",
        headers={**_auth(token), "Fly-Client-IP": "198.51.100.31"},
        json={"user_message": "hi"},
    )
    second = client.post(
        "/api/agent/chat/stream",
        headers={**_auth(token), "Fly-Client-IP": "198.51.100.32"},
        json={"user_message": "hi"},
    )

    assert first.status_code == 200
    assert second.status_code == 429
    assert _bucket(db, "agent-ip", "198.51.100.31") is not None
    assert _bucket(db, "agent-ip", "198.51.100.32") is None
    assert _bucket(db, "agent-user", str(user.id)).event_count == 1


def test_agent_stream_route_forwards_payload_and_user(client, user_with_token, monkeypatch):
    user, token = user_with_token
    run_agent = MagicMock(return_value=iter(['data: {"type":"done"}\n\n']))
    monkeypatch.setattr("backend.routers.agent.agent_service.run_agent_stream", run_agent)
    resolve_model = MagicMock(return_value="vendor/allowed:free")
    monkeypatch.setattr("backend.routers.agent.llm.resolve_allowed_model", resolve_model)

    response = client.post(
        "/api/agent/chat/stream",
        headers=_auth(token),
        json={
            "user_message": "推薦跑鞋",
            "history": [{"role": "user", "content": "之前"}],
            "provider": "openrouter",
            "model": "vendor/allowed:free",
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert '"type":"done"' in response.text
    assert run_agent.call_args.kwargs["user_id"] == user.id
    assert run_agent.call_args.kwargs["model"] == "vendor/allowed:free"
    resolve_model.assert_called_once()


def test_agent_stream_rejects_unapproved_model_before_llm_call(
    client, user_with_token, monkeypatch
):
    _, token = user_with_token
    run_agent = MagicMock()
    monkeypatch.setattr("backend.routers.agent.agent_service.run_agent_stream", run_agent)
    monkeypatch.setattr(
        "backend.routers.agent.llm.resolve_allowed_model",
        MagicMock(side_effect=llm.LLMError("不允許使用此模型")),
    )
    response = client.post(
        "/api/agent/chat/stream",
        headers=_auth(token),
        json={"user_message": "分析跑鞋", "model": "openai/gpt-paid"},
    )

    assert response.status_code == 400
    assert "不允許" in response.json()["detail"]
    run_agent.assert_not_called()


def test_agent_stream_rejects_malformed_or_oversized_payload(client, user_with_token):
    _, token = user_with_token
    malformed = client.post(
        "/api/agent/chat/stream",
        headers=_auth(token),
        json={"user_message": "分析跑鞋", "history": {"bad": "shape"}},
    )
    oversized = client.post(
        "/api/agent/chat/stream",
        headers=_auth(token),
        json={"user_message": "x" * 12_001},
    )

    assert malformed.status_code == 422
    assert oversized.status_code == 422


def test_rate_limit_windows_reset_after_their_fixed_window(db):
    window = rate_limits.Window("agent-user", "987654", 2, "AI 請求過於頻繁，請稍後再試。")
    engine = db.get_bind()
    rate_limits.consume(engine, [window], now=100)
    rate_limits.consume(engine, [window], now=101)
    with pytest.raises(HTTPException) as exc_info:
        rate_limits.consume(engine, [window], now=102)
    assert exc_info.value.status_code == 429
    assert exc_info.value.headers == {"Retry-After": "58"}

    rate_limits.consume(engine, [window], now=161)


def test_rate_limit_checks_never_commit_the_request_session(db, user_with_token):
    """SPEC-047: throttling uses its own transaction; pending request work is untouched."""
    user, _ = user_with_token
    request = SimpleNamespace(
        headers={}, client=SimpleNamespace(host="198.51.100.51"),
        app=SimpleNamespace(state=SimpleNamespace(settings=app.state.settings, db_engine=db.get_bind())),
    )
    db.add(Shoe(user_id=user.id, brand="Pending", model="Uncommitted", date="2026-01-01"))
    rate_limits.enforce_auth_rate_limit(request)
    db.rollback()
    assert db.query(Shoe).filter_by(brand="Pending").count() == 0
    assert _bucket(db, "auth-global", "global").event_count == 1


def test_update_shoe_not_found(client, user_with_token):
    _, token = user_with_token
    response = client.put("/api/shoes/999999", headers=_auth(token), json={"mileage": 5})
    assert response.status_code == 404
    assert response.json()["detail"] == "Shoe not found"


def test_monthly_mileage_rejects_negative_create_and_invalid_updates(client, db, user_with_token):
    user, token = user_with_token
    negative = client.post(
        "/api/monthly-mileage",
        headers=_auth(token),
        json={"year": 2026, "month": 1, "km": -1},
    )
    assert negative.status_code == 422

    entry = MonthlyMileage(user_id=user.id, year=2026, month=1, km=10)
    db.add(entry)
    db.commit()
    db.refresh(entry)

    bad_month = client.put(
        f"/api/monthly-mileage/{entry.id}", headers=_auth(token), json={"month": 0}
    )
    bad_km = client.put(
        f"/api/monthly-mileage/{entry.id}", headers=_auth(token), json={"km": -0.1}
    )
    null_km = client.put(
        f"/api/monthly-mileage/{entry.id}", headers=_auth(token), json={"km": None}
    )
    assert bad_month.status_code == 422
    assert bad_km.status_code == 422
    assert null_km.status_code == 422

    unchanged = client.put(
        f"/api/monthly-mileage/{entry.id}", headers=_auth(token), json={}
    )
    assert unchanged.status_code == 200

    non_conflicting_month = client.put(
        f"/api/monthly-mileage/{entry.id}", headers=_auth(token), json={"month": 2}
    )
    assert non_conflicting_month.status_code == 200
    assert non_conflicting_month.json()["month"] == 2


def _failing_db(existing=None):
    db = MagicMock()
    db.info = {}
    db.query.return_value.filter.return_value.first.return_value = existing
    db.commit.side_effect = RuntimeError("commit failed")
    return db


def test_create_routes_roll_back_failed_commits():
    user = SimpleNamespace(id=7)
    shoe_db = _failing_db()
    with pytest.raises(RuntimeError, match="commit failed"):
        create_shoe(
            schemas.ShoeCreate(brand="A", model="B", date="2026-01-01"),
            current_user=user,
            db=shoe_db,
            config=app.state.settings,
        )
    shoe_db.rollback.assert_called_once_with()

    mileage_db = _failing_db(existing=None)
    with pytest.raises(RuntimeError, match="commit failed"):
        create_monthly_mileage(
            schemas.MonthlyMileageCreate(year=2026, month=1, km=1),
            current_user=user,
            db=mileage_db,
        )
    mileage_db.rollback.assert_called_once_with()

    run_db = _failing_db(existing=SimpleNamespace(id=3))
    run_db.query.return_value.filter.return_value.first.side_effect = [
        SimpleNamespace(id=3),
        None,
    ]
    run_db.query.return_value.filter.return_value.count.return_value = 0
    with pytest.raises(RuntimeError, match="commit failed"):
        create_run(
            schemas.RunCreate(date="2026-08-01", km=5, shoe_id=3),
            current_user=user,
            db=run_db,
            config=app.state.settings,
        )
    run_db.rollback.assert_called_once_with()


def test_update_routes_roll_back_failed_commits():
    user = SimpleNamespace(id=7)
    shoe = SimpleNamespace(id=1, mileage=1)
    shoe_db = _failing_db(existing=shoe)
    with pytest.raises(RuntimeError, match="commit failed"):
        update_shoe(
            1,
            schemas.ShoeUpdate(mileage=2),
            current_user=user,
            db=shoe_db,
        )
    shoe_db.rollback.assert_called_once_with()

    entry = SimpleNamespace(id=1, year=2026, month=1, km=1)
    mileage_db = _failing_db(existing=entry)
    with pytest.raises(RuntimeError, match="commit failed"):
        update_monthly_mileage(
            1,
            schemas.MonthlyMileageUpdate(km=2),
            current_user=user,
            db=mileage_db,
        )
    mileage_db.rollback.assert_called_once_with()

    run = SimpleNamespace(id=1, date="2026-08-01", km=1, shoe_id=3)
    run_db = _failing_db(existing=run)
    run_db.query.return_value.filter.return_value.first.side_effect = [
        run,
        SimpleNamespace(id=4, km=10),
        SimpleNamespace(id=4, km=9),
    ]
    with pytest.raises(RuntimeError, match="commit failed"):
        update_run(
            1,
            schemas.RunUpdate(km=2),
            current_user=user,
            db=run_db,
        )
    run_db.rollback.assert_called_once_with()


def test_delete_routes_roll_back_failed_commits():
    user = SimpleNamespace(id=7)
    shoe_db = _failing_db(existing=SimpleNamespace(id=1))
    shoe_db.query.return_value.filter.return_value.first.side_effect = [
        SimpleNamespace(id=1),
        None,
    ]
    with pytest.raises(RuntimeError, match="commit failed"):
        delete_shoe(1, current_user=user, db=shoe_db)
    shoe_db.rollback.assert_called_once_with()

    mileage_db = _failing_db(existing=SimpleNamespace(id=1, year=2026, month=8))
    mileage_db.query.return_value.filter.return_value.scalar.return_value = 0
    with pytest.raises(RuntimeError, match="commit failed"):
        delete_monthly_mileage(1, current_user=user, db=mileage_db)
    mileage_db.rollback.assert_called_once_with()

    run_db = _failing_db(existing=SimpleNamespace(id=1))
    run_db.query.return_value.filter.return_value.first.side_effect = [
        SimpleNamespace(id=1, shoe_id=3, date="2026-08-01", km=5),
        SimpleNamespace(id=4, km=5),
    ]
    with pytest.raises(RuntimeError, match="commit failed"):
        delete_run(1, current_user=user, db=run_db)
    run_db.rollback.assert_called_once_with()


def test_signed_tokens_without_valid_user_are_rejected(client):
    no_subject = create_access_token({})
    missing_user = create_access_token({"sub": "does-not-exist"})
    assert client.get("/api/auth/me", headers=_auth(no_subject)).status_code == 401
    assert client.get("/api/auth/me", headers=_auth(missing_user)).status_code == 401


def test_static_asset_and_non404_http_errors(client):
    asset = client.get("/favicon.svg")
    assert asset.status_code == 200
    assert "svg" in asset.headers["content-type"]

    manifest = client.get("/manifest.webmanifest")
    assert manifest.status_code == 200
    assert manifest.json()["display"] == "standalone"

    service_worker = client.get("/service-worker.js")
    assert service_worker.status_code == 200
    assert "running-shoes-shell-v58" in service_worker.text

    agent_script = client.get("/app-agent.js")
    assert agent_script.status_code == 200
    assert "sendAgentMessage" in agent_script.text

    report_script = client.get("/app-reports.js")
    assert report_script.status_code == 200
    assert "generateReport" in report_script.text

    runs_script = client.get("/app-runs.js")
    assert runs_script.status_code == 200
    assert "fetchRunPages" in runs_script.text

    shoes_script = client.get("/app-shoes.js")
    assert shoes_script.status_code == 200
    assert "class ShoeModal" in shoes_script.text

    core_script = client.get("/app-core.js")
    assert core_script.status_code == 200
    assert "async function loadData" in core_script.text

    app_script = client.get("/app.js")
    assert app_script.status_code == 200
    assert "async function init" in app_script.text

    stylesheet = client.get("/styles.css")
    assert stylesheet.status_code == 200
    assert "--bg" in stylesheet.text

    method_error = client.post("/api/agent/providers")
    assert method_error.status_code == 405
    assert method_error.json()["detail"] == "Method Not Allowed"


def test_404_handler_falls_back_when_path_resolution_fails(monkeypatch):
    request = SimpleNamespace(
        url=SimpleNamespace(path="/broken"),
        app=SimpleNamespace(state=SimpleNamespace(frontend_dir=None)),
    )
    bad_frontend = MagicMock()
    bad_frontend.__truediv__.return_value.resolve.side_effect = OSError("bad path")
    request.app.state.frontend_dir = bad_frontend
    fallback = MagicMock(name="fallback-response")
    monkeypatch.setattr(app.state, "frontend_dir", bad_frontend)
    monkeypatch.setattr("backend.app_factory._index_response", MagicMock(return_value=fallback))

    from backend.app_factory import http_exception_handler

    response = asyncio.run(
        http_exception_handler(request, StarletteHTTPException(status_code=404, detail="missing"))
    )
    assert response is fallback


def test_xlsx_export_reports_missing_openpyxl(client, db, user_with_token, monkeypatch):
    user, token = user_with_token
    _add_export_shoes(db, user.id)
    original_import = builtins.__import__

    def fail_openpyxl(name, *args, **kwargs):
        if name == "openpyxl" or name.startswith("openpyxl."):
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail_openpyxl)
    response = client.get("/api/export?format=xlsx&mode=active", headers=_auth(token))
    assert response.status_code == 500
    assert "缺少 openpyxl" in response.json()["detail"]


def test_export_defensive_empty_rows_and_unknown_direct_format(
    db, user_with_token, monkeypatch
):
    user, _ = user_with_token
    _add_export_shoes(db, user.id)
    monkeypatch.setattr(
        "backend.services.exports.generate_shoe_rows",
        lambda *args, **kwargs: iter([]),
    )

    csv_response = export_shoes(format="csv", mode="all", current_user=user, db=db)
    xlsx_response = export_shoes(format="xlsx", mode="all", current_user=user, db=db)
    unknown_response = export_shoes(format="pdf", mode="all", current_user=user, db=db)

    assert csv_response.media_type == "text/csv; charset=utf-8"
    assert xlsx_response.media_type.endswith("spreadsheetml.sheet")
    assert unknown_response is None
