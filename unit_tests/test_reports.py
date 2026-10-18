"""Tests for the AI monthly report feature (one-shot generation + persistence)."""

import json
from datetime import UTC, date, datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend import llm, reports
from backend.auth import create_access_token, get_password_hash
from backend.database import Base, get_db
from backend.main import app
from backend.models import MonthlyReport, Run, Shoe, User
from backend.rate_limits import _agent_global_rate_events, _agent_ip_rate_events, _agent_rate_events
from backend.routers import reports as report_routes


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db):
    def override_get_db():
        yield db
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def clear_agent_rate_buckets():
    _agent_rate_events.clear()
    _agent_ip_rate_events.clear()
    _agent_global_rate_events.clear()
    yield
    _agent_rate_events.clear()
    _agent_ip_rate_events.clear()
    _agent_global_rate_events.clear()


@pytest.fixture
def mock_llm(monkeypatch):
    resolve = MagicMock(return_value="free-model:free")
    stream = MagicMock(return_value=iter(["# 9月報告", "本月跑量穩定。"]))
    monkeypatch.setattr(llm, "resolve_allowed_model", resolve)
    monkeypatch.setattr(llm, "call_llm_stream", stream)
    return stream


def _auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def _all_events(text):
    return [
        json.loads(line.removeprefix("data: ").strip())
        for line in text.split("\n")
        if line.startswith("data: ")
    ]


def _add_shoe(db, user_id, brand="Mizuno", model="Wave Sky 7", mileage=100):
    shoe = Shoe(
        user_id=user_id, brand=brand, model=model, date="2026-01-01",
        price=2390, orig_price=4780, mileage=mileage,
        expected_mileage=800, monthly_km=60, categories=["Daily"],
    )
    db.add(shoe)
    db.commit()
    db.refresh(shoe)
    return shoe


def _add_run(db, user_id, shoe_id, date, km):
    run = Run(user_id=user_id, shoe_id=shoe_id, date=date, km=km)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


# ── build_report_stats ────────────────────────────────────────

def test_build_report_stats_computes_month_numbers(db):
    user = User(username="statsuser", hashed_password=get_password_hash("pass1234"))
    db.add(user)
    db.commit()
    db.refresh(user)
    shoe_a = _add_shoe(db, user.id, brand="Mizuno", model="Wave Sky 7")
    shoe_b = _add_shoe(db, user.id, brand="New Balance", model="Rebel v5")
    _add_run(db, user.id, shoe_a.id, "2026-06-01", 10)
    _add_run(db, user.id, shoe_a.id, "2026-06-05", 8)
    _add_run(db, user.id, shoe_b.id, "2026-06-10", 12)
    _add_run(db, user.id, shoe_a.id, "2026-05-20", 20)
    _add_run(db, user.id, shoe_a.id, "2025-12-31", 5)

    stats = reports.build_report_stats(db, user.id, 2026, 6)

    assert stats["report_month"] == {"year": 2026, "month": 6}
    assert stats["month_run_stats"]["month_km"] == 30.0
    assert stats["month_run_stats"]["run_count"] == 3
    assert stats["month_run_stats"]["run_days"] == 3
    assert stats["month_run_stats"]["primary_shoe"] == {"shoe": "Mizuno Wave Sky 7", "km": 18.0}
    assert stats["prev_month_run_km"] == 20.0
    assert stats["prev_month_delta_km"] == 10.0
    assert stats["ytd_run_km"] == 50.0
    assert stats["running_goal"]["monthly_km"] == 125.0
    assert stats["running_goal"]["yearly_km"] == 1500.0
    assert stats["running_goal"]["active"] is True
    assert stats["overall_monthly_stats"]["status"] == "no_records"


def test_build_report_stats_handles_month_without_runs(db):
    user = User(username="emptyuser", hashed_password=get_password_hash("pass1234"))
    db.add(user)
    db.commit()
    db.refresh(user)
    _add_shoe(db, user.id)

    stats = reports.build_report_stats(db, user.id, 2026, 6)

    assert stats["month_run_stats"]["month_km"] == 0.0
    assert stats["month_run_stats"]["run_count"] == 0
    assert stats["month_run_stats"]["primary_shoe"] is None
    assert stats["prev_month_run_km"] == 0.0
    assert stats["prev_month_delta_km"] == 0.0
    assert stats["ytd_run_km"] == 0.0


