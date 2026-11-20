
import asyncio
import io
import json
import threading
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient

from backend.clock import local_today
from backend.dependencies import get_db
from backend.main import app
from backend.middleware import UploadLimitMiddleware
from backend.models import MonthlyMileage, Run, Shoe, StravaImport
from backend.routers import strava as strava_routes
from backend.routers.strava import _parse_strava_csv
from backend.services.strava_imports import ImportResult
from unit_tests.test_api import _auth_header

CSV = "活動 ID,活動日期,活動類型,活動裝備,距離\n" \
    "1001,2026年8月30日 上午11:40:36,跑步,Mizuno Wave Sky 7,5250\n" \
    "1002,2026年8月29日,步行,Mizuno Wave Sky 7,3000\n" \
    "1003,2026年8月28日,跑步,,6100\n"


@pytest.mark.parametrize("action", ["preview", "import"])
def test_strava_worker_keeps_event_loop_responsive(monkeypatch, action):
    loop_thread = threading.get_ident()
    started, release = threading.Event(), threading.Event()
    worker_threads = []
    session = object()

    def parse(raw, max_rows):
        worker_threads.append(threading.get_ident())
        assert threading.get_ident() != loop_thread
        assert raw == b"mock csv"
        started.set()
        assert release.wait(timeout=3), "event loop did not release worker"
        return [], 0, []

    def service(db, user_id, *args, **kwargs):
        assert db is session and user_id == 7
        assert threading.get_ident() == worker_threads[0]
        if action == "preview":
            return {"run_count": 0}
        return ImportResult(0, 0, 0, 0, 0, 0.0, 0)

    monkeypatch.setattr(strava_routes, "_parse_strava_csv", parse)
    monkeypatch.setattr(strava_routes.strava_imports, "preview" if action == "preview" else "import_runs", service)
    budget = []
    monkeypatch.setattr(strava_routes, "enforce_strava_upload_limits", lambda request, user_id: budget.append(user_id))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(strava_upload_slot=threading.Lock())))

    async def scenario():
        file = UploadFile(io.BytesIO(b"mock csv"), filename="test.csv")
        kwargs = dict(request=request, config=app.state.settings, file=file, start_date="", end_date="",
                      current_user=SimpleNamespace(id=7), db=session)
        if action == "import":
            kwargs["mapping"] = "{}"
            kwargs["conflicts"] = "{}"
        route = strava_routes.preview_strava_import if action == "preview" else strava_routes.import_strava_runs
        task = asyncio.create_task(route(**kwargs))
        try:
            async def wait_started():
                while not started.is_set():
                    await asyncio.sleep(0.001)
            await asyncio.wait_for(wait_started(), timeout=1)
            # The worker is still blocked, but this coroutine continues on the loop.
            assert not task.done()
            # SPEC-074: a second upload while one is parsing is turned away, not queued.
            with pytest.raises(HTTPException) as busy:
                await route(**kwargs)
            assert busy.value.status_code == 429 and "另一個 Strava 匯入" in busy.value.detail
            assert budget == [7], "a busy rejection does not spend the account's budget"
            release.set()
            result = await asyncio.wait_for(task, timeout=3)
            assert result.get("run_count", result.get("imported")) == 0
        finally:
            release.set()
            await file.close()
            if not task.done():
                await task

    asyncio.run(scenario())


@pytest.fixture
def client(db):
    def override_get_db():
        yield db
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def upload(
    client,
    path,
    token,
    mapping=None,
    start_date="",
    csv_content=CSV,
    end_date="",
):
    data = {"mapping": mapping} if mapping is not None else {}
    if start_date:
        data["start_date"] = start_date
    if end_date:
        data["end_date"] = end_date
    return client.post(path, headers=_auth_header(token), files={
        "file": ("activities.csv", io.BytesIO(csv_content.encode("utf-8-sig")), "text/csv")
    }, data=data)


def test_strava_parser_rejects_future_activities():
    future = (local_today() + timedelta(days=1)).isoformat()
    raw = (
        "活動 ID,活動日期,活動類型,活動裝備,距離\n"
        f"future-1,{future},跑步,Test Shoe,5000\n"
    ).encode()

    rows, invalid, warnings = _parse_strava_csv(raw, 50_000)

    assert rows == []
    assert invalid == 1
    assert warnings == ["已略過 1 筆格式不完整的跑步活動"]


