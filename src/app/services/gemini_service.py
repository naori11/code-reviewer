import logging

from google import genai
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..core.config import Settings

logger = logging.getLogger(__name__)


PROMPT_INSTRUCTIONS = """You are an expert Senior Staff Software Engineer and Security Auditor. Your task is to perform a brutal, production-readiness code review of the provided Git diff.

Focus on:
1. Bugs: Logic errors, off-by-one, null handling, race conditions, async/sync blocking.
2. Security: Injection, auth bypass, data exposure, insecure defaults.
3. Performance: N+1 queries, blocking I/O, memory leaks, token/payload limits.
4. Maintainability: Monolithic design, magic strings, lack of logging, poor separation of concerns.
5. Edge Cases: Large payloads, missing env vars, API rate limits.

For every issue found, use this strict Markdown format:
- **Severity:** [Critical/High/Medium/Low]
- **Location:** [Line number or Function name in the diff, e.g., `main.py:123` or `function_name`]
- **Issue:** [Concise description]
- **Solution:** [Exact code fix or architectural change required]

Be concise, direct, and actionable. Do not include pleasantries or conversational filler. Start immediately with the findings or state \"No significant issues found.\" if applicable."""


class GeminiService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = genai.Client(api_key=settings.gemini_api_key)

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
        retry=retry_if_exception_type(Exception),
    )
    def generate_review(self, diff_content: str, model_name: str) -> tuple[str, int]:
        token_count = self.count_tokens(model_name=model_name, contents=diff_content)
        logger.info("Diff token count: %s", token_count)

        if token_count > self.settings.max_tokens:
            message = (
                f"ERROR: The code change is too large for automated review "
                f"(contains approximately {token_count} tokens, limit is {self.settings.max_tokens}). "
                "Please review manually."
            )
            return message, token_count

        full_prompt = f"{PROMPT_INSTRUCTIONS}\n\nCode Diff:\n{diff_content}"
        response = self.client.models.generate_content(model=model_name, contents=full_prompt)
        return response.text or "No significant issues found.", token_count

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
