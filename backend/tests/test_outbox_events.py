from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.events import (
    CoreEventType,
    OutboxStatus,
    create_domain_event,
    validate_event_payload,
)
from app.core.models import (
    AuditEventRecord,
    CommitmentRecord,
    OutboxEventRecord,
    ProcessedEventRecord,
)
from app.core.outbox import (
    OutboxDispatcher,
    is_stale_event,
    requeue_dead_letter,
    to_domain_event,
)
from app.core.schemas import (
    CommitmentCreateRequest,
    CommitmentTerms,
    CommitmentTransitionRequest,
    DomainEvent,
    FeasibilityAssessment,
    FeasibilityState,
)
from app.core.service import CommitmentService
from app.db.base import Base


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture
def service() -> CommitmentService:
    return CommitmentService()


def _manager_context(
    tenant_id: str = "tenant_test",
    correlation_id: str = "corr_test_001",
    causation_id: str | None = None,
) -> RequestContext:
    return RequestContext(
        tenant_id=tenant_id,
        actor_id="user_manager_01",
        actor_role="MANAGER",
        correlation_id=correlation_id,
        causation_id=causation_id,
    )


def _create_sample_commitment(
    service: CommitmentService,
    session: Session,
    context: RequestContext,
) -> str:
    now = datetime.now(timezone.utc)
    request = CommitmentCreateRequest(
        order_id="ord_test_001",
        customer_id="cust_test_001",
        terms=CommitmentTerms(
            sku="BURGER",
            quantity=Decimal("50"),
            unit="pcs",
            deadline=now,
        ),
        evidence_refs=["ev_test_request_001"],
    )
    commitment = service.create_request(session, context, request)
    return commitment.commitment_id


def test_event_envelope_validation() -> None:
    """Ensure DomainEvent envelope validates required fields and rejects secrets (BE-04a)."""
    # Valid envelope
    event = create_domain_event(
        event_type=CoreEventType.COMMITMENT_CREATED.value,
        tenant_id="tenant_01",
        correlation_id="corr_01",
        commitment_id="com_01",
        commitment_version=1,
        causation_id="cause_01",
        payload={"commitment_id": "com_01", "sku": "BURGER"},
    )
    assert event.event_id.startswith("evt_")
    assert event.schema_version == 1
    assert event.event_type == "commitment.created"
    assert event.tenant_id == "tenant_01"
    assert event.correlation_id == "corr_01"
    assert event.causation_id == "cause_01"
    assert event.occurred_at.tzinfo is not None

    # Forbidden sensitive keywords in payload are rejected
    with pytest.raises(ValueError, match="forbidden sensitive keyword 'api_key'"):
        validate_event_payload({"api_key": "secret_12345"})

    with pytest.raises(ValueError, match="forbidden sensitive keyword 'password'"):
        validate_event_payload({"meta": {"user_password": "plain"}})


def test_core_event_types_defined() -> None:
    """Ensure all required core domain event types are defined (BE-04a)."""
    expected_types = {
        "commitment.created",
        "commitment.proposal_offered",
        "commitment.confirmed",
        "commitment.at_risk",
        "commitment.risk_resolved",
        "commitment.fulfilment_verified",
        "audit.recorded",
    }
    defined_values = {e.value for e in CoreEventType}
    assert expected_types.issubset(defined_values)


def test_outbox_atomic_with_state_change(service: CommitmentService, db_session: Session) -> None:
    """State transition writes outbox_events in same transaction; offline publisher leaves PENDING (SAF-2, UT-07)."""
    context = _manager_context()
    commitment_id = _create_sample_commitment(service, db_session, context)

    # Initial creation wrote outbox in same transaction
    outbox_initial = db_session.scalars(
        select(OutboxEventRecord).where(OutboxEventRecord.commitment_id == commitment_id)
    ).all()
    assert len(outbox_initial) == 1
    assert outbox_initial[0].status == OutboxStatus.PENDING.value
    assert outbox_initial[0].attempts == 0
    assert outbox_initial[0].published_at is None
    assert outbox_initial[0].event_type == CoreEventType.COMMITMENT_CREATED.value

    # State transition to OFFERED
    transition_resp = service.transition(
        db_session,
        context,
        commitment_id,
        CommitmentTransitionRequest(
            dimension="agreement",
            target_state="OFFERED",
            expected_commitment_version=1,
            reason="Offer prepared for customer",
        ),
    )
    assert transition_resp.commitment.commitment_version == 2

    # Verify outbox row for OFFERED was committed in the same transaction
    outbox_rows = db_session.scalars(
        select(OutboxEventRecord)
        .where(OutboxEventRecord.commitment_id == commitment_id)
        .order_by(OutboxEventRecord.occurred_at.asc())
    ).all()
    assert len(outbox_rows) == 2
    second_event = outbox_rows[1]
    assert second_event.status == OutboxStatus.PENDING.value
    assert second_event.attempts == 0
    assert second_event.event_type == CoreEventType.COMMITMENT_PROPOSAL_OFFERED.value
    assert second_event.commitment_version == 2

    # Simulated publisher offline / failure: the committed outbox row remains safely stored as PENDING
    assert second_event.status == OutboxStatus.PENDING.value
    assert db_session.get(CommitmentRecord, (context.tenant_id, commitment_id)).commitment_version == 2


