"""SPEC-147: every account counts "today", months and the run-date limit in its own IANA zone."""

import io
import json
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from backend import clock, models, strava_import
from backend.dependencies import get_db
from backend.main import app
from backend.read_models.account_clock import account_today, account_zone
from backend.services import email_codes
from backend.tools import db_tools
from unit_tests.token_helpers import token_for

# 00:30 on 1 February in Taipei, still 06:30 on 31 January in Honolulu (UTC-10).
MIDNIGHT_IN_TAIPEI = datetime(2026, 1, 31, 16, 30, tzinfo=UTC)


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: (yield db)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def freeze(monkeypatch):
    def at(instant: datetime) -> None:
        class FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return instant.astimezone(tz) if tz is not None else instant.replace(tzinfo=None)

        monkeypatch.setattr(clock, "datetime", FrozenDatetime)

    at(MIDNIGHT_IN_TAIPEI)
    return at


def _account(db, name: str, zone: str | None = None):
    user = models.User(username=name, hashed_password="synthetic")
    if zone is not None:
        user.timezone = zone
    db.add(user)
    db.commit()
    db.refresh(user)
    return user, {"Authorization": f"Bearer {token_for(user)}"}


def _shoe(client, headers) -> int:
    response = client.post("/api/shoes", headers=headers, json={"brand": "Zone", "model": "Runner", "date": "2025-12-01"})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _run(client, headers, shoe_id: int, day: str, **extra):
    return client.post("/api/runs", headers={**headers, **extra}, json={"date": day, "km": 5, "shoe_id": shoe_id})


def test_new_accounts_start_in_taipei_and_each_account_changes_only_its_own_zone(client, db, freeze):
    """AC-4: GET /me names the zone; PUT /timezone validates it and touches only the signed-in account."""
    owner, headers = _account(db, "zone-owner")
    other, other_headers = _account(db, "zone-other")
    assert owner.timezone == "Asia/Taipei"
    assert client.get("/api/auth/me", headers=headers).json()["timezone"] == "Asia/Taipei"

    changed = client.put("/api/auth/timezone", headers=headers, json={"timezone": "Pacific/Honolulu"})
    assert changed.status_code == 200, changed.text
    assert changed.json() == {"timezone": "Pacific/Honolulu", "today": "2026-01-31"}
    assert client.get("/api/auth/me", headers=headers).json()["timezone"] == "Pacific/Honolulu"
    assert client.get("/api/auth/me", headers=other_headers).json()["timezone"] == "Asia/Taipei"

    for bad in ("Mars/Olympus_Mons", "", "+08:00", "UTC+8", "Factory", "asia/taipei", "x" * 65, None, 8):
        response = client.put("/api/auth/timezone", headers=headers, json={"timezone": bad})
        assert response.status_code == 422, bad
    smuggled = client.put("/api/auth/timezone", headers=headers, json={"timezone": "Asia/Tokyo", "user_id": other.id})
    assert smuggled.status_code == 422, "no field can aim the change at another account"
    assert client.put("/api/auth/timezone", json={"timezone": "Asia/Tokyo"}).status_code == 401
    db.expire_all()
    assert (db.get(models.User, owner.id).timezone, db.get(models.User, other.id).timezone) == (
        "Pacific/Honolulu", "Asia/Taipei")
    assert account_today(db, owner.id) == date(2026, 1, 31)
    assert account_today(db, other.id) == date(2026, 2, 1)


def test_a_stored_zone_that_is_no_longer_known_counts_in_the_default_zone(db, freeze):
    user, _ = _account(db, "retired-zone", "Mars/Olympus_Mons")
    assert account_zone(db, user.id) is clock.DEFAULT_ZONE
    assert account_today(db, user.id) == date(2026, 2, 1)
    assert account_today(db, 999_999) == date(2026, 2, 1), "an unknown account reads no other account's zone"


def test_the_run_date_limit_is_today_on_the_account_calendar(client, db, freeze):
    """AC-5: 1 February is today in Taipei but the future in Honolulu, for creates, keyed creates and edits."""
    _, taipei = _account(db, "limit-taipei")
    _, honolulu = _account(db, "limit-honolulu", "Pacific/Honolulu")
    taipei_shoe, honolulu_shoe = _shoe(client, taipei), _shoe(client, honolulu)

    assert _run(client, taipei, taipei_shoe, "2026-02-01").status_code == 200
    refused = _run(client, honolulu, honolulu_shoe, "2026-02-01")
    assert refused.status_code == 422
    assert "Pacific/Honolulu：2026-01-31" in refused.json()["detail"]
    keyed = _run(client, honolulu, honolulu_shoe, "2026-02-01", **{"Idempotency-Key": "zone-offline-queue-0001"})
    assert keyed.status_code == 422, "an offline run replays through the same rule"

    run = _run(client, honolulu, honolulu_shoe, "2026-01-31")
    assert run.status_code == 200
    run_id = run.json()["id"]
    assert client.put(f"/api/runs/{run_id}", headers=honolulu, json={"date": "2026-02-01"}).status_code == 422
    assert client.put(f"/api/runs/{run_id}", headers=honolulu, json={"km": 6}).status_code == 200, (
        "an edit that keeps the date is not re-checked")
    moved = client.put(f"/api/runs/{run_id}", headers=honolulu, json={"date": "2026-01-30"})
    assert moved.status_code == 200 and moved.json()["date"] == "2026-01-30"
    # Past every zone's today (UTC+14 is on 1 February too), the request schema refuses it.
    assert _run(client, taipei, taipei_shoe, "2026-02-02").status_code == 422


