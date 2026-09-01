import asyncio
import io

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.database import get_db
from backend.main import StravaUploadLimitMiddleware, _parse_strava_csv, app
from backend.models import MonthlyMileage, Run, Shoe
from unit_tests.test_api import _auth_header

CSV = "活動 ID,活動日期,活動類型,活動裝備,距離\n" \
    "1001,2026年8月30日 上午11:40:36,跑步,Mizuno Wave Sky 7,5250\n" \
    "1002,2026年8月29日,步行,Mizuno Wave Sky 7,3000\n" \
    "1003,2026年8月28日,跑步,,6100\n"


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
    sync_mileage=False,
):
    data = {"mapping": mapping} if mapping is not None else {}
    if start_date:
        data["start_date"] = start_date
    if end_date:
        data["end_date"] = end_date
    if sync_mileage:
        data["sync_shoe_mileage"] = "true"
    return client.post(path, headers=_auth_header(token), files={
        "file": ("activities.csv", io.BytesIO(csv_content.encode("utf-8-sig")), "text/csv")
    }, data=data)


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


def test_strava_import_rejects_foreign_shoe_mapping(client, db, user_with_token):
    _user, token = user_with_token
    foreign_shoe = Shoe(user_id=999, brand="Mizuno", model="Wave Sky 7", date="2026-01-01")
    db.add(foreign_shoe)
    db.commit()
    response = upload(client, "/api/runs/import/strava", token, f'{{"Mizuno Wave Sky 7": {foreign_shoe.id}}}')
    assert response.status_code == 404


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
        sync_mileage=True,
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
    parsed, invalid, _warnings = _parse_strava_csv(csv_content.encode("utf-8"))
    assert invalid == 0
    assert [row["date"] for row in parsed] == ["2026-08-30", "2026-08-31"]


def test_strava_upload_size_limit_is_bounded_before_full_read(
    client, user_with_token, monkeypatch
):
    from backend import main as main_module

    _user, token = user_with_token
    monkeypatch.setattr(main_module, "MAX_STRAVA_CSV_BYTES", 10)
    response = upload(client, "/api/runs/import/strava/preview", token)
    assert response.status_code == 413


def test_strava_parser_rejects_excess_rows_without_materializing_all(monkeypatch):
    from backend import main as main_module

    monkeypatch.setattr(main_module, "MAX_STRAVA_CSV_ROWS", 2)
    csv_content = (
        "活動 ID,活動日期,活動類型,活動裝備,距離\n"
        "1,2026年1月1日,步行,Shoe,1000\n"
        "2,2026年1月2日,步行,Shoe,1000\n"
        "3,2026年1月3日,步行,Shoe,1000\n"
    )
    with pytest.raises(HTTPException) as error:
        _parse_strava_csv(csv_content.encode("utf-8"))
    assert error.value.status_code == 413
    assert "2" in str(error.value.detail)


def test_strava_request_limit_rejects_before_endpoint_parsing(
    client, user_with_token, monkeypatch
):
    from backend import main as main_module

    _user, token = user_with_token
    endpoint_called = False

    async def fail_if_endpoint_reads(_file):
        nonlocal endpoint_called
        endpoint_called = True
        raise AssertionError("endpoint should not parse an oversized multipart body")

    monkeypatch.setattr(main_module, "MAX_STRAVA_REQUEST_BYTES", 10)
    monkeypatch.setattr(main_module, "_read_strava_upload", fail_if_endpoint_reads)
    response = upload(client, "/api/runs/import/strava/preview", token)
    assert response.status_code == 413
    assert endpoint_called is False


def test_strava_request_limit_counts_chunked_body_without_content_length(monkeypatch):
    from backend import main as main_module

    monkeypatch.setattr(main_module, "MAX_STRAVA_REQUEST_BYTES", 10)
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
    middleware = StravaUploadLimitMiddleware(downstream)
    asyncio.run(middleware(scope, receive, send))
    assert sent[0]["type"] == "http.response.start"
    assert sent[0]["status"] == 413


def test_run_model_declares_unique_strava_activity_index():
    index = next(
        item for item in Run.__table__.indexes
        if item.name == "idx_runs_user_strava_id"
    )
    assert index.unique is True
