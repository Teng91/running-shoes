"""LLM provider and chat HTTP endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend import agent as agent_service
from backend import llm, models, schemas
from backend.auth import get_current_user
from backend.database import get_db
from backend.rate_limits import enforce_agent_request_limits, enforce_model_refresh_limits

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.get("/providers")
def list_agent_providers(current_user: models.User = Depends(get_current_user)):
    return llm.list_providers()


@router.post("/models/refresh")
def refresh_agent_models(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    enforce_model_refresh_limits(current_user.id, db)
    return llm.list_providers(force=True)


@router.post("/chat/stream")
def agent_chat_stream(
    request: Request,
    payload: schemas.AgentChatRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    enforce_agent_request_limits(request, current_user.id, db)
    try:
        provider = llm.LLMProvider.from_str(payload.provider)
        model = llm.resolve_allowed_model(provider, payload.model)
    except llm.LLMError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StreamingResponse(
        agent_service.run_agent_stream(
            user_message=payload.user_message,
            history=[turn.model_dump() for turn in payload.history],
            provider=provider.value,
            model=model,
            db=db,
            user_id=current_user.id,
        ),
        media_type="text/event-stream",
    )
