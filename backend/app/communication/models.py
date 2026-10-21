"""P4-owned persistence. P5 must register metadata and supply the Alembic migration."""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKeyConstraint, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CommunicationRequestRecord(Base):
    __tablename__ = "communication_requests"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    communication_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    commitment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    proposal_id: Mapped[str] = mapped_column(String(128), nullable=False)
    proposal_version: Mapped[int] = mapped_column(Integer, nullable=False)
    request_status: Mapped[str] = mapped_column(String(32), nullable=False)
    # Immutable, validated intake snapshot. It is never used as current authorization.
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "commitment_id", "proposal_id", "proposal_version",
            name="uq_communication_request_proposal",
        ),
        Index("ix_communication_requests_tenant_commitment", "tenant_id", "commitment_id"),
        Index("ix_communication_requests_tenant_status", "tenant_id", "request_status"),
    )


class CommunicationSourceEventRecord(Base):
    """Multiple deliveries/events can reference one logical communication request."""

    __tablename__ = "communication_request_sources"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    communication_id: Mapped[str] = mapped_column(String(128), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    # Preserve provenance for every event alias, rather than overwriting the first.
    reference: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "communication_id"],
            ["communication_requests.tenant_id", "communication_requests.communication_id"],
            name="fk_communication_source_request",
        ),
    )


class MessageDraftRecord(Base):
    __tablename__ = "communication_drafts"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    draft_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    communication_id: Mapped[str] = mapped_column(String(128), nullable=False)
    # Binds proposal/commitment/plan, approved terms/evidence, template/language/channel.
    validation_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "communication_id"],
            ["communication_requests.tenant_id", "communication_requests.communication_id"],
            name="fk_communication_draft_request",
        ),
        UniqueConstraint(
            "tenant_id", "communication_id", "validation_hash",
            name="uq_communication_draft_variant",
        ),
        Index("ix_communication_drafts_tenant_request", "tenant_id", "communication_id"),
    )
