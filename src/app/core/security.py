import hashlib
import hmac
import logging
from typing import Optional

from fastapi import Depends, Header, HTTPException

from .config import Settings, get_settings

logger = logging.getLogger(__name__)


def verify_webhook_signature(signature: Optional[str], raw_payload: bytes, settings: Settings) -> None:
    if not signature:
        raise HTTPException(status_code=401, detail="X-Hub-Signature-256 header is missing")

    try:
        sha_name, signature_hash = signature.split("=", 1)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid signature format") from exc

    if sha_name != "sha256":
        raise HTTPException(status_code=401, detail="Unsupported signature algorithm")

    mac = hmac.new(settings.webhook_secret.encode(), msg=raw_payload, digestmod=hashlib.sha256)
    expected_signature = mac.hexdigest()

    if not hmac.compare_digest(expected_signature, signature_hash):
        raise HTTPException(status_code=401, detail="Invalid signature")


async def verify_admin_token(
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
    settings: Settings = Depends(get_settings),
) -> str:
    if not settings.admin_api_key:
        logger.critical("ADMIN_API_KEY is not configured. Admin API access is disabled.")
        raise HTTPException(status_code=503, detail="Admin API is not configured.")

    if not x_admin_token or x_admin_token != settings.admin_api_key:
        logger.warning("Unauthorized admin API access attempt.")
        raise HTTPException(status_code=403, detail="Unauthorized admin access")

    return x_admin_token
