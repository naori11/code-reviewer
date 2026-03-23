import hashlib
import hmac
from typing import Optional

from fastapi import Depends, Header, HTTPException

from .config import Settings, get_settings


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
    valid_tokens = [settings.webhook_secret]
    if settings.admin_api_key:
        valid_tokens.append(settings.admin_api_key)

    if not x_admin_token or x_admin_token not in valid_tokens:
        raise HTTPException(status_code=403, detail="Unauthorized admin access")

    return x_admin_token
