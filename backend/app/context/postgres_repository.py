"""Provisional P1 PostgreSQL tables. Explicit init only, separate from P5 migrations."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import CheckConstraint, DateTime, Index, String, UniqueConstraint, desc, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from .deterministic_extraction import PROVISIONAL_PRODUCTS, VERSION, extract_explicit_fields
from .ingestion_schemas import ExtractionAttemptRecord, IngestResponse, MessagePage, ProcessResponse, StoredMessage
from .repository import (
    DuplicateConflict,
    ExtractionNotFound,
    MessageNotFound,
    PersistenceUnavailable,
    ProcessingConflict,
)
from .schemas import Channel, ExtractedField, ProcessingStatus, RawMessageEnvelope


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
        UniqueConstraint("tenant_id", "channel", "provider_message_id", name="uq_p1_delivery"),
        CheckConstraint("processing_status IN ('RECEIVED', 'PROCESSING', 'PROCESSED', 'PROCESSING_FAILED')", name="ck_p1_processing"),
        CheckConstraint("channel = 'WHATSAPP' AND synthetic_provider = 'SYNTHETIC_WHATSAPP'", name="ck_p1_synthetic_provider"),
        Index("ix_p1_inbox", "tenant_id", "ingested_at", "message_id"),
        {"schema": "p1_dev"},
    )

    message_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(200), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_message_id: Mapped[str] = mapped_column(String(200), nullable=False)
    synthetic_provider: Mapped[str] = mapped_column(String(30), nullable=False)
    raw: Mapped[dict] = mapped_column(JSONB, nullable=False)
    immutable_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    processing_status: Mapped[str] = mapped_column(String(30), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def fingerprint(envelope: RawMessageEnvelope) -> str:
    # received_at is delivery observation time; an identical retry may arrive later.
    content = envelope.model_dump(mode="json", exclude={"received_at"})
    canonical = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def stored(row: InboundMessage) -> StoredMessage:
    return StoredMessage(message_id=row.message_id, raw=RawMessageEnvelope(**row.raw),
                         synthetic_provider=row.synthetic_provider, content_sha256=row.content_sha256,
                         processing_status=row.processing_status, ingested_at=row.ingested_at, updated_at=row.updated_at)


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


class PostgresMessageRepository:
    def __init__(self, engine: Engine):
        self.engine = engine

    def ingest(self, envelope: RawMessageEnvelope, now: datetime) -> IngestResponse:
        digest = fingerprint(envelope)
        try:
            with Session(self.engine) as session, session.begin():
                statement = insert(InboundMessage).values(
                    message_id=str(uuid4()), tenant_id=envelope.tenant_id, channel=envelope.channel,
                    provider_message_id=envelope.provider_message_id, synthetic_provider="SYNTHETIC_WHATSAPP",
                    raw=envelope.model_dump(mode="json"), immutable_fingerprint=digest,
                    content_sha256=hashlib.sha256(envelope.text.encode("utf-8")).hexdigest(),
                    processing_status="RECEIVED", ingested_at=now, updated_at=now,
                ).on_conflict_do_nothing(constraint="uq_p1_delivery").returning(InboundMessage.message_id)
                created_id = session.execute(statement).scalar_one_or_none()
                # PostgreSQL READ COMMITTED: a fresh statement sees the winner of a concurrent insert.
                row = session.scalar(select(InboundMessage).where(
                    InboundMessage.tenant_id == envelope.tenant_id, InboundMessage.channel == envelope.channel,
                    InboundMessage.provider_message_id == envelope.provider_message_id,
                ))
                if row is None:
                    raise PersistenceUnavailable("Message storage temporarily unavailable")
                if row.immutable_fingerprint != digest:
                    raise DuplicateConflict("Provider message ID already has different original content")
                result = IngestResponse(message=stored(row), duplicate=created_id is None)
            # Return only after the transaction commits successfully.
            return result
        except SQLAlchemyError:
            raise PersistenceUnavailable("Message storage temporarily unavailable") from None

    def get(self, tenant_id: str, message_id: str) -> StoredMessage | None:
        try:
            with Session(self.engine) as session:
                row = session.scalar(select(InboundMessage).where(InboundMessage.tenant_id == tenant_id, InboundMessage.message_id == message_id))
                return stored(row) if row else None
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
                    return MessagePage(items=[stored(row) for row in rows], total=total, limit=limit, offset=offset)
        except SQLAlchemyError:
            raise PersistenceUnavailable("Message storage temporarily unavailable") from None

    def awaiting_processing(self, tenant_id: str, limit: int = 25) -> list[StoredMessage]:
        """P1-02 discovery boundary only; no claim, processing, worker or automatic retry."""
        return self.list(tenant_id, processing_status="RECEIVED", limit=limit).items

    def process(self, tenant_id: str, message_id: str, *, reprocess: bool = False, now: datetime | None = None) -> ProcessResponse:
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

                if not reprocess:
                    existing_attempt = session.scalar(
                        select(ExtractionAttempt).where(
                            ExtractionAttempt.tenant_id == tenant_id,
                            ExtractionAttempt.message_id == message_id,
                            ExtractionAttempt.extractor_version == extractor_version,
                            ExtractionAttempt.input_content_sha256 == row.content_sha256,
                            ExtractionAttempt.status == "PROCESSED",
                        ).order_by(desc(ExtractionAttempt.started_at)).limit(1)
                    )
                    if existing_attempt is not None:
                        return ProcessResponse(
                            message=stored(row),
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
                completed_time = datetime.now(timezone.utc)
                try:
                    result = extract_explicit_fields(stored_msg, catalog=PROVISIONAL_PRODUCTS)
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
                    attempt.status = "PROCESSED"
                    attempt.fields = [f.model_dump(mode="json") for f in result.fields]
                    attempt.completed_at = completed_time
                    row.processing_status = "PROCESSED"
                    row.updated_at = completed_time
                except Exception as exc:
                    attempt.status = "PROCESSING_FAILED"
                    attempt.diagnostic = str(exc)[:1000]
                    attempt.completed_at = completed_time
                    row.processing_status = "PROCESSING_FAILED"
                    row.updated_at = completed_time

                session.flush()
                return ProcessResponse(
                    message=stored(row),
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
