import io

import pytest
from fastapi.testclient import TestClient

from backend.database import get_db
from backend.main import app
from backend.models import Run, Shoe
from unit_tests.test_api import _auth_header

CSV = "活動 ID,活動日期,活動類型,活動裝備,距離\n" \
    "1001,2026年8月30日 上午11:40:36,跑步,Mizuno Wave Sky 7,5.25\n" \
    "1002,2026年8月29日,步行,Mizuno Wave Sky 7,3\n" \
    "1003,2026年8月28日,跑步,,6.10\n"


@pytest.fixture
def client(db):
    def override_get_db():
        yield db
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def upload(client, path, token, mapping=None):
    data = {"mapping": mapping} if mapping is not None else {}
    return client.post(path, headers=_auth_header(token), files={
        "file": ("activities.csv", io.BytesIO(CSV.encode("utf-8-sig")), "text/csv")
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
    assert groups[""]["suggested_shoe_id"] is None


def test_strava_import_is_idempotent_and_skips_unmapped(client, db, user_with_token):
    user, token = user_with_token
    shoe = Shoe(user_id=user.id, brand="Mizuno", model="Wave Sky 7", date="2026-01-01")
    db.add(shoe)
    db.commit()
    mapping = f'{{"Mizuno Wave Sky 7": {shoe.id}, "": null}}'
    first = upload(client, "/api/runs/import/strava", token, mapping)
    assert first.status_code == 200
    assert first.json()["imported"] == 1
    assert first.json()["skipped_unmapped"] == 1
    second = upload(client, "/api/runs/import/strava", token, mapping)
    assert second.status_code == 200
    assert second.json()["imported"] == 0
    assert second.json()["skipped_duplicate"] == 1
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
