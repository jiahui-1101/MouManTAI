"""Real migrated PostgreSQL proof for the canonical P2 -> Core -> P3 path.

This module requires an explicitly approved disposable TEST_DATABASE_URL. It
does not create, migrate, reset, or drop databases or schemas.
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.events import CoreEventType, OutboxStatus
from app.core.models import (
    AuditEventRecord,
    CommitmentRecord,
    CommitmentProposalRecord,
    OutboxEventRecord,
    ProcessedEventRecord,
)
from app.core.outbox import OutboxDispatcher
from app.core.schemas import (
    CommitmentCreateRequest,
    ProposalConfirmRequest,
    ProposalCreateRequest,
)
from app.core.service import CommitmentService
from app.feasibility.persisted_sources import OperationalSnapshotRecord, stage_snapshot
from app.feasibility.production import EvaluationSnapshot
from app.feasibility.production_fixtures import build_production_example
from app.recovery.persistence import RecoveryCaseRecord, RecoveryCaseTriggerRecord
from app.worker import configure_isolated_subscribers


def _approved_engine():
    raw_url = os.getenv("TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("PostgreSQL NOT VERIFIED: explicit approved TEST_DATABASE_URL is absent")
    if os.getenv("TEST_DATABASE_APPROVED") != "1":
        pytest.fail("TEST_DATABASE_APPROVED=1 is required")
    url = make_url(raw_url)
    if not url.database or "test" not in url.database.lower():
        pytest.fail("A named disposable test database is required")

    engine = create_engine(raw_url, pool_pre_ping=True)
    assert engine.dialect.name == "postgresql"
    alembic_config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    script = ScriptDirectory.from_config(alembic_config)
    assert len(script.get_heads()) == 1, "migration graph must have exactly one Alembic head"
    with engine.connect() as connection:
        revisions = connection.scalars(text("SELECT version_num FROM alembic_version")).all()
        assert revisions == script.get_heads(), (revisions, script.get_heads())
    revision = revisions[0]
    ancestors = {entry.revision for entry in script.iterate_revisions(revision, "base")}
    assert "0011_p4_confirmations" in ancestors
    assert "0012_p3_internal_actions" in ancestors
    tables = set(inspect(engine).get_table_names())
    required = {
        CommitmentRecord.__tablename__,
        CommitmentProposalRecord.__tablename__,
        AuditEventRecord.__tablename__,
        OutboxEventRecord.__tablename__,
        ProcessedEventRecord.__tablename__,
        OperationalSnapshotRecord.__tablename__,
        RecoveryCaseRecord.__tablename__,
        RecoveryCaseTriggerRecord.__tablename__,
    }
    assert required <= tables, f"migrated integration tables are missing: {sorted(required - tables)}"
    # This opt-in test module uses only these tenant prefixes. Quarantine retry
    # records left by a prior run so the global dispatcher cannot consume them
    # before the new test event; no other tenant's outbox is touched.
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE outbox_events SET status = 'PUBLISHED', "
                "published_at = COALESCE(published_at, now()), next_retry_at = NULL "
                "WHERE (tenant_id LIKE 'tenant_p2_p3_%' OR tenant_id LIKE 'tenant_p2_stale_%') "
                "AND status IN ('PENDING', 'FAILED')"
            )
        )
    return engine


def _isolated_snapshot(tenant_id: str, commitment_id: str, commitment_version: int) -> EvaluationSnapshot:
    base, _ = build_production_example()
    data = base.model_dump(exclude_computed_fields=True)
    operational = data["operational"]
    operational["tenant_id"] = tenant_id
    for key in (
        "sku_catalog",
        "bom_components",
        "inventory_lots",
        "reservations",
        "incoming_deliveries",
        "capacity_calendars",
        "confirmed_commitments",
        "unit_conversions",
    ):
        for row in operational[key]:
            row["tenant_id"] = tenant_id
    for source in operational["sources"]:
        source["tenant_id"] = tenant_id
        source["source_ref"] = f"db://{source['source_id']}"
        source["evidence_refs"] = [f"ev_{source['source_id']}"]
    # A real P2 hard shortage drives Core's AT_RISK transition.
    patty_lot = next(row for row in operational["inventory_lots"] if row["sku_id"] == "PATTY")
    patty_lot["quantity"] = "50"
    target = next(row for row in operational["confirmed_commitments"])
    target.update(
        tenant_id=tenant_id,
        commitment_id=commitment_id,
        commitment_version=commitment_version,
    )

    production = data["production"]
    production["tenant_id"] = tenant_id
    for key in ("resources", "processes", "plans", "jobs"):
        for row in production[key] or ():
            row["tenant_id"] = tenant_id
    for source in production["sources"]:
        source["tenant_id"] = tenant_id
        source["source_ref"] = f"db://{source['source_id']}"
        source["evidence_refs"] = [f"ev_{source['source_id']}"]
    for plan in production["plans"]:
        plan["commitment_id"] = commitment_id
        plan["commitment_version"] = commitment_version
    return EvaluationSnapshot.model_validate(data)


def _create_confirmed_commitment(db: Session, tenant_id: str) -> tuple[str, str]:
    _, base_commitment = build_production_example()
    commitment_id = f"com_p2_p3_{uuid4().hex[:12]}"
    context = RequestContext(
        tenant_id=tenant_id,
        actor_id="user_manager_01",
        actor_role="MANAGER",
        correlation_id=f"corr_{uuid4().hex}",
    )
    service = CommitmentService()
    created = service.create_request(
        db,
        context,
        CommitmentCreateRequest(
            commitment_id=commitment_id,
            order_id=f"ord_{uuid4().hex[:12]}",
            customer_id=f"cust_{uuid4().hex[:12]}",
            terms=base_commitment.terms,
            evidence_refs=[f"ev_request_{uuid4().hex}"],
        ),
    )
    proposal_id = f"prop_{uuid4().hex}"
    service.create_proposal(
        db,
        context,
        commitment_id,
        ProposalCreateRequest(
            proposal_id=proposal_id,
            proposal_version=1,
            expected_commitment_version=created.commitment_version,
            revised_terms=base_commitment.terms,
            reason="Isolated synthetic integration fixture",
            evidence_refs=[f"ev_proposal_{uuid4().hex}"],
        ),
    )
    transition = service.confirm_proposal(
        db,
        context,
        commitment_id,
        ProposalConfirmRequest(
            proposal_id=proposal_id,
            proposal_version=1,
            expected_commitment_version=2,
            decision="ACCEPT",
            evidence_refs=[f"ev_synthetic_test_acceptance_{uuid4().hex}"],
            reason="Isolated synthetic test identity only",
            customer_identity_status="LINK_VERIFIED",
        ),
    )
    assert transition.domain_event.event_type == CoreEventType.COMMITMENT_CONFIRMED.value
    return commitment_id, transition.domain_event.event_id


def _configure_test_dispatcher(monkeypatch) -> OutboxDispatcher:
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E", "1")
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E_KEY", f"isolated-e2e-{uuid4().hex}")
    dispatcher = OutboxDispatcher()
    configure_isolated_subscribers(dispatcher)
    assert [name for name, _ in dispatcher.get_subscribers("commitment.confirmed")] == [
        "p2_confirmed_evaluator"
    ]
    assert [name for name, _ in dispatcher.get_subscribers("commitment.at_risk")] == [
        "p3.recovery_trigger.v1"
    ]
    return dispatcher


def test_confirmed_p2_event_retries_atomically_through_core_risk_to_p3_case(
    monkeypatch,
) -> None:
    engine = _approved_engine()
    tenant_id = f"tenant_p2_p3_{uuid4().hex[:12]}"
    dispatcher = _configure_test_dispatcher(monkeypatch)
    try:
        with Session(engine) as db:
            commitment_id, confirmed_event_id = _create_confirmed_commitment(db, tenant_id)
            current = db.get(CommitmentRecord, (tenant_id, commitment_id))
            assert current is not None and current.commitment_version == 3
            stage_snapshot(
                db,
                _isolated_snapshot(tenant_id, commitment_id, current.commitment_version),
                current=True,
            )
            db.commit()

            p2_handler = dispatcher.get_subscribers("commitment.confirmed")[0][1]
            fail_once = True

            def fail_after_core_staging(session, event):
                nonlocal fail_once
                result = p2_handler(session, event)
                if fail_once:
                    fail_once = False
                    raise RuntimeError("injected post-stage retry check")
                return result

            dispatcher.register_subscriber(
                "commitment.confirmed", "p2_confirmed_evaluator", fail_after_core_staging
            )
            first = dispatcher.process_outbox_batch(db)
            failed_event = db.get(OutboxEventRecord, confirmed_event_id)
            assert first.processed_count >= 1
            assert failed_event.status == OutboxStatus.FAILED.value
            assert failed_event.attempts == 1
            assert failed_event.last_error == "RuntimeError: injected post-stage retry check"
            assert db.get(
                ProcessedEventRecord,
                (tenant_id, confirmed_event_id, "p2_confirmed_evaluator"),
            ) is None
            rolled_back_commitment = db.get(CommitmentRecord, (tenant_id, commitment_id))
            assert rolled_back_commitment.commitment_version == 3
            assert rolled_back_commitment.risk_state == "NORMAL"
            assert db.scalar(
                select(func.count()).select_from(AuditEventRecord).where(
                    AuditEventRecord.tenant_id == tenant_id,
                    AuditEventRecord.commitment_id == commitment_id,
                    AuditEventRecord.event_type == CoreEventType.COMMITMENT_AT_RISK.value,
                )
            ) == 0
            assert db.scalar(
                select(func.count()).select_from(OutboxEventRecord).where(
                    OutboxEventRecord.tenant_id == tenant_id,
                    OutboxEventRecord.event_type == CoreEventType.COMMITMENT_AT_RISK.value,
                )
            ) == 0

            # Retry through the same canonical P2 handler after the dispatcher rollback.
            dispatcher.register_subscriber(
                "commitment.confirmed", "p2_confirmed_evaluator", p2_handler
            )
            failed_event.next_retry_at = None
            db.commit()
            retried = dispatcher.process_outbox_batch(db)
            assert retried.failed_count == 0
            assert failed_event.status == OutboxStatus.PUBLISHED.value
            assert db.get(
                ProcessedEventRecord,
                (tenant_id, confirmed_event_id, "p2_confirmed_evaluator"),
            ) is not None

            at_risk = db.scalar(
                select(OutboxEventRecord).where(
                    OutboxEventRecord.tenant_id == tenant_id,
                    OutboxEventRecord.commitment_id == commitment_id,
                    OutboxEventRecord.event_type == CoreEventType.COMMITMENT_AT_RISK.value,
                )
            )
            assert at_risk is not None and at_risk.status == OutboxStatus.PENDING.value
            assessment_id = at_risk.payload["assessment_id"]
            assert at_risk.payload["assessment_commitment_version"] == 3
            assert at_risk.payload["commitment_id"] == commitment_id
            assert at_risk.payload["snapshot_id"] == "snapshot-buffered-v1"
            assert at_risk.payload["snapshot_version"] == 1
            assert at_risk.causation_id == confirmed_event_id
            assert at_risk.payload["evidence_refs"]

            assessed = db.scalar(
                select(AuditEventRecord).where(
                    AuditEventRecord.tenant_id == tenant_id,
                    AuditEventRecord.commitment_id == commitment_id,
                    AuditEventRecord.event_type == CoreEventType.COMMITMENT_AT_RISK.value,
                )
            )
            assert assessed is not None
            assert assessed.new_state["assessment_id"] == assessment_id
            assert assessed.new_state["assessment_commitment_version"] == 3
            assert assessed.new_state["commitment_version"] == 4
            assert assessed.new_state["snapshot_id"] == at_risk.payload["snapshot_id"]
            assert assessed.new_state["snapshot_version"] == at_risk.payload["snapshot_version"]
            assert assessed.evidence_refs == at_risk.payload["evidence_refs"]

            core = db.get(CommitmentRecord, (tenant_id, commitment_id))
            assert core.commitment_version == 4
            assert core.feasibility_state == "INFEASIBLE"
            assert core.risk_state == "AT_RISK"

            # A second dispatcher pass consumes the Core risk event via P3's
            # persisted assessment lookup in the same PostgreSQL transaction.
            dispatcher.process_outbox_batch(db)
            at_risk = db.get(OutboxEventRecord, at_risk.event_id)
            assert at_risk.status == OutboxStatus.PUBLISHED.value
            trigger = db.scalar(
                select(RecoveryCaseTriggerRecord).where(
                    RecoveryCaseTriggerRecord.tenant_id == tenant_id,
                    RecoveryCaseTriggerRecord.event_id == at_risk.event_id,
                )
            )
            case = db.scalar(
                select(RecoveryCaseRecord).where(
                    RecoveryCaseRecord.tenant_id == tenant_id,
                    RecoveryCaseRecord.commitment_id == commitment_id,
                )
            )
            assert trigger is not None and case is not None
            assert trigger.assessment_id == assessment_id
            assert trigger.snapshot_id == at_risk.payload["snapshot_id"]
            assert trigger.snapshot_version == at_risk.payload["snapshot_version"]
            assert trigger.commitment_version == 4
            assert trigger.assessment_commitment_version == 3
            assert trigger.assessment_provenance_status == "VERIFIED_AUTHORITATIVE"
            assert db.get(
                ProcessedEventRecord,
                (tenant_id, at_risk.event_id, "p3.recovery_trigger.v1"),
            ) is not None

            case_count = db.scalar(
                select(func.count()).select_from(RecoveryCaseRecord).where(
                    RecoveryCaseRecord.tenant_id == tenant_id,
                    RecoveryCaseRecord.commitment_id == commitment_id,
                )
            )
            trigger_count = db.scalar(
                select(func.count()).select_from(RecoveryCaseTriggerRecord).where(
                    RecoveryCaseTriggerRecord.tenant_id == tenant_id,
                    RecoveryCaseTriggerRecord.event_id == at_risk.event_id,
                )
            )

            # Redelivery remains idempotent after both subscribers have committed.
            confirmed = db.get(OutboxEventRecord, confirmed_event_id)
            confirmed.status = OutboxStatus.PENDING.value
            confirmed.published_at = None
            confirmed.next_retry_at = None
            at_risk.status = OutboxStatus.PENDING.value
            at_risk.published_at = None
            at_risk.next_retry_at = None
            db.commit()
            dispatcher.process_outbox_batch(db)
            assert db.scalar(
                select(func.count()).select_from(RecoveryCaseRecord).where(
                    RecoveryCaseRecord.tenant_id == tenant_id,
                    RecoveryCaseRecord.commitment_id == commitment_id,
                )
            ) == case_count == 1
            assert db.scalar(
                select(func.count()).select_from(RecoveryCaseTriggerRecord).where(
                    RecoveryCaseTriggerRecord.tenant_id == tenant_id,
                    RecoveryCaseTriggerRecord.event_id == at_risk.event_id,
                )
            ) == trigger_count == 1
            assert db.scalar(
                select(func.count()).select_from(ProcessedEventRecord).where(
                    ProcessedEventRecord.tenant_id == tenant_id,
                    ProcessedEventRecord.event_id == confirmed_event_id,
                    ProcessedEventRecord.consumer_name == "p2_confirmed_evaluator",
                )
            ) == 1
            assert db.scalar(
                select(func.count()).select_from(ProcessedEventRecord).where(
                    ProcessedEventRecord.tenant_id == tenant_id,
                    ProcessedEventRecord.event_id == at_risk.event_id,
                    ProcessedEventRecord.consumer_name == "p3.recovery_trigger.v1",
                )
            ) == 1
    finally:
        engine.dispose()


def test_stale_confirmed_event_is_not_discarded_without_p2_completion(monkeypatch) -> None:
    engine = _approved_engine()
    tenant_id = f"tenant_p2_stale_{uuid4().hex[:12]}"
    dispatcher = _configure_test_dispatcher(monkeypatch)
    try:
        with Session(engine) as db:
            commitment_id, event_id = _create_confirmed_commitment(db, tenant_id)
            current = db.get(CommitmentRecord, (tenant_id, commitment_id))
            current.commitment_version += 1
            db.commit()

            dispatcher.process_outbox_batch(db)
            stale = db.get(OutboxEventRecord, event_id)
            assert stale.status == OutboxStatus.FAILED.value
            assert stale.last_error == "STALE_MANDATORY_SUBSCRIBER_INCOMPLETE"
            assert db.get(
                ProcessedEventRecord,
                (tenant_id, event_id, "p2_confirmed_evaluator"),
            ) is None
            assert db.scalar(
                select(func.count()).select_from(AuditEventRecord).where(
                    AuditEventRecord.tenant_id == tenant_id,
                    AuditEventRecord.commitment_id == commitment_id,
                    AuditEventRecord.new_state["assessment_id"].as_string().is_not(None),
                )
            ) == 0
    finally:
        engine.dispose()
