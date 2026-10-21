"""Add outbox status/retry tracking, audit causation_id, and processed_events table."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_outbox_processing"
down_revision: Union[str, None] = "0002_commitment_registry"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Update outbox_events with status and retry tracking
    op.add_column(
        "outbox_events",
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PENDING"),
    )
    op.add_column(
        "outbox_events",
        sa.Column("last_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "outbox_events",
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_outbox_events_status_retry",
        "outbox_events",
        ["status", "next_retry_at"],
    )

    # 2. Update audit_events with causation_id
    op.add_column(
        "audit_events",
        sa.Column("causation_id", sa.String(length=128), nullable=True),
    )

    # 3. Create processed_events table for idempotent consumers
    op.create_table(
        "processed_events",
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("consumer_name", sa.String(length=128), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "event_id", "consumer_name"),
    )
    op.create_index(
        "ix_processed_events_tenant_event",
        "processed_events",
        ["tenant_id", "event_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_processed_events_tenant_event", table_name="processed_events")
    op.drop_table("processed_events")
    op.drop_column("audit_events", "causation_id")
    op.drop_index("ix_outbox_events_status_retry", table_name="outbox_events")
    op.drop_column("outbox_events", "next_retry_at")
    op.drop_column("outbox_events", "last_error")
    op.drop_column("outbox_events", "status")
