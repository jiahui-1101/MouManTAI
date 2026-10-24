import importlib.machinery
import importlib.util
import os
import sys
from collections.abc import Generator

# Ensure pure-python SQLAlchemy implementation on environments with AppControl/WDAC/CI
os.environ["DISABLE_SQLALCHEMY_CEXT"] = "1"
# Test clients use header-based identity, so enable synthetic mode for tests.
os.environ.setdefault("MOUMANTAI_SYNTHETIC_MODE", "1")

# Strict mode: When REQUIRE_POSTGRES=1, bind to PostgreSQL suite URL before any app import (F12)
REQUIRE_POSTGRES = os.getenv("REQUIRE_POSTGRES", "0").lower() in ("1", "true", "yes")

if REQUIRE_POSTGRES:
    raw_pg_url = os.getenv("TEST_DATABASE_URL")
    if raw_pg_url:
        if raw_pg_url.startswith("postgresql://"):
            raw_pg_url = raw_pg_url.replace("postgresql://", "postgresql+psycopg://", 1)
        os.environ["DATABASE_URL"] = raw_pg_url
        os.environ["TEST_DATABASE_URL"] = raw_pg_url
        os.environ.setdefault("P1_DATABASE_URL", raw_pg_url)
        os.environ.setdefault("TEST_DATABASE_APPROVED", "1")
    else:
        # Strict mode: Point DATABASE_URL away from SQLite so unconfigured runs never silently pass on SQLite
        os.environ["DATABASE_URL"] = "postgresql+psycopg://missing-test-database-url:5432/none"
    raw_mig_url = os.getenv("TEST_MIGRATION_DATABASE_URL")
    if raw_mig_url and raw_mig_url.startswith("postgresql://"):
        os.environ["TEST_MIGRATION_DATABASE_URL"] = raw_mig_url.replace("postgresql://", "postgresql+psycopg://", 1)
else:
    # Ensure test default is in-memory SQLite unless explicitly overridden
    os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")


class PurePythonSQLAlchemyFinder(importlib.machinery.PathFinder):
    """Intercept and redirect SQLAlchemy cython modules to pure-Python implementations."""

    @classmethod
    def find_spec(cls, fullname, path=None, target=None):
        if fullname.startswith("sqlalchemy.") and fullname.endswith("_cy"):
            if path is None:
                return None
            for entry in path:
                base = os.path.join(entry, fullname.split(".")[-1] + ".py")
                if os.path.isfile(base):
                    return importlib.util.spec_from_file_location(fullname, base)
        return None


if not any(isinstance(finder, type) and finder.__name__ == "PurePythonSQLAlchemyFinder" for finder in sys.meta_path):
    sys.meta_path.insert(0, PurePythonSQLAlchemyFinder)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.dependencies import get_db
from app.db.base import Base
from app.orders import models as _order_models  # noqa: F401 - register OrderRequest tables
from app.suppliers import models as _supplier_models  # noqa: F401 - register Mock supplier tables
from app.main import app


def _truncate_all_application_tables(engine) -> None:
    """Truncate all application tables excluding alembic_version."""
    with engine.begin() as conn:
        tables = conn.execute(
            text(
                """
                SELECT table_schema, table_name 
                FROM information_schema.tables 
                WHERE table_type = 'BASE TABLE' 
                  AND table_schema NOT IN ('pg_catalog', 'information_schema')
                  AND table_name != 'alembic_version'
                """
            )
        ).fetchall()
        if tables:
            quoted = ", ".join(f'"{schema}"."{table}"' for schema, table in tables)
            conn.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))


@pytest.fixture(scope="session")
def pg_suite_engine():
    raw_url = os.getenv("TEST_DATABASE_URL")
    if not REQUIRE_POSTGRES:
        if not raw_url:
            pytest.skip("PostgreSQL engine requested but TEST_DATABASE_URL is not set")
    else:
        if not raw_url:
            pytest.fail("REQUIRE_POSTGRES=1 is set, but TEST_DATABASE_URL is missing or empty.")

    if raw_url.startswith("postgresql://"):
        raw_url = raw_url.replace("postgresql://", "postgresql+psycopg://", 1)

    try:
        engine = create_engine(raw_url, pool_pre_ping=True, connect_args={"connect_timeout": 3})
        if engine.dialect.name != "postgresql":
            pytest.fail(f"PostgreSQL tests require postgresql dialect, got '{engine.dialect.name}'")
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        if REQUIRE_POSTGRES:
            pytest.fail(f"REQUIRE_POSTGRES=1 is set, but PostgreSQL is unreachable at {raw_url}: {exc}")
        else:
            pytest.skip(f"PostgreSQL unreachable at {raw_url}: {exc}")

    # Build schema by running Alembic to head on the suite DB using F2 approach (b)
    from alembic import command
    from alembic.config import Config

    alembic_ini_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    migrations_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "migrations"))
    alembic_cfg = Config(alembic_ini_path)
    alembic_cfg.set_main_option("script_location", migrations_dir)
    alembic_cfg.set_main_option("sqlalchemy.url", raw_url.replace("%", "%%"))

    with engine.connect() as conn:
        alembic_cfg.attributes["connection"] = conn
        command.upgrade(alembic_cfg, "head")

    _truncate_all_application_tables(engine)

    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture(autouse=True)
def pg_isolation(request):
    if REQUIRE_POSTGRES:
        pg_eng = request.getfixturevalue("pg_suite_engine")
        yield
        _truncate_all_application_tables(pg_eng)
    else:
        yield


@pytest.fixture
def test_engine(request):
    if REQUIRE_POSTGRES:
        yield request.getfixturevalue("pg_suite_engine")
    else:
        # Portable suite only. Migrated PostgreSQL coverage has a separate opt-in
        # fixture that never creates tables or silently switches database engines.
        engine = create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        try:
            yield engine
        finally:
            Base.metadata.drop_all(engine)


@pytest.fixture
def session(test_engine) -> Generator[Session, None, None]:
    session_factory = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client(test_engine) -> Generator[TestClient, None, None]:
    session_factory = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
