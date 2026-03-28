import asyncio
from types import SimpleNamespace

import pytest

from src.app.services.gemini_service import GeminiService, GeminiServiceError, TokenLimitExceededError


class _FakeCountTokensResponse:
    def __init__(self, total_tokens: int):
        self.total_tokens = total_tokens


class _FakeGenerateResponse:
    def __init__(self, text: str):
        self.text = text


class _FakeModels:
    def __init__(self, total_tokens: int = 12, structured_text: str = '{"summary":"Looks good","suggestions":[]}'):
        self.total_tokens = total_tokens
        self.structured_text = structured_text
        self.last_generate_contents: str | None = None

    async def count_tokens(self, model: str, contents: str):
        return _FakeCountTokensResponse(self.total_tokens)

    async def generate_content(self, model: str, contents: str, config=None):
        self.last_generate_contents = contents
        return _FakeGenerateResponse(self.structured_text)


class _FakeClient:
    def __init__(self, models: _FakeModels):
        self.aio = SimpleNamespace(models=models)


def _settings(max_tokens: int = 100_000):
    return SimpleNamespace(
        gemini_api_key="test-key",
        ai_review_prompt="Review thoroughly",
        max_tokens=max_tokens,
    )


def test_count_tokens_returns_total_tokens() -> None:
    models = _FakeModels(total_tokens=42)
    service = GeminiService(settings=_settings(), client=_FakeClient(models))

    token_count = asyncio.run(service.count_tokens(model_name="models/test", contents="diff text"))

    assert token_count == 42


def test_generate_review_success() -> None:
    models = _FakeModels(
        total_tokens=10,
        structured_text='{"summary":"No significant issues found.","suggestions":[]}',
    )
    service = GeminiService(settings=_settings(max_tokens=100), client=_FakeClient(models))

    review, token_count = asyncio.run(service.generate_review(diff_content="+print('ok')", model_name="models/test", prompt_instructions="Review thoroughly"))

    assert token_count == 10
    assert review == "No significant issues found."
    assert models.last_generate_contents is not None
    assert "Review thoroughly" in models.last_generate_contents
    assert "Code Diff:" in models.last_generate_contents
    assert "+print('ok')" in models.last_generate_contents


def test_generate_review_raises_on_token_limit() -> None:
    models = _FakeModels(total_tokens=500)
    service = GeminiService(settings=_settings(max_tokens=100), client=_FakeClient(models))

    with pytest.raises(TokenLimitExceededError) as exc_info:
        asyncio.run(
            service.generate_review(
                diff_content="huge diff",
                model_name="models/test",
                prompt_instructions="Review thoroughly",
            )
        )

    assert exc_info.value.token_count == 500
    assert "too large for automated review" in str(exc_info.value)


def test_generate_review_wraps_unexpected_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    models = _FakeModels(total_tokens=1)
    service = GeminiService(settings=_settings(), client=_FakeClient(models))

    async def _boom(*args, **kwargs):
        raise RuntimeError("counting failed")

    monkeypatch.setattr(service, "count_tokens", _boom)

    with pytest.raises(GeminiServiceError) as exc_info:
        asyncio.run(
            service.generate_review(
                diff_content="diff",
                model_name="models/test",
                prompt_instructions="Review thoroughly",
            )
        )

    assert "Error calling Gemini API" in str(exc_info.value)
