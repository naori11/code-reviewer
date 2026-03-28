import hashlib
import json
import logging
import re
from collections.abc import Iterable

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from sqlmodel import Session

from ..core.config import Settings, get_settings
from ..core.database import engine, get_session
from ..core.security import verify_webhook_signature
from ..crud.app_config import get_app_config_singleton, resolve_effective_review_prompt
from ..models.entities import ReviewHistory
from ..services.gemini_service import (
    GeminiService,
    GeminiServiceError,
    StructuredReviewParseError,
    TokenLimitExceededError,
)
from ..services.github_service import GithubService, GithubServiceError

logger = logging.getLogger(__name__)
router = APIRouter(tags=["webhooks"])


def get_github_service(request: Request, settings: Settings = Depends(get_settings)) -> GithubService:
    return GithubService(settings, http_client=request.app.state.http_client)


def get_gemini_service(request: Request, settings: Settings = Depends(get_settings)) -> GeminiService:
    return GeminiService(settings, client=request.app.state.gemini_client)


def _normalize_diff_path(path: str) -> str:
    return path.strip().replace("\\", "/").lstrip("./")


def _extract_diff_line_map(diff_content: str) -> dict[str, set[int]]:
    line_map: dict[str, set[int]] = {}
    current_path: str | None = None
    current_new_line: int | None = None

    for raw_line in diff_content.splitlines():
        if raw_line.startswith("diff --git "):
            current_path = None
            current_new_line = None
            continue

        if raw_line.startswith("+++ "):
            candidate = raw_line[4:].strip()
            if candidate == "/dev/null":
                current_path = None
            elif candidate.startswith("b/"):
                current_path = _normalize_diff_path(candidate[2:])
            else:
                current_path = _normalize_diff_path(candidate)

            if current_path:
                line_map.setdefault(current_path, set())
            continue

        if raw_line.startswith("@@ "):
            match = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", raw_line)
            current_new_line = int(match.group(1)) if match else None
            continue

        if current_path is None or current_new_line is None:
            continue

        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            line_map[current_path].add(current_new_line)
            current_new_line += 1
            continue

        if raw_line.startswith("-") and not raw_line.startswith("---"):
            continue

        current_new_line += 1

    return line_map


def _build_inline_review_comments(
    suggestions: Iterable[dict],
    diff_line_map: dict[str, set[int]],
) -> tuple[list[dict], list[str]]:
    inline_comments: list[dict] = []
    moved_to_summary: list[str] = []

    for suggestion in suggestions:
        path = _normalize_diff_path(str(suggestion.get("path", "")))
        line = suggestion.get("line")
        message = str(suggestion.get("message", "")).strip()
        severity = str(suggestion.get("severity", "Medium")).strip() or "Medium"

        if not path or not isinstance(line, int) or line <= 0 or not message:
            continue

        body = f"**Severity:** {severity}\n\n{message}"
        if line in diff_line_map.get(path, set()):
            inline_comments.append({"path": path, "line": line, "body": body, "side": "RIGHT"})
        else:
            moved_to_summary.append(f"- **{severity}** `{path}:{line}` — {message}")

    return inline_comments, moved_to_summary


def _build_failure_summary(error_text: str) -> str:
    return (
        "AI Review Failed\n\n"
        "The automated structured review could not be completed.\n\n"
        "Technical details:\n"
        f"- {error_text}"
    )


