"""Add P5 evidence links and pending P4 notification intents.

Revision ID: 0023_business_orch_links
Revises: 0022_mock_memory_history
"""

import sqlalchemy as sa
from alembic import op

revision = "0023_business_orch_links"
down_revision = "0022_mock_memory_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "business_orchestration_impact_links",
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("impact_id", sa.String(128), nullable=False),
        sa.Column("commitment_id", sa.String(128), nullable=False),
        sa.Column("event_id", sa.String(128), nullable=False),
        sa.Column("commitment_version", sa.Integer(), nullable=True),
        sa.Column("link_status", sa.String(48), nullable=False),
        sa.Column("classification", sa.String(48), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("resource_refs", sa.JSON(), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("projection", sa.JSON(), nullable=False),
        sa.Column("source_digest", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "impact_id", "commitment_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "commitment_id"], ["commitments.tenant_id", "commitments.commitment_id"],
            name="fk_orchestration_link_commitment", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["p2_supplier_delay_events.tenant_id", "p2_supplier_delay_events.event_id"],
            name="fk_orchestration_link_p2_event", ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "commitment_version IS NULL OR commitment_version >= 1",
            name="ck_orchestration_link_version",
        ),
    )
    op.create_index(
        "ix_orchestration_links_tenant_commitment",
        "business_orchestration_impact_links", ["tenant_id", "commitment_id"],
    )
    op.create_index(
        "ix_orchestration_links_tenant_event",
        "business_orchestration_impact_links", ["tenant_id", "event_id"],
    )

    op.create_table(
        "business_orchestration_notification_intents",
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("intent_id", sa.String(128), nullable=False),
        sa.Column("source_event_id", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("commitment_id", sa.String(128), nullable=False),
        sa.Column("commitment_version", sa.Integer(), nullable=False),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("causation_id", sa.String(128), nullable=True),
        sa.Column("source_event_type", sa.String(128), nullable=False),
        sa.Column("notification_type", sa.String(64), nullable=False),
        sa.Column("integration_mode", sa.String(16), nullable=False),
        sa.Column("status", sa.String(48), nullable=False),
        sa.Column("blocker_codes", sa.JSON(), nullable=False),
        sa.Column("review_requirements", sa.JSON(), nullable=False),
        sa.Column("plan_id", sa.String(128), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("approval_id", sa.String(128), nullable=False),
        sa.Column("task_id", sa.String(128), nullable=False),
        sa.Column("receipt_ref", sa.String(128), nullable=False),
        sa.Column("audit_id", sa.String(128), nullable=False),
        sa.Column("order_request_id", sa.String(128), nullable=True),
        sa.Column("order_request_version", sa.Integer(), nullable=True),
        sa.Column("customer_ref", sa.String(128), nullable=True),
        sa.Column("contact_ref", sa.String(128), nullable=True),
        sa.Column("channel_ref", sa.String(32), nullable=True),
        sa.Column("original_channel_ref", sa.String(128), nullable=True),
        sa.Column("consent_ref", sa.String(256), nullable=True),
        sa.Column("verified_change", sa.JSON(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("source_provenance", sa.JSON(), nullable=False),
        sa.Column("authorization_context", sa.JSON(), nullable=False),
        sa.Column("evidence_tier", sa.String(32), nullable=False),
        sa.Column("verification_status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "intent_id", name="pk_business_orchestration_notification_intents"),
        sa.UniqueConstraint("tenant_id", "source_event_id", name="uq_orchestration_intent_source_event"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_orchestration_intent_idempotency_key"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "commitment_id"], ["commitments.tenant_id", "commitments.commitment_id"],
            name="fk_orchestration_intent_commitment", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_event_id"], ["outbox_events.event_id"],
            name="fk_orchestration_intent_outbox_event", ondelete="RESTRICT",
        ),
        sa.CheckConstraint("commitment_version >= 1 AND plan_version >= 1",
                           name="ck_orchestration_intent_versions"),
        sa.CheckConstraint("order_request_version IS NULL OR order_request_version >= 1",
                           name="ck_orchestration_intent_order_request_version"),
        sa.CheckConstraint(
            "status IN ('UNRESOLVED_ORDER_ACCEPTANCE','PENDING_P4_REVIEW')",
            name="ck_orchestration_intent_pending_only",
        ),
        sa.CheckConstraint("integration_mode IN ('SYNTHETIC','MOCK')",
                           name="ck_orchestration_intent_integration_mode"),
        sa.CheckConstraint("evidence_tier = 'DEMO-ONLY'",
                           name="ck_orchestration_intent_evidence_tier"),
        sa.CheckConstraint("verification_status = 'INTERNALLY-VERIFIED'",
                           name="ck_orchestration_intent_verification_status"),
    )
    op.create_index(
        "ix_orchestration_intents_tenant_commitment",
        "business_orchestration_notification_intents", ["tenant_id", "commitment_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_orchestration_intents_tenant_commitment",
        table_name="business_orchestration_notification_intents",
    )
    op.drop_table("business_orchestration_notification_intents")
    op.drop_index(
        "ix_orchestration_links_tenant_event", table_name="business_orchestration_impact_links",
    )
    op.drop_index(
        "ix_orchestration_links_tenant_commitment", table_name="business_orchestration_impact_links",
    )
    op.drop_table("business_orchestration_impact_links")
