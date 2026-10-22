"""P4-owned durable persistence; explicit Alembic migrations own schema upgrades."""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKeyConstraint, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RecipientPreferenceRecord(Base):
    __tablename__ = "communication_recipient_preferences"
    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    channel: Mapped[str] = mapped_column(String(32), primary_key=True)
    consent_purpose: Mapped[str] = mapped_column(String(64), primary_key=True)
    recipient_identity_id: Mapped[str] = mapped_column(String(200), nullable=False)
    consent_status: Mapped[str] = mapped_column(String(16), nullable=False)
    consent_evidence_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    consent_recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consent_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    allowed_contact_hours: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    last_audit_id: Mapped[str] = mapped_column(String(128), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_by_actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    __table_args__ = (
        CheckConstraint("consent_status IN ('OPTED_IN','OPTED_OUT')", name="ck_preference_status"),
        CheckConstraint("version >= 1", name="ck_preference_version"),
        CheckConstraint("channel IN ('MOCK_EMAIL','MOCK_WHATSAPP','MOCK_TELEGRAM')", name="ck_preference_channel"),
        CheckConstraint("consent_purpose = 'TRANSACTIONAL_REVISED_TERMS'", name="ck_preference_purpose"),
        CheckConstraint("source = 'SYNTHETIC_FIXTURE'", name="ck_preference_source"),
        CheckConstraint("consent_expires_at > consent_recorded_at", name="ck_preference_expiry"),
        CheckConstraint("(consent_status = 'OPTED_OUT' AND revoked_at IS NOT NULL) OR (consent_status = 'OPTED_IN' AND revoked_at IS NULL)", name="ck_preference_revocation"),
    )


class RecipientPreferenceChangeRecord(Base):
    """Append-only service journal; this is consent history, never plan approval."""
    __tablename__ = "communication_recipient_preference_changes"
    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    audit_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    command_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    customer_id: Mapped[str] = mapped_column(String(128), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    consent_purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_state: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    new_state: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint("tenant_id", "request_key", name="uq_preference_change_key"),
        UniqueConstraint("tenant_id", "customer_id", "channel", "consent_purpose", "version", name="uq_preference_change_version"),
        ForeignKeyConstraint(["tenant_id", "customer_id", "channel", "consent_purpose"],
            ["communication_recipient_preferences.tenant_id", "communication_recipient_preferences.customer_id", "communication_recipient_preferences.channel", "communication_recipient_preferences.consent_purpose"], name="fk_preference_change_scope"),
    )


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
        UniqueConstraint("tenant_id", "communication_id", "draft_id", name="uq_draft_request_identity"),
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


class DraftReviewRecord(Base):
    __tablename__ = "communication_draft_reviews"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    review_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    communication_id: Mapped[str] = mapped_column(String(128), nullable=False)
    draft_id: Mapped[str] = mapped_column(String(128), nullable=False)
    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    # Original terminal decision never overwritten. Invalidation only adds a latch.
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidation_code: Mapped[str | None] = mapped_column(String(128))
    invalidation_audit_id: Mapped[str | None] = mapped_column(String(128))

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "communication_id", "draft_id"],
            ["communication_drafts.tenant_id", "communication_drafts.communication_id", "communication_drafts.draft_id"],
            name="fk_review_exact_draft",
        ),
        UniqueConstraint("tenant_id", "communication_id", "draft_id", name="uq_review_terminal_draft"),
        UniqueConstraint("tenant_id", "request_key", name="uq_review_request_key"),
        UniqueConstraint("tenant_id", "communication_id", "draft_id", "review_id", name="uq_review_exact_identity"),
        Index("ix_review_tenant_request", "tenant_id", "communication_id"),
    )


class OutboundMessageRecord(Base):
    __tablename__ = "communication_outbound_messages"
    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    outbound_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    communication_id: Mapped[str] = mapped_column(String(128), nullable=False)
    draft_id: Mapped[str] = mapped_column(String(128), nullable=False)
    approved_review_id: Mapped[str] = mapped_column(String(128), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    validation_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    recipient_identity_id: Mapped[str] = mapped_column(String(128), nullable=False)
    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_reference: Mapped[str | None] = mapped_column(String(128))
    provider_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    authorization_evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(128))
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "communication_id", "draft_id", "approved_review_id"],
            ["communication_draft_reviews.tenant_id", "communication_draft_reviews.communication_id",
             "communication_draft_reviews.draft_id", "communication_draft_reviews.review_id"], name="fk_outbound_exact_review"),
        UniqueConstraint("tenant_id", "draft_id", name="uq_outbound_one_draft"),
        UniqueConstraint("tenant_id", "outbound_id", "communication_id", "draft_id", "approved_review_id", name="uq_outbound_confirmation_binding"),
        UniqueConstraint("tenant_id", "request_key", name="uq_outbound_request_key"),
        UniqueConstraint("channel", "provider_reference", name="uq_outbound_provider_reference"),
        CheckConstraint("status IN ('QUEUED','SENT','FAILED','DELIVERY_UNKNOWN')", name="ck_outbound_status"),
        CheckConstraint("(status = 'SENT' AND provider_confirmed AND provider_reference IS NOT NULL AND sent_at IS NOT NULL) OR (status <> 'SENT' AND NOT provider_confirmed AND sent_at IS NULL)", name="ck_outbound_confirmed_sent"),
        Index("ix_outbound_tenant_request", "tenant_id", "communication_id"),
        Index("ix_outbound_tenant_status", "tenant_id", "status"),
    )


