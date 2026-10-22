"""P4 durable local outbound messaging; frozen schema, no runtime model imports."""
from alembic import op
import sqlalchemy as sa

revision = "0009_p4_outbound_messaging"
down_revision = "0008_p4_communication"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("communication_draft_reviews") as batch:
        batch.create_unique_constraint("uq_review_exact_identity", ["tenant_id", "communication_id", "draft_id", "review_id"])
    op.create_table(
        'communication_outbound_messages',
        sa.Column('tenant_id', sa.String(128), nullable=False),
        sa.Column('outbound_id', sa.String(128), nullable=False),
        sa.Column('communication_id', sa.String(128), nullable=False),
        sa.Column('draft_id', sa.String(128), nullable=False),
        sa.Column('approved_review_id', sa.String(128), nullable=False),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('validation_hash', sa.String(64), nullable=False),
        sa.Column('channel', sa.String(32), nullable=False),
        sa.Column('recipient_identity_id', sa.String(128), nullable=False),
        sa.Column('request_key', sa.String(128), nullable=False),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('provider_reference', sa.String(128), nullable=True),
        sa.Column('provider_confirmed', sa.Boolean(), nullable=False),
        sa.Column('authorization_evidence', sa.JSON(), nullable=False),
        sa.Column('correlation_id', sa.String(128), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('failed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error_code', sa.String(128), nullable=True),
        sa.PrimaryKeyConstraint('tenant_id', 'outbound_id'),
        sa.CheckConstraint("(status = 'SENT' AND provider_confirmed AND provider_reference IS NOT NULL AND sent_at IS NOT NULL) OR (status <> 'SENT' AND NOT provider_confirmed AND sent_at IS NULL)", name='ck_outbound_confirmed_sent'),
        sa.CheckConstraint("status IN ('QUEUED','SENT','FAILED','DELIVERY_UNKNOWN')", name='ck_outbound_status'),
        sa.ForeignKeyConstraint(['tenant_id', 'communication_id', 'draft_id', 'approved_review_id'], ['communication_draft_reviews.tenant_id', 'communication_draft_reviews.communication_id', 'communication_draft_reviews.draft_id', 'communication_draft_reviews.review_id'], name='fk_outbound_exact_review'),
        sa.UniqueConstraint('tenant_id', 'draft_id', name='uq_outbound_one_draft'),
        sa.UniqueConstraint('channel', 'provider_reference', name='uq_outbound_provider_reference'),
        sa.UniqueConstraint('tenant_id', 'request_key', name='uq_outbound_request_key'),
    )
    op.create_index('ix_outbound_tenant_request', 'communication_outbound_messages', ['tenant_id', 'communication_id'])
    op.create_index('ix_outbound_tenant_status', 'communication_outbound_messages', ['tenant_id', 'status'])
    op.create_table(
        'communication_send_attempts',
        sa.Column('tenant_id', sa.String(128), nullable=False),
        sa.Column('outbound_id', sa.String(128), nullable=False),
        sa.Column('attempt_number', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('provider_reference', sa.String(128), nullable=True),
        sa.Column('error_code', sa.String(128), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('tenant_id', 'outbound_id', 'attempt_number'),
        sa.CheckConstraint('attempt_number = 1', name='ck_attempt_one_submission'),
        sa.CheckConstraint("status IN ('QUEUED','SENT','FAILED','DELIVERY_UNKNOWN')", name='ck_attempt_status'),
        sa.ForeignKeyConstraint(['tenant_id', 'outbound_id'], ['communication_outbound_messages.tenant_id', 'communication_outbound_messages.outbound_id'], name='fk_attempt_outbound'),
    )


def downgrade():
    op.drop_table('communication_send_attempts')
    op.drop_index('ix_outbound_tenant_request', table_name='communication_outbound_messages')
    op.drop_index('ix_outbound_tenant_status', table_name='communication_outbound_messages')
    op.drop_table('communication_outbound_messages')
    with op.batch_alter_table("communication_draft_reviews") as batch:
        batch.drop_constraint("uq_review_exact_identity", type_="unique")
