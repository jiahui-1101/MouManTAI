"""Persist every C3 classification outcome for verified P1 ingress."""

import sqlalchemy as sa
from alembic import op

revision = "0027_c3_verified_ingress"
down_revision = "0026_c3_message_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "c3_classification_results",
        sa.Column("tenant_id", sa.String(200), primary_key=True),
        sa.Column("message_id", sa.String(200), primary_key=True),
        sa.Column("source_hash", sa.String(64), primary_key=True),
        sa.Column("outcome", sa.JSON(), nullable=False),
        sa.Column("review_id", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_c3_classification_message", "c3_classification_results", ["tenant_id", "message_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_c3_classification_message", table_name="c3_classification_results")
    op.drop_table("c3_classification_results")
