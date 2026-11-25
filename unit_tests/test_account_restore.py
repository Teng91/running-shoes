import json
from dataclasses import replace

import pytest

from backend import models
from backend.backup_contract import MAX_BACKUP_BYTES, parse_backup
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
    raw = b" " * (MAX_BACKUP_BYTES + 1) if mutation == "oversize" else json.dumps(payload).encode()
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


def test_update_import_refreshes_existing_data_and_recalculates_totals(workspace):
    from backend.services import report_storage, runs
    with workspace.sessions() as db:
        payload = archive(db)
        payload['running_goal'] = {'start_year': 2026, 'monthly_km': 100, 'yearly_km': 1200}
        payload['monthly_reports'] = [{'year': 2026, 'month': 1, 'content_md': 'first', 'model': 'mock', 'stats_json': {}}]
        preview = account_restore.preview_restore(db, 2, json.dumps(payload).encode(), workspace.config)
        account_restore.apply_restore(db, 2, preview['token'], 'initial-cloud-import', workspace.config)
        imported_shoe = db.query(models.Shoe).filter_by(user_id=2).one()
        imported_run_id = db.query(models.Run).filter_by(user_id=2).one().id
        add_run(db, imported_shoe.id, uid=2, km=3)
        local_shoe = add_shoe(db, uid=2, mileage=7)
        local_shoe_id = local_shoe.id
        generation = report_storage.begin_generation(db, 2, 2026, 1)
        payload['shoes'][0].update(nickname='Cloud updated', mileage=32, baseline_mileage=30)
        payload['shoes'].append(dict(payload['shoes'][0], id=99, nickname='Second', mileage=48, baseline_mileage=40))
        payload['runs'][0].update(date='2026-02-02', km=8, shoe_id=99)
        payload['runs'].append(dict(payload['runs'][0], id=99, shoe_id=payload['shoes'][0]['id'], km=2))
        payload['monthly_mileages'] = [{'year': 2026, 'month': 1, 'km': 12, 'adjustment_km': 12},
                                       {'year': 2026, 'month': 2, 'km': 12, 'adjustment_km': 2}]
        payload['running_goal']['monthly_km'] = 180
        payload['running_goal']['yearly_km'] = 2160
        payload['monthly_reports'][0]['content_md'] = 'cloud updated'
        raw = json.dumps(payload).encode()
        preview = account_restore.preview_restore(db, 2, raw, workspace.config, 'update')
        summary = preview['summary']
        assert (summary['new_shoes'], summary['updated_shoes'], summary['new_runs'], summary['updated_runs']) == (1, 1, 1, 1)
        assert summary['updated_months'] == summary['updated_reports'] == 1 and summary['updated_goal']
        result = account_restore.apply_restore(db, 2, preview['token'], 'update-cloud-import', workspace.config)
        assert account_restore.apply_restore(db, 2, preview['token'], 'update-cloud-import', workspace.config) == result
        db.expire_all()
        assert db.query(models.Shoe).filter_by(user_id=2, nickname='Cloud updated').one().mileage == 35
        assert db.query(models.Shoe).filter_by(user_id=2, nickname='Second').one().mileage == 48
        assert db.get(models.Shoe, local_shoe_id).mileage == 7
        assert db.get(models.Run, imported_run_id).date == '2026-02-02'
        assert {row.month: row.km for row in db.query(models.MonthlyMileage).filter_by(user_id=2)} == {1: 15, 2: 12}
        assert db.query(models.RunningGoal).filter_by(user_id=2).one().monthly_km == 180
        assert db.query(models.MonthlyReport).filter_by(user_id=2).one().content_md == 'cloud updated'
        assert report_storage.persist_current_report(db, 2, 2026, 1, generation, 'stale', 'mock', {}) is None
        assert db.query(models.Shoe).filter_by(user_id=1).one().mileage == 25
        preview = account_restore.preview_restore(db, 2, raw, workspace.config, 'update')
        account_restore.apply_restore(db, 2, preview['token'], 'repeat-cloud-import', workspace.config)
        db.expire_all()
        assert db.query(models.Run).filter_by(user_id=2).count() == 3
        assert db.query(models.Shoe).filter_by(user_id=2, nickname='Cloud updated').one().mileage == 35
        run = db.get(models.Run, imported_run_id)
        runs.delete_run(db, 2, run.id, run.version)
        preview = account_restore.preview_restore(db, 2, raw, workspace.config, 'update')
        assert preview['summary']['updated_runs'] == 0
        assert preview['summary']['unchanged_runs'] == preview['summary']['preserved_deleted_runs'] == 1
        account_restore.apply_restore(db, 2, preview['token'], 'preserve-run-deletion', workspace.config)
        assert db.query(models.Run).filter_by(user_id=2).count() == 2


def test_update_preview_binds_mode_rejects_legacy_and_rolls_back(workspace, monkeypatch):
    with workspace.sessions() as db:
        payload = archive(db)
        raw = json.dumps(payload).encode()
        preview = account_restore.preview_restore(db, 2, raw, workspace.config, 'update')
        with pytest.raises(Conflict):
            account_restore.apply_restore(db, 1, preview['token'], 'foreign-update-import', workspace.config)
        stored = db.query(models.RestorePreview).filter_by(user_id=2, token=preview['token']).one()
        stored.payload_json = {**stored.payload_json, 'mode': 'merge'}
        db.commit()
        with pytest.raises(Conflict, match='內容已變更'):
            account_restore.apply_restore(db, 2, preview['token'], 'changed-update-mode', workspace.config)
        preview = account_restore.preview_restore(db, 2, raw, workspace.config, 'update')
        def fail():
            raise RuntimeError('commit failed')
        with monkeypatch.context() as patch:
            patch.setattr(db, 'commit', fail)
            with pytest.raises(RuntimeError):
                account_restore.apply_restore(db, 2, preview['token'], 'rollback-update-import', workspace.config)
        assert db.query(models.Shoe).filter_by(user_id=2).count() == 0
        payload['version'] = 1
        payload.pop('source_id')
        with pytest.raises(Invalid, match='v2'):
            account_restore.preview_restore(db, 2, json.dumps(payload).encode(), workspace.config, 'update')
        with pytest.raises(Invalid):
            account_restore.preview_restore(db, 2, raw, workspace.config, 'unknown')


def test_update_checks_resulting_shoe_quota_and_strava_conflicts(workspace):
    from backend.services import shoes
    with workspace.sessions() as db:
        payload = archive(db)
        raw = json.dumps(payload).encode()
        preview = account_restore.preview_restore(db, 2, raw, workspace.config)
        account_restore.apply_restore(db, 2, preview['token'], 'quota-initial-import', workspace.config)
        target = db.query(models.Shoe).filter_by(user_id=2).one()
        shoes.delete_shoe(db, 2, target.id, target.version)
        add_shoe(db, uid=2)
        with pytest.raises(Conflict, match='上限'):
            account_restore.preview_restore(db, 2, raw, replace(workspace.config, max_shoes_per_user=1), 'update')
        target = db.query(models.Shoe).filter_by(user_id=2, is_deleted=False).one()
        another_run = add_run(db, target.id, uid=2)
        another_run.strava_id = 'conflicting-strava'
        db.commit()
        payload['runs'][0]['strava_id'] = 'conflicting-strava'
        with pytest.raises(Conflict, match='Strava'):
            account_restore.preview_restore(db, 2, json.dumps(payload).encode(), workspace.config, 'update')
        assert db.query(models.Shoe).filter_by(user_id=2, is_deleted=True).count() == 1


