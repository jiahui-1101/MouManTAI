"""Resend inbound and restricted outbound channel adapter.

This adapter persists only through the existing P1 MessageRepository boundary. Its send
methods are internal provider transports and are not connected to P4 authorization yet.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import logging
import re
import time
from datetime import UTC, datetime
from email.utils import parseaddr
from typing import Any

import httpx

from app.context.attachment_validator import (
    AttachmentValidationError,
    validate_attachment,
)
from app.context.document_schemas import AttachmentRecord
from app.context.ingestion import IngestionService
from app.context.repository import MessageRepository
from app.context.schemas import Attachment, RawMessageEnvelope

from .config import ResendChannelConfig
from .provider_transport import (
    ProcessIdempotencyGate,
    ProviderPayloadTooLarge,
    ProviderSendResult,
    ProviderStatusReceipt,
    classify_http_status,
    read_limited_get,
    safe_get,
)
from .state import ChannelStateManager, get_state_manager

logger = logging.getLogger(__name__)
_MESSAGE_ID = re.compile(r"<[^\s<>\r\n]+@[^\s<>\r\n]+>")
_ADDRESS = re.compile(r"^[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+$")
_SENSITIVE_HEADER_CHARS = re.compile(r"[\r\n\x00]")


class ResendWebhookError(ValueError):
    """Safe, non-secret error raised for invalid or unprocessable Resend events."""


class ResendProviderUnavailable(ResendWebhookError):
    """The signed event is valid but Resend's retrieval API is unavailable."""


