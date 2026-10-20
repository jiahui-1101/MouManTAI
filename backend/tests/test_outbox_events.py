from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone
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
    process_outbox_batch,
    requeue_dead_letter,
    to_domain_event,
)
from app.core.schemas import (
    CommitmentCreateRequest,
    CommitmentTerms,
    CommitmentTransitionRequest,
    DomainEvent,
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
