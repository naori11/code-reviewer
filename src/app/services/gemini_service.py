import logging

from google import genai
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..core.config import Settings

logger = logging.getLogger(__name__)


class TokenLimitExceededError(Exception):
    def __init__(self, message: str, token_count: int):
        super().__init__(message)
        self.token_count = token_count


class GeminiServiceError(Exception):
    pass


class GeminiService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = genai.Client(api_key=settings.gemini_api_key)
        self.prompt_instructions = settings.ai_review_prompt

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
    )
    def count_tokens(self, model_name: str, contents: str) -> int:
        token_count_response = self.client.models.count_tokens(model=model_name, contents=contents)
        return token_count_response.total_tokens

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(GeminiServiceError),
    )
    def generate_review(self, diff_content: str, model_name: str) -> tuple[str, int]:
        try:
            token_count = self.count_tokens(model_name=model_name, contents=diff_content)
            logger.info("Diff token count: %s", token_count)

            if token_count > self.settings.max_tokens:
                message = (
                    f"The code change is too large for automated review "
                    f"(contains approximately {token_count} tokens, limit is {self.settings.max_tokens}). "
                    "Please review manually."
                )
                raise TokenLimitExceededError(message, token_count)

            full_prompt = f"{self.prompt_instructions}\n\nCode Diff:\n{diff_content}"
            response = self.client.models.generate_content(model=model_name, contents=full_prompt)
            return response.text or "No significant issues found.", token_count
        except TokenLimitExceededError:
            raise
        except Exception as exc:
            logger.exception("Error calling Gemini API: %s", exc)
            raise GeminiServiceError(f"Error calling Gemini API: {exc}") from exc

    def list_models(self) -> list[dict]:
        models: list[dict] = []
        for model in self.client.models.list():
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

    def validate_model(self, model_name: str) -> None:
        self.client.models.get(model=model_name)