class ResendAdapter:
    def __init__(self, config: ResendChannelConfig, repository: MessageRepository,
                 state_manager: ChannelStateManager | None = None,
                 http_client: httpx.Client | None = None, clock: Any = None):
        self.config = config
        self.repository = repository
        self.state_manager = state_manager or get_state_manager()
        self._custom_client = http_client
        self._clock = clock or (lambda: datetime.now(UTC))
        self.ingestion_service = IngestionService(repository, clock=self._clock)
        self._send_gate = ProcessIdempotencyGate()

    def _get_client(self) -> httpx.Client:
        if self._custom_client is not None:
            return self._custom_client
        return httpx.Client(timeout=httpx.Timeout(self.config.request_timeout_seconds, connect=3.0),
                            follow_redirects=False)

    @staticmethod
    def _header(headers: dict[str, str], name: str) -> str | None:
        return next((value for key, value in headers.items() if key.lower() == name.lower()), None)

    def verify_webhook(self, raw_body: bytes, headers: dict[str, str], *, now: int | None = None) -> bool:
        """Verify Resend/Svix v1 signatures over the exact raw body and a bounded timestamp."""
        secret = self.config.webhook_secret
        msg_id = self._header(headers, "svix-id")
        timestamp = self._header(headers, "svix-timestamp")
        signature_header = self._header(headers, "svix-signature")
        if not secret or not msg_id or not timestamp or not signature_header:
            raise ResendWebhookError("Resend webhook signature headers are missing")
        if len(msg_id) > 200 or not re.fullmatch(r"[A-Za-z0-9._-]+", msg_id):
            raise ResendWebhookError("Resend webhook event id is invalid")
        try:
            issued_at = int(timestamp)
            key = base64.b64decode(secret.removeprefix("whsec_"), validate=True)
        except (ValueError, TypeError) as exc:
            raise ResendWebhookError("Resend webhook signature configuration is invalid") from exc
        current = int(now if now is not None else time.time())
        if abs(current - issued_at) > 300:
            raise ResendWebhookError("Resend webhook signature timestamp is outside the accepted window")
        signed = msg_id.encode() + b"." + timestamp.encode() + b"." + raw_body
        expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
        signatures = []
        for candidate in signature_header.split():
            version, sep, value = candidate.partition(",")
            if sep and version == "v1":
                signatures.append(value)
        if not signatures or not any(hmac.compare_digest(expected, value) for value in signatures):
            raise ResendWebhookError("Resend webhook signature is invalid")
        return True

    def _api_headers(self) -> dict[str, str]:
        if not self.config.api_key:
            raise ResendProviderUnavailable("Resend API key is not configured")
        return {"Authorization": f"Bearer {self.config.api_key}", "Accept": "application/json"}

    def _get_received_email(self, email_id: str) -> dict[str, Any]:
        response = safe_get(self._get_client(),
            f"{self.config.api_base_url.rstrip('/')}/emails/receiving/{email_id}",
            headers=self._api_headers())
        if not response.is_success:
            raise ResendProviderUnavailable("Resend received-email retrieval failed")
        try:
            data = response.json()
        except ValueError as exc:
            raise ResendProviderUnavailable("Resend returned an invalid received-email response") from exc
        if not isinstance(data, dict):
            raise ResendProviderUnavailable("Resend returned an invalid received-email response")
        return data

    @staticmethod
    def _safe_address(raw: str, label: str) -> tuple[str, str]:
        if not raw or _SENSITIVE_HEADER_CHARS.search(raw):
            raise ResendWebhookError(f"Resend {label} address is invalid")
        display, address = parseaddr(raw)
        if not address or len(address) > 254 or not _ADDRESS.fullmatch(address):
            raise ResendWebhookError(f"Resend {label} address is invalid")
        return display, address.lower()

    @staticmethod
    def _message_ids(value: str | None) -> list[str]:
        if not value or _SENSITIVE_HEADER_CHARS.search(value):
            return []
        return [item for item in _MESSAGE_ID.findall(value) if len(item) <= 200][:100]

    @staticmethod
    def _plain_html(value: str) -> str:
        value = re.sub(r"(?i)<(br|p|div|tr)[^>]*>", "\n", value)
        value = re.sub(r"<[^>]+>", "", value)
        return html.unescape(re.sub(r"\n\s*\n+", "\n\n", value)).strip()

    def _download_attachments(self, email_id: str, attachment_meta: list[dict[str, Any]],
                              received_at: datetime) -> list[Attachment]:
        saved: list[Attachment] = []
        for item in attachment_meta[:10]:
            if not isinstance(item, dict):
                continue
            attachment_id = str(item.get("id") or "")
            if not attachment_id or len(attachment_id) > 200 or not re.fullmatch(r"[A-Za-z0-9._-]+", attachment_id):
                raise ResendProviderUnavailable("Resend returned an invalid attachment identifier")
            response = safe_get(self._get_client(),
                f"{self.config.api_base_url.rstrip('/')}/emails/receiving/{email_id}/attachments/{attachment_id}",
                headers=self._api_headers())
            if not response.is_success:
                raise ResendProviderUnavailable("Resend attachment metadata retrieval failed")
            try:
                metadata = response.json()
            except ValueError as exc:
                raise ResendProviderUnavailable("Resend returned invalid attachment metadata") from exc
            if not isinstance(metadata, dict):
                raise ResendProviderUnavailable("Resend returned invalid attachment metadata")
            url = metadata.get("download_url")
            try:
                parsed = httpx.URL(url) if isinstance(url, str) else None
                allowed_url = (parsed is not None and parsed.scheme == "https"
                    and parsed.host == "inbound-cdn.resend.com"
                    and parsed.port in {None, 443} and not parsed.username and not parsed.password)
            except (TypeError, ValueError):
                allowed_url = False
            if not allowed_url:
                raise ResendWebhookError("Resend returned a download URL outside its inbound CDN")
            declared_size = metadata.get("size", item.get("size"))
            try:
                declared_size = int(declared_size) if declared_size is not None else None
            except (TypeError, ValueError) as exc:
                raise ResendProviderUnavailable("Resend attachment size metadata is invalid") from exc
            if declared_size is not None and (declared_size < 0 or declared_size > self.config.max_attachment_bytes):
                raise ResendWebhookError("Resend attachment exceeds the configured size limit")
            try:
                status_code, content = read_limited_get(
                    self._get_client(), url, self.config.max_attachment_bytes)
            except ProviderPayloadTooLarge as exc:
                raise ResendWebhookError("Resend attachment exceeds the configured size limit") from exc
            if not 200 <= status_code < 300:
                raise ResendProviderUnavailable("Resend attachment download failed or exceeded the size limit")
            filename = str(metadata.get("filename") or item.get("filename") or "attachment.bin")
            mime = str(metadata.get("content_type") or item.get("content_type") or "application/octet-stream")
            try:
                detected_mime, clean_filename = validate_attachment(filename, content, mime)
            except AttachmentValidationError as exc:
                logger.info("Skipping unsupported Resend attachment (%s)", type(exc).__name__)
                continue
            digest = hashlib.sha256(f"{email_id}:{attachment_id}".encode()).hexdigest()[:24]
            att_id, evidence_ref = f"att_rs_{digest}", f"ev_rs_{digest}"
            record = AttachmentRecord(attachment_id=att_id, tenant_id=self.config.tenant_id,
                evidence_ref=evidence_ref, filename=clean_filename, media_type=detected_mime,
                size_bytes=len(content), content_sha256=hashlib.sha256(content).hexdigest(),
                created_at=received_at)
            self.repository.save_attachment(self.config.tenant_id, record, content)
            saved.append(Attachment(attachment_id=att_id, filename=clean_filename,
                media_type=detected_mime, size_bytes=len(content), evidence_ref=evidence_ref))
        return saved

    def process_received_event(self, raw_body: bytes, headers: dict[str, str], *,
                               signature_verified: bool = False) -> RawMessageEnvelope | None:
        if not signature_verified:
            self.verify_webhook(raw_body, headers)
        try:
            event = json.loads(raw_body)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ResendWebhookError("Resend webhook body is invalid JSON") from exc
        if not isinstance(event, dict) or event.get("type") != "email.received":
            raise ResendWebhookError("Unsupported Resend webhook event")
        event_data = event.get("data") or {}
        if not isinstance(event_data, dict):
            raise ResendWebhookError("Resend event data is invalid")
        email_id = str(event_data.get("email_id") or "")
        if not email_id or len(email_id) > 200 or not re.fullmatch(r"[A-Za-z0-9._-]+", email_id):
            raise ResendWebhookError("Resend event has an invalid email id")
        raw_to = event_data.get("to", [])
        raw_to = raw_to if isinstance(raw_to, list) else [raw_to]
        received_to = {str(item).strip().lower() for item in raw_to if isinstance(item, str)}
        allowed_to = {item.strip().lower() for item in self.config.inbound_addresses}
        if not allowed_to or not received_to.intersection(allowed_to):
            raise ResendWebhookError("Resend event recipient is outside the configured tenant inboxes")

        email_data = self._get_received_email(email_id)
        from_value = str(email_data.get("from") or event_data.get("from") or "")
        display_name, sender_email = self._safe_address(from_value, "From")
        received_at = self._clock()
        raw_created = email_data.get("created_at") or event_data.get("created_at")
        message_at: datetime | None = None
        try:
            parsed_created = datetime.fromisoformat(str(raw_created))
            if parsed_created.tzinfo is None:
                parsed_created = parsed_created.replace(tzinfo=UTC)
            message_at = parsed_created.astimezone(UTC)
        except (ValueError, TypeError):
            # Receive time is not evidence of when the customer sent the email.
            # Keeping provider time unknown also makes webhook replays fingerprint-stable.
            pass

        headers_data = email_data.get("headers") or {}
        if isinstance(headers_data, list):
            rfc_headers = {str(item.get("name", "")).lower(): str(item.get("value", ""))
                           for item in headers_data if isinstance(item, dict)}
        elif isinstance(headers_data, dict):
            rfc_headers = {str(key).lower(): str(value) for key, value in headers_data.items()}
        else:
            rfc_headers = {}
        rfc_message_id = str(email_data.get("message_id") or event_data.get("message_id")
                             or rfc_headers.get("message-id") or "")
        own_message_ids = self._message_ids(rfc_message_id)
        parent_ids = self._message_ids(rfc_headers.get("in-reply-to"))
        reference_ids = self._message_ids(rfc_headers.get("references"))
        provider_id = own_message_ids[-1] if own_message_ids else f"resend_{email_id}"
        subject = str(email_data.get("subject") or event_data.get("subject") or "").strip()
        if _SENSITIVE_HEADER_CHARS.search(subject):
            subject = ""
        body = str(email_data.get("text") or "").strip()
        if not body and email_data.get("html"):
            body = self._plain_html(str(email_data["html"]))
        if subject and body:
            text = f"Subject: {subject}\n\n{body}"
        elif subject:
            text = f"Subject: {subject}"
        else:
            text = body
        attachments_meta = email_data.get("attachments") or event_data.get("attachments") or []
        attachments = self._download_attachments(email_id, attachments_meta, received_at) if attachments_meta else []
        if not text.strip() and attachments:
            text = f"[Email Attachment: {attachments[0].filename}]"
        if not text.strip():
            return None
        text = text[:20_000]
        thread_ref = reference_ids[0] if reference_ids else (own_message_ids[-1] if own_message_ids else email_id)
        return RawMessageEnvelope(tenant_id=self.config.tenant_id, channel="EMAIL",
            provider_message_id=provider_id, sender_identity_id=sender_email,
            sender_alias=(display_name.strip() or sender_email)[:200], received_at=received_at,
            message_at=message_at, text=text, attachments=attachments, thread_ref=thread_ref,
            reply_to_provider_message_id=parent_ids[-1] if parent_ids else (reference_ids[-1] if reference_ids else None),
            adapter_mode="REAL")

    def ingest_received_event(self, raw_body: bytes, headers: dict[str, str], *,
                              signature_verified: bool = False):
        envelope = self.process_received_event(raw_body, headers, signature_verified=signature_verified)
        if envelope is None:
            return None
        result = self.ingestion_service.ingest(envelope, self.config.tenant_id)
        if not result.duplicate:
            try:
                self.repository.process(self.config.tenant_id, result.message.message_id)
            except Exception as exc:  # noqa: BLE001 - ingestion is committed; avoid provider retry for extraction failure.
                logger.warning("Resend inbound extraction failed (%s)", type(exc).__name__)
        return result

    @staticmethod
    def _validate_rfc_header(value: str, header_name: str) -> str:
        if not value or _SENSITIVE_HEADER_CHARS.search(value) or len(value) > 998:
            raise ResendWebhookError(f"Email {header_name} header is invalid")
        return value

    def send_reply(self, *, to: str, subject: str, text: str, idempotency_key: str,
                   in_reply_to: str | None = None, references: list[str] | None = None) -> ProviderSendResult:
        if not self.config.is_outbound_configured:
            raise ResendWebhookError("Resend outbound transport is disabled or unconfigured")
        _, recipient = self._safe_address(to, "recipient")
        allowed = {value.strip().lower() for value in self.config.test_recipients}
        if recipient not in allowed:
            raise ResendWebhookError("Email recipient is not in the configured test recipient allowlist")
        display, sender = self._safe_address(str(self.config.verified_from_email), "verified From")
        from_value = f"{display} <{sender}>" if display else sender
        reply_to: str | None = None
        if self.config.reply_to_email:
            _, reply_to = self._safe_address(self.config.reply_to_email, "Reply-To")
        safe_subject = self._validate_rfc_header(subject, "Subject")
        headers: dict[str, str] = {}
        if in_reply_to:
            parent_ids = self._message_ids(self._validate_rfc_header(in_reply_to, "In-Reply-To"))
            if len(parent_ids) != 1:
                raise ResendWebhookError("Email In-Reply-To header is invalid")
            headers["In-Reply-To"] = parent_ids[0]
        if references:
            if len(references) > 100:
                raise ResendWebhookError("Email References header has too many identifiers")
            ids = []
            for value in references:
                parsed = self._message_ids(self._validate_rfc_header(value, "References"))
                if len(parsed) != 1:
                    raise ResendWebhookError("Email References header contains an invalid identifier")
                ids.append(parsed[0])
            headers["References"] = " ".join(ids)
            if len(headers["References"]) > 998:
                raise ResendWebhookError("Email References header exceeds the RFC line limit")
        if not isinstance(text, str) or not text.strip() or len(text) > 20_000:
            raise ResendWebhookError("Email reply body is empty or exceeds the supported limit")
        payload: dict[str, Any] = {"from": from_value, "to": [recipient], "subject": safe_subject,
                                   "text": text, "headers": headers}
        if reply_to:
            payload["reply_to"] = [reply_to]
        key = str(idempotency_key).strip()
        fingerprint = hashlib.sha256(repr(sorted(payload.items())).encode()).hexdigest()

        def submit() -> ProviderSendResult:
            try:
                response = self._get_client().post(f"{self.config.api_base_url.rstrip('/')}/emails",
                    headers={**self._api_headers(), "Idempotency-Key": key}, json=payload)
            except httpx.TimeoutException:
                return ProviderSendResult("RESEND", "UNKNOWN", error_class="UNKNOWN",
                    error_code="PROVIDER_TIMEOUT", idempotency_key=key)
            except httpx.RequestError:
                return ProviderSendResult("RESEND", "UNKNOWN", error_class="UNKNOWN",
                    error_code="PROVIDER_CONNECTION_ERROR", idempotency_key=key)
            state, error_class, error_code = classify_http_status(response.status_code)
            try:
                data = response.json()
            except ValueError:
                data = {}
            if state == "ACCEPTED" and data.get("id"):
                return ProviderSendResult("RESEND", "ACCEPTED", str(data["id"]),
                    provider_status="ACCEPTED", idempotency_key=key)
            if state == "ACCEPTED":
                state, error_class, error_code = "UNKNOWN", "UNKNOWN", "PROVIDER_RESPONSE_INVALID"
            return ProviderSendResult("RESEND", state, provider_status=str(response.status_code),
                error_class=error_class, error_code=error_code, idempotency_key=key)

        try:
            return self._send_gate.execute(key, fingerprint, submit)
        except ValueError as exc:
            raise ResendWebhookError(str(exc)) from exc

    def parse_status_event(self, event: dict[str, Any]) -> ProviderStatusReceipt | None:
        data = event.get("data") or {}
        message_id = data.get("message_id") or data.get("email_id")
        if not message_id:
            return None
        event_type = str(event.get("type", ""))
        state = {"email.sent": "SENT", "email.delivered": "DELIVERED",
                 "email.bounced": "FAILED", "email.failed": "FAILED"}.get(event_type, "UNKNOWN")
        return ProviderStatusReceipt("RESEND", self.config.tenant_id, str(message_id), state,
            str(event.get("created_at")) if event.get("created_at") else None,
            "PROVIDER_DELIVERY_FAILED" if state == "FAILED" else None)
