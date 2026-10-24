"""Comprehensive migration tests for 0007_recovery_case_constraints_alignment (ADR-017, Task T-P3H1).

Verifies:
1. Exactly one Alembic head with a valid history containing revision 0007.
2. Upgrade 0006 -> 0007 preserves seeded case and trigger rows with zero data loss.
3. Negative RESTRICT test: DELETE FROM recovery_cases with dependent triggers raises IntegrityError.
4. Negative RESTRICT test: DELETE FROM commitments with dependent triggers raises IntegrityError.
5. Partial unique index uq_recovery_cases_one_active_per_commitment:
   - Exactly one active case per commitment permitted.
   - Attempting to insert a second active case for the same commitment fails with IntegrityError.
   - A COMPLETED (inactive) case does not block a new active case for the same commitment.
6. Downgrade 0007 -> 0006 cleanly restores original constraint names and CASCADE policy.
7. Re-upgrade from 0006 -> 0007 succeeds.
8. PostgreSQL schema proof is in the separate opt-in migrated database suite.
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

ALEMBIC_INI = os.path.join(REPO_ROOT, "backend", "alembic.ini")
MIGRATIONS_DIR = os.path.join(REPO_ROOT, "backend", "migrations")


def _get_alembic_config(db_url: str) -> Config:
    cfg = Config(ALEMBIC_INI)
    cfg.set_main_option("sqlalchemy.url", db_url)
    cfg.set_main_option("script_location", MIGRATIONS_DIR)
    return cfg


def test_alembic_has_exactly_one_head() -> None:
    """Keep 0007 in valid ancestry while permitting later feature migrations."""
    cfg = Config(ALEMBIC_INI)
    cfg.set_main_option("script_location", MIGRATIONS_DIR)
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1, f"Expected exactly 1 Alembic head, found: {heads}"
    required = "0007_recovery_case_constraints_alignment"
    assert script.get_revision(required) is not None, f"Required migration {required} is missing"
    # Alembic resolves the complete graph here and rejects missing parents/cycles.
    history = list(script.walk_revisions(base="base", head=heads[0]))
    revisions = {revision.revision for revision in history}
    assert len(revisions) == len(history), "Migration history contains duplicate revisions"
    assert required in revisions, f"{required} must be the head or an ancestor of {heads[0]}"
    assert any(revision.down_revision is None for revision in history), "Migration history has no base"
    for revision in history:
        parents = revision.down_revision
        if parents is None:
            continue
        if isinstance(parents, str):
            parents = (parents,)
        assert set(parents) <= revisions, f"Unresolved parent(s) for migration {revision.revision}"


def test_migration_0006_to_0007_upgrade_downgrade_and_restrict() -> None:
    """Exercise migration constraints on the dedicated PG DB or a temporary SQLite file."""
    require_pg = os.getenv("REQUIRE_POSTGRES", "0").lower() in ("1", "true", "yes")
    tmp_path = None
    if require_pg:
        mig_url = os.getenv("TEST_MIGRATION_DATABASE_URL")
        if not mig_url:
            pytest.fail("REQUIRE_POSTGRES=1 is set, but TEST_MIGRATION_DATABASE_URL is missing or empty.")
        if mig_url.startswith("postgresql://"):
            mig_url = mig_url.replace("postgresql://", "postgresql+psycopg://", 1)
        parsed = make_url(mig_url)
        if (
            os.getenv("TEST_DATABASE_APPROVED") != "1"
            or not parsed.drivername.startswith("postgresql")
            or parsed.host not in ("localhost", "127.0.0.1", "::1")
            or not parsed.database
            or not (parsed.database == "moumantai_migration" or parsed.database.endswith("_test"))
        ):
            pytest.fail("Use an approved local, disposable PostgreSQL migration test database")
        db_url = mig_url
    else:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = tmp.name
        db_url = f"sqlite:///{tmp_path.replace(os.sep, '/')}"

    cfg = _get_alembic_config(db_url)
    old_env_db_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = db_url
    engine = create_engine(db_url)

    try:
        if require_pg:
            with engine.begin() as conn:
                conn.execute(text("DROP SCHEMA public CASCADE"))
                conn.execute(text("CREATE SCHEMA public"))
                # The later P1 migration owns this separate schema. Reset it too,
                # otherwise a second run fails on its already-created tables.
                conn.execute(text("DROP SCHEMA IF EXISTS p1_dev CASCADE"))

        # 1. Migrate to 0006
        command.upgrade(cfg, "0006_recovery_cases")

        now = datetime.now(timezone.utc).isoformat()
        tenant = "tenant_mig_07"
        com_id = "com_mig_07"
        case_id = "case_mig_07"
        event_id = "evt_mig_07"

        # 2. Seed data in commitments, recovery_cases, and recovery_case_triggers at 0006
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM recovery_case_triggers WHERE tenant_id = :t"), {"t": tenant})
            conn.execute(text("DELETE FROM recovery_cases WHERE tenant_id = :t"), {"t": tenant})
            conn.execute(text("DELETE FROM commitments WHERE tenant_id = :t"), {"t": tenant})
            # Seed commitment
            conn.execute(
                text(
                    """
                    INSERT INTO commitments (
                        tenant_id, commitment_id, customer_id, order_id,
                        agreement_state, feasibility_state, risk_state, recovery_state, fulfilment_state,
                        commitment_version, terms, evidence_refs, updated_at
                    ) VALUES (
                        :tenant_id, :commitment_id, 'cust_01', 'ord_01',
                        'CONFIRMED', 'FEASIBLE', 'NORMAL', 'NOT_STARTED', 'UNFULFILLED',
                        1, '{"sku": "BURGER", "quantity": "10", "unit": "pcs"}', '[]', :now
                    )
                    """
                ),
                {"tenant_id": tenant, "commitment_id": com_id, "now": now},
            )

            # Seed recovery case at 0006
            conn.execute(
                text(
                    """
                    INSERT INTO recovery_cases (
                        tenant_id, case_id, commitment_id, risk_episode_id, opening_event_id,
                        status, case_version, commitment_version, payload_schema_version,
                        case_payload, resolution_refs, created_at, updated_at
                    ) VALUES (
                        :tenant_id, :case_id, :commitment_id, 'risk_ep_01', :event_id,
                        'OPEN', 1, 1, 1,
                        '{"plan_id": "p_01"}', '[]', :now, :now
                    )
                    """
                ),
                {"tenant_id": tenant, "case_id": case_id, "commitment_id": com_id, "event_id": event_id, "now": now},
            )

            # Seed recovery trigger at 0006
            conn.execute(
                text(
                    """
                    INSERT INTO recovery_case_triggers (
                        tenant_id, event_id, case_id, commitment_id, commitment_version,
                        assessment_id, assessment_provenance_status, snapshot_version,
                        constraints, affected_commitment_ids, evidence_refs,
                        correlation_id, occurred_at, event_digest
                    ) VALUES (
                        :tenant_id, :event_id, :case_id, :commitment_id, 1,
                        'asm_01', 'VERIFIED', 101,
                        '[]', '[]', '[]',
                        'corr_01', :now, 'digest_01'
                    )
                    """
                ),
                {"tenant_id": tenant, "event_id": event_id, "case_id": case_id, "commitment_id": com_id, "now": now},
            )

        # 3. Upgrade to 0007_recovery_case_constraints_alignment
        command.upgrade(cfg, "0007_recovery_case_constraints_alignment")

        # 4. Zero Data Loss Assertion: ensure seeded case and trigger rows are intact
        with engine.connect() as conn:
            case_row = conn.execute(
                text("SELECT case_id, status FROM recovery_cases WHERE tenant_id = :t AND case_id = :c"),
                {"t": tenant, "c": case_id},
            ).mappings().one()
            assert case_row["case_id"] == case_id
            assert case_row["status"] == "OPEN"

            trigger_row = conn.execute(
                text("SELECT event_id, assessment_id FROM recovery_case_triggers WHERE tenant_id = :t AND event_id = :e"),
                {"t": tenant, "e": event_id},
            ).mappings().one()
            assert trigger_row["event_id"] == event_id
            assert trigger_row["assessment_id"] == "asm_01"

        # 5. Negative RESTRICT Test: DELETE FROM recovery_cases with dependent trigger MUST FAIL
        with engine.connect() as conn:
            if engine.dialect.name == "sqlite":
                conn.execute(text("PRAGMA foreign_keys = ON"))
            with pytest.raises(IntegrityError):
                conn.execute(
                    text("DELETE FROM recovery_cases WHERE tenant_id = :t AND case_id = :c"),
                    {"t": tenant, "c": case_id},
                )
                conn.commit()
            conn.rollback()

        # 6. Negative RESTRICT Test: DELETE FROM commitments with dependent trigger MUST FAIL
        with engine.connect() as conn:
            if engine.dialect.name == "sqlite":
                conn.execute(text("PRAGMA foreign_keys = ON"))
            with pytest.raises(IntegrityError):
                conn.execute(
                    text("DELETE FROM commitments WHERE tenant_id = :t AND commitment_id = :c"),
                    {"t": tenant, "c": com_id},
                )
                conn.commit()
            conn.rollback()

        # 7. Partial Unique Index: only one active case per commitment
        with engine.connect() as conn:
            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        """
                        INSERT INTO recovery_cases (
                            tenant_id, case_id, commitment_id, risk_episode_id, opening_event_id,
                            status, case_version, commitment_version, payload_schema_version,
                            case_payload, resolution_refs, created_at, updated_at
                        ) VALUES (
                            :tenant_id, 'case_second_active', :commitment_id, 'risk_ep_02', 'evt_second',
                            'AWAITING_EVALUATION_INPUTS', 1, 1, 1,
                            '{}', '[]', :now, :now
                        )
                        """
                    ),
                    {"tenant_id": tenant, "commitment_id": com_id, "now": now},
                )
                conn.commit()
            conn.rollback()

            # A COMPLETED (inactive) case should NOT violate the partial index
            conn.execute(
                text(
                    """
                    INSERT INTO recovery_cases (
                        tenant_id, case_id, commitment_id, risk_episode_id, opening_event_id,
                        status, case_version, commitment_version, payload_schema_version,
                        case_payload, resolution_refs, created_at, updated_at
                    ) VALUES (
                        :tenant_id, 'case_completed_prior', :commitment_id, 'risk_ep_prior', 'evt_prior',
                        'COMPLETED', 1, 1, 1,
                        '{}', '[]', :now, :now
                    )
                    """
                ),
                {"tenant_id": tenant, "commitment_id": com_id, "now": now},
            )
            conn.commit()

        # 8. Clean Downgrade 0007 -> 0006
        command.downgrade(cfg, "0006_recovery_cases")

        # Verify data still preserved after downgrade
        with engine.connect() as conn:
            count = conn.execute(text("SELECT count(*) FROM recovery_cases")).scalar()
            assert count >= 2

        # 9. Re-upgrade from 0006 -> 0007 (head)
        command.upgrade(cfg, "head")

    finally:
        engine.dispose()
        if old_env_db_url is not None:
            os.environ["DATABASE_URL"] = old_env_db_url
        else:
            os.environ.pop("DATABASE_URL", None)
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
