"""Create the shared Commitment Registry, audit and outbox tables."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_commitment_registry"
down_revision: Union[str, None] = "0001_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "commitments",
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("commitment_id", sa.String(length=128), nullable=False),
        sa.Column("order_id", sa.String(length=128), nullable=False),
        sa.Column("customer_id", sa.String(length=128), nullable=False),
        sa.Column("terms", sa.JSON(), nullable=False),
        sa.Column("agreement_state", sa.String(length=32), nullable=False),
        sa.Column("feasibility_state", sa.String(length=32), nullable=False),
        sa.Column("risk_state", sa.String(length=32), nullable=False),
        sa.Column("recovery_state", sa.String(length=32), nullable=False),
        sa.Column("fulfilment_state", sa.String(length=32), nullable=False),
        sa.Column("commitment_version", sa.Integer(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "commitment_id"),
    )
    op.create_index(
        "ix_commitments_tenant_updated",
        "commitments",
        ["tenant_id", "updated_at"],
    )

    op.create_table(
        "audit_events",
        sa.Column("audit_id", sa.String(length=128), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("commitment_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("actor_role", sa.String(length=32), nullable=False),
        sa.Column("dimension", sa.String(length=32), nullable=False),
        sa.Column("previous_state", sa.JSON(), nullable=True),
        sa.Column("new_state", sa.JSON(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("audit_id"),
    )
    op.create_index(
        "ix_audit_events_tenant_commitment",
        "audit_events",
        ["tenant_id", "commitment_id", "occurred_at"],
    )

    op.create_table(
        "outbox_events",
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("commitment_id", sa.String(length=128), nullable=True),
        sa.Column("commitment_version", sa.Integer(), nullable=True),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column("causation_id", sa.String(length=128), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index(
        "ix_outbox_events_tenant_commitment",
        "outbox_events",
        ["tenant_id", "commitment_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_events_tenant_commitment", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_index("ix_audit_events_tenant_commitment", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_commitments_tenant_updated", table_name="commitments")
    op.drop_table("commitments")
