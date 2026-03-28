from collections.abc import Generator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from src.app.core.config import get_settings
from src.app.models import entities  # noqa: F401


@pytest.fixture
def mock_settings(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    env = {
        "WEBHOOK_SECRET": "test-webhook-secret",
        "ADMIN_API_KEY": "test-admin-token",
        "GEMINI_API_KEY": "test-gemini-key",
        "GITHUB_TOKEN": "test-github-token",
        "GITHUB_APP_ID": "12345",
        "GITHUB_PRIVATE_KEY": "test-private-key",
        "DATABASE_URL": "sqlite://",
    }

    for key, value in env.items():
        monkeypatch.setenv(key, value)

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def db_engine(mock_settings: None):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)


@pytest.fixture
def db_session(db_engine) -> Generator[Session, None, None]:
    with Session(db_engine) as session:
        yield session


@pytest.fixture
def app(db_engine, mock_settings: None) -> Generator[FastAPI, None, None]:
    from src.app.api import webhooks

    test_app = FastAPI()
    test_app.include_router(webhooks.router)
    test_app.state.http_client = object()
    test_app.state.gemini_client = object()

    def override_get_session() -> Generator[Session, None, None]:
        with Session(db_engine) as session:
            yield session

    original_engine = webhooks.engine
    webhooks.engine = db_engine
    test_app.dependency_overrides[webhooks.get_session] = override_get_session
    yield test_app
    webhooks.engine = original_engine
    test_app.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client
