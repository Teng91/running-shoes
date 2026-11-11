"""Account preview lifecycle, transaction ownership and replay receipts."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import Text, cast, func
from sqlalchemy.orm import Session

from backend import models
from backend.backup_contract import (
    MAX_BACKUP_BYTES,
    AccountBackup,
    backup_fingerprint,
    parse_backup,
)
from backend.services.account_import import execute_import
from backend.services.account_import_plan import RestoreMode, build_import_plan, summarize_import
from backend.services.errors import Conflict, Invalid
from backend.services.fingerprints import payload_hash
from backend.services.transactions import write_transaction
from backend.settings import Settings

MAX_ACTIVE_PREVIEWS = 8
# Stored previews are ASCII-escaped JSON, which can double Chinese text; three files'
# worth always leaves room for one full-size preview per account.
MAX_PREVIEW_BYTES = 3 * MAX_BACKUP_BYTES


def preview_restore(db: Session, user_id: int, raw: bytes, config: Settings, mode: RestoreMode = "merge") -> dict:
    backup = parse_backup(raw)
    if mode not in {"merge", "update"} or (mode == "update" and backup.version < 2):
        raise Invalid("更新匯入需要 v2/v3 帳號資料檔；舊版檔案請選擇只新增")
    with write_transaction(db, user_id, reason="account.preview"):
        plan = build_import_plan(db, user_id, backup, mode)
        summary = summarize_import(plan, backup, config, mode)
        # Serialize the validated models straight to JSON text and release them before
        # rebuilding the stored payload, so two full Python copies never coexist.
        archive_json = backup.model_dump_json()
        del plan, backup
        payload = {"mode": mode, "backup": json.loads(archive_json)}
        del archive_json
        revision = db.query(models.User.data_revision).filter_by(id=user_id).scalar()
        now = datetime.now(UTC)
        db.query(models.RestorePreview).filter(models.RestorePreview.user_id == user_id,
                                               models.RestorePreview.expires_at < now).delete(synchronize_session=False)
        token = str(uuid4())
        count, size = db.query(func.count(), func.coalesce(func.sum(func.length(cast(models.RestorePreview.payload_json, Text))), 0)).filter(models.RestorePreview.user_id == user_id).one()
        # ASCII-escaped JSON: its character count is its byte count.
        if count >= MAX_ACTIVE_PREVIEWS or size + len(json.dumps(payload, ensure_ascii=True)) > MAX_PREVIEW_BYTES:
            raise Conflict("有效預覽數量或容量已達上限，請關閉其他預覽或稍後再試")
        db.add(models.RestorePreview(user_id=user_id, token=token, revision=revision,
                                    payload_hash=payload_hash(payload), payload_json=payload,
                                    expires_at=now + timedelta(minutes=20)))
        return {"token": token, "summary": summary, "expires_in_seconds": 1200}


def apply_restore(db: Session, user_id: int, token: str, operation_id: str, config: Settings) -> dict:
    fingerprint = payload_hash({"kind": "account.restore", "token": token})
    with write_transaction(db, user_id, reason="account.restore", operation_id=operation_id):
        receipt = db.get(models.MutationReceipt, (user_id, operation_id))
        if receipt is not None:
            if receipt.payload_hash != fingerprint:
                raise Conflict("操作識別碼已用於不同內容")
            return receipt.response_json
        preview = db.query(models.RestorePreview).filter_by(user_id=user_id, token=token).first()
        revision = db.query(models.User.data_revision).filter_by(id=user_id).scalar()
        if preview is None or preview.expires_at.replace(tzinfo=UTC) < datetime.now(UTC):
            raise Conflict("還原預覽已過期，請重新預覽")
        if preview.revision != revision:
            raise Conflict("資料已在預覽後變更，請重新預覽")
        payload = preview.payload_json
        mode = payload.get("mode", "merge")
        backup = AccountBackup.model_validate(payload.get("backup", payload))
        fingerprint_matches = payload_hash(payload) == preview.payload_hash if "backup" in payload else backup_fingerprint(backup) == preview.payload_hash
        if not fingerprint_matches or mode not in {"merge", "update"} or (mode == "update" and backup.version < 2):
            raise Conflict("還原預覽內容已變更")
        plan = build_import_plan(db, user_id, backup, mode)
        summary = summarize_import(plan, backup, config, mode)
        execute_import(db, user_id, backup, config, plan, update_existing=mode == "update")
        response = {"ok": True, "summary": summary}
        db.add(models.MutationReceipt(user_id=user_id, operation_id=operation_id,
                                       payload_hash=fingerprint, response_json=response))
        db.delete(preview)
        return response


def discard_expired_previews(db: Session, now: datetime | None = None) -> int:
    """Startup maintenance: drop every account's expired temporary previews.

    A preview holds a full backup (up to 64 MiB per account) and an abandoned one
    was otherwise kept until that same account previewed again. Only expired
    temporary rows are removed; no account data is read or returned.
    """
    with write_transaction(db, reason="account.preview.expire"):
        return int(
            db.query(models.RestorePreview)
            .filter(models.RestorePreview.expires_at < (now or datetime.now(UTC)))
            .delete(synchronize_session=False)
        )


def discard_preview(db: Session, user_id: int, token: str) -> dict:
    with write_transaction(db, user_id, reason="account.preview.discard"):
        db.query(models.RestorePreview).filter_by(user_id=user_id, token=token).delete(synchronize_session=False)
    return {"ok": True}