def test_update_http_mode_and_legacy_preview_compatibility(workspace):
    from fastapi.testclient import TestClient

    from backend.app_factory import create_app
    from backend.services.fingerprints import payload_hash
    from unit_tests.token_helpers import token_for_name
    with workspace.sessions() as db:
        raw = json.dumps(archive(db)).encode()
        preview = account_restore.preview_restore(db, 2, raw, workspace.config)
        stored = db.query(models.RestorePreview).filter_by(user_id=2).one()
        stored.payload_json = stored.payload_json['backup']
        stored.payload_hash = payload_hash(stored.payload_json)
        db.commit()
        account_restore.apply_restore(db, 2, preview['token'], 'legacy-preview-apply', workspace.config)
    app = create_app(workspace.config, db_engine=workspace.engine, session_factory=workspace.sessions)
    headers = {'Authorization': 'Bearer ' + token_for_name(workspace.sessions, 'two', secret_key=workspace.config.secret_key or None)}
    with TestClient(app) as client:
        response = client.post('/api/account-restore/preview?mode=update', content=raw, headers=headers)
        assert response.status_code == 200 and response.json()['summary']['mode'] == 'update'
        assert client.post('/api/account-restore/preview?mode=unknown', content=raw, headers=headers).status_code == 422


def test_update_rejects_two_source_runs_targeting_one_strava_record(workspace):
    with workspace.sessions() as db:
        payload = archive(db)
        payload['runs'][0]['strava_id'] = 'stable-strava'
        preview = account_restore.preview_restore(db, 2, json.dumps(payload).encode(), workspace.config)
        account_restore.apply_restore(db, 2, preview['token'], 'strava-initial-import', workspace.config)
        payload['runs'][0]['strava_id'] = None
        payload['runs'].append(dict(payload['runs'][0], id=99, strava_id='stable-strava'))
        payload['shoes'][0]['mileage'] += 5
        payload['monthly_mileages'][0]['km'] += 5
        with pytest.raises(Conflict, match='多筆來源'):
            account_restore.preview_restore(db, 2, json.dumps(payload).encode(), workspace.config, 'update')
        row = db.query(models.Run).filter_by(user_id=2).one()
        assert row.km == 5 and row.strava_id == 'stable-strava'


def test_identical_update_preserves_versions_history_and_unrelated_edits(workspace):
    from backend import schemas
    from backend.services import monthly, shoes
    with workspace.sessions() as db:
        payload = archive(db)
        payload['running_goal'] = {'start_year': 2026, 'monthly_km': 100, 'yearly_km': 1200}
        payload['monthly_reports'] = [{'year': 2026, 'month': 1, 'content_md': 'unchanged', 'model': 'mock',
                                      'stats_json': {}, 'created_at': '2026-01-01T00:00:00Z', 'updated_at': '2026-01-01T00:00:00Z'}]
        raw = json.dumps(payload).encode()
        preview = account_restore.preview_restore(db, 2, raw, workspace.config)
        account_restore.apply_restore(db, 2, preview['token'], 'noop-initial-import', workspace.config)
        extra = add_shoe(db, uid=2, mileage=7)
        extra_id, extra_version = extra.id, extra.version
        monthly.create_monthly_mileage(db, 2, schemas.MonthlyMileageCreate(year=2025, month=12, km=12))
        def snapshot():
            db.expire_all()
            return ({kind.__tablename__: [(row.id, row.version) for row in db.query(kind).filter_by(user_id=2).order_by(kind.id)]
                     for kind in (models.Shoe, models.Run, models.MonthlyMileage, models.RunningGoal)},
                    db.query(models.AuditEvent).filter_by(user_id=2).count(), db.get(models.User, 2).data_revision)
        before = snapshot()
        preview = account_restore.preview_restore(db, 2, raw, workspace.config, 'update')
        account_restore.apply_restore(db, 2, preview['token'], 'identical-import-noop', workspace.config)
        assert snapshot() == before
        shoes.update_shoe(db, 2, extra_id, schemas.ShoeUpdate(nickname='Local edit succeeds', expected_version=extra_version))
        unrelated = db.query(models.MonthlyMileage).filter_by(user_id=2, year=2025).one()
        old_month_version = unrelated.version
        payload['runs'][0]['km'] = 8
        payload['shoes'][0]['mileage'] = 28
        payload['monthly_mileages'][0]['km'] = 8
        preview = account_restore.preview_restore(db, 2, json.dumps(payload).encode(), workspace.config, 'update')
        account_restore.apply_restore(db, 2, preview['token'], 'changed-import-mileage', workspace.config)
        db.expire_all()
        assert db.query(models.MonthlyMileage).filter_by(user_id=2, year=2025).one().version == old_month_version
        assert db.query(models.Shoe).filter_by(user_id=2, nickname='').one().mileage == 28
        assert db.get(models.Shoe, extra_id).version == extra_version + 1


def test_late_preview_cannot_revoke_newer_token(workspace, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, current_thread
    with workspace.sessions() as db:
        raw = json.dumps(archive(db)).encode()
    started, finish = Event(), Event()
    original = account_restore.parse_backup
    def delayed(raw):
        backup = original(raw)
        if current_thread().name.startswith('older-preview'):
            started.set()
            assert finish.wait(10)
        return backup
    def preview(mode):
        with workspace.sessions() as db:
            return account_restore.preview_restore(db, 2, raw, workspace.config, mode)
    monkeypatch.setattr(account_restore, 'parse_backup', delayed)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix='older-preview') as pool:
        old = pool.submit(preview, 'merge')
        assert started.wait(10)
        newer = preview('update')
        finish.set()
        older = old.result()
    with workspace.sessions() as db:
        assert db.query(models.RestorePreview).filter_by(user_id=2).count() == 2
        account_restore.discard_preview(db, 1, older['token'])
        assert db.query(models.RestorePreview).filter_by(user_id=2).count() == 2
        result = account_restore.apply_restore(db, 2, newer['token'], 'late-preview-new-apply', workspace.config)
        assert result['summary']['mode'] == 'update'
        account_restore.discard_preview(db, 2, older['token'])
        assert db.query(models.RestorePreview).filter_by(user_id=2).count() == 0


def test_preview_limits_expiration_and_discard_are_user_scoped(workspace, monkeypatch):
    from datetime import UTC, datetime, timedelta
    with workspace.sessions() as db:
        raw = json.dumps(archive(db)).encode()
        monkeypatch.setattr(account_restore, 'MAX_ACTIVE_PREVIEWS', 2)
        first = account_restore.preview_restore(db, 2, raw, workspace.config)
        second = account_restore.preview_restore(db, 2, raw, workspace.config)
        with pytest.raises(Conflict, match='上限'):
            account_restore.preview_restore(db, 2, raw, workspace.config)
        row = db.get(models.RestorePreview, (2, first['token']))
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
        account_restore.preview_restore(db, 2, raw, workspace.config)
        assert db.get(models.RestorePreview, (2, first['token'])) is None
        account_restore.discard_preview(db, 2, second['token'])
        monkeypatch.setattr(account_restore, 'MAX_PREVIEW_BYTES', 1)
        with pytest.raises(Conflict, match='容量'):
            account_restore.preview_restore(db, 2, raw, workspace.config)
        assert db.query(models.RestorePreview).filter_by(user_id=2).count() == 1


