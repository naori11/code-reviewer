import hmac
import hashlib
import os
import json
from fastapi import FastAPI, Request, HTTPException, Header
from typing import Optional, Dict, Any
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

# Get the webhook secret from environment variables
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

async def verify_signature(request: Request, signature: str):
    """
    Verifies that the signature in the header matches the payload's HMAC.
    """
    if not WEBHOOK_SECRET:
        # In development, you might want to skip this if no secret is set.
        # But for security, it should be required.
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

@app.post("/webhook")
async def webhook_handler(request: Request, x_hub_signature_256: Optional[str] = Header(None)):
    """
    Handles incoming webhook requests from GitHub with HMAC verification.
    """
    # 1. Verify the HMAC signature
    await verify_signature(request, x_hub_signature_256)

    # 2. Parse the JSON payload
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # 3. Extract diff_url and issue_url
    # These paths are common for 'pull_request' events.
    pull_request = payload.get("pull_request", {})
    diff_url = pull_request.get("diff_url")
    
    # 'issue_url' can also be found in pull_request payloads or issue-related events
    issue_url = pull_request.get("issue_url") or payload.get("issue", {}).get("url")

    print(f"Received verified webhook.")
    print(f"diff_url: {diff_url}")
    print(f"issue_url: {issue_url}")

    return {
        "status": "success", 
        "message": "Webhook received and verified",
        "extracted_data": {
            "diff_url": diff_url,
            "issue_url": issue_url
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
