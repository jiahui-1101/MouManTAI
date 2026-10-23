"""Real migrated PostgreSQL proof for the canonical P2 -> Core -> P3 path.

This module requires an explicitly approved disposable TEST_DATABASE_URL. It
does not create, migrate, reset, or drop databases or schemas.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Lock, Thread, current_thread
from time import monotonic, sleep
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event as sqlalchemy_event, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
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
    CommitmentTerms,
    ProposalConfirmRequest,
    ProposalCreateRequest,
)
from app.core.service import CommitmentService
from app.feasibility.persisted_sources import (
    OperationalSnapshotRecord,
    PersistedSupplierDelayProcessor,
    SupplierDelayEventRecord,
    stage_snapshot,
)
from app.feasibility.production import EvaluationSnapshot
from app.feasibility.production_fixtures import build_production_example
from app.recovery.persistence import RecoveryCaseRecord, RecoveryCaseTriggerRecord
from app.worker import configure_isolated_subscribers


pytestmark = pytest.mark.postgres


def _approved_engine():
    if os.getenv("REQUIRE_POSTGRES") != "1":
        pytest.skip("PostgreSQL NOT VERIFIED: REQUIRE_POSTGRES=1 is absent")
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


def _create_confirmed_commitment(
    db: Session,
    tenant_id: str,
    *,
    terms: CommitmentTerms | None = None,
    commitment_id: str | None = None,
) -> tuple[str, str]:
    _, base_commitment = build_production_example()
    commitment_terms = terms or base_commitment.terms
    commitment_id = commitment_id or f"com_p2_p3_{uuid4().hex[:12]}"
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
            terms=commitment_terms,
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
            revised_terms=commitment_terms,
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


def _supplier_delay_snapshots(
    tenant_id: str, commitment_id: str, commitment_version: int,
) -> tuple[EvaluationSnapshot, EvaluationSnapshot, CommitmentTerms, object]:
    """Create fresh persisted-source inputs around the real P2 delay fixture."""
    from app.feasibility.fixtures import build_supplier_delay_scenario
    from app.feasibility.models import SupplierDeliveryEvidenceType

    scenario = build_supplier_delay_scenario()
    production_template, core_commitment = build_production_example()
    captured_at = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=2)
    offset = captured_at - scenario.before.captured_at
    valid_through = captured_at + timedelta(days=7)

    def adapt(source, version: int, delta: timedelta) -> EvaluationSnapshot:
        def scope(value):
            if isinstance(value, dict):
                return {
                    key: tenant_id if key == "tenant_id" else scope(item)
                    for key, item in value.items()
                }
            if isinstance(value, (tuple, list)):
                return type(value)(scope(item) for item in value)
            return value

        data = scope(source.model_dump(mode="python", exclude_computed_fields=True))

        def shift(value):
            if isinstance(value, datetime):
                return value + delta
            if isinstance(value, dict):
                return {key: shift(item) for key, item in value.items()}
            if isinstance(value, (tuple, list)):
                return type(value)(shift(item) for item in value)
            return value

        data = shift(data)
        data["snapshot_id"] = f"p2-lock-{tenant_id}-v{version}"
        data["snapshot_version"] = version
        data["captured_at"] = source.captured_at + delta
        data["confirmed_commitments"] = list(data["confirmed_commitments"][:1])
        data["confirmed_commitments"][0]["commitment_id"] = commitment_id
        data["confirmed_commitments"][0]["commitment_version"] = commitment_version
        data["reservations"] = []
        # Match the explicit continuous-window assumption in
        # build_production_example(); the supplier-delay fixture's 480-minute
        # daily total intentionally leaves working breaks unlocated.
        for calendar in data["capacity_calendars"]:
            for window in calendar["windows"]:
                window["available_minutes"] = "600"
        for source_row in data["sources"]:
            source_row["source_ref"] = source_row["source_ref"].replace("synthetic://", "db://")
            source_row["valid_through"] = valid_through
            for claim in source_row["supplier_delivery_evidence"]:
                if claim["evidence_type"] == SupplierDeliveryEvidenceType.ETA_CHANGE.value:
                    claim["observed_at"] = data["captured_at"]
        production_data = scope(
            production_template.production.model_dump(mode="python", exclude_computed_fields=True)
        )
        production_data = shift(production_data)
        production_data["tenant_id"] = tenant_id
        for source_row in production_data["sources"]:
            source_row["source_ref"] = source_row["source_ref"].replace("synthetic://", "db://")
            source_row["valid_through"] = valid_through
        for plan in production_data["plans"]:
            plan["commitment_id"] = commitment_id
            plan["commitment_version"] = commitment_version
        return EvaluationSnapshot.model_validate({
            "operational": data,
            "production": production_data,
            "as_of": data["captured_at"],
            "current_snapshot_version": version,
        })

    before = adapt(scenario.before, 1, offset)
    after = adapt(scenario.after, 2, offset)
    source_commitment = before.operational.confirmed_commitments[0]
    source_line = source_commitment.lines[0]
    terms = CommitmentTerms.model_validate({
        **core_commitment.terms.model_dump(mode="python"),
        "sku": source_line.sku_id,
        "quantity": source_line.quantity,
        "unit": source_line.unit,
        "deadline": source_commitment.delivery_deadline,
    })
    eta_evidence = next(
        claim
        for source_row in after.operational.sources
        for claim in source_row.supplier_delivery_evidence
        if claim.evidence_type is SupplierDeliveryEvidenceType.ETA_CHANGE
        and claim.delivery_id == scenario.changed_delivery_id
    )
    return before, after, terms, eta_evidence


def _supplier_delay_request(tenant_id: str, before, after, eta_evidence):
    from app.feasibility.api_schemas import SupplierDelayRequest
    from app.feasibility.impact import (
        OperationalChange,
        OperationalChangeType,
        ResourceKey,
        ResourceKind,
    )

    change = OperationalChange(
        event_id=f"evt_supplier_lock_{uuid4().hex}",
        tenant_id=tenant_id,
        correlation_id=f"corr_supplier_lock_{uuid4().hex}",
        event_type=OperationalChangeType.SUPPLIER_DELIVERY_CHANGED,
        occurred_at=after.operational.captured_at,
        before_snapshot_version=before.operational.snapshot_version,
        after_snapshot_version=after.operational.snapshot_version,
        resource_keys=(ResourceKey(
            kind=ResourceKind.SUPPLIER_DELIVERY,
            resource_id=eta_evidence.delivery_id,
        ),),
        evidence_refs=(eta_evidence.evidence_ref,),
    )
    return SupplierDelayRequest(change=change, source_evidence=eta_evidence)


def _wait_for_database_lock_wait(engine, backend_pid: int, timeout_seconds: float = 10) -> list[int]:
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT wait_event_type, pg_blocking_pids(pid) "
                    "FROM pg_stat_activity WHERE pid = :pid"
                ),
                {"pid": backend_pid},
            ).first()
        if row is not None and row[0] == "Lock" and row[1]:
            return list(row[1])
        sleep(0.01)
    raise AssertionError(f"PostgreSQL backend {backend_pid} never entered a bounded row-lock wait")


@pytest.mark.parametrize("first_transaction", ["confirmed", "supplier"])
def test_postgresql_confirmed_assessment_and_supplier_promotion_share_lock_order(
    monkeypatch, first_transaction: str,
) -> None:
    """Exercise both transaction orderings with two real PostgreSQL Sessions."""
    engine = _approved_engine()
    tenant_id = f"tenant_p2_p3_lock_{uuid4().hex[:12]}"
    lock_context = RequestContext(
        tenant_id=tenant_id,
        actor_id="user_manager_01",
        actor_role="MANAGER",
        correlation_id=f"corr_supplier_lock_{uuid4().hex}",
    )
    dispatcher = _configure_test_dispatcher(monkeypatch)
    try:
        with Session(engine) as db:
            commitment_id = f"com_p2_p3_{uuid4().hex[:12]}"
            before, after, terms, eta_evidence = _supplier_delay_snapshots(
                tenant_id, commitment_id, 3,
            )
            commitment_id, confirmed_event_id = _create_confirmed_commitment(
                db, tenant_id, terms=terms, commitment_id=commitment_id,
            )
            stage_snapshot(db, before, current=True)
            stage_snapshot(db, after)
            db.commit()

        request = _supplier_delay_request(tenant_id, before, after, eta_evidence)
        supplier_started = Event()
        second_lock_attempted = Event()
        first_lock_acquired = Event()
        release_first = Event()
        event_guard = Lock()
        sequence_guard = Lock()
        lock_sequence: dict[str, list[str]] = {"confirmed": [], "supplier": []}
        paused_first = False
        backend_pids: dict[str, int] = {}
        results: dict[str, object] = {}
        failures: dict[str, BaseException] = {}

        def is_commitment_lock(statement: str) -> bool:
            lowered = statement.lower()
            return "for update" in lowered and "commitments" in lowered

        def is_snapshot_lock(statement: str) -> bool:
            lowered = statement.lower()
            return "for update" in lowered and "p2_operational_snapshots" in lowered

        def before_cursor_execute(connection, cursor, statement, parameters, context, executemany):
            name = current_thread().name
            if name != first_transaction and is_commitment_lock(statement):
                second_lock_attempted.set()

        def after_cursor_execute(connection, cursor, statement, parameters, context, executemany):
            nonlocal paused_first
            name = current_thread().name
            if name not in lock_sequence:
                return
            label = "commitment" if is_commitment_lock(statement) else (
                "snapshot" if is_snapshot_lock(statement) else None
            )
            if label is None:
                return
            with sequence_guard:
                lock_sequence[name].append(label)
            if name == first_transaction and label == "commitment":
                with event_guard:
                    should_pause = not paused_first
                    paused_first = True
                if should_pause:
                    first_lock_acquired.set()
                    if not release_first.wait(12):
                        raise TimeoutError("test did not release first transaction's Commitment lock")

        sqlalchemy_event.listen(engine, "before_cursor_execute", before_cursor_execute)
        sqlalchemy_event.listen(engine, "after_cursor_execute", after_cursor_execute)

        def confirmed_worker() -> None:
            try:
                with Session(engine) as db:
                    db.execute(text("SET LOCAL lock_timeout = '10s'"))
                    db.execute(text("SET LOCAL statement_timeout = '15s'"))
                    backend_pids["confirmed"] = db.scalar(text("SELECT pg_backend_pid()"))
                    results["confirmed"] = dispatcher.process_outbox_batch(db)
            except BaseException as exc:  # surfaced on the test thread after both joins
                failures["confirmed"] = exc

        def supplier_worker() -> None:
            try:
                with Session(engine) as db:
                    db.execute(text("SET LOCAL lock_timeout = '10s'"))
                    db.execute(text("SET LOCAL statement_timeout = '15s'"))
                    backend_pids["supplier"] = db.scalar(text("SELECT pg_backend_pid()"))
                    supplier_started.set()
                    results["supplier"] = PersistedSupplierDelayProcessor().process(
                        db, lock_context, request,
                    )
            except BaseException as exc:  # expected stale-version rejection is asserted below
                failures["supplier"] = exc

        confirmed_thread = Thread(target=confirmed_worker, name="confirmed", daemon=True)
        supplier_thread = Thread(target=supplier_worker, name="supplier", daemon=True)
        first_thread, second_thread = (
            (confirmed_thread, supplier_thread)
            if first_transaction == "confirmed"
            else (supplier_thread, confirmed_thread)
        )
        try:
            first_thread.start()
            assert first_lock_acquired.wait(10), "first transaction did not acquire its Commitment row lock"
            second_thread.start()
            if first_transaction == "supplier":
                assert supplier_started.wait(10), "supplier transaction did not start"
            assert second_lock_attempted.wait(10), "overlapping transaction did not attempt the Commitment lock"
            second_name = "supplier" if first_transaction == "confirmed" else "confirmed"
            blockers = _wait_for_database_lock_wait(engine, backend_pids[second_name])
            assert blockers, f"PostgreSQL did not report a lock blocker for {second_name}"
            release_first.set()
            first_thread.join(15)
            second_thread.join(15)
            assert not first_thread.is_alive(), f"{first_transaction} transaction hung after lock release"
            assert not second_thread.is_alive(), f"overlapping {second_name} transaction hung after lock release"
        finally:
            release_first.set()
            if first_thread.ident is not None:
                first_thread.join(15)
            if second_thread.ident is not None:
                second_thread.join(15)
            sqlalchemy_event.remove(engine, "before_cursor_execute", before_cursor_execute)
            sqlalchemy_event.remove(engine, "after_cursor_execute", after_cursor_execute)

        assert not failures.get("confirmed"), f"confirmed dispatcher failed: {failures.get('confirmed')}"
        assert lock_sequence["supplier"].index("commitment") < lock_sequence["supplier"].index("snapshot")
        if first_transaction == "confirmed":
            assert lock_sequence["confirmed"].index("commitment") < lock_sequence["confirmed"].index("snapshot")
        else:
            # The stale mandatory event must stop at Core version validation;
            # it must not resolve or assess a snapshot at the newer version.
            assert "commitment" in lock_sequence["confirmed"]
            assert "snapshot" not in lock_sequence["confirmed"]

        with Session(engine) as db:
            core = db.get(CommitmentRecord, (tenant_id, commitment_id))
            before_row = db.get(OperationalSnapshotRecord, (tenant_id, 1))
            after_row = db.get(OperationalSnapshotRecord, (tenant_id, 2))
            confirmed_event = db.get(OutboxEventRecord, confirmed_event_id)
            assert core is not None and before_row is not None and after_row is not None
            assert core.commitment_version == 4

            if first_transaction == "confirmed":
                assert "confirmed" in results
                assert isinstance(failures.get("supplier"), DomainError)
                assert failures["supplier"].code == "COMMITMENT_VERSION_CONFLICT"
                assert core.feasibility_state == "FEASIBLE" and core.risk_state == "NORMAL"
                assert before_row.is_current is True and after_row.is_current is False
                assert confirmed_event.status == OutboxStatus.PUBLISHED.value
                assert db.get(
                    ProcessedEventRecord,
                    (tenant_id, confirmed_event_id, "p2_confirmed_evaluator"),
                ) is not None
                assert db.scalar(select(func.count()).select_from(SupplierDelayEventRecord).where(
                    SupplierDelayEventRecord.tenant_id == tenant_id,
                )) == 0
                assert db.get(OutboxEventRecord, request.change.event_id) is None
                expected_risk_count = 0
            else:
                assert "supplier" in results
                assert "supplier" not in failures
                assert core.feasibility_state == "INFEASIBLE" and core.risk_state == "AT_RISK"
                assert before_row.is_current is False and after_row.is_current is True
                assert confirmed_event.status == OutboxStatus.FAILED.value
                assert confirmed_event.last_error.startswith("DomainError:")
                assert db.get(
                    ProcessedEventRecord,
                    (tenant_id, confirmed_event_id, "p2_confirmed_evaluator"),
                ) is None
                assert db.scalar(select(func.count()).select_from(SupplierDelayEventRecord).where(
                    SupplierDelayEventRecord.tenant_id == tenant_id,
                )) == 1
                expected_risk_count = 1

            risk_events = db.scalars(select(OutboxEventRecord).where(
                OutboxEventRecord.tenant_id == tenant_id,
                OutboxEventRecord.event_type == CoreEventType.COMMITMENT_AT_RISK.value,
            )).all()
            assert len(risk_events) == expected_risk_count
            assessment_audits = db.scalars(select(AuditEventRecord).where(
                AuditEventRecord.tenant_id == tenant_id,
                AuditEventRecord.new_state["assessment_id"].as_string().is_not(None),
            )).all()
            assert len(assessment_audits) == 1
            assessment_audit = assessment_audits[0]
            expected_snapshot = before if first_transaction == "confirmed" else after
            assert assessment_audit.new_state["snapshot_id"] == expected_snapshot.operational.snapshot_id
            assert assessment_audit.new_state["snapshot_version"] == expected_snapshot.operational.snapshot_version
            assert assessment_audit.new_state["assessment_commitment_version"] == 3
            if risk_events:
                assert assessment_audit.causation_id == request.change.event_id
                dispatcher.process_outbox_batch(db)
                trigger_count = db.scalar(select(func.count()).select_from(RecoveryCaseTriggerRecord).where(
                    RecoveryCaseTriggerRecord.tenant_id == tenant_id,
                    RecoveryCaseTriggerRecord.event_id == risk_events[0].event_id,
                ))
                case_count = db.scalar(select(func.count()).select_from(RecoveryCaseRecord).where(
                    RecoveryCaseRecord.tenant_id == tenant_id,
                    RecoveryCaseRecord.commitment_id == commitment_id,
                ))
                assert trigger_count == 1 and case_count == 1
            else:
                assert db.scalar(select(func.count()).select_from(RecoveryCaseTriggerRecord).where(
                    RecoveryCaseTriggerRecord.tenant_id == tenant_id,
                )) == 0
                assert db.scalar(select(func.count()).select_from(RecoveryCaseRecord).where(
                    RecoveryCaseRecord.tenant_id == tenant_id,
                    RecoveryCaseRecord.commitment_id == commitment_id,
                )) == 0

            # Redeliver each required event. A completed P2 evaluation is skipped;
            # an uncompleted stale mandatory event remains visible as failed.
            confirmed_event.status = OutboxStatus.PENDING.value
            confirmed_event.published_at = None
            confirmed_event.next_retry_at = None
            if risk_events:
                risk_events[0].status = OutboxStatus.PENDING.value
                risk_events[0].published_at = None
                risk_events[0].next_retry_at = None
            db.commit()
            db.expire_all()
            dispatcher.process_outbox_batch(db)
            db.expire_all()

            assert db.scalar(select(func.count()).select_from(RecoveryCaseTriggerRecord).where(
                RecoveryCaseTriggerRecord.tenant_id == tenant_id,
            )) == expected_risk_count
            assert db.scalar(select(func.count()).select_from(RecoveryCaseRecord).where(
                RecoveryCaseRecord.tenant_id == tenant_id,
                RecoveryCaseRecord.commitment_id == commitment_id,
            )) == expected_risk_count
            final_confirmed = db.get(OutboxEventRecord, confirmed_event_id)
            if first_transaction == "supplier":
                assert final_confirmed.status == OutboxStatus.FAILED.value
                assert final_confirmed.last_error == "STALE_MANDATORY_SUBSCRIBER_INCOMPLETE"
                assert final_confirmed.attempts >= 2
            else:
                assert db.get(
                    ProcessedEventRecord,
                    (tenant_id, confirmed_event_id, "p2_confirmed_evaluator"),
                ) is not None
    finally:
        engine.dispose()
