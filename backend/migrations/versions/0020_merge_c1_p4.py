"""Join C1 persistence and P4 orders persistence branches.

Revision ID: 0020_merge_c1_p4
Revises: 0019_merge_c1_mock, 0019_p4_orders_persistence
"""

revision = "0020_merge_c1_p4"
down_revision = ("0019_merge_c1_mock", "0019_p4_orders_persistence")
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Parent revisions own their independent schemas; this revision only joins them.
    pass


def downgrade() -> None:
    pass
