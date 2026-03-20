import click
import httpx
import json
import os
import secrets
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv, set_key

# Configuration setup for the CLI client
CONFIG_DIR = Path.home() / ".code_reviewer"
CONFIG_FILE = CONFIG_DIR / "config.json"

def save_client_config(url: str, token: str):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump({"url": url.rstrip("/"), "token": token}, f)

def load_client_config():
    if not CONFIG_FILE.exists():
        click.secho("Error: Client not initialized. Run 'python reviewer.py init' first.", fg="red")
        exit(1)
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

@click.group()
def cli():
    """Code Reviewer CLI - Manage your Gemini models and server setup."""
    pass

@cli.command()
@click.option("--url", prompt="Server URL (e.g., http://localhost:8000)", help="The URL of your FastAPI server.")
@click.option("--token", prompt="Admin Token (WEBHOOK_SECRET)", hide_input=True, help="Your server's Admin Token.")
def init(url, token):
    """Initialize the CLI client with server credentials."""
    save_client_config(url, token)
    click.secho(f"Successfully initialized! Configuration saved to {CONFIG_FILE}", fg="green")

@cli.command()
def setup_server():
    """Interactive wizard to configure your server's .env file."""
    click.secho("\n🚀 Code Reviewer Server Onboarding", fg="cyan", bold=True)
    click.echo("This wizard will help you configure your environment variables.\n")
    
    env_path = Path(".env")
    if not env_path.exists():
        if Path(".env.example").exists():
            import shutil
            shutil.copy(".env.example", ".env")
            click.echo("✔ Created .env from .env.example")
        else:
            env_path.touch()
            click.echo("✔ Created new .env file")

    # 1. Generate WEBHOOK_SECRET
    load_dotenv()
    current_secret = os.getenv("WEBHOOK_SECRET")
    if not current_secret:
        new_secret = secrets.token_hex(20)
        set_key(".env", "WEBHOOK_SECRET", new_secret)
        click.secho(f"✔ Generated new WEBHOOK_SECRET: {new_secret}", fg="green")
    else:
        click.echo("✔ WEBHOOK_SECRET already exists.")

    # 2. GEMINI_API_KEY
    click.echo("\n--- AI Configuration ---")
    click.echo("Get your API key from: https://aistudio.google.com/")
    gemini_key = click.prompt("Enter your GEMINI_API_KEY", default=os.getenv("GEMINI_API_KEY", ""))
    if gemini_key:
        set_key(".env", "GEMINI_API_KEY", gemini_key)

    # 3. GitHub Authentication
    click.echo("\n--- GitHub Authentication ---")
    auth_choice = click.prompt(
        "Which GitHub Auth method would you like to use?",
        type=click.Choice(['app', 'pat'], case_sensitive=False),
        default='app'
    )

    if auth_choice == 'app':
        click.echo("Setting up GitHub App (Recommended for security)...")
        app_id = click.prompt("Enter your GITHUB_APP_ID", default=os.getenv("GITHUB_APP_ID", ""))
        set_key(".env", "GITHUB_APP_ID", app_id)
        
        click.echo("Note: Paste the private key as a single line with '\\n' for newlines if possible.")
        private_key = click.prompt("Enter your GITHUB_PRIVATE_KEY", default=os.getenv("GITHUB_PRIVATE_KEY", ""))
        set_key(".env", "GITHUB_PRIVATE_KEY", private_key)
        
        # Clear PAT if switching to App
        set_key(".env", "GITHUB_TOKEN", "")
    else:
        click.echo("Setting up Personal Access Token (PAT)...")
        pat_token = click.prompt("Enter your GITHUB_TOKEN", default=os.getenv("GITHUB_TOKEN", ""))
        set_key(".env", "GITHUB_TOKEN", pat_token)
        
        # Clear App keys if switching to PAT
        set_key(".env", "GITHUB_APP_ID", "")
        set_key(".env", "GITHUB_PRIVATE_KEY", "")

    # Final Summary
    load_dotenv() # Reload to get the generated secret if it was new
    secret = os.getenv("WEBHOOK_SECRET")
    
    click.secho("\n✨ Setup Complete!", fg="green", bold=True)
    click.echo("-" * 40)
    click.echo("Next Steps for GitHub Webhook Configuration:")
    click.echo(f"1. Payload URL:  http://[your-server-ip]:8000/webhook")
    click.echo(f"2. Content type: application/json")
    click.echo(f"3. Secret:       {secret}")
    click.echo(f"4. Events:       Select 'Pull requests'")
    click.echo("-" * 40)
    click.echo("\nFinally, run 'python reviewer.py init' to connect this CLI to your server.")

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
        click.secho(f"Error fetching models: {str(e)}", fg="red")

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
        click.secho(f"Successfully switched to {model_id}", fg="green")
    except Exception as e:
        click.secho(f"Error setting model: {str(e)}", fg="red")

@cli.command()
def status():
    """Show the currently active Gemini model."""
    config = load_client_config()
    headers = {"X-Admin-Token": config["token"]}
    
    try:
        response = httpx.get(f"{config['url']}/api/models/active", headers=headers)
        response.raise_for_status()
        data = response.json()
        click.echo(f"Active Model: {data.get('active_model')}")
    except Exception as e:
        click.secho(f"Error fetching status: {str(e)}", fg="red")

if __name__ == "__main__":
    cli()
