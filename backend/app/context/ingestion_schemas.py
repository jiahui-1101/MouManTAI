"""P1-local ingestion contracts, provisional pending P5 review."""

from typing import Literal

from pydantic import Field

from .schemas import ExtractedField, Identifier, P1Model, ProcessingStatus, RawMessageEnvelope, Timestamp


class StoredMessage(P1Model):
    message_id: Identifier
    raw: RawMessageEnvelope
    synthetic_provider: Literal["SYNTHETIC_WHATSAPP"]
    content_sha256: str
    processing_status: ProcessingStatus
    extractor_version: Identifier | None = None
    ingested_at: Timestamp
    updated_at: Timestamp


class IngestResponse(P1Model):
    message: StoredMessage
    duplicate: bool


class MessagePage(P1Model):
    items: list[StoredMessage]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0, le=10_000)


class ExtractionAttemptRecord(P1Model):
    attempt_id: Identifier
    tenant_id: Identifier
    message_id: Identifier
    extractor_version: Identifier
    input_content_sha256: str
    status: Literal["PROCESSING", "PROCESSED", "PROCESSING_FAILED"]
    fields: list[ExtractedField] = Field(default_factory=list)
    diagnostic: str | None = None
    started_at: Timestamp
    completed_at: Timestamp | None = None


class ProcessResponse(P1Model):
    message: StoredMessage
    attempt: ExtractionAttemptRecord
    reprocessed: bool


class ExtractionHistoryResponse(P1Model):
    items: list[ExtractionAttemptRecord]


class DevelopmentContext(P1Model):
    mode: Literal["LOCAL_SYNTHETIC_ONLY"] = "LOCAL_SYNTHETIC_ONLY"
    tenant_id: Identifier
    implemented_channel: Literal["WHATSAPP"] = "WHATSAPP"
    authentication: Literal["NOT_IMPLEMENTED"] = "NOT_IMPLEMENTED"


class ApiError(P1Model):
    detail: str
