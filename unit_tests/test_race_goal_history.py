"""SPEC-128: target race changes show in the history and a deleted race goal can be recovered."""

import uuid

from backend.models import AuditEvent, RaceGoal
from backend.services import exports
from unit_tests.test_run_pace import client, headers, owner

__all__ = ["client"]

RACE = {"race_name": "示範半馬", "race_date": "2099-03-07", "distance_km": 21.0975, "target_seconds": 7200,
        "reference_distance_km": None, "reference_seconds": None, "reference_temperature_c": None, "plan_weeks": 10}


def race_events(client, user):
    rows = client.get("/api/history?limit=50", headers=headers(user)).json()["rows"]
    return [row for row in rows if row["entity"] == "race_goals"]


def restore(client, user, event_id):
    return client.post("/api/operations", headers=headers(user), json={
        "operation_id": uuid.uuid4().hex, "kind": "history.restore", "entity_id": event_id})


def test_race_goal_changes_are_audited_and_a_deleted_goal_is_recovered(client, db):
    user, _ = owner(db, "race-history")
    assert client.put("/api/race-goal", headers=headers(user), json=RACE).status_code == 200
    assert client.put("/api/race-goal", headers=headers(user),
                      json={**RACE, "target_seconds": 6900, "expected_version": 1}).status_code == 200
    assert client.delete("/api/race-goal?expected_version=2", headers=headers(user)).status_code == 200

    events = race_events(client, user)
    assert [event["action"] for event in events] == ["delete", "update", "insert"]
    assert [event["reason"] for event in events] == ["race_goal.delete", "race_goal.update", "race_goal.update"]
    assert events[1]["before"]["target_seconds"] == 7200 and events[1]["after"]["target_seconds"] == 6900
    assert "user_id" not in events[0]["before"]
    assert [event["can_restore"] for event in events] == [True, False, False]

    response = restore(client, user, events[0]["id"])
    assert response.status_code == 200, response.text
    recovered = client.get("/api/race-goal", headers=headers(user)).json()
    assert recovered == {**RACE, "target_seconds": 6900, "version": 3}
    after = race_events(client, user)
    assert after[0]["action"] == "insert" and after[0]["reason"] == "history.restore"
    assert next(event for event in after if event["id"] == events[0]["id"])["restored"] is True
    assert restore(client, user, events[0]["id"]).status_code == 409, "a recovered deletion cannot be recovered twice"


def test_recovery_keeps_a_newer_goal_and_another_account_cannot_recover(client, db):
    user, _ = owner(db, "race-history-newer")
    other, _ = owner(db, "race-history-other")
    client.put("/api/race-goal", headers=headers(user), json=RACE)
    client.delete("/api/race-goal", headers=headers(user))
    deleted = race_events(client, user)[0]
    client.put("/api/race-goal", headers=headers(user), json={**RACE, "race_name": "新的比賽"})

    response = restore(client, user, deleted["id"])
    assert response.status_code == 409
    assert "已經有新的目標賽事" in response.json()["detail"]
    assert client.get("/api/race-goal", headers=headers(user)).json()["race_name"] == "新的比賽"

    assert restore(client, other, deleted["id"]).status_code == 404
    assert race_events(client, other) == []
    assert db.query(RaceGoal).filter_by(user_id=other.id).count() == 0


def test_backups_leave_race_goal_history_out(client, db):
    user, _ = owner(db, "race-history-backup")
    client.put("/api/race-goal", headers=headers(user), json=RACE)
    assert db.query(AuditEvent).filter_by(user_id=user.id, entity="race_goals").count() == 1
    payload, _ = exports.build_account_export(db, user)
    assert payload["race_goal"] == RACE
    assert payload["history"], "the shoe created by the fixture is still archived"
    assert all(event["entity"] != "race_goals" for event in payload["history"])