def test_duplicate_event_idempotency(db_session: Session) -> None:
    """Delivering the same event_id twice results in exactly one mutation and one audit record (BE-04c, UT-06)."""
    dispatcher = OutboxDispatcher()
    now = datetime.now(timezone.utc)
    event = DomainEvent(
        event_id="evt_duplicate_001",
        schema_version=1,
        event_type="commitment.confirmed",
        tenant_id="tenant_idempotent",
        commitment_id="com_idem_001",
        commitment_version=2,
        correlation_id="corr_idem_001",
        occurred_at=now,
        payload={"sku": "BURGER"},
    )

    execution_count = 0
    audit_records_created = 0

    def mock_subscriber(session: Session, evt: DomainEvent) -> None:
        nonlocal execution_count, audit_records_created
        execution_count += 1
        # Write an audit row as part of the consumer's action
        audit = AuditEventRecord(
            audit_id=f"aud_{evt.event_id}_{execution_count}",
            tenant_id=evt.tenant_id,
            commitment_id=evt.commitment_id or "com_none",
            event_type=evt.event_type,
            actor_id="consumer_worker",
            actor_role="SYSTEM",
            dimension="agreement",
            new_state={"confirmed": True},
            evidence_refs=["ev_001"],
            reason="Confirmed by consumer",
            correlation_id=evt.correlation_id,
            occurred_at=datetime.now(timezone.utc),
        )
        session.add(audit)
        audit_records_created += 1

    consumer_name = "test_confirmation_consumer"

    # First delivery: executes consumer
    first_run = dispatcher.execute_consumer(db_session, event, consumer_name, mock_subscriber)
    assert first_run is True
    assert execution_count == 1
    assert audit_records_created == 1

    # Verify processed_events recorded
    processed = db_session.scalar(
        select(ProcessedEventRecord).where(
            ProcessedEventRecord.tenant_id == event.tenant_id,
            ProcessedEventRecord.event_id == event.event_id,
            ProcessedEventRecord.consumer_name == consumer_name,
        )
    )
    assert processed is not None

    # Second delivery with identical event_id: idempotent skip cleanly
    second_run = dispatcher.execute_consumer(db_session, event, consumer_name, mock_subscriber)
    assert second_run is False
    assert execution_count == 1  # No duplicate execution
    assert audit_records_created == 1  # No duplicate audit record

    # Total audit rows in DB for this event is still 1
    audits = db_session.scalars(
        select(AuditEventRecord).where(AuditEventRecord.correlation_id == event.correlation_id)
    ).all()
    assert len(audits) == 1


