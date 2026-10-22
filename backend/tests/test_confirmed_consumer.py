"""Mandatory P2 confirmation delivery uses persisted evidence and one transaction."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.events import OutboxStatus
from app.core.models import (
    AuditEventRecord,
    CommitmentRecord,
    OutboxEventRecord,
    ProcessedEventRecord,
)
from app.core.outbox import OutboxDispatcher
from app.feasibility.confirmed_consumer import PersistedConfirmedEvaluator
from app.feasibility.persisted_sources import stage_snapshot
from app.feasibility.production_fixtures import build_production_example
from app.worker import configure_isolated_subscribers


def _seed(db: Session) -> tuple[str, str, str]:
    snapshot, commitment = build_production_example()
    db.add(CommitmentRecord(
        tenant_id=commitment.tenant_id, commitment_id=commitment.commitment_id,
        order_id=commitment.order_id, customer_id=commitment.customer_id,
        terms=commitment.terms.model_dump(mode="json"), agreement_state="CONFIRMED",
        feasibility_state="NOT_ASSESSED", risk_state="NORMAL", recovery_state="NONE",
        fulfilment_state="NOT_STARTED", commitment_version=commitment.commitment_version,
        evidence_refs=list(commitment.evidence_refs), updated_at=datetime.now(UTC),
    ))
    stage_snapshot(db, snapshot, current=True)
    event_id = "evt_confirmed_p2_persisted"
    db.add(OutboxEventRecord(
        event_id=event_id, tenant_id=commitment.tenant_id,
        event_type="commitment.confirmed", commitment_id=commitment.commitment_id,
        commitment_version=commitment.commitment_version,
        correlation_id="corr_confirmed_p2", causation_id=None,
        occurred_at=datetime.now(UTC), payload={"commitment_id": commitment.commitment_id},
        status=OutboxStatus.PENDING.value, attempts=0,
    ))
    db.commit()
    return commitment.tenant_id, commitment.commitment_id, event_id


def test_mandatory_consumers_require_explicit_isolated_worker_gate(monkeypatch) -> None:
    dispatcher = OutboxDispatcher()
    monkeypatch.delenv("MOUMANTAI_ISOLATED_E2E", raising=False)
    configure_isolated_subscribers(dispatcher)
    assert dispatcher.get_subscribers("commitment.confirmed") == []
    assert dispatcher.get_subscribers("commitment.at_risk") == []

    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E", "1")
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E_KEY", "isolated-key-" + "x" * 32)
    configure_isolated_subscribers(dispatcher)
    assert [name for name, _ in dispatcher.get_subscribers("commitment.confirmed")] == ["p2_confirmed_evaluator"]
    assert [name for name, _ in dispatcher.get_subscribers("commitment.at_risk")] == ["p3.recovery_trigger.v1"]


def test_confirmed_consumer_publishes_only_after_durable_assessment(session: Session) -> None:
    tenant, commitment, event_id = _seed(session)
    dispatcher = OutboxDispatcher()
    dispatcher.register_subscriber("commitment.confirmed", "p2_confirmed_evaluator", PersistedConfirmedEvaluator().persist)

    result = dispatcher.process_outbox_batch(session)
    assert result.published_count >= 1, session.get(OutboxEventRecord, event_id).last_error
    assert session.get(OutboxEventRecord, event_id).status == OutboxStatus.PUBLISHED.value
    assert session.get(ProcessedEventRecord, (tenant, event_id, "p2_confirmed_evaluator")) is not None
    record = session.get(CommitmentRecord, (tenant, commitment))
    assert record.commitment_version == 2
    assert record.feasibility_state == "FEASIBLE"
    audits = session.scalars(select(AuditEventRecord).where(
        AuditEventRecord.tenant_id == tenant, AuditEventRecord.commitment_id == commitment,
        AuditEventRecord.new_state["assessment_id"].as_string().is_not(None),
    )).all()
    assert len(audits) == 1
    assert audits[0].causation_id == event_id

    dispatcher.process_outbox_batch(session)
    assert session.get(CommitmentRecord, (tenant, commitment)).commitment_version == 2
    assert len(session.scalars(select(AuditEventRecord).where(
        AuditEventRecord.tenant_id == tenant, AuditEventRecord.commitment_id == commitment,
        AuditEventRecord.new_state["assessment_id"].as_string().is_not(None),
    )).all()) == 1


def test_confirmed_consumer_failure_rolls_back_assessment_and_marker(session: Session) -> None:
    tenant, commitment, event_id = _seed(session)
    evaluator = PersistedConfirmedEvaluator()

    def fail_after_write(db, event):
        evaluator.persist(db, event)
        raise RuntimeError("synthetic downstream failure")

    dispatcher = OutboxDispatcher()
    dispatcher.register_subscriber("commitment.confirmed", "p2_confirmed_evaluator", fail_after_write)
    result = dispatcher.process_outbox_batch(session)
    assert result.failed_count == 1
    assert session.get(OutboxEventRecord, event_id).status == OutboxStatus.FAILED.value
    assert session.get(ProcessedEventRecord, (tenant, event_id, "p2_confirmed_evaluator")) is None
    assert session.get(CommitmentRecord, (tenant, commitment)).commitment_version == 1
    assert session.scalars(select(AuditEventRecord).where(
        AuditEventRecord.tenant_id == tenant, AuditEventRecord.commitment_id == commitment,
        AuditEventRecord.new_state["assessment_id"].as_string().is_not(None),
    )).all() == []

    dispatcher.register_subscriber("commitment.confirmed", "p2_confirmed_evaluator", evaluator.persist)
    record = session.get(OutboxEventRecord, event_id)
    record.next_retry_at = None
    session.commit()
    assert dispatcher.process_outbox_batch(session).published_count >= 1
    assert session.get(ProcessedEventRecord, (tenant, event_id, "p2_confirmed_evaluator")) is not None