def test_schema_six_preserves_existing_preview_and_is_idempotent(workspace):
    from sqlalchemy import inspect, text

    from backend.migrations import run_startup_migrations, schema_version
    with workspace.sessions() as db:
        raw = json.dumps(archive(db)).encode()
        preview = account_restore.preview_restore(db, 2, raw, workspace.config)
        before = exports.build_account_export(db, db.get(models.User, 1))[0]
    with workspace.engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE old_restore_previews (user_id INTEGER NOT NULL PRIMARY KEY REFERENCES users(id), token VARCHAR(36) NOT NULL, revision INTEGER NOT NULL, payload_hash VARCHAR(64) NOT NULL, payload_json JSON NOT NULL, expires_at DATETIME NOT NULL)')
        connection.exec_driver_sql('INSERT INTO old_restore_previews SELECT * FROM restore_previews')
        connection.exec_driver_sql('DROP TABLE restore_previews')
        connection.exec_driver_sql('ALTER TABLE old_restore_previews RENAME TO restore_previews')
        connection.execute(text("UPDATE schema_metadata SET value='5' WHERE key='schema_version'"))
    run_startup_migrations(workspace.engine, workspace.sessions)
    run_startup_migrations(workspace.engine, workspace.sessions)
    assert schema_version(workspace.engine) == 14
    assert inspect(workspace.engine).get_pk_constraint('restore_previews')['constrained_columns'] == ['user_id', 'token']
    with workspace.sessions() as db:
        after = exports.build_account_export(db, db.get(models.User, 1))[0]
        assert {key: value for key, value in before.items() if key != 'exported_at'} == {key: value for key, value in after.items() if key != 'exported_at'}
        second = account_restore.preview_restore(db, 2, raw, workspace.config)
        assert second['token'] != preview['token']
        account_restore.apply_restore(db, 2, preview['token'], 'schema-five-old-preview', workspace.config)


def test_discard_preview_http_requires_its_account(workspace):
    from fastapi.testclient import TestClient

    from backend.app_factory import create_app
    from unit_tests.token_helpers import token_for_name
    with workspace.sessions() as db:
        preview = account_restore.preview_restore(db, 2, json.dumps(archive(db)).encode(), workspace.config)
    app = create_app(workspace.config, db_engine=workspace.engine, session_factory=workspace.sessions)
    def headers(name):
        return {'Authorization': 'Bearer ' + token_for_name(workspace.sessions, name, secret_key=workspace.config.secret_key or None)}
    with TestClient(app) as client:
        path = '/api/account-restore/preview/' + preview['token']
        assert client.delete(path).status_code in (401, 403)
        assert client.delete(path, headers=headers('one')).status_code == 200
        with workspace.sessions() as db:
            assert db.get(models.RestorePreview, (2, preview['token'])) is not None
        assert client.delete(path, headers=headers('two')).status_code == 200
        assert client.delete(path, headers=headers('two')).status_code == 200


def test_preview_schema_rollback_preserves_business_rows(workspace):
    from pathlib import Path

    from sqlalchemy import inspect

    from backend.migrations import run_startup_migrations, schema_version
    with workspace.sessions() as db:
        raw = json.dumps(archive(db)).encode()
        account_restore.preview_restore(db, 2, raw, workspace.config)
        account_restore.preview_restore(db, 2, raw, workspace.config)
        before = db.query(models.AuditEvent).count()
    connection = workspace.engine.raw_connection()
    try:
        connection.executescript(Path('scripts/rollback_schema_fourteen.sql').read_text(encoding="utf-8"))
        connection.executescript(Path('scripts/rollback_schema_thirteen.sql').read_text(encoding="utf-8"))
        connection.executescript(Path('scripts/rollback_schema_twelve.sql').read_text(encoding="utf-8"))
        connection.executescript(Path('scripts/rollback_schema_eleven.sql').read_text(encoding="utf-8"))
        connection.executescript(Path('scripts/rollback_schema_ten.sql').read_text(encoding="utf-8"))
        connection.executescript(Path('scripts/rollback_schema_nine.sql').read_text(encoding="utf-8"))
        connection.executescript(Path('scripts/rollback_schema_eight.sql').read_text(encoding="utf-8"))
        connection.executescript(Path('scripts/rollback_schema_seven.sql').read_text(encoding="utf-8"))
        connection.executescript(Path('scripts/rollback_preview_schema.sql').read_text(encoding="utf-8"))
    finally:
        connection.close()
    assert schema_version(workspace.engine) == 5
    assert inspect(workspace.engine).get_pk_constraint('restore_previews')['constrained_columns'] == ['user_id']
    with workspace.sessions() as db:
        assert db.query(models.Shoe).filter_by(user_id=1).one().mileage == 25
        assert db.query(models.AuditEvent).count() == before
        assert db.query(models.RestorePreview).count() == 0
    run_startup_migrations(workspace.engine, workspace.sessions)
    assert schema_version(workspace.engine) == 14


def test_export_contract_limits_and_explicit_history_omission(workspace):
    from fastapi.testclient import TestClient

    from backend.app_factory import create_app
    from backend.backup_contract import ARCHIVE_LIMITS
    from unit_tests.token_helpers import token_for_name
    with workspace.sessions() as db:
        history = {'user_id': 1, 'operation_id': 'synthetic-export-boundary', 'reason': 'shoe.update',
                   'entity': 'shoes', 'entity_id': 1, 'action': 'update', 'before_json': None,
                   'after_json': None, 'created_at': '2026-10-24T00:00:00Z', 'restored': False, 'imported': False}
        db.bulk_insert_mappings(models.AuditEvent, [history] * ARCHIVE_LIMITS['history'])
        db.commit()
        payload, _ = exports.build_account_export(db, db.get(models.User, 1))
        assert len(parse_backup(json.dumps(payload).encode()).history) == ARCHIVE_LIMITS['history']
        db.bulk_insert_mappings(models.AuditEvent, [history, {**history, 'user_id': 2}])
        db.commit()
        with pytest.raises(Invalid, match=rf"異動歷史.*{ARCHIVE_LIMITS['history']:,}.*取消包含異動歷史"):
            exports.build_account_export(db, db.get(models.User, 1))
        payload, name = exports.build_account_export(db, db.get(models.User, 1), include_history=False)
        assert parse_backup(json.dumps(payload).encode()).history == []
        assert name.endswith('_without_history.json')
        other, _ = exports.build_account_export(db, db.get(models.User, 2))
        assert len(other['history']) == 1
    app = create_app(workspace.config, db_engine=workspace.engine, session_factory=workspace.sessions)
    headers = {'Authorization': 'Bearer ' + token_for_name(workspace.sessions, 'one', secret_key=workspace.config.secret_key or None)}
    with TestClient(app) as client:
        failure = client.get('/api/export/account', headers=headers)
        assert failure.status_code == 400 and '取消包含異動歷史' in failure.json()['detail']
        response = client.get('/api/export/account?include_history=false', headers=headers)
        assert response.status_code == 200
        assert parse_backup(response.content).history == []
        assert '_without_history.json' in response.headers['Content-Disposition']
        assert client.get('/api/export/account?include_history=false').status_code in (401, 403)
    with workspace.sessions() as db:
        assert db.query(models.AuditEvent).filter_by(user_id=1).count() == ARCHIVE_LIMITS['history'] + 1