def test_strava_preview_filters_runs_and_suggests_shoe(client, db, user_with_token):
    user, token = user_with_token
    shoe = Shoe(user_id=user.id, brand="Mizuno", model="Wave Sky 7", date="2026-01-01")
    db.add(shoe)
    db.commit()
    response = upload(client, "/api/runs/import/strava/preview", token)
    assert response.status_code == 200
    result = response.json()
    assert result["run_count"] == 2
    assert result["duplicate_count"] == 0
    groups = {group["gear"]: group for group in result["gear_groups"]}
    assert groups["Mizuno Wave Sky 7"]["suggested_shoe_id"] == shoe.id
    assert groups["Mizuno Wave Sky 7"]["km"] == 5.25
    assert groups[""]["suggested_shoe_id"] is None


def test_strava_import_is_idempotent_and_syncs_totals(client, db, user_with_token):
    user, token = user_with_token
    shoe = Shoe(
        user_id=user.id,
        brand="Mizuno",
        model="Wave Sky 7",
        date="2026-01-01",
        mileage=10,
    )
    db.add(shoe)
    db.commit()
    mapping = f'{{"Mizuno Wave Sky 7": {shoe.id}, "": null}}'
    first = upload(client, "/api/runs/import/strava", token, mapping)
    assert first.status_code == 200
    assert first.json()["imported"] == 1
    assert first.json()["skipped_unmapped"] == 1
    assert first.json()["synced_mileage"] == 5.25
    db.refresh(shoe)
    assert shoe.mileage == 15.25
    monthly = db.query(MonthlyMileage).filter_by(
        user_id=user.id, year=2026, month=8
    ).one()
    assert monthly.km == 5.25
    second = upload(client, "/api/runs/import/strava", token, mapping)
    assert second.status_code == 200
    assert second.json()["imported"] == 0
    assert second.json()["skipped_duplicate"] == 1
    assert second.json()["synced_mileage"] == 0
    db.refresh(shoe)
    db.refresh(monthly)
    assert shoe.mileage == 15.25
    assert monthly.km == 5.25
    assert db.query(Run).filter(Run.user_id == user.id).count() == 1
    history = client.get("/api/runs/import/strava/history", headers=_auth_header(token))
    assert history.status_code == 200
    assert len(history.json()) == 2
    assert history.json()[0]["imported_count"] == 0
    assert history.json()[0]["duplicate_count"] == 1
    assert history.json()[0]["imported_at"].endswith("+00:00")
    assert history.json()[1]["imported_count"] == 1
    assert history.json()[1]["imported_km"] == 5.25

    preview_again = upload(client, "/api/runs/import/strava/preview", token)
    assert preview_again.status_code == 200
    assert preview_again.json()["run_count"] == 2
    assert preview_again.json()["duplicate_count"] == 1
    assert preview_again.json()["importable_count"] == 1
    assert preview_again.json()["importable_km"] == 6.1
    assert preview_again.json()["gear_groups"] == [
        {
            "gear": "",
            "count": 1,
            "km": 6.1,
            "first_date": "2026-08-28",
            "conflict_count": 0,
            "suggested_shoe_id": None,
            "shoe_name": None,
            "ambiguous_match": False,
        }
    ]


def test_strava_import_rejects_foreign_shoe_mapping(client, db, user_with_token):
    _user, token = user_with_token
    foreign_shoe = Shoe(user_id=999, brand="Mizuno", model="Wave Sky 7", date="2026-01-01")
    db.add(foreign_shoe)
    db.commit()
    response = upload(client, "/api/runs/import/strava", token, f'{{"Mizuno Wave Sky 7": {foreign_shoe.id}}}')
    assert response.status_code == 404
    assert db.query(StravaImport).count() == 0


def test_strava_import_history_is_isolated_by_user(client, db, user_with_token):
    user, token = user_with_token
    db.add(StravaImport(user_id=user.id, imported_count=2, imported_km=8))
    db.add(StravaImport(user_id=999, imported_count=9, imported_km=99))
    db.commit()
    response = client.get("/api/runs/import/strava/history", headers=_auth_header(token))
    assert response.status_code == 200
    assert [item["imported_count"] for item in response.json()] == [2]


