"""Provisional P1 PostgreSQL tables. Explicit init only, separate from P5 migrations."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    desc,
    func,
    or_,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from .association_schemas import (
    AssociationCandidate,
    AssociationDecision,
    AssociationDecisionRequest,
    CustomerAccount,
    IdentityLinkStatus,
    MessageAssociationRecord,
    OrderReference,
)
from .deterministic_extraction import PROVISIONAL_PRODUCTS, VERSION, extract_explicit_fields
from .document_schemas import AttachmentRecord, DocumentEvidence, DocumentExtractionResult
from .ingestion_schemas import (
    ExtractionAttemptRecord,
    IngestResponse,
    MessagePage,
    ProcessResponse,
    StoredMessage,
)
from .order_context_schemas import (
    ContextReadinessStatus,
    ContextReviewRecord,
    ContextReviewRequest,
    OrderContextRecord,
    OrderContextVersionRecord,
    RequestedItem,
)
from .repository import (
    AssociationNotFound,
    ContextNotFound,
    DuplicateConflict,
    ExtractionNotFound,
    MessageNotFound,
    OrderContextSourceSnapshot,
    PersistenceUnavailable,
    ProcessingConflict,
    StaleContextVersion,
)
from .schemas import Channel, ExtractedField, ProcessingStatus, RawMessageEnvelope


def _to_json_compatible(val: Any) -> Any:
    """Recursively convert datetime and pydantic models to JSON-safe primitives for JSONB columns."""
    if val is None or isinstance(val, (int, float, str, bool)):
        return val
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    if isinstance(val, list):
        return [_to_json_compatible(item) for item in val]
    if isinstance(val, dict):
        return {k: _to_json_compatible(v) for k, v in val.items()}
    if hasattr(val, "model_dump"):
        return val.model_dump(mode="json")
    return str(val)


class P1Base(DeclarativeBase):
    pass


class ExtractionAttempt(P1Base):
    __tablename__ = "extraction_attempts"
    __table_args__ = (
        CheckConstraint("status IN ('PROCESSING', 'PROCESSED', 'PROCESSING_FAILED')", name="ck_p1_attempt_status"),
        Index("ix_p1_attempts_message", "tenant_id", "message_id", "started_at"),
        Index("ix_p1_attempts_fingerprint", "tenant_id", "message_id", "extractor_version", "input_content_sha256"),
        {"schema": "p1_dev"},
    )

    attempt_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(200), nullable=False)
    message_id: Mapped[str] = mapped_column(String(36), nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(50), nullable=False)
    input_content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    fields: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    diagnostic: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InboundMessage(P1Base):
    __tablename__ = "inbound_messages"
    __table_args__ = (
        Index(
            "uq_p1_delivery_legacy",
            "tenant_id",
            "channel",
            "provider_message_id",
            unique=True,
            postgresql_where=text("provider_account_id IS NULL"),
        ),
        Index(
            "uq_p1_delivery_scoped",
            "tenant_id",
            "provider",
            "provider_account_id",
            "provider_native_message_id",
            unique=True,
            postgresql_where=text("provider_account_id IS NOT NULL AND channel <> 'TELEGRAM'"),
        ),
        Index(
            "uq_p1_delivery_telegram_scoped",
            "tenant_id",
            "provider",
            "provider_account_id",
            "conversation_id",
            "provider_native_message_id",
            unique=True,
            postgresql_where=text("provider_account_id IS NOT NULL AND channel = 'TELEGRAM'"),
        ),
        Index(
            "ix_p1_parent_native_scope",
            "tenant_id",
            "provider",
            "provider_account_id",
            "conversation_id",
            "provider_native_message_id",
            postgresql_where=text("provider_account_id IS NOT NULL"),
        ),
        Index(
            "ix_p1_parent_rfc_scope",
            "tenant_id",
            "provider",
            "provider_account_id",
            "rfc_message_id",
            postgresql_where=text("provider_account_id IS NOT NULL AND rfc_message_id IS NOT NULL"),
        ),
        Index(
            "ix_p1_pending_parent_scope",
            "tenant_id",
            "provider",
            "provider_account_id",
            "conversation_id",
            "exact_parent_reference",
            postgresql_where=text("parent_resolution = 'UNRESOLVED' AND provider_account_id IS NOT NULL"),
        ),
        CheckConstraint(
            "(provider_account_id IS NULL) = (provider_native_message_id IS NULL)",
            name="ck_p1_provider_identity_pair",
        ),
        CheckConstraint(
            "parent_resolution IN ('NO_EXACT_PARENT', 'UNRESOLVED', 'AMBIGUOUS', 'REFERENCE_MATCH', 'LEGACY_UNKNOWN', 'INVALID')",
            name="ck_p1_parent_resolution",
        ),
        CheckConstraint(
            "source_authenticity IN ('VERIFIED', 'UNVERIFIED', 'SYNTHETIC')",
            name="ck_p1_source_authenticity",
        ),
        CheckConstraint("processing_status IN ('RECEIVED', 'PROCESSING', 'PROCESSED', 'PROCESSING_FAILED')", name="ck_p1_processing"),
        CheckConstraint(
            "(synthetic_provider IS NOT NULL AND ("
            "(channel = 'WHATSAPP' AND synthetic_provider = 'SYNTHETIC_WHATSAPP') OR "
            "(channel = 'EMAIL' AND synthetic_provider = 'SYNTHETIC_EMAIL') OR "
            "(channel = 'TELEGRAM' AND synthetic_provider = 'SYNTHETIC_TELEGRAM') OR "
            "(channel = 'UNKNOWN' AND synthetic_provider = 'SYNTHETIC_UNKNOWN')"
            ") AND provider = 'SYNTHETIC') OR "
            "(synthetic_provider IS NULL AND provider IN ('TELEGRAM_BOT_API', 'GMAIL_API', 'WHATSAPP_CLOUD_API', 'REAL') AND channel IN ('WHATSAPP', 'EMAIL', 'TELEGRAM', 'UNKNOWN'))",
            name="ck_p1_provenance",
        ),
        Index("ix_p1_inbox", "tenant_id", "ingested_at", "message_id"),
        {"schema": "p1_dev"},
    )

    message_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(200), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_message_id: Mapped[str] = mapped_column(String(200), nullable=False)
    provider_account_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    provider_native_message_id: Mapped[str | None] = mapped_column(String(998), nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(String(998), nullable=True)
    rfc_message_id: Mapped[str | None] = mapped_column(String(998), nullable=True)
    exact_parent_reference: Mapped[str | None] = mapped_column(String(998), nullable=True)
    parent_resolution: Mapped[str] = mapped_column(String(24), nullable=False, default="LEGACY_UNKNOWN", server_default="LEGACY_UNKNOWN")
    resolved_parent_message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_authenticity: Mapped[str] = mapped_column(String(20), nullable=False, default="UNVERIFIED", server_default="UNVERIFIED")
    synthetic_provider: Mapped[str | None] = mapped_column(String(30), nullable=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="SYNTHETIC")
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False)
    immutable_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    processing_status: Mapped[str] = mapped_column(String(30), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MessageAssociation(P1Base):
    __tablename__ = "message_associations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "message_id", name="uq_p1_message_association"),
        Index("ix_p1_assoc_message", "tenant_id", "message_id"),
        {"schema": "p1_dev"},
    )

    association_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(200), nullable=False)
    message_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    verified_customer: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    verified_order: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    candidates: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    conflicts: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    last_decision: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    version: Mapped[int] = mapped_column(nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OrderContext(P1Base):
    __tablename__ = "order_contexts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "context_id", name="uq_p1_order_context"),
        Index("ix_p1_ctx_order", "tenant_id", "order_id"),
        {"schema": "p1_dev"},
    )

    context_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(200), nullable=False)
    order_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    customer_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    customer_identity_status: Mapped[str] = mapped_column(String(30), nullable=False, default="UNVERIFIED")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="UNRESOLVED")
    context_version: Mapped[int] = mapped_column(nullable=False, default=1)
    requested_items: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, default=list)
    requested_delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_qualifier: Mapped[str | None] = mapped_column(String(30), nullable=True)
    special_instructions: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    source_message_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    field_evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    missing_fields: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    conflicts: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    last_reviewed_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_reviewed_role: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    core_commitment_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    published_to_core_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OrderContextVersion(P1Base):
    __tablename__ = "order_context_versions"
    __table_args__ = (
        Index("ix_p1_ctx_version", "tenant_id", "context_id", "context_version"),
        {"schema": "p1_dev"},
    )

    version_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    context_id: Mapped[str] = mapped_column(String(36), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(200), nullable=False)
    context_version: Mapped[int] = mapped_column(nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    change_type: Mapped[str] = mapped_column(String(50), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    actor_role: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ContextReview(P1Base):
    __tablename__ = "context_reviews"
    __table_args__ = (
        Index("ix_p1_review_context", "tenant_id", "context_id"),
        {"schema": "p1_dev"},
    )

    review_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(200), nullable=False)
    context_id: Mapped[str] = mapped_column(String(36), nullable=False)
    context_version_before: Mapped[int] = mapped_column(nullable=False)
    context_version_after: Mapped[int] = mapped_column(nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(200), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(50), nullable=False)
    field_changes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    note: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AttachmentModel(P1Base):
    __tablename__ = "attachments"
    __table_args__ = (
        Index("ix_p1_attachments_evidence_ref", "tenant_id", "evidence_ref", unique=True),
        {"schema": "p1_dev"},
    )

    attachment_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    evidence_ref: Mapped[str] = mapped_column(String(100), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DocumentExtractionModel(P1Base):
    __tablename__ = "document_extractions"
    __table_args__ = (
        Index("ix_p1_doc_extractions_att", "tenant_id", "attachment_id"),
        {"schema": "p1_dev"},
    )

    tenant_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    evidence_ref: Mapped[str] = mapped_column(String(100), primary_key=True)
    attachment_id: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    document_type: Mapped[str] = mapped_column(String(50), nullable=False)
    page_count: Mapped[int] = mapped_column(nullable=False, default=0)
    text_content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def fingerprint(envelope: RawMessageEnvelope) -> str:
    # received_at is delivery observation time; an identical retry may arrive later.
    content = envelope.model_dump(mode="json", exclude={"received_at"})
    canonical = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


_CHANNEL_PROVIDER = {
    "TELEGRAM": "TELEGRAM_BOT_API",
    "EMAIL": "GMAIL_API",
    "WHATSAPP": "WHATSAPP_CLOUD_API",
    "UNKNOWN": "REAL",
}


def _frame_from_envelope(envelope: RawMessageEnvelope, *, parent: bool = False) -> ReplyFrame | None:
    from .channels.reply_framing import FramingError, ReplyFrame

    if not envelope.provider_account_id or not envelope.provider_native_message_id:
        return None
    provider = {"TELEGRAM": "TELEGRAM", "EMAIL": "EMAIL", "WHATSAPP": "WHATSAPP"}.get(envelope.channel)
    if provider is None:
        return None
    exact_parent_id = None
    if not parent:
        if provider == "EMAIL":
            exact_parent_id = (envelope.rfc_in_reply_to or [None])[0]
        else:
            exact_parent_id = envelope.reply_to_provider_message_id
    try:
        return ReplyFrame(
            tenant_id=envelope.tenant_id,
            provider=provider,
            account_id=envelope.provider_account_id,
            native_message_id=envelope.provider_native_message_id,
            sender_id=envelope.sender_identity_id,
            conversation_id=envelope.conversation_id,
            exact_parent_id=exact_parent_id,
            relationship_source=envelope.relationship_source if exact_parent_id else "NONE",
            rfc_message_id=envelope.rfc_message_id,
            in_reply_to=tuple(envelope.rfc_in_reply_to),
            references=tuple(envelope.rfc_references),
            attachment_source_ids=tuple(envelope.native_attachment_source_ids),
        )
    except (FramingError, ValueError):
        return None


def _parent_reference(envelope: RawMessageEnvelope) -> str | None:
    if envelope.channel == "EMAIL":
        return (envelope.rfc_in_reply_to or [None])[0] or envelope.reply_to_provider_message_id
    return envelope.reply_to_provider_message_id


def _scope_lock_key(frame: ReplyFrame, native_id: str) -> str:
    conversation = "" if frame.provider == "EMAIL" else (frame.conversation_id or "")
    return "\x1f".join((frame.tenant_id, frame.provider, frame.account_id, conversation, native_id))


def _row_frame(row: InboundMessage) -> ReplyFrame | None:
    if not row.provider_account_id or not row.provider_native_message_id or row.source_authenticity != "VERIFIED":
        return None
    try:
        raw = RawMessageEnvelope.model_validate(row.raw)
        return _frame_from_envelope(raw, parent=True)
    except ValidationError:
        return None


def stored(row: InboundMessage, extractor_version: str | None = None) -> StoredMessage:
    raw_mode = row.raw.get("adapter_mode")
    row_provider = getattr(row, "provider", None) or "SYNTHETIC"
    is_real = raw_mode == "REAL" or row_provider in ("TELEGRAM_BOT_API", "GMAIL_API", "WHATSAPP_CLOUD_API") or row.synthetic_provider is None
    if is_real:
        if row.channel == "TELEGRAM":
            source_label = "Telegram"
            provider_name = row_provider if row_provider != "SYNTHETIC" else "TELEGRAM_BOT_API"
        elif row.channel == "EMAIL":
            source_label = "Gmail"
            provider_name = row_provider if row_provider != "SYNTHETIC" else "GMAIL_API"
        elif row.channel == "WHATSAPP":
            source_label = "WhatsApp"
            provider_name = row_provider if row_provider != "SYNTHETIC" else "WHATSAPP_CLOUD_API"
        else:
            source_label = row.channel.capitalize()
            provider_name = row_provider if row_provider != "SYNTHETIC" else "REAL"
        synthetic_prov = None
    else:
        source_label = "Synthetic"
        provider_name = "SYNTHETIC"
        synthetic_prov = row.synthetic_provider
    return StoredMessage(
        message_id=row.message_id,
        raw=RawMessageEnvelope(**row.raw),
        synthetic_provider=synthetic_prov,
        provider=provider_name,
        source_label=source_label,
        content_sha256=row.content_sha256,
        processing_status=row.processing_status,
        extractor_version=extractor_version,
        ingested_at=row.ingested_at,
        updated_at=row.updated_at,
    )


def attempt_record(row: ExtractionAttempt) -> ExtractionAttemptRecord:
    fields = [ExtractedField.model_validate(f) for f in (row.fields or [])]
    return ExtractionAttemptRecord(
        attempt_id=row.attempt_id,
        tenant_id=row.tenant_id,
        message_id=row.message_id,
        extractor_version=row.extractor_version,
        input_content_sha256=row.input_content_sha256,
        status=row.status,
        fields=fields,
        diagnostic=row.diagnostic,
        started_at=row.started_at,
        completed_at=row.completed_at,
    )


def association_record(row: MessageAssociation) -> MessageAssociationRecord:
    verified_cust = CustomerAccount.model_validate(row.verified_customer) if row.verified_customer else None
    verified_ord = OrderReference.model_validate(row.verified_order) if row.verified_order else None
    candidates = [AssociationCandidate.model_validate(c) for c in (row.candidates or [])]
    last_decision = AssociationDecision.model_validate(row.last_decision) if row.last_decision else None
    return MessageAssociationRecord(
        association_id=row.association_id,
        tenant_id=row.tenant_id,
        message_id=row.message_id,
        status=IdentityLinkStatus(row.status),
        verified_customer=verified_cust,
        verified_order=verified_ord,
        candidates=candidates,
        conflicts=list(row.conflicts or []),
        last_decision=last_decision,
        version=row.version,
        updated_at=row.updated_at,
    )


def order_context_record(row: OrderContext) -> OrderContextRecord:
    items = [RequestedItem.model_validate(it) for it in (row.requested_items or [])]
    return OrderContextRecord(
        context_id=row.context_id,
        tenant_id=row.tenant_id,
        order_id=row.order_id,
        customer_id=row.customer_id,
        customer_identity_status=row.customer_identity_status,  # type: ignore
        status=row.status,  # type: ignore
        context_version=row.context_version,
        requested_items=items,
        requested_delivery_at=row.requested_delivery_at,
        delivery_qualifier=row.delivery_qualifier,
        special_instructions=row.special_instructions,
        source_message_ids=list(row.source_message_ids or []),
        field_evidence=dict(row.field_evidence or {}),
        missing_fields=list(row.missing_fields or []),
        conflicts=list(row.conflicts or []),
        last_reviewed_by=row.last_reviewed_by,
        last_reviewed_role=row.last_reviewed_role,
        last_reviewed_at=row.last_reviewed_at,
        core_commitment_id=getattr(row, "core_commitment_id", None),
        published_to_core_at=getattr(row, "published_to_core_at", None),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def order_context_version_record(row: OrderContextVersion) -> OrderContextVersionRecord:
    return OrderContextVersionRecord(
        version_id=row.version_id,
        context_id=row.context_id,
        tenant_id=row.tenant_id,
        context_version=row.context_version,
        snapshot=dict(row.snapshot or {}),
        change_type=row.change_type,  # type: ignore
        actor_id=row.actor_id,
        actor_role=row.actor_role,
        reason=row.reason,
        created_at=row.created_at,
    )


def context_review_record(row: ContextReview) -> ContextReviewRecord:
    return ContextReviewRecord(
        review_id=row.review_id,
        tenant_id=row.tenant_id,
        context_id=row.context_id,
        context_version_before=row.context_version_before,
        context_version_after=row.context_version_after,
        action=row.action,  # type: ignore
        actor_id=row.actor_id,
        actor_role=row.actor_role,
        field_changes=dict(row.field_changes or {}),
        note=row.note,
        created_at=row.created_at,
    )


class PostgresMessageRepository:
    def __init__(self, engine: Engine, *, proposal_service=None, catalog=None):
        self.engine = engine
        self._proposal_service = proposal_service
        self.catalog = PROVISIONAL_PRODUCTS if catalog is None else catalog

    @property
    def proposal_service(self):
        if self._proposal_service is None:
            from .extraction import prepare_model_proposal_service
            self._proposal_service = prepare_model_proposal_service()
        return self._proposal_service

    def _candidate_parent_rows(self, session: Session, envelope: RawMessageEnvelope) -> list[InboundMessage]:
        frame = _frame_from_envelope(envelope)
        reference = _parent_reference(envelope)
        if frame is None or not reference or envelope.relationship_source not in {"PROVIDER_QUOTE", "SENDER_HEADER"}:
            return []
        filters = [
            InboundMessage.tenant_id == envelope.tenant_id,
            InboundMessage.channel == envelope.channel,
            InboundMessage.provider == _CHANNEL_PROVIDER[envelope.channel],
            InboundMessage.provider_account_id == envelope.provider_account_id,
            InboundMessage.source_authenticity == "VERIFIED",
        ]
        if envelope.channel == "EMAIL":
            filters.append(InboundMessage.rfc_message_id == reference)
        else:
            filters.extend((
                InboundMessage.conversation_id == envelope.conversation_id,
                InboundMessage.provider_native_message_id == reference,
            ))
        return list(session.scalars(select(InboundMessage).where(*filters)).all())

    def _resolve_parent_in_session(
        self, session: Session, envelope: RawMessageEnvelope
    ) -> tuple[ParentResolution, InboundMessage | None]:
        from .channels.reply_framing import ParentResolution, resolve_parent

        reference = _parent_reference(envelope)
        if not reference:
            return ParentResolution("NO_EXACT_PARENT"), None
        if envelope.framing_error:
            return ParentResolution("INVALID"), None
        if envelope.relationship_source not in {"PROVIDER_QUOTE", "SENDER_HEADER"}:
            return ParentResolution("UNRESOLVED"), None
        frame = _frame_from_envelope(envelope)
        if frame is None:
            return ParentResolution("UNRESOLVED"), None
        rows = self._candidate_parent_rows(session, envelope)
        frames = [candidate for row in rows if (candidate := _row_frame(row)) is not None]
        resolution = resolve_parent(frame, frames)
        if resolution.state != "REFERENCE_MATCH":
            return resolution, None
        matched = [row for row in rows if row.provider_native_message_id == resolution.parent_native_id]
        if len(matched) != 1:
            return ParentResolution("AMBIGUOUS"), None
        return resolution, matched[0]

    @staticmethod
    def _lock_parent_scopes(session: Session, envelope: RawMessageEnvelope) -> None:
        frame = _frame_from_envelope(envelope, parent=True)
        if frame is None:
            return
        own_reference = envelope.rfc_message_id if envelope.channel == "EMAIL" else envelope.provider_native_message_id
        references = {own_reference, _parent_reference(envelope)} - {None}
        for reference in sorted(references):
            lock_key = _scope_lock_key(frame, reference)
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
                {"lock_key": lock_key},
            )

    def _reconcile_waiting_children(self, session: Session, parent: InboundMessage) -> None:
        if parent.source_authenticity != "VERIFIED" or not parent.provider_account_id:
            return
        parent_target = parent.rfc_message_id if parent.channel == "EMAIL" else parent.provider_native_message_id
        if not parent_target:
            return
        filters = [
            InboundMessage.tenant_id == parent.tenant_id,
            InboundMessage.channel == parent.channel,
            InboundMessage.provider == parent.provider,
            InboundMessage.provider_account_id == parent.provider_account_id,
            InboundMessage.exact_parent_reference == parent_target,
            InboundMessage.parent_resolution.in_(["UNRESOLVED", "REFERENCE_MATCH", "AMBIGUOUS"]),
        ]
        if parent.channel != "EMAIL":
            filters.append(InboundMessage.conversation_id == parent.conversation_id)
        children = session.scalars(select(InboundMessage).where(*filters).with_for_update()).all()
        for child in children:
            try:
                envelope = RawMessageEnvelope.model_validate(child.raw)
            except ValidationError:
                child.parent_resolution = "INVALID"
                child.resolved_parent_message_id = None
                continue
            resolution, parent_row = self._resolve_parent_in_session(session, envelope)
            child.parent_resolution = resolution.state
            child.resolved_parent_message_id = parent_row.message_id if parent_row else None

    def resolve_exact_parent(self, tenant_id: str, message_id: str) -> ParentResolution:
        """Read the durable exact-parent result; thread/sender are never consulted."""
        from .channels.reply_framing import ParentResolution

        try:
            with Session(self.engine) as session:
                child = session.scalar(select(InboundMessage).where(
                    InboundMessage.tenant_id == tenant_id,
                    InboundMessage.message_id == message_id,
                ))
                if child is None:
                    return ParentResolution("UNRESOLVED")
                if child.parent_resolution != "REFERENCE_MATCH" or not child.resolved_parent_message_id:
                    return ParentResolution(child.parent_resolution)  # type: ignore[arg-type]
                parent = session.scalar(select(InboundMessage).where(
                    InboundMessage.tenant_id == tenant_id,
                    InboundMessage.message_id == child.resolved_parent_message_id,
                ))
                if parent is None:
                    return ParentResolution("UNRESOLVED")
                return ParentResolution("REFERENCE_MATCH", parent.provider_native_message_id)
        except SQLAlchemyError:
            raise PersistenceUnavailable("Parent lookup temporarily unavailable") from None

    def get_contexts_by_exact_parent(self, tenant_id: str, message_id: str) -> list[OrderContextRecord]:
        """Return active context(s) sourced by the unique, resolved parent message."""
        try:
            with Session(self.engine) as session:
                child = session.scalar(select(InboundMessage).where(
                    InboundMessage.tenant_id == tenant_id,
                    InboundMessage.message_id == message_id,
                    InboundMessage.parent_resolution == "REFERENCE_MATCH",
                ))
                if child is None or not child.resolved_parent_message_id:
                    return []
                rows = session.scalars(select(OrderContext).where(
                    OrderContext.tenant_id == tenant_id,
                    OrderContext.source_message_ids.contains([child.resolved_parent_message_id]),
                    OrderContext.core_commitment_id.is_(None),
                    OrderContext.status.in_(["INFORMATION_PARTIAL", "UNRESOLVED", "CONFLICT"]),
                ).order_by(OrderContext.updated_at.desc())).all()
                return [order_context_record(row) for row in rows]
        except SQLAlchemyError:
            raise PersistenceUnavailable("Context lookup temporarily unavailable") from None

    def ingest(self, envelope: RawMessageEnvelope, now: datetime) -> IngestResponse:
        digest = fingerprint(envelope)
        is_real = envelope.adapter_mode == "REAL"
        provider = _CHANNEL_PROVIDER[envelope.channel] if is_real else "SYNTHETIC"
        frame = _frame_from_envelope(envelope, parent=True)
        parent_reference = _parent_reference(envelope)
        try:
            with Session(self.engine) as session, session.begin():
                self._lock_parent_scopes(session, envelope)
                resolution, parent_row = self._resolve_parent_in_session(session, envelope)
                exact_reference = parent_reference if envelope.relationship_source in {"PROVIDER_QUOTE", "SENDER_HEADER"} else None
                values = dict(
                    message_id=str(uuid4()),
                    tenant_id=envelope.tenant_id,
                    channel=envelope.channel,
                    provider_message_id=envelope.provider_message_id,
                    provider_account_id=envelope.provider_account_id,
                    provider_native_message_id=envelope.provider_native_message_id,
                    conversation_id=envelope.conversation_id,
                    rfc_message_id=envelope.rfc_message_id,
                    exact_parent_reference=exact_reference,
                    parent_resolution=resolution.state,
                    resolved_parent_message_id=parent_row.message_id if parent_row else None,
                    source_authenticity=envelope.source_authenticity,
                    synthetic_provider=(None if is_real else f"SYNTHETIC_{envelope.channel}"),
                    provider=provider,
                    raw=envelope.model_dump(mode="json"),
                    immutable_fingerprint=digest,
                    content_sha256=hashlib.sha256(envelope.text.encode("utf-8")).hexdigest(),
                    processing_status="RECEIVED",
                    ingested_at=now,
                    updated_at=now,
                )
                statement = insert(InboundMessage).values(**values).on_conflict_do_nothing().returning(InboundMessage.message_id)
                created_id = session.execute(statement).scalar_one_or_none()
                if envelope.provider_account_id and envelope.provider_native_message_id:
                    identity_filters = [
                        InboundMessage.tenant_id == envelope.tenant_id,
                        InboundMessage.provider == provider,
                        InboundMessage.provider_account_id == envelope.provider_account_id,
                        InboundMessage.provider_native_message_id == envelope.provider_native_message_id,
                    ]
                    if envelope.channel == "TELEGRAM":
                        identity_filters.append(InboundMessage.conversation_id == envelope.conversation_id)
                else:
                    identity_filters = [
                        InboundMessage.tenant_id == envelope.tenant_id,
                        InboundMessage.channel == envelope.channel,
                        InboundMessage.provider_message_id == envelope.provider_message_id,
                        InboundMessage.provider_account_id.is_(None),
                    ]
                row = session.scalar(select(InboundMessage).where(*identity_filters))
                if row is None:
                    raise PersistenceUnavailable("Message storage temporarily unavailable")
                if row.immutable_fingerprint != digest:
                    raise DuplicateConflict("Provider message ID already has different original content")
                if created_id is not None:
                    self._reconcile_waiting_children(session, row)
                result = IngestResponse(message=stored(row), duplicate=created_id is None)
            # Return only after the transaction commits successfully.
            return result
        except SQLAlchemyError:
            raise PersistenceUnavailable("Message storage temporarily unavailable") from None

    def get(self, tenant_id: str, message_id: str) -> StoredMessage | None:
        try:
            with Session(self.engine) as session:
                row = session.scalar(select(InboundMessage).where(InboundMessage.tenant_id == tenant_id, InboundMessage.message_id == message_id))
                if not row:
                    return None
                ext_ver = session.scalar(
                    select(ExtractionAttempt.extractor_version)
                    .where(ExtractionAttempt.tenant_id == tenant_id, ExtractionAttempt.message_id == message_id, ExtractionAttempt.status == "PROCESSED")
                    .order_by(ExtractionAttempt.started_at.desc())
                    .limit(1)
                )
                return stored(row, extractor_version=ext_ver)
        except SQLAlchemyError:
            raise PersistenceUnavailable("Message storage temporarily unavailable") from None

    def list(self, tenant_id: str, *, channel: Channel | None = None, search: str = "",
             processing_status: ProcessingStatus | None = None, limit: int = 25, offset: int = 0) -> MessagePage:
        if not 1 <= limit <= 100 or not 0 <= offset <= 10_000 or len(search) > 200:
            raise ValueError("Invalid Inbox pagination/search bounds")
        filters = [InboundMessage.tenant_id == tenant_id]
        if channel:
            filters.append(InboundMessage.channel == channel)
        if processing_status:
            filters.append(InboundMessage.processing_status == processing_status)
        if search:
            filters.append(or_(InboundMessage.raw["text"].astext.icontains(search, autoescape=True),
                               InboundMessage.raw["sender_alias"].astext.icontains(search, autoescape=True),
                               InboundMessage.provider_message_id.icontains(search, autoescape=True)))
        try:
            # A repeatable-read transaction keeps total and items on one snapshot.
            with self.engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
                with Session(bind=connection) as session, session.begin():
                    total = session.scalar(select(func.count()).select_from(InboundMessage).where(*filters))
                    rows = session.scalars(select(InboundMessage).where(*filters).order_by(
                        InboundMessage.ingested_at.desc(), InboundMessage.message_id.desc()).limit(limit).offset(offset)).all()
                    versions = {}
                    if rows:
                        msg_ids = [r.message_id for r in rows]
                        attempts = session.execute(
                            select(ExtractionAttempt.message_id, ExtractionAttempt.extractor_version)
                            .where(ExtractionAttempt.tenant_id == tenant_id, ExtractionAttempt.message_id.in_(msg_ids), ExtractionAttempt.status == "PROCESSED")
                            .order_by(ExtractionAttempt.started_at.desc())
                        ).all()
                        for m_id, ext_ver in attempts:
                            if m_id not in versions:
                                versions[m_id] = ext_ver

                    return MessagePage(items=[stored(row, extractor_version=versions.get(row.message_id)) for row in rows], total=total, limit=limit, offset=offset)
        except SQLAlchemyError:
            raise PersistenceUnavailable("Message storage temporarily unavailable") from None

    def awaiting_processing(self, tenant_id: str, limit: int = 25) -> list[StoredMessage]:
        """P1-02 discovery boundary only; no claim, processing, worker or automatic retry."""
        return self.list(tenant_id, processing_status="RECEIVED", limit=limit).items

    def process(self, tenant_id: str, message_id: str, *, reprocess: bool = False, now: datetime | None = None,
                operation_id: str | None = None) -> ProcessResponse:
        current_time = now or datetime.now(timezone.utc)
        extractor_version = VERSION
        try:
            with Session(self.engine) as session, session.begin():
                row = session.scalar(
                    select(InboundMessage).where(
                        InboundMessage.tenant_id == tenant_id,
                        InboundMessage.message_id == message_id,
                    ).with_for_update()
                )
                if row is None:
                    raise MessageNotFound(f"Message {message_id} not found")

                if operation_id:
                    previous = session.scalars(select(ExtractionAttempt).where(
                        ExtractionAttempt.tenant_id == tenant_id, ExtractionAttempt.message_id == message_id,
                    ).order_by(desc(ExtractionAttempt.started_at))).all()
                    for prior in previous:
                        try:
                            if json.loads(prior.diagnostic or "{}").get("operation_id") == operation_id:
                                return ProcessResponse(message=stored(row, prior.extractor_version),
                                    attempt=attempt_record(prior), reprocessed=reprocess)
                        except (ValueError, TypeError):
                            continue  # Legacy unstructured diagnostic; never rewrite it.

                if not reprocess:
                    existing_attempt = session.scalar(
                        select(ExtractionAttempt).where(
                            ExtractionAttempt.tenant_id == tenant_id,
                            ExtractionAttempt.message_id == message_id,
                            ExtractionAttempt.input_content_sha256 == row.content_sha256,
                            ExtractionAttempt.status == "PROCESSED",
                        ).order_by(desc(ExtractionAttempt.started_at)).limit(1)
                    )
                    if existing_attempt is not None:
                        return ProcessResponse(
                            message=stored(row, existing_attempt.extractor_version),
                            attempt=attempt_record(existing_attempt),
                            reprocessed=False,
                        )

                attempt_id = str(uuid4())
                attempt = ExtractionAttempt(
                    attempt_id=attempt_id,
                    tenant_id=tenant_id,
                    message_id=message_id,
                    extractor_version=extractor_version,
                    input_content_sha256=row.content_sha256,
                    status="PROCESSING",
                    fields=[],
                    diagnostic=None,
                    started_at=current_time,
                    completed_at=None,
                )
                session.add(attempt)
                row.processing_status = "PROCESSING"
                row.updated_at = current_time
                session.flush()

                stored_msg = stored(row)
                try:
                    result = extract_explicit_fields(stored_msg, catalog=self.catalog)
                    raw_text = stored_msg.raw.text
                    for f in result.fields:
                        for ev in f.evidence:
                            if ev.start < 0 or ev.end > len(raw_text) or ev.start >= ev.end:
                                raise ValueError(
                                    f"Evidence span [{ev.start}:{ev.end}] out of bounds for text length {len(raw_text)}"
                                )
                            actual_quote = raw_text[ev.start : ev.end]
                            if actual_quote != ev.quote:
                                raise ValueError(
                                    f"Evidence quote mismatch: expected {ev.quote!r}, got {actual_quote!r}"
                                )
                    from .reconciliation import reconcile_canonical_fields
                    active_fields, _ = reconcile_canonical_fields(
                        rule_fields=result.fields,
                        model_candidates=[],
                        catalog=self.catalog,
                        tenant_id=stored_msg.raw.tenant_id,
                        raw_text=raw_text,
                    )
                    actual_extractor_version = extractor_version
                    diagnostics_dict = {"trigger": "explicit_reprocess" if reprocess else "process",
                                        "configured": False, "accepted_model_fields": 0}
                    if operation_id:
                        diagnostics_dict["operation_id"] = operation_id
                    if stored_msg.raw.received_at > stored_msg.ingested_at:
                        diagnostics_dict["source_clock_anomaly"] = "receipt_after_persistence"

                    svc = self.proposal_service
                    if svc and getattr(svc, "enabled", False):
                        diagnostics_dict["configured"] = True
                        try:
                            import asyncio
                            import concurrent.futures

                            def _run_async(coro):
                                try:
                                    asyncio.get_running_loop()
                                except RuntimeError:
                                    return asyncio.run(coro)
                                else:
                                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                                        return pool.submit(asyncio.run, coro).result()

                            proposal_res = _run_async(
                                svc.extract_stored(stored_msg, catalog=self.catalog)
                            )
                            if getattr(proposal_res, "outcomes", None):
                                diagnostics_dict["model_outcomes"] = proposal_res.outcomes
                            if getattr(proposal_res, "routing_reasons", None):
                                diagnostics_dict["routing_reasons"] = proposal_res.routing_reasons
                            diagnostics_dict["worker_request_count"] = getattr(proposal_res, "worker_request_count", 0)
                            diagnostics_dict["runtime_reported"] = getattr(proposal_res, "telemetry", {})

                            candidates = getattr(proposal_res, "candidates", [])
                            if candidates:
                                actual_extractor_version = "p1-ai-pipeline-v2"
                                for c in candidates:
                                    for ev in c.evidence:
                                        if ev.start < 0 or ev.end > len(raw_text) or ev.start >= ev.end or raw_text[ev.start:ev.end] != ev.quote:
                                            raise ValueError(f"Model evidence span [{ev.start}:{ev.end}] invalid")
                                diagnostics_dict["raw_proposals"] = [
                                    {"field_name": c.field_name, "value": c.value, "status": c.validation_status}
                                    for c in candidates
                                ]
                                reconciled_fields, accepted_count = reconcile_canonical_fields(
                                    rule_fields=result.fields,
                                    model_candidates=candidates,
                                    catalog=self.catalog,
                                    tenant_id=stored_msg.raw.tenant_id,
                                    raw_text=raw_text,
                                )
                                active_fields = reconciled_fields
                                diagnostics_dict["accepted_model_fields"] = accepted_count
                            elif getattr(proposal_res, "outcomes", None) and any(
                                v in ("unavailable", "timeout", "busy", "endpoint_http_error", "transport_or_schema_error", "invalid_context_or_candidate")
                                for v in proposal_res.outcomes.values()
                            ):
                                diagnostics_dict["fallback"] = "rules_only"
                        except Exception as model_exc:
                            diagnostics_dict["model_error"] = "proposal_processing_failed"
                            diagnostics_dict["fallback"] = "rules_only"

                    attempt.status = "PROCESSED"
                    attempt.extractor_version = actual_extractor_version
                    attempt.fields = [f.model_dump(mode="json") for f in active_fields]
                    # Preserve valid JSON in the existing bounded column. Never
                    # truncate JSON mid-string or discard primary outcome state.
                    diagnostic = json.dumps(diagnostics_dict, separators=(",", ":"))
                    if len(diagnostic) > 1000:
                        for telemetry in diagnostics_dict.get("runtime_reported", {}).values():
                            for key in ("dtype", "peak_gpu_bytes", "load_seconds"):
                                telemetry.pop(key, None)
                        diagnostic = json.dumps(diagnostics_dict, separators=(",", ":"))
                    if len(diagnostic) > 1000:
                        diagnostics_dict.pop("raw_proposals", None)
                        diagnostic = json.dumps(diagnostics_dict, separators=(",", ":"))
                    if len(diagnostic) > 1000:
                        diagnostics_dict["runtime_reported"] = {k: {"attempted": v.get("attempted", False),
                            "succeeded": v.get("succeeded", False)} for k, v in diagnostics_dict.get("runtime_reported", {}).items()}
                        diagnostic = json.dumps(diagnostics_dict, separators=(",", ":"))
                    attempt.diagnostic = diagnostic
                    completed_time = datetime.now(timezone.utc)
                    attempt.completed_at = completed_time
                    row.processing_status = "PROCESSED"
                    row.updated_at = completed_time
                except Exception as exc:
                    completed_time = datetime.now(timezone.utc)
                    attempt.status = "PROCESSING_FAILED"
                    attempt.diagnostic = str(exc)[:1000]
                    attempt.completed_at = completed_time
                    row.processing_status = "PROCESSING_FAILED"
                    row.updated_at = completed_time

                session.flush()
                return ProcessResponse(
                    message=stored(row, extractor_version=attempt.extractor_version),
                    attempt=attempt_record(attempt),
                    reprocessed=reprocess,
                )
        except (MessageNotFound, ProcessingConflict):
            raise
        except SQLAlchemyError:
            raise PersistenceUnavailable("Message storage temporarily unavailable") from None

    def get_latest_extraction(self, tenant_id: str, message_id: str) -> ExtractionAttemptRecord | None:
        try:
            with Session(self.engine) as session:
                row = session.scalar(
                    select(ExtractionAttempt).where(
                        ExtractionAttempt.tenant_id == tenant_id,
                        ExtractionAttempt.message_id == message_id,
                    ).order_by(desc(ExtractionAttempt.started_at)).limit(1)
                )
                if row is None:
                    # Verify message existence to distinguish 404 message from no extraction
                    msg = session.scalar(
                        select(InboundMessage).where(
                            InboundMessage.tenant_id == tenant_id,
                            InboundMessage.message_id == message_id,
                        )
                    )
                    if msg is None:
                        raise MessageNotFound(f"Message {message_id} not found")
                    raise ExtractionNotFound(f"No extraction attempt for message {message_id}")
                return attempt_record(row)
        except (MessageNotFound, ExtractionNotFound):
            raise
        except SQLAlchemyError:
            raise PersistenceUnavailable("Message storage temporarily unavailable") from None

    def list_extraction_attempts(self, tenant_id: str, message_id: str) -> list[ExtractionAttemptRecord]:
        try:
            with Session(self.engine) as session:
                msg = session.scalar(
                    select(InboundMessage).where(
                        InboundMessage.tenant_id == tenant_id,
                        InboundMessage.message_id == message_id,
                    )
                )
                if msg is None:
                    raise MessageNotFound(f"Message {message_id} not found")
                rows = session.scalars(
                    select(ExtractionAttempt).where(
                        ExtractionAttempt.tenant_id == tenant_id,
                        ExtractionAttempt.message_id == message_id,
                    ).order_by(desc(ExtractionAttempt.started_at))
                ).all()
                return [attempt_record(row) for row in rows]
        except MessageNotFound:
            raise
        except SQLAlchemyError:
            raise PersistenceUnavailable("Message storage temporarily unavailable") from None

    def get_association(self, tenant_id: str, message_id: str) -> MessageAssociationRecord | None:
        try:
            with Session(self.engine) as session:
                row = session.scalar(
                    select(MessageAssociation).where(
                        MessageAssociation.tenant_id == tenant_id,
                        MessageAssociation.message_id == message_id,
                    )
                )
                if row is None:
                    msg = session.scalar(
                        select(InboundMessage).where(
                            InboundMessage.tenant_id == tenant_id,
                            InboundMessage.message_id == message_id,
                        )
                    )
                    if msg is None:
                        raise MessageNotFound(f"Message {message_id} not found")
                    return None
                return association_record(row)
        except MessageNotFound:
            raise
        except SQLAlchemyError:
            raise PersistenceUnavailable("Message storage temporarily unavailable") from None

    def save_association(self, record: MessageAssociationRecord) -> MessageAssociationRecord:
        try:
            with Session(self.engine) as session, session.begin():
                stmt = insert(MessageAssociation).values(
                    association_id=record.association_id,
                    tenant_id=record.tenant_id,
                    message_id=record.message_id,
                    status=record.status.value,
                    verified_customer=record.verified_customer.model_dump(mode="json") if record.verified_customer else None,
                    verified_order=record.verified_order.model_dump(mode="json") if record.verified_order else None,
                    candidates=[c.model_dump(mode="json") for c in record.candidates],
                    conflicts=record.conflicts,
                    last_decision=record.last_decision.model_dump(mode="json") if record.last_decision else None,
                    version=record.version,
                    updated_at=record.updated_at,
                ).on_conflict_do_update(
                    constraint="uq_p1_message_association",
                    set_={
                        "status": record.status.value,
                        "verified_customer": record.verified_customer.model_dump(mode="json") if record.verified_customer else None,
                        "verified_order": record.verified_order.model_dump(mode="json") if record.verified_order else None,
                        "candidates": [c.model_dump(mode="json") for c in record.candidates],
                        "conflicts": record.conflicts,
                        "last_decision": record.last_decision.model_dump(mode="json") if record.last_decision else None,
                        "version": record.version,
                        "updated_at": record.updated_at,
                    },
                )
                session.execute(stmt)
                row = session.scalar(
                    select(MessageAssociation).where(
                        MessageAssociation.tenant_id == record.tenant_id,
                        MessageAssociation.message_id == record.message_id,
                    )
                )
                if row is None:
                    raise PersistenceUnavailable("Message storage temporarily unavailable")
                return association_record(row)
        except SQLAlchemyError:
            raise PersistenceUnavailable("Message storage temporarily unavailable") from None

    def decide_association(
        self,
        tenant_id: str,
        message_id: str,
        request: AssociationDecisionRequest,
        actor_id: str,
        actor_role: str,
    ) -> MessageAssociationRecord:
        from .association_service import AssociationService, StaleAssociationVersion

        try:
            with Session(self.engine) as session, session.begin():
                row = session.scalar(
                    select(MessageAssociation).where(
                        MessageAssociation.tenant_id == tenant_id,
                        MessageAssociation.message_id == message_id,
                    ).with_for_update()
                )
                if row is None:
                    msg = session.scalar(
                        select(InboundMessage).where(
                            InboundMessage.tenant_id == tenant_id,
                            InboundMessage.message_id == message_id,
                        )
                    )
                    if msg is None:
                        raise MessageNotFound(f"Message {message_id} not found")
                    raise AssociationNotFound(f"Association for message {message_id} not found")

                current_record = association_record(row)
                svc = AssociationService()
                updated_record = svc.apply_decision(current_record, request, actor_id=actor_id, actor_role=actor_role)

                row.status = updated_record.status.value
                row.verified_customer = updated_record.verified_customer.model_dump(mode="json") if updated_record.verified_customer else None
                row.verified_order = updated_record.verified_order.model_dump(mode="json") if updated_record.verified_order else None
                row.last_decision = updated_record.last_decision.model_dump(mode="json") if updated_record.last_decision else None
                row.version = updated_record.version
                row.updated_at = updated_record.updated_at
                if updated_record.status.value == "LINK_VERIFIED" and updated_record.verified_customer:
                    linked_ctxs = session.scalars(select(OrderContext).where(
                        OrderContext.tenant_id == tenant_id,
                        OrderContext.source_message_ids.contains([message_id]),
                    )).all()
                    for linked_context in linked_ctxs:
                        linked_context.customer_id = updated_record.verified_customer.customer_id
                        linked_context.customer_identity_status = "LINK_VERIFIED"
                        if "customer_identity" in (linked_context.missing_fields or []):
                            linked_context.missing_fields = [
                                field for field in linked_context.missing_fields
                                if field != "customer_identity"
                            ]
                        if (
                            not linked_context.missing_fields
                            and linked_context.requested_items
                            and not linked_context.conflicts
                        ):
                            linked_context.status = "INFORMATION_READY"
                session.flush()
                return association_record(row)
        except (MessageNotFound, AssociationNotFound, StaleAssociationVersion):
            raise
        except SQLAlchemyError:
            raise PersistenceUnavailable("Message storage temporarily unavailable") from None

    def get_order_context(self, tenant_id: str, context_id: str) -> OrderContextRecord | None:
        try:
            with Session(self.engine) as session:
                row = session.scalar(
                    select(OrderContext).where(
                        OrderContext.tenant_id == tenant_id,
                        OrderContext.context_id == context_id,
                    )
                )
                if row is None:
                    return None
                return order_context_record(row)
        except SQLAlchemyError:
            raise PersistenceUnavailable("Message storage temporarily unavailable") from None

    def get_order_context_by_order(self, tenant_id: str, order_id: str) -> OrderContextRecord | None:
        try:
            with Session(self.engine) as session:
                row = session.scalar(
                    select(OrderContext).where(
                        OrderContext.tenant_id == tenant_id,
                        OrderContext.order_id == order_id,
                    )
                )
                if row is None:
                    return None
                return order_context_record(row)
        except SQLAlchemyError:
            raise PersistenceUnavailable("Message storage temporarily unavailable") from None

    def list_active_contexts_by_customer(
        self, tenant_id: str, customer_id: str
    ) -> list[OrderContextRecord]:
        try:
            with Session(self.engine) as session:
                stmt = (
                    select(OrderContext)
                    .where(
                        OrderContext.tenant_id == tenant_id,
                        OrderContext.customer_id == customer_id,
                        OrderContext.core_commitment_id.is_(None),
                        OrderContext.status.in_(["INFORMATION_PARTIAL", "UNRESOLVED", "CONFLICT"]),
                    )
                    .order_by(OrderContext.updated_at.desc())
                )
                rows = session.scalars(stmt).all()
                return [order_context_record(row) for row in rows]
        except SQLAlchemyError:
            raise PersistenceUnavailable("Context lookup temporarily unavailable") from None

    def get_latest_active_context_by_customer(
        self, tenant_id: str, customer_id: str
    ) -> OrderContextRecord | None:
        rows = self.list_active_contexts_by_customer(tenant_id, customer_id)
        return rows[0] if rows else None

    def list_active_contexts_by_sender(
        self, tenant_id: str, sender_identity_id: str
    ) -> list[OrderContextRecord]:
        try:
            with Session(self.engine) as session:
                recent_msgs = session.scalars(
                    select(InboundMessage)
                    .where(InboundMessage.tenant_id == tenant_id)
                    .order_by(InboundMessage.ingested_at.desc())
                    .limit(50)
                ).all()
                matching_ids = [
                    m.message_id for m in recent_msgs
                    if isinstance(m.raw, dict) and m.raw.get("sender_identity_id") == sender_identity_id
                ]
                seen_ctx_ids: set[str] = set()
                results: list[OrderContextRecord] = []
                for msg_id in matching_ids:
                    rows = session.scalars(
                        select(OrderContext)
                        .where(
                            OrderContext.tenant_id == tenant_id,
                            OrderContext.source_message_ids.contains([msg_id]),
                            OrderContext.core_commitment_id.is_(None),
                            OrderContext.status.in_(["INFORMATION_PARTIAL", "UNRESOLVED", "CONFLICT"]),
                        )
                        .order_by(OrderContext.updated_at.desc())
                    ).all()
                    for row in rows:
                        if row.context_id not in seen_ctx_ids:
                            seen_ctx_ids.add(row.context_id)
                            results.append(order_context_record(row))
                return results
        except SQLAlchemyError:
            raise PersistenceUnavailable("Context lookup temporarily unavailable") from None

    def get_contexts_by_thread_or_reply(
        self,
        tenant_id: str,
        sender_identity_id: str | None,
        reply_to_provider_message_id: str | None,
        thread_ref: str | None,
    ) -> list[OrderContextRecord]:
        # Exact parents are resolved through durable provider/account scope in
        # get_contexts_by_exact_parent. This legacy method now serves only broad
        # same-thread grouping and never interprets a provider ID on its own.
        if reply_to_provider_message_id or not thread_ref:
            return []
        try:
            with Session(self.engine) as session:
                recent_msgs = session.scalars(
                    select(InboundMessage)
                    .where(InboundMessage.tenant_id == tenant_id)
                    .order_by(InboundMessage.ingested_at.desc())
                    .limit(50)
                ).all()
                thread_msg_ids: list[str] = []
                for m in recent_msgs:
                    if not isinstance(m.raw, dict):
                        continue
                    if sender_identity_id and m.raw.get("sender_identity_id") != sender_identity_id:
                        continue
                    if thread_ref and m.raw.get("thread_ref") == thread_ref:
                        thread_msg_ids.append(m.message_id)

                candidate_msg_ids = thread_msg_ids
                seen_ctx_ids: set[str] = set()
                results: list[OrderContextRecord] = []
                for msg_id in candidate_msg_ids:
                    rows = session.scalars(
                        select(OrderContext)
                        .where(
                            OrderContext.tenant_id == tenant_id,
                            OrderContext.source_message_ids.contains([msg_id]),
                            OrderContext.core_commitment_id.is_(None),
                            OrderContext.status.in_(["INFORMATION_PARTIAL", "UNRESOLVED", "CONFLICT"]),
                        )
                        .order_by(OrderContext.updated_at.desc())
                    ).all()
                    for row in rows:
                        if row.context_id not in seen_ctx_ids:
                            seen_ctx_ids.add(row.context_id)
                            results.append(order_context_record(row))
                return results
        except SQLAlchemyError:
            raise PersistenceUnavailable("Context lookup temporarily unavailable") from None

    def get_latest_active_context_by_sender(
        self, tenant_id: str, sender_identity_id: str
    ) -> OrderContextRecord | None:
        rows = self.list_active_contexts_by_sender(tenant_id, sender_identity_id)
        return rows[0] if rows else None

    def save_order_context(
        self,
        record: OrderContextRecord,
        change_type: str = "INITIAL_CREATION",
        actor_id: str | None = None,
        actor_role: str | None = None,
        reason: str | None = None,
    ) -> OrderContextRecord:
        try:
            with Session(self.engine) as session, session.begin():
                existing = session.scalar(
                    select(OrderContext).where(
                        OrderContext.tenant_id == record.tenant_id,
                        OrderContext.context_id == record.context_id,
                    ).with_for_update()
                )
                now = datetime.now(timezone.utc)
                if existing is None:
                    row = OrderContext(
                        context_id=record.context_id,
                        tenant_id=record.tenant_id,
                        order_id=record.order_id,
                        customer_id=record.customer_id,
                        customer_identity_status=record.customer_identity_status,
                        status=record.status,
                        context_version=record.context_version,
                        requested_items=[it.model_dump(mode="json") for it in record.requested_items],
                        requested_delivery_at=record.requested_delivery_at,
                        delivery_qualifier=record.delivery_qualifier,
                        special_instructions=record.special_instructions,
                        source_message_ids=record.source_message_ids,
                        field_evidence=record.field_evidence,
                        missing_fields=record.missing_fields,
                        conflicts=record.conflicts,
                        last_reviewed_by=record.last_reviewed_by,
                        last_reviewed_role=record.last_reviewed_role,
                        last_reviewed_at=record.last_reviewed_at,
                        core_commitment_id=record.core_commitment_id,
                        published_to_core_at=record.published_to_core_at,
                        created_at=record.created_at or now,
                        updated_at=record.updated_at or now,
                    )
                    session.add(row)
                    session.flush()

                    version_row = OrderContextVersion(
                        version_id=str(uuid4()),
                        context_id=row.context_id,
                        tenant_id=row.tenant_id,
                        context_version=row.context_version,
                        snapshot=order_context_record(row).model_dump(mode="json"),
                        change_type=change_type,
                        actor_id=actor_id,
                        actor_role=actor_role,
                        reason=reason,
                        created_at=now,
                    )
                    session.add(version_row)
                    return order_context_record(row)
                else:
                    if existing.context_version != record.context_version:
                        raise StaleContextVersion(
                            f"Context version mismatch: expected {record.context_version}, got {existing.context_version}"
                        )
                    existing.order_id = record.order_id
                    existing.customer_id = record.customer_id
                    existing.customer_identity_status = record.customer_identity_status
                    existing.status = record.status
                    existing.context_version += 1
                    existing.requested_items = [it.model_dump(mode="json") for it in record.requested_items]
                    existing.requested_delivery_at = record.requested_delivery_at
                    existing.delivery_qualifier = record.delivery_qualifier
                    existing.special_instructions = record.special_instructions
                    existing.source_message_ids = record.source_message_ids
                    existing.field_evidence = record.field_evidence
                    existing.missing_fields = record.missing_fields
                    existing.conflicts = record.conflicts
                    existing.core_commitment_id = record.core_commitment_id
                    existing.published_to_core_at = record.published_to_core_at
                    existing.updated_at = now
                    session.flush()

                    version_row = OrderContextVersion(
                        version_id=str(uuid4()),
                        context_id=existing.context_id,
                        tenant_id=existing.tenant_id,
                        context_version=existing.context_version,
                        snapshot=order_context_record(existing).model_dump(mode="json"),
                        change_type=change_type,
                        actor_id=actor_id,
                        actor_role=actor_role,
                        reason=reason,
                        created_at=now,
                    )
                    session.add(version_row)
                    return order_context_record(existing)
        except StaleContextVersion:
            raise
        except SQLAlchemyError:
            raise PersistenceUnavailable("Message storage temporarily unavailable") from None

    def get_order_context_by_message(self, tenant_id: str, message_id: str) -> OrderContextRecord | None:
        try:
            with Session(self.engine) as session:
                rows = session.scalars(select(OrderContext).where(OrderContext.tenant_id == tenant_id,
                    OrderContext.source_message_ids.contains([message_id])).limit(2)).all()
                if len(rows) > 1:
                    raise ProcessingConflict("Multiple historical contexts reference this message; select a context explicitly")
                return order_context_record(rows[0]) if rows else None
        except SQLAlchemyError:
            raise PersistenceUnavailable("Context lookup temporarily unavailable") from None

    def update_order_context(
        self,
        tenant_id: str,
        context_id: str,
        expected_version: int,
        updates: dict,
        actor_id: str | None = None,
        actor_role: str | None = None,
        reason: str | None = None,
    ) -> OrderContextRecord:
        try:
            with Session(self.engine) as session, session.begin():
                row = session.scalar(
                    select(OrderContext).where(
                        OrderContext.tenant_id == tenant_id,
                        OrderContext.context_id == context_id,
                    ).with_for_update()
                )
                if row is None:
                    raise ContextNotFound(f"OrderContext {context_id} not found")
                if row.context_version != expected_version:
                    raise StaleContextVersion(
                        f"Context version mismatch: expected {expected_version}, got {row.context_version}"
                    )

                now = datetime.now(timezone.utc)
                for key, val in updates.items():
                    if hasattr(row, key):
                        if key == "requested_items" and isinstance(val, list):
                            setattr(row, key, [it if isinstance(it, dict) else it.model_dump(mode="json") for it in val])
                        else:
                            setattr(row, key, val)

                row.context_version += 1
                row.updated_at = now
                session.flush()

                version_row = OrderContextVersion(
                    version_id=str(uuid4()),
                    context_id=row.context_id,
                    tenant_id=row.tenant_id,
                    context_version=row.context_version,
                    snapshot=order_context_record(row).model_dump(mode="json"),
                    change_type="HUMAN_EDIT",
                    actor_id=actor_id,
                    actor_role=actor_role,
                    reason=reason,
                    created_at=now,
                )
                session.add(version_row)
                return order_context_record(row)
        except (ContextNotFound, StaleContextVersion):
            raise
        except SQLAlchemyError:
            raise PersistenceUnavailable("Message storage temporarily unavailable") from None

    def apply_context_review(
        self,
        tenant_id: str,
        context_id: str,
        request: ContextReviewRequest,
        actor_id: str,
        actor_role: str,
    ) -> OrderContextRecord:
        try:
            with Session(self.engine) as session, session.begin():
                row = session.scalar(
                    select(OrderContext).where(
                        OrderContext.tenant_id == tenant_id,
                        OrderContext.context_id == context_id,
                    ).with_for_update()
                )
                if row is None:
                    raise ContextNotFound(f"OrderContext {context_id} not found")
                if row.context_version != request.expected_context_version:
                    raise StaleContextVersion(
                        f"Context version mismatch: expected {request.expected_context_version}, got {row.context_version}"
                    )

                now = datetime.now(timezone.utc)
                before_ver = row.context_version
                after_ver = before_ver + 1
                field_changes: dict = {}
                previous_missing = list(row.missing_fields or [])

                if request.field_edits:
                    for field_name, new_val in request.field_edits.items():
                        if hasattr(row, field_name):
                            old_val = getattr(row, field_name)
                            if field_name == "requested_items" and isinstance(new_val, list):
                                norm_new = [it if isinstance(it, dict) else it.model_dump(mode="json") for it in new_val]
                                field_changes[field_name] = {
                                    "old": _to_json_compatible(old_val),
                                    "new": _to_json_compatible(norm_new),
                                }
                                setattr(row, field_name, norm_new)
                            else:
                                model_val = new_val
                                if field_name == "requested_delivery_at" and isinstance(new_val, str):
                                    try:
                                        model_val = datetime.fromisoformat(new_val)
                                    except Exception:
                                        model_val = new_val
                                field_changes[field_name] = {
                                    "old": _to_json_compatible(old_val),
                                    "new": _to_json_compatible(new_val),
                                }
                                setattr(row, field_name, model_val)

                if row.conflicts and row.delivery_qualifier == "DEADLINE":
                    row.conflicts = [c for c in row.conflicts if "EXACT arrival time" not in c]

                if request.action in {"ACCEPT_EXTRACTION", "EDIT_FIELD"}:
                    from .review_readiness import reviewed_missing_fields
                    row.missing_fields = reviewed_missing_fields(row, request.field_edits, self.catalog)
                    if row.missing_fields != previous_missing or 'missing_fields' in field_changes:
                        field_changes['missing_fields'] = {'old': previous_missing, 'new': row.missing_fields}

                if request.action in {"ACCEPT_EXTRACTION", "EDIT_FIELD"}:
                    row.status = ("CONFLICT" if row.conflicts else "INFORMATION_READY"
                                  if not row.missing_fields and row.requested_items else "INFORMATION_PARTIAL")
                elif request.action == "MARK_UNRESOLVED":
                    row.status = "UNRESOLVED"
                elif request.action == "REQUEST_MORE_INFO":
                    row.status = "INFORMATION_PARTIAL"

                row.context_version = after_ver
                row.last_reviewed_by = actor_id
                row.last_reviewed_role = actor_role
                row.last_reviewed_at = now
                row.updated_at = now
                session.flush()

                review_entry = ContextReview(
                    review_id=str(uuid4()),
                    tenant_id=tenant_id,
                    context_id=context_id,
                    context_version_before=before_ver,
                    context_version_after=after_ver,
                    action=request.action,
                    actor_id=actor_id,
                    actor_role=actor_role,
                    field_changes=field_changes,
                    note=request.note,
                    created_at=now,
                )
                session.add(review_entry)
                if field_changes:
                    evidence = dict(row.field_evidence or {})
                    for field_name in field_changes:
                        evidence[field_name] = [{"evidence_ref": review_entry.review_id,
                            "method": "HUMAN", "actor_id": actor_id,
                            "context_version": after_ver, "normalized_value": field_changes[field_name]["new"]}]
                    row.field_evidence = evidence

                version_entry = OrderContextVersion(
                    version_id=str(uuid4()),
                    context_id=context_id,
                    tenant_id=tenant_id,
                    context_version=after_ver,
                    snapshot=order_context_record(row).model_dump(mode="json"),
                    change_type=request.action,
                    actor_id=actor_id,
                    actor_role=actor_role,
                    reason=request.note,
                    created_at=now,
                )
                session.add(version_entry)
                return order_context_record(row)
        except (ContextNotFound, StaleContextVersion):
            raise
        except SQLAlchemyError:
            raise PersistenceUnavailable("Message storage temporarily unavailable") from None

    def list_context_versions(self, tenant_id: str, context_id: str) -> list[OrderContextVersionRecord]:
        try:
            with Session(self.engine) as session:
                rows = session.scalars(
                    select(OrderContextVersion).where(
                        OrderContextVersion.tenant_id == tenant_id,
                        OrderContextVersion.context_id == context_id,
                    ).order_by(OrderContextVersion.context_version.desc())
                ).all()
                return [order_context_version_record(r) for r in rows]
        except SQLAlchemyError:
            raise PersistenceUnavailable("Message storage temporarily unavailable") from None

    def list_context_reviews(self, tenant_id: str, context_id: str) -> list[ContextReviewRecord]:
        try:
            with Session(self.engine) as session:
                rows = session.scalars(
                    select(ContextReview).where(
                        ContextReview.tenant_id == tenant_id,
                        ContextReview.context_id == context_id,
                    ).order_by(ContextReview.created_at.desc())
                ).all()
                return [context_review_record(r) for r in rows]
        except SQLAlchemyError:
            raise PersistenceUnavailable("Message storage temporarily unavailable") from None

    def read_order_context_source(
        self, tenant_id: str, context_id: str
    ) -> OrderContextSourceSnapshot | None:
        """Load mapping inputs in one tenant-scoped, read-only DB snapshot.

        The returned association is the current row for each message. P1 does
        not retain historical association versions, so callers must preserve
        the row's version and downstream consumers must re-read it.
        """
        try:
            with self.engine.connect().execution_options(
                isolation_level="REPEATABLE READ"
            ) as connection:
                with Session(bind=connection) as session, session.begin():
                    session.execute(text("SET TRANSACTION READ ONLY"))
                    context_row = session.scalar(
                        select(OrderContext).where(
                            OrderContext.tenant_id == tenant_id,
                            OrderContext.context_id == context_id,
                        )
                    )
                    if context_row is None:
                        return None

                    context = order_context_record(context_row)
                    source_ids = tuple(dict.fromkeys(context.source_message_ids))
                    version_rows = session.scalars(
                        select(OrderContextVersion).where(
                            OrderContextVersion.tenant_id == tenant_id,
                            OrderContextVersion.context_id == context_id,
                        ).order_by(OrderContextVersion.context_version.desc())
                    ).all()
                    review_rows = session.scalars(
                        select(ContextReview).where(
                            ContextReview.tenant_id == tenant_id,
                            ContextReview.context_id == context_id,
                        ).order_by(ContextReview.created_at.desc())
                    ).all()

                    message_rows = []
                    association_rows = []
                    attempt_rows = []
                    if source_ids:
                        message_rows = session.scalars(
                            select(InboundMessage).where(
                                InboundMessage.tenant_id == tenant_id,
                                InboundMessage.message_id.in_(source_ids),
                            )
                        ).all()
                        association_rows = session.scalars(
                            select(MessageAssociation).where(
                                MessageAssociation.tenant_id == tenant_id,
                                MessageAssociation.message_id.in_(source_ids),
                            )
                        ).all()
                        attempt_rows = session.scalars(
                            select(ExtractionAttempt).where(
                                ExtractionAttempt.tenant_id == tenant_id,
                                ExtractionAttempt.message_id.in_(source_ids),
                            ).order_by(ExtractionAttempt.started_at.desc())
                        ).all()

                    latest_processed_version: dict[str, str] = {}
                    for row in attempt_rows:
                        if row.status == "PROCESSED":
                            latest_processed_version.setdefault(
                                row.message_id, row.extractor_version
                            )

                    return OrderContextSourceSnapshot(
                        context=context,
                        context_versions=tuple(
                            order_context_version_record(row) for row in version_rows
                        ),
                        context_reviews=tuple(
                            context_review_record(row) for row in review_rows
                        ),
                        source_messages=tuple(
                            stored(row, latest_processed_version.get(row.message_id))
                            for row in message_rows
                        ),
                        associations=tuple(
                            association_record(row) for row in association_rows
                        ),
                        extraction_attempts=tuple(
                            attempt_record(row) for row in attempt_rows
                        ),
                    )
        except SQLAlchemyError:
            raise PersistenceUnavailable("Message storage temporarily unavailable") from None
        except (ValidationError, ValueError, TypeError, KeyError):
            # Stored JSON/model corruption is not safe to echo to a caller.
            raise PersistenceUnavailable("P1 source records could not be validated") from None

    def save_attachment(self, tenant_id: str, attachment: AttachmentRecord, content: bytes) -> AttachmentRecord:
        try:
            with Session(self.engine) as session:
                stmt = select(AttachmentModel).where(
                    AttachmentModel.tenant_id == tenant_id,
                    AttachmentModel.evidence_ref == attachment.evidence_ref,
                )
                existing = session.execute(stmt).scalar_one_or_none()
                if existing:
                    existing.filename = attachment.filename
                    existing.media_type = attachment.media_type
                    existing.size_bytes = attachment.size_bytes
                    existing.content_sha256 = attachment.content_sha256
                    existing.content = content
                else:
                    record = AttachmentModel(
                        attachment_id=attachment.attachment_id,
                        tenant_id=tenant_id,
                        evidence_ref=attachment.evidence_ref,
                        filename=attachment.filename,
                        media_type=attachment.media_type,
                        size_bytes=attachment.size_bytes,
                        content_sha256=attachment.content_sha256,
                        content=content,
                        created_at=attachment.created_at,
                    )
                    session.add(record)
                session.commit()
                return attachment
        except SQLAlchemyError:
            raise PersistenceUnavailable("Message storage temporarily unavailable") from None

    def get_attachment(self, tenant_id: str, evidence_ref: str) -> tuple[AttachmentRecord, bytes] | None:
        try:
            with Session(self.engine) as session:
                stmt = select(AttachmentModel).where(
                    AttachmentModel.tenant_id == tenant_id,
                    AttachmentModel.evidence_ref == evidence_ref,
                )
                row = session.execute(stmt).scalar_one_or_none()
                if not row:
                    return None
                rec = AttachmentRecord(
                    attachment_id=row.attachment_id,
                    tenant_id=row.tenant_id,
                    evidence_ref=row.evidence_ref,
                    filename=row.filename,
                    media_type=row.media_type,
                    size_bytes=row.size_bytes,
                    content_sha256=row.content_sha256,
                    created_at=row.created_at,
                )
                return rec, bytes(row.content)
        except SQLAlchemyError:
            raise PersistenceUnavailable("Message storage temporarily unavailable") from None

    def save_document_extraction(self, tenant_id: str, extraction: DocumentExtractionResult) -> DocumentExtractionResult:
        try:
            with Session(self.engine) as session:
                stmt = select(DocumentExtractionModel).where(
                    DocumentExtractionModel.tenant_id == tenant_id,
                    DocumentExtractionModel.evidence_ref == extraction.evidence_ref,
                )
                existing = session.execute(stmt).scalar_one_or_none()
                payload = {
                    "extracted_fields": extraction.extracted_fields,
                    "evidence_items": [ev.model_dump(mode="json") for ev in extraction.evidence_items],
                    "is_payment_notice": extraction.is_payment_notice,
                    "diagnostic": extraction.diagnostic,
                }
                if existing:
                    existing.status = extraction.status
                    existing.document_type = extraction.document_type
                    existing.page_count = extraction.page_count
                    existing.text_content = extraction.text_content
                    existing.payload = payload
                else:
                    record = DocumentExtractionModel(
                        tenant_id=tenant_id,
                        evidence_ref=extraction.evidence_ref,
                        attachment_id=extraction.attachment_id,
                        status=extraction.status,
                        document_type=extraction.document_type,
                        page_count=extraction.page_count,
                        text_content=extraction.text_content,
                        payload=payload,
                        created_at=extraction.extracted_at,
                    )
                    session.add(record)
                session.commit()
                return extraction
        except SQLAlchemyError:
            raise PersistenceUnavailable("Message storage temporarily unavailable") from None

    def get_document_extraction(self, tenant_id: str, evidence_ref: str) -> DocumentExtractionResult | None:
        try:
            with Session(self.engine) as session:
                stmt = select(DocumentExtractionModel).where(
                    DocumentExtractionModel.tenant_id == tenant_id,
                    DocumentExtractionModel.evidence_ref == evidence_ref,
                )
                row = session.execute(stmt).scalar_one_or_none()
                if not row:
                    return None
                payload = row.payload or {}
                evidence_items = [
                    DocumentEvidence(**item) for item in payload.get("evidence_items", [])
                ]
                return DocumentExtractionResult(
                    attachment_id=row.attachment_id,
                    evidence_ref=row.evidence_ref,
                    status=row.status,  # type: ignore
                    document_type=row.document_type,  # type: ignore
                    page_count=row.page_count,
                    text_content=row.text_content,
                    extracted_fields=payload.get("extracted_fields", []),
                    evidence_items=evidence_items,
                    is_payment_notice=payload.get("is_payment_notice", False),
                    diagnostic=payload.get("diagnostic"),
                    extracted_at=row.created_at,
                )
        except SQLAlchemyError:
            raise PersistenceUnavailable("Message storage temporarily unavailable") from None

