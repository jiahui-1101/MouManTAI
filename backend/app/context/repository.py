"""Replaceable P1 repository boundary. No shared Core or identity operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .association_schemas import AssociationDecisionRequest, MessageAssociationRecord
from .attachment_validator import (
    AttachmentLimitExceeded,
    InvalidAttachmentPayload,
    UnsupportedAttachmentType,
)
from .document_schemas import AttachmentRecord, DocumentExtractionResult
from .ingestion_schemas import (
    ExtractionAttemptRecord,
    IngestResponse,
    MessagePage,
    ProcessResponse,
    StoredMessage,
)
from .order_context_schemas import (
    ContextReviewRecord,
    ContextReviewRequest,
    OrderContextRecord,
    OrderContextVersionRecord,
)
from .schemas import Channel, ProcessingStatus, RawMessageEnvelope


@dataclass(frozen=True)
class OrderContextSourceSnapshot:
    """One tenant-scoped, read-only P1 snapshot for order-context mapping."""

    context: OrderContextRecord
    context_versions: tuple[OrderContextVersionRecord, ...]
    context_reviews: tuple[ContextReviewRecord, ...]
    source_messages: tuple[StoredMessage, ...]
    associations: tuple[MessageAssociationRecord, ...]
    extraction_attempts: tuple[ExtractionAttemptRecord, ...]


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


class AssociationNotFound(Exception):
    """No association record exists for the requested message."""


class ContextNotFound(Exception):
    """The requested order context does not exist in the tenant scope."""


class StaleContextVersion(Exception):
    """The requested expected_context_version does not match the current version."""


class AttachmentNotFound(Exception):
    """The requested attachment does not exist in the tenant scope."""


class MessageRepository(Protocol):
    def ingest(self, envelope: RawMessageEnvelope, now: datetime) -> IngestResponse: ...
    def get(self, tenant_id: str, message_id: str) -> StoredMessage | None: ...
    def list(self, tenant_id: str, *, channel: Channel | None = None, search: str = "",
             processing_status: ProcessingStatus | None = None, limit: int = 25, offset: int = 0) -> MessagePage: ...
    def awaiting_processing(self, tenant_id: str, limit: int = 25) -> list[StoredMessage]: ...
    def process(self, tenant_id: str, message_id: str, *, reprocess: bool = False, now: datetime | None = None,
                operation_id: str | None = None) -> ProcessResponse: ...
    def get_latest_extraction(self, tenant_id: str, message_id: str) -> ExtractionAttemptRecord | None: ...
    def list_extraction_attempts(self, tenant_id: str, message_id: str) -> list[ExtractionAttemptRecord]: ...
    def get_association(self, tenant_id: str, message_id: str) -> MessageAssociationRecord | None: ...
    def save_association(self, record: MessageAssociationRecord) -> MessageAssociationRecord: ...
    def decide_association(self, tenant_id: str, message_id: str, request: AssociationDecisionRequest, actor_id: str, actor_role: str) -> MessageAssociationRecord: ...
    def get_order_context(self, tenant_id: str, context_id: str) -> OrderContextRecord | None: ...
    def get_order_context_by_order(self, tenant_id: str, order_id: str) -> OrderContextRecord | None: ...
    def get_order_context_by_message(self, tenant_id: str, message_id: str) -> OrderContextRecord | None: ...
    def save_order_context(self, record: OrderContextRecord, change_type: str = "INITIAL_CREATION", actor_id: str | None = None, actor_role: str | None = None, reason: str | None = None) -> OrderContextRecord: ...
    def update_order_context(self, tenant_id: str, context_id: str, expected_version: int, updates: dict, actor_id: str | None = None, actor_role: str | None = None, reason: str | None = None) -> OrderContextRecord: ...
    def apply_context_review(self, tenant_id: str, context_id: str, request: ContextReviewRequest, actor_id: str, actor_role: str) -> OrderContextRecord: ...
    def list_context_versions(self, tenant_id: str, context_id: str) -> list[OrderContextVersionRecord]: ...
    def list_context_reviews(self, tenant_id: str, context_id: str) -> list[ContextReviewRecord]: ...
    def read_order_context_source(
        self, tenant_id: str, context_id: str
    ) -> OrderContextSourceSnapshot | None: ...
    def save_attachment(self, tenant_id: str, attachment: AttachmentRecord, content: bytes) -> AttachmentRecord: ...
    def get_attachment(self, tenant_id: str, evidence_ref: str) -> tuple[AttachmentRecord, bytes] | None: ...
    def save_document_extraction(self, tenant_id: str, extraction: DocumentExtractionResult) -> DocumentExtractionResult: ...
    def get_document_extraction(self, tenant_id: str, evidence_ref: str) -> DocumentExtractionResult | None: ...

