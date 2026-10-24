"""Persistent cursor and state management for inbound channels.

Tracks:
- Telegram update offsets (preventing duplicate update deliveries across restarts).
- Gmail sync cursors and OAuth tokens.
- Channel operational status and diagnostics.

Supports file-backed persistent storage with in-memory caching and thread-safe locking.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ChannelStateManager:
    """Thread-safe persistent state manager for channel cursors and credentials."""

    def __init__(self, storage_path: Path | str | None = None):
        if storage_path is None:
            local_dir = Path(".local")
            local_dir.mkdir(parents=True, exist_ok=True)
            self.storage_path = local_dir / "channel_state.json"
        else:
            self.storage_path = Path(storage_path)

        self._lock = threading.RLock()
        self._state: dict[str, dict[str, Any]] = self._load()

    def _load(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            if self.storage_path.is_file():
                try:
                    data = json.loads(self.storage_path.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        return data
                except Exception as exc:
                    logger.warning("Could not read channel state from %s: %s", self.storage_path, exc)
            return {}

    def _save(self) -> None:
        with self._lock:
            try:
                self.storage_path.parent.mkdir(parents=True, exist_ok=True)
                temp_path = self.storage_path.with_suffix(".tmp")
                temp_path.write_text(json.dumps(self._state, indent=2, default=str), encoding="utf-8")
                temp_path.replace(self.storage_path)
            except Exception as exc:
                logger.error("Failed to persist channel state to %s: %s", self.storage_path, exc)

    def _get_channel_data(self, channel: str, tenant_id: str) -> dict[str, Any]:
        key = f"{channel.upper()}:{tenant_id}"
        if key not in self._state:
            self._state[key] = {
                "channel": channel.upper(),
                "tenant_id": tenant_id,
                "cursor": None,
                "tokens": {},
                "seen_ids": [],
                "status": "UNCONFIGURED",
                "last_error": None,
                "last_poll_at": None,
                "last_success_at": None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        return self._state[key]

    # --- Telegram Cursor ---

    def get_telegram_offset(self, tenant_id: str) -> int | None:
        with self._lock:
            data = self._get_channel_data("TELEGRAM", tenant_id)
            cursor = data.get("cursor")
            return int(cursor) if cursor is not None else None

    def save_telegram_offset(self, tenant_id: str, offset: int) -> None:
        with self._lock:
            data = self._get_channel_data("TELEGRAM", tenant_id)
            data["cursor"] = offset
            data["last_success_at"] = datetime.now(timezone.utc).isoformat()
            data["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save()

    # --- Gmail Cursor and Tokens ---

    def get_gmail_cursor(self, tenant_id: str) -> int | None:
        with self._lock:
            data = self._get_channel_data("EMAIL", tenant_id)
            cursor = data.get("cursor")
            return int(cursor) if cursor is not None else None

    def save_gmail_cursor(self, tenant_id: str, internal_date: int) -> None:
        with self._lock:
            data = self._get_channel_data("EMAIL", tenant_id)
            data["cursor"] = internal_date
            data["last_success_at"] = datetime.now(timezone.utc).isoformat()
            data["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save()

    def get_gmail_tokens(self, tenant_id: str) -> dict[str, Any]:
        with self._lock:
            data = self._get_channel_data("EMAIL", tenant_id)
            return dict(data.get("tokens") or {})

    def save_gmail_tokens(self, tenant_id: str, tokens: dict[str, Any]) -> None:
        with self._lock:
            data = self._get_channel_data("EMAIL", tenant_id)
            data["tokens"] = tokens
            data["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save()

    # --- Deduplication Memory ---

    def has_seen_provider_id(self, channel: str, tenant_id: str, provider_id: str) -> bool:
        with self._lock:
            data = self._get_channel_data(channel, tenant_id)
            seen: list[str] = data.setdefault("seen_ids", [])
            return provider_id in seen

    def mark_seen_provider_id(self, channel: str, tenant_id: str, provider_id: str, max_history: int = 500) -> None:
        with self._lock:
            data = self._get_channel_data(channel, tenant_id)
            seen: list[str] = data.setdefault("seen_ids", [])
            if provider_id not in seen:
                seen.append(provider_id)
                if len(seen) > max_history:
                    seen.pop(0)
                data["updated_at"] = datetime.now(timezone.utc).isoformat()
                self._save()

    # --- Operational Status ---

    def set_status(
        self,
        channel: str,
        tenant_id: str,
        status: str,
        last_error: str | None = None,
    ) -> None:
        with self._lock:
            data = self._get_channel_data(channel, tenant_id)
            data["status"] = status
            data["last_error"] = last_error
            data["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save()

    def record_poll_attempt(self, channel: str, tenant_id: str, error: str | None = None) -> None:
        with self._lock:
            data = self._get_channel_data(channel, tenant_id)
            now = datetime.now(timezone.utc).isoformat()
            data["last_poll_at"] = now
            if error:
                data["last_error"] = error
            else:
                data["last_success_at"] = now
                data["last_error"] = None
            data["updated_at"] = now
            self._save()

    def get_channel_summary(self, channel: str, tenant_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._get_channel_data(channel, tenant_id))


_global_state_manager: ChannelStateManager | None = None


def get_state_manager() -> ChannelStateManager:
    global _global_state_manager
    if _global_state_manager is None:
        _global_state_manager = ChannelStateManager()
    return _global_state_manager