def test_strava_import_history_is_bounded(client, db, user_with_token, monkeypatch):

    user, token = user_with_token
    shoe = Shoe(user_id=user.id, brand="Mizuno", model="Wave Sky 7", date="2026-01-01")
    db.add(shoe)
    db.commit()
    monkeypatch.setattr(app.state, "settings", replace(app.state.settings, max_strava_import_history_per_user=2))
    mapping = f'{{"Mizuno Wave Sky 7": {shoe.id}, "": null}}'
    for _ in range(3):
        assert upload(client, "/api/runs/import/strava", token, mapping).status_code == 200
    assert db.query(StravaImport).filter_by(user_id=user.id).count() == 2


def test_strava_preview_rejects_missing_columns(client, user_with_token):
    _user, token = user_with_token
    response = client.post("/api/runs/import/strava/preview", headers=_auth_header(token), files={
        "file": ("bad.csv", io.BytesIO(b"foo,bar\n1,2\n"), "text/csv")
    })
    assert response.status_code == 400
    assert "必要欄位" in response.json()["detail"]


def test_strava_start_date_filters_older_runs_and_allows_shared_mapping(client, db, user_with_token):
    user, token = user_with_token
    shoe = Shoe(user_id=user.id, brand="Mizuno", model="Wave Sky 7", date="2024-01-01")
    db.add(shoe)
    db.commit()
    csv_content = CSV + "999,2025年6月30日,跑步,Fila Bon Voyage,4000\n" \
        "1000,2025年7月1日,跑步,Fila Bon Voyage,5000\n"
    mapping = f'{{"Mizuno Wave Sky 7": {shoe.id}, "Fila Bon Voyage": {shoe.id}, "": null}}'
    response = upload(
        client,
        "/api/runs/import/strava",
        token,
        mapping,
        "2025-07-01",
        csv_content,
    )
    assert response.status_code == 200
    assert response.json()["filtered_out"] == 1
    assert response.json()["imported"] == 2
    assert response.json()["synced_mileage"] == 10.25
    db.refresh(shoe)
    assert shoe.mileage == 10.25
    assert db.query(Run).filter(Run.shoe_id == shoe.id).count() == 2


def test_strava_end_date_excludes_manual_log_period(client, user_with_token):
    _user, token = user_with_token
    response = upload(
        client,
        "/api/runs/import/strava/preview",
        token,
        start_date="2025-07-01",
        end_date="2026-07-31",
    )
    assert response.status_code == 200
    assert response.json()["run_count"] == 0
    assert response.json()["filtered_out"] == 2
    invalid_range = upload(
        client,
        "/api/runs/import/strava/preview",
        token,
        start_date="2026-08-01",
        end_date="2026-07-31",
    )
    assert invalid_range.status_code == 400
    assert invalid_range.json()["detail"] == "起始日期不可晚於結束日期"


@pytest.mark.parametrize("distance", ["nan", "0.1", "4.9"])
def test_strava_preview_rejects_non_finite_or_zero_rounded_distance(
    client, user_with_token, distance
):
    _user, token = user_with_token
    csv_content = (
        "活動 ID,活動日期,活動類型,活動裝備,距離\n"
        f"1,2026年1月1日,跑步,Shoe,{distance}\n"
    )
    response = upload(
        client, "/api/runs/import/strava/preview", token, csv_content=csv_content
    )
    assert response.status_code == 200
    assert response.json()["run_count"] == 0
    assert response.json()["invalid_count"] == 1


def test_strava_preview_does_not_guess_between_duplicate_shoe_names(
    client, db, user_with_token
):
    user, token = user_with_token
    db.add_all([
        Shoe(user_id=user.id, brand="Mizuno", model="Wave Sky 7", date="2024-01-01"),
        Shoe(user_id=user.id, brand="Mizuno", model="Wave Sky 7", date="2025-01-01"),
    ])
    db.commit()
    response = upload(client, "/api/runs/import/strava/preview", token)
    group = next(
        item for item in response.json()["gear_groups"]
        if item["gear"] == "Mizuno Wave Sky 7"
    )
    assert group["suggested_shoe_id"] is None
    assert group["ambiguous_match"] is True


