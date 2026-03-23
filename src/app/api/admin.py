from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, desc, select

from ..core.config import Settings, get_settings
from ..core.database import get_session
from ..core.security import verify_admin_token
from ..crud.app_config import get_app_config_singleton, set_active_model_singleton
from ..models.entities import ReviewHistory
from ..models.schemas import (
    ActiveModelRequest,
    ActiveModelResponse,
    ActiveModelUpdateResponse,
    ModelsResponse,
    ReviewHistoryItem,
    ReviewHistoryResponse,
)
from ..services.gemini_service import GeminiService

router = APIRouter(prefix="/api/admin", tags=["admin"])


def get_gemini_service(settings: Settings = Depends(get_settings)) -> GeminiService:
    return GeminiService(settings)


@router.get("/models", response_model=ModelsResponse)
async def list_models(
    _: str = Depends(verify_admin_token),
    gemini_service: GeminiService = Depends(get_gemini_service),
):
    try:
        models = gemini_service.list_models()
        return ModelsResponse(status="success", count=len(models), models=models)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to list models: {exc}") from exc


@router.get("/config/active-model", response_model=ActiveModelResponse)
async def get_active_model(
    _: str = Depends(verify_admin_token),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    app_config = get_app_config_singleton(session)
    active_model = app_config.active_model if app_config else settings.ai_model_name
    return ActiveModelResponse(active_model=active_model)


@router.post("/config/active-model", response_model=ActiveModelUpdateResponse)
async def set_active_model(
    payload: ActiveModelRequest,
    _: str = Depends(verify_admin_token),
    session: Session = Depends(get_session),
    gemini_service: GeminiService = Depends(get_gemini_service),
):
    try:
        gemini_service.validate_model(payload.model_name)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid or inaccessible model: {payload.model_name}") from exc

    set_active_model_singleton(session, payload.model_name)
    return ActiveModelUpdateResponse(status="success", active_model=payload.model_name)


@router.get("/history", response_model=ReviewHistoryResponse)
async def review_history(
    _: str = Depends(verify_admin_token),
    session: Session = Depends(get_session),
):
    rows = session.exec(select(ReviewHistory).order_by(desc(ReviewHistory.created_at))).all()
    history = [
        ReviewHistoryItem(
            id=row.id,
            repo_name=row.repo_name,
            pr_number=row.pr_number,
            model_used=row.model_used,
            token_count=row.token_count,
            status=row.status,
            created_at=row.created_at,
        )
        for row in rows
    ]
    return ReviewHistoryResponse(status="success", count=len(history), history=history)