def test_export_uses_import_byte_budget_and_rejects_unsafe_content(workspace, monkeypatch):
    from datetime import UTC, datetime

    from backend import backup_contract
    exported_at = datetime(2026, 10, 24, tzinfo=UTC)
    with workspace.sessions() as db:
        add_shoe(db, nickname='中文鞋款')
        payload, _ = exports.build_account_export(db, db.get(models.User, 1), include_history=False, now=exported_at)
        size = len(json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode())
        monkeypatch.setattr(backup_contract, 'MAX_BACKUP_BYTES', size)
        exports.build_account_export(db, db.get(models.User, 1), include_history=False, now=exported_at)
        monkeypatch.setattr(backup_contract, 'MAX_BACKUP_BYTES', size - 1)
        with pytest.raises(Invalid, match='未產生下載檔'):
            exports.build_account_export(db, db.get(models.User, 1), include_history=False, now=exported_at)
        monkeypatch.setattr(backup_contract, 'MAX_BACKUP_BYTES', MAX_BACKUP_BYTES)
        db.add(models.MonthlyReport(user_id=1, year=2026, month=1, content_md='synthetic', model='mock',
                                     stats_json={'api_key': 'synthetic-never-export'}))
        db.commit()
        with pytest.raises(Invalid, match='不符合匯入格式') as error:
            exports.build_account_export(db, db.get(models.User, 1), include_history=False, now=exported_at)
        assert 'synthetic-never-export' not in str(error.value)


def test_export_collection_capacity_is_shared_and_never_truncates(workspace, monkeypatch):
    from backend.backup_contract import ARCHIVE_LIMITS
    with workspace.sessions() as db:
        add_shoe(db)
        add_shoe(db)
        monkeypatch.setitem(ARCHIVE_LIMITS, 'shoes', 1)
        with pytest.raises(Invalid, match=r'鞋款.*1 筆.*完整資料庫備份'):
            exports.build_account_export(db, db.get(models.User, 1))
        assert db.query(models.Shoe).filter_by(user_id=1).count() == 2
        from backend import backup_contract
        monkeypatch.setitem(ARCHIVE_LIMITS, 'shoes', 5000)
        monkeypatch.setattr(backup_contract, 'MAX_BACKUP_BYTES', 1)
        serialized = []
        original = exports._serialize_shoe
        def observed(row):
            serialized.append(row.id)
            return original(row)
        monkeypatch.setattr(exports, '_serialize_shoe', observed)
        with pytest.raises(Invalid, match='未產生下載檔'):
            exports.build_account_export(db, db.get(models.User, 1), include_history=False)
        assert len(serialized) == 1, 'byte overflow stops before serializing the remaining rows'


def test_import_diff_preview_matches_patches_and_preserves_local_runs(workspace):
    from backend.services import runs
    with workspace.sessions() as db:
        payload = archive(db)
        payload['running_goal'] = {'start_year': 2026, 'monthly_km': 100, 'yearly_km': 1200}
        payload['monthly_reports'] = [{'year': 2026, 'month': 1, 'content_md': 'same', 'model': 'mock', 'stats_json': {}}]
        raw = json.dumps(payload).encode()
        first = account_restore.preview_restore(db, 2, raw, workspace.config, 'update')
        assert (first['summary']['new_shoes'], first['summary']['new_runs'], first['summary']['new_months'], first['summary']['new_reports']) == (1, 1, 1, 1)
        assert first['summary']['new_goal']
        account_restore.apply_restore(db, 2, first['token'], 'diff-initial-transfer', workspace.config)
        target_shoe = db.query(models.Shoe).filter_by(user_id=2).one()
        extra_shoe = add_shoe(db, uid=2, mileage=9)
        extra_shoe_id, extra_version = extra_shoe.id, extra_shoe.version
        add_run(db, target_shoe.id, uid=2, km=3)
        same = account_restore.preview_restore(db, 2, raw, workspace.config, 'update')
        summary = same['summary']
        assert all(summary['updated_' + kind] == 0 for kind in ('shoes', 'runs', 'months', 'reports'))
        assert all(summary['unchanged_' + kind] == 1 for kind in ('shoes', 'runs', 'months', 'reports'))
        assert summary['unchanged_goal'] and not summary['updated_goal']
        account_restore.apply_restore(db, 2, same['token'], 'diff-identical-transfer', workspace.config)
        assert db.get(models.Shoe, target_shoe.id).mileage == 28
        before = {kind.__tablename__: {row.id: row.version for row in db.query(kind).filter_by(user_id=2)}
                  for kind in (models.Shoe, models.Run, models.MonthlyMileage)}
        payload['runs'][0].update(date='2026-02-02', km=7)
        payload['shoes'][0]['mileage'] = 27
        payload['monthly_mileages'] = [{'year': 2026, 'month': 1, 'km': 0, 'adjustment_km': 0},
                                       {'year': 2026, 'month': 2, 'km': 7, 'adjustment_km': 0}]
        payload['running_goal'].update(monthly_km=180, yearly_km=2160)
        payload['monthly_reports'][0]['content_md'] = 'changed'
        changed = account_restore.preview_restore(db, 2, json.dumps(payload).encode(), workspace.config, 'update')
        summary = changed['summary']
        assert all(summary['updated_' + kind] == 1 for kind in ('shoes', 'runs', 'months', 'reports'))
        assert summary['new_months'] == 1 and summary['updated_goal']
        result = account_restore.apply_restore(db, 2, changed['token'], 'diff-changed-transfer', workspace.config)
        assert result['summary'] == summary
        db.expire_all()
        for kind, key in ((models.Shoe, 'shoes'), (models.Run, 'runs'), (models.MonthlyMileage, 'months')):
            actual = sum(row.version != before[kind.__tablename__][row.id] for row in db.query(kind).filter_by(user_id=2)
                         if row.id in before[kind.__tablename__])
            assert actual == summary['updated_' + key]
        assert db.get(models.Shoe, extra_shoe_id).version == extra_version
        assert db.get(models.Shoe, target_shoe.id).mileage == 30
        assert {row.month: row.km for row in db.query(models.MonthlyMileage).filter_by(user_id=2)} == {1: 3, 2: 7}
        target_run = db.query(models.Run).filter_by(user_id=2, date='2026-02-02').one()
        runs.delete_run(db, 2, target_run.id, target_run.version)
        deleted = account_restore.preview_restore(db, 2, json.dumps(payload).encode(), workspace.config, 'update')['summary']
        assert deleted['updated_runs'] == deleted['unchanged_runs'] == 0
        assert deleted['preserved_deleted_runs'] == 1


@pytest.mark.parametrize('mode', ['merge', 'update'])
def test_own_archive_preserves_deleted_runs(workspace, mode):
    from backend.services import runs
    with workspace.sessions() as db:
        payload = archive(db)
        run = db.query(models.Run).filter_by(user_id=1).one()
        runs.delete_run(db, 1, run.id)
        preview = account_restore.preview_restore(db, 1, json.dumps(payload).encode(), workspace.config, mode)
        assert preview['summary']['new_runs'] == 0
        assert preview['summary']['preserved_deleted_runs'] == 1
        account_restore.apply_restore(db, 1, preview['token'], 'own-deleted-restore', workspace.config)
        assert db.query(models.Run).filter_by(user_id=1).count() == 0
        assert db.query(models.Shoe).filter_by(user_id=1).one().mileage == 20


