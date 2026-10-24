"""Persist canonical requests imported from controlled Mock customer sources."""

import sqlalchemy as sa
from alembic import op

revision = "0018_mock_order_requests"
down_revision = "0017_p1_real_channel_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mock_order_sources",
        sa.Column("tenant_id", sa.String(128), primary_key=True),
        sa.Column("source_id", sa.String(128), primary_key=True),
        sa.Column("customer_id", sa.String(128), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("terms", sa.JSON(), nullable=False),
        sa.Column("customer_request_ref", sa.String(128), nullable=False),
        sa.Column("price_disclosure_ref", sa.String(128), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_through", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.CheckConstraint("source_version > 0", name="ck_mock_order_source_version"),
        sa.CheckConstraint("status IN ('CURRENT', 'REVOKED')", name="ck_mock_order_source_status"),
    )
    op.create_table(
        "order_requests",
        sa.Column("tenant_id", sa.String(128), primary_key=True),
        sa.Column("order_request_id", sa.String(128), primary_key=True),
        sa.Column("customer_id", sa.String(128), nullable=False),
        sa.Column("source_id", sa.String(128), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("source_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_valid_through", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_evidence_refs", sa.JSON(), nullable=False),
        sa.Column("terms", sa.JSON(), nullable=False),
        sa.Column("terms_hash", sa.String(80), nullable=False),
        sa.Column("request_version", sa.Integer(), nullable=False),
        sa.Column("decision_status", sa.String(32), nullable=False),
        sa.Column("review_actor_id", sa.String(128)),
        sa.Column("review_reason", sa.Text()),
        sa.Column("commitment_id", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "source_id"],
            ["mock_order_sources.tenant_id", "mock_order_sources.source_id"],
            name="fk_order_request_mock_source", ondelete="RESTRICT",
        ),
        sa.CheckConstraint("request_version > 0", name="ck_order_request_version"),
        sa.CheckConstraint(
            "decision_status IN ('PENDING', 'REVIEWED', 'RESERVATION_UNKNOWN', 'REJECTED', 'ACCEPTED')",
            name="ck_order_request_decision_status",
        ),
    )
    op.create_index("ix_order_requests_tenant_status", "order_requests", ["tenant_id", "decision_status"])
    op.create_table(
        "order_request_audit",
        sa.Column("audit_id", sa.String(128), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("order_request_id", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("request_version", sa.Integer(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_order_request_audit_tenant_order", "order_request_audit",
                    ["tenant_id", "order_request_id", "occurred_at"])
    op.create_table(
        "mock_orbyte_states",
        sa.Column("tenant_id", sa.String(128), primary_key=True),
        sa.Column("snapshot_version", sa.Integer(), nullable=False),
        sa.Column("snapshot_payload", sa.JSON(), nullable=False),
        sa.Column("next_outcome", sa.String(32), nullable=False, server_default="NORMAL"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("snapshot_version > 0", name="ck_mock_orbyte_state_version"),
        sa.CheckConstraint("next_outcome IN ('NORMAL', 'REJECT', 'UNKNOWN')", name="ck_mock_orbyte_outcome"),
    )
    op.create_table(
        "mock_orbyte_reservations",
        sa.Column("operation_id", sa.String(128), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("order_request_id", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_version", sa.Integer(), nullable=False),
        sa.Column("terms_hash", sa.String(80), nullable=False),
        sa.Column("snapshot_version", sa.Integer(), nullable=False),
        sa.Column("assessment_id", sa.String(128), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("approval_reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("receipt", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_mock_reservation_tenant_key"),
        sa.CheckConstraint("status IN ('CONFIRMED', 'UNKNOWN', 'FAILED')", name="ck_mock_reservation_status"),
    )
    op.create_index("ix_mock_reservation_tenant_order", "mock_orbyte_reservations",
                    ["tenant_id", "order_request_id"])


def downgrade() -> None:
    op.drop_index("ix_mock_reservation_tenant_order", table_name="mock_orbyte_reservations")
    op.drop_table("mock_orbyte_reservations")
    op.drop_table("mock_orbyte_states")
    op.drop_index("ix_order_request_audit_tenant_order", table_name="order_request_audit")
    op.drop_table("order_request_audit")
    op.drop_index("ix_order_requests_tenant_status", table_name="order_requests")
    op.drop_table("order_requests")
    op.drop_table("mock_order_sources")
