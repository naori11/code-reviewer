import click
import httpx
import json
import os
import secrets
import hmac
import hashlib
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv, set_key
from google import genai
from github import Github, Auth

# Configuration setup for the CLI client
CONFIG_DIR = Path.home() / ".code_reviewer"
CONFIG_FILE = CONFIG_DIR / "config.json"

def save_client_config(url: str, token: str):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump({"url": url.rstrip("/"), "token": token}, f)

def load_client_config():
    if not CONFIG_FILE.exists():
        click.secho("Error: Client not initialized. Run 'reviewer init' first.", fg="red")
        exit(1)
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

@click.group(help="""
Code Reviewer CLI - Manage your Gemini models and server setup.

Getting Started:
  1. Run 'setup-server' on your VM to configure the environment.
  2. Run 'init' to connect this CLI to your server.
  3. Use 'health' to verify your API connections.
""")
def cli():
    pass

@cli.command()
@click.option("--url", help="The URL of your FastAPI server (e.g., http://localhost:8000).")
@click.option("--token", help="Your server's Admin Token (WEBHOOK_SECRET).")
def init(url, token):
    """Connect the CLI to your Code Reviewer server."""
    # Auto-detection of local .env
    env_path = Path(".env")
    auto_token = None
    if env_path.exists():
        load_dotenv()
        auto_token = os.getenv("WEBHOOK_SECRET")
    
    if not url:
        url = click.prompt("Server URL", default="http://localhost:8000")
    
    if not token:
        if auto_token:
            if click.confirm(f"Found WEBHOOK_SECRET in local .env. Use it?", default=True):
                token = auto_token
        
        if not token:
            token = click.prompt("Admin Token (WEBHOOK_SECRET)", hide_input=True)

    save_client_config(url, token)
    click.secho(f"✔ Successfully initialized! Config saved to {CONFIG_FILE}", fg="green")

