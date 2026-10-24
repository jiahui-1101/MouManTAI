"""P1 Gmail API Inbound Channel Adapter.

Supports:
- Google OAuth 2.0 authorization URL generation and token exchange.
- Automatic access-token refresh on expiry using refresh_token.
- Incremental inbox polling with restart-safe internalDate/history cursor.
- Pagination handling and duplicate prevention.
- Comprehensive MIME body parsing:
  - Multipart traversal (multipart/alternative, multipart/mixed).
  - Plain text preference with clean HTML fallback (tag stripping).
  - RFC 2822 header extraction (From name/email, Subject, Date, Message-ID).
- Supported PDF and image attachment extraction via Gmail API attachment endpoints.
- Error handling for expired or revoked authorization (invalid_grant).
- Direct handoff into P1 IngestionService and downstream AI pipeline.
"""

from __future__ import annotations

import base64
import email.utils
import hashlib
import logging
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

import httpx

from app.context.attachment_validator import validate_attachment
from app.context.document_schemas import AttachmentRecord
from app.context.ingestion import IngestionService
from app.context.ingestion_schemas import IngestResponse
from app.context.repository import MessageRepository
from app.context.schemas import Attachment, RawMessageEnvelope

from .config import GmailChannelConfig
from .reply_framing import FramingError, email_frame
from .state import ChannelStateManager, get_state_manager

logger = logging.getLogger(__name__)

GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


class GmailAuthError(Exception):
    """Raised when OAuth credentials are invalid, revoked, or expired."""


class GmailApiError(Exception):
    """Raised when Gmail API requests fail."""


def _base64url_decode(encoded_str: str) -> bytes:
    """Decode URL-safe base64 string padding as needed."""
    rem = len(encoded_str) % 4
    if rem > 0:
        encoded_str += "=" * (4 - rem)
    return base64.urlsafe_b64decode(encoded_str)


def _strip_html_tags(html: str) -> str:
    """Convert HTML content into clean plain text for AI extraction."""
    # Replace line breaks and paragraph breaks with newlines
    text = re.sub(r"(?i)<(br|p|div|tr)[^>]*>", "\n", html)
    # Strip remaining HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Collapse multiple spaces within lines
    text = re.sub(r"[ \t]+", " ", text)
    # Collapse multiple blank lines
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


