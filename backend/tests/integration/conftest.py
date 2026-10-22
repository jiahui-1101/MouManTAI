"""Explicit synthetic authority for legacy Core journey tests only.

This is a test double, not durable Manager Approval or production authorization.
"""

import pytest

from app.core.errors import DomainError
from app.core.router import get_recovery_execution_authority
from app.main import app


@pytest.fixture
def synthetic_execution_authority():
    class SyntheticExecutionAuthority:
        def verify(self, db, context, commitment_id, request) -> None:
            if context.actor_role not in {"MANAGER", "OWNER"}:
                raise DomainError("APPROVAL_REQUIRED", "Manager role required", status_code=403)
            if request.plan.approval_state.value != "APPROVED":
                raise DomainError("APPROVAL_REQUIRED", "Synthetic plan is not approved", status_code=403)
            if request.plan.tenant_id != context.tenant_id or request.plan.commitment_id != commitment_id:
                raise DomainError("RECOVERY_SCOPE_MISMATCH", "Synthetic plan scope mismatch", status_code=403)

    previous = app.dependency_overrides.get(get_recovery_execution_authority)
    app.dependency_overrides[get_recovery_execution_authority] = SyntheticExecutionAuthority
    try:
        yield
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_recovery_execution_authority, None)
        else:
            app.dependency_overrides[get_recovery_execution_authority] = previous

@pytest.fixture
def postgresql_test_engine():
    """Use only an explicitly approved, already migrated PostgreSQL test DB.

    This fixture does not create, migrate, reset, or drop database objects.
    """
    import os
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.engine import make_url

    from app.core.models import AuditEventRecord, CommitmentRecord, ResourceStockRecord
    from app.feasibility.persisted_sources import OperationalSnapshotRecord

    raw_url = os.getenv("TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("PostgreSQL NOT VERIFIED: explicit TEST_DATABASE_URL is absent")
    if os.getenv("TEST_DATABASE_APPROVED") != "1":
        pytest.fail("TEST_DATABASE_APPROVED=1 is required")

    url = make_url(raw_url)
    if not url.database or "test" not in url.database.lower():
        pytest.fail("PostgreSQL integration tests require a named disposable test database")

    engine = create_engine(raw_url, pool_pre_ping=True)
    try:
        if engine.dialect.name != "postgresql":
            pytest.fail(f"PostgreSQL integration tests require PostgreSQL, got {engine.dialect.name}")

        config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
        script = ScriptDirectory.from_config(config)
        heads = script.get_heads()
        if len(heads) != 1:
            pytest.fail(f"Expected exactly one Alembic head, found {heads}")

        with engine.connect() as connection:
            revisions = connection.scalars(text("SELECT version_num FROM alembic_version")).all()
        if revisions != heads:
            pytest.fail(f"Database must already be at Alembic head {heads}; found {revisions}")

        tables = set(inspect(engine).get_table_names())
        required = {
            CommitmentRecord.__tablename__,
            AuditEventRecord.__tablename__,
            ResourceStockRecord.__tablename__,
            OperationalSnapshotRecord.__tablename__,
        }
        if not required <= tables:
            pytest.fail(f"Migrated PostgreSQL schema is missing tables: {sorted(required - tables)}")

        yield engine
    finally:
        engine.dispose()