def test_strava_preview_preserves_unicode_when_matching_gear(
    client, db, user_with_token
):
    user, token = user_with_token
    shoe = Shoe(user_id=user.id, brand="跑鞋", model="天空七號", date="2025-01-01")
    db.add(shoe)
    db.commit()
    csv_content = (
        "活動 ID,活動日期,活動類型,活動裝備,距離\n"
        "1,2026年1月1日,跑步,跑鞋 天空七號,5000\n"
    )
    response = upload(
        client, "/api/runs/import/strava/preview", token, csv_content=csv_content
    )
    assert response.status_code == 200
    assert response.json()["gear_groups"][0]["suggested_shoe_id"] == shoe.id


def test_strava_preview_accepts_official_english_headers_and_dates(
    client, db, user_with_token
):
    user, token = user_with_token
    shoe = Shoe(user_id=user.id, brand="Mizuno", model="Wave Sky 7", date="2025-01-01")
    db.add(shoe)
    db.commit()
    csv_content = (
        "Activity ID,Activity Date,Activity Type,Activity Gear,Distance\n"
        '1,"Aug 30, 2026, 11:40:36 AM",Run,Mizuno Wave Sky 7,5250\n'
        '2,"August 31, 2026, 1:05:02 PM",Run,Mizuno Wave Sky 7,6100\n'
    )
    response = upload(
        client, "/api/runs/import/strava/preview", token, csv_content=csv_content
    )
    assert response.status_code == 200
    result = response.json()
    assert result["run_count"] == 2
    assert result["invalid_count"] == 0
    assert result["gear_groups"][0]["gear"] == "Mizuno Wave Sky 7"
    assert result["gear_groups"][0]["suggested_shoe_id"] == shoe.id
    assert result["gear_groups"][0]["km"] == 11.35
    parsed, invalid, _warnings = _parse_strava_csv(csv_content.encode("utf-8"), 50_000)
    assert invalid == 0
    assert [row["date"] for row in parsed] == ["2026-08-30", "2026-08-31"]


def test_strava_upload_size_limit_is_bounded_before_full_read(
    client, user_with_token, monkeypatch
):

    _user, token = user_with_token
    monkeypatch.setattr(app.state, "settings", replace(app.state.settings, max_strava_csv_bytes=10))
    response = upload(client, "/api/runs/import/strava/preview", token)
    assert response.status_code == 413


def test_strava_parser_rejects_excess_rows_without_materializing_all(monkeypatch):

    csv_content = (
        "活動 ID,活動日期,活動類型,活動裝備,距離\n"
        "1,2026年1月1日,步行,Shoe,1000\n"
        "2,2026年1月2日,步行,Shoe,1000\n"
        "3,2026年1月3日,步行,Shoe,1000\n"
    )
    with pytest.raises(HTTPException) as error:
        _parse_strava_csv(csv_content.encode("utf-8"), max_rows=2)
    assert error.value.status_code == 413
    assert "2" in str(error.value.detail)


def test_strava_request_limit_rejects_before_endpoint_parsing(
    client, user_with_token, monkeypatch
):

    _user, token = user_with_token
    endpoint_called = False

    async def fail_if_endpoint_reads(_file, _max_bytes):
        nonlocal endpoint_called
        endpoint_called = True
        raise AssertionError("endpoint should not parse an oversized multipart body")

    guard = app.middleware_stack
    while not isinstance(guard, UploadLimitMiddleware):
        guard = guard.app
    monkeypatch.setattr(guard, "max_bytes", 10)
    monkeypatch.setattr("backend.routers.strava._read_strava_upload", fail_if_endpoint_reads)
    response = upload(client, "/api/runs/import/strava/preview", token)
    assert response.status_code == 413
    assert response.headers["x-request-id"]
    assert endpoint_called is False


def test_strava_request_limit_counts_chunked_body_without_content_length(monkeypatch):

    messages = iter([
        {"type": "http.request", "body": b"123456", "more_body": True},
        {"type": "http.request", "body": b"789012", "more_body": False},
    ])
    sent = []

    async def receive():
        return next(messages)

    async def send(message):
        sent.append(message)

    async def downstream(_scope, limited_receive, _send):
        while True:
            message = await limited_receive()
            if not message.get("more_body"):
                return

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/runs/import/strava/preview",
        "headers": [],
    }
    middleware = UploadLimitMiddleware(downstream, max_bytes=10, max_backup_bytes=10)
    asyncio.run(middleware(scope, receive, send))
    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 413


def test_run_model_declares_unique_strava_activity_index():
    index = next(
        item for item in Run.__table__.indexes
        if item.name == "idx_runs_user_strava_id"
    )
    assert index.unique is True


