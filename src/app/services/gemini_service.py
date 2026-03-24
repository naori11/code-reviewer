import logging

from google import genai
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential
from tenacity.asyncio import AsyncRetrying

from ..core.config import Settings

logger = logging.getLogger(__name__)


class TokenLimitExceededError(Exception):
    def __init__(self, message: str, token_count: int):
        super().__init__(message)
        self.token_count = token_count


class GeminiServiceError(Exception):
    pass


class GeminiService:
    def __init__(self, settings: Settings, client: genai.Client | None = None):
        self.settings = settings
        self.client = client or genai.Client(api_key=settings.gemini_api_key)
        self.prompt_instructions = settings.ai_review_prompt

    async def count_tokens(self, model_name: str, contents: str) -> int:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=2, max=10),
            retry=retry_if_exception_type(Exception),
        ):
            with attempt:
                token_count_response = await self.client.aio.models.count_tokens(model=model_name, contents=contents)
                return token_count_response.total_tokens
        raise GeminiServiceError("Failed to count Gemini tokens after retries.")

    async def generate_review(self, diff_content: str, model_name: str) -> tuple[str, int]:
        try:
            token_count = await self.count_tokens(model_name=model_name, contents=diff_content)
            logger.info("Diff token count: %s", token_count)

            if token_count > self.settings.max_tokens:
                message = (
                    f"The code change is too large for automated review "
                    f"(contains approximately {token_count} tokens, limit is {self.settings.max_tokens}). "
                    "Please review manually."
                )
                raise TokenLimitExceededError(message, token_count)

            full_prompt = f"{self.prompt_instructions}\n\nCode Diff:\n{diff_content}"
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=1, min=2, max=10),
                retry=retry_if_exception_type(Exception),
            ):
                with attempt:
                    response = await self.client.aio.models.generate_content(model=model_name, contents=full_prompt)
                    return response.text or "No significant issues found.", token_count
            raise GeminiServiceError("Failed to generate Gemini review after retries.")
        except TokenLimitExceededError:
            raise
        except Exception as exc:
            logger.exception("Async Gemini API error: %s", exc)
            raise GeminiServiceError(f"Error calling Gemini API: {exc}") from exc

    async def list_models(self) -> list[dict]:
        models: list[dict] = []
        async for model in self.client.aio.models.list():
            name = getattr(model, "name", None) or "unknown"
            display_name = getattr(model, "display_name", None) or name
            methods = getattr(model, "supported_generation_methods", []) or getattr(model, "supported_methods", [])
            methods_lower = [m.lower() for m in methods]
            is_text_model = any(m in ["generatecontent", "generate_content"] for m in methods_lower)
            if not methods and any(family in name.lower() for family in ["gemini", "gemma"]):
                is_text_model = True

            if is_text_model:
                input_token_limit = getattr(model, "input_token_limit", None)
                description = getattr(model, "description", None) or "No description available"
                models.append(
                    {
                        "model_id": name,
                        "display_name": display_name,
                        "input_token_limit": input_token_limit if input_token_limit is not None else "Unknown",
                        "description": description,
                    }
                )

        models.sort(key=lambda x: x["display_name"])
        return models

    async def validate_model(self, model_name: str) -> None:
        await self.client.aio.models.get(model=model_name)
