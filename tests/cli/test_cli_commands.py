import json
from pathlib import Path
from types import SimpleNamespace

import httpx
from click.testing import CliRunner

import reviewer


def _set_cli_config_path(monkeypatch, tmp_path: Path) -> Path:
    config_dir = tmp_path / ".code_reviewer"
    config_file = config_dir / "config.json"
    monkeypatch.setattr(reviewer, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(reviewer, "CONFIG_FILE", config_file)
    return config_file


def test_init_saves_config_success(monkeypatch, tmp_path: Path) -> None:
    config_file = _set_cli_config_path(monkeypatch, tmp_path)

    class _Resp:
        status_code = 200

    monkeypatch.setattr(reviewer.httpx, "get", lambda *args, **kwargs: _Resp())

    runner = CliRunner()
    result = runner.invoke(
        reviewer.cli,
        [
            "init",
            "--url",
            "http://localhost:8000",
            "--token",
            "secret-token",
            "--auto-restart",
        ],
    )

    assert result.exit_code == 0
    assert config_file.exists()

    data = json.loads(config_file.read_text())
    assert data["url"] == "http://localhost:8000"
    assert data["token"] == "secret-token"
    assert data["auto_restart_on_config_change"] is True


def test_init_connect_error_user_declines(monkeypatch, tmp_path: Path) -> None:
    config_file = _set_cli_config_path(monkeypatch, tmp_path)

    def _raise_connect_error(*args, **kwargs):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(reviewer.httpx, "get", _raise_connect_error)

    runner = CliRunner()
    result = runner.invoke(
        reviewer.cli,
        ["init", "--url", "http://bad-host"],
        input="n\n",
    )

    assert result.exit_code == 0
    assert "Could not connect to http://bad-host" in result.output
    assert not config_file.exists()


def test_health_reports_missing_credentials(monkeypatch) -> None:
    monkeypatch.setattr(reviewer, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    runner = CliRunner()
    result = runner.invoke(reviewer.cli, ["health"])

    assert result.exit_code == 0
    assert "Gemini: No API Key found in .env" in result.output
    assert "GitHub: No credentials found in .env" in result.output


def test_health_pat_success(monkeypatch) -> None:
    monkeypatch.setattr(reviewer, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.delenv("GITHUB_APP_ID", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_token")

    class _FakeModels:
        def list(self, config):
            return []

    class _FakeGenaiClient:
        def __init__(self, api_key: str):
            self.api_key = api_key
            self.models = _FakeModels()

    class _FakeUser:
        login = "ci-bot"

    class _FakeGithubClient:
        def __init__(self, auth):
            self.auth = auth

        def get_user(self):
            return _FakeUser()

    monkeypatch.setattr(reviewer.genai, "Client", _FakeGenaiClient)
    monkeypatch.setattr(reviewer.Auth, "Token", lambda token: SimpleNamespace(token=token))
    monkeypatch.setattr(reviewer, "Github", _FakeGithubClient)

    runner = CliRunner()
    result = runner.invoke(reviewer.cli, ["health"])

    assert result.exit_code == 0
    assert "Gemini API: Connected and Authorized" in result.output
    assert "GitHub PAT: Authenticated as ci-bot" in result.output


def test_admin_mode_models(monkeypatch) -> None:
    monkeypatch.setattr(
        reviewer,
        "_admin_get",
        lambda path, timeout=10.0: {
            "count": 1,
            "models": [{"display_name": "Gemini Flash", "model_id": "gemini-2.5-flash"}],
        },
    )

    runner = CliRunner()
    result = runner.invoke(reviewer.cli, ["admin-mode", "models"])

    assert result.exit_code == 0
    assert "DISPLAY NAME" in result.output
    assert "Gemini Flash" in result.output


def test_admin_mode_prompt_history(monkeypatch) -> None:
    monkeypatch.setattr(
        reviewer,
        "_admin_get",
        lambda path, timeout=10.0: {
            "count": 1,
            "history": [
                {
                    "prompt_version": 3,
                    "prompt_hash": "abc123def456",
                    "review_count": 7,
                    "first_used_at": "2026-03-20T00:00:00Z",
                    "last_used_at": "2026-03-29T00:00:00Z",
                }
            ],
        },
    )

    runner = CliRunner()
    result = runner.invoke(reviewer.cli, ["admin-mode", "prompt-history"])

    assert result.exit_code == 0
    assert "PROMPT V" in result.output
    assert "abc123def456" in result.output
    assert "Total: 1 prompt versions found." in result.output
