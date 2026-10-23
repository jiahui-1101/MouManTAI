"""Opt-in proof against an approved, already migrated PostgreSQL test database.

Set TEST_DATABASE_URL and TEST_DATABASE_APPROVED=1 explicitly. This module never
creates tables, upgrades migrations, drops a database, or substitutes SQLite.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError


REVISION_0007 = "0007_recovery_case_constraints_alignment"

pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module")
def migrated_postgresql_engine():
    if os.environ.get("REQUIRE_POSTGRES") != "1":
        pytest.skip("PostgreSQL NOT VERIFIED: REQUIRE_POSTGRES=1 is absent")
    raw_url = os.environ.get("TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("PostgreSQL NOT VERIFIED: explicit approved TEST_DATABASE_URL is absent")
    if os.environ.get("TEST_DATABASE_APPROVED") != "1":
        pytest.fail("TEST_DATABASE_URL requires explicit TEST_DATABASE_APPROVED=1")
    url = make_url(raw_url)
    assert url.get_backend_name() == "postgresql", "Migrated integration requires PostgreSQL"
    assert url.database and "test" in url.database.lower(), "Database identifier must name an isolated test DB"
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    engine = create_engine(url, pool_pre_ping=True)
    assert engine.dialect.name == "postgresql"
    try:
        yield engine
    finally:
        engine.dispose()


def _assert_migration_0007_or_descendant(connection) -> str:
    current = connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
    assert len(current) == 1, f"Expected one applied Alembic revision, found {len(current)}"
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "migrations"))
    script = ScriptDirectory.from_config(config)
    revisions = {revision.revision for revision in script.iterate_revisions(current[0], "base")}
    assert REVISION_0007 in revisions, f"Applied revision {current[0]} does not descend from 0007"
    return current[0]


def test_migrated_postgresql_schema_enforces_recovery_constraints(migrated_postgresql_engine) -> None:
    engine = migrated_postgresql_engine
    with engine.connect() as connection:
        _assert_migration_0007_or_descendant(connection)
    inspector = inspect(engine)
    required = {"commitments", "recovery_cases", "recovery_case_triggers", "processed_events"}
    assert required <= set(inspector.get_table_names())
    assert set(inspector.get_pk_constraint("recovery_cases")["constrained_columns"]) == {"tenant_id", "case_id"}
    assert set(inspector.get_pk_constraint("recovery_case_triggers")["constrained_columns"]) == {"tenant_id", "event_id"}
    unique_names = {item["name"] for item in inspector.get_unique_constraints("recovery_cases")}
    assert "uq_recovery_cases_tenant_case_commitment" in unique_names
    index_names = {item["name"] for item in inspector.get_indexes("recovery_cases")}
    assert "uq_recovery_cases_one_active_per_commitment" in index_names
    foreign_keys = {item["name"]: item for item in inspector.get_foreign_keys("recovery_case_triggers")}
    for name in ("fk_recovery_case_triggers_case_tenant_commitment", "fk_recovery_case_triggers_commitment_tenant"):
        assert foreign_keys[name]["options"]["ondelete"] == "RESTRICT"


def test_migrated_postgresql_case_trigger_processed_atomicity(migrated_postgresql_engine) -> None:
    engine = migrated_postgresql_engine
    tenant = f"tenant_p3_pg_{uuid4().hex[:12]}"
    commitment = f"com_{uuid4().hex[:12]}"
    case = f"case_{uuid4().hex[:12]}"
    event = f"evt_{uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)
    params = {
        "tenant": tenant, "commitment": commitment, "case": case, "event": event,
        "wrong_tenant": f"wrong_{uuid4().hex[:12]}", "now": now,
    }

    with engine.connect() as connection:
        _assert_migration_0007_or_descendant(connection)
        assert {"recovery_cases", "recovery_case_triggers"} <= set(inspect(connection).get_table_names())

    try:
        with engine.begin() as connection:
            connection.execute(text("""
                INSERT INTO commitments (tenant_id, commitment_id, order_id, customer_id, terms,
                    agreement_state, feasibility_state, risk_state, recovery_state, fulfilment_state,
                    commitment_version, evidence_refs, updated_at)
                VALUES (:tenant, :commitment, 'ord_pg', 'cust_pg', '{}',
                    'CONFIRMED', 'INFEASIBLE', 'AT_RISK', 'RECOVERY_REQUIRED', 'NOT_STARTED',
                    2, '[]', :now)
            """), params)
            connection.execute(text("""
                INSERT INTO recovery_cases (tenant_id, case_id, commitment_id, risk_episode_id,
                    opening_event_id, status, case_version, commitment_version,
                    payload_schema_version, case_payload, resolution_refs, created_at, updated_at)
                VALUES (:tenant, :case, :commitment, :event, :event, 'OPEN', 1, 2, 1,
                    '{}', '[]', :now, :now)
            """), params)
            connection.execute(text("""
                INSERT INTO recovery_case_triggers (tenant_id, event_id, case_id, commitment_id,
                    commitment_version, assessment_id, assessment_commitment_version,
                    assessment_provenance_status, snapshot_id, snapshot_version, constraints,
                    affected_commitment_ids, evidence_refs, correlation_id, occurred_at, event_digest)
                VALUES (:tenant, :event, :case, :commitment, 2, 'asm_pg', 1,
                    'VERIFIED_AUTHORITATIVE', 'snap_pg', 7, '[]', '[]', '["ev_pg"]',
                    'corr_pg', :now, 'digest_pg')
            """), params)
            connection.execute(text("""
                INSERT INTO processed_events (tenant_id, event_id, consumer_name, processed_at)
                VALUES (:tenant, :event, 'p3.recovery_trigger.v1', :now)
            """), params)

        with engine.connect() as connection:
            for table in ("recovery_cases", "recovery_case_triggers", "processed_events"):
                count = connection.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id = :tenant"), params
                ).scalar_one()
                assert count == 1, f"{table} was not persisted"

            for statement in (
                "DELETE FROM recovery_cases WHERE tenant_id = :tenant AND case_id = :case",
                "DELETE FROM commitments WHERE tenant_id = :tenant AND commitment_id = :commitment",
                "INSERT INTO processed_events (tenant_id, event_id, consumer_name, processed_at) "
                "VALUES (:tenant, :event, 'p3.recovery_trigger.v1', :now)",
                "INSERT INTO recovery_cases (tenant_id, case_id, commitment_id, risk_episode_id, "
                "opening_event_id, status, case_version, commitment_version, payload_schema_version, "
                "case_payload, resolution_refs, created_at, updated_at) VALUES "
                "(:tenant, 'second_active_pg', :commitment, 'second_episode_pg', 'second_event_pg', "
                "'OPEN', 1, 2, 1, '{}', '[]', :now, :now)",
                "INSERT INTO recovery_case_triggers (tenant_id, event_id, case_id, commitment_id, "
                "commitment_version, assessment_id, assessment_provenance_status, snapshot_version, "
                "constraints, affected_commitment_ids, evidence_refs, correlation_id, occurred_at, event_digest) "
                "VALUES (:wrong_tenant, 'wrong_tenant_event', :case, :commitment, 2, 'asm_wrong', "
                "'VERIFIED_AUTHORITATIVE', 7, '[]', '[]', '[]', 'corr_pg', :now, 'digest_wrong')",
                "UPDATE recovery_cases SET status = 'INVALID' "
                "WHERE tenant_id = :tenant AND case_id = :case",
                "UPDATE recovery_case_triggers SET snapshot_version = 0 "
                "WHERE tenant_id = :tenant AND event_id = :event",
            ):
                savepoint = connection.begin_nested()
                with pytest.raises(IntegrityError):
                    connection.execute(text(statement), params)
                savepoint.rollback()

        rollback_case = f"rollback_{uuid4().hex[:12]}"
        rollback_event = f"rollback_{uuid4().hex[:12]}"
        rollback_params = {**params, "case": rollback_case, "event": rollback_event}
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text("""
                    INSERT INTO recovery_cases (tenant_id, case_id, commitment_id, risk_episode_id,
                        opening_event_id, status, case_version, commitment_version,
                        payload_schema_version, case_payload, resolution_refs, created_at, updated_at)
                    VALUES (:tenant, :case, :commitment, :event, :event, 'COMPLETED', 1, 2, 1,
                        '{}', '[]', :now, :now)
                """), rollback_params)
                connection.execute(text("""
                    INSERT INTO recovery_case_triggers (tenant_id, event_id, case_id, commitment_id,
                        commitment_version, assessment_id, assessment_provenance_status,
                        snapshot_version, constraints, affected_commitment_ids, evidence_refs,
                        correlation_id, occurred_at, event_digest)
                    VALUES (:tenant, :event, :case, :commitment, 2, 'asm_rollback',
                        'VERIFIED_AUTHORITATIVE', 7, '[]', '[]', '[]', 'corr_pg', :now, 'digest_rollback')
                """), rollback_params)
                connection.execute(text("""
                    INSERT INTO processed_events (tenant_id, event_id, consumer_name, processed_at)
                    VALUES (:tenant, :event, 'p3.recovery_trigger.v1', :now)
                """), rollback_params)
            finally:
                transaction.rollback()
        with engine.connect() as connection:
            for table in ("recovery_cases", "recovery_case_triggers", "processed_events"):
                assert connection.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id = :tenant AND event_id = :event")
                    if table != "recovery_cases" else
                    text("SELECT count(*) FROM recovery_cases WHERE tenant_id = :tenant AND case_id = :case"),
                    rollback_params,
                ).scalar_one() == 0
    finally:
        with engine.begin() as connection:
            for table in ("processed_events", "recovery_case_triggers", "recovery_cases", "commitments"):
                connection.execute(text(f"DELETE FROM {table} WHERE tenant_id = :tenant"), params)
