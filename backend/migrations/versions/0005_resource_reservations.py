"""Add resource_stocks and resource_reservations tables for mock inventory and concurrency locking."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005_resource_reservations"
down_revision: Union[str, None] = "0004_commitment_proposals"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. resource_stocks table
    op.create_table(
        "resource_stocks",
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("resource_id", sa.String(length=128), nullable=False),
        sa.Column("total_quantity", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("reserved_quantity", sa.Numeric(precision=18, scale=4), server_default="0", nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("snapshot_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "resource_id"),
    )
    op.create_index(
        "ix_resource_stocks_tenant_updated",
        "resource_stocks",
        ["tenant_id", "updated_at"],
    )

    # 2. resource_reservations table
    op.create_table(
        "resource_reservations",
        sa.Column("reservation_id", sa.String(length=128), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("commitment_id", sa.String(length=128), nullable=False),
        sa.Column("plan_id", sa.String(length=128), nullable=False),
        sa.Column("action_id", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("resource_id", sa.String(length=128), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=18, scale=4), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="ACTIVE", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("reservation_id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_resource_reservations_tenant_idempotency"),
    )
    op.create_index(
        "ix_resource_reservations_tenant_commitment",
        "resource_reservations",
        ["tenant_id", "commitment_id"],
    )
    op.create_index(
        "ix_resource_reservations_tenant_resource_status",
        "resource_reservations",
        ["tenant_id", "resource_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_resource_reservations_tenant_resource_status", table_name="resource_reservations")
    op.drop_index("ix_resource_reservations_tenant_commitment", table_name="resource_reservations")
    op.drop_table("resource_reservations")
    op.drop_index("ix_resource_stocks_tenant_updated", table_name="resource_stocks")
    op.drop_table("resource_stocks")
