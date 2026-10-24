"""P5-owned derived links and pending P4 handoff intents.

These rows reference canonical Core, P2 and P3 records. They are not business
state, Recovery authority, customer status, or outbound communication records.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class BusinessImpactLinkRecord(Base):
    __tablename__ = "business_orchestration_impact_links"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    impact_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    commitment_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    commitment_version: Mapped[int | None] = mapped_column(Integer)
    link_status: Mapped[str] = mapped_column(String(48), nullable=False)
    classification: Mapped[str] = mapped_column(String(48), nullable=False)
    evidence_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    resource_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    projection: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    source_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "commitment_id"],
            ["commitments.tenant_id", "commitments.commitment_id"],
            name="fk_orchestration_link_commitment", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["p2_supplier_delay_events.tenant_id", "p2_supplier_delay_events.event_id"],
            name="fk_orchestration_link_p2_event", ondelete="RESTRICT",
        ),
        Index("ix_orchestration_links_tenant_commitment", "tenant_id", "commitment_id"),
        Index("ix_orchestration_links_tenant_event", "tenant_id", "event_id"),
        CheckConstraint("commitment_version IS NULL OR commitment_version >= 1",
                        name="ck_orchestration_link_version"),
    )


class BusinessNotificationIntentRecord(Base):
    __tablename__ = "business_orchestration_notification_intents"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    intent_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    commitment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    commitment_version: Mapped[int] = mapped_column(Integer, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    causation_id: Mapped[str | None] = mapped_column(String(128))
    source_event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    notification_type: Mapped[str] = mapped_column(String(64), nullable=False)
    integration_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(48), nullable=False)
    blocker_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    review_requirements: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    plan_id: Mapped[str] = mapped_column(String(128), nullable=False)
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    approval_id: Mapped[str] = mapped_column(String(128), nullable=False)
    task_id: Mapped[str] = mapped_column(String(128), nullable=False)
    receipt_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    audit_id: Mapped[str] = mapped_column(String(128), nullable=False)
    order_request_id: Mapped[str | None] = mapped_column(String(128))
    order_request_version: Mapped[int | None] = mapped_column(Integer)
    customer_ref: Mapped[str | None] = mapped_column(String(128))
    contact_ref: Mapped[str | None] = mapped_column(String(128))
    channel_ref: Mapped[str | None] = mapped_column(String(32))
    original_channel_ref: Mapped[str | None] = mapped_column(String(128))
    consent_ref: Mapped[str | None] = mapped_column(String(256))
    verified_change: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    evidence_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    source_provenance: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    authorization_context: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    evidence_tier: Mapped[str] = mapped_column(String(32), nullable=False)
    verification_status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "commitment_id"],
            ["commitments.tenant_id", "commitments.commitment_id"],
            name="fk_orchestration_intent_commitment", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_event_id"], ["outbox_events.event_id"],
            name="fk_orchestration_intent_outbox_event", ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "source_event_id", name="uq_orchestration_intent_source_event"),
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_orchestration_intent_idempotency_key"),
        Index("ix_orchestration_intents_tenant_commitment", "tenant_id", "commitment_id", "created_at"),
        CheckConstraint("commitment_version >= 1 AND plan_version >= 1",
                        name="ck_orchestration_intent_versions"),
        CheckConstraint("order_request_version IS NULL OR order_request_version >= 1",
                        name="ck_orchestration_intent_order_request_version"),
        CheckConstraint("status IN ('UNRESOLVED_ORDER_ACCEPTANCE','PENDING_P4_REVIEW')",
                        name="ck_orchestration_intent_pending_only"),
        CheckConstraint("integration_mode IN ('SYNTHETIC','MOCK')",
                        name="ck_orchestration_intent_integration_mode"),
        CheckConstraint("evidence_tier = 'DEMO-ONLY'",
                        name="ck_orchestration_intent_evidence_tier"),
        CheckConstraint("verification_status = 'INTERNALLY-VERIFIED'",
                        name="ck_orchestration_intent_verification_status"),
    )
