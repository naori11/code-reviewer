import json
import logging

import anyio
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlmodel import Session

from ..core.config import Settings, get_settings
from ..core.database import get_session
from ..core.security import verify_webhook_signature
from ..crud.app_config import get_app_config_singleton
from ..models.entities import ReviewHistory
from ..services.gemini_service import GeminiService, GeminiServiceError, TokenLimitExceededError
from ..services.github_service import GithubService, GithubServiceError

logger = logging.getLogger(__name__)
router = APIRouter(tags=["webhooks"])


def get_github_service(settings: Settings = Depends(get_settings)) -> GithubService:
    return GithubService(settings)


def get_gemini_service(settings: Settings = Depends(get_settings)) -> GeminiService:
    return GeminiService(settings)


@router.post("/webhook")
async def webhook_handler(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    session: Session = Depends(get_session),
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
    installation_id = payload.get("installation", {}).get("id")

    if pull_request and action in ["opened", "synchronize", "reopened"]:
        repo_full_name = payload.get("repository", {}).get("full_name")
        pr_number = pull_request.get("number")

        if not (repo_full_name and pr_number):
            return {"status": "success", "message": "Webhook received, no PR action taken"}

        github_client = github_service.get_client(installation_id)
        github_token = github_service.get_diff_token(github_client, installation_id)

        if not github_token:
            raise HTTPException(status_code=500, detail="GitHub authentication configuration missing.")

        try:
            diff_content = await anyio.to_thread.run_sync(
                github_service.download_diff,
                github_token,
                repo_full_name,
                pr_number,
            )
        except GithubServiceError as exc:
            logger.error("Failed to download diff for PR #%s: %s", pr_number, exc)
            raise HTTPException(status_code=500, detail=f"Failed to retrieve PR diff from GitHub: {exc}") from exc

        if not diff_content:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to retrieve PR diff from GitHub for {repo_full_name} #{pr_number} (empty content)",
            )

        app_config = get_app_config_singleton(session)
        active_model = app_config.active_model if app_config else settings.ai_model_name

        history_status = "Success"
        review_content = ""
        review_token_count = 0
        error_response: HTTPException | None = None

        try:
            review_content, review_token_count = await anyio.to_thread.run_sync(
                gemini_service.generate_review,
                diff_content,
                active_model,
            )
        except TokenLimitExceededError as exc:
            history_status = "Failure"
            review_content = str(exc)
            review_token_count = exc.token_count
            error_response = HTTPException(status_code=400, detail=review_content)
        except GeminiServiceError as exc:
            history_status = "Failure"
            review_content = str(exc)
            error_response = HTTPException(status_code=500, detail=review_content)
        except Exception as exc:
            logger.exception("Unhandled error generating Gemini review for PR #%s: %s", pr_number, exc)
            history_status = "Failure"
            review_content = f"An unexpected error occurred during AI review: {exc}"
            error_response = HTTPException(status_code=500, detail=review_content)

        history_row = ReviewHistory(
            repo_name=repo_full_name,
            pr_number=pr_number,
            model_used=active_model,
            token_count=review_token_count,
            status=history_status,
        )
        session.add(history_row)
        session.commit()

        await anyio.to_thread.run_sync(
            github_service.post_github_comment,
            github_client,
            repo_full_name,
            pr_number,
            review_content,
            active_model,
        )

        if error_response:
            raise error_response

        return {
            "status": "success",
            "message": "Webhook processed, review generated and posted to PR",
            "review_preview": review_content[:100] + "..." if len(review_content) > 100 else review_content,
        }

    return {"status": "success", "message": "Webhook received, no PR action taken"}
