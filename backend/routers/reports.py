"""Monthly AI report HTTP endpoints."""


from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend import llm, models, schemas
from backend import reports as report_statistics
from backend.auth import get_current_user
from backend.clock import local_today
from backend.dependencies import get_db
from backend.rate_limits import enforce_agent_request_limits
from backend.report_llm import stream_report_text
from backend.report_protocol import report_sse
from backend.services.reports import generate_report

router = APIRouter(prefix="/api/reports", tags=["reports"])

@router.post("/generate")
def generate_monthly_report(
    request: Request,
    payload: schemas.ReportGenerateRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    enforce_agent_request_limits(request, current_user.id)
    today = local_today()
    if (payload.year, payload.month) > (today.year, today.month):
        raise HTTPException(status_code=422, detail="未來月份無法產生報告")
    try:
        model = llm.resolve_allowed_model(llm.LLMProvider.openrouter, payload.model)
    except llm.LLMError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    user_id = current_user.id
    return StreamingResponse(
        report_sse(generate_report(
            db, user_id, payload.year, payload.month, model,
            build_stats=lambda: report_statistics.build_report_stats(
                db, user_id, payload.year, payload.month, today=today
            ),
            stream_text=lambda stats: stream_report_text(model, stats),
        )),
        media_type="text/event-stream",
    )


@router.get("")
def list_monthly_reports(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.query(models.MonthlyReport).filter(
        models.MonthlyReport.user_id == current_user.id
    ).order_by(models.MonthlyReport.year.desc(), models.MonthlyReport.month.desc()).all()
    return [
        {
            "id": row.id,
            "year": row.year,
            "month": row.month,
            "model": row.model,
            "updated_at": schemas.serialize_utc_timestamp(row.updated_at) if row.updated_at else None,
        }
        for row in rows
    ]


@router.get("/{year}/{month}")
def get_monthly_report(
    year: int,
    month: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(models.MonthlyReport).filter(
        models.MonthlyReport.user_id == current_user.id,
        models.MonthlyReport.year == year,
        models.MonthlyReport.month == month,
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="查無此月份的報告")
    return {
        "id": row.id,
        "year": row.year,
        "month": row.month,
        "model": row.model,
        "content_md": row.content_md,
        "stats_json": row.stats_json,
        "created_at": schemas.serialize_utc_timestamp(row.created_at) if row.created_at else None,
        "updated_at": schemas.serialize_utc_timestamp(row.updated_at) if row.updated_at else None,
    }
