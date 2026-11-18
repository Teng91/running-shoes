from dataclasses import replace

import pytest
from sqlalchemy import inspect, text

from backend import models, schemas
from backend.migrations import run_startup_migrations, schema_version
from backend.services import history, monthly, runs, shoes
from backend.services.errors import Conflict, NotFound
from unit_tests.workspace_helpers import add_run, add_shoe
from unit_tests.workspace_helpers import workspace as workspace


def test_deleted_run_restore_preserves_mileage_and_rejects_replay(workspace):
    with workspace.sessions() as db:
        shoe = add_shoe(db, mileage=20)
        run = add_run(db, shoe.id)
        runs.delete_run(db, 1, run.id, run.version)
        event = db.query(models.AuditEvent).filter_by(user_id=1, entity="runs", action="delete").one()
        result = history.restore_deleted(db, 1, event.id, workspace.config)
        assert result["ok"]
        db.expire_all()
        assert db.get(models.Shoe, shoe.id).mileage == 25
        assert db.query(models.MonthlyMileage).one().km == 5
        assert db.query(models.Run).count() == 1
        with pytest.raises(Conflict):
            history.restore_deleted(db, 1, event.id, workspace.config)
        with pytest.raises(NotFound):
            history.restore_deleted(db, 2, event.id, workspace.config)
        assert history.list_history(db, 2)["rows"] == []


def test_history_groups_mileage_side_effects_without_credentials(workspace):
    with workspace.sessions() as db:
        shoe = add_shoe(db)
        add_run(db, shoe.id)
        events = history.list_history(db, 1)["rows"]
        group = [row for row in events if row["reason"] == "run.create"]
        assert {row["entity"] for row in group} == {"runs", "shoes", "monthly_mileages"}
        assert len({row["operation_id"] for row in group}) == 1
        assert "hashed_password" not in str(events) and "token_version" not in str(events)
        first = history.list_history(db, 1, limit=2)
        second = history.list_history(db, 1, before=first["next_cursor"], limit=2)
        assert not {row["id"] for row in first["rows"]} & {row["id"] for row in second["rows"]}


def test_restore_shoe_requires_capacity_and_original_state(workspace):
    with workspace.sessions() as db:
        shoe = add_shoe(db)
        shoes.delete_shoe(db, 1, shoe.id, shoe.version)
        event = next(row for row in history.list_history(db, 1)["rows"] if row["can_restore"])
        add_shoe(db)
        with pytest.raises(Conflict, match="上限"):
            history.restore_deleted(db, 1, event["id"], replace(workspace.config, max_shoes_per_user=1))
        history.restore_deleted(db, 1, event["id"], workspace.config)
        db.expire_all()
        assert not db.get(models.Shoe, shoe.id).is_deleted


def test_restore_run_requires_original_shoe_and_quota(workspace):
    with workspace.sessions() as db:
        shoe = add_shoe(db)
        run = add_run(db, shoe.id)
        runs.delete_run(db, 1, run.id)
        event = db.query(models.AuditEvent).filter_by(entity="runs", action="delete").one()
        shoes.delete_shoe(db, 1, shoe.id)
        with pytest.raises(Conflict, match="先復原鞋款"):
            history.restore_deleted(db, 1, event.id, workspace.config)
        shoe_event = db.query(models.AuditEvent).filter_by(entity="shoes", reason="shoe.delete").one()
        history.restore_deleted(db, 1, shoe_event.id, workspace.config)
        add_run(db, shoe.id)
        with pytest.raises(Conflict, match="上限"):
            history.restore_deleted(db, 1, event.id, replace(workspace.config, max_runs_per_user=1))


