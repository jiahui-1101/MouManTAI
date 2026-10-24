"""Persist synthetic decision-history source and audit."""

import sqlalchemy as sa
from alembic import op

revision = "0022_mock_memory_history"
down_revision = "0021_mock_optimization_dataset"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mock_memory_datasets",
        sa.Column("tenant_id", sa.String(128), primary_key=True),
        sa.Column("dataset_id", sa.String(128), primary_key=True),
        sa.Column("domain", sa.String(32), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("cases", sa.JSON(), nullable=False),
        sa.Column("policy", sa.JSON(), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_mock_memory_tenant_domain", "mock_memory_datasets", ["tenant_id", "domain"])
    op.create_table(
        "mock_memory_audit",
        sa.Column("audit_id", sa.String(128), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("dataset_id", sa.String(128), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("mock_memory_audit")
    op.drop_index("ix_mock_memory_tenant_domain", table_name="mock_memory_datasets")
    op.drop_table("mock_memory_datasets")
