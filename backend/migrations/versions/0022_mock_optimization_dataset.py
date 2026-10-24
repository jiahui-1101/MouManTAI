"""Persist bounded synthetic CP-SAT advisory inputs."""

import sqlalchemy as sa
from alembic import op

revision = "0022_mock_optimization_dataset"
down_revision = "0021_mock_forecast_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mock_optimization_datasets",
        sa.Column("tenant_id", sa.String(128), primary_key=True),
        sa.Column("dataset_id", sa.String(128), primary_key=True),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("constraint_payload", sa.JSON(), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_mock_opt_tenant_actor", "mock_optimization_datasets", ["tenant_id", "actor_id"])
    op.create_table(
        "mock_optimization_audit",
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
    op.drop_table("mock_optimization_audit")
    op.drop_index("ix_mock_opt_tenant_actor", table_name="mock_optimization_datasets")
    op.drop_table("mock_optimization_datasets")