@pytest.mark.parametrize("has_runs", [False, True])
def test_restore_monthly_adjustment_and_reject_later_changes(workspace, has_runs):
    with workspace.sessions() as db:
        shoe = add_shoe(db)
        if has_runs:
            add_run(db, shoe.id)
            entry = db.query(models.MonthlyMileage).one()
            monthly.update_monthly_mileage(db, 1, entry.id, schemas.MonthlyMileageUpdate(km=100))
        else:
            entry = monthly.create_monthly_mileage(db, 1, schemas.MonthlyMileageCreate(year=2026, month=1, km=100))
        db.expire_all()
        monthly.delete_monthly_mileage(db, 1, entry.id)
        event = db.query(models.AuditEvent).filter_by(entity="monthly_mileages", reason="monthly.delete").one()
        history.restore_deleted(db, 1, event.id, workspace.config)
        db.expire_all()
        assert db.query(models.MonthlyMileage).one().km == 100


def test_history_and_business_change_roll_back_together(workspace, monkeypatch):
    with workspace.sessions() as db:
        def fail():
            raise RuntimeError("commit failed")
        monkeypatch.setattr(db, "commit", fail)
        with pytest.raises(RuntimeError):
            add_shoe(db)
    with workspace.sessions() as db:
        assert db.query(models.Shoe).count() == db.query(models.AuditEvent).count() == 0
        assert db.query(models.WriteContext).count() == 0


def test_schema_five_upgrade_preserves_existing_business_data(workspace):
    with workspace.sessions() as db:
        shoe = add_shoe(db, mileage=123)
        identifier = shoe.id
    with workspace.engine.begin() as connection:
        for trigger in connection.execute(text("SELECT name FROM sqlite_master WHERE type='trigger'")).scalars().all():
            connection.exec_driver_sql(f'DROP TRIGGER "{trigger}"')
        for table in ("audit_events", "write_contexts", "restore_previews", "restore_mappings", "mutation_receipts"):
            connection.exec_driver_sql(f'DROP TABLE "{table}"')
        connection.execute(text("UPDATE schema_metadata SET value='4' WHERE key='schema_version'"))
        connection.execute(text("ALTER TABLE users DROP COLUMN backup_id"))
        connection.execute(text("ALTER TABLE users DROP COLUMN data_revision"))
    for _ in range(2):
        run_startup_migrations(workspace.engine, workspace.sessions)
    assert schema_version(workspace.engine) == 12
    assert "audit_events" in inspect(workspace.engine).get_table_names()
    with workspace.sessions() as db:
        assert db.get(models.Shoe, identifier).mileage == 123
        assert db.get(models.User, 1).backup_id


@pytest.mark.parametrize("entity", ["run", "monthly"])
def test_deleted_identifiers_are_never_reused_by_new_records(workspace, entity):
    with workspace.sessions() as db:
        if entity == "run":
            shoe = add_shoe(db)
            old = add_run(db, shoe.id)
            old_id = old.id
            runs.delete_run(db, 1, old_id)
            assert add_run(db, shoe.id).id > old_id
        else:
            payload = schemas.MonthlyMileageCreate(year=2026, month=1, km=100)
            old = monthly.create_monthly_mileage(db, 1, payload)
            old_id = old.id
            monthly.delete_monthly_mileage(db, 1, old_id)
            assert monthly.create_monthly_mileage(db, 1, payload).id > old_id


def test_startup_rebuilds_stale_audit_triggers_from_current_columns(workspace):
    """SPEC-047: a trigger created for an older column list is replaced, not kept."""
    with workspace.engine.begin() as connection:
        connection.exec_driver_sql("DROP TRIGGER audit_shoes_update")
        # Simulate a trigger from an older schema: its snapshot lacks `nickname`.
        connection.exec_driver_sql("""
            CREATE TRIGGER audit_shoes_update AFTER UPDATE ON shoes BEGIN
              INSERT INTO audit_events (user_id,operation_id,reason,entity,entity_id,action,
                before_json,after_json,created_at,restored,imported)
              VALUES (NEW.user_id,'stale','legacy.write','shoes',NEW.id,'update',
                json_object('id', OLD.id),json_object('id', NEW.id),'now',0,0);
            END
        """)
    run_startup_migrations(workspace.engine, workspace.sessions)
    with workspace.sessions() as db:
        shoe = add_shoe(db)
        shoes.update_shoe(db, 1, shoe.id, schemas.ShoeUpdate(nickname="Daily"))
        event = db.query(models.AuditEvent).filter_by(entity="shoes", action="update").one()
        assert event.operation_id != "stale"
        assert event.before_json["nickname"] == "" and event.after_json["nickname"] == "Daily"


