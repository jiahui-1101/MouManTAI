"""Persist P4 requests, source aliases, drafts and terminal draft reviews.

Revision ID is kept within Alembic's default 32-character version column.
Frozen DDL: do not import application models into historical migrations.
"""

from alembic import op
import sqlalchemy as sa

revision = "0008_p4_communication"
down_revision = "0007_recovery_case_constraints_alignment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "communication_requests",
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("communication_id", sa.String(128), nullable=False),
        sa.Column("commitment_id", sa.String(128), nullable=False),
        sa.Column("proposal_id", sa.String(128), nullable=False),
        sa.Column("proposal_version", sa.Integer(), nullable=False),
        sa.Column("request_status", sa.String(32), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "communication_id"),
        sa.UniqueConstraint("tenant_id", "commitment_id", "proposal_id", "proposal_version",
                            name="uq_communication_request_proposal"),
    )
    op.create_index("ix_communication_requests_tenant_commitment", "communication_requests",
                    ["tenant_id", "commitment_id"])
    op.create_index("ix_communication_requests_tenant_status", "communication_requests",
                    ["tenant_id", "request_status"])
    op.create_table(
        "communication_request_sources",
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("source_event_id", sa.String(128), nullable=False),
        sa.Column("communication_id", sa.String(128), nullable=False),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("reference", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "source_event_id"),
        sa.ForeignKeyConstraint(["tenant_id", "communication_id"],
                                ["communication_requests.tenant_id", "communication_requests.communication_id"],
                                name="fk_communication_source_request"),
    )
    op.create_table(
        "communication_drafts",
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("draft_id", sa.String(128), nullable=False),
        sa.Column("communication_id", sa.String(128), nullable=False),
        sa.Column("validation_hash", sa.String(64), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "draft_id"),
        sa.UniqueConstraint("tenant_id", "communication_id", "draft_id", name="uq_draft_request_identity"),
        sa.UniqueConstraint("tenant_id", "communication_id", "validation_hash",
                            name="uq_communication_draft_variant"),
        sa.ForeignKeyConstraint(["tenant_id", "communication_id"],
                                ["communication_requests.tenant_id", "communication_requests.communication_id"],
                                name="fk_communication_draft_request"),
    )
    op.create_index("ix_communication_drafts_tenant_request", "communication_drafts",
                    ["tenant_id", "communication_id"])
    op.create_table(
        "communication_draft_reviews",
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("review_id", sa.String(128), nullable=False),
        sa.Column("communication_id", sa.String(128), nullable=False),
        sa.Column("draft_id", sa.String(128), nullable=False),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invalidation_code", sa.String(128), nullable=True),
        sa.Column("invalidation_audit_id", sa.String(128), nullable=True),
        sa.PrimaryKeyConstraint("tenant_id", "review_id"),
        sa.ForeignKeyConstraint(["tenant_id", "communication_id", "draft_id"],
                                ["communication_drafts.tenant_id", "communication_drafts.communication_id",
                                 "communication_drafts.draft_id"], name="fk_review_exact_draft"),
        sa.UniqueConstraint("tenant_id", "communication_id", "draft_id", name="uq_review_terminal_draft"),
        sa.UniqueConstraint("tenant_id", "request_key", name="uq_review_request_key"),
    )
    op.create_index("ix_review_tenant_request", "communication_draft_reviews", ["tenant_id", "communication_id"])


def downgrade() -> None:
    # Reverse dependency order. Only P4 objects introduced above are removed.
    op.drop_index("ix_review_tenant_request", table_name="communication_draft_reviews")
    op.drop_table("communication_draft_reviews")
    op.drop_index("ix_communication_drafts_tenant_request", table_name="communication_drafts")
    op.drop_table("communication_drafts")
    op.drop_table("communication_request_sources")
    op.drop_index("ix_communication_requests_tenant_status", table_name="communication_requests")
    op.drop_index("ix_communication_requests_tenant_commitment", table_name="communication_requests")
    op.drop_table("communication_requests")
