"""Join C1 scoped-message and synthetic Mock order migration branches.

Revision ID: 0019_merge_c1_mock
Revises: 0018_c1_scoped_message_parent, 0018_mock_order_requests
"""

revision = "0019_merge_c1_mock"
down_revision = ("0018_c1_scoped_message_parent", "0018_mock_order_requests")
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The parent revisions are independent and remain responsible for their schemas.
    pass


def downgrade() -> None:
    pass
