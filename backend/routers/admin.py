"""Site admin routes: registration invites and temporary passwords (SPEC-075).

Admins are the usernames in ``ADMIN_USERNAMES``; everyone else gets 403.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend import models, schemas
from backend.auth import get_current_user
from backend.dependencies import get_db
from backend.rate_limits import enforce_auth_rate_limit
from backend.routers.errors import service_errors
from backend.routers.password_notices import notify_password_changed
from backend.services import accounts, email_codes, invites

router = APIRouter(prefix="/api/admin", tags=["admin"])


def require_admin(request: Request, current_user: models.User = Depends(get_current_user)) -> models.User:
    if not request.app.state.settings.is_admin(current_user.username):
        raise HTTPException(status_code=403, detail="Admin only")
    return current_user


@router.get("/invites")
def list_invites(_admin: models.User = Depends(require_admin), db: Session = Depends(get_db)):
    return invites.list_invites(db)


@router.post("/invites")
def create_invite(payload: schemas.InviteCreate, _admin: models.User = Depends(require_admin),
                  db: Session = Depends(get_db)):
    with service_errors():
        return invites.create_invite(db, note=payload.note, max_uses=payload.max_uses, days=payload.days,
                                     code=payload.code)


@router.delete("/invites/{invite_id}")
def revoke_invite(invite_id: int, _admin: models.User = Depends(require_admin), db: Session = Depends(get_db)):
    with service_errors():
        return invites.revoke_invite(db, invite_id)


@router.post("/reset-password")
def reset_password(request: Request, payload: schemas.AdminPasswordReset, background: BackgroundTasks,
                   _admin: models.User = Depends(require_admin), db: Session = Depends(get_db)):
    """One-off temporary password for a user who forgot theirs; their sessions end."""
    enforce_auth_rate_limit(request)
    with service_errors():
        result = accounts.admin_reset_password(db, payload.username)
    notify_password_changed(request, background, db, payload.username, email_codes.CHANGED_BY_ADMIN)
    return result
