"""P4 durable confirmation evidence. Frozen DDL, parent is actual standalone Head 0010."""
from alembic import op
import sqlalchemy as sa

revision = "0011_p4_confirmations"
down_revision = "0010_p4_recipient_preferences"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("communication_outbound_messages") as batch:
        batch.create_unique_constraint("uq_outbound_confirmation_binding", ["tenant_id", "outbound_id", "communication_id", "draft_id", "approved_review_id"])
    op.create_table('communication_confirmation_sessions',
        sa.Column('tenant_id', sa.String(128), primary_key=True),
        sa.Column('confirmation_id', sa.String(128), primary_key=True),
        sa.Column('outbound_id', sa.String(128), nullable=False),
        sa.Column('communication_id', sa.String(128), nullable=False),
        sa.Column('draft_id', sa.String(128), nullable=False),
        sa.Column('approved_review_id', sa.String(128), nullable=False),
        sa.Column('customer_id', sa.String(128), nullable=False),
        sa.Column('recipient_identity_id', sa.String(200), nullable=False),
        sa.Column('channel', sa.String(32), nullable=False),
        sa.Column('token_digest', sa.String(64), nullable=False),
        sa.Column('binding', sa.JSON(), nullable=False),
        sa.Column('state', sa.String(32), nullable=False),
        sa.Column('created_by', sa.String(128), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("(state IN ('ACCEPTED','REJECTED','COUNTEROFFER_RECEIVED') AND consumed_at IS NOT NULL) OR (state IN ('AWAITING_RESPONSE','CLARIFICATION_REQUIRED','UNRESOLVED') AND consumed_at IS NULL)", name='ck_confirmation_consumption'),
        sa.CheckConstraint('expires_at > created_at', name='ck_confirmation_expiry'),
        sa.CheckConstraint("channel IN ('MOCK_EMAIL','MOCK_WHATSAPP','MOCK_TELEGRAM')", name='ck_confirmation_mock_channel'),
        sa.ForeignKeyConstraint(['tenant_id', 'outbound_id', 'communication_id', 'draft_id', 'approved_review_id'], ['communication_outbound_messages.tenant_id', 'communication_outbound_messages.outbound_id', 'communication_outbound_messages.communication_id', 'communication_outbound_messages.draft_id', 'communication_outbound_messages.approved_review_id'], name='fk_confirmation_exact_outbound'),
        sa.UniqueConstraint('tenant_id', 'outbound_id', name='uq_confirmation_one_outbound'),
        sa.UniqueConstraint('token_digest', name='uq_confirmation_token_digest'),
    )
    op.create_index('ix_confirmation_tenant_request', 'communication_confirmation_sessions', ['tenant_id', 'communication_id'])
    op.create_table('communication_confirmation_attempts',
        sa.Column('tenant_id', sa.String(128), primary_key=True),
        sa.Column('attempt_id', sa.String(128), primary_key=True),
        sa.Column('confirmation_id', sa.String(128), nullable=False),
        sa.Column('inbound_message_id', sa.String(128), nullable=False),
        sa.Column('provider_message_id', sa.String(200), nullable=False),
        sa.Column('channel', sa.String(32), nullable=False),
        sa.Column('proof_digest', sa.String(64), nullable=False),
        sa.Column('source_digest', sa.String(64), nullable=False),
        sa.Column('evidence_refs', sa.JSON(), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['tenant_id', 'confirmation_id'], ['communication_confirmation_sessions.tenant_id', 'communication_confirmation_sessions.confirmation_id'], name='fk_confirmation_attempt_session'),
        sa.UniqueConstraint('tenant_id', 'confirmation_id', 'attempt_id', name='uq_confirmation_attempt_binding'),
        sa.UniqueConstraint('tenant_id', 'inbound_message_id', name='uq_confirmation_inbound_message'),
        sa.UniqueConstraint('tenant_id', 'channel', 'provider_message_id', name='uq_confirmation_provider_message'),
    )
    op.create_index('ix_confirmation_attempt_history', 'communication_confirmation_attempts', ['tenant_id', 'confirmation_id', 'received_at'])
    op.create_table('communication_confirmation_decisions',
        sa.Column('tenant_id', sa.String(128), primary_key=True),
        sa.Column('decision_id', sa.String(128), primary_key=True),
        sa.Column('confirmation_id', sa.String(128), nullable=False),
        sa.Column('attempt_id', sa.String(128), nullable=False),
        sa.Column('terminal_confirmation_id', sa.String(128), nullable=True),
        sa.Column('intent', sa.String(32), nullable=False),
        sa.Column('reason', sa.String(128), nullable=False),
        sa.Column('proposed_changes', sa.JSON(), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("(intent IN ('ACCEPT','REJECT','COUNTEROFFER') AND terminal_confirmation_id IS NOT NULL AND terminal_confirmation_id = confirmation_id) OR (intent IN ('CLARIFICATION','UNKNOWN') AND terminal_confirmation_id IS NULL)", name='ck_confirmation_terminal_binding'),
        sa.ForeignKeyConstraint(['tenant_id', 'confirmation_id', 'attempt_id'], ['communication_confirmation_attempts.tenant_id', 'communication_confirmation_attempts.confirmation_id', 'communication_confirmation_attempts.attempt_id'], name='fk_confirmation_decision_attempt'),
        sa.UniqueConstraint('tenant_id', 'attempt_id', name='uq_confirmation_attempt_decision'),
        sa.UniqueConstraint('tenant_id', 'terminal_confirmation_id', name='uq_confirmation_terminal_decision'),
    )


def downgrade():
    op.drop_table('communication_confirmation_decisions')
    op.drop_index('ix_confirmation_attempt_history', table_name='communication_confirmation_attempts')
    op.drop_table('communication_confirmation_attempts')
    op.drop_index('ix_confirmation_tenant_request', table_name='communication_confirmation_sessions')
    op.drop_table('communication_confirmation_sessions')
    with op.batch_alter_table("communication_outbound_messages") as batch:
        batch.drop_constraint("uq_outbound_confirmation_binding", type_="unique")
