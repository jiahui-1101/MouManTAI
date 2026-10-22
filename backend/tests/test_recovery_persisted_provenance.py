"""P3 consumes exact persisted Core risk provenance without a fixture lookup."""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.models import AuditEventRecord, CommitmentRecord, OutboxEventRecord, ProcessedEventRecord
from app.core.outbox import OutboxDispatcher, to_domain_event
from app.core.service import CommitmentService
from app.recovery.fixtures import load_demo_recovery_inputs
from app.recovery.persistence import RecoveryCaseRecord, RecoveryCaseTriggerRecord
from app.recovery.trigger_persistence import (
    PersistedCoreAssessmentLookup,
    SessionScopedRecoveryTriggerAdapter,
)


def _risk_event(session: Session):
    inputs = load_demo_recovery_inputs()
    source = inputs.commitment
    tenant_id, commitment_id = "tenant_p3_source", "com_p3_source"
    session.add(CommitmentRecord(
        tenant_id=tenant_id, commitment_id=commitment_id,
        order_id=source.order_id, customer_id=source.customer_id,
        terms=source.terms.model_dump(mode="json"),
        agreement_state="CONFIRMED", feasibility_state="NOT_ASSESSED",
        risk_state="NORMAL", recovery_state="NONE", fulfilment_state="NOT_STARTED",
        commitment_version=1, evidence_refs=[], updated_at=datetime.now(timezone.utc),
    ))
    session.commit()
    assessment = inputs.assessment.model_copy(update={
        "assessment_id": "fa_p3_source", "tenant_id": tenant_id,
        "commitment_id": commitment_id, "commitment_version": 1,
    })
    context = RequestContext(
        tenant_id=tenant_id, actor_id="service_p2_writer", actor_role="SERVICE",
        correlation_id="corr_p3_source", causation_id="evt_supplier_change_source",
    )
    CommitmentService().assess(
        session, context, commitment_id, assessment, snapshot_id="snap_p3_source",
    )
    row = session.scalar(select(OutboxEventRecord).where(
        OutboxEventRecord.tenant_id == tenant_id,
        OutboxEventRecord.commitment_id == commitment_id,
        OutboxEventRecord.event_type == "commitment.at_risk",
    ))
    assert row is not None
    return to_domain_event(row), assessment


def test_persisted_core_assessment_creates_exact_p3_case_and_trigger(session: Session) -> None:
    event, assessment = _risk_event(session)
    adapter = SessionScopedRecoveryTriggerAdapter(
        authoritative_assessment_lookup=PersistedCoreAssessmentLookup(),
    )
    case, created, duplicate = adapter.persist(session, event)
    assert created and not duplicate
    session.commit()
    trigger = session.get(RecoveryCaseTriggerRecord, (event.tenant_id, event.event_id))
    assert trigger is not None
    assert trigger.case_id == case.case_id
    assert trigger.assessment_id == assessment.assessment_id
    assert trigger.assessment_commitment_version == 1
    assert trigger.commitment_version == 2
    assert trigger.snapshot_id == "snap_p3_source"
    assert trigger.evidence_refs == assessment.evidence_refs
    assert trigger.assessment_provenance_status == "VERIFIED_AUTHORITATIVE"
    assert session.get(RecoveryCaseRecord, (event.tenant_id, case.case_id)) is not None
    assert session.scalars(select(ProcessedEventRecord)).all() == []
    replay, replay_created, replay_duplicate = adapter.persist(session, event)
    assert replay.case_id == case.case_id and not replay_created and replay_duplicate


def test_isolated_dispatcher_commits_case_trigger_and_processed_marker(session: Session) -> None:
    event, _ = _risk_event(session)
    adapter = SessionScopedRecoveryTriggerAdapter(
        authoritative_assessment_lookup=PersistedCoreAssessmentLookup(),
    )
    dispatcher = OutboxDispatcher()
    dispatcher.register_subscriber("commitment.at_risk", "p3.recovery_trigger.v1", adapter.persist)
    result = dispatcher.process_outbox_batch(session)
    assert result.published_count == 1 and result.failed_count == 0
    assert session.get(ProcessedEventRecord, (
        event.tenant_id, event.event_id, "p3.recovery_trigger.v1",
    )) is not None
    assert session.get(RecoveryCaseTriggerRecord, (event.tenant_id, event.event_id)) is not None
    assert session.get(OutboxEventRecord, event.event_id).status == "PUBLISHED"
    assert dispatcher.process_outbox_batch(session).processed_count == 0
    assert len(session.scalars(select(RecoveryCaseTriggerRecord)).all()) == 1


