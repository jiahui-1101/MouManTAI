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
import hmac
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from app.context.attachment_validator import validate_attachment
from app.context.document_schemas import AttachmentRecord
from app.context.ingestion import IngestionService
from app.context.ingestion_schemas import IngestResponse
from app.context.repository import MessageRepository
from app.context.schemas import Attachment, RawMessageEnvelope

from .config import WhatsAppChannelConfig
from .provider_transport import (
    ProcessIdempotencyGate,
    ProviderSendResult,
    ProviderStatusReceipt,
    classify_http_status,
    read_limited_get,
    safe_get,
)
from .state import ChannelStateManager, get_state_manager

logger = logging.getLogger(__name__)


class WhatsAppWebhookError(Exception):
    """Base error for WhatsApp webhook failures."""


class InvalidSignatureError(WhatsAppWebhookError):
    """Raised when X-Hub-Signature-256 is missing or invalid."""


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
        self._send_gate = ProcessIdempotencyGate()

    def _get_client(self) -> httpx.Client:
        if self._custom_client is not None:
            return self._custom_client
        return httpx.Client(timeout=httpx.Timeout(self.config.request_timeout_seconds, connect=3.0), follow_redirects=False)

    # --- Webhook Verification (GET) ---

    def verify_challenge(self, mode: str | None, verify_token: str | None, challenge: str | None) -> str:
        """Handle Meta Webhook verification handshake."""
        if not self.config.can_verify_webhook:
            raise WebhookVerificationError("WHATSAPP_VERIFY_TOKEN is not configured")

        if mode != "subscribe":
            raise WebhookVerificationError(f"Unsupported hub.mode '{mode}'; expected 'subscribe'")

        if not verify_token or not hmac.compare_digest(verify_token, self.config.verify_token):
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

        actual_sig = signature_header[7:].strip()
        expected_sig = hmac.new(
            self.config.app_secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected_sig, actual_sig):
            raise InvalidSignatureError("HMAC-SHA256 signature mismatch; request untrusted")

        return True

    # --- Media Retrieval via Graph API ---

    def download_media(self, media_id: str) -> tuple[bytes, str, str]:
        """Fetch media URL from Graph API, download binary data, and return (content, mime, filename)."""
        if not self.config.access_token:
            raise WhatsAppWebhookError("WHATSAPP_ACCESS_TOKEN is required to download media")

        client = self._get_client()
        headers = {"Authorization": f"Bearer {self.config.access_token}"}
        url = f"{self.config.api_base_url.rstrip('/')}/{media_id}"

        # 1. Fetch media metadata URL
        resp = safe_get(client, url, headers=headers)
        if not resp.is_success:
            raise WhatsAppWebhookError("Failed fetching WhatsApp media metadata")

        meta = resp.json()
        download_url = meta.get("url")
        declared_mime = meta.get("mime_type", "")
        if not download_url:
            raise WhatsAppWebhookError(f"No download URL returned for media {media_id}")

        parsed_url = httpx.URL(download_url)
        if (parsed_url.scheme != "https" or parsed_url.host not in {"lookaside.fbsbx.com", "lookaside.instagram.com"}
                or parsed_url.port not in {None, 443} or parsed_url.username or parsed_url.password):
            raise WhatsAppWebhookError("WhatsApp returned a media URL outside the trusted Meta media hosts")

        # 2. Download binary content using the same bearer token
        status_code, content = read_limited_get(client, download_url, 10 * 1024 * 1024, headers=headers)
        if not 200 <= status_code < 300:
            raise WhatsAppWebhookError("Failed downloading WhatsApp media binary")
        filename = f"whatsapp_media_{media_id}"
        return content, declared_mime, filename

    @staticmethod
    def _normalized_recipient(recipient: str) -> str:
        return re.sub(r"\D", "", recipient)

    def _validate_outbound_recipient(self, recipient: str) -> str:
        normalized = self._normalized_recipient(recipient)
        allowed = {self._normalized_recipient(value) for value in self.config.test_recipient_ids}
        if not self.config.outbound_enabled or not self.config.is_configured:
            raise WhatsAppWebhookError("WhatsApp outbound transport is disabled or unconfigured")
        if not normalized or normalized not in allowed:
            raise WhatsAppWebhookError("WhatsApp recipient is not in the configured test recipient allowlist")
        return normalized

    def send_text(self, recipient: str, text: str, *, idempotency_key: str,
                  service_window_expires_at: datetime | None = None,
                  reply_to_message_id: str | None = None) -> ProviderSendResult:
        """Send inside a current service window; for outside it, use an approved template."""
        recipient_id = self._validate_outbound_recipient(recipient)
        if not text.strip() or len(text) > 4096:
            raise WhatsAppWebhookError("WhatsApp message text is empty or exceeds the provider limit")
        now = self._clock()
        if (service_window_expires_at is None or service_window_expires_at.tzinfo is None
                or service_window_expires_at <= now):
            raise WhatsAppWebhookError("WhatsApp customer service window is not currently open")
        payload: dict[str, Any] = {"messaging_product": "whatsapp", "recipient_type": "individual",
            "to": recipient_id, "type": "text", "text": {"preview_url": False, "body": text},
            "biz_opaque_callback_data": str(idempotency_key)}
        if reply_to_message_id:
            payload["context"] = {"message_id": reply_to_message_id}
        return self._submit_outbound(payload, idempotency_key)

    def send_template(self, recipient: str, template_name: str, language_code: str, *,
                      idempotency_key: str, components: list[dict[str, Any]] | None = None) -> ProviderSendResult:
        """Send a named pre-approved template to an explicitly allowlisted test recipient."""
        recipient_id = self._validate_outbound_recipient(recipient)
        if not re.fullmatch(r"[a-z0-9_]{1,128}", template_name) or not re.fullmatch(r"[a-z]{2,3}(?:_[A-Z]{2})?", language_code):
            raise WhatsAppWebhookError("WhatsApp template name or language code is invalid")
        if template_name not in set(self.config.approved_templates):
            raise WhatsAppWebhookError("WhatsApp template is not in the configured approved template allowlist")
        payload: dict[str, Any] = {"messaging_product": "whatsapp", "to": recipient_id, "type": "template",
            "template": {"name": template_name, "language": {"code": language_code}}}
        if components:
            payload["template"]["components"] = components
        payload["biz_opaque_callback_data"] = str(idempotency_key)
        return self._submit_outbound(payload, idempotency_key)

    def _submit_outbound(self, payload: dict[str, Any], key: str) -> ProviderSendResult:
        if not self.config.phone_number_id or not self.config.access_token:
            raise WhatsAppWebhookError("WhatsApp phone number id and access token are required")
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

        def submit() -> ProviderSendResult:
            try:
                response = self._get_client().post(
                    f"{self.config.api_base_url.rstrip('/')}/{self.config.phone_number_id}/messages",
                    headers={"Authorization": f"Bearer {self.config.access_token}"}, json=payload)
            except httpx.TimeoutException:
                return ProviderSendResult("WHATSAPP", "UNKNOWN", error_class="UNKNOWN",
                    error_code="PROVIDER_TIMEOUT", idempotency_key=key)
            except httpx.RequestError:
                return ProviderSendResult("WHATSAPP", "UNKNOWN", error_class="UNKNOWN",
                    error_code="PROVIDER_CONNECTION_ERROR", idempotency_key=key)
            state, error_class, error_code = classify_http_status(response.status_code)
            try:
                data = response.json()
            except ValueError:
                data = {}
            if state == "ACCEPTED" and data.get("messages"):
                return ProviderSendResult("WHATSAPP", "ACCEPTED", data["messages"][0].get("id"),
                    provider_status="ACCEPTED", idempotency_key=key)
            if state == "ACCEPTED":
                state, error_class, error_code = "UNKNOWN", "UNKNOWN", "PROVIDER_RESPONSE_INVALID"
            return ProviderSendResult("WHATSAPP", state, provider_status=str(response.status_code),
                error_class=error_class, error_code=error_code, idempotency_key=key)

        try:
            return self._send_gate.execute(str(key), fingerprint, submit)
        except ValueError as exc:
            raise WhatsAppWebhookError(str(exc)) from exc

    def parse_status_callbacks(self, payload: dict[str, Any]) -> list[ProviderStatusReceipt]:
        """Normalize signed delivery callbacks without inventing durable status storage."""
        state_map = {"sent": "SENT", "delivered": "DELIVERED", "read": "READ", "failed": "FAILED"}
        receipts: list[ProviderStatusReceipt] = []
        for entry in payload.get("entry", []) if isinstance(payload.get("entry", []), list) else []:
            for change in entry.get("changes", []) if isinstance(entry.get("changes", []), list) else []:
                if change.get("field") != "messages":
                    continue
                value = change.get("value", {})
                self._validate_account_metadata(value)
                for status in value.get("statuses", []) if isinstance(value.get("statuses", []), list) else []:
                    provider_id = status.get("id")
                    if not provider_id:
                        continue
                    name = str(status.get("status", "")).lower()
                    try:
                        occurred = datetime.fromtimestamp(int(status.get("timestamp")), tz=timezone.utc).isoformat()
                    except (TypeError, ValueError, OSError):
                        occurred = None
                    receipts.append(ProviderStatusReceipt("WHATSAPP", self.config.tenant_id,
                        str(provider_id), state_map.get(name, "UNKNOWN"), occurred,
                        "PROVIDER_DELIVERY_FAILED" if name == "failed" else None))
        return receipts

    def _validate_account_metadata(self, value: dict[str, Any]) -> None:
        metadata = value.get("metadata") or {}
        actual = str(metadata.get("phone_number_id", ""))
        expected = str(self.config.phone_number_id or "")
        if expected and actual != expected:
            raise WhatsAppWebhookError("WhatsApp webhook phone number account is missing or does not match configured account")

    # --- Webhook Notification Processing ---

    def parse_webhook_payload(self, payload: dict[str, Any]) -> list[RawMessageEnvelope]:
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

                self._validate_account_metadata(value)

                # Delivery statuses (sent, delivered, read) - do not ingest as inbound messages
                if "statuses" in value and not value.get("messages"):
                    logger.debug("Received WhatsApp delivery status callback")
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
                    if not msg_id or len(str(msg_id)) > 200:
                        continue

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
                                content, _detected_mime, default_name = self.download_media(media_id)
                                target_name = filename or default_name
                                valid_mime, clean_name = validate_attachment(target_name, content, declared_mime)

                                stable = hashlib.sha256(f"{msg_id}:{media_id}".encode()).hexdigest()[:24]
                                att_id = f"att_wa_{stable}"
                                ev_ref = f"ev_wa_{stable}"
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
                                logger.warning("Failed processing WhatsApp media (%s)", type(exc).__name__)

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
                        sender_identity_id=sender_id,
                        sender_alias=sender_alias,
                        received_at=received_at,
                        message_at=message_at,
                        text=text,
                        attachments=attachments,
                        thread_ref=sender_id,
                        reply_to_provider_message_id=(msg.get("context") or {}).get("id"),
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
        envelopes = self.parse_webhook_payload(payload)
        responses: list[IngestResponse] = []

        # 3. Ingest each message
        for envelope in envelopes:
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
