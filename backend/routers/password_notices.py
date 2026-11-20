"""Password-change notices shared by the account and admin routes (SPEC-090).

Routers never import each other; HTTP helpers both need live here, like `errors.py`.
"""

from fastapi import BackgroundTasks, Request
from sqlalchemy.orm import Session

from backend.clock import local_now
from backend.mailer import deliver_later
from backend.services import email_codes


def notify_password_changed(request: Request, background: BackgroundTasks, db: Session, identifier: str,
                            how: str) -> None:
    """SPEC-083: email the bound address after the response; mail problems never fail the change."""
    mailer = request.app.state.mailer
    if mailer is not None:
        email_codes.notify_password_changed(db, identifier, how, send=deliver_later(mailer, background.add_task),
                                            when=local_now())
