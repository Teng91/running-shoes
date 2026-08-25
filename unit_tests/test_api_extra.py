"""Additional API coverage for exports, spending, agent routes, and failures."""

import asyncio
import builtins
import csv
import io
import re
from types import SimpleNamespace
from unittest.mock import MagicMock

import openpyxl
import pytest
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend import schemas
from backend.auth import create_access_token
from backend.database import get_db
from backend.main import (
    app,
    create_monthly_mileage,
    create_shoe,
    delete_monthly_mileage,
    delete_shoe,
    export_shoes,
    update_monthly_mileage,
    update_shoe,
)
from backend.models import MonthlyMileage, Shoe


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
    monkeypatch.setattr("backend.main.llm.list_providers", list_providers)

    public_response = client.get("/api/agent/providers")
    refresh_response = client.post("/api/agent/models/refresh", headers=_auth(token))

    assert public_response.json() == [{"id": "openrouter"}]
    assert refresh_response.json() == [{"id": "openrouter"}]
    assert list_providers.call_args_list[0].kwargs == {}
    assert list_providers.call_args_list[1].kwargs == {"force": True}


def test_agent_stream_route_forwards_payload_and_user(client, user_with_token, monkeypatch):
    user, token = user_with_token
    run_agent = MagicMock(return_value=iter(['data: {"type":"done"}\n\n']))
    monkeypatch.setattr("backend.main.agent.run_agent_stream", run_agent)

    response = client.post(
        "/api/agent/chat/stream",
        headers=_auth(token),
        json={
            "user_message": "推薦跑鞋",
            "history": [{"role": "user", "content": "之前"}],
            "provider": "openrouter",
            "model": "openrouter/free",
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert '"type":"done"' in response.text
    assert run_agent.call_args.kwargs["user_id"] == user.id
    assert run_agent.call_args.kwargs["model"] == "openrouter/free"


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
    assert negative.status_code == 400

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
    assert bad_month.status_code == 400
    assert bad_km.status_code == 400

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


def test_delete_routes_roll_back_failed_commits():
    user = SimpleNamespace(id=7)
    shoe_db = _failing_db(existing=SimpleNamespace(id=1))
    with pytest.raises(RuntimeError, match="commit failed"):
        delete_shoe(1, current_user=user, db=shoe_db)
    shoe_db.rollback.assert_called_once_with()

    mileage_db = _failing_db(existing=SimpleNamespace(id=1))
    with pytest.raises(RuntimeError, match="commit failed"):
        delete_monthly_mileage(1, current_user=user, db=mileage_db)
    mileage_db.rollback.assert_called_once_with()


def test_signed_tokens_without_valid_user_are_rejected(client):
    no_subject = create_access_token({})
    missing_user = create_access_token({"sub": "does-not-exist"})
    assert client.get("/api/auth/me", headers=_auth(no_subject)).status_code == 401
    assert client.get("/api/auth/me", headers=_auth(missing_user)).status_code == 401


def test_static_asset_and_non404_http_errors(client):
    asset = client.get("/favicon.svg")
    assert asset.status_code == 200
    assert "svg" in asset.headers["content-type"]

    method_error = client.post("/api/agent/providers")
    assert method_error.status_code == 405
    assert method_error.json()["detail"] == "Method Not Allowed"


def test_404_handler_falls_back_when_path_resolution_fails(monkeypatch):
    request = SimpleNamespace(url=SimpleNamespace(path="/broken"))
    bad_frontend = MagicMock()
    bad_frontend.__truediv__.return_value.resolve.side_effect = OSError("bad path")
    fallback = MagicMock(name="fallback-response")
    monkeypatch.setattr("backend.main.frontend_dir", bad_frontend)
    monkeypatch.setattr("backend.main._index_response", MagicMock(return_value=fallback))

    from backend.main import http_exception_handler

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
    monkeypatch.setattr("backend.main._generate_shoe_rows", lambda *args, **kwargs: iter([]))

    csv_response = export_shoes(format="csv", mode="all", current_user=user, db=db)
    xlsx_response = export_shoes(format="xlsx", mode="all", current_user=user, db=db)
    unknown_response = export_shoes(format="pdf", mode="all", current_user=user, db=db)

    assert csv_response.media_type == "text/csv; charset=utf-8"
    assert xlsx_response.media_type.endswith("spreadsheetml.sheet")
    assert unknown_response is None
