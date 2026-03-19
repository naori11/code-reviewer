from fastapi import FastAPI
from pydantic import BaseModel
from typing import Dict, Any

app = FastAPI()

class WebhookPayload(BaseModel):
    # GitHub payloads are complex; using a generic structure to avoid 422 errors
    pass

@app.post("/webhook")
async def webhook_handler(payload: Dict[str, Any]):
    """
    Handles incoming webhook requests from GitHub.
    """
    # Log or process the payload here if needed
    print(f"Received webhook: {payload}")
    return {"status": "success", "message": "Webhook received successfully"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
