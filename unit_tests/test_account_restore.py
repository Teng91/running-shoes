import json
from dataclasses import replace

import pytest

from backend import models
from backend.backup_contract import parse_backup
from backend.services import account_restore, exports
from backend.services.errors import Conflict, Invalid
from unit_tests.workspace_helpers import add_run, add_shoe
from unit_tests.workspace_helpers import workspace as workspace


def archive(db):
    shoe = add_shoe(db, mileage=20)
    add_run(db, shoe.id)
    return exports.build_account_export(db, db.get(models.User, 1))[0]


def test_restore_roundtrip_is_atomic_and_idempotent(workspace):
    with workspace.sessions() as db:
        payload = archive(db)
        raw = json.dumps(payload).encode()
        before = db.query(models.Shoe).filter_by(user_id=2).count()
        preview = account_restore.preview_restore(db, 2, raw, workspace.config)
        assert preview["summary"]["new_shoes"] == 1 and preview["summary"]["new_runs"] == 1
        assert db.query(models.Shoe).filter_by(user_id=2).count() == before
        result = account_restore.apply_restore(db, 2, preview["token"], "restore-operation-1", workspace.config)
        assert account_restore.apply_restore(db, 2, preview["token"], "restore-operation-1", workspace.config) == result
        db.expire_all()
        assert db.query(models.Shoe).filter_by(user_id=2).one().mileage == 25
        assert db.query(models.MonthlyMileage).filter_by(user_id=2).one().km == 5
        assert db.query(models.Run).filter_by(user_id=2).count() == 1
        second = account_restore.preview_restore(db, 2, raw, workspace.config)
        assert second["summary"]["new_shoes"] == second["summary"]["new_runs"] == 0
        account_restore.apply_restore(db, 2, second["token"], "restore-operation-2", workspace.config)
        assert db.query(models.Run).filter_by(user_id=2).count() == 1
        assert db.query(models.AuditEvent).filter_by(user_id=2, imported=True).count() > 0


def test_restore_preview_rejects_account_theft_changes_and_key_reuse(workspace):
    with workspace.sessions() as db:
        raw = json.dumps(archive(db)).encode()
        preview = account_restore.preview_restore(db, 2, raw, workspace.config)
        with pytest.raises(Conflict):
            account_restore.apply_restore(db, 1, preview["token"], "restore-operation-1", workspace.config)
        add_shoe(db, uid=2)
        with pytest.raises(Conflict, match="預覽後變更"):
            account_restore.apply_restore(db, 2, preview["token"], "restore-operation-1", workspace.config)
        preview = account_restore.preview_restore(db, 2, raw, workspace.config)
        account_restore.apply_restore(db, 2, preview["token"], "restore-operation-1", workspace.config)
        with pytest.raises(Conflict, match="不同內容"):
            account_restore.apply_restore(db, 2, "0" * 36, "restore-operation-1", workspace.config)


def test_restore_commit_failure_rolls_back_every_business_and_mapping_row(workspace, monkeypatch):
    with workspace.sessions() as db:
        preview = account_restore.preview_restore(db, 2, json.dumps(archive(db)).encode(), workspace.config)
        def fail():
            raise RuntimeError("commit failed")
        monkeypatch.setattr(db, "commit", fail)
        with pytest.raises(RuntimeError):
            account_restore.apply_restore(db, 2, preview["token"], "restore-operation-1", workspace.config)
    with workspace.sessions() as db:
        for model in (models.Shoe, models.Run, models.MonthlyMileage, models.RestoreMapping, models.AuditEvent, models.MutationReceipt):
            assert db.query(model).filter_by(user_id=2).count() == 0


