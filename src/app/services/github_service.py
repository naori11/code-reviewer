import json
import logging
from typing import Optional

import httpx
from gidgethub import BadRequest, HTTPException as GitHubHTTPException, apps
from gidgethub.httpx import GitHubAPI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..core.config import Settings

logger = logging.getLogger(__name__)


class GithubServiceError(Exception):
    pass


class GithubService:
    def __init__(self, settings: Settings, http_client: httpx.AsyncClient):
        self.settings = settings
        self.http_client = http_client

    async def _get_token(self, installation_id: Optional[int]) -> str:
        if installation_id and self.settings.github_app_id and self.settings.github_private_key:
            try:
                private_key = self.settings.github_private_key.replace("\\n", "\n")
                token_response = await apps.get_installation_access_token(
                    self.http_client,
                    installation_id=str(installation_id),
                    app_id=str(self.settings.github_app_id),
                    private_key=private_key,
                )
                return token_response["token"]
            except Exception as exc:
                logger.exception("Failed to generate GitHub installation token: %s", exc)
                raise GithubServiceError("GitHub App authentication failed.") from exc

        if self.settings.github_token:
            logger.warning("Using GITHUB_TOKEN (PAT) is deprecated. Please switch to GitHub App.")
            return self.settings.github_token

        logger.error("No GitHub authentication configured.")
        raise GithubServiceError("GitHub authentication configuration missing.")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(GithubServiceError),
    )
    async def download_diff(self, installation_id: Optional[int], repo_full_name: str, pr_number: int) -> str:
        github_token = await self._get_token(installation_id)
        url = f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}"
        headers = {
            "Authorization": f"token {github_token}",
            "Accept": "application/vnd.github.v3.diff",
        }

        try:
            response = await self.http_client.get(url, headers=headers)

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
        except httpx.TimeoutException as exc:
            raise GithubServiceError(f"Timed out during diff download: {exc}") from exc
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
        retry=retry_if_exception_type(GithubServiceError),
    )
    async def post_github_comment(
        self,
        installation_id: Optional[int],
        repo_full_name: str,
        pr_number: int,
        comment_body: str,
        model_name: str,
    ) -> None:
        github_token = await self._get_token(installation_id)
        github_api = GitHubAPI(self.http_client, self.settings.app_name, oauth_token=github_token)

        header = f"{self.settings.ai_review_header}\n\n{self.settings.ai_review_disclaimer}\n\n"
        footer = f"\n\n---\n<sub>Powered by {model_name} - {self.settings.app_name}</sub>"

        max_body_length = self.settings.github_comment_limit - len(header) - len(footer) - 100
        if len(comment_body) > max_body_length:
            logger.warning("Comment body too long (%s characters), truncating.", len(comment_body))
            truncation_msg = "\n\n**[Review truncated due to GitHub character limit]**"
            comment_body = comment_body[: max_body_length - len(truncation_msg)] + truncation_msg

        formatted_comment = f"{header}{comment_body}{footer}"
        try:
            await github_api.post(
                f"/repos/{repo_full_name}/issues/{pr_number}/comments",
                data={"body": formatted_comment},
            )
            logger.info("Successfully posted comment to PR #%s", pr_number)
        except httpx.TimeoutException as exc:
            raise GithubServiceError(f"Timed out while posting GitHub comment: {exc}") from exc
        except (BadRequest, GitHubHTTPException) as exc:
            raise GithubServiceError(f"GitHub API error while posting comment: {exc}") from exc
        except Exception as exc:
            logger.exception("Unexpected error posting GitHub comment: %s", exc)
            raise GithubServiceError(f"Unexpected error posting GitHub comment: {exc}") from exc
