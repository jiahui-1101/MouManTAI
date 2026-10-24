"""P1 Channel Manager: orchestrates inbound channels and polling worker lifecycles."""

from __future__ import annotations

import logging
from typing import Any

from app.context.dependencies import local_repository
from app.context.repository import MessageRepository

from .config import ChannelsConfig
from .gmail import GmailAdapter
from .state import ChannelStateManager, get_state_manager
from .telegram import TelegramAdapter
from .whatsapp import WhatsAppAdapter

logger = logging.getLogger(__name__)


class ChannelManager:
    """Central lifecycle orchestrator for P1 inbound channel adapters."""

    def __init__(
        self,
        config: ChannelsConfig | None = None,
        repository: MessageRepository | None = None,
        state_manager: ChannelStateManager | None = None,
    ):
        self.config = config or ChannelsConfig.load_from_env()
        self.repository = repository or local_repository()
        self.state_manager = state_manager or get_state_manager()

        self.telegram = TelegramAdapter(
            config=self.config.telegram,
            repository=self.repository,
            state_manager=self.state_manager,
        )
        self.gmail = GmailAdapter(
            config=self.config.gmail,
            repository=self.repository,
            state_manager=self.state_manager,
        )
        self.whatsapp = WhatsAppAdapter(
            config=self.config.whatsapp,
            repository=self.repository,
            state_manager=self.state_manager,
        )

    def start_configured_workers(self) -> None:
        """Start background polling workers for configured channels.

        Safe to invoke during application startup; non-configured channels are cleanly skipped.
        """
        # Telegram polling worker
        if self.config.telegram.is_configured and self.config.telegram.mode == "polling" and self.config.telegram.auto_start:
            try:
                self.telegram.start_polling()
            except Exception as exc:
                logger.error("Failed starting Telegram polling worker: %s", exc)
        else:
            logger.info("Telegram polling worker not started (configured=%s, mode=%s)",
                        self.config.telegram.is_configured, self.config.telegram.mode)

        # Gmail polling worker
        if not self.config.gmail.refresh_token:
            saved_tokens = self.state_manager.get_gmail_tokens(self.config.gmail.tenant_id)
            if saved_tokens.get("refresh_token"):
                self.config.gmail.refresh_token = saved_tokens["refresh_token"]
                self.config.gmail.access_token = saved_tokens.get("access_token")

        if self.config.gmail.is_configured and self.config.gmail.auto_start:
            try:
                self.gmail.start_polling()
            except Exception as exc:
                logger.error("Failed starting Gmail polling worker: %s", exc)
        else:
            logger.info("Gmail polling worker not started (configured=%s)", self.config.gmail.is_configured)

    def stop_all_workers(self) -> None:
        """Gracefully stop all running channel workers."""
        try:
            self.telegram.stop_polling()
        except Exception as exc:
            logger.warning("Error stopping Telegram polling: %s", exc)

        try:
            self.gmail.stop_polling()
        except Exception as exc:
            logger.warning("Error stopping Gmail polling: %s", exc)

    def poll_all_now(self) -> dict[str, Any]:
        """Trigger an immediate synchronous poll cycle on all configured polling channels."""
        results: dict[str, Any] = {}

        if self.config.telegram.is_configured and self.config.telegram.mode == "polling":
            try:
                count = self.telegram.poll_once()
                results["telegram"] = {"status": "ok", "processed": count}
            except Exception as exc:
                results["telegram"] = {"status": "error", "error": str(exc)}
        else:
            results["telegram"] = {"status": "skipped", "reason": "Not configured for polling"}

        if self.config.gmail.is_configured:
            try:
                count = self.gmail.poll_inbox()
                results["gmail"] = {"status": "ok", "processed": count}
            except Exception as exc:
                results["gmail"] = {"status": "error", "error": str(exc)}
        else:
            results["gmail"] = {"status": "skipped", "reason": "Not configured"}

        return results

    def get_status(self) -> dict[str, Any]:
        """Return operational and configuration status across all three channels."""
        tg_summary = self.state_manager.get_channel_summary("TELEGRAM", self.config.telegram.tenant_id)
        gm_summary = self.state_manager.get_channel_summary("EMAIL", self.config.gmail.tenant_id)
        wa_summary = self.state_manager.get_channel_summary("WHATSAPP", self.config.whatsapp.tenant_id)

        return {
            "telegram": {
                "configured": self.config.telegram.is_configured,
                "mode": self.config.telegram.mode,
                "is_polling": self.telegram.is_polling,
                "tenant_id": self.config.telegram.tenant_id,
                "last_offset": tg_summary.get("cursor"),
                "status": tg_summary.get("status", "UNCONFIGURED" if not self.config.telegram.is_configured else "READY"),
                "last_poll_at": tg_summary.get("last_poll_at"),
                "last_error": tg_summary.get("last_error"),
            },
            "gmail": {
                "configured": self.config.gmail.is_configured,
                "can_authorize": self.config.gmail.can_authorize,
                "is_polling": self.gmail.is_polling,
                "tenant_id": self.config.gmail.tenant_id,
                "last_cursor": gm_summary.get("cursor"),
                "status": gm_summary.get("status", "UNCONFIGURED" if not self.config.gmail.is_configured else "READY"),
                "last_poll_at": gm_summary.get("last_poll_at"),
                "last_error": gm_summary.get("last_error"),
            },
            "whatsapp": {
                "configured": self.config.whatsapp.is_configured,
                "can_verify_webhook": self.config.whatsapp.can_verify_webhook,
                "tenant_id": self.config.whatsapp.tenant_id,
                "status": wa_summary.get("status", "UNCONFIGURED" if not self.config.whatsapp.is_configured else "WEBHOOK_READY"),
                "last_poll_at": wa_summary.get("last_poll_at"),
                "last_error": wa_summary.get("last_error"),
            },
        }


_global_channel_manager: ChannelManager | None = None


def get_channel_manager() -> ChannelManager:
    global _global_channel_manager
    if _global_channel_manager is None:
        _global_channel_manager = ChannelManager()
    return _global_channel_manager
