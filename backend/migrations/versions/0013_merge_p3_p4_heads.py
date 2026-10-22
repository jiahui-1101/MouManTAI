"""Join the independently published P3 and P4 additive migration branches.

Revision ID: 0013_merge_p3_p4_heads
Revises: 0012_p3_internal_actions, 0010_p4_recipient_preferences
"""

revision = "0013_merge_p3_p4_heads"
down_revision = ("0012_p3_internal_actions", "0010_p4_recipient_preferences")
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Both parents create disjoint tables and constraints from the shared 0008 base.
    pass


def downgrade() -> None:
    pass
