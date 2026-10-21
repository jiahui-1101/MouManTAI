"""Provisional P1 PostgreSQL tables. Explicit init only, separate from P5 migrations."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from uuid import uuid4

from sqlalchemy import CheckConstraint, DateTime, Index, String, UniqueConstraint, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from .ingestion_schemas import IngestResponse, MessagePage, StoredMessage
from .repository import DuplicateConflict, PersistenceUnavailable
from .schemas import Channel, ProcessingStatus, RawMessageEnvelope


class P1Base(DeclarativeBase):
    pass


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
