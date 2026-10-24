"""Durable C3 message review candidates and terminal human decisions."""

import sqlalchemy as sa
from alembic import op

revision = "0026_c3_message_reviews"
down_revision = "0025_merge_c1_business_orch"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "c3_message_reviews",
        sa.Column("tenant_id", sa.String(200), primary_key=True),
        sa.Column("review_id", sa.String(128), primary_key=True),
        sa.Column("message_id", sa.String(200), nullable=False),
        sa.Column("candidate_hash", sa.String(64), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("source_snapshot", sa.JSON(), nullable=False),
        sa.Column("candidate_snapshot", sa.JSON(), nullable=False),
        sa.Column("provider_attempts", sa.JSON(), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decision", sa.String(24)),
        sa.Column("corrected_intent", sa.String(40)),
        sa.Column("decision_reason", sa.String(1000)),
        sa.Column("reviewer_id", sa.String(128)),
        sa.Column("reviewer_role", sa.String(32)),
        sa.Column("authorization_evidence_refs", sa.JSON()),
        sa.Column("request_key", sa.String(128)),
        sa.UniqueConstraint("tenant_id", "message_id", "candidate_hash", name="uq_c3_review_candidate"),
        sa.UniqueConstraint("tenant_id", "request_key", name="uq_c3_review_request_key"),
    )
    op.create_index("ix_c3_review_queue", "c3_message_reviews", ["tenant_id", "state", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_c3_review_queue", table_name="c3_message_reviews")
    op.drop_table("c3_message_reviews")
