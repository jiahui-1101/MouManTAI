"""P1 Real Inbound Channel Configuration.

Zero hardcoded secrets. Reads strictly from environment variables.
Provides structured configuration and readiness checks for Telegram, Gmail, and WhatsApp.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

logger = logging.getLogger(__name__)


class ChannelConfigBase(BaseModel):
    model_config = ConfigDict(extra="ignore", validate_default=True)
    request_timeout_seconds: float = Field(default=10.0, ge=1.0, le=30.0)

    @property
    def has_tenant_assignment(self) -> bool:
        tenant_id = str(getattr(self, "tenant_id", "")).strip()
        return bool(tenant_id and not tenant_id.casefold().startswith("synthetic"))

    @field_validator("api_base_url", check_fields=False)
    @classmethod
    def require_secure_provider_base(cls, value: str) -> str:
        parsed = urlsplit(value)
        try:
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("provider API base URL has an invalid port") from exc
        if (parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("provider API base URL must use HTTPS and contain no credentials, query, or fragment")
        return value.rstrip("/")


class TelegramChannelConfig(ChannelConfigBase):
    """Configuration for Telegram Bot API integration."""
    bot_token: str | None = None
    mode: Literal["polling", "webhook"] = "polling"
    webhook_url: str | None = None
    webhook_secret: str | None = None
    bot_account_id: str | None = None
    outbound_enabled: bool = False
    test_recipient_ids: list[str] = Field(default_factory=list)
    poll_interval_seconds: float = Field(default=2.0, ge=0.01, le=60.0)
    poll_timeout_seconds: int = Field(default=20, ge=1, le=60)
    tenant_id: str = "synthetic_tenant_a"
    api_base_url: str = "https://api.telegram.org"
    auto_start: bool = True

    @model_validator(mode="after")
    def consistent_bot_account(self):
        prefix = (self.bot_token or "").partition(":")[0]
        if prefix.isdigit() and self.bot_account_id and self.bot_account_id.strip() != prefix:
            raise ValueError("Telegram bot account does not match its token account")
        return self

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token and len(self.bot_token.strip()) > 5 and self.has_tenant_assignment)

    @property
    def provider_account_id(self) -> str | None:
        if self.bot_account_id and self.bot_account_id.strip():
            return self.bot_account_id.strip()
        if self.bot_token:
            token_prefix = self.bot_token.partition(":")[0]
            if token_prefix.isdigit():
                return token_prefix
        return None


class GmailChannelConfig(ChannelConfigBase):
    """Configuration for Google OAuth & Gmail API polling."""
    client_id: str | None = None
    client_secret: str | None = None
    refresh_token: str | None = None
    mailbox_account_id: str | None = None
    access_token: str | None = None
    token_expiry: datetime | None = None
    redirect_uri: str = "http://localhost:8000/v1/channels/gmail/oauth/callback"
    poll_interval_seconds: float = Field(default=30.0, ge=0.01, le=3600.0)
    query: str = "label:INBOX"
    tenant_id: str = "synthetic_tenant_a"
    api_base_url: str = "https://gmail.googleapis.com"
    token_endpoint: str = "https://oauth2.googleapis.com/token"
    auth_endpoint: str = "https://accounts.google.com/o/oauth2/v2/auth"
    auto_start: bool = True
    credentials_file: str | None = None

    @field_validator("token_endpoint", "auth_endpoint")
    @classmethod
    def require_secure_oauth_endpoint(cls, value: str) -> str:
        parsed = urlsplit(value)
        try:
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("Gmail OAuth endpoint has an invalid port") from exc
        if (parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("Gmail OAuth endpoints must use HTTPS and contain no credentials, query, or fragment")
        return value

    @property
    def is_configured(self) -> bool:
        return bool(
            self.client_id
            and self.client_secret
            and (self.refresh_token or self.access_token)
            and self.has_tenant_assignment
        )

    @property
    def can_authorize(self) -> bool:
        return bool(self.client_id and self.client_secret)


class ResendChannelConfig(ChannelConfigBase):
    """Resend inbound webhook and restricted outbound transport settings."""
    api_key: str | None = None
    webhook_secret: str | None = None
    # Operator-bound receiving mailbox; never inferred from an incoming sender.
    account_id: str | None = None
    tenant_id: str = "synthetic_tenant_a"
    api_base_url: str = "https://api.resend.com"
    inbound_addresses: list[str] = Field(default_factory=list)
    outbound_enabled: bool = False
    test_recipients: list[str] = Field(default_factory=list)
    verified_from_email: str | None = None
    reply_to_email: str | None = None
    max_attachment_bytes: int = Field(default=10 * 1024 * 1024, ge=1, le=10 * 1024 * 1024)

    @property
    def is_inbound_configured(self) -> bool:
        return bool(self.api_key and self.webhook_secret and self.account_id
                    and self.account_id.strip().casefold() in {a.strip().casefold() for a in self.inbound_addresses}
                    and self.has_tenant_assignment)

    @property
    def is_outbound_configured(self) -> bool:
        return bool(self.api_key and self.verified_from_email and self.outbound_enabled
                    and self.test_recipients and self.has_tenant_assignment)


class WhatsAppChannelConfig(ChannelConfigBase):
    """Configuration for Meta WhatsApp Cloud API webhooks."""
    phone_number_id: str | None = None
    access_token: str | None = None
    app_secret: str | None = None
    verify_token: str | None = None
    tenant_id: str = "synthetic_tenant_a"
    api_base_url: str = "https://graph.facebook.com/v26.0"
    outbound_enabled: bool = False
    test_recipient_ids: list[str] = Field(default_factory=list)
    approved_templates: list[str] = Field(default_factory=list)

    @property
    def is_configured(self) -> bool:
        return bool(
            self.phone_number_id
            and self.access_token
            and self.app_secret
            and self.verify_token
            and self.has_tenant_assignment
        )

    @property
    def can_verify_webhook(self) -> bool:
        return bool(self.verify_token)


class ChannelsConfig(ChannelConfigBase):
    """Master configuration container for all real inbound channels."""
    telegram: TelegramChannelConfig = Field(default_factory=TelegramChannelConfig)
    gmail: GmailChannelConfig = Field(default_factory=GmailChannelConfig)
    whatsapp: WhatsAppChannelConfig = Field(default_factory=WhatsAppChannelConfig)
    resend: ResendChannelConfig = Field(default_factory=ResendChannelConfig)

    @classmethod
    def load_from_env(cls) -> ChannelsConfig:
        tenant_id = os.environ.get("P1_DEV_TENANT_ID", "synthetic_tenant_a")
        c1_bot_id = os.environ.get("TELEGRAM_BOT_ID")
        c2_bot_id = os.environ.get("TELEGRAM_BOT_ACCOUNT_ID")
        if c1_bot_id and c2_bot_id and c1_bot_id.strip() != c2_bot_id.strip():
            raise ValueError("Telegram account configuration aliases disagree")

        telegram = TelegramChannelConfig(
            bot_token=os.environ.get("TELEGRAM_BOT_TOKEN"),
            mode=os.environ.get("TELEGRAM_MODE", "polling").lower(),  # type: ignore[arg-type]
            webhook_url=os.environ.get("TELEGRAM_WEBHOOK_URL"),
            webhook_secret=os.environ.get("TELEGRAM_WEBHOOK_SECRET"),
            bot_account_id=os.environ.get("TELEGRAM_BOT_ID") or os.environ.get("TELEGRAM_BOT_ACCOUNT_ID"),
            outbound_enabled=os.environ.get("TELEGRAM_OUTBOUND_ENABLED", "false").lower() == "true",
            test_recipient_ids=[v.strip() for v in os.environ.get("TELEGRAM_TEST_RECIPIENT_IDS", "").split(",") if v.strip()],
            request_timeout_seconds=float(os.environ.get("CHANNEL_REQUEST_TIMEOUT_SECONDS", "10")),
            poll_interval_seconds=float(os.environ.get("TELEGRAM_POLL_INTERVAL", "2.0")),
            poll_timeout_seconds=int(os.environ.get("TELEGRAM_POLL_TIMEOUT", "20")),
            tenant_id=os.environ.get("TELEGRAM_TENANT_ID", tenant_id),
            api_base_url=os.environ.get("TELEGRAM_API_BASE_URL", "https://api.telegram.org"),
            auto_start=os.environ.get("TELEGRAM_AUTO_START", "true").lower() == "true",
        )

        cred_file = os.environ.get("GMAIL_CREDENTIALS_FILE")
        file_client_id = None
        file_client_secret = None
        file_redirect_uri = None
        file_auth_endpoint = None
        file_token_endpoint = None

        if cred_file:
            cred_path = Path(cred_file)
            if not cred_path.is_absolute():
                repo_root = Path(__file__).resolve().parents[4]
                if (repo_root / cred_file).is_file():
                    cred_path = repo_root / cred_file
                elif Path(cred_file).is_file():
                    cred_path = Path(cred_file)
            if cred_path.is_file():
                try:
                    cred_data = json.loads(cred_path.read_text(encoding="utf-8"))
                    oauth_info = cred_data.get("web") or cred_data.get("installed") or {}
                    file_client_id = oauth_info.get("client_id")
                    file_client_secret = oauth_info.get("client_secret")
                    uris = oauth_info.get("redirect_uris") or []
                    if uris:
                        file_redirect_uri = uris[0]
                    if oauth_info.get("auth_uri"):
                        file_auth_endpoint = oauth_info.get("auth_uri")
                    if oauth_info.get("token_uri"):
                        file_token_endpoint = oauth_info.get("token_uri")
                except Exception as exc:
                    logger.warning("Failed to parse GMAIL_CREDENTIALS_FILE %s: %s", cred_path, exc)

        gmail = GmailChannelConfig(
            client_id=os.environ.get("GMAIL_CLIENT_ID") or file_client_id,
            client_secret=os.environ.get("GMAIL_CLIENT_SECRET") or file_client_secret,
            refresh_token=os.environ.get("GMAIL_REFRESH_TOKEN"),
            mailbox_account_id=os.environ.get("GMAIL_ACCOUNT_EMAIL"),
            access_token=os.environ.get("GMAIL_ACCESS_TOKEN"),
            redirect_uri=os.environ.get("GMAIL_REDIRECT_URI") or file_redirect_uri or "http://localhost:8000/v1/channels/gmail/oauth/callback",
            poll_interval_seconds=float(os.environ.get("GMAIL_POLL_INTERVAL", "30.0")),
            query=os.environ.get("GMAIL_QUERY", "label:INBOX"),
            tenant_id=os.environ.get("GMAIL_TENANT_ID", tenant_id),
            api_base_url=os.environ.get("GMAIL_API_BASE_URL", "https://gmail.googleapis.com"),
            token_endpoint=file_token_endpoint or "https://oauth2.googleapis.com/token",
            auth_endpoint=file_auth_endpoint or "https://accounts.google.com/o/oauth2/v2/auth",
            auto_start=os.environ.get("GMAIL_AUTO_START", "true").lower() == "true",
            credentials_file=cred_file,
            request_timeout_seconds=float(os.environ.get("CHANNEL_REQUEST_TIMEOUT_SECONDS", "10")),
        )

        whatsapp = WhatsAppChannelConfig(
            phone_number_id=os.environ.get("WHATSAPP_PHONE_NUMBER_ID"),
            access_token=os.environ.get("WHATSAPP_ACCESS_TOKEN"),
            app_secret=os.environ.get("WHATSAPP_APP_SECRET"),
            verify_token=os.environ.get("WHATSAPP_VERIFY_TOKEN"),
            tenant_id=os.environ.get("WHATSAPP_TENANT_ID", tenant_id),
            api_base_url=os.environ.get("WHATSAPP_API_BASE_URL", "https://graph.facebook.com/v26.0"),
            outbound_enabled=os.environ.get("WHATSAPP_OUTBOUND_ENABLED", "false").lower() == "true",
            test_recipient_ids=[v.strip() for v in os.environ.get("WHATSAPP_TEST_RECIPIENT_IDS", "").split(",") if v.strip()],
            approved_templates=[v.strip() for v in os.environ.get("WHATSAPP_APPROVED_TEMPLATES", "").split(",") if v.strip()],
            request_timeout_seconds=float(os.environ.get("CHANNEL_REQUEST_TIMEOUT_SECONDS", "10")),
        )

        resend = ResendChannelConfig(
            account_id=os.environ.get("RESEND_ACCOUNT_ID"),
            api_key=os.environ.get("RESEND_API_KEY"),
            webhook_secret=os.environ.get("RESEND_WEBHOOK_SECRET"),
            tenant_id=os.environ.get("RESEND_TENANT_ID", tenant_id),
            api_base_url=os.environ.get("RESEND_API_BASE_URL", "https://api.resend.com"),
            inbound_addresses=[v.strip().lower() for v in os.environ.get("RESEND_INBOUND_ADDRESSES", "").split(",") if v.strip()],
            outbound_enabled=os.environ.get("RESEND_OUTBOUND_ENABLED", "false").lower() == "true",
            test_recipients=[v.strip().lower() for v in os.environ.get("RESEND_TEST_RECIPIENTS", "").split(",") if v.strip()],
            verified_from_email=os.environ.get("RESEND_VERIFIED_FROM_EMAIL"),
            reply_to_email=os.environ.get("RESEND_REPLY_TO_EMAIL"),
            max_attachment_bytes=int(os.environ.get("RESEND_MAX_ATTACHMENT_BYTES", str(10 * 1024 * 1024))),
            request_timeout_seconds=float(os.environ.get("CHANNEL_REQUEST_TIMEOUT_SECONDS", "10")),
        )

        return cls(telegram=telegram, gmail=gmail, whatsapp=whatsapp, resend=resend)
