"""Account recovery, canonical writes and history HTTP adapters."""

from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from backend import models, schemas
from backend.auth import get_current_user
from backend.dependencies import get_db, get_settings
from backend.rate_limits import enforce_restore_preview_limits
from backend.routers.errors import service_errors
from backend.services import account_restore, history, operations
from backend.settings import Settings

router = APIRouter(prefix="/api", tags=["workspace"])

RESTORE_BUSY_DETAIL = "另一個備份還原正在處理，請稍後再試。"


@contextmanager
def restore_slot(request: Request) -> Iterator[None]:
    """Run one backup preview/restore per process; each holds several copies of the file.

    A busy slot is rejected at once instead of queued, so waiting requests never pile
    up threads or memory, and nothing is parsed or stored.
    """
    slot: Lock = request.app.state.restore_slot
    if not slot.acquire(blocking=False):
        raise HTTPException(429, detail=RESTORE_BUSY_DETAIL, headers={"Retry-After": "5"})
    try:
        yield
    finally:
        slot.release()


@router.post("/operations")
def mutate(
    command: schemas.MutationCommand, config: Settings = Depends(get_settings),
    user: models.User = Depends(get_current_user), db: Session = Depends(get_db),
):
    try:
        with service_errors():
            return operations.execute_operation(db, user.id, command, config)
    except ValidationError as exc:
        raise HTTPException(422, detail="操作內容格式不正確") from exc


@router.get("/history")
def get_history(
    before: Annotated[int | None, Query(gt=0)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    user: models.User = Depends(get_current_user), db: Session = Depends(get_db),
):
    return history.list_history(db, user.id, before=before, limit=limit)


@router.post("/account-restore/preview")
async def preview(
    request: Request, config: Settings = Depends(get_settings),
    user: models.User = Depends(get_current_user), db: Session = Depends(get_db),
    mode: account_restore.RestoreMode = "merge",
):
    with restore_slot(request):
        # Inside the slot, so a busy rejection does not spend the account's budget.
        await run_in_threadpool(enforce_restore_preview_limits, request, user.id)
        raw = await request.body()
        with service_errors():
            return await run_in_threadpool(account_restore.preview_restore, db, user.id, raw, config, mode)


class RestoreApply(BaseModel):
    token: str = Field(min_length=36, max_length=36)


@router.delete("/account-restore/preview/{token}")
def discard(
    token: str, user: models.User = Depends(get_current_user), db: Session = Depends(get_db),
):
    with service_errors():
        return account_restore.discard_preview(db, user.id, token)


@router.post("/account-restore/apply")
def apply(
    request: Request,
    payload: RestoreApply,
    operation_id: Annotated[str, Header(alias="Idempotency-Key", min_length=16, max_length=128,
                                       pattern=r"^[A-Za-z0-9._:-]+$")],
    config: Settings = Depends(get_settings), user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    with restore_slot(request), service_errors():
        return account_restore.apply_restore(db, user.id, payload.token, operation_id, config)