class SendAttemptRecord(Base):
    __tablename__ = "communication_send_attempts"
    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    outbound_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    attempt_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_reference: Mapped[str | None] = mapped_column(String(128))
    error_code: Mapped[str | None] = mapped_column(String(128))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "outbound_id"],
            ["communication_outbound_messages.tenant_id", "communication_outbound_messages.outbound_id"], name="fk_attempt_outbound"),
        CheckConstraint("attempt_number = 1", name="ck_attempt_one_submission"),
        CheckConstraint("status IN ('QUEUED','SENT','FAILED','DELIVERY_UNKNOWN')", name="ck_attempt_status"),
    )


class ConfirmationSessionRecord(Base):
    __tablename__ = "communication_confirmation_sessions"
    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    confirmation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    outbound_id: Mapped[str] = mapped_column(String(128), nullable=False)
    communication_id: Mapped[str] = mapped_column(String(128), nullable=False)
    draft_id: Mapped[str] = mapped_column(String(128), nullable=False)
    approved_review_id: Mapped[str] = mapped_column(String(128), nullable=False)
    customer_id: Mapped[str] = mapped_column(String(128), nullable=False)
    recipient_identity_id: Mapped[str] = mapped_column(String(200), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    token_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    binding: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "outbound_id", "communication_id", "draft_id", "approved_review_id"],
            ["communication_outbound_messages.tenant_id", "communication_outbound_messages.outbound_id",
             "communication_outbound_messages.communication_id", "communication_outbound_messages.draft_id",
             "communication_outbound_messages.approved_review_id"], name="fk_confirmation_exact_outbound"),
        UniqueConstraint("tenant_id", "outbound_id", name="uq_confirmation_one_outbound"),
        UniqueConstraint("token_digest", name="uq_confirmation_token_digest"),
        CheckConstraint("channel IN ('MOCK_EMAIL','MOCK_WHATSAPP','MOCK_TELEGRAM')", name="ck_confirmation_mock_channel"),
        CheckConstraint("expires_at > created_at", name="ck_confirmation_expiry"),
        CheckConstraint("(state IN ('ACCEPTED','REJECTED','COUNTEROFFER_RECEIVED') AND consumed_at IS NOT NULL) OR (state IN ('AWAITING_RESPONSE','CLARIFICATION_REQUIRED','UNRESOLVED') AND consumed_at IS NULL)", name="ck_confirmation_consumption"),
        Index("ix_confirmation_tenant_request", "tenant_id", "communication_id"),
    )


class ConfirmationAttemptRecord(Base):
    __tablename__ = "communication_confirmation_attempts"
    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    attempt_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    confirmation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    inbound_message_id: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_message_id: Mapped[str] = mapped_column(String(200), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    proof_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    source_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "confirmation_id"],
            ["communication_confirmation_sessions.tenant_id", "communication_confirmation_sessions.confirmation_id"], name="fk_confirmation_attempt_session"),
        UniqueConstraint("tenant_id", "channel", "provider_message_id", name="uq_confirmation_provider_message"),
        UniqueConstraint("tenant_id", "inbound_message_id", name="uq_confirmation_inbound_message"),
        UniqueConstraint("tenant_id", "confirmation_id", "attempt_id", name="uq_confirmation_attempt_binding"),
        Index("ix_confirmation_attempt_history", "tenant_id", "confirmation_id", "received_at"),
    )


class ConfirmationDecisionRecord(Base):
    __tablename__ = "communication_confirmation_decisions"
    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    decision_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    confirmation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    attempt_id: Mapped[str] = mapped_column(String(128), nullable=False)
    terminal_confirmation_id: Mapped[str | None] = mapped_column(String(128))
    intent: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(String(128), nullable=False)
    proposed_changes: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "confirmation_id", "attempt_id"],
            ["communication_confirmation_attempts.tenant_id", "communication_confirmation_attempts.confirmation_id", "communication_confirmation_attempts.attempt_id"], name="fk_confirmation_decision_attempt"),
        UniqueConstraint("tenant_id", "attempt_id", name="uq_confirmation_attempt_decision"),
        UniqueConstraint("tenant_id", "terminal_confirmation_id", name="uq_confirmation_terminal_decision"),
        CheckConstraint("(intent IN ('ACCEPT','REJECT','COUNTEROFFER') AND terminal_confirmation_id IS NOT NULL AND terminal_confirmation_id = confirmation_id) OR (intent IN ('CLARIFICATION','UNKNOWN') AND terminal_confirmation_id IS NULL)", name="ck_confirmation_terminal_binding"),
    )
