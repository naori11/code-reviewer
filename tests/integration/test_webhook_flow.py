import hashlib
import hmac
import json

from sqlmodel import Session, select

from src.app.models.entities import ReviewHistory


class _FakeGithubService:
    def __init__(self):
        self.review_calls = []

    async def download_diff(self, installation_id: int, repo_full_name: str, pr_number: int) -> str:
        return "diff --git a/main.py b/main.py\n--- a/main.py\n+++ b/main.py\n@@ -1 +1 @@\n+print('ok')\n"

    async def create_pull_request_review(
        self,
        installation_id: int,
        repo_full_name: str,
        pr_number: int,
        commit_id: str,
        summary: str,
        comments: list[dict],
        model_name: str,
    ) -> None:
        self.review_calls.append(
            {
                "installation_id": installation_id,
                "repo_full_name": repo_full_name,
                "pr_number": pr_number,
                "commit_id": commit_id,
                "summary": summary,
                "comments": comments,
                "model_name": model_name,
            }
        )


class _FakeGeminiService:
    async def generate_structured_review(self, diff_content: str, model_name: str) -> tuple[dict, int]:
        return {
            "summary": "Mock review markdown",
            "suggestions": [{"path": "main.py", "line": 1, "message": "Use structured logging", "severity": "Low"}],
        }, 123


def _signed_headers(secret: str, payload: dict) -> dict:
    raw = json.dumps(payload).encode()
    signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return {
        "X-Hub-Signature-256": f"sha256={signature}",
        "Content-Type": "application/json",
    }


def test_webhook_full_flow_records_history_and_posts_comment(
    mock_settings,
    app,
    client,
):
    from src.app.api import webhooks

    github_service = _FakeGithubService()

    app.dependency_overrides[webhooks.get_github_service] = lambda: github_service
    app.dependency_overrides[webhooks.get_gemini_service] = lambda: _FakeGeminiService()

    payload = {
        "action": "opened",
        "pull_request": {"number": 42, "head": {"sha": "abc123"}},
        "installation": {"id": 555},
        "repository": {"full_name": "owner/repo"},
    }

    response = client.post(
        "/webhook", data=json.dumps(payload), headers=_signed_headers("test-webhook-secret", payload)
    )

    assert response.status_code == 202
    assert response.json()["status"] == "accepted"

    assert len(github_service.review_calls) == 1
    assert github_service.review_calls[0]["repo_full_name"] == "owner/repo"
    assert github_service.review_calls[0]["pr_number"] == 42
    assert github_service.review_calls[0]["summary"] == "Mock review markdown"

    with Session(webhooks.engine) as session:
        rows = session.exec(
            select(ReviewHistory).where(ReviewHistory.repo_name == "owner/repo", ReviewHistory.pr_number == 42)
        ).all()
        assert len(rows) == 1
        assert rows[0].status == "Success"
        assert rows[0].token_count == 123


def test_webhook_rejects_invalid_signature(mock_settings, client):
    from src.app.api import webhooks

    payload = {
        "action": "opened",
        "pull_request": {"number": 42},
        "installation": {"id": 555},
        "repository": {"full_name": "owner/repo"},
    }

    response = client.post(
        "/webhook",
        data=json.dumps(payload),
        headers={
            "X-Hub-Signature-256": "sha256=invalid",
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 401
