import json
import logging
from typing import Any

from google import genai
from tenacity import retry_if_exception_type, stop_after_attempt, wait_exponential
from tenacity.asyncio import AsyncRetrying

from ..core.config import Settings

logger = logging.getLogger(__name__)

REQUIRED_REVIEW_PROMPT_PREFIX = """Review the provided Git diff and return ONLY valid JSON with no markdown fences and no extra text.

Output schema:
{
  \"summary\": \"High-level review summary\",
  \"suggestions\": [
    {
      \"path\": \"relative/file/path.py\",
      \"line\": 42,
      \"message\": \"Issue + concrete fix\",
      \"severity\": \"Critical|High|Medium|Low\"
    }
  ]
}"""


class TokenLimitExceededError(Exception):
    def __init__(self, message: str, token_count: int):
        super().__init__(message)
        self.token_count = token_count


class GeminiServiceError(Exception):
    pass


class StructuredReviewParseError(GeminiServiceError):
    pass


class GeminiService:
    VALID_SEVERITIES = {"critical": "Critical", "high": "High", "medium": "Medium", "low": "Low"}

    def __init__(self, settings: Settings, client: genai.Client | None = None):
        self.settings = settings
        self.client = client or genai.Client(api_key=settings.gemini_api_key)

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

    def _normalize_structured_review(self, raw_text: str) -> dict[str, Any]:
        if not raw_text or not raw_text.strip():
            raise StructuredReviewParseError("Gemini returned empty structured review output.")

        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise StructuredReviewParseError("Gemini structured review output is not valid JSON.") from exc

        if not isinstance(parsed, dict):
            raise StructuredReviewParseError("Gemini structured review output must be a JSON object.")

        summary = parsed.get("summary", "")
        suggestions = parsed.get("suggestions", [])

        if not isinstance(summary, str):
            raise StructuredReviewParseError("Gemini structured review output field 'summary' must be a string.")
        if not isinstance(suggestions, list):
            raise StructuredReviewParseError("Gemini structured review output field 'suggestions' must be an array.")

        normalized_suggestions: list[dict[str, Any]] = []
        for item in suggestions:
            if not isinstance(item, dict):
                continue

            path = item.get("path")
            line = item.get("line")
            message = item.get("message")
            severity = item.get("severity")

            if not isinstance(path, str) or not path.strip():
                continue
            if isinstance(line, str) and line.isdigit():
                line = int(line)
            if not isinstance(line, int) or line <= 0:
                continue
            if not isinstance(message, str) or not message.strip():
                continue

            severity_normalized = "Medium"
            if isinstance(severity, str):
                severity_normalized = self.VALID_SEVERITIES.get(severity.strip().lower(), "Medium")

            normalized_suggestions.append(
                {
                    "path": path.strip(),
                    "line": line,
                    "message": message.strip(),
                    "severity": severity_normalized,
                }
            )

        return {
            "summary": summary.strip() or "No significant issues found.",
            "suggestions": normalized_suggestions,
        }

    async def generate_structured_review(
        self,
        diff_content: str,
        model_name: str,
        prompt_instructions: str,
    ) -> tuple[dict[str, Any], int]:
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

            full_prompt = (
                f"{REQUIRED_REVIEW_PROMPT_PREFIX}\n\n"
                f"Additional review instructions:\n{prompt_instructions}\n\n"
                f"Code Diff:\n{diff_content}"
            )
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=1, min=2, max=10),
                retry=retry_if_exception_type(Exception),
            ):
                with attempt:
                    response = await self.client.aio.models.generate_content(
                        model=model_name,
                        contents=full_prompt,
                        config={"response_mime_type": "application/json"},
                    )
                    normalized = self._normalize_structured_review(response.text or "")
                    return normalized, token_count
            raise GeminiServiceError("Failed to generate Gemini structured review after retries.")
        except TokenLimitExceededError:
            raise
        except StructuredReviewParseError:
            raise
        except Exception as exc:
            logger.exception("Async Gemini API error: %s", exc)
            raise GeminiServiceError(f"Error calling Gemini API: {exc}") from exc

    async def generate_review(self, diff_content: str, model_name: str, prompt_instructions: str) -> tuple[str, int]:
        structured_review, token_count = await self.generate_structured_review(
            diff_content,
            model_name,
            prompt_instructions,
        )

        lines: list[str] = [structured_review.get("summary", "No significant issues found.")]
        suggestions = structured_review.get("suggestions", [])
        if suggestions:
            lines.append("")
            for suggestion in suggestions:
                lines.append(
                    f"- **Severity:** {suggestion['severity']}\n"
                    f"  **Location:** `{suggestion['path']}:{suggestion['line']}`\n"
                    f"  **Issue/Solution:** {suggestion['message']}"
                )

        return "\n".join(lines), token_count

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
