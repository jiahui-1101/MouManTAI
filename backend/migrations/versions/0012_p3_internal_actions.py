"""Persist verified synthetic internal task and execution receipt.

Revision ID: 0012_p3_internal_actions
Revises: 0011_manager_approval
"""

from alembic import op
import sqlalchemy as sa

revision = "0012_p3_internal_actions"
down_revision = "0011_manager_approval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "internal_recovery_tasks",
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("task_id", sa.String(128), nullable=False),
        sa.Column("commitment_id", sa.String(128), nullable=False),
        sa.Column("plan_id", sa.String(128), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("task_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "task_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "plan_id", "plan_version"],
            ["recovery_plan_versions.tenant_id", "recovery_plan_versions.plan_id",
             "recovery_plan_versions.plan_version"],
            name="fk_internal_task_plan", ondelete="RESTRICT",
        ),
    )
    op.create_table(
        "recovery_action_executions",
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("execution_id", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("commitment_id", sa.String(128), nullable=False),
        sa.Column("plan_id", sa.String(128), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("approval_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.String(128), nullable=True),
        sa.Column("receipt_ref", sa.String(128), nullable=True),
        sa.Column("audit_id", sa.String(128), nullable=True),
        sa.Column("last_error", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "execution_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "plan_id", "plan_version"],
            ["recovery_plan_versions.tenant_id", "recovery_plan_versions.plan_id",
             "recovery_plan_versions.plan_version"],
            name="fk_recovery_action_plan", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_recovery_action_key"),
        sa.CheckConstraint("attempts >= 0", name="ck_recovery_action_attempts"),
    )


def downgrade() -> None:
    op.drop_table("recovery_action_executions")
    op.drop_table("internal_recovery_tasks")