def test_recovered_run_retains_all_source_aliases(workspace):
    from backend import schemas
    from backend.services import history, runs
    with workspace.sessions() as db:
        payload = archive(db)
        def apply(data, uid, key):
            preview = account_restore.preview_restore(db, uid, json.dumps(data).encode(), workspace.config, 'update')
            account_restore.apply_restore(db, uid, preview['token'], key, workspace.config)
            db.expire_all()
            return preview['summary']
        apply(payload, 2, 'initial-source-import')
        local_backup = exports.build_account_export(db, db.get(models.User, 2))[0]
        target = db.query(models.Run).filter_by(user_id=2).one()
        old_id = target.id
        db.add(models.RestoreMapping(user_id=1, source_id='other-account-source', entity='run', source_key='999', target_id=old_id))
        db.commit()
        # Two recovery cycles must keep every previous ID as an alias.
        for _cycle in range(2):
            target = db.query(models.Run).filter_by(user_id=2).one()
            runs.delete_run(db, 2, target.id)
            event = db.query(models.AuditEvent).filter_by(user_id=2, entity='runs', action='delete', imported=False, restored=False).one()
            history.restore_deleted(db, 2, event.id, workspace.config)
        source_run = db.query(models.Run).filter_by(user_id=1).one()
        runs.update_run(db, 1, source_run.id, schemas.RunUpdate(km=9))
        updated = exports.build_account_export(db, db.get(models.User, 1))[0]
        summary = apply(updated, 2, 'update-recovered-source')
        assert summary['updated_runs'] == 1 and summary['new_runs'] == summary['preserved_deleted_runs'] == 0
        assert db.query(models.Run).filter_by(user_id=2).one().km == 9
        summary = apply(local_backup, 2, 'update-recovered-own')
        assert summary['updated_runs'] == 1 and summary['new_runs'] == 0
        assert db.query(models.Run).filter_by(user_id=2).one().km == 5
        assert db.query(models.RestoreMapping).filter_by(user_id=1, source_id='other-account-source').one().target_id == old_id


def test_imported_history_cannot_create_local_tombstones(workspace):
    """SPEC-047: only a local deletion writes a tombstone; imported audit rows never do."""
    from backend.services import runs
    with workspace.sessions() as db:
        payload = archive(db)
        run = db.query(models.Run).filter_by(user_id=1).one()
        runs.delete_run(db, 1, run.id)
        event = db.query(models.AuditEvent).filter_by(user_id=1, entity='runs', action='delete').one()
        event.imported = True
        db.query(models.RunTombstone).filter_by(user_id=1).delete()
        db.commit()
        preview = account_restore.preview_restore(db, 1, json.dumps(payload).encode(), workspace.config)
        assert preview['summary']['new_runs'] == 1
        assert preview['summary']['preserved_deleted_runs'] == 0


def test_local_deletion_tombstone_is_preserved_after_audit_rows_are_pruned(workspace):
    from backend.services import runs
    with workspace.sessions() as db:
        payload = archive(db)
        run = db.query(models.Run).filter_by(user_id=1).one()
        runs.delete_run(db, 1, run.id)
        db.query(models.AuditEvent).filter_by(user_id=1).delete()
        db.commit()
        preview = account_restore.preview_restore(db, 1, json.dumps(payload).encode(), workspace.config)
        assert preview['summary']['new_runs'] == 0
        assert preview['summary']['preserved_deleted_runs'] == 1


def test_recovery_source_aliases_roll_back_with_failed_commit(workspace, monkeypatch):
    from backend.services import history, runs
    with workspace.sessions() as db:
        payload = archive(db)
        preview = account_restore.preview_restore(db, 1, json.dumps(payload).encode(), workspace.config)
        account_restore.apply_restore(db, 1, preview['token'], 'remember-own-source', workspace.config)
        run = db.query(models.Run).filter_by(user_id=1).one()
        old_id = run.id
        db.add(models.RestoreMapping(user_id=1, source_id=payload['source_id'], entity='run', source_key=str(old_id), target_id=old_id))
        db.commit()
        runs.delete_run(db, 1, old_id)
        event = db.query(models.AuditEvent).filter_by(user_id=1, entity='runs', action='delete', imported=False).one()
        event_id = event.id
        def fail():
            raise RuntimeError('synthetic commit failure')
        monkeypatch.setattr(db, 'commit', fail)
        with pytest.raises(RuntimeError, match='synthetic'):
            history.restore_deleted(db, 1, event_id, workspace.config)
    with workspace.sessions() as db:
        assert db.query(models.Run).filter_by(user_id=1).count() == 0
        assert not db.get(models.AuditEvent, event_id).restored
        assert db.query(models.RestoreMapping).filter_by(user_id=1, entity='run').one().target_id == old_id


def test_portable_source_recovery_aliases_roundtrip(workspace):
    from backend import schemas
    from backend.services import history, runs
    with workspace.sessions() as db:
        shoe = add_shoe(db)
        add_run(db, shoe.id)
        def export(uid):
            return exports.build_account_export(db, db.get(models.User, uid), include_history=False)[0]
        def apply(payload, key):
            preview = account_restore.preview_restore(db, 2, json.dumps(payload).encode(), workspace.config, 'update')
            account_restore.apply_restore(db, 2, preview['token'], key, workspace.config)
            db.expire_all()
            return preview['summary']
        def recover(uid):
            row = db.query(models.Run).filter_by(user_id=uid).one()
            old_id = row.id
            runs.delete_run(db, uid, old_id)
            event = db.query(models.AuditEvent).filter_by(user_id=uid, entity='runs', action='delete', imported=False, restored=False).one()
            history.restore_deleted(db, uid, event.id, workspace.config)
            return old_id
        original = export(1)
        assert original['version'] == 6
        apply(original, 'portable-first-import')
        source_old = recover(1)
        restored = export(1)
        assert restored['runs'][0]['aliases'] == [source_old] and restored['history'] == []
        summary = apply(restored, 'portable-restored-import')
        assert summary['new_runs'] == summary['updated_runs'] == 0
        assert db.query(models.Run).filter_by(user_id=2).count() == 1
        target_old = recover(2)
        target_archive = export(2)
        assert target_archive['runs'][0]['aliases'] == [target_old], 'never export another source/account namespace'
        source = db.query(models.Run).filter_by(user_id=1).one()
        runs.update_run(db, 1, source.id, schemas.RunUpdate(km=7))
        source_second = recover(1)
        newer = export(1)
        assert set(newer['runs'][0]['aliases']) == {source_old, source_second}
        summary = apply(newer, 'portable-second-recovery')
        assert summary['new_runs'] == 0 and summary['updated_runs'] == 1
        assert db.query(models.Run).filter_by(user_id=2).one().km == 7
        assert db.query(models.Shoe).filter_by(user_id=2).one().mileage == 7
        unchanged = apply(newer, 'portable-repeat-import')
        assert unchanged['updated_shoes'] == unchanged['updated_runs'] == unchanged['updated_months'] == 0
        local = db.query(models.Run).filter_by(user_id=2).one()
        runs.delete_run(db, 2, local.id)
        deleted = apply(newer, 'portable-preserve-target-deletion')
        assert deleted['new_runs'] == 0 and deleted['preserved_deleted_runs'] == 1
        assert db.query(models.Run).filter_by(user_id=2).count() == 0


