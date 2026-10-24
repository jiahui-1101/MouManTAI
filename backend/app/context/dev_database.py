"""P1-only local config and explicit schema initialization, not shared migrations."""

import os
from pathlib import Path
import sys


def _load_env_if_present() -> None:
    candidates = [Path(".env"), Path(__file__).resolve().parents[3] / ".env"]
    for path in candidates:
        if path.is_file():
            try:
                for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, val = line.split("=", 1)
                        key = key.strip()
                        val = val.strip().strip("'\"")
                        if key not in os.environ:
                            os.environ[key] = val
            except Exception:
                pass
            break


_load_env_if_present()

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.schema import CreateSchema

from .postgres_repository import P1Base
from .repository import PersistenceUnavailable


def create_p1_engine(url: str | None = None) -> Engine:
    value = url or os.environ.get("P1_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not value:
        raise PersistenceUnavailable("P1 development PostgreSQL is not configured")
    try:
        parsed = make_url(value)
        if parsed.drivername == "postgresql":
            parsed = parsed.set(drivername="postgresql+psycopg")
        elif parsed.drivername != "postgresql+psycopg":
            raise ValueError("PostgreSQL with psycopg is required")
        return create_engine(parsed, pool_pre_ping=True, connect_args={"connect_timeout": 3},
                             isolation_level="READ COMMITTED", hide_parameters=True)
    except (ValueError, TypeError, SQLAlchemyError):
        raise PersistenceUnavailable("P1 development PostgreSQL configuration is invalid") from None


def initialize_p1_schema(engine: Engine) -> None:
    with engine.begin() as connection:
        from app.db.base import Base
        Base.metadata.create_all(connection)
        connection.execute(CreateSchema("p1_dev", if_not_exists=True))
        P1Base.metadata.create_all(connection)
        connection.execute(text("ALTER TABLE p1_dev.order_contexts ADD COLUMN IF NOT EXISTS core_commitment_id VARCHAR(100);"))
        connection.execute(text("ALTER TABLE p1_dev.order_contexts ADD COLUMN IF NOT EXISTS published_to_core_at TIMESTAMPTZ;"))
        connection.execute(text("ALTER TABLE p1_dev.inbound_messages ADD COLUMN IF NOT EXISTS provider VARCHAR(50) DEFAULT 'SYNTHETIC';"))
        connection.execute(text("ALTER TABLE p1_dev.inbound_messages ADD COLUMN IF NOT EXISTS provider_account_id VARCHAR(200);"))
        connection.execute(text("ALTER TABLE p1_dev.inbound_messages ADD COLUMN IF NOT EXISTS provider_native_message_id VARCHAR(998);"))
        connection.execute(text("ALTER TABLE p1_dev.inbound_messages ADD COLUMN IF NOT EXISTS conversation_id VARCHAR(998);"))
        connection.execute(text("ALTER TABLE p1_dev.inbound_messages ADD COLUMN IF NOT EXISTS rfc_message_id VARCHAR(998);"))
        connection.execute(text("ALTER TABLE p1_dev.inbound_messages ADD COLUMN IF NOT EXISTS exact_parent_reference VARCHAR(998);"))
        connection.execute(text("ALTER TABLE p1_dev.inbound_messages ADD COLUMN IF NOT EXISTS parent_resolution VARCHAR(24) NOT NULL DEFAULT 'LEGACY_UNKNOWN';"))
        connection.execute(text("ALTER TABLE p1_dev.inbound_messages ADD COLUMN IF NOT EXISTS resolved_parent_message_id VARCHAR(36);"))
        connection.execute(text("ALTER TABLE p1_dev.inbound_messages ADD COLUMN IF NOT EXISTS source_authenticity VARCHAR(20) NOT NULL DEFAULT 'UNVERIFIED';"))
        connection.execute(text("ALTER TABLE p1_dev.inbound_messages ALTER COLUMN synthetic_provider DROP NOT NULL;"))
        connection.execute(text("ALTER TABLE p1_dev.inbound_messages DROP CONSTRAINT IF EXISTS uq_p1_delivery;"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_p1_delivery_legacy ON p1_dev.inbound_messages (tenant_id, channel, provider_message_id) WHERE provider_account_id IS NULL;"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_p1_delivery_scoped ON p1_dev.inbound_messages (tenant_id, provider, provider_account_id, provider_native_message_id) WHERE provider_account_id IS NOT NULL AND channel <> 'TELEGRAM';"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_p1_delivery_telegram_scoped ON p1_dev.inbound_messages (tenant_id, provider, provider_account_id, conversation_id, provider_native_message_id) WHERE provider_account_id IS NOT NULL AND channel = 'TELEGRAM';"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_p1_parent_native_scope ON p1_dev.inbound_messages (tenant_id, provider, provider_account_id, conversation_id, provider_native_message_id) WHERE provider_account_id IS NOT NULL;"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_p1_parent_rfc_scope ON p1_dev.inbound_messages (tenant_id, provider, provider_account_id, rfc_message_id) WHERE provider_account_id IS NOT NULL AND rfc_message_id IS NOT NULL;"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_p1_pending_parent_scope ON p1_dev.inbound_messages (tenant_id, provider, provider_account_id, conversation_id, exact_parent_reference) WHERE parent_resolution = 'UNRESOLVED' AND provider_account_id IS NOT NULL;"))
        connection.execute(text("ALTER TABLE p1_dev.inbound_messages DROP CONSTRAINT IF EXISTS ck_p1_provider_identity_pair;"))
        connection.execute(text("ALTER TABLE p1_dev.inbound_messages ADD CONSTRAINT ck_p1_provider_identity_pair CHECK ((provider_account_id IS NULL) = (provider_native_message_id IS NULL));"))
        connection.execute(text("ALTER TABLE p1_dev.inbound_messages DROP CONSTRAINT IF EXISTS ck_p1_parent_resolution;"))
        connection.execute(text("ALTER TABLE p1_dev.inbound_messages ADD CONSTRAINT ck_p1_parent_resolution CHECK (parent_resolution IN ('NO_EXACT_PARENT', 'UNRESOLVED', 'AMBIGUOUS', 'REFERENCE_MATCH', 'LEGACY_UNKNOWN', 'INVALID'));"))
        connection.execute(text("ALTER TABLE p1_dev.inbound_messages DROP CONSTRAINT IF EXISTS ck_p1_source_authenticity;"))
        connection.execute(text("ALTER TABLE p1_dev.inbound_messages ADD CONSTRAINT ck_p1_source_authenticity CHECK (source_authenticity IN ('VERIFIED', 'UNVERIFIED', 'SYNTHETIC'));"))
        connection.execute(text("ALTER TABLE p1_dev.inbound_messages DROP CONSTRAINT IF EXISTS ck_p1_synthetic_provider;"))
        connection.execute(text("ALTER TABLE p1_dev.inbound_messages DROP CONSTRAINT IF EXISTS ck_p1_provenance;"))
        connection.execute(text("""
            ALTER TABLE p1_dev.inbound_messages ADD CONSTRAINT ck_p1_provenance
            CHECK (
                (synthetic_provider IS NOT NULL AND (
                    (channel = 'WHATSAPP' AND synthetic_provider = 'SYNTHETIC_WHATSAPP') OR
                    (channel = 'EMAIL' AND synthetic_provider = 'SYNTHETIC_EMAIL') OR
                    (channel = 'TELEGRAM' AND synthetic_provider = 'SYNTHETIC_TELEGRAM') OR
                    (channel = 'UNKNOWN' AND synthetic_provider = 'SYNTHETIC_UNKNOWN')
                ) AND provider = 'SYNTHETIC')
                OR
                (synthetic_provider IS NULL AND provider IN ('TELEGRAM_BOT_API', 'GMAIL_API', 'WHATSAPP_CLOUD_API', 'REAL') AND channel IN ('WHATSAPP', 'EMAIL', 'TELEGRAM', 'UNKNOWN'))
            );
        """))


if __name__ == "__main__":
    if sys.argv[1:] != ["init"]:
        raise SystemExit("Usage: python -m app.context.dev_database init")
    try:
        engine = create_p1_engine()
        initialize_p1_schema(engine)
        engine.dispose()
        print("Initialized provisional P1 schema p1_dev (P5 review pending)")
    except Exception:
        raise SystemExit("P1 schema initialization failed; check local PostgreSQL configuration/connectivity") from None
