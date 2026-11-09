"""User-scoped source aliases across run deletion and explicit recovery.

The caller owns the transaction. Deletion tombstones live in their own table, so
audit history can be pruned without letting a restored backup resurrect a run.
"""

from sqlalchemy import String, cast
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from backend import models
from backend.services.errors import Invalid


def record_tombstone(db: Session, user_id: int, run_id: int) -> None:
    db.execute(
        sqlite_insert(models.RunTombstone)
        .values(user_id=user_id, run_id=run_id)
        .on_conflict_do_nothing(index_elements=["user_id", "run_id"])
    )


def add_local_tombstones(db: Session, user_id: int, mappings: dict[tuple[str, str], int]) -> None:
    deleted_ids = db.query(models.RunTombstone.run_id).filter_by(user_id=user_id)
    for (identifier,) in deleted_ids:
        mappings.setdefault(("run", str(identifier)), identifier)


def relink_recovered_run(db: Session, user_id: int, old_id: int, new_id: int) -> None:
    # Every external and previous local alias follows the explicitly recovered row.
    db.query(models.RestoreMapping).filter_by(user_id=user_id, entity="run", target_id=old_id).update(
        {models.RestoreMapping.target_id: new_id}, synchronize_session="fetch",
    )
    source = db.query(models.User.backup_id).filter_by(id=user_id).scalar()
    identity = (user_id, source, "run", str(old_id))
    alias = db.get(models.RestoreMapping, identity)
    if alias is None:
        db.add(models.RestoreMapping(user_id=user_id, source_id=source, entity="run", source_key=str(old_id), target_id=new_id))
    else:
        alias.target_id = new_id


def export_run_aliases(db: Session, user_id: int, source: str, limit: int) -> dict[int, list[int]]:
    """Export only this account's native lineage for runs still in the archive."""
    rows = db.query(models.RestoreMapping.target_id, models.RestoreMapping.source_key).join(
        models.Run, models.Run.id == models.RestoreMapping.target_id,
    ).filter(models.RestoreMapping.user_id == user_id, models.Run.user_id == user_id,
             models.RestoreMapping.source_id == source, models.RestoreMapping.entity == "run",
             models.RestoreMapping.source_key != cast(models.RestoreMapping.target_id, String)
    ).order_by(models.RestoreMapping.target_id, models.RestoreMapping.source_key).limit(limit + 1)
    result: dict[int, list[int]] = {}
    for count, (target, key) in enumerate(rows.yield_per(100)):
        if count == limit or not key.isascii() or not key.isdecimal() or int(key) <= 0:
            raise Invalid("跑步來源別名超過備份容量或格式不正確，請使用管理員完整資料庫備份")
        result.setdefault(target, []).append(int(key))
    return result
