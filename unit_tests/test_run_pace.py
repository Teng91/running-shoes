"""SPEC-060: run moving time, derived pace and Strava moving-time backfill."""

import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend import models
from backend.backup_contract import parse_backup
from backend.database import configure_sqlite_connection
from backend.dependencies import get_db
from backend.main import app
from backend.migrations import run_startup_migrations, schema_version
from backend.models import Run, Shoe, User
from backend.run_metrics import is_plausible_duration, pace_seconds_per_km
from backend.strava_import import duration_backfills, parse_csv
from unit_tests.token_helpers import create_access_token

# The column layout of a real zh-TW Strava export: 經過時間 and 距離 appear twice
# (the second 距離 is metres), 移動時間 once.
STRAVA_HEADER = "活動 ID,活動日期,活動名稱,活動類型,經過時間,距離,活動裝備,經過時間,移動時間,距離,平均速度\n"


def strava_row(activity_id, day, distance_m, moving, elapsed=None, gear="Mizuno Wave Sky 7", kind="跑步"):
    elapsed = moving if elapsed is None else elapsed
    return (f"{activity_id},2026年{day} 上午8:17:07,晨跑,{kind},{elapsed},{distance_m / 1000:.2f},{gear},"
            f"{elapsed}.0,{moving},{distance_m}.0,3.0\n")


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: (yield db)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def headers(user):
    return {"Authorization": f"Bearer {create_access_token({'sub': user.username})}"}


def owner(db, name="pace-owner"):
    user = User(username=name, hashed_password="synthetic")
    db.add(user)
    db.flush()
    shoe = Shoe(user_id=user.id, brand="Mizuno", model="Wave Sky 7", date="2024-01-01")
    db.add(shoe)
    db.commit()
    return user, shoe


def upload(client, user, path, csv_text, mapping=None):
    data = {"mapping": json.dumps(mapping)} if mapping is not None else {}
    return client.post(path, headers=headers(user), data=data, files={
        "file": ("activities.csv", io.BytesIO(csv_text.encode("utf-8")), "text/csv")})


def test_pace_is_derived_and_plausibility_bounds_typos():
    assert pace_seconds_per_km(4400, 13.22) == 333
    assert pace_seconds_per_km(None, 5) is None
    assert pace_seconds_per_km(1800, 0) is None
    assert is_plausible_duration(1500, 5)
    assert not is_plausible_duration(30, 5), "30 s for 5 km is minutes typed as seconds"
    assert not is_plausible_duration(5 * 3601, 5)
    assert not is_plausible_duration(0, 5)


def test_manual_run_records_duration_and_returns_pace(client, db):
    user, shoe = owner(db)
    created = client.post("/api/runs", headers=headers(user), json={
        "date": "2026-11-15", "km": 10, "shoe_id": shoe.id, "duration_seconds": 3330})
    assert created.status_code == 200
    assert created.json()["duration_seconds"] == 3330
    assert created.json()["pace_seconds_per_km"] == 333
    untimed = client.post("/api/runs", headers=headers(user), json={"date": "2026-11-14", "km": 5, "shoe_id": shoe.id})
    assert untimed.json()["duration_seconds"] is None and untimed.json()["pace_seconds_per_km"] is None
    listed = client.get("/api/runs", headers=headers(user)).json()
    assert [row["pace_seconds_per_km"] for row in listed] == [333, None]


@pytest.mark.parametrize("duration", [30, 0, 3.5, "1800", 7 * 24 * 3600 + 1])
def test_manual_run_rejects_invalid_or_implausible_duration(client, db, duration):
    user, shoe = owner(db)
    response = client.post("/api/runs", headers=headers(user), json={
        "date": "2026-11-15", "km": 5, "shoe_id": shoe.id, "duration_seconds": duration})
    assert response.status_code == 422
    assert db.query(Run).count() == 0


