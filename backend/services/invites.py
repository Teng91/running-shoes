"""Registration invites (SPEC-075).

Only a SHA-256 of each invite code is stored; the plain code is returned once, when created.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from backend import models
from backend.services.errors import Invalid, NotFound
from backend.services.transactions import write_transaction

# No 0/O or 1/I/L: codes are read aloud and typed on phones.
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
CODE_LENGTH = 8
MAX_USES = 20
MAX_DAYS = 90
INVALID_INVITE = "Invalid invite code"


def normalize_code(code: str) -> str:
    return "".join(character for character in code.upper() if character.isalnum())


def code_hash(code: str) -> str:
    return hashlib.sha256(normalize_code(code).encode("utf-8")).hexdigest()


def _now() -> datetime:
    # Stored naive in UTC, like the other DateTime columns.
    return datetime.now(UTC).replace(tzinfo=None)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") + "Z" if value else None


def _out(invite: models.Invite, now: datetime) -> dict:
    return {
        "id": invite.id, "note": invite.note, "max_uses": invite.max_uses, "used_count": invite.used_count,
        "expires_at": _iso(invite.expires_at), "created_at": _iso(invite.created_at), "revoked": invite.revoked,
        "active": not invite.revoked and invite.used_count < invite.max_uses and invite.expires_at > now,
    }


def create_invite(db: Session, *, note: str, max_uses: int, days: int) -> dict:
    if not 1 <= max_uses <= MAX_USES:
        raise Invalid(f"max_uses must be between 1 and {MAX_USES}")
    if not 1 <= days <= MAX_DAYS:
        raise Invalid(f"days must be between 1 and {MAX_DAYS}")
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    now = _now()
    with write_transaction(db):
        invite = models.Invite(code_hash=code_hash(code), note=note.strip()[:60], max_uses=max_uses,
                               used_count=0, expires_at=now + timedelta(days=days), revoked=False, created_at=now)
        db.add(invite)
        db.flush()
        result = _out(invite, now)
    return {**result, "code": f"{code[:4]}-{code[4:]}"}


def list_invites(db: Session) -> list[dict]:
    now = _now()
    rows = db.query(models.Invite).order_by(models.Invite.id.desc()).limit(100).all()
    return [_out(invite, now) for invite in rows]


def revoke_invite(db: Session, invite_id: int) -> dict:
    with write_transaction(db):
        invite = db.query(models.Invite).filter(models.Invite.id == invite_id).first()
        if invite is None:
            raise NotFound("Invite not found")
        invite.revoked = True
        db.flush()
        result = _out(invite, _now())
    return result


def redeem_invite(db: Session, code: str) -> None:
    """Spend one use inside the caller's registration transaction; every problem is the same error."""
    if len(normalize_code(code)) != CODE_LENGTH:
        raise Invalid(INVALID_INVITE)
    changed = db.query(models.Invite).filter(
        models.Invite.code_hash == code_hash(code),
        models.Invite.revoked.is_(False),
        models.Invite.used_count < models.Invite.max_uses,
        models.Invite.expires_at > _now(),
    ).update({models.Invite.used_count: models.Invite.used_count + 1}, synchronize_session=False)
    if not changed:
        raise Invalid(INVALID_INVITE)
