"""Persist P2 synthetic operational snapshots and supplier delay evidence.

Revision ID: 0009_p2_operational_sources
Revises: 0008_p4_communication
"""

from alembic import op
import sqlalchemy as sa

revision = "0009_p2_operational_sources"
down_revision = "0008_p4_communication"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "p2_operational_snapshots",
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("snapshot_version", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.String(128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "snapshot_version"),
        sa.UniqueConstraint("tenant_id", "snapshot_id", name="uq_p2_snapshot_identity"),
        sa.CheckConstraint("snapshot_version >= 1", name="ck_p2_snapshot_version_positive"),
    )
    op.create_index(
        "uq_p2_one_current_snapshot", "p2_operational_snapshots", ["tenant_id"], unique=True,
        postgresql_where=sa.text("is_current"), sqlite_where=sa.text("is_current = 1"),
    )
    op.create_table(
        "p2_supplier_delay_events",
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("event_id", sa.String(128), nullable=False),
        sa.Column("before_snapshot_version", sa.Integer(), nullable=False),
        sa.Column("after_snapshot_version", sa.Integer(), nullable=False),
        sa.Column("evidence_ref", sa.String(128), nullable=False),
        sa.Column("impact_id", sa.String(128), nullable=False),
        sa.Column("event_digest", sa.String(64), nullable=False),
        sa.Column("impact_payload", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "event_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "before_snapshot_version"],
            ["p2_operational_snapshots.tenant_id", "p2_operational_snapshots.snapshot_version"],
            name="fk_p2_delay_before_snapshot", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "after_snapshot_version"],
            ["p2_operational_snapshots.tenant_id", "p2_operational_snapshots.snapshot_version"],
            name="fk_p2_delay_after_snapshot", ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "after_snapshot_version > before_snapshot_version", name="ck_p2_delay_version_advance",
        ),
    )


def downgrade() -> None:
    op.drop_table("p2_supplier_delay_events")
    op.drop_index("uq_p2_one_current_snapshot", table_name="p2_operational_snapshots")
    op.drop_table("p2_operational_snapshots")
