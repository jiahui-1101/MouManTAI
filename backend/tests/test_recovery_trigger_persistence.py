"""SQLite-only contract tests; PostgreSQL migration/locking remains unverified."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.core.errors import DomainError
from app.core.events import create_domain_event
from app.core.models import CommitmentRecord, ProcessedEventRecord
from app.core.schemas import (
    AgreementState,
    FeasibilityState,
    FulfilmentState,
    RecoveryState,
    RiskState,
)
from app.recovery.fixtures import load_demo_recovery_inputs
from app.recovery.models import RecoveryCaseStatus
from app.recovery.persistence import RecoveryCaseRecord, RecoveryCaseTriggerRecord
from app.recovery.trigger_persistence import (
    SessionScopedRecoveryTriggerAdapter,
    SyntheticAssessmentProof,
)
from app.recovery.triggers import canonical_domain_event_digest


class FixtureAssessmentLookup:
    """Explicit fixture only; not an authoritative P2/P5 service."""

    def __init__(self, proof):
        self.proof = proof
        self.calls = 0

    def lookup(self, session, tenant_id, commitment_id, assessment_id, event_id):
        del session, tenant_id, commitment_id, assessment_id, event_id
        self.calls += 1
        return self.proof


def _setup(session):
    inputs = load_demo_recovery_inputs()
    commitment = inputs.commitment.model_copy(update={
        "tenant_id": "tenant_trigger_sql",
        "commitment_id": "com_trigger_sql",
        "commitment_version": 5,
        "agreement_state": AgreementState.CONFIRMED,
        "feasibility_state": FeasibilityState.INFEASIBLE,
        "risk_state": RiskState.AT_RISK,
        "recovery_state": RecoveryState.RECOVERY_REQUIRED,
        "fulfilment_state": FulfilmentState.NOT_STARTED,
    })
    assessment = inputs.assessment.model_copy(update={
        "tenant_id": commitment.tenant_id,
        "commitment_id": commitment.commitment_id,
        "commitment_version": 3,
        "status": FeasibilityState.INFEASIBLE,
        "affected_commitment_ids": [commitment.commitment_id],
    })
    session.add(CommitmentRecord(
        tenant_id=commitment.tenant_id,
        commitment_id=commitment.commitment_id,
        order_id=commitment.order_id,
        customer_id=commitment.customer_id,
        terms=commitment.terms.model_dump(mode="json"),
        agreement_state=commitment.agreement_state.value,
        feasibility_state=commitment.feasibility_state.value,
        risk_state=commitment.risk_state.value,
        recovery_state=commitment.recovery_state.value,
        fulfilment_state=commitment.fulfilment_state.value,
        commitment_version=commitment.commitment_version,
        evidence_refs=commitment.evidence_refs,
        updated_at=commitment.updated_at,
    ))
    session.flush()
    return commitment, assessment


def _event(commitment, assessment, *, event_id="evt_trigger_sql", version=None, tenant_id=None):
    return create_domain_event(
        event_id=event_id,
        event_type="commitment.at_risk",
        tenant_id=tenant_id or commitment.tenant_id,
        commitment_id=commitment.commitment_id,
        commitment_version=version or commitment.commitment_version,
        correlation_id="corr_trigger_sql",
        causation_id="assessment-command-sql",
        occurred_at=datetime(2026, 10, 22, 10, tzinfo=UTC),
        payload={
            "commitment_id": commitment.commitment_id,
            "assessment_id": assessment.assessment_id,
            "evaluated_commitment_version": assessment.commitment_version,
            "snapshot_version": assessment.snapshot_version,
            "snapshot_id": "snap_fixture_sql",
            "feasibility_status": "INFEASIBLE",
            "constraints": [item.model_dump(mode="json") for item in assessment.constraints],
            "affected_commitment_ids": assessment.affected_commitment_ids,
            "evidence_refs": assessment.evidence_refs,
        },
    )


def _adapter(assessment, *, event_id="evt_trigger_sql", **changes):
    proof = SyntheticAssessmentProof(
        assessment=assessment, snapshot_id="snap_fixture_sql", caused_event_id=event_id
    )
    proof = SyntheticAssessmentProof(**{**proof.__dict__, **changes})
    lookup = FixtureAssessmentLookup(proof)
    return SessionScopedRecoveryTriggerAdapter(
        synthetic_assessment_lookup=lookup, allow_synthetic_for_tests=True
    ), lookup


def _count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def test_caller_session_atomic_rows_and_no_processed_marker(session):
    commitment, assessment = _setup(session)
    event = _event(commitment, assessment)
    adapter, _ = _adapter(assessment)
    with patch.object(session, "commit") as commit, patch.object(session, "rollback") as rollback:
        case, created, duplicate = adapter.persist(session, event)
    commit.assert_not_called()
    rollback.assert_not_called()
    assert created and not duplicate and not adapter.live_ready
    assert case.status == RecoveryCaseStatus.AWAITING_EVALUATION_INPUTS
    assert case.storage_mode == "DURABLE_DATABASE"
    assert _count(session, RecoveryCaseRecord) == 1
    assert _count(session, RecoveryCaseTriggerRecord) == 1
    assert _count(session, ProcessedEventRecord) == 0
    row = session.get(RecoveryCaseTriggerRecord, (event.tenant_id, event.event_id))
    assert row.case_id == case.case_id
    case_row = session.get(RecoveryCaseRecord, (event.tenant_id, case.case_id))
    assert case_row.case_payload["case_id"] == case.case_id
    assert case_row.risk_episode_id == event.event_id
    assert row.source_event_digest == canonical_domain_event_digest(event)
    assert row.assessment_provenance_status == "SOURCE_COMMITMENT_VERSION_RECORDED_UNVERIFIED"
    assert row.assessment_commitment_version == assessment.commitment_version
    assert row.snapshot_id == "snap_fixture_sql"


def test_caller_rollback_removes_uncommitted_case_and_trigger(session):
    commitment, assessment = _setup(session)
    # Commit only the P5 fixture first; P3 writes then belong to the caller's new transaction.
    session.commit()
    adapter, _ = _adapter(assessment)
    adapter.persist(session, _event(commitment, assessment))
    session.rollback()
    assert _count(session, RecoveryCaseRecord) == 0
    assert _count(session, RecoveryCaseTriggerRecord) == 0
    assert _count(session, CommitmentRecord) == 1


def test_exact_redelivery_is_idempotent_even_after_core_version_advances(session):
    commitment, assessment = _setup(session)
    event = _event(commitment, assessment)
    adapter, lookup = _adapter(assessment)
    case, _, _ = adapter.persist(session, event)
    session.get(CommitmentRecord, (commitment.tenant_id, commitment.commitment_id)).commitment_version = 6
    session.flush()
    replay, created, duplicate = adapter.persist(session, event)
    assert replay.case_id == case.case_id and not created and duplicate
    assert lookup.calls == 1
    assert _count(session, RecoveryCaseTriggerRecord) == 1


def test_fixture_redelivery_never_becomes_live_acknowledgment(session):
    commitment, assessment = _setup(session)
    event = _event(commitment, assessment)
    adapter, _ = _adapter(assessment)
    adapter.persist(session, event)
    with pytest.raises(DomainError) as exc:
        SessionScopedRecoveryTriggerAdapter().persist(session, event)
    assert exc.value.code == "AUTHORITATIVE_ASSESSMENT_LOOKUP_UNAVAILABLE"
    assert _count(session, ProcessedEventRecord) == 0


def test_conflicting_redelivery_rejected_without_extra_rows(session):
    commitment, assessment = _setup(session)
    event = _event(commitment, assessment)
    adapter, _ = _adapter(assessment)
    adapter.persist(session, event)
    changed = event.model_copy(update={"correlation_id": "different-correlation"})
    with pytest.raises(DomainError, match="different DomainEvent content") as exc:
        adapter.persist(session, changed)
    assert exc.value.code == "RECOVERY_EVENT_ID_CONFLICT"
    assert _count(session, RecoveryCaseTriggerRecord) == 1


def test_wrong_tenant_and_missing_authority_fail_closed(session):
    commitment, assessment = _setup(session)
    event = _event(commitment, assessment)
    with pytest.raises(DomainError) as exc:
        SessionScopedRecoveryTriggerAdapter().persist(session, event)
    assert exc.value.code == "AUTHORITATIVE_ASSESSMENT_LOOKUP_UNAVAILABLE"
    adapter, _ = _adapter(assessment)
    with pytest.raises(DomainError) as exc:
        adapter.persist(session, _event(commitment, assessment, tenant_id="another_tenant"))
    assert exc.value.code == "COMMITMENT_NOT_FOUND"
    assert _count(session, RecoveryCaseRecord) == 0


def test_lookup_injection_without_explicit_test_switch_is_still_unavailable(session):
    commitment, assessment = _setup(session)
    lookup = FixtureAssessmentLookup(SyntheticAssessmentProof(
        assessment=assessment, snapshot_id="snap_fixture_sql", caused_event_id="evt_trigger_sql"
    ))
    adapter = SessionScopedRecoveryTriggerAdapter(synthetic_assessment_lookup=lookup)
    with pytest.raises(DomainError) as exc:
        adapter.persist(session, _event(commitment, assessment))
    assert exc.value.code == "AUTHORITATIVE_ASSESSMENT_LOOKUP_UNAVAILABLE"
    assert lookup.calls == 0


def test_missing_lookup_result_does_not_create_history(session):
    commitment, assessment = _setup(session)
    lookup = FixtureAssessmentLookup(None)
    adapter = SessionScopedRecoveryTriggerAdapter(
        synthetic_assessment_lookup=lookup, allow_synthetic_for_tests=True
    )
    with pytest.raises(DomainError) as exc:
        adapter.persist(session, _event(commitment, assessment))
    assert exc.value.code == "RECOVERY_ASSESSMENT_PROVENANCE_MISSING"
    assert _count(session, RecoveryCaseTriggerRecord) == 0


def test_cross_tenant_assessment_is_rejected(session):
    commitment, assessment = _setup(session)
    wrong = assessment.model_copy(update={"tenant_id": "another_tenant"})
    adapter, _ = _adapter(wrong)
    with pytest.raises(DomainError) as exc:
        adapter.persist(session, _event(commitment, assessment))
    assert exc.value.code == "RECOVERY_ASSESSMENT_SCOPE_CONFLICT"


def test_assessment_version_and_snapshot_mismatches_are_rejected(session):
    commitment, assessment = _setup(session)
    wrong = assessment.model_copy(update={"snapshot_version": assessment.snapshot_version + 1})
    adapter, _ = _adapter(wrong)
    with pytest.raises(DomainError) as exc:
        adapter.persist(session, _event(commitment, assessment))
    assert exc.value.code == "RECOVERY_ASSESSMENT_VERSION_CONFLICT"
    wrong = assessment.model_copy(update={"commitment_version": assessment.commitment_version + 1})
    adapter, _ = _adapter(wrong)
    with pytest.raises(DomainError) as exc:
        adapter.persist(session, _event(commitment, assessment))
    assert exc.value.code == "RECOVERY_ASSESSMENT_VERSION_CONFLICT"
    assert _count(session, RecoveryCaseTriggerRecord) == 0


@pytest.mark.parametrize("change", [
    {"snapshot_id": ""},
    {"caused_event_id": "wrong_event"},
])
def test_missing_or_wrong_causal_proof_fails_closed(session, change):
    commitment, assessment = _setup(session)
    adapter, _ = _adapter(assessment, **change)
    with pytest.raises(DomainError) as exc:
        adapter.persist(session, _event(commitment, assessment))
    assert exc.value.code == "RECOVERY_ASSESSMENT_PROVENANCE_MISSING"
    assert _count(session, RecoveryCaseTriggerRecord) == 0


def test_missing_assessment_evidence_and_mismatched_content_fail_closed(session):
    commitment, assessment = _setup(session)
    empty = assessment.model_copy(update={"evidence_refs": [], "constraints": []})
    adapter, _ = _adapter(empty)
    with pytest.raises(DomainError) as exc:
        adapter.persist(session, _event(commitment, empty))
    assert exc.value.code == "RECOVERY_ASSESSMENT_EVIDENCE_MISSING"
    adapter, _ = _adapter(assessment)
    altered = _event(commitment, assessment).model_copy(deep=True)
    altered.payload["constraints"] = []
    with pytest.raises(DomainError) as exc:
        adapter.persist(session, altered)
    assert exc.value.code == "RECOVERY_ASSESSMENT_CONTENT_CONFLICT"
    assert _count(session, RecoveryCaseTriggerRecord) == 0


def test_stale_first_delivery_raises_and_cannot_be_acknowledged(session):
    commitment, assessment = _setup(session)
    adapter, _ = _adapter(assessment)
    with pytest.raises(DomainError) as exc:
        adapter.persist(session, _event(commitment, assessment, version=4))
    assert exc.value.code == "RECOVERY_TRIGGER_VERSION_CONFLICT"
    assert _count(session, RecoveryCaseRecord) == 0
    assert _count(session, ProcessedEventRecord) == 0


def test_reuse_active_case_and_preserve_completed_episode(session):
    commitment, assessment = _setup(session)
    first_adapter, _ = _adapter(assessment)
    first, _, _ = first_adapter.persist(session, _event(commitment, assessment))
    second_adapter, _ = _adapter(assessment, event_id="evt_second")
    second, created, duplicate = second_adapter.persist(
        session, _event(commitment, assessment, event_id="evt_second")
    )
    assert second.case_id == first.case_id and not created and not duplicate
    assert len(second.trigger_events) == 2
    original = session.get(RecoveryCaseRecord, (commitment.tenant_id, first.case_id))
    original.status = RecoveryCaseStatus.COMPLETED.value
    original.case_payload = {
        **original.case_payload,
        "status": RecoveryCaseStatus.COMPLETED.value,
    }
    session.flush()
    historical_payload = original.case_payload.copy()
    historical_episode_id = original.risk_episode_id
    third_adapter, _ = _adapter(assessment, event_id="evt_new_episode")
    third, created, duplicate = third_adapter.persist(
        session, _event(commitment, assessment, event_id="evt_new_episode")
    )
    assert created and not duplicate and third.case_id != first.case_id
    assert _count(session, RecoveryCaseRecord) == 2
    retained = session.get(RecoveryCaseRecord, (commitment.tenant_id, first.case_id))
    assert retained.status == "COMPLETED" and retained.case_payload == historical_payload
    assert retained.risk_episode_id == historical_episode_id
    assert third_adapter.repository.get_active_case(
        session, commitment.tenant_id, commitment.commitment_id
    ).case_id == third.case_id
    assert len(first_adapter.repository.list_case_triggers(session, commitment.tenant_id, first.case_id)) == 2


def test_demo_planning_is_separate_from_sql_adapter():
    from app.recovery.service import default_recovery_planner, demo_recovery_planner

    assert demo_recovery_planner.repository is not default_recovery_planner.repository
    assert not SessionScopedRecoveryTriggerAdapter().live_ready


def test_committed_rows_survive_session_restart_in_sqlite(test_engine):
    factory = sessionmaker(bind=test_engine, autoflush=False)
    with factory() as first_session:
        commitment, assessment = _setup(first_session)
        adapter, _ = _adapter(assessment)
        case, _, _ = adapter.persist(first_session, _event(commitment, assessment))
        first_session.commit()
    with factory() as second_session:
        assert second_session.get(RecoveryCaseRecord, (commitment.tenant_id, case.case_id)) is not None
        replay, created, duplicate = adapter.persist(second_session, _event(commitment, assessment))
        assert replay.case_id == case.case_id and not created and duplicate
