"""SPEC-062: a Strava import never doubles a run that was already entered by hand.

SPEC-091: the user chooses skip, link or import for each same-day conflict.
"""

import io
import json

import pytest

from backend.models import MonthlyMileage, Run, Shoe
from backend.strava_import import (
    ConflictChoiceError,
    DuplicateConflictLinkError,
    manual_matches,
    resolve_conflicts,
)
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


def test_conflicts_offer_every_same_day_manual_run_not_linked_automatically():
    """SPEC-091: a run this import links automatically is not offered again."""
    manual = [(1, "2026-11-05", 5.0, None), (2, "2026-11-05", 12.0, None), (3, "2026-11-05", 20.0, 6000)]
    links, conflicts = manual_matches([row("near", "2026-11-05", 5.02, 1500), row("odd", "2026-11-05", 8.0, 2400)],
                                      manual, set())
    assert [link["run_id"] for link in links] == [1]
    assert conflicts[0]["strava_id"] == "odd" and conflicts[0]["candidate_run_ids"] == [2, 3]


def test_conflict_choices_skip_import_or_link_a_candidate_and_reject_stale_ones():
    manual = [(2, "2026-11-05", 8.1, None), (3, "2026-11-05", 20.0, 6000), (4, "2026-11-06", 6.0, None)]
    conflicts = [
        {"strava_id": "x", "date": "2026-11-05", "km": 8.0, "duration_seconds": 2400, "candidate_run_ids": [2, 3]},
        {"strava_id": "y", "date": "2026-11-05", "km": 5.0, "duration_seconds": 1500, "candidate_run_ids": [2, 3]},
        {"strava_id": "z", "date": "2026-11-06", "km": 7.0, "duration_seconds": 2100, "candidate_run_ids": [4]},
    ]
    links, imports = resolve_conflicts(conflicts, {"x": 2, "y": "import", "z": "skip"}, manual)
    assert links == [{"strava_id": "x", "run_id": 2, "date": "2026-11-05", "duration_seconds": 2400}]
    assert imports == {"y"}
    timed, _ = resolve_conflicts(conflicts, {"x": 3}, manual)
    assert timed[0]["duration_seconds"] is None, "a typed time is never replaced"
    assert resolve_conflicts(conflicts, {}, manual) == ([], set()), "no choice means skip"
    for stale in ({"unknown": "import"}, {"x": 4}, {"x": "link"}, {"x": True}, {"x": 2.0}):
        with pytest.raises(ConflictChoiceError):
            resolve_conflicts(conflicts, stale, manual)
    with pytest.raises(DuplicateConflictLinkError):
        resolve_conflicts(conflicts, {"x": 2, "y": 2}, manual)


def _upload(client, user, path, csv_text, mapping, conflicts):
    return client.post(path, headers=headers(user), data={"mapping": json.dumps(mapping), "conflicts": conflicts},
                       files={"file": ("activities.csv", io.BytesIO(csv_text.encode("utf-8")), "text/csv")})


