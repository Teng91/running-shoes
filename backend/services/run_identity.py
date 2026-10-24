"""User-scoped source aliases across run deletion and explicit recovery.

The caller owns the transaction. Imported audit rows are display-only and cannot
establish a local deletion identity.
"""

from sqlalchemy.orm import Session

from backend import models


def add_local_tombstones(db: Session, user_id: int, mappings: dict[tuple[str, str], int]) -> None:
    deleted_ids = db.query(models.AuditEvent.entity_id).filter_by(
        user_id=user_id, entity="runs", action="delete", imported=False,
    ).distinct()
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
