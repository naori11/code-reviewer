from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session

from src.app.api import admin
from src.app.models.entities import ReviewHistory


def test_prompt_history_groups_and_orders(mock_settings, db_engine):
    test_app = FastAPI()
    test_app.include_router(admin.router)
    test_app.state.gemini_client = object()

    def override_get_session():
        with Session(db_engine) as session:
            yield session

    test_app.dependency_overrides[admin.get_session] = override_get_session

    now = datetime.now(timezone.utc)
    with Session(db_engine) as session:
        session.add(
            ReviewHistory(
                repo_name="owner/repo",
                pr_number=1,
                model_used="m1",
                token_count=10,
                status="Success",
                prompt_version=1,
                prompt_hash="hashv1",
                created_at=now - timedelta(days=2),
            )
        )
        session.add(
            ReviewHistory(
                repo_name="owner/repo",
                pr_number=2,
                model_used="m1",
                token_count=11,
                status="Success",
                prompt_version=1,
                prompt_hash="hashv1",
                created_at=now - timedelta(days=1),
            )
        )
        session.add(
            ReviewHistory(
                repo_name="owner/repo",
                pr_number=3,
                model_used="m1",
                token_count=12,
                status="Success",
                prompt_version=2,
                prompt_hash="hashv2",
                created_at=now,
            )
        )
        session.commit()

    with TestClient(test_app) as client:
        response = client.get("/api/admin/history/prompts", headers={"X-Admin-Token": "test-admin-token"})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["count"] == 2

    newest = data["history"][0]
    assert newest["prompt_version"] == 2
    assert newest["prompt_hash"] == "hashv2"
    assert newest["review_count"] == 1

    older = data["history"][1]
    assert older["prompt_version"] == 1
    assert older["prompt_hash"] == "hashv1"
    assert older["review_count"] == 2
