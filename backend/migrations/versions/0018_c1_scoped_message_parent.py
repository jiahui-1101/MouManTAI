"""Add provider-account scoped P1 identity and exact-parent persistence.

Legacy messages keep NULL account/native identifiers and are explicitly marked
LEGACY_UNKNOWN. No historical account or parent is inferred during upgrade.
"""

from alembic import op
import sqlalchemy as sa

revision = "0018_c1_scoped_message_parent"
down_revision = "0017_p1_real_channel_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.add_column("inbound_messages", sa.Column("provider_account_id", sa.String(200), nullable=True), schema="p1_dev")
    op.add_column("inbound_messages", sa.Column("provider_native_message_id", sa.String(998), nullable=True), schema="p1_dev")
    op.add_column("inbound_messages", sa.Column("conversation_id", sa.String(998), nullable=True), schema="p1_dev")
    op.add_column("inbound_messages", sa.Column("rfc_message_id", sa.String(998), nullable=True), schema="p1_dev")
    op.add_column("inbound_messages", sa.Column("exact_parent_reference", sa.String(998), nullable=True), schema="p1_dev")
    op.add_column(
        "inbound_messages",
        sa.Column("parent_resolution", sa.String(24), nullable=False, server_default="LEGACY_UNKNOWN"),
        schema="p1_dev",
    )
    op.add_column("inbound_messages", sa.Column("resolved_parent_message_id", sa.String(36), nullable=True), schema="p1_dev")
    op.add_column(
        "inbound_messages",
        sa.Column("source_authenticity", sa.String(20), nullable=False, server_default="UNVERIFIED"),
        schema="p1_dev",
    )

    op.drop_constraint("uq_p1_delivery", "inbound_messages", schema="p1_dev", type_="unique")
    # Keep the historical delivery key for records with unknown account scope.
    op.create_index(
        "uq_p1_delivery_legacy",
        "inbound_messages",
        ["tenant_id", "channel", "provider_message_id"],
        unique=True,
        schema="p1_dev",
        postgresql_where=sa.text("provider_account_id IS NULL"),
    )
    op.create_index(
        "uq_p1_delivery_scoped",
        "inbound_messages",
        ["tenant_id", "provider", "provider_account_id", "provider_native_message_id"],
        unique=True,
        schema="p1_dev",
        postgresql_where=sa.text("provider_account_id IS NOT NULL AND channel <> 'TELEGRAM'"),
    )
    op.create_index(
        "uq_p1_delivery_telegram_scoped",
        "inbound_messages",
        ["tenant_id", "provider", "provider_account_id", "conversation_id", "provider_native_message_id"],
        unique=True,
        schema="p1_dev",
        postgresql_where=sa.text("provider_account_id IS NOT NULL AND channel = 'TELEGRAM'"),
    )
    op.create_check_constraint(
        "ck_p1_provider_identity_pair",
        "inbound_messages",
        "(provider_account_id IS NULL) = (provider_native_message_id IS NULL)",
        schema="p1_dev",
    )
    op.create_check_constraint(
        "ck_p1_parent_resolution",
        "inbound_messages",
        "parent_resolution IN ('NO_EXACT_PARENT', 'UNRESOLVED', 'AMBIGUOUS', 'REFERENCE_MATCH', 'LEGACY_UNKNOWN', 'INVALID')",
        schema="p1_dev",
    )
    op.create_check_constraint(
        "ck_p1_source_authenticity",
        "inbound_messages",
        "source_authenticity IN ('VERIFIED', 'UNVERIFIED', 'SYNTHETIC')",
        schema="p1_dev",
    )
    op.create_index(
        "ix_p1_parent_native_scope",
        "inbound_messages",
        ["tenant_id", "provider", "provider_account_id", "conversation_id", "provider_native_message_id"],
        schema="p1_dev",
        postgresql_where=sa.text("provider_account_id IS NOT NULL"),
    )
    op.create_index(
        "ix_p1_parent_rfc_scope",
        "inbound_messages",
        ["tenant_id", "provider", "provider_account_id", "rfc_message_id"],
        schema="p1_dev",
        postgresql_where=sa.text("provider_account_id IS NOT NULL AND rfc_message_id IS NOT NULL"),
    )
    op.create_index(
        "ix_p1_pending_parent_scope",
        "inbound_messages",
        ["tenant_id", "provider", "provider_account_id", "conversation_id", "exact_parent_reference"],
        schema="p1_dev",
        postgresql_where=sa.text("parent_resolution = 'UNRESOLVED' AND provider_account_id IS NOT NULL"),
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    # Recreating the former global provider-message key can fail if account-
    # scoped deliveries with the same legacy key now coexist. In that case the
    # operator must retain this revision until an approved export/reconciliation.
    op.drop_index("ix_p1_pending_parent_scope", table_name="inbound_messages", schema="p1_dev")
    op.drop_index("ix_p1_parent_rfc_scope", table_name="inbound_messages", schema="p1_dev")
    op.drop_index("ix_p1_parent_native_scope", table_name="inbound_messages", schema="p1_dev")
    op.drop_constraint("ck_p1_source_authenticity", "inbound_messages", schema="p1_dev", type_="check")
    op.drop_constraint("ck_p1_parent_resolution", "inbound_messages", schema="p1_dev", type_="check")
    op.drop_constraint("ck_p1_provider_identity_pair", "inbound_messages", schema="p1_dev", type_="check")
    op.drop_index("uq_p1_delivery_scoped", table_name="inbound_messages", schema="p1_dev")
    op.drop_index("uq_p1_delivery_telegram_scoped", table_name="inbound_messages", schema="p1_dev")
    op.drop_index("uq_p1_delivery_legacy", table_name="inbound_messages", schema="p1_dev")
    op.create_unique_constraint(
        "uq_p1_delivery",
        "inbound_messages",
        ["tenant_id", "channel", "provider_message_id"],
        schema="p1_dev",
    )
    for column in (
        "source_authenticity",
        "resolved_parent_message_id",
        "parent_resolution",
        "exact_parent_reference",
        "rfc_message_id",
        "conversation_id",
        "provider_native_message_id",
        "provider_account_id",
    ):
        op.drop_column("inbound_messages", column, schema="p1_dev")
