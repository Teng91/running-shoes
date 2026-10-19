"""Account backup and shoe export HTTP adapters."""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from backend import models
from backend.auth import get_current_user
from backend.database import get_db
from backend.services import exports as export_service

router = APIRouter(tags=["exports"])


@router.get("/api/export/account")
def export_account_data(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    payload, filename = export_service.build_account_export(db, current_user)
    return JSONResponse(
        payload,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/api/export")
def export_shoes(
    format: str = Query("xlsx", pattern="^(csv|xlsx)$"),
    mode: str = Query("active", pattern="^(all|active|retired)$"),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        export_file = export_service.build_shoe_export(
            format, mode, current_user.id, db
        )
    except export_service.NoExportRowsError as exc:
        raise HTTPException(status_code=404, detail="沒有可匯出的跑鞋資料") from exc
    except export_service.ExportDependencyError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if export_file is None:
        return None
    return Response(
        content=export_file.content,
        media_type=export_file.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{export_file.filename}"'
        },
    )
