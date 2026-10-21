"""P1-only local config and explicit schema initialization, not shared migrations."""

import os
import sys

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.schema import CreateSchema

from .postgres_repository import P1Base
from .repository import PersistenceUnavailable


def create_p1_engine(url: str | None = None) -> Engine:
    value = url or os.environ.get("P1_DATABASE_URL")
    if not value:
        raise PersistenceUnavailable("P1 development PostgreSQL is not configured")
    try:
        parsed = make_url(value)
        if parsed.drivername != "postgresql+psycopg":
            raise ValueError("PostgreSQL with psycopg is required")
        return create_engine(parsed, pool_pre_ping=True, connect_args={"connect_timeout": 3},
                             isolation_level="READ COMMITTED", hide_parameters=True)
    except (ValueError, TypeError, SQLAlchemyError):
        raise PersistenceUnavailable("P1 development PostgreSQL configuration is invalid") from None


def initialize_p1_schema(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(CreateSchema("p1_dev", if_not_exists=True))
        P1Base.metadata.create_all(connection)
        connection.execute(text("ALTER TABLE p1_dev.order_contexts ADD COLUMN IF NOT EXISTS core_commitment_id VARCHAR(100);"))
        connection.execute(text("ALTER TABLE p1_dev.order_contexts ADD COLUMN IF NOT EXISTS published_to_core_at TIMESTAMPTZ;"))


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
