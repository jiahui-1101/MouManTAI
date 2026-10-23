"""P1 real vs synthetic provenance migration.

Allows inbound_messages.synthetic_provider to be NULL for real-channel messages,
adds provider column, and replaces ck_p1_synthetic_provider with ck_p1_provenance.
Preserves existing synthetic data.
"""
from alembic import op
import sqlalchemy as sa

revision = "0017_p1_real_channel_provenance"
down_revision = "0016_p1_context_persistence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    # 1. Add provider column with default 'SYNTHETIC'
    op.add_column("inbound_messages", sa.Column("provider", sa.String(50), nullable=True), schema="p1_dev")
    op.execute("UPDATE p1_dev.inbound_messages SET provider = 'SYNTHETIC' WHERE provider IS NULL")
    op.alter_column("inbound_messages", "provider", nullable=False, schema="p1_dev")

    # 2. Make synthetic_provider nullable so real messages have synthetic_provider = NULL
    op.alter_column("inbound_messages", "synthetic_provider", nullable=True, schema="p1_dev")

    # 3. Drop old ck_p1_synthetic_provider check constraint
    op.drop_constraint("ck_p1_synthetic_provider", "inbound_messages", schema="p1_dev", type_="check")

    # 4. Add new ck_p1_provenance check constraint
    op.create_check_constraint(
        "ck_p1_provenance",
        "inbound_messages",
        "(synthetic_provider IS NOT NULL AND ("
        "(channel = 'WHATSAPP' AND synthetic_provider = 'SYNTHETIC_WHATSAPP') OR "
        "(channel = 'EMAIL' AND synthetic_provider = 'SYNTHETIC_EMAIL') OR "
        "(channel = 'TELEGRAM' AND synthetic_provider = 'SYNTHETIC_TELEGRAM') OR "
        "(channel = 'UNKNOWN' AND synthetic_provider = 'SYNTHETIC_UNKNOWN')"
        ") AND provider = 'SYNTHETIC') OR "
        "(synthetic_provider IS NULL AND provider IN ('TELEGRAM_BOT_API', 'GMAIL_API', 'WHATSAPP_CLOUD_API', 'REAL') AND channel IN ('WHATSAPP', 'EMAIL', 'TELEGRAM', 'UNKNOWN'))",
        schema="p1_dev",
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.drop_constraint("ck_p1_provenance", "inbound_messages", schema="p1_dev", type_="check")
    op.execute("UPDATE p1_dev.inbound_messages SET synthetic_provider = 'SYNTHETIC_' || channel WHERE synthetic_provider IS NULL")
    op.alter_column("inbound_messages", "synthetic_provider", nullable=False, schema="p1_dev")
    op.create_check_constraint(
        "ck_p1_synthetic_provider",
        "inbound_messages",
        "(channel = 'WHATSAPP' AND synthetic_provider = 'SYNTHETIC_WHATSAPP') OR "
        "(channel = 'EMAIL' AND synthetic_provider = 'SYNTHETIC_EMAIL') OR "
        "(channel = 'TELEGRAM' AND synthetic_provider = 'SYNTHETIC_TELEGRAM') OR "
        "(channel = 'UNKNOWN' AND synthetic_provider = 'SYNTHETIC_UNKNOWN')",
        schema="p1_dev",
    )
    op.drop_column("inbound_messages", "provider", schema="p1_dev")