@pytest.mark.parametrize('problem', ['duplicate', 'self', 'other', 'negative', 'string', 'legacy', 'budget'])
def test_portable_alias_contract_rejects_ambiguous_graphs(workspace, monkeypatch, problem):
    from backend import backup_contract
    with workspace.sessions() as db:
        payload = archive(db)
    run = payload['runs'][0]
    run['aliases'] = [99, 99] if problem == 'duplicate' else [run['id']] if problem == 'self' else [99]
    if problem == 'other':
        payload['runs'].append({**run, 'id': 99, 'aliases': []})
    elif problem == 'negative':
        run['aliases'] = [-1]
    elif problem == 'string':
        run['aliases'] = ['99']
    elif problem == 'legacy':
        payload['version'] = 2
    elif problem == 'budget':
        monkeypatch.setattr(backup_contract, 'MAX_RUN_ALIASES', 1)
        run['aliases'] = [98, 99]
    with pytest.raises(Invalid):
        parse_backup(json.dumps(payload).encode())


def test_portable_alias_conflicts_reject_without_merging_local_rows(workspace):
    with workspace.sessions() as db:
        payload = archive(db)
        preview = account_restore.preview_restore(db, 2, json.dumps(payload).encode(), workspace.config)
        account_restore.apply_restore(db, 2, preview['token'], 'portable-conflict-initial', workspace.config)
        own_shoe = db.query(models.Shoe).filter_by(user_id=2).one()
        other_run = add_run(db, own_shoe.id, uid=2)
        old_id = payload['runs'][0]['id']
        payload['runs'][0].update(id=999, aliases=[old_id])
        db.add(models.RestoreMapping(user_id=2, source_id=payload['source_id'], entity='run', source_key='999', target_id=other_run.id))
        db.commit()
        before = db.query(models.AuditEvent).filter_by(user_id=2).count()
        for mode in ('merge', 'update'):
            with pytest.raises(Conflict, match='別名'):
                account_restore.preview_restore(db, 2, json.dumps(payload).encode(), workspace.config, mode)
        assert db.query(models.Run).filter_by(user_id=2).count() == 2
        assert db.query(models.AuditEvent).filter_by(user_id=2).count() == before


def test_portable_alias_export_capacity_and_legacy_readers(workspace, monkeypatch):
    from backend.services import history, runs
    with workspace.sessions() as db:
        payload = archive(db)
        for version in (1, 2):
            legacy = {**payload, 'version': version}
            for row in legacy['runs']:
                row.pop('aliases', None)
            assert parse_backup(json.dumps(legacy).encode()).version == version
        for _cycle in range(2):
            row = db.query(models.Run).filter_by(user_id=1).one()
            runs.delete_run(db, 1, row.id)
            event = db.query(models.AuditEvent).filter_by(user_id=1, entity='runs', action='delete', imported=False, restored=False).one()
            history.restore_deleted(db, 1, event.id, workspace.config)
        monkeypatch.setattr(exports, 'MAX_RUN_ALIASES', 1)
        with pytest.raises(Invalid, match='別名'):
            exports.build_account_export(db, db.get(models.User, 1), include_history=False)
        assert exports.build_account_export(db, db.get(models.User, 2))[0]['runs'] == []


def test_fractional_import_ignores_legacy_noise_and_preserves_real_changes(workspace):
    with workspace.sessions() as db:
        shoe = add_shoe(db)
        add_run(db, shoe.id, km=0.1)
        add_run(db, shoe.id, km=0.2)
        db.expire_all()
        shoe = db.query(models.Shoe).filter_by(user_id=1).one()
        month = db.query(models.MonthlyMileage).filter_by(user_id=1).one()
        assert shoe.mileage == month.km == 0.3
        # Simulate legacy accumulated Float storage without a production migration.
        shoe.mileage = month.km = 0.30000000000000004
        db.commit()
        versions = shoe.version, month.version
        before = db.query(models.AuditEvent).filter_by(user_id=1).count()
        payload = exports.build_account_export(db, db.get(models.User, 1))[0]
        preview = account_restore.preview_restore(db, 1, json.dumps(payload).encode(), workspace.config, 'update')
        assert preview['summary']['updated_shoes'] == preview['summary']['updated_months'] == 0
        account_restore.apply_restore(db, 1, preview['token'], 'fractional-identical-import', workspace.config)
        db.expire_all()
        assert (shoe.version, month.version) == versions
        assert db.query(models.AuditEvent).filter_by(user_id=1).count() == before
        payload['runs'][0]['km'] = 0.11
        payload['shoes'][0]['mileage'] = payload['monthly_mileages'][0]['km'] = 0.31
        preview = account_restore.preview_restore(db, 1, json.dumps(payload).encode(), workspace.config, 'update')
        assert preview['summary']['updated_shoes'] == preview['summary']['updated_runs'] == preview['summary']['updated_months'] == 1
        account_restore.apply_restore(db, 1, preview['token'], 'fractional-real-change-import', workspace.config)
        db.expire_all()
        assert shoe.mileage == month.km == 0.31
        assert (shoe.version, month.version) == (versions[0] + 1, versions[1] + 1)


@pytest.mark.parametrize('version', [1, 2])
def test_legacy_archive_fingerprint_excludes_v3_defaults(workspace, version):
    from backend.backup_contract import backup_fingerprint
    from backend.services.fingerprints import payload_hash
    with workspace.sessions() as db:
        payload = archive(db)
    payload['version'] = version
    if version == 1:
        payload.pop('source_id')
    for row in payload['runs']:
        row.pop('aliases', None)
        row.pop('duration_seconds', None)
        row.pop('activity_type', None)
    parsed = parse_backup(json.dumps(payload).encode())
    original = parsed.model_dump(mode='json')
    # SPEC-126: archives before v6 hash as before, without the target race field.
    original.pop('race_goal')
    for row in original['runs']:
        row.pop('aliases')
        row.pop('duration_seconds')
        row.pop('activity_type')
    assert backup_fingerprint(parsed) == payload_hash(original)


def test_imported_history_never_evicts_local_recoverable_events(workspace, monkeypatch):
    """v4.7.1: local and imported audit events have separate retention caps."""
    from backend.services import history, retention, runs
    monkeypatch.setattr(retention.prune_account_history, "__kwdefaults__", {
        "audit_events": 50, "imported_audit_events": 3, "receipts": 1_000, "tombstones": 50_000,
    })
    with workspace.sessions() as db:
        payload = archive(db)
        assert len(payload["history"]) > 3
        shoe = add_shoe(db, uid=2)
        run = add_run(db, shoe.id, uid=2)
        runs.delete_run(db, 2, run.id, run.version)
        local_before = db.query(models.AuditEvent).filter_by(user_id=2, imported=False).count()
        preview = account_restore.preview_restore(db, 2, json.dumps(payload).encode(), workspace.config)
        account_restore.apply_restore(db, 2, preview['token'], 'retention-import-0001', workspace.config)
        rows = history.list_history(db, 2, limit=100)['rows']
        assert sum(row['imported'] for row in rows) == 3
        assert db.query(models.AuditEvent).filter_by(user_id=2, imported=False).count() >= local_before
        assert any(row['can_restore'] and row['entity'] == 'runs' for row in rows)


def test_startup_discards_every_accounts_expired_previews_only(workspace, tmp_path):
    """v4.7.1: abandoned previews (up to 64 MiB each account) no longer wait for that account."""
    from datetime import UTC, datetime, timedelta

    from fastapi.testclient import TestClient

    from backend.app_factory import create_app
    now = datetime.now(UTC)
    with workspace.sessions() as db:
        for user_id, token, expires_at in ((1, 'a' * 36, now - timedelta(minutes=1)),
                                           (2, 'b' * 36, now - timedelta(days=3)),
                                           (2, 'c' * 36, now + timedelta(minutes=10))):
            db.add(models.RestorePreview(user_id=user_id, token=token, revision=0, payload_hash='x',
                                         payload_json={}, expires_at=expires_at))
        db.commit()
    app = create_app(workspace.config, db_engine=workspace.engine, session_factory=workspace.sessions,
                     frontend_dir=tmp_path)
    with TestClient(app):
        pass
    with workspace.sessions() as db:
        assert [(row.user_id, row.token) for row in db.query(models.RestorePreview)] == [(2, 'c' * 36)]


