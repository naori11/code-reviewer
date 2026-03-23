import json
import logging

import anyio
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlmodel import Session

from ..core.config import Settings, get_settings
from ..core.database import get_session
from ..core.security import verify_webhook_signature
from ..models.entities import AppConfig, ReviewHistory
from ..services.gemini_service import GeminiService
from ..services.github_service import GithubService

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

        diff_content = await anyio.to_thread.run_sync(
            github_service.download_diff,
            github_token,
            repo_full_name,
            pr_number,
        )
        if not diff_content:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to retrieve PR diff from GitHub for {repo_full_name} #{pr_number}",
            )

        app_config = session.get(AppConfig, 1)
        active_model = app_config.active_model if app_config else settings.ai_model_name

        review, token_count = await anyio.to_thread.run_sync(
            gemini_service.generate_review,
            diff_content,
            active_model,
        )

        status = "Success"
        if review.startswith("ERROR:"):
            status = "Failure"

        history_row = ReviewHistory(
            repo_name=repo_full_name,
            pr_number=pr_number,
            model_used=active_model,
            token_count=token_count,
            status=status,
        )
        session.add(history_row)
        session.commit()

        if review.startswith("ERROR:"):
            await anyio.to_thread.run_sync(
                github_service.post_github_comment,
                github_client,
                repo_full_name,
                pr_number,
                review,
                active_model,
            )
            raise HTTPException(status_code=400 if "too large" in review else 500, detail=review)

        await anyio.to_thread.run_sync(
            github_service.post_github_comment,
            github_client,
            repo_full_name,
            pr_number,
            review,
            active_model,
        )

        return {
            "status": "success",
            "message": "Webhook processed, review generated and posted to PR",
            "review_preview": review[:100] + "..." if len(review) > 100 else review,
        }

    return {"status": "success", "message": "Webhook received, no PR action taken"}