@pytest.mark.parametrize("mutation", ["secret", "foreign_id", "reference", "duplicate", "nan", "mileage", "version", "deep", "oversize"])
def test_backup_validation_rejects_untrusted_or_inconsistent_archives(workspace, mutation):
    with workspace.sessions() as db:
        payload = archive(db)
    if mutation == "secret":
        payload["hashed_password"] = "do-not-echo"
    elif mutation == "foreign_id":
        payload["runs"][0]["user_id"] = 2
    elif mutation == "reference":
        payload["runs"][0]["shoe_id"] = 99999
    elif mutation == "duplicate":
        payload["shoes"].append(payload["shoes"][0])
    elif mutation == "nan":
        payload["runs"][0]["km"] = float("nan")
    elif mutation == "mileage":
        payload["shoes"][0]["mileage"] = 1
    elif mutation == "version":
        payload["version"] = 99
    elif mutation == "deep":
        value = {}
        for _ in range(30):
            value = {"nested": value}
        payload["monthly_reports"] = [{"stats_json": value}]
    raw = b" " * (20 * 1024 * 1024 + 1) if mutation == "oversize" else json.dumps(payload).encode()
    with pytest.raises(Invalid) as error:
        parse_backup(raw)
    assert "do-not-echo" not in str(error.value)


def test_legacy_backup_and_same_model_shoes_preserve_distinct_records(workspace):
    with workspace.sessions() as db:
        payload = archive(db)
        second = dict(payload["shoes"][0], id=99, mileage=0, baseline_mileage=0)
        payload["shoes"].append(second)
        payload["version"] = 1
        payload.pop("source_id")
        payload.pop("history")
        for shoe in payload["shoes"]:
            shoe.pop("baseline_mileage")
        for month in payload["monthly_mileages"]:
            month.pop("adjustment_km")
        raw = json.dumps(payload).encode()
        preview = account_restore.preview_restore(db, 2, raw, workspace.config)
        assert preview["summary"]["legacy"]
        account_restore.apply_restore(db, 2, preview["token"], "restore-operation-1", workspace.config)
        assert db.query(models.Shoe).filter_by(user_id=2).count() == 2


def test_restore_checks_quotas_before_writing(workspace):
    with workspace.sessions() as db:
        raw = json.dumps(archive(db)).encode()
        add_shoe(db, uid=2)
        with pytest.raises(Conflict, match="上限"):
            account_restore.preview_restore(db, 2, raw, replace(workspace.config, max_shoes_per_user=1))


def test_restore_expired_preview_rejects_without_mutation(workspace):
    from datetime import UTC, datetime, timedelta
    with workspace.sessions() as db:
        preview = account_restore.preview_restore(db, 2, json.dumps(archive(db)).encode(), workspace.config)
        row = db.query(models.RestorePreview).filter_by(user_id=2, token=preview['token']).one()
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
        with pytest.raises(Conflict, match='過期'):
            account_restore.apply_restore(db, 2, preview['token'], 'restore-operation-1', workspace.config)
        assert db.query(models.Shoe).filter_by(user_id=2).count() == 0


def test_restore_incremental_source_keeps_existing_edits_and_tombstones(workspace):
    from backend import schemas
    from backend.services import runs, shoes
    with workspace.sessions() as db:
        original = archive(db)
        def merge(payload, number):
            preview = account_restore.preview_restore(db, 2, json.dumps(payload).encode(), workspace.config)
            account_restore.apply_restore(db, 2, preview['token'], f'restore-operation-{number}', workspace.config)
        merge(original, 1)
        target = db.query(models.Shoe).filter_by(user_id=2).one()
        shoes.update_shoe(db, 2, target.id, schemas.ShoeUpdate(nickname='My edit', expected_version=target.version))
        source = db.query(models.Shoe).filter_by(user_id=1).one()
        add_run(db, source.id, km=8)
        updated = exports.build_account_export(db, db.get(models.User, 1))[0]
        merge(updated, 2)
        db.expire_all()
        target = db.query(models.Shoe).filter_by(user_id=2).one()
        assert target.nickname == 'My edit' and target.mileage == 33
        target_run = db.query(models.Run).filter_by(user_id=2).order_by(models.Run.id).first()
        runs.delete_run(db, 2, target_run.id, target_run.version)
        merge(updated, 3)
        db.expire_all()
        assert db.query(models.Run).filter_by(user_id=2).count() == 1
        assert db.query(models.Shoe).filter_by(user_id=2).one().mileage == 28