class GmailAdapter:
    """Production-ready inbound adapter for Google Gmail API."""

    def __init__(
        self,
        config: GmailChannelConfig,
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

        # Load existing tokens from persistent state manager if present
        saved_tokens = self.state_manager.get_gmail_tokens(self.config.tenant_id)
        if saved_tokens:
            saved_refresh = saved_tokens.get("refresh_token")
            if self.config.refresh_token:
                # If explicit refresh_token configured, only reuse access_token if refresh_tokens match
                if saved_refresh and saved_refresh == self.config.refresh_token:
                    if "access_token" in saved_tokens:
                        self.config.access_token = saved_tokens["access_token"]
                else:
                    # Mismatched/stale saved tokens: discard old access token
                    self.config.access_token = None
            else:
                if "refresh_token" in saved_tokens:
                    self.config.refresh_token = saved_tokens["refresh_token"]
                if "access_token" in saved_tokens:
                    self.config.access_token = saved_tokens["access_token"]

    @property
    def is_polling(self) -> bool:
        return self._is_polling

    def _get_client(self) -> httpx.Client:
        if self._custom_client is not None:
            return self._custom_client
        return httpx.Client(timeout=30.0)

    # --- Google OAuth 2.0 Authorization & Token Refresh ---

    def get_authorization_url(self, state: str | None = None) -> str:
        """Generate Google OAuth 2.0 consent URL requesting offline access."""
        if not self.config.can_authorize:
            raise GmailAuthError("GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET are required for OAuth")
        params = {
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "response_type": "code",
            "scope": GMAIL_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
        }
        if state:
            params["state"] = state
        return f"{self.config.auth_endpoint}?{urlencode(params)}"

    def exchange_code(self, code: str) -> dict[str, Any]:
        """Exchange authorization code for access and refresh tokens."""
        if not self.config.can_authorize:
            raise GmailAuthError("GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET are required")

        data = {
            "code": code,
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "redirect_uri": self.config.redirect_uri,
            "grant_type": "authorization_code",
        }
        client = self._get_client()
        try:
            resp = client.post(self.config.token_endpoint, data=data)
            token_data = resp.json()
            if not resp.is_success or "error" in token_data:
                raise GmailAuthError(f"OAuth code exchange failed: {token_data.get('error_description', resp.text)}")

            self.config.access_token = token_data.get("access_token")
            if "refresh_token" in token_data:
                self.config.refresh_token = token_data["refresh_token"]

            self.state_manager.save_gmail_tokens(self.config.tenant_id, token_data)
            self.state_manager.set_status("EMAIL", self.config.tenant_id, "TOKEN_READY")
            return token_data
        except Exception as exc:
            if isinstance(exc, GmailAuthError):
                raise
            raise GmailAuthError(f"Token exchange network failure: {exc}") from exc

    def refresh_access_token(self) -> str:
        """Use refresh_token to obtain a new access_token."""
        refresh_token = self.config.refresh_token
        if not refresh_token:
            # Check state manager
            saved = self.state_manager.get_gmail_tokens(self.config.tenant_id)
            refresh_token = saved.get("refresh_token")

        if not refresh_token:
            self.state_manager.set_status("EMAIL", self.config.tenant_id, "AUTH_EXPIRED", "Missing refresh token")
            raise GmailAuthError("No refresh token available to refresh Gmail access token")

        data = {
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        client = self._get_client()
        try:
            resp = client.post(self.config.token_endpoint, data=data)
            token_data = resp.json()
            if not resp.is_success or "error" in token_data:
                err = token_data.get("error", "")
                desc = token_data.get("error_description", resp.text)
                if err == "invalid_grant":
                    self.state_manager.set_status("EMAIL", self.config.tenant_id, "AUTH_EXPIRED", f"Revoked: {desc}")
                    raise GmailAuthError(f"Google OAuth authorization has expired or been revoked: {desc}")
                raise GmailAuthError(f"Token refresh failed: {desc}")

            new_access_token = token_data["access_token"]
            self.config.access_token = new_access_token
            # Preserve existing refresh token if not returned
            if "refresh_token" not in token_data:
                token_data["refresh_token"] = refresh_token

            self.state_manager.save_gmail_tokens(self.config.tenant_id, token_data)
            return new_access_token
        except Exception as exc:
            if isinstance(exc, GmailAuthError):
                raise
            raise GmailAuthError(f"Token refresh network error: {exc}") from exc

    def get_valid_access_token(self) -> str:
        """Return a valid access token, refreshing if necessary."""
        if not self.config.access_token:
            return self.refresh_access_token()
        return self.config.access_token

    # --- Gmail API Calls ---

    def get_profile(self) -> dict[str, Any]:
        """Fetch authenticated user's Gmail profile (emailAddress, messagesTotal, historyId)."""
        token = self.get_valid_access_token()
        url = f"{self.config.api_base_url.rstrip('/')}/gmail/v1/users/me/profile"
        headers = {"Authorization": f"Bearer {token}"}
        client = self._get_client()
        try:
            resp = client.get(url, headers=headers)
            if resp.status_code == 401:
                token = self.refresh_access_token()
                headers["Authorization"] = f"Bearer {token}"
                resp = client.get(url, headers=headers)

            if not resp.is_success:
                raise GmailApiError(f"Gmail get_profile failed ({resp.status_code}): {resp.text}")
            return resp.json()
        except Exception as exc:
            if isinstance(exc, (GmailApiError, GmailAuthError)):
                raise
            raise GmailApiError(f"Gmail get_profile network error: {exc}") from exc

    def verify_connection(self) -> dict[str, Any]:
        """Safely verify authenticated Gmail account identity and OAuth validity."""
        if not self.config.is_configured:
            return {"authenticated": False, "reason": "Not configured"}
        profile = self.get_profile()
        email_addr = profile.get("emailAddress", "").strip()
        if self.config.mailbox_account_id and email_addr.casefold() != self.config.mailbox_account_id.strip().casefold():
            return {"authenticated": False, "reason": "OAuth mailbox differs from configured account identity"}
        if "@" in email_addr:
            u, d = email_addr.split("@", 1)
            masked = (u[:3] + "***@" + d) if len(u) > 3 else (u[0] + "***@" + d)
        else:
            masked = "***"
        if "@" in email_addr:
            self.state_manager.set_verified_account_id("EMAIL", self.config.tenant_id, email_addr)
            self.config.mailbox_account_id = email_addr
        return {
            "authenticated": True,
            "email_address": email_addr,
            "masked_email": masked,
            "messages_total": profile.get("messagesTotal", 0),
            "threads_total": profile.get("threadsTotal", 0),
            "history_id": profile.get("historyId"),
        }

    def list_messages(
        self,
        query: str | None = None,
        page_token: str | None = None,
        max_results: int = 50,
    ) -> dict[str, Any]:
        """Fetch list of message summaries matching query from Gmail API."""
        token = self.get_valid_access_token()
        url = f"{self.config.api_base_url.rstrip('/')}/gmail/v1/users/me/messages"
        params: dict[str, Any] = {"maxResults": max_results}
        if query:
            params["q"] = query
        if page_token:
            params["pageToken"] = page_token

        headers = {"Authorization": f"Bearer {token}"}
        client = self._get_client()
        try:
            resp = client.get(url, params=params, headers=headers)
            if resp.status_code == 401:
                # Token expired; refresh and retry once
                token = self.refresh_access_token()
                headers["Authorization"] = f"Bearer {token}"
                resp = client.get(url, params=params, headers=headers)

            if not resp.is_success:
                raise GmailApiError(f"Gmail list_messages failed ({resp.status_code}): {resp.text}")
            return resp.json()
        except Exception as exc:
            if isinstance(exc, (GmailApiError, GmailAuthError)):
                raise
            raise GmailApiError(f"Gmail list_messages network error: {exc}") from exc

    def get_message_detail(self, message_id: str) -> dict[str, Any]:
        """Fetch full MIME message details by ID."""
        token = self.get_valid_access_token()
        url = f"{self.config.api_base_url.rstrip('/')}/gmail/v1/users/me/messages/{message_id}"
        headers = {"Authorization": f"Bearer {token}"}
        client = self._get_client()
        try:
            resp = client.get(url, params={"format": "full"}, headers=headers)
            if resp.status_code == 401:
                token = self.refresh_access_token()
                headers["Authorization"] = f"Bearer {token}"
                resp = client.get(url, params={"format": "full"}, headers=headers)

            if not resp.is_success:
                raise GmailApiError(f"Gmail get_message_detail failed for {message_id}: {resp.text}")
            return resp.json()
        except Exception as exc:
            if isinstance(exc, (GmailApiError, GmailAuthError)):
                raise
            raise GmailApiError(f"Gmail get_message_detail network error: {exc}") from exc

    def download_attachment(self, message_id: str, attachment_id: str) -> bytes:
        """Download raw attachment bytes given message_id and attachment_id."""
        token = self.get_valid_access_token()
        url = f"{self.config.api_base_url.rstrip('/')}/gmail/v1/users/me/messages/{message_id}/attachments/{attachment_id}"
        headers = {"Authorization": f"Bearer {token}"}
        client = self._get_client()
        try:
            resp = client.get(url, headers=headers)
            if resp.status_code == 401:
                token = self.refresh_access_token()
                headers["Authorization"] = f"Bearer {token}"
                resp = client.get(url, headers=headers)

            if not resp.is_success:
                raise GmailApiError(f"Gmail download_attachment failed for {attachment_id}: {resp.text}")
            data = resp.json()
            raw_data = data.get("data", "")
            return _base64url_decode(raw_data)
        except Exception as exc:
            if isinstance(exc, (GmailApiError, GmailAuthError)):
                raise
            raise GmailApiError(f"Gmail download_attachment error: {exc}") from exc

    # --- MIME Parsing & Normalization ---

    def _extract_body_and_attachments(
        self,
        message_id: str,
        payload: dict[str, Any],
        received_at: datetime,
    ) -> tuple[str, list[Attachment]]:
        """Recursively traverse Gmail payload to extract text body and download attachments."""
        text_plain_parts: list[str] = []
        text_html_parts: list[str] = []
        attachments: list[Attachment] = []

        def walk_parts(part: dict[str, Any]) -> None:
            mime_type = part.get("mimeType", "")
            filename = part.get("filename", "")
            body = part.get("body", {})

            # Check if this part is an attachment
            attachment_id = body.get("attachmentId")
            if filename and (attachment_id or body.get("data")):
                try:
                    if attachment_id:
                        content = self.download_attachment(message_id, attachment_id)
                    else:
                        content = _base64url_decode(body.get("data", ""))

                    detected_mime, clean_filename = validate_attachment(filename, content, mime_type)
                    att_id = f"att_gm_{uuid4().hex[:12]}"
                    ev_ref = f"ev_gm_{uuid4().hex[:12]}"
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
                    logger.warning("Skipping invalid or unsupported email attachment '%s': %s", filename, exc)
                return

            # Check body text
            data_str = body.get("data")
            if data_str:
                try:
                    decoded = _base64url_decode(data_str).decode("utf-8", errors="replace")
                    if mime_type == "text/plain":
                        text_plain_parts.append(decoded)
                    elif mime_type == "text/html":
                        text_html_parts.append(_strip_html_tags(decoded))
                except Exception as exc:
                    logger.warning("Failed decoding message part: %s", exc)

            for subpart in part.get("parts", []):
                walk_parts(subpart)

        walk_parts(payload)

        # Prefer plain text; fallback to sanitized HTML
        if text_plain_parts:
            full_body = "\n\n".join(text_plain_parts).strip()
        elif text_html_parts:
            full_body = "\n\n".join(text_html_parts).strip()
        else:
            full_body = ""

        return full_body, attachments

    def parse_message(
        self, msg_data: dict[str, Any], *, source_verified: bool = False
    ) -> RawMessageEnvelope | None:
        """Parse raw Gmail message payload into canonical RawMessageEnvelope."""
        msg_id = msg_data.get("id")
        if not msg_id:
            return None

        thread_id = msg_data.get("threadId")
        raw_internal_date = msg_data.get("internalDate")
        if raw_internal_date:
            message_at = datetime.fromtimestamp(int(raw_internal_date) / 1000.0, tz=timezone.utc)
        else:
            message_at = self._clock()
        received_at = self._clock()

        payload = msg_data.get("payload", {})
        headers_list = payload.get("headers", [])
        headers = {h.get("name", "").lower(): h.get("value", "") for h in headers_list}

        # Extract From header
        raw_from = headers.get("from", "")
        parsed_name, parsed_email = email.utils.parseaddr(raw_from)
        sender_email = parsed_email or "unknown@email.com"
        sender_alias = parsed_name or sender_email

        # Extract Subject
        subject = headers.get("subject", "").strip()

        verified_account_id = self.state_manager.get_channel_summary(
            "EMAIL", self.config.tenant_id
        ).get("verified_account_id")
        account_id = verified_account_id or self.config.mailbox_account_id
        frame = None
        framing_error = None
        try:
            if not account_id:
                raise FramingError("Authenticated Gmail mailbox identity is unavailable")
            frame = email_frame(msg_data, tenant_id=self.config.tenant_id, mailbox=account_id)
        except FramingError as exc:
            framing_error = str(exc)

        # Preserve source header values even when conservative framing rejects them.
        rfc_message_id = frame.rfc_message_id if frame else headers.get("message-id", "").strip() or None
        in_reply_to = list(frame.in_reply_to) if frame else ([headers["in-reply-to"].strip()] if headers.get("in-reply-to", "").strip() else [])
        references = list(frame.references) if frame else ([headers["references"].strip()] if headers.get("references", "").strip() else [])
        provider_message_id = f"gmail_{msg_id}"

        # Extract Body and Attachments
        body_text, attachments = self._extract_body_and_attachments(msg_id, payload, received_at)

        # Compose full text representation for extraction (Subject + Body)
        if subject and body_text:
            text = f"Subject: {subject}\n\n{body_text}"
        elif subject:
            text = f"Subject: {subject}"
        elif body_text:
            text = body_text
        elif attachments:
            text = f"[Email Attachment: {attachments[0].filename}]"
        else:
            return None  # Empty email

        # Ensure text does not exceed envelope constraint (20,000 characters)
        if len(text) > 20000:
            text = text[:19990] + "..."

        return RawMessageEnvelope(
            tenant_id=self.config.tenant_id,
            channel="EMAIL",
            provider_message_id=provider_message_id,
            provider_account_id=frame.account_id if frame else account_id,
            provider_native_message_id=(frame.native_message_id if frame else (str(msg_id) if account_id else None)),
            sender_identity_id=frame.sender_id if frame else sender_email,
            sender_alias=sender_alias,
            received_at=received_at,
            message_at=message_at,
            text=text,
            attachments=attachments,
            thread_ref=thread_id,
            conversation_id=frame.conversation_id if frame else thread_id,
            reply_to_provider_message_id=frame.exact_parent_id if frame else None,
            rfc_message_id=rfc_message_id,
            rfc_in_reply_to=in_reply_to,
            rfc_references=references,
            native_attachment_source_ids=list(frame.attachment_source_ids) if frame else [],
            relationship_source=frame.relationship_source if frame else "UNKNOWN",
            source_authenticity=(
                "VERIFIED"
                if source_verified and verified_account_id and account_id
                and verified_account_id.casefold() == account_id.casefold()
                else "UNVERIFIED"
            ),
            correlation_id=f"gmail-message:{msg_id}",
            framing_error=framing_error,
            adapter_mode="REAL",
        )

    # --- Polling Worker Lifecycle ---

    def poll_inbox(self) -> int:
        """Poll Gmail inbox incrementally using restart-safe cursor."""
        if not self.config.is_configured:
            return 0

        if not self.state_manager.get_channel_summary("EMAIL", self.config.tenant_id).get("verified_account_id"):
            verification = self.verify_connection()
            if not verification.get("authenticated"):
                raise GmailAuthError("Authenticated Gmail mailbox identity could not be verified")

        # Retrieve restart-safe cursor
        last_internal_date = self.state_manager.get_gmail_cursor(self.config.tenant_id)

        # Build query
        query = self.config.query
        if last_internal_date is not None:
            # Query messages newer than last internalDate (in seconds)
            after_epoch = int(last_internal_date / 1000)
            query = f"{query} after:{after_epoch}"

        processed_count = 0
        page_token: str | None = None
        highest_internal_date = last_internal_date or 0

        try:
            while True:
                resp = self.list_messages(query=query, page_token=page_token, max_results=25)
                messages = resp.get("messages", [])
                if not messages:
                    break

                for msg_summary in messages:
                    m_id = msg_summary.get("id")
                    if not m_id:
                        continue

                    # In-memory fast duplicate skip
                    if self.state_manager.has_seen_provider_id("EMAIL", self.config.tenant_id, f"gmail_{m_id}"):
                        continue

                    msg_data = self.get_message_detail(m_id)
                    curr_internal_date = int(msg_data.get("internalDate", 0))

                    # Deduplicate if before cursor
                    if last_internal_date and curr_internal_date <= last_internal_date:
                        continue

                    try:
                        envelope = self.parse_message(msg_data, source_verified=True)
                        if envelope is not None:
                            result = self.ingestion_service.ingest(envelope, self.config.tenant_id)
                            if not result.duplicate:
                                try:
                                    self.repository.process(self.config.tenant_id, result.message.message_id)
                                except Exception as exc:
                                    logger.warning("Automatic extraction on Gmail message %s failed: %s",
                                                   result.message.message_id, exc)
                                try:
                                    from app.context.context_service import ContextService
                                    ContextService(self.repository).create_or_update_from_message(
                                        self.config.tenant_id, result.message.message_id
                                    )
                                except Exception as exc:
                                    logger.warning("Automatic context creation for Gmail message %s failed: %s",
                                                   result.message.message_id, exc)

                            self.state_manager.mark_seen_provider_id("EMAIL", self.config.tenant_id, f"gmail_{m_id}")
                            processed_count += 1
                    except Exception as msg_exc:
                        logger.warning("Could not process Gmail message %s: %s", m_id, msg_exc)
                        self.state_manager.mark_seen_provider_id("EMAIL", self.config.tenant_id, f"gmail_{m_id}")

                    if curr_internal_date > highest_internal_date:
                        highest_internal_date = curr_internal_date

                page_token = resp.get("nextPageToken")
                if not page_token:
                    break

            if highest_internal_date > (last_internal_date or 0):
                self.state_manager.save_gmail_cursor(self.config.tenant_id, highest_internal_date)

            self.state_manager.record_poll_attempt("EMAIL", self.config.tenant_id)
            return processed_count
        except Exception as exc:
            err_msg = str(exc)
            logger.error("Error during Gmail inbox polling: %s", err_msg)
            self.state_manager.record_poll_attempt("EMAIL", self.config.tenant_id, error=err_msg)
            raise

    def start_polling(self) -> None:
        """Start background polling thread if not already running."""
        with self._lock:
            if self._is_polling:
                logger.info("Gmail polling is already running")
                return
            if not self.config.is_configured:
                logger.info("Gmail credentials not configured; polling worker skipped")
                self.state_manager.set_status("EMAIL", self.config.tenant_id, "UNCONFIGURED")
                return

            self._stop_event.clear()
            self._is_polling = True
            self.state_manager.set_status("EMAIL", self.config.tenant_id, "POLLING")

            self._poll_thread = threading.Thread(
                target=self._run_polling_loop,
                name="GmailPollingWorker",
                daemon=True,
            )
            self._poll_thread.start()
            logger.info("Gmail polling worker started for tenant %s", self.config.tenant_id)

    def stop_polling(self, timeout: float = 5.0) -> None:
        """Signal polling loop to stop and join thread."""
        with self._lock:
            if not self._is_polling:
                return
            self._stop_event.set()
            self._is_polling = False
            self.state_manager.set_status("EMAIL", self.config.tenant_id, "IDLE")

        if self._poll_thread and self._poll_thread.is_alive() and threading.current_thread() != self._poll_thread:
            self._poll_thread.join(timeout=timeout)
            logger.info("Gmail polling worker stopped")

    def _run_polling_loop(self) -> None:
        """Worker loop running in background thread."""
        interval = max(5.0, self.config.poll_interval_seconds)
        while not self._stop_event.is_set():
            try:
                self.poll_inbox()
            except GmailAuthError as exc:
                logger.error("Gmail authentication failure; halting polling: %s", exc)
                self.stop_polling()
                break
            except Exception as exc:
                logger.error("Unhandled error in Gmail polling loop: %s", exc)
                time.sleep(min(60.0, interval * 2))

            self._stop_event.wait(timeout=interval)
