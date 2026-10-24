"""Additive tenant-scoped development planning assumptions for portfolio demo."""
import sqlalchemy as sa
from alembic import op

revision = "0022_portfolio_demo_planning_inputs"
down_revision = "0021_mock_forecast_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "portfolio_demo_bom",
        sa.Column("tenant_id", sa.String(128), primary_key=True),
        sa.Column("sku", sa.String(128), primary_key=True),
        sa.Column("resource_id", sa.String(128), primary_key=True),
        sa.Column("quantity_per_unit", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("provenance", sa.String(32), nullable=False),
        sa.Column("seed_key", sa.String(64), nullable=False),
        sa.CheckConstraint("quantity_per_unit > 0", name="ck_portfolio_bom_positive"),
        sa.CheckConstraint("provenance = 'DEMO_ONLY'", name="ck_portfolio_bom_demo_only"),
    )
    op.create_table(
        "portfolio_demo_financials",
        sa.Column("tenant_id", sa.String(128), primary_key=True),
        sa.Column("sku", sa.String(128), primary_key=True),
        sa.Column("unit_revenue", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit_total_cost", sa.Numeric(18, 4), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("provenance", sa.String(32), nullable=False),
        sa.Column("seed_key", sa.String(64), nullable=False),
        sa.CheckConstraint("unit_revenue >= 0 AND unit_total_cost >= 0", name="ck_portfolio_financial_nonnegative"),
        sa.CheckConstraint("provenance = 'DEMO_ONLY'", name="ck_portfolio_financial_demo_only"),
    )
    op.create_table(
        "portfolio_demo_lots",
        sa.Column("tenant_id", sa.String(128), primary_key=True),
        sa.Column("lot_id", sa.String(128), primary_key=True),
        sa.Column("resource_id", sa.String(128), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("expires_on", sa.Date(), nullable=False),
        sa.Column("provenance", sa.String(32), nullable=False),
        sa.Column("seed_key", sa.String(64), nullable=False),
        sa.UniqueConstraint("tenant_id", "lot_id", name="uq_portfolio_lot_tenant_id"),
        sa.CheckConstraint("quantity > 0", name="ck_portfolio_lot_positive"),
        sa.CheckConstraint("provenance = 'DEMO_ONLY'", name="ck_portfolio_lot_demo_only"),
    )
    op.create_index("ix_portfolio_lots_tenant_resource_expiry", "portfolio_demo_lots",
                    ["tenant_id", "resource_id", "expires_on"])
    op.create_table(
        "portfolio_demo_capacity",
        sa.Column("tenant_id", sa.String(128), primary_key=True),
        sa.Column("capacity_id", sa.String(128), primary_key=True),
        sa.Column("horizon_start", sa.Date(), nullable=False),
        sa.Column("horizon_end", sa.Date(), nullable=False),
        sa.Column("max_units", sa.Numeric(18, 4), nullable=False),
        sa.Column("unit", sa.String(32), nullable=False),
        sa.Column("provenance", sa.String(32), nullable=False),
        sa.Column("seed_key", sa.String(64), nullable=False),
        sa.CheckConstraint("horizon_end >= horizon_start", name="ck_portfolio_capacity_dates"),
        sa.CheckConstraint("max_units > 0", name="ck_portfolio_capacity_positive"),
        sa.CheckConstraint("provenance = 'DEMO_ONLY'", name="ck_portfolio_capacity_demo_only"),
    )


def downgrade() -> None:
    op.drop_table("portfolio_demo_capacity")
    op.drop_index("ix_portfolio_lots_tenant_resource_expiry", table_name="portfolio_demo_lots")
    op.drop_table("portfolio_demo_lots")
    op.drop_table("portfolio_demo_financials")
    op.drop_table("portfolio_demo_bom")