def _bearer(workspace, name):
    from unit_tests.token_helpers import token_for_name
    return {'Authorization': 'Bearer ' + token_for_name(workspace.sessions, name, secret_key=workspace.config.secret_key or None)}


def test_archive_limits_follow_account_quotas_and_fit_a_full_real_account(workspace):
    """v4.7.3: lower limits still accept the largest account the app itself can hold."""
    from backend.backup_contract import ARCHIVE_LIMITS
    from backend.services.retention import AUDIT_EVENTS_PER_USER, IMPORTED_AUDIT_EVENTS_PER_USER
    from backend.settings import Settings
    assert ARCHIVE_LIMITS['history'] == AUDIT_EVENTS_PER_USER + IMPORTED_AUDIT_EVENTS_PER_USER
    assert ARCHIVE_LIMITS['runs'] >= Settings.from_env({}).max_runs_per_user
    with pytest.raises(Invalid, match='10 MB'):
        parse_backup(b' ' * (MAX_BACKUP_BYTES + 1))
    with workspace.sessions() as db:
        shoe = add_shoe(db, nickname='日常訓練鞋', size='US 9.5', price=3990, orig_price=4980,
                        categories=['Daily', 'Tempo'])
        for _ in range(3):
            add_run(db, shoe.id, km=10.37)
        archive_payload = exports.build_account_export(db, db.get(models.User, 1))[0]
    # Real exported row shapes scaled to the account quotas: MAX_RUNS_PER_USER runs, every
    # retained audit event (each logged run writes run, shoe and month events) and ten
    # years of monthly reports.
    shoes, runs_per_shoe, km = 500, 10, 10.37
    archive_payload['shoes'] = [{**archive_payload['shoes'][0], 'id': i, 'mileage': round(runs_per_shoe * km, 2),
                                 'baseline_mileage': 0} for i in range(1, shoes + 1)]
    archive_payload['runs'] = [{**archive_payload['runs'][0], 'id': i, 'shoe_id': 1 + i % shoes, 'km': km,
                                'strava_id': str(10**10 + i)} for i in range(1, shoes * runs_per_shoe + 1)]
    run_date = archive_payload['runs'][0]['date']
    archive_payload['monthly_mileages'] = [{'year': int(run_date[:4]), 'month': int(run_date[5:7]),
                                            'km': round(shoes * runs_per_shoe * km, 2), 'adjustment_km': 0}]
    templates = archive_payload['history']
    archive_payload['history'] = [{**templates[i % len(templates)], 'id': i}
                                  for i in range(1, ARCHIVE_LIMITS['history'] + 1)]
    archive_payload['monthly_reports'] = [
        {'year': 2016 + i // 12, 'month': i % 12 + 1, 'content_md': '本月跑量穩定成長。' * 330,
         'model': 'openrouter/synthetic', 'stats_json': {'month_km': 120.5, 'runs': 12},
         'created_at': None, 'updated_at': None} for i in range(120)]
    raw = json.dumps(archive_payload, ensure_ascii=False, separators=(',', ':')).encode()
    assert len(raw) <= MAX_BACKUP_BYTES
    parsed = parse_backup(raw)
    assert len(parsed.runs) == shoes * runs_per_shoe and len(parsed.history) == ARCHIVE_LIMITS['history']


def test_restore_preview_is_rate_limited_per_account_and_globally(workspace, tmp_path):
    """v4.7.3: uploads are parsed a bounded number of times; rejections store nothing."""
    from fastapi.testclient import TestClient

    from backend.app_factory import create_app
    with workspace.sessions() as db:
        raw = json.dumps(archive(db)).encode()
    config = replace(workspace.config, restore_preview_rate_limit_per_minute=2,
                     restore_preview_global_rate_limit_per_minute=3)
    app = create_app(config, db_engine=workspace.engine, session_factory=workspace.sessions, frontend_dir=tmp_path)
    with TestClient(app) as client:
        def preview(name):
            return client.post('/api/account-restore/preview', content=raw, headers=_bearer(workspace, name))
        assert [preview('two').status_code for _ in range(2)] == [200, 200]
        account_limited = preview('two')
        assert account_limited.status_code == 429 and 'Retry-After' in account_limited.headers
        assert account_limited.json()['detail'] == '備份預覽過於頻繁，請稍後再試。'
        assert preview('one').status_code == 200
        site_limited = preview('one')
        assert site_limited.status_code == 429
        assert site_limited.json()['detail'] == '備份還原服務目前忙碌，請稍後再試。'
    with workspace.sessions() as db:
        assert db.query(models.RestorePreview).filter_by(user_id=2).count() == 2
        assert db.query(models.RestorePreview).filter_by(user_id=1).count() == 1


def test_backup_preview_and_restore_run_one_at_a_time_per_process(workspace, tmp_path):
    """v4.7.3: a second heavy restore request is refused at once without parsing or counting."""
    from fastapi.testclient import TestClient

    from backend.app_factory import create_app
    with workspace.sessions() as db:
        raw = json.dumps(archive(db)).encode()
        token = account_restore.preview_restore(db, 2, raw, workspace.config)['token']
    config = replace(workspace.config, restore_preview_rate_limit_per_minute=1)
    app = create_app(config, db_engine=workspace.engine, session_factory=workspace.sessions, frontend_dir=tmp_path)
    headers = _bearer(workspace, 'two')
    apply_headers = {**headers, 'Idempotency-Key': 'restore-slot-apply-0001'}
    with TestClient(app) as client:
        assert app.state.restore_slot.acquire(blocking=False)
        try:
            busy = client.post('/api/account-restore/preview', content=raw, headers=headers)
            assert busy.status_code == 429 and busy.headers['Retry-After'] == '5'
            assert busy.json()['detail'] == '另一個備份還原正在處理，請稍後再試。'
            assert client.post('/api/account-restore/apply', json={'token': token},
                               headers=apply_headers).status_code == 429
        finally:
            app.state.restore_slot.release()
        with workspace.sessions() as db:
            assert db.query(models.RestorePreview).filter_by(user_id=2).count() == 1
            assert db.query(models.MutationReceipt).filter_by(user_id=2).count() == 0
        # The refused preview did not spend this account's one-per-minute budget.
        assert client.post('/api/account-restore/preview', content=raw, headers=headers).status_code == 200
        assert client.post('/api/account-restore/apply', json={'token': token},
                           headers=apply_headers).status_code == 200
    assert app.state.restore_slot.acquire(blocking=False)
    app.state.restore_slot.release()