def test_strava_preview_reports_each_gear_groups_earliest_importable_date(db, user_with_token):
    """SPEC-046: the UI compares this date with the mapped shoe's purchase date."""
    from backend.read_models.strava_preview import build_preview

    user, _token = user_with_token
    rows = [
        {"strava_id": "a", "date": "2026-03-10", "km": 5.0, "gear": "Rider"},
        {"strava_id": "b", "date": "2026-01-04", "km": 6.0, "gear": "Rider"},
        {"strava_id": "c", "date": "2026-02-01", "km": 7.0, "gear": "Sky"},
    ]
    preview = build_preview(db, user.id, rows, 0, [])
    groups = {group["gear"]: group for group in preview["gear_groups"]}
    assert groups["Rider"]["first_date"] == "2026-01-04"
    assert groups["Sky"]["first_date"] == "2026-02-01"


@pytest.mark.parametrize(("path", "message"), [
    ("/api/runs/import/strava/preview", "Strava 上傳請求不可超過 3 MB"),
    ("/api/account-restore/preview", "備份不可超過 5 MB"),
])
def test_upload_limit_messages_follow_the_configured_limits(path, message):
    """SPEC-047: the rejection text is derived from the enforced byte limit."""
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(event):
        sent.append(event)

    async def downstream(_scope, _receive, _send):
        raise AssertionError("oversized request must not reach the route")

    middleware = UploadLimitMiddleware(downstream, max_bytes=3 * 1024 * 1024, max_backup_bytes=5 * 1024 * 1024)
    scope = {"type": "http", "method": "POST", "path": path,
             "headers": [(b"content-length", str(6 * 1024 * 1024).encode())]}
    asyncio.run(middleware(scope, receive, send))
    assert sent[0]["status"] == 413
    assert json.loads(sent[1]["body"])["detail"] == message


@pytest.mark.parametrize(("value", "local", "utc"), [
    ("2026年10月31日 下午10:30:00", "2026-11-01", "2026-10-31"),
    ("Oct 31, 2026, 10:30:00 PM", "2026-11-01", "2026-10-31"),
    ("2026年10月31日 上午12:05:00", "2026-10-31", "2026-10-31"),
    ("2026年8月30日 上午11:40:36", "2026-08-30", "2026-08-30"),
    # SPEC-063: the part-of-day words a real zh-TW export uses besides 上午/下午.
    ("2026年10月31日 晚上11:30:52", "2026-11-01", "2026-10-31"),
    ("2026年10月16日 晚上11:51:20", "2026-10-17", "2026-10-16"),
    ("2026年10月31日 傍晚6:10:00", "2026-11-01", "2026-10-31"),
    ("2026年11月7日 中午12:40:21", "2026-11-07", "2026-11-07"),
    ("2026年11月7日 中午1:05:00", "2026-11-07", "2026-11-07"),
    ("2026年10月11日 凌晨3:02:49", "2026-10-11", "2026-10-11"),
    ("2026年11月14日 清晨7:12:27", "2026-11-14", "2026-11-14"),
    ("2026年11月14日 早上9:00:00", "2026-11-14", "2026-11-14"),
    ("2026年11月14日 午夜12:30:00", "2026-11-14", "2026-11-14"),
    ("2026年10月31日 23:30:52", "2026-11-01", "2026-10-31"),
    ("2026年8月30日", "2026-08-30", "2026-08-30"),
    ("2026-08-30", "2026-08-30", "2026-08-30"),
])
def test_strava_utc_timestamps_become_taipei_calendar_dates(value, local, utc):
    """SPEC-047: a 06:30 Taipei run exported as 22:30 UTC belongs to the next local day."""
    from backend.strava_import import parse_activity_dates

    assert parse_activity_dates(value) == (local, utc)


UTC_SHIFT_CSV = (
    "Activity ID,Activity Date,Activity Type,Activity Gear,Distance\n"
    '"shift-1","Oct 31, 2026, 10:30:00 PM",Run,Mizuno Wave Sky 7,10000\n'
    '"edited-1","Oct 31, 2026, 11:00:00 PM",Run,Mizuno Wave Sky 7,4000\n'
    '"same-1","Oct 15, 2026, 9:00:00 AM",Run,Mizuno Wave Sky 7,3000\n'
)


