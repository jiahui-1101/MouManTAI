"""Replaceable P1 repository boundary. No shared Core or identity operations."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .ingestion_schemas import IngestResponse, MessagePage, StoredMessage
from .schemas import Channel, ProcessingStatus, RawMessageEnvelope


class DuplicateConflict(Exception):
    """The delivery key already exists with different immutable content."""


class PersistenceUnavailable(Exception):
    """Sanitized storage failure. Never expose connection strings to callers."""


class MessageRepository(Protocol):
    def ingest(self, envelope: RawMessageEnvelope, now: datetime) -> IngestResponse: ...
    def get(self, tenant_id: str, message_id: str) -> StoredMessage | None: ...
    def list(self, tenant_id: str, *, channel: Channel | None = None, search: str = "",
             processing_status: ProcessingStatus | None = None, limit: int = 25, offset: int = 0) -> MessagePage: ...
    def awaiting_processing(self, tenant_id: str, limit: int = 25) -> list[StoredMessage]: ...
