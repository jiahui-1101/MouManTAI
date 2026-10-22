"""Join the integrated P3 branch and Main's P4 customer confirmations.

Revision ID: 0014_merge_p3_p4_confirmations
Revises: 0013_merge_p3_p4_heads, 0011_p4_confirmations
"""

revision = "0014_merge_p3_p4_confirmations"
down_revision = ("0013_merge_p3_p4_heads", "0011_p4_confirmations")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
