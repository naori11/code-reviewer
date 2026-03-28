import click
import httpx
import json
import os
import secrets
import hmac
import hashlib
import subprocess
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv, set_key
from google import genai
from github import Github, Auth

# Configuration setup for the CLI client
CONFIG_DIR = Path.home() / ".code_reviewer"
CONFIG_FILE = CONFIG_DIR / "config.json"


def save_client_config(url: str, token: str, auto_restart: bool = False):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump({"url": url.rstrip("/"), "token": token, "auto_restart_on_config_change": auto_restart}, f)


def load_client_config():
    if not CONFIG_FILE.exists():
        click.secho("Error: Client not initialized. Run 'reviewer init' first.", fg="red")
        exit(1)
    with open(CONFIG_FILE, "r") as f:
        config = json.load(f)
        # Ensure default value if key is missing from old config
        if "auto_restart_on_config_change" not in config:
            config["auto_restart_on_config_change"] = False
        return config


def _admin_get(path: str, timeout: float = 10.0):
    config = load_client_config()
    headers = {"X-Admin-Token": config["token"]}
    response = httpx.get(f"{config['url']}{path}", headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _admin_post(path: str, payload: dict, timeout: float = 10.0):
    config = load_client_config()
    headers = {"X-Admin-Token": config["token"]}
    response = httpx.post(f"{config['url']}{path}", headers=headers, json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _print_models_table(data: dict):
    click.echo(f"\n{'DISPLAY NAME':<35} | {'MODEL ID':<45}")
    click.echo("-" * 85)

    for model in data.get("models", []):
        click.echo(f"{model['display_name']:<35} | {model['model_id']:<45}")

    click.echo(f"\nTotal: {data.get('count', 0)} models found.")


def _print_prompt(data: dict):
    click.secho("✔ Current review prompt", fg="green")
    click.echo(f"Prompt Version: {data.get('prompt_version')}")
    click.echo("\n--- Prompt Start ---")
    click.echo(data.get("review_prompt", ""))
    click.echo("--- Prompt End ---")


def _print_active_model(data: dict):
    click.secho("✔ Active model", fg="green")
    click.echo(f"Active Model  : {data.get('active_model')}")


def _print_history(data: dict):
    click.echo(
        f"\n{'REPO':<30} | {'PR':<8} | {'MODEL':<28} | {'TOKENS':<8} | {'STATUS':<10} | {'PROMPT V':<8} | {'HASH':<12}"
    )
    click.echo("-" * 130)
    for row in data.get("history", []):
        click.echo(
            f"{str(row.get('repo_name', '')):<30} | "
            f"{str(row.get('pr_number', '')):<8} | "
            f"{str(row.get('model_used', '')):<28} | "
            f"{str(row.get('token_count', '')):<8} | "
            f"{str(row.get('status', '')):<10} | "
            f"{str(row.get('prompt_version', '')):<8} | "
            f"{str(row.get('prompt_hash', '')):<12}"
        )
    click.echo(f"\nTotal: {data.get('count', 0)} records found.")


def _print_prompt_history(data: dict):
    click.echo(f"\n{'PROMPT V':<10} | {'HASH':<12} | {'REVIEWS':<8} | {'FIRST USED':<26} | {'LAST USED':<26}")
    click.echo("-" * 100)
    for row in data.get("history", []):
        click.echo(
            f"{str(row.get('prompt_version', '')):<10} | "
            f"{str(row.get('prompt_hash', '')):<12} | "
            f"{str(row.get('review_count', '')):<8} | "
            f"{str(row.get('first_used_at', '')):<26} | "
            f"{str(row.get('last_used_at', '')):<26}"
        )
    click.echo(f"\nTotal: {data.get('count', 0)} prompt versions found.")


def restart_server():
    """Executes docker-compose restart to apply changes."""
    click.echo("🔄 Restarting server container via docker-compose...")
    try:
        # Check if docker-compose.yml exists in current directory
        if not Path("docker-compose.yml").exists():
            click.secho("Error: docker-compose.yml not found in the current directory.", fg="red")
            click.echo("Please manually run 'docker-compose restart' in the server directory.")
            return

        result = subprocess.run(["docker-compose", "restart"], capture_output=True, text=True)
        if result.returncode == 0:
            click.secho("✔ Server restarted successfully!", fg="green")
        else:
            click.secho(f"✘ Failed to restart server: {result.stderr}", fg="red")
            click.echo("Please ensure Docker is running and you have permissions.")
    except FileNotFoundError:
        click.secho("Error: 'docker-compose' command not found.", fg="red")
        click.echo("Please install Docker Compose or restart the server manually.")
    except Exception as e:
        click.secho(f"Error during restart: {str(e)}", fg="red")


@click.group(
    help="""
Code Reviewer CLI - Manage your Gemini models and server setup.

\b
Getting Started:
  1. Run 'setup-server' on your VM to configure the environment.
  2. Run 'init' to connect this CLI to your server.
  3. Use 'health' to verify your API connections.
"""
)
def cli():
    pass


@cli.group("admin-mode")
def admin_mode():
    """Call admin API endpoints."""
    pass


@cli.command()
@click.option("--url", help="The URL of your FastAPI server (e.g., http://localhost:8000).")
@click.option("--token", help="Your server's Admin Token (WEBHOOK_SECRET).")
@click.option("--auto-restart", is_flag=True, help="Enable automatic server restart on config changes.")
def init(url, token, auto_restart):
    """Connect the CLI to your Code Reviewer server."""
    # Auto-detection of local .env
    env_path = Path(".env")
    auto_token = None
    if env_path.exists():
        load_dotenv()
        auto_token = os.getenv("WEBHOOK_SECRET")

    if not url:
        url = click.prompt("Server URL", default="http://localhost:8000")

    url = url.rstrip("/")

    # Verify server connectivity (similar to status command)
    click.echo(f"Verifying connection to {url}...")
    try:
        # Use a simple health check or the active model endpoint
        # We don't have the token yet if it's not provided, so we might get a 403 or 401,
        # but as long as we get a response, the URL is likely correct.
        response = httpx.get(f"{url}/api/admin/config/active-model", timeout=5.0)
        if response.status_code in [200, 403]:
            click.secho(f"✔ Server reached successfully.", fg="green")
        else:
            click.secho(
                f"⚠ Server returned unexpected status {response.status_code}. It might be misconfigured.", fg="yellow"
            )
    except (httpx.ConnectError, httpx.ConnectTimeout):
        click.secho(f"✘ Error: Could not connect to {url}.", fg="red")
        click.secho("The server may not be running or the address typed is wrong.", fg="red")
        if not click.confirm("Do you want to proceed anyway?", default=False):
            return
    except Exception as e:
        click.secho(f"⚠ Warning: Could not verify server connection: {str(e)}", fg="yellow")

    if not token:
        if auto_token:
            if click.confirm(f"Found WEBHOOK_SECRET in local .env. Use it?", default=True):
                token = auto_token

        if not token:
            token = click.prompt("Admin Token (WEBHOOK_SECRET)", hide_input=True)

    if not auto_restart:
        auto_restart = click.confirm("Enable automatic server restart on config changes?", default=False)

    save_client_config(url, token, auto_restart)
    click.secho(f"✔ Successfully initialized! Config saved to {CONFIG_FILE}", fg="green")


@cli.command()
@click.option("--restart", is_flag=True, help="Force a server restart after setup.")
def setup_server(restart):
    """Interactive wizard to configure the server's .env file."""
    click.secho("\n🚀 Code Reviewer Server Onboarding", fg="cyan", bold=True)

    env_path = Path(".env")
    if not env_path.exists():
        if Path(".env.example").exists():
            import shutil

            shutil.copy(".env.example", ".env")
            click.echo("✔ Created .env from .env.example")
        else:
            env_path.touch()
            click.echo("✔ Created new .env file")

    load_dotenv()

    config_changed = False

    # 1. WEBHOOK_SECRET
    current_secret = os.getenv("WEBHOOK_SECRET")
    if not current_secret:
        new_secret = secrets.token_hex(20)
        set_key(".env", "WEBHOOK_SECRET", new_secret)
        click.secho(f"✔ Generated new WEBHOOK_SECRET: {new_secret}", fg="green")
        config_changed = True
    else:
        click.echo("✔ WEBHOOK_SECRET is already configured.")

    # 2. GEMINI_API_KEY
    click.echo("\n--- AI Configuration ---")
    if os.getenv("GEMINI_API_KEY"):
        click.secho("✔ GEMINI_API_KEY is already configured.", fg="green")
        if click.confirm("Do you want to update it?", default=False):
            gemini_key = click.prompt("Enter new GEMINI_API_KEY")
            set_key(".env", "GEMINI_API_KEY", gemini_key)
            config_changed = True
    else:
        click.echo("Get your key from: https://aistudio.google.com/")
        gemini_key = click.prompt("Enter your GEMINI_API_KEY")
        set_key(".env", "GEMINI_API_KEY", gemini_key)
        config_changed = True

    # 3. GitHub Auth
    click.echo("\n--- GitHub Authentication ---")
    has_app = os.getenv("GITHUB_APP_ID") and os.getenv("GITHUB_PRIVATE_KEY")
    has_pat = bool(os.getenv("GITHUB_TOKEN"))

    if has_app or has_pat:
        method = "GitHub App" if has_app else "Personal Access Token"
        click.secho(f"✔ Currently using: {method}", fg="green")
        if not click.confirm("Do you want to change authentication method?", default=False):
            auth_choice = "skip"
        else:
            auth_choice = click.prompt("Choose method", type=click.Choice(["app", "pat"]), default="app")
    else:
        click.echo("Method A (GitHub App): More secure, supports granular permissions.")
        click.echo("Method B (PAT): Simple setup using a personal token.")
        auth_choice = click.prompt("Choose method", type=click.Choice(["app", "pat"]), default="app")

    if auth_choice == "app":
        app_id = click.prompt("Enter GITHUB_APP_ID", default=os.getenv("GITHUB_APP_ID", ""))
        set_key(".env", "GITHUB_APP_ID", app_id)
        click.echo("Hint: Private keys look like '-----BEGIN RSA PRIVATE KEY-----...'")
        private_key = click.prompt("Enter GITHUB_PRIVATE_KEY", default=os.getenv("GITHUB_PRIVATE_KEY", ""))
        set_key(".env", "GITHUB_PRIVATE_KEY", private_key)
        set_key(".env", "GITHUB_TOKEN", "")  # Clear PAT
        config_changed = True
    elif auth_choice == "pat":
        pat_token = click.prompt("Enter GITHUB_TOKEN", default=os.getenv("GITHUB_TOKEN", ""))
        set_key(".env", "GITHUB_TOKEN", pat_token)
        set_key(".env", "GITHUB_APP_ID", "")  # Clear App
        set_key(".env", "GITHUB_PRIVATE_KEY", "")
        config_changed = True

    # Final Summary & Guide
    load_dotenv()
    secret = os.getenv("WEBHOOK_SECRET")
    click.secho("\n✨ Server Configuration Complete!", fg="green", bold=True)

    # Handle Restart
    if config_changed or restart:
        # Load config to check for auto-restart
        try:
            cli_config = load_client_config()
            auto_restart = cli_config.get("auto_restart_on_config_change", False)
        except Exception:
            auto_restart = False

        if (
            restart
            or auto_restart
            or click.confirm("Configuration updated. Restart the server container to apply changes?", default=True)
        ):
            restart_server()
        else:
            click.secho("\nNote: Please manually run `docker-compose restart` for changes to take effect.", fg="yellow")

    click.echo("\nHow to set up your GitHub Webhook:")
    click.echo("  1. Go to your Repository/App Settings > Webhooks > Add Webhook.")
    click.echo(f"  2. Payload URL: http://[your-server-ip]:8000/webhook")
    click.echo("  3. Content type: application/json")
    click.echo(f"  4. Secret: {secret}")
    click.echo("  5. Which events? Select 'Individual events' > 'Pull requests'.")
    click.echo("\nNext: Run 'reviewer init' on your client machine.")


@cli.command()
def health():
    """Verify that your Gemini and GitHub API connections are working."""
    load_dotenv()
    click.echo("Checking API Health...")

    # 1. Gemini Check
    gemini_key = os.getenv("GEMINI_API_KEY")
    if not gemini_key:
        click.secho("✘ Gemini: No API Key found in .env", fg="red")
    else:
        try:
            client = genai.Client(api_key=gemini_key)
            # Try to list models as a connectivity test
            client.models.list(config={"page_size": 1})
            click.secho("✔ Gemini API: Connected and Authorized", fg="green")
        except Exception as e:
            click.secho(f"✘ Gemini API: Failed - {str(e)}", fg="red")

    # 2. GitHub Check
    app_id = os.getenv("GITHUB_APP_ID")
    pat = os.getenv("GITHUB_TOKEN")

    try:
        if app_id:
            private_key = os.getenv("GITHUB_PRIVATE_KEY", "").replace("\\n", "\n")
            app_auth = Auth.AppAuth(app_id, private_key)
            github_client = Github(auth=app_auth)
            # We can't easily test 'AppAuth' without an installation ID, but we can check the JWT
            github_client.get_app()
            click.secho("✔ GitHub App: Authentication Successful", fg="green")
        elif pat:
            token_auth = Auth.Token(pat)
            github_client = Github(auth=token_auth)
            user = github_client.get_user().login
            click.secho(f"✔ GitHub PAT: Authenticated as {user}", fg="green")
        else:
            click.secho("✘ GitHub: No credentials found in .env", fg="red")
    except Exception as e:
        click.secho(f"✘ GitHub API: Failed - {str(e)}", fg="red")


@cli.command()
def env():
    """Display a masked summary of your environment variables."""
    load_dotenv()
    vars = ["GEMINI_API_KEY", "GITHUB_APP_ID", "GITHUB_TOKEN", "WEBHOOK_SECRET"]
    click.echo("\nEnvironment Status:")
    for var in vars:
        val = os.getenv(var)
        if val:
            masked = val[:4] + "*" * (len(val) - 8) + val[-4:] if len(val) > 8 else "****"
            click.echo(f"  {var:<18}: {masked}")
        else:
            click.secho(f"  {var:<18}: NOT SET", fg="yellow")


@cli.command()
def test_webhook():
    """Simulate a GitHub 'ping' event to test server signature verification."""
    config = load_client_config()
    load_dotenv()
    secret = os.getenv("WEBHOOK_SECRET")

    if not secret:
        click.secho("Error: WEBHOOK_SECRET not found in .env. Cannot sign payload.", fg="red")
        return

    # Using 'ping' instead of 'opened' to test signature without triggering PR logic
    payload = {
        "zen": "Everything is better with a CLI.",
        "hook_id": 123456789,
        "hook": {"type": "App", "id": 123456789, "active": True, "events": ["pull_request"]},
    }
    body = json.dumps(payload)

    # Generate HMAC signature
    signature = "sha256=" + hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()

    headers = {"X-Hub-Signature-256": signature, "Content-Type": "application/json", "X-GitHub-Event": "ping"}

    click.echo(f"Sending test 'ping' to {config['url']}/webhook...")
    try:
        response = httpx.post(f"{config['url']}/webhook", content=body, headers=headers)
        if response.status_code == 202:
            click.secho(
                f"✔ Success: Signature verified. Server responded: {response.json().get('message')}", fg="green"
            )
        else:
            click.secho(f"✘ Failed: Server returned {response.status_code} - {response.text}", fg="red")
    except Exception as e:
        click.secho(f"✘ Error connecting to server: {str(e)}", fg="red")


@cli.command()
def list():
    """List Gemini models suitable for code review."""
    try:
        data = _admin_get("/api/admin/models")
        _print_models_table(data)
    except Exception as e:
        click.secho(f"Error: {str(e)}", fg="red")


@cli.command()
@click.argument("model_id")
def set(model_id):
    """Switch the active Gemini model for reviews."""
    payload = {"model_name": model_id}

    try:
        _admin_post("/api/admin/config/active-model", payload)
        click.secho(f"✔ Successfully switched to {model_id}", fg="green")
    except Exception as e:
        click.secho(f"Error: {str(e)}", fg="red")


@cli.command("prompt")
def get_prompt():
    """Show the current review prompt and version."""
    try:
        data = _admin_get("/api/admin/config/review-prompt")
        _print_prompt(data)
    except Exception as e:
        click.secho(f"Error: {str(e)}", fg="red")


@cli.command("set-prompt")
@click.option("--text", help="Review prompt text to set.")
@click.option("--reset-default", is_flag=True, help="Reset review prompt to server-side default AI_REVIEW_PROMPT.")
def set_prompt(text, reset_default):
    """Set the active review prompt used by AI reviews."""
    if text and reset_default:
        click.secho("Error: Use either --text or --reset-default, not both.", fg="red")
        return

    if reset_default:
        payload = {"reset_to_default": True}
    else:
        prompt_text = text

        if prompt_text is None:
            try:
                data = _admin_get("/api/admin/config/review-prompt")
                current_prompt = data.get("review_prompt", "")
            except Exception as e:
                click.secho(f"Error fetching current prompt: {str(e)}", fg="red")
                return

            prompt_text = click.prompt("Review prompt", default=current_prompt, show_default=False)

        prompt_text = prompt_text.strip()
        if not prompt_text:
            click.secho("Error: Prompt must not be empty.", fg="red")
            return

        payload = {"review_prompt": prompt_text}

    try:
        data = _admin_post("/api/admin/config/review-prompt", payload)
        click.secho("✔ Review prompt updated", fg="green")
        click.echo(f"Prompt Version: {data.get('prompt_version')}")
    except Exception as e:
        click.secho(f"Error: {str(e)}", fg="red")


@cli.command()
def status():
    """Check server connection and show active model."""
    config = load_client_config()
    url = config["url"]
    headers = {"X-Admin-Token": config["token"]}

    click.echo(f"Checking connection to {url}...")
    try:
        response = httpx.get(f"{url}/api/admin/config/active-model", headers=headers, timeout=5.0)
        if response.status_code == 200:
            data = response.json()
            click.secho(f"✔ Server Status: Online", fg="green")
            _print_active_model(data)
        elif response.status_code == 403:
            click.secho(f"✘ Server Status: Unauthorized", fg="red")
            click.echo("Reason: The Admin Token configured in this CLI does not match the server's WEBHOOK_SECRET.")
            click.echo("Fix   : Run 'reviewer init' to update your token.")
        else:
            click.secho(f"✘ Server Status: Error {response.status_code}", fg="red")
            click.echo(f"Response: {response.text}")
    except (httpx.ConnectError, httpx.ConnectTimeout):
        click.secho(f"✘ Server Status: Unreachable", fg="red")
        click.echo(f"Reason: Could not connect to {url}. Ensure the FastAPI server is running and the URL is correct.")
    except Exception as e:
        click.secho(f"✘ Server Status: Offline/Error", fg="red")
        click.echo(f"Error detail: {str(e)}")


@admin_mode.command("models")
def admin_models():
    """List Gemini models from admin API."""
    try:
        data = _admin_get("/api/admin/models")
        _print_models_table(data)
    except Exception as e:
        click.secho(f"Error: {str(e)}", fg="red")


@admin_mode.command("active-model")
def admin_active_model():
    """Show active model from admin API."""
    try:
        data = _admin_get("/api/admin/config/active-model")
        _print_active_model(data)
    except Exception as e:
        click.secho(f"Error: {str(e)}", fg="red")


@admin_mode.command("set-model")
@click.argument("model_id")
def admin_set_model(model_id):
    """Set active model via admin API."""
    try:
        _admin_post("/api/admin/config/active-model", {"model_name": model_id})
        click.secho(f"✔ Successfully switched to {model_id}", fg="green")
    except Exception as e:
        click.secho(f"Error: {str(e)}", fg="red")


@admin_mode.command("prompt")
def admin_prompt():
    """Show current review prompt from admin API."""
    try:
        data = _admin_get("/api/admin/config/review-prompt")
        _print_prompt(data)
    except Exception as e:
        click.secho(f"Error: {str(e)}", fg="red")


@admin_mode.command("set-prompt")
@click.option("--text", help="Review prompt text to set.")
@click.option("--reset-default", is_flag=True, help="Reset review prompt to server-side default AI_REVIEW_PROMPT.")
def admin_set_prompt(text, reset_default):
    """Set review prompt via admin API."""
    if text and reset_default:
        click.secho("Error: Use either --text or --reset-default, not both.", fg="red")
        return

    if reset_default:
        payload = {"reset_to_default": True}
    else:
        prompt_text = text
        if prompt_text is None:
            try:
                data = _admin_get("/api/admin/config/review-prompt")
                current_prompt = data.get("review_prompt", "")
            except Exception as e:
                click.secho(f"Error fetching current prompt: {str(e)}", fg="red")
                return
            prompt_text = click.prompt("Review prompt", default=current_prompt, show_default=False)

        prompt_text = prompt_text.strip()
        if not prompt_text:
            click.secho("Error: Prompt must not be empty.", fg="red")
            return
        payload = {"review_prompt": prompt_text}

    try:
        data = _admin_post("/api/admin/config/review-prompt", payload)
        click.secho("✔ Review prompt updated", fg="green")
        click.echo(f"Prompt Version: {data.get('prompt_version')}")
    except Exception as e:
        click.secho(f"Error: {str(e)}", fg="red")


@admin_mode.command("history")
def admin_history():
    """Show review history from admin API."""
    try:
        data = _admin_get("/api/admin/history")
        _print_history(data)
    except Exception as e:
        click.secho(f"Error: {str(e)}", fg="red")


@admin_mode.command("prompt-history")
def admin_prompt_history():
    """Show prompt usage history from admin API."""
    try:
        data = _admin_get("/api/admin/history/prompts")
        _print_prompt_history(data)
    except Exception as e:
        click.secho(f"Error: {str(e)}", fg="red")


if __name__ == "__main__":
    cli()