def test_out_of_order_event_ignored(service: CommitmentService, db_session: Session) -> None:
    """Event with commitment_version=1 arriving after commitment is at version=2 does not revert state (BE-04d, UT-04)."""
    context = _manager_context()
    commitment_id = _create_sample_commitment(service, db_session, context)

    # Transition to version 2 (OFFERED)
    service.transition(
        db_session,
        context,
        commitment_id,
        CommitmentTransitionRequest(
            dimension="agreement",
            target_state="OFFERED",
            expected_commitment_version=1,
            reason="Proposal offered",
        ),
    )
    current_record = db_session.get(CommitmentRecord, (context.tenant_id, commitment_id))
    assert current_record.commitment_version == 2
    assert current_record.agreement_state == "OFFERED"

    # Now create an out-of-order event carrying stale commitment_version=1
    stale_event = DomainEvent(
        event_id="evt_stale_delayed_001",
        schema_version=1,
        event_type="commitment.proposal_offered",
        tenant_id=context.tenant_id,
        commitment_id=commitment_id,
        commitment_version=1,  # Stale version!
        correlation_id="corr_stale_001",
        occurred_at=datetime.now(timezone.utc),
        payload={"target_state": "CANCELLED"},
    )

    # Verify is_stale_event detects it as stale
    assert is_stale_event(db_session, stale_event) is True

    # Simulate consumer guarded with is_stale_event
    state_mutated = False

    def consumer_with_guard(session: Session, evt: DomainEvent) -> None:
        nonlocal state_mutated
        if is_stale_event(session, evt):
            return  # Ignored out-of-order stale event
        # If not guarded, it would erroneously overwrite state
        rec = session.get(CommitmentRecord, (evt.tenant_id, evt.commitment_id))
        rec.agreement_state = "CANCELLED"
        rec.commitment_version = evt.commitment_version
        state_mutated = True

    dispatcher = OutboxDispatcher()
    dispatcher.execute_consumer(db_session, stale_event, "version_guard_consumer", consumer_with_guard)

    assert state_mutated is False
    # Verify commitment in DB is preserved untouched
    refreshed = db_session.get(CommitmentRecord, (context.tenant_id, commitment_id))
    assert refreshed.commitment_version == 2
    assert refreshed.agreement_state == "OFFERED"

    # In-order event with matching version is NOT stale
    current_event = DomainEvent(
        event_id="evt_current_002",
        schema_version=1,
        event_type="commitment.confirmed",
        tenant_id=context.tenant_id,
        commitment_id=commitment_id,
        commitment_version=2,  # Current version
        correlation_id="corr_valid_002",
        occurred_at=datetime.now(timezone.utc),
        payload={},
    )
    assert is_stale_event(db_session, current_event) is False


def test_outbox_retry_and_dead_letter(db_session: Session) -> None:
    """Failing subscriber increments attempts, records error, moves to DEAD_LETTER, and succeeds after requeue (BE-04b, UT-07)."""
    dispatcher = OutboxDispatcher()
    now = datetime.now(timezone.utc)
    event_id = "evt_retry_test_001"
    tenant_id = "tenant_retry"

    # Add an outbox event to DB
    outbox_record = OutboxEventRecord(
        event_id=event_id,
        tenant_id=tenant_id,
        event_type="test.transient_failure",
        commitment_id="com_retry_001",
        commitment_version=1,
        correlation_id="corr_retry_001",
        occurred_at=now,
        payload={"sku": "BURGER"},
        attempts=0,
        status=OutboxStatus.PENDING.value,
    )
    db_session.add(outbox_record)
    db_session.commit()

    should_fail = True

    def flaky_subscriber(session: Session, evt: DomainEvent) -> None:
        if should_fail:
            raise RuntimeError("Simulated transient connection timeout")

    dispatcher.register_subscriber("test.transient_failure", "flaky_worker", flaky_subscriber)

    # Batch 1: attempt 1 -> status FAILED, attempts 1
    res1 = dispatcher.process_outbox_batch(db_session, max_attempts=3, backoff_base_seconds=1.0)
    assert res1.failed_count == 1
    rec = db_session.get(OutboxEventRecord, event_id)
    assert rec.attempts == 1
    assert rec.status == OutboxStatus.FAILED.value
    assert "RuntimeError: Simulated transient connection timeout" in rec.last_error
    assert rec.next_retry_at is not None

    # Simulate next retry time reached
    rec.next_retry_at = datetime.now(timezone.utc)
    db_session.commit()

    # Batch 2: attempt 2 -> status FAILED, attempts 2
    res2 = dispatcher.process_outbox_batch(db_session, max_attempts=3, backoff_base_seconds=1.0)
    assert res2.failed_count == 1
    rec = db_session.get(OutboxEventRecord, event_id)
    assert rec.attempts == 2
    assert rec.status == OutboxStatus.FAILED.value

    # Simulate next retry time reached
    rec.next_retry_at = datetime.now(timezone.utc)
    db_session.commit()

    # Batch 3: attempt 3 reaches max_attempts (3) -> moves to DEAD_LETTER
    res3 = dispatcher.process_outbox_batch(db_session, max_attempts=3, backoff_base_seconds=1.0)
    assert res3.dead_letter_count == 1
    rec = db_session.get(OutboxEventRecord, event_id)
    assert rec.attempts == 3
    assert rec.status == OutboxStatus.DEAD_LETTER.value
    assert rec.next_retry_at is None

    # Normal worker polling ignores DEAD_LETTER
    res4 = dispatcher.process_outbox_batch(db_session, max_attempts=3)
    assert res4.processed_count == 0

    # Reconciliation: transient issue resolved, administrator requeues dead letter
    should_fail = False
    requeued = dispatcher.requeue_dead_letter(db_session, event_id)
    assert requeued.status == OutboxStatus.PENDING.value
    assert requeued.attempts == 0
    assert requeued.last_error is None

    # Next batch successfully publishes the event
    res5 = dispatcher.process_outbox_batch(db_session, max_attempts=3)
    assert res5.published_count == 1
    rec = db_session.get(OutboxEventRecord, event_id)
    assert rec.status == OutboxStatus.PUBLISHED.value
    assert rec.published_at is not None


