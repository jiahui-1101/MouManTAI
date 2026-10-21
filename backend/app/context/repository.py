"""Replaceable P1 repository boundary. No shared Core or identity operations."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from .ingestion_schemas import ExtractionAttemptRecord, IngestResponse, MessagePage, ProcessResponse, StoredMessage
from .schemas import Channel, ProcessingStatus, RawMessageEnvelope


class DuplicateConflict(Exception):
    """The delivery key already exists with different immutable content."""


class PersistenceUnavailable(Exception):
    """Sanitized storage failure. Never expose connection strings to callers."""


class MessageNotFound(Exception):
    """The requested message does not exist in the tenant scope."""


class ProcessingConflict(Exception):
    """The message is concurrently undergoing processing."""


class ExtractionNotFound(Exception):
    """No extraction attempt exists for the requested message."""


class MessageRepository(Protocol):
    def ingest(self, envelope: RawMessageEnvelope, now: datetime) -> IngestResponse: ...
    def get(self, tenant_id: str, message_id: str) -> StoredMessage | None: ...
    def list(self, tenant_id: str, *, channel: Channel | None = None, search: str = "",
             processing_status: ProcessingStatus | None = None, limit: int = 25, offset: int = 0) -> MessagePage: ...
    def awaiting_processing(self, tenant_id: str, limit: int = 25) -> list[StoredMessage]: ...
    def process(self, tenant_id: str, message_id: str, *, reprocess: bool = False, now: datetime | None = None) -> ProcessResponse: ...
    def get_latest_extraction(self, tenant_id: str, message_id: str) -> ExtractionAttemptRecord | None: ...
    def list_extraction_attempts(self, tenant_id: str, message_id: str) -> list[ExtractionAttemptRecord]: ...
