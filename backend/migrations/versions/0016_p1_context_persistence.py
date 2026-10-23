"""Frozen P1 PostgreSQL DDL; no runtime ORM imports or create_all.

Existing manually-created schemas require explicit adoption review; this revision
must not silently stamp incompatible tables. Only use a disposable DB for tests.
"""
from alembic import op

revision = "0016_p1_context_persistence"
down_revision = "0015_p4_followup"
branch_labels = None
depends_on = None

DDL = (
    """CREATE TABLE p1_dev.attachments (
	attachment_id VARCHAR(100) NOT NULL, 
	tenant_id VARCHAR(200) NOT NULL, 
	evidence_ref VARCHAR(100) NOT NULL, 
	filename VARCHAR(255) NOT NULL, 
	media_type VARCHAR(100) NOT NULL, 
	size_bytes INTEGER NOT NULL, 
	content_sha256 VARCHAR(64) NOT NULL, 
	content BYTEA NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (attachment_id, tenant_id)
)""",
    """CREATE UNIQUE INDEX ix_p1_attachments_evidence_ref ON p1_dev.attachments (tenant_id, evidence_ref)""",
    """CREATE TABLE p1_dev.context_reviews (
	review_id VARCHAR(36) NOT NULL, 
	tenant_id VARCHAR(200) NOT NULL, 
	context_id VARCHAR(36) NOT NULL, 
	context_version_before INTEGER NOT NULL, 
	context_version_after INTEGER NOT NULL, 
	action VARCHAR(50) NOT NULL, 
	actor_id VARCHAR(200) NOT NULL, 
	actor_role VARCHAR(50) NOT NULL, 
	field_changes JSONB NOT NULL, 
	note VARCHAR(1000), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (review_id)
)""",
    """CREATE INDEX ix_p1_review_context ON p1_dev.context_reviews (tenant_id, context_id)""",
    """CREATE TABLE p1_dev.document_extractions (
	tenant_id VARCHAR(200) NOT NULL, 
	evidence_ref VARCHAR(100) NOT NULL, 
	attachment_id VARCHAR(100) NOT NULL, 
	status VARCHAR(50) NOT NULL, 
	document_type VARCHAR(50) NOT NULL, 
	page_count INTEGER NOT NULL, 
	text_content TEXT NOT NULL, 
	payload JSONB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (tenant_id, evidence_ref)
)""",
    """CREATE INDEX ix_p1_doc_extractions_att ON p1_dev.document_extractions (tenant_id, attachment_id)""",
    """CREATE TABLE p1_dev.extraction_attempts (
	attempt_id VARCHAR(36) NOT NULL, 
	tenant_id VARCHAR(200) NOT NULL, 
	message_id VARCHAR(36) NOT NULL, 
	extractor_version VARCHAR(50) NOT NULL, 
	input_content_sha256 VARCHAR(64) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	fields JSONB NOT NULL, 
	diagnostic VARCHAR(1000), 
	started_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (attempt_id), 
	CONSTRAINT ck_p1_attempt_status CHECK (status IN ('PROCESSING', 'PROCESSED', 'PROCESSING_FAILED'))
)""",
    """CREATE INDEX ix_p1_attempts_fingerprint ON p1_dev.extraction_attempts (tenant_id, message_id, extractor_version, input_content_sha256)""",
    """CREATE INDEX ix_p1_attempts_message ON p1_dev.extraction_attempts (tenant_id, message_id, started_at)""",
    """CREATE TABLE p1_dev.inbound_messages (
	message_id VARCHAR(36) NOT NULL, 
	tenant_id VARCHAR(200) NOT NULL, 
	channel VARCHAR(20) NOT NULL, 
	provider_message_id VARCHAR(200) NOT NULL, 
	synthetic_provider VARCHAR(30) NOT NULL, 
	raw JSONB NOT NULL, 
	immutable_fingerprint VARCHAR(64) NOT NULL, 
	content_sha256 VARCHAR(64) NOT NULL, 
	processing_status VARCHAR(30) NOT NULL, 
	ingested_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (message_id), 
	CONSTRAINT uq_p1_delivery UNIQUE (tenant_id, channel, provider_message_id), 
	CONSTRAINT ck_p1_processing CHECK (processing_status IN ('RECEIVED', 'PROCESSING', 'PROCESSED', 'PROCESSING_FAILED')), 
	CONSTRAINT ck_p1_synthetic_provider CHECK ((channel = 'WHATSAPP' AND synthetic_provider = 'SYNTHETIC_WHATSAPP') OR (channel = 'EMAIL' AND synthetic_provider = 'SYNTHETIC_EMAIL') OR (channel = 'TELEGRAM' AND synthetic_provider = 'SYNTHETIC_TELEGRAM') OR (channel = 'UNKNOWN' AND synthetic_provider = 'SYNTHETIC_UNKNOWN'))
)""",
    """CREATE INDEX ix_p1_inbox ON p1_dev.inbound_messages (tenant_id, ingested_at, message_id)""",
    """CREATE TABLE p1_dev.message_associations (
	association_id VARCHAR(36) NOT NULL, 
	tenant_id VARCHAR(200) NOT NULL, 
	message_id VARCHAR(36) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	verified_customer JSONB, 
	verified_order JSONB, 
	candidates JSONB NOT NULL, 
	conflicts JSONB NOT NULL, 
	last_decision JSONB, 
	version INTEGER NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (association_id), 
	CONSTRAINT uq_p1_message_association UNIQUE (tenant_id, message_id)
)""",
    """CREATE INDEX ix_p1_assoc_message ON p1_dev.message_associations (tenant_id, message_id)""",
    """CREATE TABLE p1_dev.order_context_versions (
	version_id VARCHAR(36) NOT NULL, 
	context_id VARCHAR(36) NOT NULL, 
	tenant_id VARCHAR(200) NOT NULL, 
	context_version INTEGER NOT NULL, 
	snapshot JSONB NOT NULL, 
	change_type VARCHAR(50) NOT NULL, 
	actor_id VARCHAR(200), 
	actor_role VARCHAR(50), 
	reason VARCHAR(500), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (version_id)
)""",
    """CREATE INDEX ix_p1_ctx_version ON p1_dev.order_context_versions (tenant_id, context_id, context_version)""",
    """CREATE TABLE p1_dev.order_contexts (
	context_id VARCHAR(36) NOT NULL, 
	tenant_id VARCHAR(200) NOT NULL, 
	order_id VARCHAR(200), 
	customer_id VARCHAR(200), 
	customer_identity_status VARCHAR(30) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	context_version INTEGER NOT NULL, 
	requested_items JSONB NOT NULL, 
	requested_delivery_at TIMESTAMP WITH TIME ZONE, 
	delivery_qualifier VARCHAR(30), 
	special_instructions VARCHAR(1000), 
	source_message_ids JSONB NOT NULL, 
	field_evidence JSONB NOT NULL, 
	missing_fields JSONB NOT NULL, 
	conflicts JSONB NOT NULL, 
	last_reviewed_by VARCHAR(200), 
	last_reviewed_role VARCHAR(50), 
	last_reviewed_at TIMESTAMP WITH TIME ZONE, 
	core_commitment_id VARCHAR(100), 
	published_to_core_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (context_id), 
	CONSTRAINT uq_p1_order_context UNIQUE (tenant_id, context_id)
)""",
    """CREATE INDEX ix_p1_ctx_order ON p1_dev.order_contexts (tenant_id, order_id)""",
)


