from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AppConfig(SQLModel, table=True):
    id: Optional[int] = Field(default=1, primary_key=True)
    active_model: str
    updated_at: datetime = Field(default_factory=utc_now)


class ReviewHistory(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    repo_name: str = Field(index=True)
    pr_number: int = Field(index=True)
    model_used: str
    token_count: int = 0
    status: str
    created_at: datetime = Field(default_factory=utc_now, index=True)
