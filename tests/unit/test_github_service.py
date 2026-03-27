import asyncio
import json
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import httpx
import pytest
from tenacity import RetryError

from src.app.core.config import Settings
from src.app.services.github_service import GithubService, GithubServiceError


class _FakeResponse:
    def __init__(self, status_code: int, text: str = "", json_data=None):
        self.status_code = status_code
        self.text = text
        self._json_data = json_data

    def json(self):
        if self._json_data is None:
            raise json.JSONDecodeError("no-json", self.text, 0)  # noqa: F821
        return self._json_data


class _FakeHTTPClient:
    def __init__(self, response: _FakeResponse):
        self._response = response
        self.last_get: dict[str, dict[str, str] | str] | None = None

    async def get(self, url: str, headers: dict):
        self.last_get = {"url": url, "headers": headers}
        return self._response


class _CaptureGitHubAPI:
    def __init__(self, *args, **kwargs):
        self.calls = []

    async def post(self, path: str, data: dict):
        self.calls.append({"path": path, "data": data})


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        github_app_id="123",
        github_private_key="private-key",
        github_token="",
        app_name="Code Review Automator",
        ai_review_header="## Automated Code Review",
        ai_review_disclaimer="AI generated",
        github_comment_limit=200,
    )


def test_download_diff_success(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeHTTPClient(_FakeResponse(status_code=200, text="diff body"))
    service = GithubService(settings=cast(Settings, _settings()), http_client=cast(httpx.AsyncClient, client))

    async def _fake_token(*args, **kwargs):
        return {"token": "ghs_test"}

    monkeypatch.setattr("src.app.services.github_service.apps.get_installation_access_token", _fake_token)

    result = asyncio.run(service.download_diff(1, "owner/repo", 7))

    assert result == "diff body"
    assert client.last_get is not None
    assert client.last_get["url"] == "https://api.github.com/repos/owner/repo/pulls/7"


def test_download_diff_raises_service_error_on_non_200(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeHTTPClient(
        _FakeResponse(status_code=403, text='{"message":"forbidden"}', json_data={"message": "forbidden"})
    )
    service = GithubService(settings=cast(Settings, _settings()), http_client=cast(httpx.AsyncClient, client))

    async def _fake_token(*args, **kwargs):
        return {"token": "ghs_test"}

    monkeypatch.setattr("src.app.services.github_service.apps.get_installation_access_token", _fake_token)

    with pytest.raises(RetryError):
        asyncio.run(service.download_diff(1, "owner/repo", 7))


def test_post_github_comment_truncates_long_body(monkeypatch: pytest.MonkeyPatch) -> None:
    service = GithubService(settings=cast(Settings, _settings()), http_client=cast(httpx.AsyncClient, AsyncMock()))

    async def _fake_get_token(*args, **kwargs):
        return "ghs_test"

    capture_api = _CaptureGitHubAPI()

    monkeypatch.setattr(service, "_get_token", _fake_get_token)
    monkeypatch.setattr("src.app.services.github_service.GitHubAPI", lambda *args, **kwargs: capture_api)

    long_body = "x" * 10_000
    asyncio.run(
        service.post_github_comment(
            1,
            "owner/repo",
            99,
            long_body,
            "models/gemini-test",
        )
    )

    assert len(capture_api.calls) == 1
    call = capture_api.calls[0]
    assert call["path"] == "/repos/owner/repo/issues/99/comments"
    posted = call["data"]["body"]
    assert "[Review truncated due to GitHub character limit]" in posted


def test_post_github_comment_wraps_http_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    service = GithubService(settings=cast(Settings, _settings()), http_client=cast(httpx.AsyncClient, AsyncMock()))

    async def _fake_get_token(*args, **kwargs):
        return "ghs_test"

    class _TimeoutAPI:
        async def post(self, path: str, data: dict):
            raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(service, "_get_token", _fake_get_token)
    monkeypatch.setattr("src.app.services.github_service.GitHubAPI", lambda *args, **kwargs: _TimeoutAPI())

    with pytest.raises(RetryError):
        asyncio.run(
            service.post_github_comment(
                1,
                "owner/repo",
                99,
                "short",
                "models/gemini-test",
            )
        )