def test_run_update_sets_keeps_and_clears_duration(client, db):
    user, shoe = owner(db)
    run_id = client.post("/api/runs", headers=headers(user), json={
        "date": "2026-11-15", "km": 5, "shoe_id": shoe.id}).json()["id"]
    timed = client.put(f"/api/runs/{run_id}", headers=headers(user), json={"duration_seconds": 1500})
    assert timed.status_code == 200 and timed.json()["pace_seconds_per_km"] == 300
    kept = client.put(f"/api/runs/{run_id}", headers=headers(user), json={"km": 6})
    assert kept.json()["duration_seconds"] == 1500 and kept.json()["pace_seconds_per_km"] == 250
    # Against the stored distance, 20 s is an implausible pace; nothing changes.
    rejected = client.put(f"/api/runs/{run_id}", headers=headers(user), json={"duration_seconds": 20})
    assert rejected.status_code == 400
    assert db.get(Run, run_id).duration_seconds == 1500
    cleared = client.put(f"/api/runs/{run_id}", headers=headers(user), json={"duration_seconds": None})
    assert cleared.status_code == 200 and cleared.json()["pace_seconds_per_km"] is None
    assert client.put(f"/api/runs/{run_id}", headers=headers(user), json={"km": None}).status_code == 422


def test_month_summary_and_shoe_analytics_average_pace_is_time_weighted(client, db):
    user, shoe = owner(db)
    other, other_shoe = owner(db, "pace-other")
    db.add_all([
        Run(user_id=user.id, shoe_id=shoe.id, date="2026-10-01", km=5, duration_seconds=1500),
        Run(user_id=user.id, shoe_id=shoe.id, date="2026-10-02", km=10, duration_seconds=3600),
        Run(user_id=user.id, shoe_id=shoe.id, date="2026-10-03", km=20),
        Run(user_id=other.id, shoe_id=other_shoe.id, date="2026-10-04", km=1, duration_seconds=3000),
    ])
    db.commit()
    summary = client.get("/api/runs/summary?year=2026&month=10", headers=headers(user)).json()
    # (1500 + 3600) / 15 km = 340 s/km, not the mean of 300 and 360; untimed and other-user runs are excluded.
    assert summary["average_pace_seconds_per_km"] == 340
    assert summary["timed_run_count"] == 2 and summary["run_count"] == 3
    empty = client.get("/api/runs/summary?year=2026&month=9", headers=headers(user)).json()
    assert empty["average_pace_seconds_per_km"] is None and empty["timed_run_count"] == 0
    analytics = client.get(f"/api/shoes/{shoe.id}/analytics", headers=headers(user)).json()
    assert analytics["usage"]["average_pace_seconds_per_km"] == 340
    assert [row["pace_seconds_per_km"] for row in analytics["recent_runs"]] == [None, 360, 300]


def test_strava_csv_uses_moving_time_and_never_rejects_a_run_for_its_time():
    csv_text = (STRAVA_HEADER
                + strava_row("a1", "11月15日", 13220, 4400, elapsed=5168)
                + strava_row("a2", "11月14日", 7060, "", elapsed=2915)
                + strava_row("a3", "11月13日", 5000, 9, elapsed=9)
                + strava_row("a4", "11月12日", 5000, "abc", elapsed="nan"))
    rows, invalid, _ = parse_csv(csv_text.encode("utf-8"), max_rows=100)
    assert invalid == 0
    by_id = {row["strava_id"]: row for row in rows}
    assert by_id["a1"]["km"] == 13.22 and by_id["a1"]["duration_seconds"] == 4400
    assert by_id["a2"]["duration_seconds"] == 2915, "elapsed time is the fallback"
    assert by_id["a3"]["duration_seconds"] is None and by_id["a3"]["km"] == 5
    assert by_id["a4"]["duration_seconds"] is None
    legacy, _, _ = parse_csv("活動 ID,活動日期,活動類型,活動裝備,距離\nb1,2026年8月30日,跑步,X,5250\n".encode(), max_rows=10)
    assert legacy[0]["duration_seconds"] is None