def test_missing_persisted_assessment_blocks_case_and_processed_marker(session: Session) -> None:
    event, _ = _risk_event(session)
    audit = session.scalar(select(AuditEventRecord).where(
        AuditEventRecord.tenant_id == event.tenant_id,
        AuditEventRecord.commitment_id == event.commitment_id,
        AuditEventRecord.event_type == "commitment.at_risk",
    ))
    assert audit is not None
    session.delete(audit)
    session.commit()
    adapter = SessionScopedRecoveryTriggerAdapter(
        authoritative_assessment_lookup=PersistedCoreAssessmentLookup(),
    )
    dispatcher = OutboxDispatcher()
    dispatcher.register_subscriber("commitment.at_risk", "p3.recovery_trigger.v1", adapter.persist)
    result = dispatcher.process_outbox_batch(session)
    assert result.failed_count == 1 and result.published_count == 0
    assert session.scalars(select(RecoveryCaseRecord)).all() == []
    assert session.scalars(select(RecoveryCaseTriggerRecord)).all() == []
    assert session.scalars(select(ProcessedEventRecord)).all() == []


def test_failed_consumer_transaction_rolls_back_p3_rows_and_retries(session: Session) -> None:
    event, _ = _risk_event(session)
    adapter = SessionScopedRecoveryTriggerAdapter(
        authoritative_assessment_lookup=PersistedCoreAssessmentLookup(),
    )
    dispatcher = OutboxDispatcher()

    def fail_after_case(db: Session, risk_event) -> None:
        adapter.persist(db, risk_event)
        raise RuntimeError("synthetic consumer interruption")

    dispatcher.register_subscriber("commitment.at_risk", "p3.recovery_trigger.v1", fail_after_case)
    first = dispatcher.process_outbox_batch(session)
    assert first.failed_count == 1
    assert session.scalars(select(RecoveryCaseRecord)).all() == []
    assert session.scalars(select(RecoveryCaseTriggerRecord)).all() == []
    assert session.scalars(select(ProcessedEventRecord)).all() == []
    row = session.get(OutboxEventRecord, event.event_id)
    assert row.status == "FAILED" and row.attempts == 1

    row.next_retry_at = None
    session.commit()
    dispatcher.register_subscriber("commitment.at_risk", "p3.recovery_trigger.v1", adapter.persist)
    retry = dispatcher.process_outbox_batch(session)
    assert retry.published_count == 1
    assert len(session.scalars(select(RecoveryCaseRecord)).all()) == 1
    assert len(session.scalars(select(RecoveryCaseTriggerRecord)).all()) == 1
    assert len(session.scalars(select(ProcessedEventRecord)).all()) == 1


@pytest.mark.parametrize("field,value", [
    ("assessment_id", "fa_wrong"),
    ("snapshot_id", "snap_wrong"),
    ("snapshot_version", 99),
])
def test_persisted_lookup_rejects_changed_risk_event_without_partial_case(
    session: Session, field: str, value: str,
) -> None:
    event, _ = _risk_event(session)
    changed = event.model_copy(update={"payload": {**event.payload, field: value}})
    adapter = SessionScopedRecoveryTriggerAdapter(
        authoritative_assessment_lookup=PersistedCoreAssessmentLookup(),
    )
    with pytest.raises(DomainError) as error:
        adapter.persist(session, changed)
    assert error.value.code == "RECOVERY_EVENT_IDENTITY_UNVERIFIABLE"
    assert session.scalars(select(RecoveryCaseRecord)).all() == []
    assert session.scalars(select(RecoveryCaseTriggerRecord)).all() == []