def upgrade():
    import logging
    _log = logging.getLogger(__name__)
    if op.get_bind().dialect.name != 'postgresql':
        _log.warning(
            'Skipping 0012_p1_context_persistence on non-PostgreSQL dialect (%s). '
            'P1 persistence tables require PostgreSQL and will not be created.',
            op.get_bind().dialect.name,
        )
        return
    op.execute('CREATE SCHEMA IF NOT EXISTS p1_dev')
    for statement in DDL:
        op.execute(statement)
    op.execute("""ALTER TABLE p1_dev.inbound_messages ADD CONSTRAINT ck_p1_provider_channel
        CHECK ((channel = 'WHATSAPP' AND synthetic_provider = 'SYNTHETIC_WHATSAPP') OR
               (channel = 'EMAIL' AND synthetic_provider = 'SYNTHETIC_EMAIL') OR
               (channel = 'TELEGRAM' AND synthetic_provider = 'SYNTHETIC_TELEGRAM') OR
               (channel = 'UNKNOWN' AND synthetic_provider = 'SYNTHETIC_UNKNOWN'))""")


def downgrade():
    if op.get_bind().dialect.name != 'postgresql':
        return
    # Destructive by definition: only execute as a deliberate rollback. Never
    # drop schema CASCADE (could remove unrelated objects); leave shared Core.
    op.drop_table('order_contexts', schema="p1_dev")
    op.drop_table('order_context_versions', schema="p1_dev")
    op.drop_table('message_associations', schema="p1_dev")
    op.drop_table('inbound_messages', schema="p1_dev")
    op.drop_table('extraction_attempts', schema="p1_dev")
    op.drop_table('document_extractions', schema="p1_dev")
    op.drop_table('context_reviews', schema="p1_dev")
    op.drop_table('attachments', schema="p1_dev")
