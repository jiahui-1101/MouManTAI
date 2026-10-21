"""PROVISIONAL P1-local types derived from REQUIREMENTS_SYSTEM §3.1.

These are not approved shared contracts. Replace/map after P5 review.
Validation checks shape and local consistency, not authorization or identity proof.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field,
    StringConstraints, field_validator, model_validator,
)

Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Channel = Literal["WHATSAPP", "EMAIL", "TELEGRAM", "UNKNOWN"]
ProcessingStatus = Literal["RECEIVED", "PROCESSING", "PROCESSED", "PROCESSING_FAILED"]
Readiness = Literal["READY", "PARTIAL", "CONFLICT", "UNRESOLVED"]
IdentityStatus = Literal["LINK_VERIFIED", "UNVERIFIED", "AMBIGUOUS"]
ReviewStatus = Literal["NOT_REQUIRED", "PENDING", "ACCEPTED", "CORRECTED", "UNRESOLVED"]


def utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


Timestamp = Annotated[AwareDatetime, AfterValidator(utc)]


class P1Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)


class Attachment(P1Model):
    attachment_id: Identifier
    filename: Identifier
    media_type: Identifier
    size_bytes: int = Field(ge=0, le=25_000_000)
    # Opaque evidence reference, never a client-controlled local filesystem path.
    evidence_ref: Identifier


class RawMessageEnvelope(P1Model):
    tenant_id: Identifier
    channel: Channel
    provider_message_id: Identifier
    sender_identity_id: Identifier
    sender_alias: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    received_at: Timestamp
    message_at: Timestamp | None = None
    business_timezone: str | None = Field(default="Asia/Kuala_Lumpur", max_length=100)
    text: str = Field(min_length=1, max_length=20_000)
    attachments: list[Attachment] = Field(default_factory=list, max_length=10)
    thread_ref: str | None = Field(default=None, max_length=200)
    reply_to_provider_message_id: str | None = Field(default=None, max_length=200)
    language: str | None = Field(default=None, max_length=35)
    adapter_mode: Literal["SYNTHETIC"] = "SYNTHETIC"

    @model_validator(mode="after")
    def supported_original_content(self):
        if not self.text.strip() or not self.sender_alias.strip():
            raise ValueError("message text and sender alias must contain non-whitespace characters")
        def contains_nul(value):
            if isinstance(value, str):
                return "\x00" in value
            if isinstance(value, list):
                return any(contains_nul(item) for item in value)
            if isinstance(value, dict):
                return any(contains_nul(item) for item in value.values())
            return False
        if contains_nul(self.model_dump()):
            raise ValueError("NUL characters cannot be persisted in PostgreSQL JSONB")
        return self

    @field_validator("business_timezone")
    @classmethod
    def known_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("business_timezone must be an IANA timezone") from exc
        return value


class FieldEvidence(P1Model):
    evidence_id: Identifier
    message_id: Identifier
    quote: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    method: Literal["FIXTURE", "RULE", "MODEL", "HUMAN"]
    method_version: Identifier

    @model_validator(mode="after")
    def valid_span(self):
        if self.end <= self.start or len(self.quote) != self.end - self.start:
            raise ValueError("evidence offsets must match quote length (Unicode code points)")
        return self


class ExtractedField(P1Model):
    field_name: Literal["customer_id", "sku", "quantity", "unit", "requested_delivery_at", "special_instructions", "order_id"]
    value: str | None
    validation_status: Literal["VALID", "MISSING", "INVALID", "UNRESOLVED", "CONFLICT"]
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence: list[FieldEvidence] = Field(default_factory=list)
    corrected_by: str | None = None
    qualifier: Literal["EXACT", "DEADLINE", "DATE_ONLY"] | None = None
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def grounded_value(self):
        if self.validation_status == "VALID" and (not self.value or not self.evidence):
            raise ValueError("valid extracted values require source evidence")
        if self.validation_status == "MISSING" and self.value is not None:
            raise ValueError("missing fields cannot contain a value")
        return self


class NormalizedMessage(P1Model):
    message_id: Identifier
    raw: RawMessageEnvelope
    content_sha256: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    processing_status: ProcessingStatus
    fields: list[ExtractedField] = Field(default_factory=list)
    diagnostic: str | None = None

    @model_validator(mode="after")
    def evidence_matches_original(self):
        for item in self.fields:
            for evidence in item.evidence:
                if evidence.message_id != self.message_id:
                    raise ValueError("evidence must reference this message")
                if self.raw.text[evidence.start:evidence.end] != evidence.quote:
                    raise ValueError("evidence quote must match original text span")
        if self.processing_status == "PROCESSING_FAILED" and not self.diagnostic:
            raise ValueError("failed processing requires a diagnostic")
        return self


class RequestedItem(P1Model):
    sku: Identifier
    quantity: Annotated[str, StringConstraints(pattern=r"^\d+(\.\d+)?$")]
    unit: Literal["pcs", "kg", "box"]

    @field_validator("quantity")
    @classmethod
    def positive_quantity(cls, value: str) -> str:
        if Decimal(value) <= 0:
            raise ValueError("quantity must be a positive decimal string")
        return value


class BusinessContext(P1Model):
    tenant_id: Identifier
    context_id: Identifier
    source_message_ids: list[Identifier] = Field(min_length=1)
    customer_id: Identifier | None = None
    customer_identity_status: IdentityStatus
    order_id: Identifier | None = None
    requested_items: list[RequestedItem] = Field(default_factory=list)
    requested_delivery_at: Timestamp | None = None
    field_evidence: dict[str, list[Identifier]] = Field(default_factory=dict)
    conflicts: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    context_version: int = Field(ge=1)
    status: Readiness

    @model_validator(mode="after")
    def readiness_consistency(self):
        if self.customer_identity_status != "LINK_VERIFIED" and (self.customer_id or self.order_id):
            raise ValueError("unverified/ambiguous identities must not assert linked IDs")
        if self.status == "READY" and (
            not self.requested_items or self.requested_delivery_at is None
            or self.conflicts or self.missing_fields
        ):
            raise ValueError("READY requires items, delivery time and no missing/conflicting fields")
        if self.status == "CONFLICT" and not self.conflicts:
            raise ValueError("CONFLICT requires a conflict description")
        if self.status == "PARTIAL" and not self.missing_fields:
            raise ValueError("PARTIAL requires missing fields")
        return self


class ContextReview(P1Model):
    tenant_id: Identifier
    context_id: Identifier
    review_id: Identifier
    expected_context_version: int = Field(ge=1)
    status: ReviewStatus
    actor_id: str | None = None
    reviewed_at: Timestamp | None = None
    note: str | None = None

    @model_validator(mode="after")
    def completed_review_has_actor(self):
        if self.status in {"ACCEPTED", "CORRECTED"} and (not self.actor_id or self.reviewed_at is None):
            raise ValueError("completed review requires actor and timestamp; authorization is external")
        return self