@cli.command()
def setup_server():
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
    
    # 1. WEBHOOK_SECRET
    current_secret = os.getenv("WEBHOOK_SECRET")
    if not current_secret:
        new_secret = secrets.token_hex(20)
        set_key(".env", "WEBHOOK_SECRET", new_secret)
        click.secho(f"✔ Generated new WEBHOOK_SECRET: {new_secret}", fg="green")
    else:
        click.echo("✔ WEBHOOK_SECRET is already configured.")

    # 2. GEMINI_API_KEY
    click.echo("\n--- AI Configuration ---")
    if os.getenv("GEMINI_API_KEY"):
        click.secho("✔ GEMINI_API_KEY is already configured.", fg="green")
        if click.confirm("Do you want to update it?", default=False):
            gemini_key = click.prompt("Enter new GEMINI_API_KEY")
            set_key(".env", "GEMINI_API_KEY", gemini_key)
    else:
        click.echo("Get your key from: https://aistudio.google.com/")
        gemini_key = click.prompt("Enter your GEMINI_API_KEY")
        set_key(".env", "GEMINI_API_KEY", gemini_key)

    # 3. GitHub Auth
    click.echo("\n--- GitHub Authentication ---")
    has_app = os.getenv("GITHUB_APP_ID") and os.getenv("GITHUB_PRIVATE_KEY")
    has_pat = bool(os.getenv("GITHUB_TOKEN"))

    if has_app or has_pat:
        method = "GitHub App" if has_app else "Personal Access Token"
        click.secho(f"✔ Currently using: {method}", fg="green")
        if not click.confirm("Do you want to change authentication method?", default=False):
            auth_choice = 'skip'
        else:
            auth_choice = click.prompt("Choose method", type=click.Choice(['app', 'pat']), default='app')
    else:
        click.echo("Method A (GitHub App): More secure, supports granular permissions.")
        click.echo("Method B (PAT): Simple setup using a personal token.")
        auth_choice = click.prompt("Choose method", type=click.Choice(['app', 'pat']), default='app')

    if auth_choice == 'app':
        app_id = click.prompt("Enter GITHUB_APP_ID", default=os.getenv("GITHUB_APP_ID", ""))
        set_key(".env", "GITHUB_APP_ID", app_id)
        click.echo("Hint: Private keys look like '-----BEGIN RSA PRIVATE KEY-----...'")
        private_key = click.prompt("Enter GITHUB_PRIVATE_KEY", default=os.getenv("GITHUB_PRIVATE_KEY", ""))
        set_key(".env", "GITHUB_PRIVATE_KEY", private_key)
        set_key(".env", "GITHUB_TOKEN", "") # Clear PAT
    elif auth_choice == 'pat':
        pat_token = click.prompt("Enter GITHUB_TOKEN", default=os.getenv("GITHUB_TOKEN", ""))
        set_key(".env", "GITHUB_TOKEN", pat_token)
        set_key(".env", "GITHUB_APP_ID", "") # Clear App
        set_key(".env", "GITHUB_PRIVATE_KEY", "")

    # Final Summary & Guide
    load_dotenv()
    secret = os.getenv("WEBHOOK_SECRET")
    click.secho("\n✨ Server Configuration Complete!", fg="green", bold=True)
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
            client.models.list(config={'page_size': 1})
            click.secho("✔ Gemini API: Connected and Authorized", fg="green")
        except Exception as e:
            click.secho(f"✘ Gemini API: Failed - {str(e)}", fg="red")

    # 2. GitHub Check
    app_id = os.getenv("GITHUB_APP_ID")
    pat = os.getenv("GITHUB_TOKEN")
    
    try:
        if app_id:
            private_key = os.getenv("GITHUB_PRIVATE_KEY", "").replace('\\n', '\n')
            auth = Auth.AppAuth(app_id, private_key)
            g = Github(auth=auth)
            # We can't easily test 'AppAuth' without an installation ID, but we can check the JWT
            g.get_app() 
            click.secho("✔ GitHub App: Authentication Successful", fg="green")
        elif pat:
            auth = Auth.Token(pat)
            g = Github(auth=auth)
            user = g.get_user().login
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
        "hook": {
            "type": "App",
            "id": 123456789,
            "active": True,
            "events": ["pull_request"]
        }
    }
    body = json.dumps(payload)
    
    # Generate HMAC signature
    signature = "sha256=" + hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    
    headers = {
        "X-Hub-Signature-256": signature,
        "Content-Type": "application/json",
        "X-GitHub-Event": "ping"
    }
    
    click.echo(f"Sending test 'ping' to {config['url']}/webhook...")
    try:
        response = httpx.post(f"{config['url']}/webhook", content=body, headers=headers)
        if response.status_code == 200:
            click.secho(f"✔ Success: Signature verified. Server responded: {response.json().get('message')}", fg="green")
        else:
            click.secho(f"✘ Failed: Server returned {response.status_code} - {response.text}", fg="red")
    except Exception as e:
        click.secho(f"✘ Error connecting to server: {str(e)}", fg="red")

@cli.command()
def list():
    """List Gemini models suitable for code review."""
    config = load_client_config()
    headers = {"X-Admin-Token": config["token"]}
    
    try:
        response = httpx.get(f"{config['url']}/api/models", headers=headers, timeout=10.0)
        response.raise_for_status()
        data = response.json()
        
        click.echo(f"\n{'DISPLAY NAME':<35} | {'MODEL ID':<45}")
        click.echo("-" * 85)
        
        for m in data.get("models", []):
            click.echo(f"{m['display_name']:<35} | {m['model_id']:<45}")
            
        click.echo(f"\nTotal: {data.get('count', 0)} models found.")
    except Exception as e:
        click.secho(f"Error: {str(e)}", fg="red")

@cli.command()
@click.argument("model_id")
def set(model_id):
    """Switch the active Gemini model for reviews."""
    config = load_client_config()
    headers = {"X-Admin-Token": config["token"]}
    payload = {"model_name": model_id}
    
    try:
        response = httpx.post(f"{config['url']}/api/models/active", headers=headers, json=payload)
        response.raise_for_status()
        click.secho(f"✔ Successfully switched to {model_id}", fg="green")
    except Exception as e:
        click.secho(f"Error: {str(e)}", fg="red")

@cli.command()
def status():
    """Check server connection and show active model."""
    config = load_client_config()
    url = config['url']
    headers = {"X-Admin-Token": config["token"]}
    
    click.echo(f"Checking connection to {url}...")
    try:
        response = httpx.get(f"{url}/api/models/active", headers=headers, timeout=5.0)
        if response.status_code == 200:
            data = response.json()
            click.secho(f"✔ Server Status: Online", fg="green")
            click.echo(f"Active Model  : {data.get('active_model')}")
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

if __name__ == "__main__":
    cli()