def test_requeue_nonexistent_event_raises_not_found(db_session: Session) -> None:
    """requeue_dead_letter raises 404 DomainError when event_id does not exist."""
    with pytest.raises(DomainError) as exc_info:
        requeue_dead_letter(db_session, "evt_does_not_exist")
    assert exc_info.value.code == "EVENT_NOT_FOUND"
    assert exc_info.value.status_code == 404


def test_correlation_and_causation_chain(service: CommitmentService, db_session: Session) -> None:
    """Trigger event evt_supplier_delay with corr_001 propagates correlation and causation across core events (BE-04f)."""
    trigger_event = create_domain_event(
        event_type="supplier.delay_detected",
        tenant_id="tenant_chain",
        correlation_id="corr_001",
        event_id="evt_supplier_delay",
        payload={"sku": "BURGER", "delay_hours": 24},
    )
    assert trigger_event.event_id == "evt_supplier_delay"
    assert trigger_event.correlation_id == "corr_001"

    context = RequestContext(
        tenant_id=trigger_event.tenant_id,
        actor_id="user_manager_01",
        actor_role="MANAGER",
        correlation_id=trigger_event.correlation_id,
        causation_id=trigger_event.event_id,
    )
    commitment_id = _create_sample_commitment(service, db_session, context)

    # State transition to AT_RISK caused by the supplier delay
    resp = service.transition(
        db_session,
        context,
        commitment_id,
        CommitmentTransitionRequest(
            dimension="risk",
            target_state="AT_RISK",
            expected_commitment_version=1,
            reason="Supplier delay reported",
            causation_id=trigger_event.event_id,
        ),
    )

    # Assert downstream DomainEvent preserved both IDs
    downstream_event = resp.domain_event
    assert downstream_event.correlation_id == "corr_001"
    assert downstream_event.causation_id == "evt_supplier_delay"
    assert downstream_event.event_type == CoreEventType.COMMITMENT_AT_RISK.value

    # Assert downstream AuditEvent preserved both IDs
    downstream_audit = resp.audit_event
    assert downstream_audit.correlation_id == "corr_001"
    assert downstream_audit.causation_id == "evt_supplier_delay"

    # Assert DB records in outbox_events and audit_events have both IDs
    db_outbox = db_session.get(OutboxEventRecord, downstream_event.event_id)
    assert db_outbox is not None
    assert db_outbox.correlation_id == "corr_001"
    assert db_outbox.causation_id == "evt_supplier_delay"

    db_audit = db_session.get(AuditEventRecord, downstream_audit.audit_id)
    assert db_audit is not None
    assert db_audit.correlation_id == "corr_001"
    assert db_audit.causation_id == "evt_supplier_delay"


