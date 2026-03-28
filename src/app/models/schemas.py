from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


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


class ReviewPromptRequest(BaseModel):
    review_prompt: str | None = Field(default=None, max_length=50000)
    reset_to_default: bool = False


class ReviewPromptResponse(BaseModel):
    review_prompt: str
    prompt_version: int


class ReviewPromptUpdateResponse(BaseModel):
    status: str
    review_prompt: str
    prompt_version: int


class ReviewHistoryItem(BaseModel):
    id: UUID
    repo_name: str
    pr_number: int
    model_used: str
    token_count: int
    status: str
    prompt_version: int | None
    prompt_hash: str | None
    created_at: datetime


class ReviewHistoryResponse(BaseModel):
    status: str
    count: int
    history: list[ReviewHistoryItem]