def test_duration_backfills_only_fill_missing_plausible_times():
    rows = [{"strava_id": "1", "duration_seconds": 1500}, {"strava_id": "1", "duration_seconds": 9},
            {"strava_id": "2", "duration_seconds": 1500}, {"strava_id": "3", "duration_seconds": 1500},
            {"strava_id": "4", "duration_seconds": None}, {"strava_id": "5", "duration_seconds": 1500}]
    existing = {"1": (None, 5.0), "2": (1400, 5.0), "3": (None, 100.0), "4": (None, 5.0)}
    assert duration_backfills(rows, existing) == [{"strava_id": "1", "duration_seconds": 1500}]


def test_strava_reimport_backfills_missing_times_without_overwriting(client, db):
    user, shoe = owner(db)
    other, other_shoe = owner(db, "pace-isolated")
    db.add_all([
        Run(user_id=user.id, shoe_id=shoe.id, date="2026-11-15", km=13.22, strava_id="s1"),
        Run(user_id=user.id, shoe_id=shoe.id, date="2026-11-14", km=7.06, strava_id="s2", duration_seconds=2000),
        Run(user_id=user.id, shoe_id=shoe.id, date="2026-11-13", km=50, strava_id="s3"),
        Run(user_id=other.id, shoe_id=other_shoe.id, date="2026-11-15", km=13.22, strava_id="s1"),
    ])
    db.commit()
    csv_text = (STRAVA_HEADER + strava_row("s1", "11月15日", 13220, 4400)
                + strava_row("s2", "11月14日", 7060, 2881)
                + strava_row("s3", "11月13日", 5000, 1500)
                + strava_row("s4", "11月12日", 5000, 1500))
    preview = upload(client, user, "/api/runs/import/strava/preview", csv_text).json()
    # s3's distance was edited to 50 km by hand; 1500 s would be a 0:30/km pace.
    assert preview["duration_backfill_count"] == 1 and preview["importable_count"] == 1
    result = upload(client, user, "/api/runs/import/strava", csv_text, {"Mizuno Wave Sky 7": shoe.id})
    assert result.status_code == 200, result.text
    assert result.json()["backfilled_durations"] == 1 and result.json()["imported"] == 1
    db.expire_all()
    runs = {row.strava_id: row for row in db.query(Run).filter_by(user_id=user.id)}
    assert (runs["s1"].duration_seconds, runs["s1"].version) == (4400, 1)
    assert runs["s2"].duration_seconds == 2000, "a stored time is never overwritten"
    assert runs["s3"].duration_seconds is None
    assert runs["s4"].duration_seconds == 1500
    assert db.query(Run).filter_by(user_id=other.id).one().duration_seconds is None
    again = upload(client, user, "/api/runs/import/strava/preview", csv_text).json()
    assert again["duration_backfill_count"] == 0 and again["importable_count"] == 0


def test_backup_v4_round_trips_duration_and_merges_never_clear_it(client, db):
    from backend.services import account_restore
    user, shoe = owner(db)
    client.post("/api/runs", headers=headers(user), json={
        "date": "2026-11-15", "km": 10, "shoe_id": shoe.id, "duration_seconds": 3330})
    archive = client.get("/api/export/account", headers=headers(user)).json()
    assert archive["version"] == 4 and archive["runs"][0]["duration_seconds"] == 3330
    assert parse_backup(json.dumps(archive).encode()).runs[0].duration_seconds == 3330
    from backend.services.errors import Invalid
    with pytest.raises(Invalid):
        parse_backup(json.dumps({**archive, "version": 3}).encode())
    untimed_v3 = {**archive, "version": 3, "runs": [{**archive["runs"][0], "duration_seconds": None}]}
    assert parse_backup(json.dumps(untimed_v3).encode()).version == 3
    # An archive row without a time (e.g. exported before SPEC-060) never clears a stored one.
    untimed = {**archive, "runs": [{**archive["runs"][0], "duration_seconds": None}]}
    preview = account_restore.preview_restore(db, user.id, json.dumps(untimed).encode(), app.state.settings, "update")
    assert preview["summary"]["updated_runs"] == 0
    retimed = {**archive, "runs": [{**archive["runs"][0], "duration_seconds": 3000}]}
    preview = account_restore.preview_restore(db, user.id, json.dumps(retimed).encode(), app.state.settings, "update")
    assert preview["summary"]["updated_runs"] == 1
    account_restore.apply_restore(db, user.id, preview["token"], "pace-retimed-import", app.state.settings)
    db.expire_all()
    assert db.query(Run).filter_by(user_id=user.id).one().duration_seconds == 3000


