"""Persist exact P3 plan versions after P2 source migration.

Revision ID: 0010_p3_recovery_plans
Revises: 0009_p2_operational_sources
"""

from alembic import op
import sqlalchemy as sa

revision = "0010_p3_recovery_plans"
down_revision = "0009_p2_operational_sources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recovery_plan_versions",
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("plan_id", sa.String(128), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("case_id", sa.String(128), nullable=False),
        sa.Column("commitment_id", sa.String(128), nullable=False),
        sa.Column("assessment_id", sa.String(128), nullable=False),
        sa.Column("snapshot_id", sa.String(128), nullable=False),
        sa.Column("snapshot_version", sa.Integer(), nullable=False),
        sa.Column("core_commitment_version", sa.Integer(), nullable=False),
        sa.Column("evaluated_commitment_version", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "plan_id", "plan_version"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "case_id", "commitment_id"],
            ["recovery_cases.tenant_id", "recovery_cases.case_id", "recovery_cases.commitment_id"],
            name="fk_recovery_plan_case", ondelete="RESTRICT",
        ),
        sa.CheckConstraint("plan_version >= 1", name="ck_recovery_plan_version_positive"),
        sa.CheckConstraint("snapshot_version >= 1", name="ck_recovery_plan_snapshot_positive"),
        sa.CheckConstraint("core_commitment_version > evaluated_commitment_version",
                           name="ck_recovery_plan_core_after_evaluation"),
    )
    op.create_index("ix_recovery_plan_case", "recovery_plan_versions", ["tenant_id", "case_id"])


def downgrade() -> None:
    op.drop_index("ix_recovery_plan_case", table_name="recovery_plan_versions")
    op.drop_table("recovery_plan_versions")