def test_reimport_moves_runs_stored_on_the_old_utc_date(client, db, user_with_token):
    """SPEC-047: a re-import corrects pre-fix UTC dates, keeps hand edits, and moves monthly totals."""
    user, token = user_with_token
    shoe = Shoe(user_id=user.id, brand="Mizuno", model="Wave Sky 7", date="2026-01-01")
    db.add(shoe)
    db.flush()
    # As stored by the pre-SPEC-047 parser (UTC date), plus one run the user re-dated by hand.
    db.add_all([
        Run(user_id=user.id, shoe_id=shoe.id, date="2026-10-31", km=10, strava_id="shift-1"),
        Run(user_id=user.id, shoe_id=shoe.id, date="2026-10-30", km=4, strava_id="edited-1"),
        Run(user_id=user.id, shoe_id=shoe.id, date="2026-10-15", km=3, strava_id="same-1"),
        MonthlyMileage(user_id=user.id, year=2026, month=10, km=17, adjustment_km=0),
    ])
    shoe.mileage = 17
    db.commit()

    preview = upload(client, "/api/runs/import/strava/preview", token, csv_content=UTC_SHIFT_CSV).json()
    assert preview["importable_count"] == 0 and preview["duplicate_count"] == 3
    assert preview["date_correction_count"] == 1
    assert preview["date_correction_samples"] == [
        {"strava_id": "shift-1", "from_date": "2026-10-31", "to_date": "2026-11-01", "km": 10.0},
    ]

    mapping = f'{{"Mizuno Wave Sky 7": {shoe.id}}}'
    result = upload(client, "/api/runs/import/strava", token, mapping, csv_content=UTC_SHIFT_CSV).json()
    assert result["corrected_dates"] == 1 and result["imported"] == 0

    db.expire_all()
    dates = {run.strava_id: run.date for run in db.query(Run).filter_by(user_id=user.id)}
    assert dates == {"shift-1": "2026-11-01", "edited-1": "2026-10-30", "same-1": "2026-10-15"}
    months = {(row.month): row.km for row in db.query(MonthlyMileage).filter_by(user_id=user.id)}
    assert months == {10: 7.0, 11: 10.0}
    assert db.get(Shoe, shoe.id).mileage == 17

    again = upload(client, "/api/runs/import/strava", token, mapping, csv_content=UTC_SHIFT_CSV).json()
    assert again["corrected_dates"] == 0


def test_deleted_strava_activity_is_not_reimported_and_preview_counts_it(client, db, user_with_token):
    """SPEC-055: deleting an imported run keeps that activity deleted across CSV re-imports."""
    from backend.models import User
    from unit_tests.token_helpers import create_access_token

    user, token = user_with_token
    shoe = Shoe(user_id=user.id, brand="Mizuno", model="Wave Sky 7", date="2026-01-01", mileage=0)
    db.add(shoe)
    db.commit()
    mapping = f'{{"Mizuno Wave Sky 7": {shoe.id}, "": null}}'
    assert upload(client, "/api/runs/import/strava", token, mapping).json()["imported"] == 1
    run = db.query(Run).filter(Run.user_id == user.id).one()
    assert client.delete(f"/api/runs/{run.id}", headers=_auth_header(token)).status_code == 200

    preview = upload(client, "/api/runs/import/strava/preview", token).json()
    assert (preview["deleted_count"], preview["duplicate_count"], preview["importable_count"]) == (1, 0, 1)
    assert [group["gear"] for group in preview["gear_groups"]] == [""], "the deleted activity needs no mapping"
    result = upload(client, "/api/runs/import/strava", token, mapping).json()
    assert (result["imported"], result["skipped_deleted"], result["synced_mileage"]) == (0, 1, 0)
    db.refresh(shoe)
    assert shoe.mileage == 0
    assert db.query(Run).filter(Run.user_id == user.id).count() == 0

    # Another account's deletion never hides the same activity from this one.
    other = User(username="strava-other", hashed_password="synthetic")
    db.add(other)
    db.flush()
    other_shoe = Shoe(user_id=other.id, brand="Mizuno", model="Wave Sky 7", date="2026-01-01")
    db.add(other_shoe)
    db.commit()
    other_token = create_access_token({"sub": other.username})
    other_mapping = f'{{"Mizuno Wave Sky 7": {other_shoe.id}, "": null}}'
    assert upload(client, "/api/runs/import/strava", other_token, other_mapping).json()["imported"] == 1