def test_months_and_goal_progress_turn_over_at_the_account_midnight(client, db, freeze):
    """AC-6: at the same instant February is the current month in Taipei and a future one in Honolulu."""
    _, taipei = _account(db, "month-taipei")
    _, honolulu = _account(db, "month-honolulu", "Pacific/Honolulu")
    for headers, state in ((taipei, "current"), (honolulu, "future")):
        progress = client.get("/api/running-goal/progress?year=2026&month=2", headers=headers).json()
        assert progress["month_state"] == state
        dashboard = client.get("/api/analytics/dashboard?year=2026&month=2", headers=headers).json()
        assert dashboard["goal"]["month_state"] == state
    january = client.get("/api/running-goal/progress?year=2026&month=1", headers=honolulu).json()
    assert (january["month_state"], january["elapsed_days"], january["remaining_days"]) == ("current", 31, 0)
    report = client.post("/api/reports/generate", headers=honolulu, json={"year": 2026, "month": 2})
    assert report.status_code == 422 and report.json()["detail"] == "未來月份無法產生報告"
    trends = client.get("/api/analytics/trends?year=2026", headers=honolulu).json()
    assert trends["end_date"] == "2026-01-31"


def test_agent_tools_count_the_year_in_the_account_zone(db, freeze):
    """AC-7: on 31 December in Honolulu it is already New Year in Taipei."""
    freeze(datetime(2026, 12, 31, 20, 0, tzinfo=UTC))
    taipei, _ = _account(db, "tool-taipei")
    honolulu, _ = _account(db, "tool-honolulu", "Pacific/Honolulu")
    assert json.loads(db_tools.running_goal_progress(db, taipei.id))["year"] == 2027
    assert json.loads(db_tools.running_goal_progress(db, honolulu.id))["year"] == 2026
    assert json.loads(db_tools.year_review(db, honolulu.id))["year"] == 2026


def test_strava_activities_are_dated_on_the_account_calendar():
    """AC-8: a 16:00 UTC run is the next morning in Taipei and the same morning in Honolulu."""
    csv_text = '活動 ID,活動日期,活動類型,活動裝備,距離\nz1,"Jan 30, 2026, 4:00:00 PM",跑步,X,5000\n'
    taipei, _, _ = strava_import.parse_csv(csv_text.encode(), max_rows=10)
    honolulu, _, _ = strava_import.parse_csv(csv_text.encode(), max_rows=10, zone=ZoneInfo("Pacific/Honolulu"))
    assert (taipei[0]["date"], taipei[0]["utc_date"]) == ("2026-01-31", "2026-01-30")
    assert honolulu[0]["date"] == "2026-01-30"
    # Pre-SPEC-047 UTC dates are only corrected for accounts still on Taiwan time.
    assert honolulu[0]["utc_date"] == honolulu[0]["date"]
    assert strava_import.date_corrections(honolulu, {"z1": "2026-01-30"}) == []
    assert strava_import.date_corrections(taipei, {"z1": "2026-01-30"})[0]["to_date"] == "2026-01-31"


def test_strava_import_upload_uses_the_signed_in_account_zone(client, db, freeze):
    """The same activity falls inside a 30 January range for Honolulu and outside it for Taipei."""
    _, taipei = _account(db, "strava-taipei")
    _, honolulu = _account(db, "strava-honolulu", "Pacific/Honolulu")
    csv_text = '活動 ID,活動日期,活動類型,活動裝備,距離\nz2,"Jan 30, 2026, 4:00:00 PM",跑步,X,5000\n'
    for headers, (inside, outside) in ((honolulu, (1, 0)), (taipei, (0, 1))):
        response = client.post("/api/runs/import/strava/preview", headers=headers, data={
            "start_date": "2026-01-30", "end_date": "2026-01-30"}, files={
            "file": ("activities.csv", io.BytesIO(csv_text.encode("utf-8")), "text/csv")})
        assert response.status_code == 200, response.text
        assert (response.json()["run_count"], response.json()["filtered_out"]) == (inside, outside)


def test_password_notice_shows_the_change_on_the_account_clock(db):
    user, _ = _account(db, "notice-tokyo", "Asia/Tokyo")
    user.email = "notice@example.test"
    db.commit()
    sent = []
    email_codes.notify_password_changed(db, user.username, email_codes.CHANGED_BY_USER,
                                        send=lambda *message: sent.append(message),
                                        when=datetime(2026, 1, 31, 16, 30, tzinfo=UTC))
    assert "2026-02-01 01:30（Asia/Tokyo，UTC+09:00）" in sent[0][2]
