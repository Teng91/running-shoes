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
    assert schema_version(workspace.engine) == 6
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
