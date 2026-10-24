"""Controlled synthetic demand history for registered forecasting APIs."""

import sqlalchemy as sa
from alembic import op

revision = "0020_mock_forecast_history"
down_revision = "0019_mock_supplier_advice"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mock_forecast_datasets",
        sa.Column("tenant_id", sa.String(128), primary_key=True),
        sa.Column("dataset_id", sa.String(128), primary_key=True),
        sa.Column("sku_id", sa.String(128), nullable=False),
        sa.Column("unit", sa.String(64), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("observations", sa.JSON(), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_mock_forecast_tenant_sku", "mock_forecast_datasets", ["tenant_id", "sku_id"])
    op.create_table(
        "mock_forecast_audit",
        sa.Column("audit_id", sa.String(128), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("dataset_id", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("mock_forecast_audit")
    op.drop_index("ix_mock_forecast_tenant_sku", table_name="mock_forecast_datasets")
    op.drop_table("mock_forecast_datasets")
