"""FastAPI endpoints for Telegram, WhatsApp, and Gmail channel operations."""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from .manager import ChannelManager, get_channel_manager
from .resend import ResendProviderUnavailable, ResendWebhookError
from .whatsapp import InvalidSignatureError, WebhookVerificationError, WhatsAppWebhookError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/channels", tags=["P1 Real Inbound Channels"])
MAX_WEBHOOK_BODY_BYTES = 2 * 1024 * 1024


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
    if not manager.telegram.validate_webhook_secret(x_telegram_bot_api_secret_token):
        raise HTTPException(status_code=403, detail="Invalid Telegram webhook authentication")

    raw_body = await request.body()
    if len(raw_body) > MAX_WEBHOOK_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Telegram webhook body exceeds the supported size")

    try:
        update = json.loads(raw_body)
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
        logger.warning("WhatsApp webhook challenge verification rejected (%s)", type(exc).__name__)
        raise HTTPException(status_code=403, detail="WhatsApp webhook verification failed")


@router.post("/whatsapp/webhook")
async def whatsapp_webhook_notification(
    request: Request,
    manager: ChannelManager = Depends(get_manager),
    x_hub_signature_256: Annotated[str | None, Header(alias="X-Hub-Signature-256")] = None,
) -> dict[str, Any]:
    """Receive incoming WhatsApp Cloud API webhook notifications with HMAC-SHA256 signature verification."""
    raw_body = await request.body()
    if len(raw_body) > MAX_WEBHOOK_BODY_BYTES:
        raise HTTPException(status_code=413, detail="WhatsApp webhook body exceeds the supported size")
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    try:
        results = manager.whatsapp.handle_webhook_event(raw_body, x_hub_signature_256, payload)
        statuses = manager.whatsapp.parse_status_callbacks(payload)
        return {
            "status": "success",
            "received_count": len(results),
            "provider_status_count": len(statuses),
            "provider_statuses": [
                {"provider_message_id": s.provider_message_id, "state": s.state,
                 "occurred_at": s.occurred_at, "error_code": s.error_code}
                for s in statuses
            ],
            "processed": [
                {"message_id": r.message.message_id, "duplicate": r.duplicate}
                for r in results
            ],
        }
    except InvalidSignatureError as exc:
        logger.warning("WhatsApp webhook signature validation failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=401, detail="Invalid HMAC-SHA256 signature")
    except WhatsAppWebhookError:
        logger.warning("WhatsApp webhook account validation failed")
        raise HTTPException(status_code=403, detail="WhatsApp webhook account is not configured for this tenant")
    except Exception as exc:
        logger.error("Error processing WhatsApp webhook event (%s)", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Webhook processing failed")


@router.post("/resend/webhook")
async def resend_webhook(
    request: Request,
    manager: ChannelManager = Depends(get_manager),
    svix_id: Annotated[str | None, Header(alias="svix-id")] = None,
    svix_timestamp: Annotated[str | None, Header(alias="svix-timestamp")] = None,
    svix_signature: Annotated[str | None, Header(alias="svix-signature")] = None,
) -> dict[str, Any]:
    """Accept signed Resend email.received events and persist through the existing P1 repository."""
    raw_body = await request.body()
    if len(raw_body) > MAX_WEBHOOK_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Resend webhook body exceeds the supported size")
    headers = {key: value for key, value in {
        "svix-id": svix_id, "svix-timestamp": svix_timestamp, "svix-signature": svix_signature,
    }.items() if value is not None}
    try:
        manager.resend.verify_webhook(raw_body, headers)
        try:
            event_preview = json.loads(raw_body)
        except (ValueError, UnicodeDecodeError):
            raise ResendWebhookError("Resend webhook body is invalid JSON")
        if isinstance(event_preview, dict) and event_preview.get("type") == "email.received":
            result = manager.resend.ingest_received_event(raw_body, headers, signature_verified=True)
            return {"status": "accepted", "processed": result is not None,
                    "duplicate": result.duplicate if result else False,
                    "provider_message_id": result.message.raw.provider_message_id if result else None}
        status_receipt = manager.resend.parse_status_event(event_preview) if isinstance(event_preview, dict) else None
        if status_receipt:
            return {"status": "accepted", "provider_status": status_receipt.state,
                    "provider_message_id": status_receipt.provider_message_id,
                    "persisted": False}
        return {"status": "ignored", "reason": "unsupported_event"}
    except ResendProviderUnavailable:
        logger.warning("Resend API retrieval failed")
        raise HTTPException(status_code=503, detail="Resend inbound retrieval is temporarily unavailable")
    except ResendWebhookError as exc:
        detail = str(exc)
        status = 401 if "signature" in detail or "timestamp" in detail else 403 if "tenant inboxes" in detail else 400
        logger.warning("Resend webhook rejected (%s)", "SIGNATURE" if status == 401 else "PAYLOAD")
        raise HTTPException(status_code=status, detail="Resend webhook could not be verified or processed")
    except Exception as exc:
        logger.error("Resend inbound processing failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Resend inbound processing is temporarily unavailable")


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
        logger.warning("Gmail OAuth authorization URL generation failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=400, detail="Gmail OAuth is not configured")


@router.get("/gmail/verify")
def gmail_verify(manager: ChannelManager = Depends(get_manager)) -> dict[str, Any]:
    """Safely verify authenticated Gmail account identity and OAuth status."""
    try:
        return manager.gmail.verify_connection()
    except Exception as exc:
        logger.warning("Gmail verification failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Gmail provider verification failed")


@router.get("/gmail/oauth/callback")
def gmail_oauth_callback(
    code: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
    manager: ChannelManager = Depends(get_manager),
) -> dict[str, Any]:
    """Handle Google OAuth callback, exchange code for refresh/access tokens, and persist credentials."""
    if error:
        raise HTTPException(status_code=400, detail="Google OAuth authorization was denied")
    if not code:
        raise HTTPException(status_code=400, detail="Missing OAuth authorization code")

    try:
        token_data = manager.gmail.exchange_code(code)
        try:
            manager.gmail.start_polling()
        except Exception as poll_exc:
            logger.warning("Could not automatically start Gmail polling worker (%s)", type(poll_exc).__name__)
        return {
            "status": "success",
            "message": "Gmail OAuth credentials successfully configured and saved.",
            "has_refresh_token": "refresh_token" in token_data,
        }
    except Exception as exc:
        logger.error("Gmail OAuth token exchange failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Gmail OAuth token exchange failed")