def test_current_month_report_compares_the_same_period(db):
    user = User(username="sameperiod", hashed_password=get_password_hash("pass1234"))
    db.add(user)
    db.commit()
    shoe = _add_shoe(db, user.id)
    _add_run(db, user.id, shoe.id, "2026-09-05", 40)
    _add_run(db, user.id, shoe.id, "2026-09-20", 60)
    _add_run(db, user.id, shoe.id, "2026-10-05", 50)
    _add_run(db, user.id, shoe.id, "2026-10-20", 100)

    stats = reports.build_report_stats(
        db, user.id, 2026, 10, today=date(2026, 10, 13)
    )

    assert stats["month_run_stats"]["month_km"] == 50
    assert stats["prev_month_run_km"] == 40
    assert stats["prev_month_delta_km"] == 10
    assert stats["comparison_label"] == "較上月同期"
    assert stats["comparison_through_day"] == 13


def test_build_report_messages_only_provides_backend_numbers(db):
    user = User(username="msguser", hashed_password=get_password_hash("pass1234"))
    db.add(user)
    db.commit()
    db.refresh(user)
    _add_shoe(db, user.id)
    _add_run(db, user.id, db.query(Shoe).first().id, "2026-06-01", 10)

    stats = reports.build_report_stats(db, user.id, 2026, 6)
    messages = reports.build_report_messages(stats)

    assert [m["role"] for m in messages] == ["system", "user"]
    assert "不得自行計算、估算或杜撰" in messages[0]["content"]
    assert "目標達成率" in messages[0]["content"]
    assert "本月一句話摘要" in messages[0]["content"]
    assert "markdown 表格" in messages[0]["content"]
    assert "二級標題（##）" in messages[0]["content"]
    assert "鞋款輪替" not in messages[0]["content"]
    assert "鞋款壽命與退役提醒" in messages[0]["content"]
    serialized = json.dumps(stats, ensure_ascii=False)
    assert '"month_km"' in serialized and "10.0" in serialized


# ── POST /api/reports/generate ────────────────────────────────

def test_generate_report_streams_and_persists(client, db, user_with_token, mock_llm):
    user, token = user_with_token
    shoe = _add_shoe(db, user.id)
    _add_run(db, user.id, shoe.id, "2026-06-01", 10)

    res = client.post(
        "/api/reports/generate",
        headers={**_auth_header(token), "Fly-Client-IP": "198.51.100.1"},
        json={"year": 2026, "month": 6},
    )

    assert res.status_code == 200
    events = _all_events(res.text)
    assert [e["type"] for e in events] == ["token", "token", "done"]
    assert events[-1]["model"] == "free-model:free"
    assert mock_llm.call_count == 1

    row = db.query(MonthlyReport).filter(MonthlyReport.user_id == user.id).one()
    assert row.content_md == "# 9月報告本月跑量穩定。"
    assert row.model == "free-model:free"
    assert row.stats_json["report_month"] == {"year": 2026, "month": 6}
    assert row.stats_json["month_run_stats"]["month_km"] == 10.0


def test_generate_report_uses_the_model_selected_in_report_tab(
    client, user_with_token, monkeypatch
):
    _user, token = user_with_token
    resolve = MagicMock(return_value="vendor/selected:free")
    stream = MagicMock(return_value=iter(["完成"]))
    monkeypatch.setattr(llm, "resolve_allowed_model", resolve)
    monkeypatch.setattr(llm, "call_llm_stream", stream)

    response = client.post(
        "/api/reports/generate",
        headers={**_auth_header(token), "Fly-Client-IP": "198.51.100.11"},
        json={"year": 2026, "month": 6, "model": "vendor/selected:free"},
    )

    assert response.status_code == 200
    resolve.assert_called_once_with(
        llm.LLMProvider.openrouter, "vendor/selected:free"
    )
    assert stream.call_args.args[1] == "vendor/selected:free"


def test_generate_report_regenerate_overwrites_same_month(
    client, db, user_with_token, mock_llm
):
    user, token = user_with_token
    headers = {**_auth_header(token), "Fly-Client-IP": "198.51.100.2"}
    payload = {"year": 2026, "month": 6}
    assert client.post("/api/reports/generate", headers=headers, json=payload).status_code == 200
    mock_llm.return_value = iter(["第二版報告"])
    assert client.post("/api/reports/generate", headers=headers, json=payload).status_code == 200

    rows = db.query(MonthlyReport).filter(MonthlyReport.user_id == user.id).all()
    assert len(rows) == 1
    assert rows[0].content_md == "第二版報告"