def test_run_deletion_tombstones_survive_audit_retention(workspace):
    """SPEC-047: deletion identity no longer depends on audit rows that retention may prune."""
    from backend.services.retention import prune_account_history
    from backend.services.run_identity import add_local_tombstones

    with workspace.sessions() as db:
        shoe = add_shoe(db)
        run = add_run(db, shoe.id)
        deleted_id = run.id
        runs.delete_run(db, 1, deleted_id, run.version)
        other_shoe = add_shoe(db, uid=2)
        add_run(db, other_shoe.id, uid=2)
        prune_account_history(db, 1, audit_events=0)
        db.commit()
        assert db.query(models.AuditEvent).filter_by(user_id=1).count() == 0
        assert db.query(models.AuditEvent).filter_by(user_id=2).count() > 0
        mappings: dict[tuple[str, str], int] = {}
        add_local_tombstones(db, 1, mappings)
        assert mappings == {("run", str(deleted_id)): deleted_id}
        other: dict[tuple[str, str], int] = {}
        add_local_tombstones(db, 2, other)
        assert other == {}


def test_each_write_keeps_only_the_newest_history_per_account(workspace, monkeypatch):
    """SPEC-047: audit events, receipts and tombstones are capped per account, oldest first."""
    from backend.services import retention

    monkeypatch.setattr(retention.prune_account_history, "__kwdefaults__", {
        "audit_events": 4, "imported_audit_events": 4, "receipts": 2, "tombstones": 1,
    })
    with workspace.sessions() as db:
        shoe = add_shoe(db)
        other_shoe = add_shoe(db, uid=2)
        created = [(run.id, run.version) for run in (add_run(db, shoe.id) for _ in range(3))]
        for run_id, version in created[:2]:
            runs.delete_run(db, 1, run_id, version)
        for index in range(3):
            db.add(models.MutationReceipt(user_id=1, operation_id=f"receipt-{index:012d}",
                                          payload_hash="x", response_json={}, recorded_at=index))
        db.commit()
        add_run(db, other_shoe.id, uid=2)
        add_run(db, shoe.id)
        audit_ids = [row.id for row in db.query(models.AuditEvent).filter_by(user_id=1).order_by(models.AuditEvent.id)]
        assert len(audit_ids) == 4 and audit_ids == sorted(audit_ids)
        assert db.query(models.AuditEvent).filter_by(user_id=2).count() == 4
        assert [row.operation_id for row in db.query(models.MutationReceipt).order_by(models.MutationReceipt.recorded_at)] == [
            "receipt-000000000001", "receipt-000000000002",
        ]
        assert [row.run_id for row in db.query(models.RunTombstone).filter_by(user_id=1)] == [created[1][0]]


def test_schema_seven_backfills_tombstones_from_audit_history(workspace):
    with workspace.sessions() as db:
        shoe = add_shoe(db)
        run = add_run(db, shoe.id)
        deleted_id = run.id
        runs.delete_run(db, 1, deleted_id, run.version)
        db.add(models.AuditEvent(user_id=1, operation_id="imported", reason="run.delete", entity="runs",
                                 entity_id=999, action="delete", before_json={}, after_json=None,
                                 created_at="2026-01-01T00:00:00Z", imported=True))
        db.commit()
    with workspace.engine.begin() as connection:
        connection.exec_driver_sql("DELETE FROM run_tombstones")
        connection.exec_driver_sql("UPDATE schema_metadata SET value='6' WHERE key='schema_version'")
    run_startup_migrations(workspace.engine, workspace.sessions)
    with workspace.sessions() as db:
        assert [(row.user_id, row.run_id) for row in db.query(models.RunTombstone)] == [(1, deleted_id)]