def test_restore_preserves_existing_month_adjustment_goal_report_and_strava_identity(workspace):
    from backend import schemas
    from backend.services import goals, monthly
    with workspace.sessions() as db:
        payload = archive(db)
        source_run = db.query(models.Run).filter_by(user_id=1).one()
        source_run.strava_id = 'shared-activity'
        db.commit()
        payload = exports.build_account_export(db, db.get(models.User, 1))[0]
        payload['running_goal'] = {'start_year': 2026, 'monthly_km': 100, 'yearly_km': 1200}
        payload['monthly_reports'] = [{'year': 2026, 'month': 1, 'content_md': 'source', 'model': 'mock', 'stats_json': {}}]
        shoe = add_shoe(db, uid=2)
        existing = add_run(db, shoe.id, uid=2)
        existing.strava_id = 'shared-activity'
        db.commit()
        month = db.query(models.MonthlyMileage).filter_by(user_id=2).one()
        monthly.update_monthly_mileage(db, 2, month.id, schemas.MonthlyMileageUpdate(km=50, expected_version=month.version))
        goals.update_goal(db, 2, schemas.RunningGoalUpdate(start_year=2026, monthly_km=180))
        db.add(models.MonthlyReport(user_id=2, year=2026, month=1, content_md='keep', model='mock', stats_json={}))
        db.commit()
        preview = account_restore.preview_restore(db, 2, json.dumps(payload).encode(), workspace.config)
        assert preview['summary']['new_runs'] == 0
        account_restore.apply_restore(db, 2, preview['token'], 'restore-operation-1', workspace.config)
        db.expire_all()
        assert db.query(models.Run).filter_by(user_id=2).count() == 1
        assert db.query(models.MonthlyMileage).filter_by(user_id=2).one().km == 50
        assert db.query(models.RunningGoal).filter_by(user_id=2).one().monthly_km == 180
        assert db.query(models.MonthlyReport).filter_by(user_id=2).one().content_md == 'keep'


def test_restore_import_summary_capacity_never_prunes_existing_history(workspace):
    from datetime import UTC, datetime
    with workspace.sessions() as db:
        payload = archive(db)
        data = dict(imported_at=datetime(2026, 1, 5, tzinfo=UTC), start_date='2026-01-01', end_date='2026-01-05',
                    imported_count=1, imported_km=5, duplicate_count=0, unmapped_count=0, invalid_count=0)
        payload['strava_imports'] = [{**data, 'imported_at': '2026-01-06T00:00:00Z'}]
        db.add(models.StravaImport(user_id=2, **data))
        db.commit()
        config = replace(workspace.config, max_strava_import_history_per_user=1)
        preview = account_restore.preview_restore(db, 2, json.dumps(payload).encode(), config)
        assert preview['summary']['new_import_summaries'] == 0 and preview['summary']['skipped_import_summaries'] == 1
        account_restore.apply_restore(db, 2, preview['token'], 'restore-operation-1', config)
        assert db.query(models.StravaImport).filter_by(user_id=2).one().imported_at.day == 5
        own_backup = exports.build_account_export(db, db.get(models.User, 2))[0]
        config = replace(config, max_strava_import_history_per_user=2)
        own_preview = account_restore.preview_restore(db, 2, json.dumps(own_backup).encode(), config)
        assert own_preview['summary']['new_import_summaries'] == 0, 'own backup recognizes existing import summaries'
        account_restore.apply_restore(db, 2, own_preview['token'], 'restore-operation-2', config)
        assert db.query(models.StravaImport).filter_by(user_id=2).count() == 1


def test_export_uses_one_read_snapshot_while_another_connection_writes(workspace):
    from sqlalchemy import event
    with workspace.sessions() as db:
        shoe = add_shoe(db, mileage=20)
        shoe_id = shoe.id
    interleaved = False
    def write_between_collections(connection, cursor, statement, parameters, context, executemany):
        nonlocal interleaved
        if not interleaved and 'FROM shoes' in statement and statement.lstrip().upper().startswith('SELECT'):
            interleaved = True
            with workspace.sessions() as writer:
                add_run(writer, shoe_id)
    event.listen(workspace.engine, 'after_cursor_execute', write_between_collections)
    try:
        with workspace.sessions() as reader:
            payload = exports.build_account_export(reader, reader.get(models.User, 1))[0]
            assert parse_backup(json.dumps(payload).encode()).shoes[0].mileage == 20
            assert payload['runs'] == []
        assert interleaved
    finally:
        event.remove(workspace.engine, 'after_cursor_execute', write_between_collections)
    with workspace.sessions() as db:
        assert db.get(models.Shoe, shoe_id).mileage == 25