def test_caller_owned_transaction_consumer_failure_and_atomic_rollback(
    service: CommitmentService,
    db_session: Session,
) -> None:
    """A consumer failure after Core mutation rolls back everything; re-delivery succeeds without duplicate (D-032, R26/R36/R55)."""
    dispatcher = OutboxDispatcher()
    now = datetime.now(timezone.utc)
    tenant_id = "tenant_tx_test"
    commitment_id = "com_tx_001"

    # Seed confirmed commitment
    record = CommitmentRecord(
        tenant_id=tenant_id,
        commitment_id=commitment_id,
        order_id="ord_tx_001",
        customer_id="cust_tx_001",
        terms={"sku": "BURGER", "quantity": "100", "unit": "pcs", "deadline": now.isoformat()},
        agreement_state="CONFIRMED",
        feasibility_state="NOT_ASSESSED",
        risk_state="NORMAL",
        recovery_state="NONE",
        fulfilment_state="NOT_STARTED",
        commitment_version=1,
        evidence_refs=["ev_conf_001"],
        updated_at=now,
    )
    event_record = OutboxEventRecord(
        event_id="evt_tx_consumer_001",
        tenant_id=tenant_id,
        event_type="commitment.confirmed",
        commitment_id=commitment_id,
        commitment_version=1,
        correlation_id="corr_tx_001",
        occurred_at=now,
        payload={"commitment_id": commitment_id},
        attempts=0,
        status=OutboxStatus.PENDING.value,
    )
    db_session.add_all([record, event_record])
    db_session.commit()

    service_ctx = RequestContext(
        tenant_id=tenant_id,
        actor_id="service_p2_worker",
        actor_role="SERVICE",
        correlation_id="corr_tx_001",
    )

    should_fail = True
    assessments_executed = 0

    def consumer_handler(session: Session, evt: DomainEvent) -> None:
        nonlocal assessments_executed
        assessments_executed += 1
        fa = FeasibilityAssessment(
            assessment_id="fa_tx_001",
            tenant_id=tenant_id,
            commitment_id=commitment_id,
            commitment_version=1,
            snapshot_version=1,
            status=FeasibilityState.INFEASIBLE,
            constraints=[],
            affected_commitment_ids=[],
            solver_status="COMPLETED",
            assessed_at=datetime.now(timezone.utc),
        )
        # Caller-owned transaction semantics: commit=False
        service.assess(session, service_ctx, commitment_id, fa, commit=False)

        if should_fail:
            raise RuntimeError("Downstream storage failure after Core assess mutation")

    # Register subscriber as required by D-017
    dispatcher.register_subscriber("commitment.confirmed", "p2_confirmed_evaluator", consumer_handler)

    # First attempt: handler raises after Core mutation
    result1 = dispatcher.process_outbox_batch(db_session, max_attempts=3, backoff_base_seconds=1.0)
    assert result1.failed_count == 1
    assert assessments_executed == 1

    # Verify atomic rollback: CommitmentRecord is completely unchanged
    refreshed_rec = db_session.get(CommitmentRecord, (tenant_id, commitment_id))
    assert refreshed_rec.commitment_version == 1
    assert refreshed_rec.feasibility_state == "NOT_ASSESSED"
    assert refreshed_rec.risk_state == "NORMAL"
    assert refreshed_rec.recovery_state == "NONE"

    # Verify atomic rollback: No audit records or new outbox records were committed for the assessment
    audits = db_session.scalars(
        select(AuditEventRecord).where(
            AuditEventRecord.tenant_id == tenant_id,
            AuditEventRecord.commitment_id == commitment_id,
        )
    ).all()
    assert len(audits) == 0

    # Verify atomic rollback: No ProcessedEventRecord was committed
    processed = db_session.scalar(
        select(ProcessedEventRecord).where(
            ProcessedEventRecord.tenant_id == tenant_id,
            ProcessedEventRecord.event_id == "evt_tx_consumer_001",
        )
    )
    assert processed is None

    # Event remains FAILED with retry schedule, not published
    outbox_rec = db_session.get(OutboxEventRecord, "evt_tx_consumer_001")
    assert outbox_rec.status == OutboxStatus.FAILED.value
    assert outbox_rec.attempts == 1

    # Re-delivery: downstream issue resolved
    should_fail = False
    outbox_rec.next_retry_at = datetime.now(timezone.utc)
    db_session.commit()

    result2 = dispatcher.process_outbox_batch(db_session, max_attempts=3)
    assert result2.published_count == 1
    assert assessments_executed == 2

    # Verification: now mutations are committed atomically
    refreshed_rec = db_session.get(CommitmentRecord, (tenant_id, commitment_id))
    assert refreshed_rec.commitment_version == 2
    assert refreshed_rec.feasibility_state == "INFEASIBLE"
    assert refreshed_rec.risk_state == "AT_RISK"
    assert refreshed_rec.recovery_state == "RECOVERY_REQUIRED"

    # Verification: ProcessedEventRecord is now recorded
    processed = db_session.scalar(
        select(ProcessedEventRecord).where(
            ProcessedEventRecord.tenant_id == tenant_id,
            ProcessedEventRecord.event_id == "evt_tx_consumer_001",
        )
    )
    assert processed is not None

    # Register p3 subscriber for the downstream commitment.at_risk event emitted by assess()
    p3_executed = 0
    def p3_handler(session: Session, evt: DomainEvent) -> None:
        nonlocal p3_executed
        p3_executed += 1

    dispatcher.register_subscriber("commitment.at_risk", "p3.recovery_trigger.v1", p3_handler)

    # Verification: Next batch processes the downstream at_risk event cleanly
    result3 = dispatcher.process_outbox_batch(db_session)
    assert result3.published_count == 1
    assert p3_executed == 1
    assert assessments_executed == 2  # p2 consumer was not re-executed

    # Verification: Now all events are published, no more pending events
    result4 = dispatcher.process_outbox_batch(db_session)
    assert result4.processed_count == 0


