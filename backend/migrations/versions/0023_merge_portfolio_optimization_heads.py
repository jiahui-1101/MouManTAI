"""Join the portfolio planning and mock optimization migration branches."""


revision = "0023_merge_portfolio_optimization_heads"
down_revision = (
    "0022_mock_optimization_dataset",
    "0022_portfolio_demo_planning_inputs",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
