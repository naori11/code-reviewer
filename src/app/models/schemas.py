from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ModelInfo(BaseModel):
    model_id: str
    display_name: str
    input_token_limit: int | str
    description: str


class ModelsResponse(BaseModel):
    status: str
    count: int
    models: list[ModelInfo]


class ActiveModelRequest(BaseModel):
    model_name: str


class ActiveModelResponse(BaseModel):
    active_model: str


class ActiveModelUpdateResponse(BaseModel):
    status: str
    active_model: str


class ReviewHistoryItem(BaseModel):
    id: UUID
    repo_name: str
    pr_number: int
    model_used: str
    token_count: int
    status: str
    created_at: datetime


class ReviewHistoryResponse(BaseModel):
    status: str
    count: int
    history: list[ReviewHistoryItem]