def test_history_recovery_restores_the_moving_time(client, db):
    from backend.services import history
    user, shoe = owner(db)
    run_id = client.post("/api/runs", headers=headers(user), json={
        "date": "2026-11-15", "km": 10, "shoe_id": shoe.id, "duration_seconds": 3330}).json()["id"]
    assert client.delete(f"/api/runs/{run_id}", headers=headers(user)).status_code == 200
    event_row = db.query(models.AuditEvent).filter_by(user_id=user.id, entity="runs", action="delete").one()
    assert event_row.before_json["duration_seconds"] == 3330
    history.restore_deleted(db, user.id, event_row.id, app.state.settings)
    db.expire_all()
    assert db.query(Run).filter_by(user_id=user.id).one().duration_seconds == 3330


def test_schema_nine_rollback_keeps_times_and_reupgrades(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'rollback9.sqlite'}", connect_args={"check_same_thread": False})
    event.listen(engine, "connect", lambda connection, _: configure_sqlite_connection(connection))
    sessions = sessionmaker(bind=engine, autoflush=False)
    run_startup_migrations(engine, sessions)
    with sessions() as db:
        user, shoe = owner(db, "rollback9")
        db.add(Run(user_id=user.id, shoe_id=shoe.id, date="2026-11-15", km=10, duration_seconds=3330))
        db.commit()
    script = Path("scripts/rollback_schema_nine.sql").read_text(encoding="utf-8")
    connection = engine.raw_connection()
    try:
        connection.executescript(Path("scripts/rollback_schema_eleven.sql").read_text(encoding="utf-8"))
        connection.executescript(Path("scripts/rollback_schema_ten.sql").read_text(encoding="utf-8"))
        connection.executescript(script)
        with pytest.raises(Exception, match="CHECK constraint failed"):
            connection.executescript(script)
        connection.rollback()
    finally:
        connection.close()
    assert schema_version(engine) == 8
    run_startup_migrations(engine, sessions)
    assert schema_version(engine) == 11
    with sessions() as db:
        assert db.query(Run).one().duration_seconds == 3330
    engine.dispose()


def test_frontend_pace_bounds_mirror_the_backend():
    from backend.run_metrics import MAX_PACE_SECONDS_PER_KM, MIN_PACE_SECONDS_PER_KM
    state = Path("frontend/app-state.js").read_text(encoding="utf-8")
    assert f"const RUN_PACE_MIN_SECONDS = {MIN_PACE_SECONDS_PER_KM};" in state
    assert f"const RUN_PACE_MAX_SECONDS = {MAX_PACE_SECONDS_PER_KM};" in state


def test_stored_moving_time_still_serializes_after_a_distance_edit():
    from backend.schemas import RunOut
    # Editing a 5 km run (1500 s) to 100 km leaves an implausible stored pace;
    # responses must still serialize it rather than fail the whole run list.
    row = RunOut(id=1, user_id=1, date="2026-11-15", km=100, shoe_id=1, duration_seconds=1500)
    assert row.model_dump()["pace_seconds_per_km"] == 15
