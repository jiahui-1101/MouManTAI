"""Persist P4 synthetic and operational orders read model.

Revision ID: 0019_p4_orders_persistence
Revises: 0018_mock_order_requests
Create Date: 2026-10-25
"""

from alembic import op, context
import sqlalchemy as sa


revision = "0019_p4_orders_persistence"
down_revision = "0018_mock_order_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Offline mode cannot inspect database tables.
    if context.is_offline_mode():
        should_create = True
    else:
        conn = op.get_bind()
        inspector = sa.inspect(conn)
        should_create = "p4_orders" not in inspector.get_table_names()

    if should_create:
        op.create_table(
            "p4_orders",
            sa.Column("tenant_id", sa.String(128), nullable=False),
            sa.Column("order_id", sa.String(128), nullable=False),
            sa.Column("commitment_id", sa.String(128), nullable=True),
            sa.Column("customer_display_name", sa.String(255), nullable=False),
            sa.Column("requested_items", sa.JSON(), nullable=False),
            sa.Column("requested_delivery_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("lifecycle_status", sa.String(64), nullable=False, server_default="UNKNOWN"),
            sa.Column("source_channel", sa.String(64), nullable=False, server_default="SYNTHETIC"),
            sa.Column("evidence_refs", sa.JSON(), nullable=False),
            sa.Column("integration_mode", sa.String(32), nullable=False, server_default="SYNTHETIC"),
            sa.Column("evidence_tier", sa.String(32), nullable=False, server_default="DEMO-ONLY"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("tenant_id", "order_id", name="pk_p4_orders"),
        )
        op.create_index(
            "ix_p4_orders_tenant_delivery",
            "p4_orders",
            ["tenant_id", "requested_delivery_at"],
        )
        op.create_index(
            "ix_p4_orders_tenant_commitment",
            "p4_orders",
            ["tenant_id", "commitment_id"],
        )


def downgrade() -> None:
    op.drop_index("ix_p4_orders_tenant_commitment", table_name="p4_orders")
    op.drop_index("ix_p4_orders_tenant_delivery", table_name="p4_orders")
    op.drop_table("p4_orders")
