"""Durable v2.2 request state and explicitly synthetic source evidence."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MockOrderSourceRecord(Base):
    """Controlled fixture source. Never evidence of a production customer action."""

    __tablename__ = "mock_order_sources"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_version: Mapped[int] = mapped_column(Integer, nullable=False)
    terms: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    customer_request_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    price_disclosure_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_through: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)


class OrderRequestRecord(Base):
    __tablename__ = "order_requests"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    order_request_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_valid_through: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_evidence_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    terms: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    terms_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    request_version: Mapped[int] = mapped_column(Integer, nullable=False)
    decision_status: Mapped[str] = mapped_column(String(32), nullable=False)
    review_actor_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    commitment_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "source_id"],
            ["mock_order_sources.tenant_id", "mock_order_sources.source_id"],
            name="fk_order_request_mock_source", ondelete="RESTRICT",
        ),
        Index("ix_order_requests_tenant_status", "tenant_id", "decision_status"),
    )


class OrderRequestAuditRecord(Base):
    __tablename__ = "order_request_audit"

    audit_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    order_request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    request_version: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_order_request_audit_tenant_order", "tenant_id", "order_request_id", "occurred_at"),
    )


class MockOrbyteStateRecord(Base):
    """One tenant-scoped synthetic resource/BOM/capacity snapshot and command lock."""

    __tablename__ = "mock_orbyte_states"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    snapshot_version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    next_outcome: Mapped[str] = mapped_column(String(32), nullable=False, default="NORMAL")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MockOrbyteReservationRecord(Base):
    __tablename__ = "mock_orbyte_reservations"

    operation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    order_request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_version: Mapped[int] = mapped_column(Integer, nullable=False)
    terms_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    snapshot_version: Mapped[int] = mapped_column(Integer, nullable=False)
    assessment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    approval_reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    receipt: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_mock_reservation_tenant_key"),
        Index("ix_mock_reservation_tenant_order", "tenant_id", "order_request_id"),
    )
