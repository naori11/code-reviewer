from fastapi import FastAPI
from pydantic import BaseModel
from typing import Dict, Any

app = FastAPI()

class WebhookPayload(BaseModel):
    event: str
    data: Dict[str, Any]

@app.post("/webhook")
async def webhook_handler(payload: WebhookPayload):
    """
    Handles incoming webhook requests.
    """
    # Simply returns a success message as requested
    return {"status": "success", "message": "Webhook received successfully"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