def test_preview_stores_the_validated_archive_without_a_second_python_copy(workspace, monkeypatch):
    """v4.7.3: the stored payload is unchanged though models are serialized straight to JSON."""
    from backend.backup_contract import AccountBackup
    with workspace.sessions() as db:
        add_shoe(db, nickname='中文鞋款', price=1234.5)
        payload = archive(db)
        payload['monthly_reports'] = [{
            'year': 2026, 'month': 1, 'content_md': '月報 **重點**', 'model': 'mock',
            'stats_json': {'month_km': 10.37, 'nested': {'ratio': 0.1, 'values': [1, 2.5]}},
            'created_at': '2026-02-01T08:30:00+08:00', 'updated_at': None,
        }]
        raw = json.dumps(payload, ensure_ascii=False).encode()
        expected = {'mode': 'merge', 'backup': parse_backup(raw).model_dump(mode='json')}

        def second_copy(*_args, **_kwargs):
            raise AssertionError('preview must not build a second Python copy of the archive')
        monkeypatch.setattr(AccountBackup, 'model_dump', second_copy)
        preview = account_restore.preview_restore(db, 2, raw, workspace.config)
        stored = db.query(models.RestorePreview).filter_by(user_id=2, token=preview['token']).one()
        assert stored.payload_json == expected
        monkeypatch.undo()
        result = account_restore.apply_restore(db, 2, preview['token'], 'restore-json-copy-0001', workspace.config)
        assert result['summary']['new_shoes'] == 2 and result['summary']['new_reports'] == 1


def test_default_preview_limit_allows_a_normal_restore_session(workspace, tmp_path):
    """v4.7.3: every file or mode change previews again; ordinary use stays under the default."""
    from fastapi.testclient import TestClient

    from backend.app_factory import create_app
    with workspace.sessions() as db:
        raw = json.dumps(archive(db)).encode()
    app = create_app(workspace.config, db_engine=workspace.engine, session_factory=workspace.sessions,
                     frontend_dir=tmp_path)
    headers = _bearer(workspace, 'two')
    with TestClient(app) as client:
        previous = None
        # Pick a file, switch modes back and forth and re-pick files, like the panel does;
        # each superseded preview is discarded as the browser does.
        for mode in ['merge', 'update', 'update', 'merge', 'update', 'update', 'merge', 'update', 'merge', 'update']:
            response = client.post(f'/api/account-restore/preview?mode={mode}', content=raw, headers=headers)
            assert response.status_code == 200, response.json()
            if previous:
                assert client.delete('/api/account-restore/preview/' + previous, headers=headers).status_code == 200
            previous = response.json()['token']


def test_backup_v5_round_trips_activity_type(workspace):
    """SPEC-096 AC-6: v5 keeps run types; older archives restore as road and never relabel a stored run."""
    from backend import schemas
    from backend.services import runs

    with workspace.sessions() as db:
        shoe = add_shoe(db, mileage=0)
        for day, km, kind in (("2026-03-01", 10, "road"), ("2026-03-08", 12, "trail"), ("2026-03-15", 8, "hike")):
            runs.create_run(db, 1, schemas.RunCreate(shoe_id=shoe.id, date=day, km=km, activity_type=kind),
                            max_runs=5000)
        payload = exports.build_account_export(db, db.get(models.User, 1))[0]
        assert payload["version"] == 6
        assert [run["activity_type"] for run in payload["runs"]] == ["road", "trail", "hike"]
        assert payload["monthly_mileages"] == [{"year": 2026, "month": 3, "km": 22, "adjustment_km": 0}]

        preview = account_restore.preview_restore(db, 2, json.dumps(payload).encode(), workspace.config)
        account_restore.apply_restore(db, 2, preview["token"], "activity-v5-import", workspace.config)
        db.expire_all()
        restored = db.query(models.Run).filter_by(user_id=2).order_by(models.Run.date).all()
        assert [run.activity_type for run in restored] == ["road", "trail", "hike"]
        assert db.query(models.Shoe).filter_by(user_id=2).one().mileage == 30
        assert db.query(models.MonthlyMileage).filter_by(user_id=2).one().km == 22

        legacy = {**payload, "version": 4, "runs": [{key: value for key, value in run.items() if key != "activity_type"}
                                                    for run in payload["runs"]],
                  "monthly_mileages": [{"year": 2026, "month": 3, "km": 30, "adjustment_km": 0}]}
        assert {run.activity_type for run in parse_backup(json.dumps(legacy).encode()).runs} == {"road"}
        with pytest.raises(Invalid):
            parse_backup(json.dumps({**payload, "version": 4}).encode())
        # Merging an old archive into the account that already labels the runs keeps the labels.
        merge = account_restore.preview_restore(db, 2, json.dumps(legacy).encode(), workspace.config, "update")
        assert merge["summary"]["updated_runs"] == 0


RACE = {"race_name": "示範半馬", "race_date": "2027-03-07", "distance_km": 21.0975, "target_seconds": 7200,
        "reference_distance_km": 10.0, "reference_seconds": 3000, "reference_temperature_c": 18.0, "plan_weeks": 10}


def test_backup_v6_round_trips_the_race_goal(workspace):
    """SPEC-126 AC-1/AC-2: the target race is exported, merged only when missing and updated only in update mode."""
    from datetime import date

    from backend import schemas
    from backend.services import race_goals

    def restore(db, payload, mode, key):
        preview = account_restore.preview_restore(db, 2, json.dumps(payload).encode(), workspace.config, mode)
        account_restore.apply_restore(db, 2, preview["token"], key, workspace.config)
        db.expire_all()
        return preview["summary"]

    def stored(db):
        row = db.query(models.RaceGoal).filter_by(user_id=2).one()
        return {name: getattr(row, name) for name in RACE}, row.version

    with workspace.sessions() as db:
        race_goals.save_race_goal(db, 1, schemas.RaceGoalUpdate(**RACE), date(2026, 11, 25))
        payload = archive(db)
        assert payload["version"] == 6 and payload["race_goal"] == RACE

        summary = restore(db, payload, "merge", "race-merge-new")
        assert (summary["new_race_goal"], summary["updated_race_goal"]) == (True, False)
        assert stored(db) == (RACE, 1)

        # A merge keeps the receiving account's own race goal.
        race_goals.save_race_goal(db, 2, schemas.RaceGoalUpdate(**{**RACE, "target_seconds": 6900}), date(2026, 11, 25))
        summary = restore(db, payload, "merge", "race-merge-kept")
        assert summary["new_race_goal"] is False
        assert stored(db) == ({**RACE, "target_seconds": 6900}, 2)

        # An update overwrites it from the archive, then reports it unchanged.
        summary = restore(db, payload, "update", "race-update")
        assert (summary["updated_race_goal"], summary["unchanged_race_goal"]) == (True, False)
        assert stored(db) == (RACE, 3)
        summary = restore(db, payload, "update", "race-update-again")
        assert (summary["updated_race_goal"], summary["unchanged_race_goal"]) == (False, True)
        assert stored(db) == (RACE, 3)


def test_only_v6_archives_carry_a_valid_race_goal(workspace):
    """SPEC-126 AC-3: earlier versions stay valid without it, and the race goal is validated like the API."""
    with workspace.sessions() as db:
        payload = archive(db)
    older = {**{key: value for key, value in payload.items() if key != "race_goal"}, "version": 5}
    assert parse_backup(json.dumps(older).encode()).race_goal is None
    for bad in ({**payload, "version": 5, "race_goal": RACE},
                {**payload, "race_goal": {**RACE, "plan_weeks": 3}},
                {**payload, "race_goal": {**RACE, "target_seconds": 30}},
                {**payload, "race_goal": {**RACE, "expected_version": 4}},
                {**payload, "race_goal": {**RACE, "version": 2}}):
        with pytest.raises(Invalid):
            parse_backup(json.dumps(bad).encode())
    assert parse_backup(json.dumps({**payload, "race_goal": {**RACE, "plan_weeks": None}}).encode()).race_goal.plan_weeks is None