async def _process_pull_request_review(
    payload: dict,
    settings: Settings,
    github_service: GithubService,
    gemini_service: GeminiService,
) -> None:
    action = payload.get("action")
    pull_request = payload.get("pull_request")
    installation_id = payload.get("installation", {}).get("id")

    if not (pull_request and action in ["opened", "synchronize", "reopened"]):
        return

    repo_full_name = payload.get("repository", {}).get("full_name")
    pr_number = pull_request.get("number")
    head_sha = pull_request.get("head", {}).get("sha")

    if not (repo_full_name and pr_number and head_sha):
        return

    try:
        diff_content = await github_service.download_diff(
            installation_id,
            repo_full_name,
            pr_number,
        )
    except GithubServiceError as exc:
        logger.error("Failed to download diff for PR #%s: %s", pr_number, exc)
        return

    if not diff_content:
        logger.error("Empty diff content for %s PR #%s", repo_full_name, pr_number)
        return

    with Session(engine) as session:
        app_config = get_app_config_singleton(session)
        active_model = app_config.active_model if app_config else settings.ai_model_name
        effective_prompt, prompt_version = resolve_effective_review_prompt(app_config, settings.ai_review_prompt)
        prompt_hash = hashlib.sha256(effective_prompt.encode("utf-8")).hexdigest()[:12]

        history_status = "Success"
        review_content = ""
        review_token_count = 0
        summary_for_review = ""
        inline_comments: list[dict] = []

        logger.info(
            "Starting structured review generation",
            extra={
                "repo": repo_full_name,
                "pr_number": pr_number,
                "model": active_model,
                "prompt_version": prompt_version,
                "prompt_hash": prompt_hash,
            },
        )

        try:
            structured_review, review_token_count = await gemini_service.generate_structured_review(
                diff_content,
                active_model,
                effective_prompt,
            )

            summary_for_review = structured_review.get("summary", "No significant issues found.")
            suggestions = structured_review.get("suggestions", [])
            diff_line_map = _extract_diff_line_map(diff_content)
            inline_comments, moved_to_summary = _build_inline_review_comments(suggestions, diff_line_map)

            if moved_to_summary:
                summary_for_review += "\n\n### Suggestions moved to summary (line not valid in current diff)\n"
                summary_for_review += "\n".join(moved_to_summary)

            if not inline_comments and moved_to_summary:
                history_status = "Fallback"

            review_content = summary_for_review
        except TokenLimitExceededError as exc:
            history_status = "Failure"
            review_token_count = exc.token_count
            review_content = str(exc)
            summary_for_review = _build_failure_summary(review_content)
        except StructuredReviewParseError as exc:
            history_status = "Failure"
            review_content = str(exc)
            summary_for_review = _build_failure_summary(review_content)
        except GeminiServiceError as exc:
            history_status = "Failure"
            review_content = str(exc)
            summary_for_review = _build_failure_summary(review_content)
        except Exception as exc:
            logger.exception("Unhandled error generating Gemini review for PR #%s: %s", pr_number, exc)
            history_status = "Failure"
            review_content = f"An unexpected error occurred during AI review: {exc}"
            summary_for_review = _build_failure_summary(review_content)

        logger.info(
            "Structured review generation completed",
            extra={
                "repo": repo_full_name,
                "pr_number": pr_number,
                "model": active_model,
                "prompt_version": prompt_version,
                "prompt_hash": prompt_hash,
                "status": history_status,
                "token_count": review_token_count,
                "inline_comments": len(inline_comments),
            },
        )

        history_row = ReviewHistory(
            repo_name=repo_full_name,
            pr_number=pr_number,
            model_used=active_model,
            token_count=review_token_count,
            status=history_status,
            prompt_version=prompt_version,
            prompt_hash=prompt_hash,
        )
        session.add(history_row)
        session.commit()

    try:
        await github_service.create_pull_request_review(
            installation_id=installation_id,
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            commit_id=head_sha,
            summary=summary_for_review,
            comments=inline_comments,
            model_name=active_model,
        )
    except GithubServiceError as exc:
        logger.error("Failed to post review for PR #%s: %s", pr_number, exc)


@router.post("/webhook", status_code=202)
async def webhook_handler(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    settings: Settings = Depends(get_settings),
    github_service: GithubService = Depends(get_github_service),
    gemini_service: GeminiService = Depends(get_gemini_service),
):
    raw_payload = await request.body()
    verify_webhook_signature(x_hub_signature_256, raw_payload, settings)

    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as exc:
        logger.error("Invalid JSON payload received.")
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

    action = payload.get("action")
    pull_request = payload.get("pull_request")

    if pull_request and action in ["opened", "synchronize", "reopened"]:
        background_tasks.add_task(_process_pull_request_review, payload, settings, github_service, gemini_service)
        return {"status": "accepted", "message": "Webhook received, review processing started asynchronously"}

    return {"status": "success", "message": "Webhook received, no PR action taken"}
