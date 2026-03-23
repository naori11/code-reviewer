import json
import logging
from typing import Optional

import httpx
from fastapi import HTTPException
from github import Auth, Github
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..core.config import Settings

logger = logging.getLogger(__name__)


class GithubServiceError(Exception):
    pass


class GithubService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def get_client(self, installation_id: Optional[int] = None) -> Github:
        if self.settings.github_app_id and self.settings.github_private_key:
            try:
                private_key = self.settings.github_private_key.replace("\\n", "\n")
                if installation_id:
                    auth = Auth.AppInstallationAuth(self.settings.github_app_id, private_key, installation_id)
                else:
                    auth = Auth.AppAuth(self.settings.github_app_id, private_key)
                return Github(auth=auth)
            except Exception as exc:
                logger.error("Failed to initialize GitHub App auth: %s", exc)
                raise HTTPException(status_code=500, detail="GitHub App authentication failed.") from exc

        if self.settings.github_token:
            logger.warning("Using GITHUB_TOKEN (PAT) is deprecated. Please switch to GitHub App.")
            return Github(auth=Auth.Token(self.settings.github_token))

        logger.error("No GitHub authentication configured.")
        raise HTTPException(status_code=500, detail="GitHub client not configured.")

    def get_diff_token(self, github_client: Github, installation_id: Optional[int]) -> Optional[str]:
        if installation_id and self.settings.github_app_id and self.settings.github_private_key:
            try:
                return github_client.get_auth().token
            except Exception as exc:
                logger.warning("Could not extract installation token: %s", exc)

        return self.settings.github_token

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(GithubServiceError),
    )
    def download_diff(self, github_token: str, repo_full_name: str, pr_number: int) -> str:
        if not github_token:
            logger.error("github_token is required for download_diff.")
            raise GithubServiceError("github_token is required for download_diff")

        url = f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}"
        headers = {
            "Authorization": f"token {github_token}",
            "Accept": "application/vnd.github.v3.diff",
        }

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.get(url, headers=headers)

            if response.status_code == 200:
                return response.text

            error_message = (
                f"Failed to fetch diff from GitHub API for {repo_full_name} PR #{pr_number}. "
                f"Status: {response.status_code}. "
            )
            try:
                error_details = response.json()
                error_message += f"Details: {error_details}"
            except (json.JSONDecodeError, httpx.DecodingError):
                error_message += f"Raw response: {response.text}"

            logger.error(error_message)
            raise GithubServiceError(error_message)
        except httpx.HTTPError as exc:
            raise GithubServiceError(f"HTTP error during diff download: {exc}") from exc
        except GithubServiceError:
            raise
        except Exception as exc:
            logger.exception("Unexpected error during diff download: %s", exc)
            raise GithubServiceError(f"Unexpected error during diff download: {exc}") from exc

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def post_github_comment(self, github_client: Github, repo_full_name: str, pr_number: int, comment_body: str, model_name: str) -> None:
        repo = github_client.get_repo(repo_full_name)
        pr = repo.get_pull(pr_number)

        header = f"{self.settings.ai_review_header}\n\n{self.settings.ai_review_disclaimer}\n\n"
        footer = f"\n\n---\n<sub> Powered by {model_name} • {self.settings.app_name}</sub>"

        max_body_length = self.settings.github_comment_limit - len(header) - len(footer) - 100
        if len(comment_body) > max_body_length:
            logger.warning("Comment body too long (%s characters), truncating.", len(comment_body))
            truncation_msg = "\n\n**[Review truncated due to GitHub character limit]**"
            comment_body = comment_body[: max_body_length - len(truncation_msg)] + truncation_msg

        formatted_comment = f"{header}{comment_body}{footer}"
        pr.create_issue_comment(formatted_comment)
        logger.info("Successfully posted comment to PR #%s", pr_number)
