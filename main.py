import hmac
import hashlib
import os
import json
from google import genai
from fastapi import FastAPI, Request, HTTPException, Header
from typing import Optional, Dict, Any
from dotenv import load_dotenv
from github import Github, Auth

load_dotenv()

app = FastAPI()

# Configuration
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

# Initialize Gemini Client
client = None
if GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)
else:
    print("Warning: GEMINI_API_KEY not found in environment variables.")

# Initialize PyGithub
if GITHUB_TOKEN:
    auth = Auth.Token(GITHUB_TOKEN)
    g = Github(auth=auth)
else:
    g = None

async def verify_signature(request: Request, signature: str):
    """
    Verifies that the signature in the header matches the payload's HMAC.
    """
    if not WEBHOOK_SECRET:
        return

    if not signature:
        raise HTTPException(status_code=401, detail="X-Hub-Signature-256 header is missing")

    body = await request.body()
    
    try:
        sha_name, signature_hash = signature.split('=')
        if sha_name != 'sha256':
            raise HTTPException(status_code=401, detail="Unsupported signature algorithm")
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid signature format")

    mac = hmac.new(WEBHOOK_SECRET.encode(), msg=body, digestmod=hashlib.sha256)
    expected_signature = mac.hexdigest()

    if not hmac.compare_digest(expected_signature, signature_hash):
        raise HTTPException(status_code=401, detail="Invalid signature")

def download_diff(repo_full_name: str, pr_number: int) -> str:
    """
    Downloads the raw diff content using the GitHub API with a specialized Accept header.
    """
    if not GITHUB_TOKEN:
        print("Error: GITHUB_TOKEN is required.")
        return ""

    try:
        import requests
        url = f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}"

        headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3.diff"
        }

        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            return response.text
        else:
            print(f"Failed to fetch diff via API: {response.status_code}")
            try:
                print(f"Error details: {response.json()}")
            except:
                pass
            return ""

    except Exception as e:
        print(f"Error fetching diff: {str(e)}")
        return ""


def get_gemini_review(diff_content: str) -> str:
    """
    Sends the diff content to Gemini for review with a custom prompt.
    """
    if not client:
        return "Gemini API client not configured."

    # --- CUSTOM PROMPT FOR INSTRUCTIONS ---
    prompt_instructions = """Review this code as a senior developer:

        Check for:
        1. Bugs: Logic errors, off-by-one, null handling, race conditions
        2. Security: Injection risks, auth issues, data exposure
        3. Performance: N+1 queries, unnecessary loops, memory leaks
        4. Maintainability: Naming, complexity, duplication
        5. Edge cases: What inputs would break this?

        For each issue:
        - Severity: Critical / High / Medium / Low
        - Line number or section
        - What's wrong
        - How to fix it

        Be harsh. I'd rather fix issues now than in production.
        """
    # ---------------------------------------

    full_prompt = f"{prompt_instructions}\n\nCode Diff:\n{diff_content}"
    
    try:
        # Using the new google-genai SDK format
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=full_prompt
        )
        return response.text
    except Exception as e:
        return f"Error calling Gemini API: {str(e)}"

@app.post("/webhook")
async def webhook_handler(request: Request, x_hub_signature_256: Optional[str] = Header(None)):
    """
    Handles incoming webhook requests from GitHub, downloads diffs, and gets Gemini reviews.
    """
    await verify_signature(request, x_hub_signature_256)

    try:
        payload = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    action = payload.get("action")
    pull_request = payload.get("pull_request")
    
    if pull_request and action in ["opened", "synchronize", "reopened"]:
        repo_full_name = payload.get("repository", {}).get("full_name")
        pr_number = pull_request.get("number")

        print(f"Processing PR #{pr_number} in {repo_full_name}")
        
        if repo_full_name and pr_number:
            print(f"Fetching diff for PR #{pr_number}...")
            diff_content = download_diff(repo_full_name, pr_number)
            
            if diff_content:
                print("Getting Gemini review...")
                review = get_gemini_review(diff_content)
                
                print("\n--- GEMINI API RESPONSE ---")
                print(review)
                print("---------------------------\n")
                
                return {
                    "status": "success",
                    "message": "Webhook processed and review generated",
                    "review_preview": review[:100] + "..." if len(review) > 100 else review
                }

    return {"status": "success", "message": "Webhook received, no PR action taken"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