def test_the_user_links_or_imports_a_conflict_and_mileage_follows_the_choice(client, db):
    """SPEC-091: a linked conflict keeps the typed run; an imported one adds a run and its mileage."""
    user, shoe = owner(db, "conflict-owner")
    other, other_shoe = owner(db, "conflict-isolated")
    created = {}
    for day, km in (("2026-11-13", 10), ("2026-11-14", 12)):
        created[day] = client.post("/api/runs", headers=headers(user), json={"date": day, "km": km, "shoe_id": shoe.id}).json()["id"]
    foreign = client.post("/api/runs", headers=headers(other), json={"date": "2026-11-13", "km": 5, "shoe_id": other_shoe.id}).json()["id"]
    csv_text = (STRAVA_HEADER
                + strava_row("c13", "11月13日", 5000, 1500)    # typed 10 km that day: conflict
                + strava_row("c14", "11月14日", 6000, 1800))   # typed 12 km that day: conflict
    preview = upload(client, user, "/api/runs/import/strava/preview", csv_text).json()
    assert preview["manual_conflict_count"] == 2
    first = preview["manual_conflicts"][0]
    assert (first["strava_id"], first["date"], first["km"], first["duration_seconds"], first["gear"]) == (
        "c13", "2026-11-13", 5.0, 1500, "Mizuno Wave Sky 7")
    assert first["candidates"] == [{"run_id": created["2026-11-13"], "km": 10.0, "duration_seconds": None,
                                    "shoe_name": "Mizuno Wave Sky 7"}], "only this account's runs are offered"

    mapping = {"Mizuno Wave Sky 7": shoe.id}
    assert _upload(client, user, "/api/runs/import/strava", csv_text, mapping, "not json").status_code == 400
    stale = _upload(client, user, "/api/runs/import/strava", csv_text, mapping, json.dumps({"c13": foreign}))
    assert stale.status_code == 409 and stale.json()["detail"] == "重複活動的選擇已過期，請重新預覽"
    db.expire_all()
    assert db.get(Run, foreign).strava_id is None, "another account's run is never linked"

    before = mileage(db, user, shoe)
    result = _upload(client, user, "/api/runs/import/strava", csv_text, mapping,
                     json.dumps({"c13": created["2026-11-13"], "c14": "import"}))
    assert result.status_code == 200, result.text
    body = result.json()
    assert (body["imported"], body["linked_manual"], body["skipped_manual_conflict"]) == (1, 1, 0)
    linked = db.get(Run, created["2026-11-13"])
    db.refresh(linked)
    assert (linked.strava_id, linked.km, linked.duration_seconds) == ("c13", 10, None), "Strava's time for 5 km is not copied onto a 10 km run"
    assert db.query(Run).filter_by(user_id=user.id, strava_id="c14").one().km == 6
    shoe_km, months = mileage(db, user, shoe)
    assert shoe_km == before[0] + 6 and months == [(2026, 11, before[1][0][2] + 6)]

    again = upload(client, user, "/api/runs/import/strava/preview", csv_text).json()
    assert (again["manual_conflict_count"], again["duplicate_count"], again["importable_count"]) == (0, 2, 0)


def test_a_conflict_with_its_own_gear_can_be_mapped_and_two_links_to_one_run_are_refused(client, db):
    """SPEC-092: a chosen import always has a shoe group; one manual run takes one activity."""
    user, shoe = owner(db, "conflict-gear-owner")
    typed = client.post("/api/runs", headers=headers(user), json={"date": "2026-11-13", "km": 10, "shoe_id": shoe.id}).json()["id"]
    csv_text = (STRAVA_HEADER
                + strava_row("p1", "11月13日", 5000, 1500, gear="Nike Pegasus 41")
                + strava_row("p2", "11月13日", 3000, 900, gear="Nike Pegasus 41"))
    preview = upload(client, user, "/api/runs/import/strava/preview", csv_text).json()
    assert preview["importable_count"] == 0
    assert preview["gear_groups"] == [{"gear": "Nike Pegasus 41", "count": 0, "km": 0.0, "first_date": "2026-11-13",
                                       "conflict_count": 2, "suggested_shoe_id": None, "shoe_name": None,
                                       "ambiguous_match": False}]

    twice = _upload(client, user, "/api/runs/import/strava", csv_text, {"Nike Pegasus 41": shoe.id},
                    json.dumps({"p1": typed, "p2": typed}))
    assert twice.status_code == 400 and twice.json()["detail"] == "同一筆手動紀錄只能連結一個 Strava 活動"

    result = _upload(client, user, "/api/runs/import/strava", csv_text, {"Nike Pegasus 41": shoe.id},
                     json.dumps({"p1": typed, "p2": "import"}))
    assert result.status_code == 200, result.text
    assert (result.json()["imported"], result.json()["linked_manual"], result.json()["skipped_unmapped"]) == (1, 1, 0)