def test_d017_mandatory_subscriber_policy_for_confirmed_and_at_risk(db_session: Session) -> None:
    """D-017 required subscriber enforcement for commitment.confirmed and commitment.at_risk."""
    dispatcher = OutboxDispatcher()
    now = datetime.now(timezone.utc)
    tenant_id = "tenant_d017"
    com_id = "com_d017_001"

    rec = CommitmentRecord(
        tenant_id=tenant_id,
        commitment_id=com_id,
        order_id="ord_d017",
        customer_id="cust_d017",
        terms={"sku": "BURGER", "quantity": "50", "unit": "pcs", "deadline": now.isoformat()},
        agreement_state="CONFIRMED",
        feasibility_state="NOT_ASSESSED",
        risk_state="NORMAL",
        recovery_state="NONE",
        fulfilment_state="NOT_STARTED",
        commitment_version=1,
        evidence_refs=["ev_d017"],
        updated_at=now,
    )
    evt_confirmed = OutboxEventRecord(
        event_id="evt_d017_conf",
        tenant_id=tenant_id,
        event_type="commitment.confirmed",
        commitment_id=com_id,
        commitment_version=1,
        correlation_id="corr_d017_1",
        occurred_at=now,
        payload={"commitment_id": com_id},
        attempts=0,
        status=OutboxStatus.PENDING.value,
    )
    evt_at_risk = OutboxEventRecord(
        event_id="evt_d017_risk",
        tenant_id=tenant_id,
        event_type="commitment.at_risk",
        commitment_id=com_id,
        commitment_version=1,
        correlation_id="corr_d017_2",
        occurred_at=now,
        payload={"commitment_id": com_id},
        attempts=0,
        status=OutboxStatus.PENDING.value,
    )
    db_session.add_all([rec, evt_confirmed, evt_at_risk])
    db_session.commit()

    # 1. No subscribers registered: both events stay PENDING and are NOT published prematurely
    res = dispatcher.process_outbox_batch(db_session)
    assert res.published_count == 0
    assert db_session.get(OutboxEventRecord, "evt_d017_conf").status == OutboxStatus.PENDING.value
    assert db_session.get(OutboxEventRecord, "evt_d017_risk").status == OutboxStatus.PENDING.value

    # 2. Wildcard subscriber registered: required named subscriber still missing -> still PENDING
    dispatcher.register_subscriber("*", "wildcard_logger", lambda s, e: None)
    res_wildcard = dispatcher.process_outbox_batch(db_session)
    assert res_wildcard.published_count == 0
    assert db_session.get(OutboxEventRecord, "evt_d017_conf").status == OutboxStatus.PENDING.value
    assert db_session.get(OutboxEventRecord, "evt_d017_risk").status == OutboxStatus.PENDING.value

    # 3. Register specifically named mandatory subscribers
    called_p2 = False
    called_p3 = False

    def p2_handler(session: Session, event: DomainEvent) -> None:
        nonlocal called_p2
        called_p2 = True

    def p3_handler(session: Session, event: DomainEvent) -> None:
        nonlocal called_p3
        called_p3 = True

    dispatcher.register_subscriber("commitment.confirmed", "p2_confirmed_evaluator", p2_handler)
    dispatcher.register_subscriber("commitment.at_risk", "p3.recovery_trigger.v1", p3_handler)

    res_valid = dispatcher.process_outbox_batch(db_session)
    assert res_valid.published_count == 2
    assert called_p2 is True
    assert called_p3 is True
    assert db_session.get(OutboxEventRecord, "evt_d017_conf").status == OutboxStatus.PUBLISHED.value
    assert db_session.get(OutboxEventRecord, "evt_d017_risk").status == OutboxStatus.PUBLISHED.value

    # 4. A stale mandatory event cannot be published before its named subscriber completes.
    rec.commitment_version = 2
    stale_event = OutboxEventRecord(
        event_id="evt_d017_stale",
        tenant_id=tenant_id,
        event_type="commitment.confirmed",
        commitment_id=com_id,
        commitment_version=1,  # Stale!
        correlation_id="corr_d017_stale",
        occurred_at=now,
        payload={"commitment_id": com_id},
        attempts=0,
        status=OutboxStatus.PENDING.value,
    )
    db_session.add(stale_event)
    db_session.commit()

    called_p2 = False
    res_stale = dispatcher.process_outbox_batch(db_session)
    assert res_stale.published_count == 0
    assert res_stale.failed_count == 1
    assert called_p2 is False
    stale_record = db_session.get(OutboxEventRecord, "evt_d017_stale")
    assert stale_record.status == OutboxStatus.FAILED.value
    assert stale_record.last_error == "STALE_MANDATORY_SUBSCRIBER_INCOMPLETE"

    reconciled: list[str] = []

    def reconcile_without_reapplying_state(session: Session, event: DomainEvent) -> None:
        reconciled.append(event.event_id)

    stale_domain_event = to_domain_event(stale_event)
    assert dispatcher.execute_consumer(
        db_session, stale_domain_event, "p2_confirmed_evaluator", reconcile_without_reapplying_state
    ) is True
    assert dispatcher.execute_consumer(
        db_session, stale_domain_event, "p2_confirmed_evaluator", reconcile_without_reapplying_state
    ) is False
    assert reconciled == [stale_event.event_id]

    stale_record.next_retry_at = now - timedelta(seconds=1)
    db_session.commit()
    res_reconciled = dispatcher.process_outbox_batch(db_session)
    assert res_reconciled.published_count == 1
    assert db_session.get(OutboxEventRecord, "evt_d017_stale").status == OutboxStatus.PUBLISHED.value

    # Verify explicit supersession audit record was written
    audit_sup = db_session.scalar(
        select(AuditEventRecord).where(
            AuditEventRecord.tenant_id == tenant_id,
            AuditEventRecord.commitment_id == com_id,
            AuditEventRecord.event_type == "commitment.event_superseded",
        )
    )
    assert audit_sup is not None
    assert audit_sup.new_state.get("superseded") is True
    assert audit_sup.new_state.get("current_commitment_version") == 2


