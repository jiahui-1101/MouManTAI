from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CommitmentRecord(Base):
    __tablename__ = "commitments"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    commitment_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(128), nullable=False)
    customer_id: Mapped[str] = mapped_column(String(128), nullable=False)
    terms: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    agreement_state: Mapped[str] = mapped_column(String(32), nullable=False)
    feasibility_state: Mapped[str] = mapped_column(String(32), nullable=False)
    risk_state: Mapped[str] = mapped_column(String(32), nullable=False)
    recovery_state: Mapped[str] = mapped_column(String(32), nullable=False)
    fulfilment_state: Mapped[str] = mapped_column(String(32), nullable=False)
    commitment_version: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_commitments_tenant_updated", "tenant_id", "updated_at"),)


class AuditEventRecord(Base):
    __tablename__ = "audit_events"

    audit_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    commitment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    dimension: Mapped[str] = mapped_column(String(32), nullable=False)
    previous_state: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    new_state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    evidence_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_audit_events_tenant_commitment", "tenant_id", "commitment_id", "occurred_at"),
    )


class OutboxEventRecord(Base):
    __tablename__ = "outbox_events"

    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    commitment_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    commitment_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    causation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
