"""P1 Telegram Bot API Inbound Channel Adapter.

Supports:
- Real Telegram Bot API requests via HTTP client (httpx).
- Long-polling via getUpdates with persistent offset tracking across restarts.
- Webhook reception via POST endpoint with secret-token verification.
- Webhook vs. polling conflict resolution (deleteWebhook before polling).
- Duplicate update protection and idempotent message ingestion.
- Attachment/media downloading (documents, photos) with magic-byte validation.
- Secure tenant assignment (server-configured, never trusting client metadata).
- Direct handoff into P1 IngestionService and deterministic/AI processing pipeline.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
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

from .config import TelegramChannelConfig
from .reply_framing import FramingError, telegram_frame
from .state import ChannelStateManager, get_state_manager

logger = logging.getLogger(__name__)


class TelegramApiError(Exception):
    """Raised when Telegram Bot API returns an error or is unreachable."""


class TelegramAdapter:
    """Production-ready inbound adapter for Telegram Bot API."""

    def __init__(
        self,
        config: TelegramChannelConfig,
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

        self._poll_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._is_polling = False
        self._lock = threading.Lock()

    @property
    def is_polling(self) -> bool:
        return self._is_polling

    def _get_client(self) -> httpx.Client:
        if self._custom_client is not None:
            return self._custom_client
        return httpx.Client(timeout=30.0)

    def _api_url(self, method: str) -> str:
        token = self.config.bot_token or ""
        return f"{self.config.api_base_url.rstrip('/')}/bot{token}/{method}"

    def _file_url(self, file_path: str) -> str:
        token = self.config.bot_token or ""
        return f"{self.config.api_base_url.rstrip('/')}/file/bot{token}/{file_path.lstrip('/')}"

    # --- Telegram Bot API Calls ---

    def get_me(self) -> dict[str, Any]:
        """Verify bot token and fetch bot profile."""
        if not self.config.is_configured:
            raise TelegramApiError("Telegram bot token is not configured")
        url = self._api_url("getMe")
        client = self._get_client()
        try:
            resp = client.get(url)
            data = resp.json()
            if not resp.is_success or not data.get("ok"):
                raise TelegramApiError(f"Telegram getMe failed: {data.get('description', resp.text)}")
            return data["result"]
        except Exception as exc:
            if isinstance(exc, TelegramApiError):
                raise
            raise TelegramApiError(f"Telegram API request failed: {exc}") from exc

    def get_webhook_info(self) -> dict[str, Any]:
        """Inspect current webhook status to detect conflicts."""
        if not self.config.is_configured:
            raise TelegramApiError("Telegram bot token is not configured")
        url = self._api_url("getWebhookInfo")
        client = self._get_client()
        try:
            resp = client.get(url)
            data = resp.json()
            if not resp.is_success or not data.get("ok"):
                raise TelegramApiError(f"Telegram getWebhookInfo failed: {data.get('description', resp.text)}")
            return data["result"]
        except Exception as exc:
            if isinstance(exc, TelegramApiError):
                raise
            raise TelegramApiError(f"Telegram API request failed: {exc}") from exc

    def delete_webhook(self, drop_pending_updates: bool = False) -> bool:
        """Clear webhook configuration so getUpdates polling can proceed without conflict."""
        if not self.config.is_configured:
            return False
        url = self._api_url("deleteWebhook")
        client = self._get_client()
        try:
            resp = client.post(url, json={"drop_pending_updates": drop_pending_updates})
            data = resp.json()
            return bool(resp.is_success and data.get("ok"))
        except Exception as exc:
            logger.warning("Failed to delete Telegram webhook: %s", exc)
            return False

    def set_webhook(self, url: str, secret_token: str | None = None) -> bool:
        """Register public HTTPS webhook with optional secret verification token."""
        if not self.config.is_configured:
            raise TelegramApiError("Telegram bot token is not configured")
        api_url = self._api_url("setWebhook")
        payload: dict[str, Any] = {
            "url": url,
            "allowed_updates": ["message"],
        }
        if secret_token:
            payload["secret_token"] = secret_token
        client = self._get_client()
        try:
            resp = client.post(api_url, json=payload)
            data = resp.json()
            if not resp.is_success or not data.get("ok"):
                raise TelegramApiError(f"Telegram setWebhook failed: {data.get('description', resp.text)}")
            return True
        except Exception as exc:
            if isinstance(exc, TelegramApiError):
                raise
            raise TelegramApiError(f"Telegram API setWebhook failed: {exc}") from exc

    def get_updates(self, offset: int | None = None, timeout: int = 10) -> list[dict[str, Any]]:
        """Fetch incoming updates via long-polling with persistent offset."""
        if not self.config.is_configured:
            raise TelegramApiError("Telegram bot token is not configured")
        url = self._api_url("getUpdates")
        params: dict[str, Any] = {
            "timeout": timeout,
            "allowed_updates": ["message"],
        }
        if offset is not None:
            params["offset"] = offset
        client = self._get_client()
        try:
            resp = client.post(url, json=params)
            data = resp.json()
            if not resp.is_success or not data.get("ok"):
                err_desc = data.get("description", resp.text)
                if "can't use getUpdates method while webhook is active" in err_desc.lower():
                    logger.info("Webhook conflict detected. Clearing active webhook for polling mode...")
                    self.delete_webhook()
                    resp = client.post(url, json=params)
                    data = resp.json()
                    if resp.is_success and data.get("ok"):
                        return data["result"]
                raise TelegramApiError(f"Telegram getUpdates failed: {err_desc}")
            return data["result"]
        except Exception as exc:
            if isinstance(exc, TelegramApiError):
                raise
            raise TelegramApiError(f"Telegram getUpdates network error: {exc}") from exc

    def download_file(self, file_id: str) -> tuple[bytes, str]:
        """Download file content from Telegram API given a file_id."""
        if not self.config.is_configured:
            raise TelegramApiError("Telegram bot token is not configured")
        client = self._get_client()
        get_file_url = self._api_url("getFile")
        resp = client.get(get_file_url, params={"file_id": file_id})
        data = resp.json()
        if not resp.is_success or not data.get("ok"):
            raise TelegramApiError(f"getFile failed for {file_id}: {data.get('description', resp.text)}")

        file_path = data["result"]["file_path"]
        download_url = self._file_url(file_path)
        file_resp = client.get(download_url)
        if not file_resp.is_success:
            raise TelegramApiError(f"Downloading file from {download_url} failed with status {file_resp.status_code}")
        filename = file_path.split("/")[-1] if "/" in file_path else "telegram_attachment"
        return file_resp.content, filename

    # --- Inbound Update Normalization ---

    def parse_update(self, update: dict[str, Any]) -> RawMessageEnvelope | None:
        """Normalize Telegram Update dictionary into canonical RawMessageEnvelope.

        Returns None if update does not contain an inbound text/attachment message.
        """
        message = update.get("message") or update.get("edited_message")
        if not message or not isinstance(message, dict):
            return None

        # Text resolution (text or caption)
        text = (message.get("text") or message.get("caption") or "").strip()

        # Sender resolution
        from_user = message.get("from") or {}
        sender_id = str(from_user.get("id") or "tg_unknown_sender")
        username = from_user.get("username")
        first_name = from_user.get("first_name", "")
        last_name = from_user.get("last_name", "")
        full_name = f"{first_name} {last_name}".strip()
        sender_alias = username or full_name or f"Telegram User {sender_id}"

        # Chat & message IDs
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id") or sender_id)
        msg_id = message.get("message_id")
        if msg_id is None:
            return None
        provider_message_id = f"tg_{chat_id}_{msg_id}"

        frame = None
        framing_error = None
        try:
            if not self.config.provider_account_id:
                raise FramingError("Telegram bot account ID is not configured or derivable")
            frame = telegram_frame(
                {"message": message},
                tenant_id=self.config.tenant_id,
                account_id=self.config.provider_account_id,
            )
        except FramingError as exc:
            framing_error = str(exc)

        # Timestamps
        raw_date = message.get("date")
        if raw_date:
            message_at = datetime.fromtimestamp(int(raw_date), tz=timezone.utc)
        else:
            message_at = self._clock()
        received_at = self._clock()

        # Attachment processing
        attachments: list[Attachment] = []

        # 1. Document attachment
        if "document" in message:
            doc = message["document"]
            file_id = doc.get("file_id")
            orig_filename = doc.get("file_name") or "document.pdf"
            mime_type = doc.get("mime_type")
            if file_id:
                try:
                    content, _ = self.download_file(file_id)
                    detected_mime, clean_filename = validate_attachment(orig_filename, content, mime_type)
                    att_id = f"att_tg_{uuid4().hex[:12]}"
                    ev_ref = f"ev_tg_{uuid4().hex[:12]}"
                    sha256 = hashlib.sha256(content).hexdigest()

                    record = AttachmentRecord(
                        attachment_id=att_id,
                        tenant_id=self.config.tenant_id,
                        evidence_ref=ev_ref,
                        filename=clean_filename,
                        media_type=detected_mime,
                        size_bytes=len(content),
                        content_sha256=sha256,
                        created_at=received_at,
                    )
                    self.repository.save_attachment(self.config.tenant_id, record, content)

                    attachments.append(
                        Attachment(
                            attachment_id=att_id,
                            filename=clean_filename,
                            media_type=detected_mime,
                            size_bytes=len(content),
                            evidence_ref=ev_ref,
                        )
                    )
                except Exception as exc:
                    logger.warning("Failed to download or validate Telegram document: %s", exc)

        # 2. Photo attachment (take highest resolution)
        elif "photo" in message and isinstance(message["photo"], list) and message["photo"]:
            photo_sizes = message["photo"]
            best_photo = photo_sizes[-1]
            file_id = best_photo.get("file_id")
            if file_id:
                try:
                    content, _ = self.download_file(file_id)
                    detected_mime, clean_filename = validate_attachment("photo.jpg", content, "image/jpeg")
                    att_id = f"att_tg_{uuid4().hex[:12]}"
                    ev_ref = f"ev_tg_{uuid4().hex[:12]}"
                    sha256 = hashlib.sha256(content).hexdigest()

                    record = AttachmentRecord(
                        attachment_id=att_id,
                        tenant_id=self.config.tenant_id,
                        evidence_ref=ev_ref,
                        filename=clean_filename,
                        media_type=detected_mime,
                        size_bytes=len(content),
                        content_sha256=sha256,
                        created_at=received_at,
                    )
                    self.repository.save_attachment(self.config.tenant_id, record, content)

                    attachments.append(
                        Attachment(
                            attachment_id=att_id,
                            filename=clean_filename,
                            media_type=detected_mime,
                            size_bytes=len(content),
                            evidence_ref=ev_ref,
                        )
                    )
                except Exception as exc:
                    logger.warning("Failed to download or validate Telegram photo: %s", exc)

        # Ensure text is not empty if only an attachment was sent
        if not text:
            if attachments:
                text = f"[Telegram Attachment: {attachments[0].filename}]"
            else:
                return None  # Empty non-media message (e.g. system update)

        return RawMessageEnvelope(
            tenant_id=self.config.tenant_id,
            channel="TELEGRAM",
            provider_message_id=provider_message_id,
            provider_account_id=frame.account_id if frame else None,
            provider_native_message_id=frame.native_message_id if frame else None,
            sender_identity_id=sender_id,
            sender_alias=sender_alias,
            received_at=received_at,
            message_at=message_at,
            text=text,
            attachments=attachments,
            native_attachment_source_ids=list(frame.attachment_source_ids) if frame else [],
            thread_ref=chat_id,
            conversation_id=frame.conversation_id if frame else chat_id,
            reply_to_provider_message_id=frame.exact_parent_id if frame else None,
            relationship_source=frame.relationship_source if frame else "UNKNOWN",
            source_authenticity="UNVERIFIED",
            correlation_id=f"telegram-update:{update['update_id']}" if update.get("update_id") is not None else None,
            framing_error=framing_error,
            adapter_mode="REAL",
        )

    def process_update(self, update: dict[str, Any], *, source_verified: bool = False) -> IngestResponse | None:
        """Process a single Telegram update: normalize, ingest, and advance cursor."""
        if not source_verified:
            raise TelegramApiError("Inbound Telegram update was not authenticated")
        update_id = update.get("update_id")
        envelope = self.parse_update(update)

        result: IngestResponse | None = None
        if envelope is not None:
            envelope = envelope.model_copy(update={"source_authenticity": "VERIFIED"})
            # Route into existing P1 ingestion service
            result = self.ingestion_service.ingest(envelope, self.config.tenant_id)
            # If newly received (not duplicate), run extraction pipeline automatically
            if not result.duplicate:
                try:
                    self.repository.process(self.config.tenant_id, result.message.message_id)
                except Exception as exc:
                    logger.warning("Automatic extraction on Telegram message %s failed: %s",
                                   result.message.message_id, exc)
                try:
                    from app.context.context_service import ContextService
                    ContextService(self.repository).create_or_update_from_message(
                        self.config.tenant_id, result.message.message_id
                    )
                except Exception as exc:
                    logger.warning("Automatic context creation for Telegram message %s failed: %s",
                                   result.message.message_id, exc)

        # Advance persistent update offset
        if update_id is not None:
            self.state_manager.save_telegram_offset(self.config.tenant_id, update_id)

        return result

    # --- Polling Worker Lifecycle ---

    def poll_once(self) -> int:
        """Run a single polling cycle. Returns count of updates processed."""
        if not self.config.is_configured:
            return 0

        last_offset = self.state_manager.get_telegram_offset(self.config.tenant_id)
        next_offset = (last_offset + 1) if last_offset is not None else None

        try:
            updates = self.get_updates(offset=next_offset, timeout=min(10, self.config.poll_timeout_seconds))
            processed_count = 0
            for update in updates:
                up_id = update.get("update_id")
                # Skip duplicate updates if already seen
                if last_offset is not None and up_id is not None and up_id <= last_offset:
                    continue
                self.process_update(update, source_verified=True)
                processed_count += 1
                if up_id is not None:
                    last_offset = up_id

            self.state_manager.record_poll_attempt("TELEGRAM", self.config.tenant_id)
            return processed_count
        except Exception as exc:
            err_msg = str(exc)
            logger.error("Error during Telegram polling: %s", err_msg)
            self.state_manager.record_poll_attempt("TELEGRAM", self.config.tenant_id, error=err_msg)
            raise

    def start_polling(self) -> None:
        """Start background polling thread if not already active."""
        with self._lock:
            if self._is_polling:
                logger.info("Telegram polling is already running")
                return
            if not self.config.is_configured:
                logger.info("Telegram bot is not configured; polling worker skipped")
                self.state_manager.set_status("TELEGRAM", self.config.tenant_id, "UNCONFIGURED")
                return

            # Clear webhook conflicts before starting polling
            try:
                info = self.get_webhook_info()
                if info.get("url"):
                    logger.info("Existing Telegram webhook detected (%s). Removing for polling mode.", info.get("url"))
                    self.delete_webhook()
            except Exception as exc:
                logger.warning("Could not check/clear Telegram webhook info: %s", exc)

            self._stop_event.clear()
            self._is_polling = True
            self.state_manager.set_status("TELEGRAM", self.config.tenant_id, "POLLING")

            self._poll_thread = threading.Thread(
                target=self._run_polling_loop,
                name="TelegramPollingWorker",
                daemon=True,
            )
            self._poll_thread.start()
            logger.info("Telegram polling worker started for tenant %s", self.config.tenant_id)

    def stop_polling(self, timeout: float = 5.0) -> None:
        """Signal polling loop to stop and join thread."""
        with self._lock:
            if not self._is_polling:
                return
            self._stop_event.set()
            self._is_polling = False
            self.state_manager.set_status("TELEGRAM", self.config.tenant_id, "IDLE")

        if self._poll_thread and self._poll_thread.is_alive() and threading.current_thread() != self._poll_thread:
            self._poll_thread.join(timeout=timeout)
            logger.info("Telegram polling worker stopped")

    def _run_polling_loop(self) -> None:
        """Worker loop running in background thread."""
        interval = max(0.5, self.config.poll_interval_seconds)
        while not self._stop_event.is_set():
            try:
                self.poll_once()
            except Exception as exc:
                logger.error("Unhandled error in Telegram polling loop: %s", exc)
                # Exponential backoff on recurring failures
                time.sleep(min(30.0, interval * 3))

            self._stop_event.wait(timeout=interval)
