"""Join merged C1/A-H history with the published business orchestration branch.

The two parents own their independent schema changes. This revision changes
only the Alembic graph and deliberately performs no data or schema migration.
"""

revision = "0025_merge_c1_business_orch"
down_revision = ("0024_merge_c1_ah", "0024_business_orch_links")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
