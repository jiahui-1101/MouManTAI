"""Joint Transaction A/B Dual-Boundary Isolation Test (ADR-016, Task T-P3H1).

Verifies:
1. Transaction A (CommitmentService.assess + risk transition + audit + outbox PENDING) commits independently.
2. Injected consumer failure in Transaction B (outbox dispatcher -> consumer -> ProcessedEventRecord):
   - Consumer writes (case/trigger) and ProcessedEventRecord are rolled back cleanly.
   - Transaction A state (Commitment risk state AT_RISK, audit record, outbox event) remains committed.
   - Outbox event attempts increment to 1, status becomes FAILED, next_retry_at follows exponential backoff.
3. Subsequent retry with successful consumer writes case/trigger, creates ProcessedEventRecord, and marks outbox PUBLISHED.
4. Idempotent deduplication: subsequent runs skip the processed event without double execution.
5. Uses test-only subscriber; never registers or enables live P3 consumer.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.events import CoreEventType, OutboxStatus
from app.core.models import (
    AuditEventRecord,
    CommitmentRecord,
    OutboxEventRecord,
    ProcessedEventRecord,
)
from app.core.outbox import OutboxDispatcher
from app.core.schemas import (
    AgreementState,
    ConstraintReason,
    DomainEvent,
    FeasibilityAssessment,
    FeasibilityState,
    FulfilmentState,
    RecoveryState,
    RiskState,
)
from app.core.service import CommitmentService


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_recovery_tables_exist(session: Session) -> None:
    insp = inspect(session.bind)
    if not insp.has_table("recovery_cases"):
        session.execute(
            text(
                """
                CREATE TABLE recovery_cases (
                    tenant_id VARCHAR(128) NOT NULL,
                    case_id VARCHAR(128) NOT NULL,
                    commitment_id VARCHAR(128) NOT NULL,
                    risk_episode_id VARCHAR(128) NOT NULL,
                    opening_event_id VARCHAR(128) NOT NULL,
                    status VARCHAR(48) NOT NULL,
                    case_version INTEGER NOT NULL,
                    commitment_version INTEGER NOT NULL,
                    payload_schema_version INTEGER NOT NULL DEFAULT 1,
                    case_payload TEXT NOT NULL,
                    resolution_event_id VARCHAR(128),
                    resolution_commitment_version INTEGER,
                    resolution_refs TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL,
                    resolved_at TIMESTAMP,
                    PRIMARY KEY (tenant_id, case_id)
                )
                """
            )
        )
    if not insp.has_table("recovery_case_triggers"):
        session.execute(
            text(
                """
                CREATE TABLE recovery_case_triggers (
                    tenant_id VARCHAR(128) NOT NULL,
                    event_id VARCHAR(128) NOT NULL,
                    case_id VARCHAR(128) NOT NULL,
                    commitment_id VARCHAR(128) NOT NULL,
                    commitment_version INTEGER NOT NULL,
                    assessment_id VARCHAR(128) NOT NULL,
                    assessment_commitment_version INTEGER,
                    assessment_provenance_status VARCHAR(64) NOT NULL,
                    snapshot_id VARCHAR(128),
                    snapshot_version INTEGER NOT NULL DEFAULT 1,
                    constraints TEXT NOT NULL DEFAULT '[]',
                    affected_commitment_ids TEXT NOT NULL DEFAULT '[]',
                    evidence_refs TEXT NOT NULL DEFAULT '[]',
                    correlation_id VARCHAR(128) NOT NULL,
                    causation_id VARCHAR(128),
                    occurred_at TIMESTAMP NOT NULL,
                    event_digest VARCHAR(64) NOT NULL,
                    source_event_digest VARCHAR(64),
                    PRIMARY KEY (tenant_id, event_id)
                )
                """
            )
        )
    session.commit()


def test_transaction_ab_isolation_and_rollback_boundary(session: Session) -> None:
    """Transaction B consumer failure must never roll back Transaction A."""
    _ensure_recovery_tables_exist(session)
    tenant = "tenant_ab_iso_01"
    com_id = "com_ab_iso_01"
    ctx = RequestContext(
        tenant_id=tenant,
        actor_id="service_p2_writer",
        actor_role="SERVICE",
        correlation_id="corr_ab_01",
        causation_id="cause_ab_01",
    )

    now = _now()

    # 1. Seed initial confirmed commitment (Transaction A prerequisite)
    commitment = CommitmentRecord(
        tenant_id=tenant,
        commitment_id=com_id,
        order_id="ord_ab_01",
        customer_id="cust_ab_01",
        terms={"sku": "BURGER", "quantity": "10", "unit": "pcs", "deadline": now.isoformat()},
        agreement_state=AgreementState.CONFIRMED.value,
        feasibility_state=FeasibilityState.FEASIBLE.value,
        risk_state=RiskState.NORMAL.value,
        recovery_state=RecoveryState.NONE.value,
        fulfilment_state=FulfilmentState.NOT_STARTED.value,
        commitment_version=1,
        evidence_refs=["ev_init_01"],
        updated_at=now,
    )
    session.add(commitment)
    session.commit()

    # 2. Execute Transaction A: Core assess() marking commitment AT_RISK
    service = CommitmentService()
    assessment = FeasibilityAssessment(
        assessment_id="asm_ab_infeasible_01",
        tenant_id=tenant,
        commitment_id=com_id,
        commitment_version=1,
        snapshot_version=101,
        status=FeasibilityState.INFEASIBLE,
        constraints=[
            ConstraintReason(
                code="SHORTAGE",
                resource_id="BURGER_PATTY",
                severity="HARD",
                evidence_refs=["ev_supplier_delay_01"],
            )
        ],
        affected_commitment_ids=[],
        evidence_refs=["ev_supplier_delay_01"],
        solver_status="COMPLETED",
        assumptions=["Supplier delivery delayed 24h"],
        assessed_at=now,
    )

    # Transaction A commits atomically
    res_comm = service.assess(session, ctx, com_id, assessment, commit=True)
    assert res_comm.risk_state == RiskState.AT_RISK
    assert res_comm.commitment_version == 2

    outbox_event = session.scalar(
        select(OutboxEventRecord).where(
            OutboxEventRecord.tenant_id == tenant,
            OutboxEventRecord.commitment_id == com_id,
        )
    )
    assert outbox_event is not None
    assert outbox_event.event_type == CoreEventType.COMMITMENT_AT_RISK.value

    # Verify Transaction A persistence in DB
    session.expire_all()
    db_comm = session.scalar(
        select(CommitmentRecord).where(
            CommitmentRecord.tenant_id == tenant,
            CommitmentRecord.commitment_id == com_id,
        )
    )
    assert db_comm is not None
    assert db_comm.risk_state == "AT_RISK"
    assert db_comm.commitment_version == 2

    db_outbox = session.scalar(
        select(OutboxEventRecord).where(
            OutboxEventRecord.tenant_id == tenant,
            OutboxEventRecord.event_id == outbox_event.event_id,
        )
    )
    assert db_outbox is not None
    assert db_outbox.status == OutboxStatus.PENDING.value
    assert db_outbox.attempts == 0

    db_audit = session.scalar(
        select(AuditEventRecord).where(
            AuditEventRecord.tenant_id == tenant,
            AuditEventRecord.commitment_id == com_id,
            AuditEventRecord.event_type == CoreEventType.COMMITMENT_AT_RISK.value,
        )
    )
    assert db_audit is not None
    assert db_audit.new_state.get("risk_state") == "AT_RISK"

    # 3. Setup Transaction B with an injected failing consumer
    injected_case_id = "case_injected_01"
    consumer_name = "test_failing_p3_consumer"

    def failing_handler(db: Session, event: DomainEvent) -> None:
        # Simulate writing a recovery case and trigger before failing
        db.execute(
            text(
                """
                INSERT INTO recovery_cases (
                    tenant_id, case_id, commitment_id, risk_episode_id, opening_event_id,
                    status, case_version, commitment_version, payload_schema_version,
                    case_payload, resolution_refs, created_at, updated_at
                ) VALUES (
                    :tenant_id, :case_id, :commitment_id, 'risk_ep_ab_01', :event_id,
                    'OPEN', 1, 2, 1,
                    '{}', '[]', :now, :now
                )
                """
            ),
            {
                "tenant_id": event.tenant_id,
                "case_id": injected_case_id,
                "commitment_id": event.commitment_id,
                "event_id": event.event_id,
                "now": _now().isoformat(),
            },
        )
        db.execute(
            text(
                """
                INSERT INTO recovery_case_triggers (
                    tenant_id, event_id, case_id, commitment_id, commitment_version,
                    assessment_id, assessment_commitment_version, assessment_provenance_status,
                    snapshot_id, snapshot_version, constraints, affected_commitment_ids,
                    evidence_refs, correlation_id, occurred_at, event_digest
                ) VALUES (
                    :tenant_id, :event_id, :case_id, :commitment_id, 2,
                    'asm_ab_infeasible_01', 1, 'VERIFIED_AUTHORITATIVE',
                    'snap_01', 101, '[]', '[]',
                    '[]', 'corr_01', :now, 'digest_01'
                )
                """
            ),
            {
                "tenant_id": event.tenant_id,
                "event_id": event.event_id,
                "case_id": injected_case_id,
                "commitment_id": event.commitment_id,
                "now": _now().isoformat(),
            },
        )
        # Raise unexpected error to trigger rollback in Transaction B
        raise RuntimeError("Injected transient recovery planning failure")

    dispatcher = OutboxDispatcher()
    # Temporarily remove mandatory subscriber gate for test consumer
    saved_mandatory = dict(dispatcher.MANDATORY_SUBSCRIBERS)
    dispatcher.MANDATORY_SUBSCRIBERS.clear()

    try:
        dispatcher.register_subscriber(
            CoreEventType.COMMITMENT_AT_RISK.value,
            consumer_name,
            failing_handler,
        )

        # 4. Dispatch Transaction B (must fail and rollback consumer only)
        batch_result = dispatcher.process_outbox_batch(session, batch_size=10, max_attempts=5)
        assert batch_result.failed_count == 1

        # 5. Assert Transaction B writes were rolled back cleanly
        session.expire_all()
        case_count = session.execute(
            text("SELECT count(*) FROM recovery_cases WHERE tenant_id = :t AND case_id = :c"),
            {"t": tenant, "c": injected_case_id},
        ).scalar()
        assert case_count == 0, "Consumer case write was not rolled back!"

        trigger_count = session.execute(
            text("SELECT count(*) FROM recovery_case_triggers WHERE tenant_id = :t AND case_id = :c"),
            {"t": tenant, "c": injected_case_id},
        ).scalar()
        assert trigger_count == 0, "Consumer trigger write was not rolled back!"

        processed_count = session.scalar(
            select(ProcessedEventRecord).where(
                ProcessedEventRecord.tenant_id == tenant,
                ProcessedEventRecord.event_id == outbox_event.event_id,
                ProcessedEventRecord.consumer_name == consumer_name,
            )
        )
        assert processed_count is None, "ProcessedEventRecord was erroneously written on failure!"

        # 6. Assert Transaction A remains completely intact (NEVER rolled back)
        comm_after_failure = session.scalar(
            select(CommitmentRecord).where(
                CommitmentRecord.tenant_id == tenant,
                CommitmentRecord.commitment_id == com_id,
            )
        )
        assert comm_after_failure is not None
        assert comm_after_failure.risk_state == "AT_RISK", "Transaction A state was rolled back!"
        assert comm_after_failure.commitment_version == 2

        outbox_after_failure = session.scalar(
            select(OutboxEventRecord).where(
                OutboxEventRecord.tenant_id == tenant,
                OutboxEventRecord.event_id == outbox_event.event_id,
            )
        )
        assert outbox_after_failure is not None
        assert outbox_after_failure.status == OutboxStatus.FAILED.value
        assert outbox_after_failure.attempts == 1
        assert "Injected transient recovery planning failure" in (outbox_after_failure.last_error or "")
        assert outbox_after_failure.next_retry_at is not None
        retry_time = outbox_after_failure.next_retry_at
        if retry_time.tzinfo is None:
            retry_time = retry_time.replace(tzinfo=timezone.utc)
        assert retry_time > _now()

        # 7. Subsequent retry with a successful consumer
        def successful_handler(db: Session, event: DomainEvent) -> None:
            db.execute(
                text(
                    """
                    INSERT INTO recovery_cases (
                        tenant_id, case_id, commitment_id, risk_episode_id, opening_event_id,
                        status, case_version, commitment_version, payload_schema_version,
                        case_payload, resolution_refs, created_at, updated_at
                    ) VALUES (
                        :tenant_id, :case_id, :commitment_id, 'risk_ep_ab_01', :event_id,
                        'OPEN', 1, 2, 1,
                        '{}', '[]', :now, :now
                    )
                    """
                ),
                {
                    "tenant_id": event.tenant_id,
                    "case_id": injected_case_id,
                    "commitment_id": event.commitment_id,
                    "event_id": event.event_id,
                    "now": _now().isoformat(),
                },
            )
            db.execute(
                text(
                    """
                    INSERT INTO recovery_case_triggers (
                        tenant_id, event_id, case_id, commitment_id, commitment_version,
                        assessment_id, assessment_commitment_version, assessment_provenance_status,
                        snapshot_id, snapshot_version, constraints, affected_commitment_ids,
                        evidence_refs, correlation_id, occurred_at, event_digest
                    ) VALUES (
                        :tenant_id, :event_id, :case_id, :commitment_id, 2,
                        'asm_ab_infeasible_01', 1, 'VERIFIED_AUTHORITATIVE',
                        'snap_01', 101, '[]', '[]',
                        '[]', 'corr_01', :now, 'digest_01'
                    )
                    """
                ),
                {
                    "tenant_id": event.tenant_id,
                    "event_id": event.event_id,
                    "case_id": injected_case_id,
                    "commitment_id": event.commitment_id,
                    "now": _now().isoformat(),
                },
            )

        # Clear failing subscriber, register successful subscriber
        dispatcher._subscribers[CoreEventType.COMMITMENT_AT_RISK.value].clear()
        dispatcher.register_subscriber(
            CoreEventType.COMMITMENT_AT_RISK.value,
            consumer_name,
            successful_handler,
        )

        # Force next_retry_at to past so dispatcher polls it immediately
        outbox_after_failure.next_retry_at = _now() - timedelta(seconds=1)
        session.commit()

        # Run dispatcher again
        retry_result = dispatcher.process_outbox_batch(session, batch_size=10)
        assert retry_result.published_count == 1

        # Assert consumer write is now committed
        session.expire_all()
        case_count_success = session.execute(
            text("SELECT count(*) FROM recovery_cases WHERE tenant_id = :t AND case_id = :c"),
            {"t": tenant, "c": injected_case_id},
        ).scalar()
        assert case_count_success == 1, "Successful retry did not commit recovery case!"

        trigger_count_success = session.execute(
            text("SELECT count(*) FROM recovery_case_triggers WHERE tenant_id = :t AND case_id = :c"),
            {"t": tenant, "c": injected_case_id},
        ).scalar()
        assert trigger_count_success == 1, "Successful retry did not commit recovery trigger!"

        # Assert ProcessedEventRecord is committed
        processed_record = session.scalar(
            select(ProcessedEventRecord).where(
                ProcessedEventRecord.tenant_id == tenant,
                ProcessedEventRecord.event_id == outbox_event.event_id,
                ProcessedEventRecord.consumer_name == consumer_name,
            )
        )
        assert processed_record is not None

        # Assert outbox event is now PUBLISHED
        outbox_final = session.scalar(
            select(OutboxEventRecord).where(
                OutboxEventRecord.tenant_id == tenant,
                OutboxEventRecord.event_id == outbox_event.event_id,
            )
        )
        assert outbox_final.status == OutboxStatus.PUBLISHED.value
        assert outbox_final.published_at is not None

        # 8. Idempotency test: duplicate batch execution skips consumer
        dup_result = dispatcher.process_outbox_batch(session, batch_size=10)
        assert dup_result.processed_count == 0

    finally:
        dispatcher.MANDATORY_SUBSCRIBERS.clear()
        dispatcher.MANDATORY_SUBSCRIBERS.update(saved_mandatory)
        dispatcher._subscribers.clear()