def test_restore_refuses_to_overwrite_later_changes(workspace):
    """v4.7.1: each recovery conflict branch keeps the newer data untouched."""
    with workspace.sessions() as db:
        shoe = add_shoe(db)
        # A deleted Strava run cannot come back once the same activity exists again.
        strava_run = add_run(db, shoe.id)
        db.query(models.Run).filter_by(id=strava_run.id).update({"strava_id": "strava-1"})
        db.commit()
        runs.delete_run(db, 1, strava_run.id)
        run_event = db.query(models.AuditEvent).filter_by(entity="runs", action="delete").one()
        db.add(models.Run(user_id=1, shoe_id=shoe.id, date="2026-01-03", km=4, strava_id="strava-1"))
        db.commit()
        with pytest.raises(Conflict, match="Strava 活動已存在"):
            history.restore_deleted(db, 1, run_event.id, workspace.config)

        # A shoe edited after deletion is not silently resurrected.
        gone = add_shoe(db)
        shoes.delete_shoe(db, 1, gone.id)
        shoe_event = db.query(models.AuditEvent).filter_by(entity="shoes", reason="shoe.delete").one()
        db.query(models.Shoe).filter_by(id=gone.id).update({models.Shoe.version: models.Shoe.version + 1})
        db.commit()
        with pytest.raises(Conflict, match="後續異動"):
            history.restore_deleted(db, 1, shoe_event.id, workspace.config)

        # A deleted month cannot replace a newer record for the same month.
        payload = schemas.MonthlyMileageCreate(year=2025, month=5, km=100)
        month = monthly.create_monthly_mileage(db, 1, payload)
        monthly.delete_monthly_mileage(db, 1, month.id)
        month_event = db.query(models.AuditEvent).filter_by(
            entity="monthly_mileages", action="delete", reason="monthly.delete").one()
        monthly.create_monthly_mileage(db, 1, schemas.MonthlyMileageCreate(year=2025, month=5, km=60))
        with pytest.raises(Conflict, match="已有新紀錄"):
            history.restore_deleted(db, 1, month_event.id, workspace.config)

        # A cleared adjustment cannot be restored after the month changed again.
        logged = db.query(models.MonthlyMileage).filter_by(year=2026, month=1).one()
        monthly.update_monthly_mileage(db, 1, logged.id, schemas.MonthlyMileageUpdate(km=100))
        db.expire_all()
        monthly.delete_monthly_mileage(db, 1, logged.id)
        clear_event = db.query(models.AuditEvent).filter_by(
            entity="monthly_mileages", action="update", reason="monthly.delete").one()
        add_run(db, shoe.id)
        with pytest.raises(Conflict, match="月份已有後續異動"):
            history.restore_deleted(db, 1, clear_event.id, workspace.config)
        db.expire_all()
        assert db.query(models.MonthlyMileage).filter_by(year=2025, month=5).one().km == 60
        assert db.query(models.AuditEvent).filter_by(restored=True).count() == 0


def test_schema_eight_backfills_deleted_strava_activities_from_audit_history(workspace):
    """SPEC-055: runs deleted before schema 8 keep their Strava activity once upgraded."""
    from backend.services.run_identity import deleted_strava_ids

    with workspace.sessions() as db:
        shoe = add_shoe(db)
        strava_id = add_run(db, shoe.id).id
        manual_id = add_run(db, shoe.id).id
        db.query(models.Run).filter_by(id=strava_id).update({"strava_id": "strava-77"})
        db.commit()
        runs.delete_run(db, 1, strava_id)
        runs.delete_run(db, 1, manual_id)
        assert deleted_strava_ids(db, 1) == {"strava-77"}
        assert deleted_strava_ids(db, 2) == set()
    with workspace.engine.begin() as connection:
        connection.exec_driver_sql("UPDATE run_tombstones SET strava_id = NULL")
        connection.exec_driver_sql("UPDATE schema_metadata SET value='7' WHERE key='schema_version'")
    run_startup_migrations(workspace.engine, workspace.sessions)
    with workspace.sessions() as db:
        rows = {row.run_id: row.strava_id for row in db.query(models.RunTombstone).filter_by(user_id=1)}
        assert rows == {strava_id: "strava-77", manual_id: None}