def test_generate_report_rejects_future_month(client, user_with_token, mock_llm):
    _user, token = user_with_token
    now = datetime.now(UTC)

    res = client.post(
        "/api/reports/generate",
        headers={**_auth_header(token), "Fly-Client-IP": "198.51.100.3"},
        json={"year": now.year + 1, "month": now.month},
    )

    assert res.status_code == 422
    assert mock_llm.call_count == 0


def test_generate_report_uses_taipei_calendar_day(
    client, user_with_token, mock_llm, monkeypatch
):
    _user, token = user_with_token
    monkeypatch.setattr(report_routes, "_local_today", lambda: date(2026, 11, 1))

    response = client.post(
        "/api/reports/generate",
        headers=_auth_header(token),
        json={"year": 2026, "month": 11},
    )

    assert response.status_code == 200
    assert mock_llm.call_count == 1


def test_generate_report_rejects_invalid_month(client, user_with_token):
    _user, token = user_with_token

    res = client.post(
        "/api/reports/generate",
        headers={**_auth_header(token), "Fly-Client-IP": "198.51.100.4"},
        json={"year": 2026, "month": 13},
    )

    assert res.status_code == 422


def test_generate_report_llm_error_persists_nothing(client, db, user_with_token, monkeypatch):
    _user, token = user_with_token
    monkeypatch.setattr(llm, "resolve_allowed_model", MagicMock(return_value="free-model:free"))
    monkeypatch.setattr(
        llm, "call_llm_stream", MagicMock(side_effect=llm.LLMError("model unavailable"))
    )

    res = client.post(
        "/api/reports/generate",
        headers={**_auth_header(token), "Fly-Client-IP": "198.51.100.5"},
        json={"year": 2026, "month": 6},
    )

    assert res.status_code == 200
    events = _all_events(res.text)
    assert events[-1]["type"] == "error"
    assert "model unavailable" in events[-1]["text"]
    assert db.query(MonthlyReport).count() == 0


def test_generate_report_requires_auth(client):
    assert client.post("/api/reports/generate", json={"year": 2026, "month": 6}).status_code == 401
    assert client.get("/api/reports").status_code == 401


# ── GET /api/reports ──────────────────────────────────────────

def test_get_saved_report(client, db, user_with_token):
    user, token = user_with_token
    db.add(MonthlyReport(
        user_id=user.id, year=2026, month=6,
        content_md="# 報告", model="m:free", stats_json={"report_month": {"year": 2026, "month": 6}},
    ))
    db.commit()

    res = client.get("/api/reports/2026/6", headers=_auth_header(token))

    assert res.status_code == 200
    body = res.json()
    assert body["content_md"] == "# 報告"
    assert body["model"] == "m:free"
    assert body["stats_json"]["report_month"] == {"year": 2026, "month": 6}


def test_get_missing_report_returns_404(client, user_with_token):
    _user, token = user_with_token
    res = client.get("/api/reports/2026/6", headers=_auth_header(token))
    assert res.status_code == 404


def test_reports_are_isolated_per_user(client, db, user_with_token):
    user, _token = user_with_token
    db.add(MonthlyReport(
        user_id=user.id, year=2026, month=6,
        content_md="# A 的報告", model="m:free", stats_json={},
    ))
    other = User(username="otheruser", hashed_password=get_password_hash("pass1234"))
    db.add(other)
    db.commit()
    db.refresh(other)
    other_token = create_access_token(data={"sub": other.username})

    empty_list = client.get("/api/reports", headers=_auth_header(other_token))
    stolen = client.get("/api/reports/2026/6", headers=_auth_header(other_token))

    assert empty_list.status_code == 200
    assert empty_list.json() == []
    assert stolen.status_code == 404


def test_reports_list_orders_newest_first(client, db, user_with_token):
    user, token = user_with_token
    db.add_all([
        MonthlyReport(user_id=user.id, year=2026, month=5, content_md="5月", model="m:free", stats_json={}),
        MonthlyReport(user_id=user.id, year=2026, month=6, content_md="6月", model="m:free", stats_json={}),
    ])
    db.commit()

    res = client.get("/api/reports", headers=_auth_header(token))

    assert res.status_code == 200
    assert [(r["year"], r["month"]) for r in res.json()] == [(2026, 6), (2026, 5)]
    assert "content_md" not in res.json()[0]
