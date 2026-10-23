"""Add durable P4 follow-up and reminder evidence (P5 parent approval 2026-10-23)."""
from alembic import op
import sqlalchemy as sa

revision = "0015_p4_followup"
down_revision = "0014_merge_p3_p4_confirmations"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "communication_followup_tasks",
        sa.Column("tenant_id", sa.String(128), primary_key=True),
        sa.Column("task_id", sa.String(128), primary_key=True),
        sa.Column("communication_id", sa.String(128), nullable=False),
        sa.Column("confirmation_id", sa.String(128), nullable=False),
        sa.Column("commitment_id", sa.String(128), nullable=False),
        sa.Column("proposal_id", sa.String(128), nullable=False),
        sa.Column("proposal_version", sa.Integer(), nullable=False),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("command_hash", sa.String(64), nullable=False),
        sa.Column("policy", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reason_code", sa.String(128)),
        sa.Column("reminders_sent", sa.Integer(), nullable=False),
        sa.Column("next_due_at", sa.DateTime(timezone=True)),
        sa.Column("escalation_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_reminder_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id", "confirmation_id"],
            ["communication_confirmation_sessions.tenant_id", "communication_confirmation_sessions.confirmation_id"], name="fk_followup_confirmation"),
        sa.ForeignKeyConstraint(["tenant_id", "communication_id"],
            ["communication_requests.tenant_id", "communication_requests.communication_id"], name="fk_followup_request"),
        sa.UniqueConstraint("tenant_id", "communication_id", name="uq_followup_one_request"),
        sa.UniqueConstraint("tenant_id", "confirmation_id", name="uq_followup_one_confirmation"),
        sa.UniqueConstraint("tenant_id", "request_key", name="uq_followup_request_key"),
        sa.CheckConstraint("proposal_version >= 1 AND reminders_sent >= 0 AND reminders_sent <= 3", name="ck_followup_counts"),
        sa.CheckConstraint("status IN ('WAITING','BLOCKED','DISPATCHING','CANCELLED','ESCALATED')", name="ck_followup_status"),
    )
    op.create_index("ix_followup_due", "communication_followup_tasks", ["tenant_id", "status", "next_due_at"])
    op.create_table(
        "communication_reminder_attempts",
        sa.Column("tenant_id", sa.String(128), primary_key=True),
        sa.Column("reminder_id", sa.String(128), primary_key=True),
        sa.Column("task_id", sa.String(128), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("provider_reference", sa.String(128)),
        sa.Column("error_code", sa.String(128)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["tenant_id", "task_id"],
            ["communication_followup_tasks.tenant_id", "communication_followup_tasks.task_id"], name="fk_reminder_task"),
        sa.UniqueConstraint("tenant_id", "task_id", "sequence", name="uq_reminder_sequence"),
        sa.CheckConstraint("sequence >= 1 AND sequence <= 3", name="ck_reminder_sequence"),
        sa.CheckConstraint("status IN ('SENT','FAILED','DELIVERY_UNKNOWN')", name="ck_reminder_status"),
        sa.CheckConstraint("channel IN ('MOCK_EMAIL','MOCK_WHATSAPP','MOCK_TELEGRAM')", name="ck_reminder_channel"),
    )


def downgrade():
    op.drop_table("communication_reminder_attempts")
    op.drop_index("ix_followup_due", table_name="communication_followup_tasks")
    op.drop_table("communication_followup_tasks")
