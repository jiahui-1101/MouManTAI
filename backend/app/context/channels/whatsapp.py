"""P1 Meta WhatsApp Cloud API Inbound Webhook Adapter.

Supports:
- Webhook GET challenge verification (hub.mode, hub.verify_token, hub.challenge).
- Webhook POST request signature verification using HMAC-SHA256 (X-Hub-Signature-256) and app_secret.
- WhatsApp Cloud API payload parsing:
  - Contacts mapping (wa_id to customer name).
  - Text messages (text.body).
  - Media messages (image, document, audio, video) with secure Graph API media retrieval.
  - Attachment validation and persistence into P1 attachment store.
  - Non-message webhook events (statuses, delivery receipts, read receipts) safely ignored without false ingestion.
- Tenant isolation and server-controlled tenant mapping.
- Provider message ID deduplication (wamid).
- Direct handoff into P1 IngestionService and AI pipeline.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import httpx

from app.context.attachment_validator import validate_attachment
from app.context.document_schemas import AttachmentRecord
from app.context.ingestion import IngestionService
from app.context.ingestion_schemas import IngestResponse
from app.context.repository import MessageRepository
from app.context.schemas import Attachment, RawMessageEnvelope

from .config import WhatsAppChannelConfig
from .reply_framing import FramingError, verify_whatsapp_signature, whatsapp_frame
from .state import ChannelStateManager, get_state_manager

logger = logging.getLogger(__name__)


class WhatsAppWebhookError(Exception):
    """Base error for WhatsApp webhook failures."""


class InvalidSignatureError(WhatsAppWebhookError):
    """Raised when X-Hub-Signature-256 is missing or invalid."""


class InvalidWhatsAppAccountError(WhatsAppWebhookError):
    """A signed callback belongs to a different business phone account."""


class WebhookVerificationError(WhatsAppWebhookError):
    """Raised when GET verification challenge fails."""


class WhatsAppAdapter:
    """Production-ready inbound adapter for Meta WhatsApp Cloud API."""

    def __init__(
        self,
        config: WhatsAppChannelConfig,
        repository: MessageRepository,
        state_manager: ChannelStateManager | None = None,
        http_client: httpx.Client | None = None,
        clock: Any = None,
    ):
        self.config = config
        self.repository = repository
        self.state_manager = state_manager or get_state_manager()
        self._custom_client = http_client
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.ingestion_service = IngestionService(repository, clock=self._clock)

    def _get_client(self) -> httpx.Client:
        if self._custom_client is not None:
            return self._custom_client
        return httpx.Client(timeout=30.0)

    # --- Webhook Verification (GET) ---

    def verify_challenge(self, mode: str | None, verify_token: str | None, challenge: str | None) -> str:
        """Handle Meta Webhook verification handshake."""
        if not self.config.can_verify_webhook:
            raise WebhookVerificationError("WHATSAPP_VERIFY_TOKEN is not configured")

        if mode != "subscribe":
            raise WebhookVerificationError(f"Unsupported hub.mode '{mode}'; expected 'subscribe'")

        if not verify_token or verify_token != self.config.verify_token:
            raise WebhookVerificationError("Invalid hub.verify_token")

        if not challenge:
            raise WebhookVerificationError("Missing hub.challenge parameter")

        self.state_manager.set_status("WHATSAPP", self.config.tenant_id, "WEBHOOK_VERIFIED")
        logger.info("Meta WhatsApp webhook challenge verified successfully for tenant %s", self.config.tenant_id)
        return challenge

    # --- HMAC-SHA256 Signature Validation (POST) ---

    def validate_signature(self, raw_body: bytes, signature_header: str | None) -> bool:
        """Validate that incoming webhook payload was signed by Meta using app_secret."""
        if not self.config.app_secret:
            raise InvalidSignatureError("WHATSAPP_APP_SECRET is not configured; cannot validate signature")
        if not signature_header:
            raise InvalidSignatureError("Missing X-Hub-Signature-256 header")
        if not signature_header.startswith("sha256="):
            raise InvalidSignatureError("Invalid signature format; expected 'sha256=...'")
        try:
            verify_whatsapp_signature(raw_body, signature_header, self.config.app_secret)
            return True
        except FramingError:
            raise InvalidSignatureError("HMAC-SHA256 signature mismatch; request untrusted") from None

    # --- Media Retrieval via Graph API ---

    def download_media(self, media_id: str) -> tuple[bytes, str, str]:
        """Fetch media URL from Graph API, download binary data, and return (content, mime, filename)."""
        if not self.config.access_token:
            raise WhatsAppWebhookError("WHATSAPP_ACCESS_TOKEN is required to download media")

        client = self._get_client()
        headers = {"Authorization": f"Bearer {self.config.access_token}"}
        url = f"{self.config.api_base_url.rstrip('/')}/{media_id}"

        # 1. Fetch media metadata URL
        resp = client.get(url, headers=headers)
        if not resp.is_success:
            raise WhatsAppWebhookError(f"Failed fetching media metadata for {media_id}: {resp.text}")

        meta = resp.json()
        download_url = meta.get("url")
        declared_mime = meta.get("mime_type", "")
        if not download_url:
            raise WhatsAppWebhookError(f"No download URL returned for media {media_id}")

        # 2. Download binary content using the same bearer token
        media_resp = client.get(download_url, headers=headers)
        if not media_resp.is_success:
            raise WhatsAppWebhookError(f"Failed downloading media binary from {download_url}: {media_resp.status_code}")

        content = media_resp.content
        filename = f"whatsapp_media_{media_id}"
        return content, declared_mime, filename

    # --- Webhook Notification Processing ---

    def parse_webhook_payload(
        self, payload: dict[str, Any], *, correlation_id: str | None = None
    ) -> list[RawMessageEnvelope]:
        """Traverse WhatsApp Cloud API payload and extract canonical RawMessageEnvelopes.

        Safely handles non-message callbacks (status receipts: sent, delivered, read)
        without raising errors or creating artificial messages.
        """
        envelopes: list[RawMessageEnvelope] = []
        received_at = self._clock()

        entries = payload.get("entry", [])
        if not isinstance(entries, list):
            return envelopes

        for entry in entries:
            changes = entry.get("changes", [])
            if not isinstance(changes, list):
                continue

            for change in changes:
                if change.get("field") != "messages":
                    continue

                value = change.get("value", {})
                if not isinstance(value, dict):
                    continue
                metadata = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
                callback_account_id = metadata.get("phone_number_id")
                if not self.config.phone_number_id or callback_account_id != self.config.phone_number_id:
                    raise InvalidWhatsAppAccountError("WhatsApp callback phone account does not match server configuration")

                # Delivery statuses (sent, delivered, read) - do not ingest as inbound messages
                if "statuses" in value and not value.get("messages"):
                    logger.debug("Received WhatsApp delivery status callback: %s", value.get("statuses"))
                    continue

                # Contacts lookup for sender aliases
                contacts_map: dict[str, str] = {}
                for contact in value.get("contacts", []):
                    wa_id = str(contact.get("wa_id", ""))
                    name = contact.get("profile", {}).get("name")
                    if wa_id and name:
                        contacts_map[wa_id] = name

                messages = value.get("messages", [])
                if not isinstance(messages, list):
                    continue

                for msg in messages:
                    msg_id = msg.get("id")
                    if not msg_id:
                        continue

                    frame = None
                    framing_error = None
                    try:
                        frame = whatsapp_frame(
                            msg,
                            tenant_id=self.config.tenant_id,
                            account_id=self.config.phone_number_id or "",
                            callback_account_id=callback_account_id,
                        )
                    except FramingError as exc:
                        framing_error = str(exc)

                    sender_id = str(msg.get("from", "unknown_wa_sender"))
                    sender_alias = contacts_map.get(sender_id, f"WhatsApp +{sender_id}")

                    raw_ts = msg.get("timestamp")
                    if raw_ts:
                        message_at = datetime.fromtimestamp(int(raw_ts), tz=timezone.utc)
                    else:
                        message_at = received_at

                    msg_type = msg.get("type", "")
                    text = ""
                    attachments: list[Attachment] = []

                    if msg_type == "text":
                        text = msg.get("text", {}).get("body", "").strip()

                    elif msg_type in ("image", "document", "audio", "video"):
                        media_data = msg.get(msg_type, {})
                        caption = media_data.get("caption", "").strip()
                        media_id = media_data.get("id")
                        declared_mime = media_data.get("mime_type")
                        ext_map = {
                            "image/jpeg": ".jpg",
                            "image/png": ".png",
                            "application/pdf": ".pdf",
                        }
                        default_ext = ext_map.get(declared_mime or "", ".jpg" if msg_type == "image" else ".pdf" if msg_type == "document" else ".bin")
                        filename = media_data.get("filename") or f"{msg_type}_{media_id}{default_ext}"

                        if media_id:
                            try:
                                content, detected_mime, default_name = self.download_media(media_id)
                                target_name = filename or default_name
                                valid_mime, clean_name = validate_attachment(target_name, content, declared_mime)

                                att_id = f"att_wa_{uuid4().hex[:12]}"
                                ev_ref = f"ev_wa_{uuid4().hex[:12]}"
                                sha256 = hashlib.sha256(content).hexdigest()

                                record = AttachmentRecord(
                                    attachment_id=att_id,
                                    tenant_id=self.config.tenant_id,
                                    evidence_ref=ev_ref,
                                    filename=clean_name,
                                    media_type=valid_mime,
                                    size_bytes=len(content),
                                    content_sha256=sha256,
                                    created_at=received_at,
                                )
                                self.repository.save_attachment(self.config.tenant_id, record, content)

                                attachments.append(
                                    Attachment(
                                        attachment_id=att_id,
                                        filename=clean_name,
                                        media_type=valid_mime,
                                        size_bytes=len(content),
                                        evidence_ref=ev_ref,
                                    )
                                )
                            except Exception as exc:
                                logger.warning("Failed processing WhatsApp media %s: %s", media_id, exc)

                        text = caption if caption else (
                            f"[WhatsApp {msg_type.title()} Attachment: {attachments[0].filename}]"
                            if attachments else f"[WhatsApp {msg_type.title()}]"
                        )

                    elif msg_type in ("interactive", "button"):
                        # E.g. quick reply button or list reply
                        interactive = msg.get("interactive", {})
                        reply = interactive.get("button_reply", {}) or interactive.get("list_reply", {})
                        text = reply.get("title", reply.get("id", f"[{msg_type} response]"))

                    else:
                        logger.info("Unsupported WhatsApp message type '%s'; skipping", msg_type)
                        continue

                    if not text:
                        continue

                    envelope = RawMessageEnvelope(
                        tenant_id=self.config.tenant_id,
                        channel="WHATSAPP",
                        provider_message_id=msg_id,
                        provider_account_id=self.config.phone_number_id,
                        provider_native_message_id=str(msg_id) if self.config.phone_number_id else None,
                        sender_identity_id=frame.sender_id if frame else sender_id,
                        sender_alias=sender_alias,
                        received_at=received_at,
                        message_at=message_at,
                        text=text,
                        attachments=attachments,
                        thread_ref=frame.conversation_id if frame else sender_id,
                        conversation_id=frame.conversation_id if frame else sender_id,
                        reply_to_provider_message_id=(frame.exact_parent_id if frame else (
                            msg.get("context", {}).get("id") if isinstance(msg.get("context"), dict) else None
                        )),
                        native_attachment_source_ids=list(frame.attachment_source_ids) if frame else [],
                        relationship_source=frame.relationship_source if frame else "UNKNOWN",
                        source_authenticity="UNVERIFIED",
                        correlation_id=correlation_id,
                        framing_error=framing_error,
                        adapter_mode="REAL",
                    )
                    envelopes.append(envelope)

        return envelopes

    def handle_webhook_event(
        self,
        raw_body: bytes,
        signature_header: str | None,
        payload: dict[str, Any],
    ) -> list[IngestResponse]:
        """Validate signature, parse webhook payload, and ingest all messages into P1 pipeline."""
        # 1. Validate signature
        self.validate_signature(raw_body, signature_header)

        # 2. Parse envelopes
        callback_id = "whatsapp-callback:" + hashlib.sha256(raw_body).hexdigest()
        envelopes = self.parse_webhook_payload(payload, correlation_id=callback_id)
        responses: list[IngestResponse] = []

        # 3. Ingest each message
        for envelope in envelopes:
            envelope = envelope.model_copy(update={"source_authenticity": "VERIFIED"})
            result = self.ingestion_service.ingest(envelope, self.config.tenant_id)
            responses.append(result)

            # Auto-trigger extraction pipeline if newly received
            if not result.duplicate:
                try:
                    self.repository.process(self.config.tenant_id, result.message.message_id)
                except Exception as exc:
                    logger.warning("Automatic extraction on WhatsApp message %s failed: %s",
                                   result.message.message_id, exc)
                try:
                    from app.context.context_service import ContextService
                    ContextService(self.repository).create_or_update_from_message(
                        self.config.tenant_id, result.message.message_id
                    )
                except Exception as exc:
                    logger.warning("Automatic context creation for WhatsApp message %s failed: %s",
                                   result.message.message_id, exc)

        self.state_manager.record_poll_attempt("WHATSAPP", self.config.tenant_id)
        return responses
