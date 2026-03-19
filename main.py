import hmac
import hashlib
import os
import json
import requests
import google.generativeai as genai
from fastapi import FastAPI, Request, HTTPException, Header
from typing import Optional, Dict, Any
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# Configuration
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN") # Optional: For private repos

# Initialize Gemini
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
else:
    print("Warning: GEMINI_API_KEY not found in environment variables.")

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

def download_diff(diff_url: str) -> str:
    """
    Downloads the raw diff content from the provided URL.
    """
    headers = {}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    
    response = requests.get(diff_url, headers=headers)
    if response.status_code == 200:
        return response.text
    else:
        print(f"Failed to download diff: {response.status_code} - {response.text}")
        return ""

def get_gemini_review(diff_content: str) -> str:
    """
    Sends the diff content to Gemini for review with a custom prompt.
    """
    if not GEMINI_API_KEY:
        return "Gemini API key not configured."

    # --- CUSTOM PROMPT FOR INSTRUCTIONS ---
    prompt_instructions = """Review this code as a senior developer:

        [Paste your code or diff]

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
        response = model.generate_content(full_prompt)
        return response.text
    except Exception as e:
        return f"Error calling Gemini API: {str(e)}"

@app.post("/webhook")
async def webhook_handler(request: Request, x_hub_signature_256: Optional[str] = Header(None)):
    """
    Handles incoming webhook requests from GitHub, downloads diffs, and gets Gemini reviews.
    """
    # 1. Verify the HMAC signature
    await verify_signature(request, x_hub_signature_256)

    # 2. Parse the JSON payload
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # 3. Process Pull Request events
    action = payload.get("action")
    pull_request = payload.get("pull_request")
    
    if pull_request and action in ["opened", "synchronize"]:
        diff_url = pull_request.get("diff_url")
        issue_url = pull_request.get("issue_url") or payload.get("issue", {}).get("url")

        print(f"Processing PR: {pull_request.get('html_url')}")
        
        if diff_url:
            print(f"Downloading diff from: {diff_url}")
            diff_content = download_diff(diff_url)
            
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
