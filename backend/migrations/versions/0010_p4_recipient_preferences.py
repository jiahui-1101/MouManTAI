"""P4 synthetic recipient consent and immutable change journal (frozen DDL)."""
from alembic import op
import sqlalchemy as sa

revision = "0010_p4_recipient_preferences"
down_revision = "0009_p4_outbound_messaging"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("communication_recipient_preferences",
        sa.Column("tenant_id", sa.String(128), primary_key=True),
        sa.Column("customer_id", sa.String(128), primary_key=True),
        sa.Column("channel", sa.String(32), primary_key=True),
        sa.Column("consent_purpose", sa.String(64), primary_key=True),
        sa.Column("recipient_identity_id", sa.String(200), nullable=False),
        sa.Column("consent_status", sa.String(16), nullable=False),
        sa.Column("consent_evidence_ref", sa.String(256), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("consent_recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consent_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("allowed_contact_hours", sa.JSON(), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("policy_version", sa.String(32), nullable=False),
        sa.Column("last_audit_id", sa.String(128), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by_actor_id", sa.String(128), nullable=False),
        sa.CheckConstraint("consent_status IN ('OPTED_IN','OPTED_OUT')", name="ck_preference_status"),
        sa.CheckConstraint("version >= 1", name="ck_preference_version"),
        sa.CheckConstraint("channel IN ('MOCK_EMAIL','MOCK_WHATSAPP','MOCK_TELEGRAM')", name="ck_preference_channel"),
        sa.CheckConstraint("consent_purpose = 'TRANSACTIONAL_REVISED_TERMS'", name="ck_preference_purpose"),
        sa.CheckConstraint("source = 'SYNTHETIC_FIXTURE'", name="ck_preference_source"),
        sa.CheckConstraint("consent_expires_at > consent_recorded_at", name="ck_preference_expiry"),
        sa.CheckConstraint("(consent_status = 'OPTED_OUT' AND revoked_at IS NOT NULL) OR (consent_status = 'OPTED_IN' AND revoked_at IS NULL)", name="ck_preference_revocation"),
    )
    op.create_table("communication_recipient_preference_changes",
        sa.Column("tenant_id", sa.String(128), primary_key=True),
        sa.Column("audit_id", sa.String(128), primary_key=True),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("command_hash", sa.String(64), nullable=False),
        sa.Column("customer_id", sa.String(128), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("consent_purpose", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("previous_state", sa.JSON(), nullable=True),
        sa.Column("new_state", sa.JSON(), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("actor_role", sa.String(32), nullable=False),
        sa.Column("correlation_id", sa.String(128), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "request_key", name="uq_preference_change_key"),
        sa.UniqueConstraint("tenant_id", "customer_id", "channel", "consent_purpose", "version", name="uq_preference_change_version"),
        sa.ForeignKeyConstraint(["tenant_id", "customer_id", "channel", "consent_purpose"],
            ["communication_recipient_preferences.tenant_id", "communication_recipient_preferences.customer_id", "communication_recipient_preferences.channel", "communication_recipient_preferences.consent_purpose"], name="fk_preference_change_scope"),
    )


def downgrade():
    op.drop_table("communication_recipient_preference_changes")
    op.drop_table("communication_recipient_preferences")
