"""SPEC-062: a Strava import never doubles a run that was already entered by hand."""

from backend.models import MonthlyMileage, Run, Shoe
from backend.strava_import import manual_matches
from unit_tests.test_run_pace import STRAVA_HEADER, client, headers, owner, strava_row, upload

__all__ = ["client"]


def row(strava_id, day, km, duration=None):
    return {"strava_id": strava_id, "date": day, "km": km, "duration_seconds": duration}


def test_manual_matches_link_only_unambiguous_same_day_runs():
    manual = [
        (1, "2026-11-01", 10.0, None),   # rounded by hand; Strava says 10.4
        (2, "2026-11-02", 5.0, 1500),    # already timed: linked, time kept
        (3, "2026-11-03", 5.0, None),    # two same-distance activities: ambiguous
        (4, "2026-11-04", 10.0, None),   # distance far off: conflict
        (5, "2026-11-05", 5.0, None),    # two runs a day with distinct distances
        (6, "2026-11-05", 12.0, None),
        (7, "2026-11-06", 8.0, None),    # implausible Strava time: linked without it
        (8, "2026-11-07", 6.0, None),    # two hand runs close to one activity
        (9, "2026-11-07", 6.1, None),
    ]
    rows = [
        row("a", "2026-11-01", 10.4, 3300), row("b", "2026-11-02", 5.02, 1400),
        row("c1", "2026-11-03", 5.0, 1500), row("c2", "2026-11-03", 5.1, 1500),
        row("d", "2026-11-04", 6.0, 1800),
        row("e1", "2026-11-05", 5.05, 1500), row("e2", "2026-11-05", 12.1, 3600),
        row("f", "2026-11-06", 8.0, 30),
        row("g", "2026-11-07", 6.05, 1800),
        row("h", "2026-11-08", 5.0, 1500),          # no hand-entered run that day: imported
        row("known", "2026-11-01", 10.0, 3000),     # already stored or deleted: not considered
        row("a", "2026-11-01", 10.4, 3300),         # repeated CSV row
    ]
    links, conflicts = manual_matches(rows, manual, {"known"})
    assert links == [
        {"strava_id": "a", "run_id": 1, "date": "2026-11-01", "duration_seconds": 3300},
        {"strava_id": "b", "run_id": 2, "date": "2026-11-02", "duration_seconds": None},
        {"strava_id": "e1", "run_id": 5, "date": "2026-11-05", "duration_seconds": 1500},
        {"strava_id": "e2", "run_id": 6, "date": "2026-11-05", "duration_seconds": 3600},
        {"strava_id": "f", "run_id": 7, "date": "2026-11-06", "duration_seconds": None},
    ]
    assert [conflict["strava_id"] for conflict in conflicts] == ["c1", "c2", "d", "g"]


def mileage(db, user, shoe):
    db.expire_all()
    months = sorted((m.year, m.month, round(m.km, 2)) for m in db.query(MonthlyMileage).filter_by(user_id=user.id))
    return round(db.get(Shoe, shoe.id).mileage, 2), months


def test_import_links_hand_entered_runs_without_doubling_mileage(client, db):
    user, shoe = owner(db)
    other, other_shoe = owner(db, "manual-isolated")
    for day, km, duration in (("2026-11-15", 13, None), ("2026-11-14", 7, 2700), ("2026-11-13", 10, None)):
        payload = {"date": day, "km": km, "shoe_id": shoe.id}
        if duration:
            payload["duration_seconds"] = duration
        assert client.post("/api/runs", headers=headers(user), json=payload).status_code == 200
    # Another account's hand-entered run on the import day must not hide this user's run.
    assert client.post("/api/runs", headers=headers(other), json={
        "date": "2026-11-12", "km": 5, "shoe_id": other_shoe.id}).status_code == 200
    before = mileage(db, user, shoe)
    csv_text = (STRAVA_HEADER
                + strava_row("s1", "11月15日", 13220, 4400)   # links and fills the time
                + strava_row("s2", "11月14日", 7060, 2881)    # links, keeps the typed time
                + strava_row("s3", "11月13日", 5000, 1500)    # same day, distance off: skipped
                + strava_row("s4", "11月12日", 5000, 1500))   # nothing typed that day: imported
    preview = upload(client, user, "/api/runs/import/strava/preview", csv_text).json()
    assert (preview["importable_count"], preview["manual_link_count"], preview["manual_link_duration_count"],
            preview["manual_conflict_count"]) == (1, 2, 1, 1)
    assert preview["manual_conflict_samples"] == [{"strava_id": "s3", "date": "2026-11-13", "km": 5.0}]
    assert preview["importable_km"] == 5.0

    result = upload(client, user, "/api/runs/import/strava", csv_text, {"Mizuno Wave Sky 7": shoe.id})
    assert result.status_code == 200, result.text
    body = result.json()
    assert (body["imported"], body["linked_manual"], body["skipped_manual_conflict"], body["skipped_duplicate"]) == (1, 2, 1, 0)
    assert body["synced_mileage"] == 5.0
    shoe_km, months = mileage(db, user, shoe)
    assert shoe_km == before[0] + 5 and months == [(2026, 11, before[1][0][2] + 5)]
    runs = {run.date: run for run in db.query(Run).filter_by(user_id=user.id)}
    assert len(runs) == 4
    assert (runs["2026-11-15"].strava_id, runs["2026-11-15"].duration_seconds, runs["2026-11-15"].km) == ("s1", 4400, 13)
    assert runs["2026-11-15"].version == 1
    assert (runs["2026-11-14"].strava_id, runs["2026-11-14"].duration_seconds) == ("s2", 2700)
    assert runs["2026-11-13"].strava_id is None
    assert runs["2026-11-12"].strava_id == "s4"
    assert db.query(Run).filter_by(user_id=other.id).one().strava_id is None

    again = upload(client, user, "/api/runs/import/strava/preview", csv_text).json()
    assert (again["importable_count"], again["manual_link_count"], again["duplicate_count"],
            again["manual_conflict_count"]) == (0, 0, 3, 1)


def test_a_deleted_linked_run_is_not_imported_again(client, db):
    user, shoe = owner(db)
    run = client.post("/api/runs", headers=headers(user), json={"date": "2026-11-15", "km": 13, "shoe_id": shoe.id}).json()
    csv_text = STRAVA_HEADER + strava_row("s1", "11月15日", 13220, 4400)
    assert upload(client, user, "/api/runs/import/strava", csv_text, {"Mizuno Wave Sky 7": shoe.id}).json()["linked_manual"] == 1
    assert client.delete(f"/api/runs/{run['id']}", headers=headers(user)).status_code == 200
    preview = upload(client, user, "/api/runs/import/strava/preview", csv_text).json()
    assert (preview["importable_count"], preview["deleted_count"], preview["manual_link_count"]) == (0, 1, 0)
