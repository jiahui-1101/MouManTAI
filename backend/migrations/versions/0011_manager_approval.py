"""Core durable synthetic Manager decisions.

Revision ID: 0011_manager_approval
Revises: 0010_p3_recovery_plans
"""

from alembic import op
import sqlalchemy as sa

revision = "0011_manager_approval"
down_revision = "0010_p3_recovery_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "manager_approval_decisions",
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("approval_id", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("commitment_id", sa.String(128), nullable=False),
        sa.Column("case_id", sa.String(128), nullable=False),
        sa.Column("plan_id", sa.String(128), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("proposal_id", sa.String(128), nullable=False),
        sa.Column("proposal_version", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.String(128), nullable=False),
        sa.Column("snapshot_version", sa.Integer(), nullable=False),
        sa.Column("commitment_version", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("action_scope", sa.JSON(), nullable=False),
        sa.Column("approved_terms", sa.JSON(), nullable=False),
        sa.Column("approved_amount", sa.Numeric(18, 4), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("actor_role", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(512), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("audit_id", sa.String(128), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "approval_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "plan_id", "plan_version"],
            ["recovery_plan_versions.tenant_id", "recovery_plan_versions.plan_id",
             "recovery_plan_versions.plan_version"],
            name="fk_manager_approval_plan", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_manager_approval_key"),
        sa.CheckConstraint("plan_version >= 1", name="ck_manager_approval_plan_version"),
        sa.CheckConstraint("approved_amount >= 0", name="ck_manager_approval_amount"),
    )


def downgrade() -> None:
    op.drop_table("manager_approval_decisions")
