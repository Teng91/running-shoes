
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from backend.credentials import get_password_hash
from backend.dependencies import get_db
from backend.main import app
from backend.models import MonthlyMileage, Shoe, User


@pytest.fixture
def client(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _auth_header(token):
    return {"Authorization": f"Bearer {token}"}


# ── Run Log CRUD Tests ─────────────────────────────────

def test_run_log_crud(client, db, user_with_token):
    user, token = user_with_token
    shoe = Shoe(user_id=user.id, brand="Mizuno", model="Wave Rider", date="2026-01-01")
    db.add(shoe)
    db.commit()
    db.refresh(shoe)
    headers = _auth_header(token)

    created = client.post("/api/runs", headers=headers, json={
        "date": "2026-08-12", "km": 8.25, "shoe_id": shoe.id,
    })
    assert created.status_code == 200
    run_id = created.json()["id"]
    assert created.json()["version"] == 0
    db.refresh(shoe)
    assert shoe.mileage == 8.25
    august = db.query(MonthlyMileage).filter_by(
        user_id=user.id, year=2026, month=8
    ).one()
    assert august.km == 8.25

    listed = client.get("/api/runs", headers=headers)
    assert listed.status_code == 200
    assert listed.json()[0]["km"] == 8.25

    updated = client.put(f"/api/runs/{run_id}", headers=headers, json={
        "date": "2026-09-01", "km": 10.5,
    })
    assert updated.status_code == 200
    assert updated.json()["km"] == 10.5
    assert updated.json()["version"] == 1
    db.refresh(shoe)
    db.refresh(august)
    september = db.query(MonthlyMileage).filter_by(
        user_id=user.id, year=2026, month=9
    ).one()
    assert shoe.mileage == 10.5
    assert august.km == 0
    assert september.km == 10.5
    omitted = client.put(f"/api/runs/{run_id}", headers=headers, json={})
    assert omitted.status_code == 200
    assert omitted.json()["km"] == 10.5

    deleted = client.delete(f"/api/runs/{run_id}", headers=headers)
    assert deleted.status_code == 200
    assert client.get("/api/runs", headers=headers).json() == []
    db.refresh(shoe)
    db.refresh(september)
    assert shoe.mileage == 0
    assert september.km == 0


def test_multiple_runs_atomically_share_one_monthly_aggregate(
    client, db, user_with_token
):
    user, token = user_with_token
    shoe = Shoe(user_id=user.id, brand="Mizuno", model="Rider", date="2026-01-01")
    db.add(shoe)
    db.commit()
    headers = _auth_header(token)

    first = client.post("/api/runs", headers=headers, json={
        "date": "2026-08-12", "km": 5, "shoe_id": shoe.id,
    })
    second = client.post("/api/runs", headers=headers, json={
        "date": "2026-08-20", "km": 7, "shoe_id": shoe.id,
    })

    assert first.status_code == 200
    assert second.status_code == 200
    db.expire_all()
    aggregates = db.query(MonthlyMileage).filter_by(
        user_id=user.id, year=2026, month=8
    ).all()
    assert len(aggregates) == 1
    assert aggregates[0].km == 12
    assert aggregates[0].version == 1


def test_run_update_rejects_stale_version_without_double_applying_mileage(
    client, db, user_with_token
):
    user, token = user_with_token
    shoe = Shoe(user_id=user.id, brand="Mizuno", model="Rider", date="2026-01-01")
    db.add(shoe)
    db.commit()
    headers = _auth_header(token)
    created = client.post("/api/runs", headers=headers, json={
        "date": "2026-08-12", "km": 8, "shoe_id": shoe.id,
    }).json()

    first = client.put(f"/api/runs/{created['id']}", headers=headers, json={
        "km": 10, "expected_version": created["version"],
    })
    stale = client.put(f"/api/runs/{created['id']}", headers=headers, json={
        "km": 12, "expected_version": created["version"],
    })

    assert first.status_code == 200
    assert first.json()["version"] == 1
    assert stale.status_code == 409
    assert "重新載入" in stale.json()["detail"]
    stale_delete = client.delete(
        f"/api/runs/{created['id']}?expected_version={created['version']}",
        headers=headers,
    )
    assert stale_delete.status_code == 409
    db.expire_all()
    assert db.get(Shoe, shoe.id).mileage == 10
    monthly = db.query(MonthlyMileage).filter_by(
        user_id=user.id, year=2026, month=8
    ).one()
    assert monthly.km == 10


def test_delete_shoe_with_run_log_preserves_history(client, db, user_with_token):
    user, token = user_with_token
    shoe = Shoe(user_id=user.id, brand="Mizuno", model="Wave Rider", date="2026-01-01")
    db.add(shoe)
    db.commit()
    db.refresh(shoe)
    headers = _auth_header(token)
    created = client.post("/api/runs", headers=headers, json={
        "date": "2026-08-12", "km": 8.25, "shoe_id": shoe.id,
    })
    assert created.status_code == 200

    deleted = client.delete(f"/api/shoes/{shoe.id}", headers=headers)
    assert deleted.status_code == 200
    assert client.get("/api/shoes/active", headers=headers).json() == []
    assert client.get("/api/runs", headers=headers).json()[0]["shoe_id"] == shoe.id
    db.refresh(shoe)
    assert shoe.is_deleted is True

    # A deleted shoe cannot be edited, selected for a new run, or deleted again.
    assert client.put(
        f"/api/shoes/{shoe.id}", headers=headers, json={"brand": "Hidden"}
    ).status_code == 404
    assert client.post("/api/runs", headers=headers, json={
        "date": "2026-08-13", "km": 5, "shoe_id": shoe.id,
    }).status_code == 404
    assert client.delete(f"/api/shoes/{shoe.id}", headers=headers).status_code == 404


def test_run_update_applies_net_delta_when_totals_were_manually_lowered(
    client, db, user_with_token
):
    user, token = user_with_token
    shoe = Shoe(user_id=user.id, brand="Mizuno", model="Wave Rider", date="2026-01-01")
    db.add(shoe)
    db.commit()
    headers = _auth_header(token)

    created = client.post("/api/runs", headers=headers, json={
        "date": "2026-08-12", "km": 8, "shoe_id": shoe.id,
    })
    assert created.status_code == 200
    monthly = db.query(MonthlyMileage).filter_by(
        user_id=user.id, year=2026, month=8
    ).one()

    # Manual totals remain supported, so editing a run must apply only its net change.
    shoe.mileage = 3
    monthly.km = 2
    db.commit()
    updated = client.put(
        f"/api/runs/{created.json()['id']}", headers=headers, json={"km": 10}
    )

    assert updated.status_code == 200
    db.refresh(shoe)
    db.refresh(monthly)
    assert shoe.mileage == 5
    assert monthly.km == 4


def test_run_log_orders_newest_first_and_can_change_owned_shoe(client, db, user_with_token):
    user, token = user_with_token
    first_shoe = Shoe(user_id=user.id, brand="Mizuno", model="Rider", date="2026-01-01")
    second_shoe = Shoe(user_id=user.id, brand="Asics", model="Novablast", date="2026-02-01")
    db.add_all([first_shoe, second_shoe])
    db.commit()
    headers = _auth_header(token)
    older = client.post("/api/runs", headers=headers, json={
        "date": "2026-08-01", "km": 5, "shoe_id": first_shoe.id,
    }).json()
    newer = client.post("/api/runs", headers=headers, json={
        "date": "2026-08-15", "km": 8, "shoe_id": first_shoe.id,
    }).json()

    listed = client.get("/api/runs", headers=headers).json()
    assert [run["id"] for run in listed] == [newer["id"], older["id"]]
    changed = client.put(f"/api/runs/{older['id']}", headers=headers, json={
        "shoe_id": second_shoe.id,
    })
    assert changed.status_code == 200
    assert changed.json()["shoe_id"] == second_shoe.id
    db.refresh(first_shoe)
    db.refresh(second_shoe)
    monthly = db.query(MonthlyMileage).filter_by(
        user_id=user.id, year=2026, month=8
    ).one()
    assert first_shoe.mileage == 8
    assert second_shoe.mileage == 5
    assert monthly.km == 13


def test_run_log_supports_month_filters_and_pagination(client, db, user_with_token):
    user, token = user_with_token
    shoe = Shoe(user_id=user.id, brand="Mizuno", model="Rider", date="2026-01-01")
    db.add(shoe)
    db.commit()
    headers = _auth_header(token)
    for run_date, km in (
        ("2025-12-31", 3),
        ("2026-08-01", 5),
        ("2026-08-15", 8),
        ("2026-09-01", 10),
    ):
        assert client.post("/api/runs", headers=headers, json={
            "date": run_date, "km": km, "shoe_id": shoe.id,
        }).status_code == 200

    august = client.get(
        "/api/runs?year=2026&month=8&limit=1&offset=0", headers=headers
    )
    august_second_page = client.get(
        "/api/runs?year=2026&month=8&limit=1&offset=1", headers=headers
    )
    year = client.get("/api/runs?year=2026", headers=headers)
    invalid = client.get("/api/runs?month=8", headers=headers)

    assert august.status_code == 200
    assert [row["date"] for row in august.json()] == ["2026-08-15"]
    assert [row["date"] for row in august_second_page.json()] == ["2026-08-01"]
    assert [row["date"] for row in year.json()] == [
        "2026-09-01", "2026-08-15", "2026-08-01",
    ]
    assert invalid.status_code == 422
    assert invalid.json()["detail"] == "month requires year"


def test_run_log_limit(client, db, user_with_token, monkeypatch):

    monkeypatch.setattr(app.state, "settings", replace(app.state.settings, max_runs_per_user=1))
    user, token = user_with_token
    shoe = Shoe(user_id=user.id, brand="Mizuno", model="Rider", date="2026-01-01")
    db.add(shoe)
    db.commit()
    headers = _auth_header(token)
    payload = {"date": "2026-08-01", "km": 5, "shoe_id": shoe.id}
    assert client.post("/api/runs", headers=headers, json=payload).status_code == 200
    limited = client.post("/api/runs", headers=headers, json=payload)
    assert limited.status_code == 409
    assert limited.json()["detail"] == "跑步紀錄已達上限"


@pytest.mark.parametrize("payload", [
    {"date": "2026-02-30", "km": 5, "shoe_id": 1},
    {"date": "2026-08-12", "km": 0, "shoe_id": 1},
    {"date": "2026-08-12", "km": 1001, "shoe_id": 1},
])
def test_run_log_rejects_invalid_payload(client, user_with_token, payload):
    _, token = user_with_token
    assert client.post("/api/runs", headers=_auth_header(token), json=payload).status_code == 422


@pytest.mark.parametrize("payload", [
    {"date": None},
    {"km": None},
    {"shoe_id": None},
    # SPEC-047: a null version is a malformed request (422), not a stale edit (409).
    {"km": 6, "expected_version": None},
])
def test_run_log_update_rejects_explicit_nulls(client, db, user_with_token, payload):
    user, token = user_with_token
    shoe = Shoe(user_id=user.id, brand="Mizuno", model="Rider", date="2026-01-01")
    db.add(shoe)
    db.commit()
    headers = _auth_header(token)
    created = client.post("/api/runs", headers=headers, json={
        "date": "2026-08-12", "km": 5, "shoe_id": shoe.id,
    })
    run_id = created.json()["id"]

    rejected = client.put(f"/api/runs/{run_id}", headers=headers, json=payload)
    assert rejected.status_code == 422
    unchanged = client.get("/api/runs", headers=headers).json()[0]
    assert unchanged["date"] == "2026-08-12"
    assert unchanged["km"] == 5
    assert unchanged["shoe_id"] == shoe.id


def test_run_log_rejects_another_users_shoe_and_record(client, db):
    from unit_tests.token_helpers import token_for

    alice = User(username="run-alice", hashed_password=get_password_hash("pass1234"))
    bob = User(username="run-bob", hashed_password=get_password_hash("pass1234"))
    db.add_all([alice, bob])
    db.commit()
    shoe = Shoe(user_id=alice.id, brand="Asics", model="Novablast", date="2026-01-01")
    bob_shoe = Shoe(user_id=bob.id, brand="Nike", model="Pegasus", date="2026-01-02")
    db.add_all([shoe, bob_shoe])
    db.commit()
    alice_headers = _auth_header(token_for(alice))
    bob_headers = _auth_header(token_for(bob))

    forbidden_create = client.post("/api/runs", headers=bob_headers, json={
        "date": "2026-08-12", "km": 5, "shoe_id": shoe.id,
    })
    assert forbidden_create.status_code == 404

    created = client.post("/api/runs", headers=alice_headers, json={
        "date": "2026-08-12", "km": 5, "shoe_id": shoe.id,
    })
    run_id = created.json()["id"]
    forbidden_reassign = client.put(f"/api/runs/{run_id}", headers=alice_headers, json={
        "shoe_id": bob_shoe.id,
    })
    assert forbidden_reassign.status_code == 404
    assert client.get("/api/runs", headers=bob_headers).json() == []
    assert client.put(f"/api/runs/{run_id}", headers=bob_headers, json={"km": 7}).status_code == 404
    assert client.delete(f"/api/runs/{run_id}", headers=bob_headers).status_code == 404


def test_runs_in_an_existing_month_do_not_consume_monthly_identifiers(client, db, user_with_token):
    """SPEC-047: only a newly created month allocates a monthly-mileage identifier."""
    from sqlalchemy import text

    user, token = user_with_token
    shoe = Shoe(user_id=user.id, brand="Mizuno", model="Rider", date="2026-01-01")
    db.add(shoe)
    db.commit()
    headers = _auth_header(token)
    for day in ("2026-08-01", "2026-08-02", "2026-08-03", "2026-09-01"):
        assert client.post("/api/runs", headers=headers, json={
            "date": day, "km": 5, "shoe_id": shoe.id,
        }).status_code == 200

    db.expire_all()
    months = db.query(MonthlyMileage).order_by(MonthlyMileage.id).all()
    assert [(row.id, row.month, row.km) for row in months] == [(1, 8, 15.0), (2, 9, 5.0)]
    next_id = db.execute(text("SELECT next_id FROM entity_sequences WHERE name='monthly_mileages'")).scalar()
    assert next_id == 3


def test_run_list_read_model_scopes_users_and_calendar_filters(db, user_with_token):
    """SPEC-047: the HTTP route delegates the run-list query to a read model."""
    from backend.models import Run
    from backend.read_models.runs import is_calendar_day, list_runs

    user, _ = user_with_token
    other = User(username="list-other", hashed_password="synthetic")
    db.add(other)
    db.flush()
    mine = Shoe(user_id=user.id, brand="A", model="Mine", date="2026-01-01")
    theirs = Shoe(user_id=other.id, brand="B", model="Theirs", date="2026-01-01")
    db.add_all([mine, theirs])
    db.flush()
    db.add_all([
        Run(user_id=user.id, shoe_id=mine.id, date="2026-02-03", km=5),
        Run(user_id=user.id, shoe_id=mine.id, date="2026-02-28", km=6),
        Run(user_id=user.id, shoe_id=mine.id, date="2025-12-31", km=7),
        Run(user_id=other.id, shoe_id=theirs.id, date="2026-02-03", km=99),
    ])
    db.commit()
    assert [run.km for run in list_runs(db, user.id)] == [6, 5, 7]
    assert [run.km for run in list_runs(db, user.id, year=2026, month=2)] == [6, 5]
    assert [run.km for run in list_runs(db, user.id, year=2026, month=2, day=3)] == [5]
    assert [run.km for run in list_runs(db, user.id, year=2025)] == [7]
    assert [run.km for run in list_runs(db, user.id, limit=1, offset=1)] == [5]
    assert not is_calendar_day(2026, 2, 29) and is_calendar_day(2024, 2, 29)


def test_shoe_month_and_report_read_models_return_only_this_account(db, user_with_token):
    """v4.7.2: list queries moved out of routers stay user-scoped and ordered."""
    from datetime import UTC, datetime

    from backend.models import MonthlyReport
    from backend.read_models.mileage import list_monthly_mileages
    from backend.read_models.saved_reports import list_saved_reports, saved_report
    from backend.read_models.shoes import shoes_by_status

    user, _ = user_with_token
    other = User(username="reads-other", hashed_password="synthetic")
    db.add(other)
    db.flush()
    db.add_all([
        Shoe(user_id=user.id, brand="A", model="Active", date="2026-01-01"),
        Shoe(user_id=user.id, brand="B", model="Retired", date="2026-01-01", is_retired=True),
        Shoe(user_id=user.id, brand="C", model="Deleted", date="2026-01-01", is_deleted=True),
        Shoe(user_id=other.id, brand="D", model="Theirs", date="2026-01-01"),
        MonthlyMileage(user_id=user.id, year=2026, month=3, km=30),
        MonthlyMileage(user_id=user.id, year=2025, month=12, km=12),
        MonthlyMileage(user_id=other.id, year=2026, month=1, km=99),
        MonthlyReport(user_id=user.id, year=2026, month=2, content_md="feb", model="m", stats_json={},
                      created_at=datetime(2026, 3, 1, tzinfo=UTC), updated_at=datetime(2026, 3, 1, tzinfo=UTC)),
        MonthlyReport(user_id=user.id, year=2026, month=3, content_md="mar", model="m", stats_json={}),
        MonthlyReport(user_id=other.id, year=2026, month=4, content_md="secret", model="m", stats_json={}),
    ])
    db.commit()
    assert [shoe.model for shoe in shoes_by_status(db, user.id, retired=False)] == ["Active"]
    assert [shoe.model for shoe in shoes_by_status(db, user.id, retired=True)] == ["Retired"]
    assert [(row.year, row.month) for row in list_monthly_mileages(db, user.id)] == [(2025, 12), (2026, 3)]
    assert [(row["year"], row["month"]) for row in list_saved_reports(db, user.id)] == [(2026, 3), (2026, 2)]
    assert saved_report(db, user.id, 2026, 2)["updated_at"] == "2026-03-01T00:00:00+00:00"
    assert saved_report(db, user.id, 2026, 4) is None


def test_run_totals_count_every_run_like_strava_and_stay_user_scoped(client, db, user_with_token):
    """SPEC-070: the running total counts every logged run, including runs on deleted shoes."""
    from backend.models import Run
    from unit_tests.token_helpers import token_for

    user, token = user_with_token
    other = User(username="totals-other", hashed_password=get_password_hash("pass1234"))
    db.add(other)
    db.flush()
    worn = Shoe(user_id=user.id, brand="Mizuno", model="Rider", date="2025-01-01", mileage=450)
    gone = Shoe(user_id=user.id, brand="ASICS", model="Excite", date="2024-01-01", is_deleted=True)
    theirs = Shoe(user_id=other.id, brand="Nike", model="Pegasus", date="2025-01-01")
    db.add_all([worn, gone, theirs])
    db.flush()
    db.add_all([Run(user_id=user.id, shoe_id=worn.id, date="2026-11-17", km=7.34),
                Run(user_id=user.id, shoe_id=worn.id, date="2026-11-10", km=10.03),
                Run(user_id=user.id, shoe_id=gone.id, date="2024-09-11", km=5.25),
                Run(user_id=other.id, shoe_id=theirs.id, date="2026-11-01", km=42.2)])
    db.commit()

    assert client.get("/api/runs/totals", headers=_auth_header(token)).json() == {"run_count": 3, "total_km": 22.62}
    other_headers = _auth_header(token_for(other))
    assert client.get("/api/runs/totals", headers=other_headers).json() == {"run_count": 1, "total_km": 42.2}
    assert client.get("/api/runs/totals").status_code == 401


# ── SPEC-096 activity types ─────────────────────────────

def test_hike_counts_toward_shoe_but_not_monthly_mileage(client, db, user_with_token):
    """SPEC-096 AC-2: a hike wears the shoe but leaves volume, goals, heatmap and streaks alone."""
    from datetime import date

    from backend.read_models.goal_progress import goal_progress
    from backend.read_models.runs import month_run_summary, run_totals
    from backend.read_models.trends import training_trends

    user, token = user_with_token
    shoe = Shoe(user_id=user.id, brand="Salomon", model="Speedcross 6", date="2026-01-01")
    db.add(shoe)
    db.commit()
    headers = _auth_header(token)
    road = client.post("/api/runs", headers=headers, json={"date": "2026-10-10", "km": 8, "shoe_id": shoe.id})
    assert road.status_code == 200 and road.json()["activity_type"] == "road"
    as_of = date(2026, 10, 31)
    before = (goal_progress(db, user.id, 2026, 10, as_of=as_of), training_trends(db, user.id, 2026, as_of))

    hike = client.post("/api/runs", headers=headers, json={
        "date": "2026-10-11", "km": 10, "shoe_id": shoe.id, "activity_type": "hike", "duration_seconds": 10800})
    assert hike.status_code == 200 and hike.json()["activity_type"] == "hike"
    assert hike.json()["pace_seconds_per_km"] == 1080, "a single hike still shows its own pace"
    db.expire_all()
    assert db.get(Shoe, shoe.id).mileage == 18
    assert db.query(MonthlyMileage).filter_by(user_id=user.id, year=2026, month=10).one().km == 8
    progress, trends = goal_progress(db, user.id, 2026, 10, as_of=as_of), training_trends(db, user.id, 2026, as_of)
    assert progress["month_km"] == before[0]["month_km"] == 8
    assert progress["ytd_km"] == before[0]["ytd_km"]
    assert trends["daily"] == before[1]["daily"] == [{"date": "2026-10-10", "km": 8.0}]
    assert trends["streaks"] == before[1]["streaks"]
    summary = month_run_summary(db, user.id, 2026, 10)
    assert (summary["total_km"], summary["run_count"], summary["run_days"]) == (8, 1, 1)
    assert [day["date"] for day in summary["calendar"]] == ["2026-10-10", "2026-10-11"], "the log lists every activity"
    assert summary["shoe_usage"] == [{"shoe_id": shoe.id, "km": 18.0, "count": 2}]
    assert run_totals(db, user.id) == {"run_count": 1, "total_km": 8.0}

    assert client.delete(f"/api/runs/{hike.json()['id']}", headers=headers).status_code == 200
    db.expire_all()
    assert db.get(Shoe, shoe.id).mileage == 8
    assert db.query(MonthlyMileage).filter_by(user_id=user.id, year=2026, month=10).one().km == 8


def test_changing_activity_type_moves_monthly_mileage(client, db, user_with_token):
    """SPEC-096 AC-4: switching road -> hike -> road moves the month, never the shoe."""
    user, token = user_with_token
    shoe = Shoe(user_id=user.id, brand="HOKA", model="Speedgoat 6", date="2026-01-01")
    db.add(shoe)
    db.commit()
    headers = _auth_header(token)
    run = client.post("/api/runs", headers=headers, json={"date": "2026-09-05", "km": 12.5, "shoe_id": shoe.id}).json()

    def totals():
        db.expire_all()
        month = db.query(MonthlyMileage).filter_by(user_id=user.id, year=2026, month=9).one()
        return db.get(Shoe, shoe.id).mileage, month.km

    assert totals() == (12.5, 12.5)
    hiked = client.put(f"/api/runs/{run['id']}", headers=headers,
                       json={"activity_type": "hike", "expected_version": run["version"]})
    assert hiked.status_code == 200 and hiked.json()["activity_type"] == "hike"
    assert hiked.json()["version"] == run["version"] + 1
    assert totals() == (12.5, 0)
    trail = client.put(f"/api/runs/{run['id']}", headers=headers,
                       json={"activity_type": "trail", "km": 13, "expected_version": hiked.json()["version"]})
    assert trail.status_code == 200 and trail.json()["activity_type"] == "trail"
    assert totals() == (13, 13)
    road = client.put(f"/api/runs/{run['id']}", headers=headers,
                      json={"activity_type": "road", "expected_version": trail.json()["version"]})
    assert road.json()["version"] == run["version"] + 3
    assert totals() == (13, 13)
    stale = client.put(f"/api/runs/{run['id']}", headers=headers,
                       json={"activity_type": "hike", "expected_version": run["version"]})
    assert stale.status_code == 409
    assert totals() == (13, 13), "a rejected edit moves nothing"


@pytest.mark.parametrize("payload", [{"activity_type": "swim"}, {"activity_type": ""}, {"activity_type": None},
                                     {"activity_type": 1}])
def test_invalid_activity_type_is_rejected(client, db, user_with_token, payload):
    """SPEC-096 AC-7: only road, trail and hike are accepted on create and update."""
    from backend.models import Run

    user, token = user_with_token
    shoe = Shoe(user_id=user.id, brand="Mizuno", model="Wave Daichi", date="2026-01-01")
    db.add(shoe)
    db.commit()
    headers = _auth_header(token)
    created = client.post("/api/runs", headers=headers, json={"date": "2026-10-01", "km": 5, "shoe_id": shoe.id, **payload})
    assert created.status_code == 422
    run = client.post("/api/runs", headers=headers, json={"date": "2026-10-01", "km": 5, "shoe_id": shoe.id}).json()
    updated = client.put(f"/api/runs/{run['id']}", headers=headers, json={**payload, "expected_version": run["version"]})
    assert updated.status_code == 422
    db.expire_all()
    stored = db.get(Run, run["id"])
    assert (stored.activity_type, stored.version, db.get(Shoe, shoe.id).mileage) == ("road", 0, 5)


def test_walk_counts_only_toward_the_shoe(client, db, user_with_token):
    """SPEC-097 AC-3: a walk is its own type and, like a hike, only wears the shoe."""
    from backend.read_models.runs import month_run_summary, run_totals

    user, token = user_with_token
    shoe = Shoe(user_id=user.id, brand="Mizuno", model="Wave Rider", date="2026-01-01")
    db.add(shoe)
    db.commit()
    headers = _auth_header(token)
    walk = client.post("/api/runs", headers=headers, json={
        "date": "2026-10-12", "km": 3.2, "shoe_id": shoe.id, "activity_type": "walk"})
    assert walk.status_code == 200 and walk.json()["activity_type"] == "walk"
    db.expire_all()
    assert db.get(Shoe, shoe.id).mileage == 3.2
    assert db.query(MonthlyMileage).filter_by(user_id=user.id, year=2026, month=10).count() == 0
    assert month_run_summary(db, user.id, 2026, 10)["total_km"] == 0
    assert run_totals(db, user.id) == {"run_count": 0, "total_km": 0.0}
    road = client.put(f"/api/runs/{walk.json()['id']}", headers=headers,
                      json={"activity_type": "road", "expected_version": walk.json()["version"]})
    assert road.status_code == 200
    db.expire_all()
    assert db.query(MonthlyMileage).filter_by(user_id=user.id, year=2026, month=10).one().km == 3.2
