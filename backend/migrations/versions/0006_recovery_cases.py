"""Add recovery_cases and recovery_case_triggers tables for P3 Recovery persistence.

Per PERSON_5 Task T5.3, agreed reply_P3.md, and P3 SqlAlchemyRecoveryRepository schema:
- recovery_cases: durable scalar/index columns + JSON case_payload
- recovery_case_triggers: append-only provenance rows for accepted at-risk trigger events
- tenant_id on every table with composite PKs and foreign keys
- working upgrade and downgrade
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006_recovery_cases"
down_revision: Union[str, None] = "0005_resource_reservations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ACTIVE_CASE_STATUSES = (
    "OPEN",
    "AWAITING_EVALUATION_INPUTS",
    "OPTIONS_READY",
    "NO_SAFE_PLAN",
    "NEEDS_REPLAN",
)

ALL_CASE_STATUSES = ACTIVE_CASE_STATUSES + ("COMPLETED",)

_ACTIVE_CASE_SQL = "status IN (" + ", ".join(f"'{s}'" for s in ACTIVE_CASE_STATUSES) + ")"
_CASE_STATUS_SQL = "status IN (" + ", ".join(f"'{s}'" for s in ALL_CASE_STATUSES) + ")"


def upgrade() -> None:
    # 1. recovery_cases table
    op.create_table(
        "recovery_cases",
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("case_id", sa.String(length=128), nullable=False),
        sa.Column("commitment_id", sa.String(length=128), nullable=False),
        sa.Column("risk_episode_id", sa.String(length=128), nullable=False),
        sa.Column("opening_event_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=48), nullable=False),
        sa.Column("case_version", sa.Integer(), nullable=False),
        sa.Column("commitment_version", sa.Integer(), nullable=False),
        sa.Column("payload_schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("case_payload", sa.JSON(), nullable=False),
        sa.Column("resolution_event_id", sa.String(length=128), nullable=True),
        sa.Column("resolution_commitment_version", sa.Integer(), nullable=True),
        sa.Column("resolution_refs", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("tenant_id", "case_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "commitment_id"],
            ["commitments.tenant_id", "commitments.commitment_id"],
            name="fk_recovery_cases_commitment_tenant",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("tenant_id", "risk_episode_id", name="uq_recovery_cases_tenant_episode"),
        sa.UniqueConstraint(
            "tenant_id", "case_id", "commitment_id", name="uq_recovery_case_tenant_case_commitment"
        ),
        sa.CheckConstraint("case_version >= 1", name="ck_recovery_cases_case_version_positive"),
        sa.CheckConstraint("commitment_version >= 1", name="ck_recovery_cases_commitment_version_positive"),
        sa.CheckConstraint("payload_schema_version >= 1", name="ck_recovery_cases_payload_version_positive"),
        sa.CheckConstraint(_CASE_STATUS_SQL, name="ck_recovery_cases_status_valid"),
    )
    op.create_index(
        "ix_recovery_cases_tenant_status_updated",
        "recovery_cases",
        ["tenant_id", "status", "updated_at"],
    )
    op.create_index(
        "ix_recovery_cases_tenant_commitment_created",
        "recovery_cases",
        ["tenant_id", "commitment_id", "created_at"],
    )
    op.create_index(
        "uq_recovery_cases_one_active_per_commitment",
        "recovery_cases",
        ["tenant_id", "commitment_id"],
        unique=True,
        postgresql_where=sa.text(_ACTIVE_CASE_SQL),
        sqlite_where=sa.text(_ACTIVE_CASE_SQL),
    )

    # 2. recovery_case_triggers table
    op.create_table(
        "recovery_case_triggers",
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("case_id", sa.String(length=128), nullable=False),
        sa.Column("commitment_id", sa.String(length=128), nullable=False),
        sa.Column("commitment_version", sa.Integer(), nullable=False),
        sa.Column("assessment_id", sa.String(length=128), nullable=False),
        sa.Column("assessment_commitment_version", sa.Integer(), nullable=True),
        sa.Column("assessment_provenance_status", sa.String(length=64), nullable=False),
        sa.Column("snapshot_id", sa.String(length=128), nullable=True),
        sa.Column("snapshot_version", sa.Integer(), nullable=False),
        sa.Column("constraints", sa.JSON(), nullable=False),
        sa.Column("affected_commitment_ids", sa.JSON(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("correlation_id", sa.String(length=128), nullable=False),
        sa.Column("causation_id", sa.String(length=128), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_digest", sa.String(length=64), nullable=False),
        sa.Column("source_event_digest", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("tenant_id", "event_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "commitment_id"],
            ["commitments.tenant_id", "commitments.commitment_id"],
            name="fk_recovery_case_triggers_commitment_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "case_id", "commitment_id"],
            [
                "recovery_cases.tenant_id",
                "recovery_cases.case_id",
                "recovery_cases.commitment_id",
            ],
            name="fk_recovery_case_triggers_case_tenant_commitment",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("commitment_version >= 1", name="ck_recovery_triggers_commitment_version_positive"),
        sa.CheckConstraint("snapshot_version >= 1", name="ck_recovery_triggers_snapshot_version_positive"),
    )
    op.create_index(
        "ix_recovery_triggers_tenant_case_time",
        "recovery_case_triggers",
        ["tenant_id", "case_id", "occurred_at"],
    )
    op.create_index(
        "ix_recovery_triggers_tenant_commitment_assessment",
        "recovery_case_triggers",
        ["tenant_id", "commitment_id", "assessment_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_recovery_triggers_tenant_commitment_assessment", table_name="recovery_case_triggers")
    op.drop_index("ix_recovery_triggers_tenant_case_time", table_name="recovery_case_triggers")
    op.drop_table("recovery_case_triggers")
    op.drop_index("uq_recovery_cases_one_active_per_commitment", table_name="recovery_cases")
    op.drop_index("ix_recovery_cases_tenant_commitment_created", table_name="recovery_cases")
    op.drop_index("ix_recovery_cases_tenant_status_updated", table_name="recovery_cases")
    op.drop_table("recovery_cases")