def test_advisory_assessments_append_only_and_never_mutate_aggregate(
    service: CommitmentService,
    db_session: Session,
) -> None:
    """Advisory assessments are append-only, do not mutate aggregate, and do not satisfy authoritative idempotency (D-033)."""
    now = datetime.now(timezone.utc)
    tenant_id = "tenant_adv_test"
    com_id = "com_adv_001"

    rec = CommitmentRecord(
        tenant_id=tenant_id,
        commitment_id=com_id,
        order_id="ord_adv_001",
        customer_id="cust_adv_001",
        terms={"sku": "BURGER", "quantity": "100", "unit": "pcs", "deadline": now.isoformat()},
        agreement_state="CONFIRMED",
        feasibility_state="NOT_ASSESSED",
        risk_state="NORMAL",
        recovery_state="NONE",
        fulfilment_state="NOT_STARTED",
        commitment_version=1,
        evidence_refs=["ev_adv_orig"],
        updated_at=now,
    )
    db_session.add(rec)
    db_session.commit()

    service_ctx = RequestContext(
        tenant_id=tenant_id,
        actor_id="service_p2_evaluator",
        actor_role="SERVICE",
        correlation_id="corr_adv_001",
    )

    advisory_fa = FeasibilityAssessment(
        assessment_id="fa_advisory_001",
        tenant_id=tenant_id,
        commitment_id=com_id,
        commitment_version=1,
        snapshot_version=1,
        status=FeasibilityState.INFEASIBLE,
        constraints=[],
        affected_commitment_ids=[],
        solver_status="COMPLETED",
        assessed_at=now,
    )

    # Record advisory assessment
    audit_event = service.record_advisory_assessment(db_session, service_ctx, advisory_fa)
    assert audit_event.event_type == "commitment.advisory_feasibility_assessed"
    assert audit_event.dimension == "feasibility"
    assert audit_event.new_state.get("advisory") is True
    assert audit_event.new_state.get("status") == "INFEASIBLE"

    # Invariant: Aggregate record is completely untouched!
    refreshed = db_session.get(CommitmentRecord, (tenant_id, com_id))
    assert refreshed.commitment_version == 1
    assert refreshed.agreement_state == "CONFIRMED"
    assert refreshed.feasibility_state == "NOT_ASSESSED"
    assert refreshed.risk_state == "NORMAL"  # NOT moved to AT_RISK despite advisory INFEASIBLE!
    assert refreshed.recovery_state == "NONE"
    assert refreshed.evidence_refs == ["ev_adv_orig"]
    assert "advisory" not in refreshed.terms  # Contractual terms untouched

    # Invariant: Advisory assessment does NOT satisfy authoritative idempotency check
    authoritative_fa = FeasibilityAssessment(
        assessment_id="fa_advisory_001",  # Same assessment_id
        tenant_id=tenant_id,
        commitment_id=com_id,
        commitment_version=1,
        snapshot_version=1,
        status=FeasibilityState.FEASIBLE,
        constraints=[],
        affected_commitment_ids=[],
        solver_status="COMPLETED",
        assessed_at=now,
    )
    # This must execute and transition state (not be skipped as duplicate)
    updated = service.assess(db_session, service_ctx, com_id, authoritative_fa)
    assert updated.feasibility_state.value == "FEASIBLE"
    assert updated.commitment_version == 2
    assert "fa_advisory_001" in updated.evidence_refs


