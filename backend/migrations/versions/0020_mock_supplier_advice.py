"""Persist synthetic supplier source datasets and human advisory selections."""

import sqlalchemy as sa
from alembic import op

revision = "0020_mock_supplier_advice"
down_revision = "0019_p4_orders_persistence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mock_supplier_datasets",
        sa.Column("tenant_id", sa.String(128), primary_key=True),
        sa.Column("dataset_id", sa.String(128), primary_key=True),
        sa.Column("dataset_version", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.String(128), nullable=False),
        sa.Column("spec", sa.JSON(), nullable=False),
        sa.Column("requirement", sa.JSON(), nullable=False),
        sa.Column("offers", sa.JSON(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_through", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("dataset_version > 0", name="ck_mock_supplier_dataset_version"),
    )
    op.create_index("ix_mock_supplier_tenant_category", "mock_supplier_datasets",
                    ["tenant_id", "category_id"])
    op.create_table(
        "mock_supplier_selections",
        sa.Column("tenant_id", sa.String(128), primary_key=True),
        sa.Column("selection_id", sa.String(128), primary_key=True),
        sa.Column("dataset_id", sa.String(128), nullable=False),
        sa.Column("dataset_version", sa.Integer(), nullable=False),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("supplier_id", sa.String(128), nullable=False),
        sa.Column("quote_id", sa.String(128), nullable=False),
        sa.Column("quote_version", sa.Integer(), nullable=False),
        sa.Column("comparison_status", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("selected_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id", "dataset_id"],
                                ["mock_supplier_datasets.tenant_id", "mock_supplier_datasets.dataset_id"],
                                name="fk_mock_supplier_selection_dataset", ondelete="RESTRICT"),
        sa.UniqueConstraint("tenant_id", "dataset_id", name="uq_mock_supplier_one_selection"),
        sa.UniqueConstraint("tenant_id", "request_key", name="uq_mock_supplier_selection_key"),
        sa.CheckConstraint("dataset_version > 0", name="ck_mock_supplier_selection_version"),
        sa.CheckConstraint("quote_version > 0", name="ck_mock_supplier_quote_version"),
        sa.CheckConstraint("comparison_status IN ('MATCHES', 'CONDITIONAL')",
                           name="ck_mock_supplier_selected_status"),
    )
    op.create_table(
        "mock_supplier_audit",
        sa.Column("audit_id", sa.String(128), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("dataset_id", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_mock_supplier_audit_tenant_dataset", "mock_supplier_audit",
                    ["tenant_id", "dataset_id", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_mock_supplier_audit_tenant_dataset", table_name="mock_supplier_audit")
    op.drop_table("mock_supplier_audit")
    op.drop_table("mock_supplier_selections")
    op.drop_index("ix_mock_supplier_tenant_category", table_name="mock_supplier_datasets")
    op.drop_table("mock_supplier_datasets")
