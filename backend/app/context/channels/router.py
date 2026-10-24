"""FastAPI endpoints for Telegram, WhatsApp, and Gmail channel operations."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import PlainTextResponse

from .manager import ChannelManager, get_channel_manager
from .whatsapp import InvalidSignatureError, WebhookVerificationError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/channels", tags=["P1 Real Inbound Channels"])


def get_manager() -> ChannelManager:
    return get_channel_manager()


# --- Channel Status & Trigger ---

@router.get("/status")
def channel_status(manager: ChannelManager = Depends(get_manager)) -> dict[str, Any]:
    """Retrieve current operational and readiness status for Telegram, Gmail, and WhatsApp."""
    return manager.get_status()


@router.post("/poll")
def trigger_poll(manager: ChannelManager = Depends(get_manager)) -> dict[str, Any]:
    """Trigger an immediate synchronous poll cycle across all configured polling channels."""
    return manager.poll_all_now()


# --- Telegram Endpoints ---

@router.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    manager: ChannelManager = Depends(get_manager),
    x_telegram_bot_api_secret_token: Annotated[str | None, Header(alias="X-Telegram-Bot-Api-Secret-Token")] = None,
) -> dict[str, Any]:
    """Receive Telegram Bot API webhook updates."""
    # Verify secret token if configured
    expected_secret = manager.config.telegram.webhook_secret
    if expected_secret:
        if not x_telegram_bot_api_secret_token or x_telegram_bot_api_secret_token != expected_secret:
            raise HTTPException(status_code=403, detail="Invalid Telegram secret token")

    try:
        update = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    if not isinstance(update, dict):
        raise HTTPException(status_code=422, detail="Update must be a JSON object")

    result = manager.telegram.process_update(update)
    return {
        "ok": True,
        "processed": result is not None,
        "duplicate": result.duplicate if result else False,
        "message_id": result.message.message_id if result else None,
    }


# --- WhatsApp Cloud API Endpoints ---

@router.get("/whatsapp/webhook", response_class=PlainTextResponse)
def whatsapp_webhook_verification(
    hub_mode: Annotated[str | None, Query(alias="hub.mode")] = None,
    hub_verify_token: Annotated[str | None, Query(alias="hub.verify_token")] = None,
    hub_challenge: Annotated[str | None, Query(alias="hub.challenge")] = None,
    manager: ChannelManager = Depends(get_manager),
) -> str:
    """Meta webhook verification endpoint. Responds with hub.challenge if token matches."""
    try:
        challenge = manager.whatsapp.verify_challenge(hub_mode, hub_verify_token, hub_challenge)
        return challenge
    except WebhookVerificationError as exc:
        logger.warning("WhatsApp webhook challenge verification rejected: %s", exc)
        raise HTTPException(status_code=403, detail=str(exc))


@router.post("/whatsapp/webhook")
async def whatsapp_webhook_notification(
    request: Request,
    manager: ChannelManager = Depends(get_manager),
    x_hub_signature_256: Annotated[str | None, Header(alias="X-Hub-Signature-256")] = None,
) -> dict[str, Any]:
    """Receive incoming WhatsApp Cloud API webhook notifications with HMAC-SHA256 signature verification."""
    raw_body = await request.body()
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    try:
        results = manager.whatsapp.handle_webhook_event(raw_body, x_hub_signature_256, payload)
        return {
            "status": "success",
            "received_count": len(results),
            "processed": [
                {"message_id": r.message.message_id, "duplicate": r.duplicate}
                for r in results
            ],
        }
    except InvalidSignatureError as exc:
        logger.warning("WhatsApp webhook signature validation failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid HMAC-SHA256 signature")
    except Exception as exc:
        logger.error("Error processing WhatsApp webhook event: %s", exc)
        raise HTTPException(status_code=500, detail=f"Webhook processing error: {exc}")


# --- Gmail OAuth Endpoints ---

@router.get("/gmail/oauth/authorize")
def gmail_oauth_authorize(
    state: str | None = None,
    manager: ChannelManager = Depends(get_manager),
) -> dict[str, str]:
    """Generate and return Google OAuth authorization consent URL."""
    try:
        url = manager.gmail.get_authorization_url(state=state)
        return {"authorization_url": url}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/gmail/verify")
def gmail_verify(manager: ChannelManager = Depends(get_manager)) -> dict[str, Any]:
    """Safely verify authenticated Gmail account identity and OAuth status."""
    try:
        return manager.gmail.verify_connection()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/gmail/oauth/callback")
def gmail_oauth_callback(
    code: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
    manager: ChannelManager = Depends(get_manager),
) -> dict[str, Any]:
    """Handle Google OAuth callback, exchange code for refresh/access tokens, and persist credentials."""
    if error:
        raise HTTPException(status_code=400, detail=f"Google OAuth authorization denied: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing OAuth authorization code")

    try:
        token_data = manager.gmail.exchange_code(code)
        try:
            manager.gmail.start_polling()
        except Exception as poll_exc:
            logger.warning("Could not automatically start Gmail polling worker: %s", poll_exc)
        return {
            "status": "success",
            "message": "Gmail OAuth credentials successfully configured and saved.",
            "has_refresh_token": "refresh_token" in token_data,
        }
    except Exception as exc:
        logger.error("Gmail OAuth token exchange failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Token exchange failed: {exc}")