def test_unregistered_mandatory_subscriber_warning_is_throttled(
    db_session: Session, caplog: pytest.LogCaptureFixture
) -> None:
    """Ensure unregistered mandatory subscriber warning logs once and does not spam every cycle."""
    import logging

    logger = logging.getLogger("app.core.outbox")
    logger.disabled = False

    dispatcher = OutboxDispatcher()
    now = datetime.now(timezone.utc)
    tenant_id = "tenant_throttle"
    com_id = "com_throttle_001"

    rec = CommitmentRecord(
        tenant_id=tenant_id,
        commitment_id=com_id,
        order_id="ord_throttle",
        customer_id="cust_throttle",
        terms={"sku": "BURGER", "quantity": "10", "unit": "pcs", "deadline": now.isoformat()},
        agreement_state="CONFIRMED",
        feasibility_state="NOT_ASSESSED",
        risk_state="NORMAL",
        recovery_state="NONE",
        fulfilment_state="NOT_STARTED",
        commitment_version=1,
        evidence_refs=["ev_throttle"],
        updated_at=now,
    )
    evt_risk = OutboxEventRecord(
        event_id="evt_throttle_risk",
        tenant_id=tenant_id,
        event_type="commitment.at_risk",
        commitment_id=com_id,
        commitment_version=1,
        correlation_id="corr_throttle",
        occurred_at=now,
        payload={"commitment_id": com_id},
        attempts=0,
        status=OutboxStatus.PENDING.value,
    )
    db_session.add_all([rec, evt_risk])
    db_session.commit()

    with caplog.at_level(logging.WARNING, logger="app.core.outbox"):
        # 1. First poll emits a warning
        res1 = dispatcher.process_outbox_batch(db_session)
        assert res1.published_count == 0
        warning_records_1 = [
            r for r in caplog.records if r.levelno == logging.WARNING and "p3.recovery_trigger.v1" in r.message
        ]
        assert len(warning_records_1) == 1

        # 2. Second poll leaves event in PENDING without repeating the warning
        res2 = dispatcher.process_outbox_batch(db_session)
        assert res2.published_count == 0
        warning_records_2 = [
            r for r in caplog.records if r.levelno == logging.WARNING and "p3.recovery_trigger.v1" in r.message
        ]
        assert len(warning_records_2) == 1  # Still 1, not spammed to 2!

