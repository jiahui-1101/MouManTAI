"""Add commitment_proposals table for versioned terms recovery and confirmation tracking."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004_commitment_proposals"
down_revision: Union[str, None] = "0003_outbox_processing"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "commitment_proposals",
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("proposal_id", sa.String(length=128), nullable=False),
        sa.Column("commitment_id", sa.String(length=128), nullable=False),
        sa.Column("proposal_version", sa.Integer(), nullable=False),
        sa.Column("revised_terms", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="ACTIVE"),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "proposal_id"),
    )
    op.create_index(
        "ix_proposals_tenant_commitment_version",
        "commitment_proposals",
        ["tenant_id", "commitment_id", "proposal_version"],
    )
    op.create_index(
        "ix_proposals_tenant_status",
        "commitment_proposals",
        ["tenant_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_proposals_tenant_status", table_name="commitment_proposals")
    op.drop_index("ix_proposals_tenant_commitment_version", table_name="commitment_proposals")
    op.drop_table("commitment_proposals")
