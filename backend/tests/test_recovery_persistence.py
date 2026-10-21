from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError

from app.core.errors import DomainError
from app.core.models import CommitmentRecord
from app.core.schemas import (
    AgreementState,
    ApprovalState,
    Commitment,
    ConstraintReason,
    FeasibilityState,
    FulfilmentState,
    PlannedAction,
    RecoveryState,
    RiskState,
    SolverStatus,
)
from app.recovery.fixtures import load_demo_recovery_inputs
from app.recovery.models import (
    ApprovalDecision,
    ApprovalDecisionState,
    PlanEvaluation,
    RecoveryCaseStatus,
    RecoveryPlanVersion,
    RecoveryResolutionReference,
    RecoveryStrategy,
    RecoveryTriggerReference,
    RiskLevel,
    SolverReadiness,
    ValidationSource,
)
from app.recovery.persistence import (
    ACTIVE_CASE_STATUSES,
    RecoveryCaseRecord,
    RecoveryCaseTriggerRecord,
    SqlAlchemyRecoveryRepository,
)
from app.recovery.service import RecoveryPlanner, RecoveryRepository


def _commitment(
    tenant_id: str = "tenant_persist_01",
    commitment_id: str = "com_persist_01",
    version: int = 5,
    *,
    risk_state: RiskState = RiskState.AT_RISK,
    recovery_state: RecoveryState = RecoveryState.RECOVERY_REQUIRED,
) -> Commitment:
    source = load_demo_recovery_inputs().commitment
    return source.model_copy(update={
        "tenant_id": tenant_id,
        "commitment_id": commitment_id,
        "agreement_state": AgreementState.CONFIRMED,
        "feasibility_state": FeasibilityState.INFEASIBLE,
        "risk_state": risk_state,
        "recovery_state": recovery_state,
        "fulfilment_state": FulfilmentState.NOT_STARTED,
        "commitment_version": version,
    })


def _persist_commitment(session, commitment: Commitment) -> None:
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


def _trigger(
    commitment: Commitment,
    *,
    event_id: str = "evt_persist_01",
    assessment_id: str = "fa_persist_01",
    assessment_version: int | None = None,
    snapshot_id: str | None = None,
    evidence_refs: list[str] | None = None,
    constraints: list[ConstraintReason] | None = None,
    source_event_digest: str | None = None,
) -> RecoveryTriggerReference:
    return RecoveryTriggerReference(
        event_id=event_id,
        tenant_id=commitment.tenant_id,
        commitment_id=commitment.commitment_id,
        commitment_version=commitment.commitment_version,
        assessment_id=assessment_id,
        assessment_commitment_version=assessment_version,
        source_event_digest=source_event_digest,
        assessment_provenance_status=(
            "SOURCE_COMMITMENT_VERSION_RECORDED_UNVERIFIED"
            if assessment_version is not None
            else "SOURCE_COMMITMENT_VERSION_MISSING"
        ),
        snapshot_id=snapshot_id,
        snapshot_version=142,
        constraints=constraints or [],
        affected_commitment_ids=[commitment.commitment_id],
        correlation_id="corr_persist_01",
        causation_id="assessment-command-persist-01",
        evidence_refs=evidence_refs or ["ev_persist_shortage"],
        occurred_at=datetime(2026, 10, 21, 10, 0, tzinfo=UTC),
    )


def _candidate(commitment: Commitment, trigger: RecoveryTriggerReference):
    planner = RecoveryPlanner(repository=RecoveryRepository())
    case, created, duplicate = planner.create_trigger_case(commitment, trigger)
    assert created and not duplicate
    return case


def _with_historical_plan_and_approval(case):
    assessed_at = datetime(2026, 10, 21, 9, 55, tzinfo=UTC)
    plan_id = "plan_historical_01"
    evaluation = PlanEvaluation(
        evaluation_id="eval_historical_01",
        tenant_id=case.tenant_id,
        commitment_id=case.commitment_id,
        plan_id=plan_id,
        plan_version=1,
        commitment_version=case.commitment_version,
        snapshot_version=142,
        feasibility_status=FeasibilityState.CONDITIONAL,
        validation_source=ValidationSource.TEST_DOUBLE_VALIDATED,
        readiness=SolverReadiness.CONDITIONAL,
        solver_status=SolverStatus.UNKNOWN.value,
        evaluated_at=assessed_at,
    )
    plan = RecoveryPlanVersion(
        tenant_id=case.tenant_id,
        recovery_case_id=case.case_id,
        plan_id=plan_id,
        plan_version=1,
        commitment_id=case.commitment_id,
        based_on_assessment_id="assessment_historical_01",
        snapshot_version=142,
        feasibility_status=FeasibilityState.CONDITIONAL,
        estimated_extra_cost=Decimal("12.50"),
        currency="MYR",
        estimated_delay_minutes=30,
        actions=[PlannedAction(
            action_id="action_historical_01",
            type="CREATE_FOLLOWUP_TASK",
            requires_approval=True,
            idempotency_key="historical-action-key",
        )],
        approval_state=ApprovalState.APPROVED,
        execution_state="NOT_STARTED",
        option_id="option_historical_01",
        strategy=RecoveryStrategy.RESCHEDULE_PARTIAL_FULFILMENT,
        risk_level=RiskLevel.MEDIUM,
        customer_impact="Historical test plan",
        affected_commitment_count=1,
        operational_disruption_level=Decimal(1),
        supplier_uncertainty_level=Decimal(0),
        customer_confirmation_required=False,
        evaluation=evaluation,
    )
    decision = ApprovalDecision(
        approval_id="approval_historical_01",
        tenant_id=case.tenant_id,
        recovery_case_id=case.case_id,
        commitment_id=case.commitment_id,
        commitment_version=case.commitment_version,
        plan_id=plan_id,
        plan_version=1,
        snapshot_version=142,
        action_scope=["CREATE_FOLLOWUP_TASK"],
        actor_id="user_manager_01",
        actor_role="MANAGER",
        decision=ApprovalDecisionState.APPROVED,
        approved_cost_limit=Decimal("12.50"),
        reason="Historical approval sentinel",
        decided_at=assessed_at,
        approved_at=assessed_at,
        expires_at=datetime(2026, 10, 22, 9, 55, tzinfo=UTC),
    )
    return case.model_copy(update={"plans": [plan], "approval_decisions": [decision]})


def test_case_and_trigger_round_trip_preserves_domain_and_provenance(session) -> None:
    commitment = _commitment()
    _persist_commitment(session, commitment)
    trigger = _trigger(commitment, assessment_version=3, snapshot_id="snap_142")
    repository = SqlAlchemyRecoveryRepository()

    saved, created, duplicate = repository.create_or_get_active_case(
        session,
        _candidate(commitment, trigger),
        trigger,
    )

    assert created and not duplicate
    assert saved.storage_mode == "DURABLE_DATABASE"
    assert saved.status == RecoveryCaseStatus.AWAITING_EVALUATION_INPUTS
    assert saved.trigger_assessment is None
    assert saved.trigger_events == [trigger]
    restored = type(saved).model_validate(saved.model_dump(mode="json"))
    assert restored == saved
    row = session.get(RecoveryCaseTriggerRecord, (commitment.tenant_id, trigger.event_id))
    assert row is not None
    assert (row.commitment_version, row.assessment_commitment_version) == (5, 3)
    assert (row.snapshot_id, row.snapshot_version) == ("snap_142", 142)
    assert row.assessment_provenance_status == "SOURCE_COMMITMENT_VERSION_RECORDED_UNVERIFIED"


def test_full_event_digest_and_structured_constraints_round_trip(session) -> None:
    commitment = _commitment()
    _persist_commitment(session, commitment)
    constraint = ConstraintReason(
        code="MATERIAL_SHORTAGE",
        resource_id="PACKAGING",
        shortage=Decimal(2),
        unit="pcs",
        severity="HARD",
        evidence_refs=["ev_shortage_full"],
    )
    trigger = _trigger(
        commitment,
        assessment_version=3,
        snapshot_id="snap_full_142",
        evidence_refs=["ev_top_level_full"],
        constraints=[constraint],
        source_event_digest="a" * 64,
    )
    repository = SqlAlchemyRecoveryRepository()
    case, _, _ = repository.create_or_get_active_case(session, _candidate(commitment, trigger), trigger)

    row = session.get(RecoveryCaseTriggerRecord, (commitment.tenant_id, trigger.event_id))
    restored = repository.list_case_triggers(session, commitment.tenant_id, case.case_id)[0]
    assert row is not None
    assert row.source_event_digest == "a" * 64
    assert row.event_digest == repository._digest(trigger)
    assert restored.constraints == [constraint]
    assert restored.snapshot_id == "snap_full_142"
    assert restored.evidence_refs == ["ev_top_level_full"]
    assert restored.correlation_id == trigger.correlation_id
    assert restored.causation_id == trigger.causation_id


def test_queries_are_tenant_scoped_and_return_ordered_trigger_history(session) -> None:
    commitment = _commitment()
    _persist_commitment(session, commitment)
    first = _trigger(commitment, event_id="evt_a")
    second = _trigger(commitment, event_id="evt_b", assessment_id="fa_second")
    repository = SqlAlchemyRecoveryRepository()
    case, _, _ = repository.create_or_get_active_case(session, _candidate(commitment, first), first)
    next_case, created, duplicate = repository.create_or_get_active_case(
        session,
        _candidate(commitment, second),
        second,
    )

    assert not created and not duplicate
    assert next_case.case_id == case.case_id
    history = repository.read_case_and_history(session, commitment.tenant_id, case.case_id)
    assert history is not None
    assert [item.event_id for item in history[1]] == ["evt_a", "evt_b"]
    assert repository.get_case_by_id(session, "tenant_other", case.case_id) is None
    assert repository.get_active_case(session, "tenant_other", commitment.commitment_id) is None
    assert repository.list_case_triggers(session, "tenant_other", case.case_id) == []


def test_duplicate_event_is_idempotent_and_conflicting_event_content_is_rejected(session) -> None:
    commitment = _commitment()
    _persist_commitment(session, commitment)
    trigger = _trigger(commitment)
    repository = SqlAlchemyRecoveryRepository()
    case, _, _ = repository.create_or_get_active_case(session, _candidate(commitment, trigger), trigger)

    duplicate_case, created, duplicate = repository.create_or_get_active_case(
        session,
        _candidate(commitment, trigger),
        trigger,
    )
    assert duplicate and not created
    assert duplicate_case.case_id == case.case_id
    assert len(repository.list_case_triggers(session, commitment.tenant_id, case.case_id)) == 1

    conflicting = trigger.model_copy(update={"evidence_refs": ["ev_conflicting_payload"]})
    with pytest.raises(DomainError, match="different trigger content"):
        repository.create_or_get_active_case(session, _candidate(commitment, conflicting), conflicting)


def test_exact_duplicate_remains_idempotent_after_authoritative_commitment_advances(session) -> None:
    commitment = _commitment()
    _persist_commitment(session, commitment)
    trigger = _trigger(commitment, source_event_digest="d" * 64)
    repository = SqlAlchemyRecoveryRepository()
    original, _, _ = repository.create_or_get_active_case(
        session,
        _candidate(commitment, trigger),
        trigger,
    )
    session.commit()
    core_row = session.get(CommitmentRecord, (commitment.tenant_id, commitment.commitment_id))
    assert core_row is not None
    core_row.commitment_version = 6
    session.commit()

    duplicate, created, is_duplicate = repository.create_or_get_active_case(
        session,
        _candidate(commitment, trigger),
        trigger,
    )

    assert not created and is_duplicate
    assert duplicate.case_id == original.case_id
    assert duplicate.commitment_version == 5
    assert duplicate.trigger_events == [trigger]


def test_append_duplicate_is_noop_after_commitment_advances(session) -> None:
    commitment = _commitment()
    _persist_commitment(session, commitment)
    trigger = _trigger(commitment, source_event_digest="e" * 64)
    repository = SqlAlchemyRecoveryRepository()
    original, _, _ = repository.create_or_get_active_case(
        session,
        _candidate(commitment, trigger),
        trigger,
    )
    session.commit()
    core_row = session.get(CommitmentRecord, (commitment.tenant_id, commitment.commitment_id))
    assert core_row is not None
    core_row.commitment_version = 6
    session.commit()
    candidate = _candidate(commitment, trigger).model_copy(update={"case_id": original.case_id})

    result, appended = repository.append_trigger_idempotently(
        session,
        tenant_id=commitment.tenant_id,
        case_id=original.case_id,
        candidate_case=candidate,
        trigger=trigger,
    )

    assert not appended
    assert result.case_id == original.case_id
    assert result.trigger_events == [trigger]


def test_same_reference_with_different_full_event_digest_is_rejected(session) -> None:
    commitment = _commitment()
    _persist_commitment(session, commitment)
    repository = SqlAlchemyRecoveryRepository()
    trigger = _trigger(commitment, source_event_digest="a" * 64)
    repository.create_or_get_active_case(session, _candidate(commitment, trigger), trigger)

    conflicting = trigger.model_copy(update={"source_event_digest": "b" * 64})
    with pytest.raises(DomainError) as exc_info:
        repository.create_or_get_active_case(session, _candidate(commitment, conflicting), conflicting)

    assert exc_info.value.code == "RECOVERY_EVENT_ID_CONFLICT"


def test_partial_and_full_event_digest_coverage_cannot_be_misreported_as_duplicate(session) -> None:
    commitment = _commitment()
    _persist_commitment(session, commitment)
    repository = SqlAlchemyRecoveryRepository()
    without_source_digest = _trigger(commitment)
    repository.create_or_get_active_case(
        session,
        _candidate(commitment, without_source_digest),
        without_source_digest,
    )

    with_source_digest = without_source_digest.model_copy(update={"source_event_digest": "c" * 64})
    with pytest.raises(DomainError) as exc_info:
        repository.create_or_get_active_case(
            session,
            _candidate(commitment, with_source_digest),
            with_source_digest,
        )

    assert exc_info.value.code == "RECOVERY_EVENT_IDENTITY_UNVERIFIABLE"


def test_active_case_index_is_explicit_and_completed_cases_do_not_occupy_it(session) -> None:
    commitment = _commitment()
    _persist_commitment(session, commitment)
    trigger = _trigger(commitment)
    repository = SqlAlchemyRecoveryRepository()
    case, _, _ = repository.create_or_get_active_case(session, _candidate(commitment, trigger), trigger)

    assert set(ACTIVE_CASE_STATUSES) == {
        "OPEN",
        "AWAITING_EVALUATION_INPUTS",
        "OPTIONS_READY",
        "NO_SAFE_PLAN",
        "NEEDS_REPLAN",
    }
    assert RecoveryCaseStatus.COMPLETED.value not in ACTIVE_CASE_STATUSES

    session.commit()
    for index, status in enumerate(ACTIVE_CASE_STATUSES):
        duplicate_active = case.model_copy(update={
            "case_id": f"rc_second_active_{index}",
            "status": RecoveryCaseStatus(status),
        })
        session.add(RecoveryCaseRecord(
            tenant_id=commitment.tenant_id,
            case_id=duplicate_active.case_id,
            commitment_id=commitment.commitment_id,
            risk_episode_id=f"evt_other_episode_{index}",
            opening_event_id=f"evt_other_episode_{index}",
            status=status,
            case_version=1,
            commitment_version=commitment.commitment_version,
            payload_schema_version=1,
            case_payload=duplicate_active.model_dump(mode="json"),
            resolution_refs=[],
            created_at=commitment.updated_at,
            updated_at=commitment.updated_at,
        ))
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


def test_invalid_case_status_is_rejected_by_persisted_status_constraint(session) -> None:
    commitment = _commitment()
    _persist_commitment(session, commitment)
    trigger = _trigger(commitment)
    repository = SqlAlchemyRecoveryRepository()
    case, _, _ = repository.create_or_get_active_case(session, _candidate(commitment, trigger), trigger)
    session.commit()
    row = session.get(RecoveryCaseRecord, (commitment.tenant_id, case.case_id))
    assert row is not None
    row.status = "NOT_A_RECOVERY_CASE_STATUS"

    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_serialized_case_identity_must_match_indexed_row(session) -> None:
    commitment = _commitment()
    _persist_commitment(session, commitment)
    trigger = _trigger(commitment)
    repository = SqlAlchemyRecoveryRepository()
    case, _, _ = repository.create_or_get_active_case(session, _candidate(commitment, trigger), trigger)
    row = session.get(RecoveryCaseRecord, (commitment.tenant_id, case.case_id))
    assert row is not None
    row.case_payload = {**row.case_payload, "case_id": "rc_tampered_identity"}
    session.flush()

    with pytest.raises(DomainError) as exc_info:
        repository.get_case_by_id(session, commitment.tenant_id, case.case_id)
    assert exc_info.value.code == "RECOVERY_CASE_IDENTITY_CONFLICT"


def test_resolution_preserves_history_and_allows_a_new_risk_episode(session) -> None:
    commitment = _commitment()
    _persist_commitment(session, commitment)
    repository = SqlAlchemyRecoveryRepository()
    first_trigger = _trigger(commitment, event_id="evt_episode_1")
    first_case, _, _ = repository.create_or_get_active_case(
        session,
        _candidate(commitment, first_trigger),
        first_trigger,
    )

    resolved_commitment = commitment.model_copy(update={
        "feasibility_state": FeasibilityState.FEASIBLE,
        "risk_state": RiskState.RESOLVED,
        "recovery_state": RecoveryState.COMPLETED,
        "commitment_version": 6,
    })
    core_row = session.get(CommitmentRecord, (commitment.tenant_id, commitment.commitment_id))
    assert core_row is not None
    core_row.feasibility_state = FeasibilityState.FEASIBLE.value
    core_row.risk_state = RiskState.RESOLVED.value
    core_row.recovery_state = RecoveryState.COMPLETED.value
    core_row.commitment_version = 6
    resolution = RecoveryResolutionReference(
        event_id="evt_resolved_episode_1",
        tenant_id=commitment.tenant_id,
        commitment_id=commitment.commitment_id,
        commitment_version=6,
        assessment_id="fa_resolved_01",
        correlation_id="corr_resolved_01",
        causation_id="assessment-feasible-01",
        occurred_at=datetime(2026, 10, 21, 11, 0, tzinfo=UTC),
    )
    closed, changed = repository.resolve_case(
        session,
        tenant_id=commitment.tenant_id,
        commitment_id=commitment.commitment_id,
        commitment=resolved_commitment,
        resolution=resolution,
    )
    assert changed and closed is not None
    assert closed.status == RecoveryCaseStatus.COMPLETED
    assert closed.resolution_events == [resolution]
    assert repository.get_active_case(session, commitment.tenant_id, commitment.commitment_id) is None

    reopened_commitment = resolved_commitment.model_copy(update={
        "feasibility_state": FeasibilityState.INFEASIBLE,
        "risk_state": RiskState.AT_RISK,
        "recovery_state": RecoveryState.RECOVERY_REQUIRED,
        "commitment_version": 11,
    })
    core_row.feasibility_state = FeasibilityState.INFEASIBLE.value
    core_row.risk_state = RiskState.AT_RISK.value
    core_row.recovery_state = RecoveryState.RECOVERY_REQUIRED.value
    core_row.commitment_version = 11
    second_trigger = _trigger(
        reopened_commitment,
        event_id="evt_episode_2",
        assessment_id="fa_episode_2",
        assessment_version=8,
    )
    second_case, created, duplicate = repository.create_or_get_active_case(
        session,
        _candidate(reopened_commitment, second_trigger),
        second_trigger,
    )

    assert created and not duplicate
    assert second_case.case_id != first_case.case_id
    assert second_case.case_id != ""
    old_case = repository.get_case_by_id(session, commitment.tenant_id, first_case.case_id)
    assert old_case is not None and old_case.status == RecoveryCaseStatus.COMPLETED
    assert repository.get_active_case(session, commitment.tenant_id, commitment.commitment_id).case_id == (
        second_case.case_id
    )


def test_completed_case_with_plan_and_approval_is_immutable_to_new_triggers(session) -> None:
    commitment = _commitment()
    _persist_commitment(session, commitment)
    repository = SqlAlchemyRecoveryRepository()
    first_trigger = _trigger(commitment, event_id="evt_terminal_open")
    case, _, _ = repository.create_or_get_active_case(
        session,
        _candidate(commitment, first_trigger),
        first_trigger,
    )
    record = session.get(RecoveryCaseRecord, (commitment.tenant_id, case.case_id))
    assert record is not None
    enriched = _with_historical_plan_and_approval(case)
    record.case_payload = repository._case_payload(enriched)
    session.flush()

    resolved_commitment = commitment.model_copy(update={
        "feasibility_state": FeasibilityState.FEASIBLE,
        "risk_state": RiskState.RESOLVED,
        "recovery_state": RecoveryState.COMPLETED,
        "commitment_version": 6,
    })
    core_row = session.get(CommitmentRecord, (commitment.tenant_id, commitment.commitment_id))
    assert core_row is not None
    core_row.feasibility_state = FeasibilityState.FEASIBLE.value
    core_row.risk_state = RiskState.RESOLVED.value
    core_row.recovery_state = RecoveryState.COMPLETED.value
    core_row.commitment_version = 6
    resolution = RecoveryResolutionReference(
        event_id="evt_terminal_resolution",
        tenant_id=commitment.tenant_id,
        commitment_id=commitment.commitment_id,
        commitment_version=6,
        assessment_id="fa_terminal_resolved",
        correlation_id="corr_terminal_resolution",
        causation_id="assessment-terminal-resolution",
        occurred_at=datetime(2026, 10, 21, 11, 0, tzinfo=UTC),
    )
    completed, changed = repository.resolve_case(
        session,
        tenant_id=commitment.tenant_id,
        commitment_id=commitment.commitment_id,
        commitment=resolved_commitment,
        resolution=resolution,
    )
    assert changed and completed is not None
    before = repository.get_case_by_id(session, commitment.tenant_id, case.case_id)
    assert before is not None and before.status == RecoveryCaseStatus.COMPLETED
    assert len(before.plans) == 1
    assert [item.approval_id for item in before.approval_decisions[:1]] == ["approval_historical_01"]
    assert before.approval_decisions[-1].decision == ApprovalDecisionState.INVALIDATED

    reopened_commitment = resolved_commitment.model_copy(update={
        "feasibility_state": FeasibilityState.INFEASIBLE,
        "risk_state": RiskState.AT_RISK,
        "recovery_state": RecoveryState.RECOVERY_REQUIRED,
        "commitment_version": 11,
    })
    core_row.feasibility_state = FeasibilityState.INFEASIBLE.value
    core_row.risk_state = RiskState.AT_RISK.value
    core_row.recovery_state = RecoveryState.RECOVERY_REQUIRED.value
    core_row.commitment_version = 11
    new_trigger = _trigger(
        reopened_commitment,
        event_id="evt_terminal_new_episode",
        assessment_id="fa_terminal_new_episode",
        assessment_version=8,
    )
    candidate = _candidate(reopened_commitment, new_trigger).model_copy(update={"case_id": case.case_id})

    with pytest.raises(DomainError) as exc_info:
        repository.append_trigger_idempotently(
            session,
            tenant_id=commitment.tenant_id,
            case_id=case.case_id,
            candidate_case=candidate,
            trigger=new_trigger,
        )

    assert exc_info.value.code == "RECOVERY_CASE_TERMINAL"
    after = repository.get_case_by_id(session, commitment.tenant_id, case.case_id)
    assert after is not None
    assert after.model_dump(mode="json") == before.model_dump(mode="json")
    assert after.plans == before.plans
    assert after.approval_decisions == before.approval_decisions


def test_repository_never_commits_or_rolls_back_the_callers_session(session) -> None:
    commitment = _commitment()
    _persist_commitment(session, commitment)
    trigger = _trigger(commitment)
    repository = SqlAlchemyRecoveryRepository()
    commits: list[bool] = []

    def count_commit(_session):
        commits.append(True)

    event.listen(session, "before_commit", count_commit)
    try:
        repository.create_or_get_active_case(session, _candidate(commitment, trigger), trigger)
        assert session.in_transaction()
        assert commits == []
        session.rollback()
        assert session.query(RecoveryCaseRecord).filter_by(tenant_id=commitment.tenant_id).count() == 0
        assert session.query(RecoveryCaseTriggerRecord).filter_by(tenant_id=commitment.tenant_id).count() == 0
        assert commits == []
    finally:
        event.remove(session, "before_commit", count_commit)


@pytest.mark.parametrize(
    ("assessment_version", "provenance_status"),
    [
        (None, "SOURCE_COMMITMENT_VERSION_MISSING"),
        (3, "SOURCE_COMMITMENT_VERSION_RECORDED_UNVERIFIED"),
    ],
)
def test_missing_or_unverified_assessment_provenance_is_preserved_not_invented(
    session,
    assessment_version,
    provenance_status,
) -> None:
    commitment = _commitment()
    _persist_commitment(session, commitment)
    trigger = _trigger(commitment, assessment_version=assessment_version)
    case, _, _ = SqlAlchemyRecoveryRepository().create_or_get_active_case(
        session,
        _candidate(commitment, trigger),
        trigger,
    )

    stored_trigger = session.get(RecoveryCaseTriggerRecord, (commitment.tenant_id, trigger.event_id))
    assert stored_trigger is not None
    assert stored_trigger.assessment_commitment_version == assessment_version
    assert stored_trigger.assessment_provenance_status == provenance_status
    assert case.trigger_assessment is None
    assert case.status == RecoveryCaseStatus.AWAITING_EVALUATION_INPUTS


def test_case_and_commitment_version_conflicts_fail_without_mutating_case(session) -> None:
    commitment = _commitment()
    _persist_commitment(session, commitment)
    trigger = _trigger(commitment)
    repository = SqlAlchemyRecoveryRepository()
    case, _, _ = repository.create_or_get_active_case(session, _candidate(commitment, trigger), trigger)

    stale_trigger = trigger.model_copy(update={
        "event_id": "evt_stale_version",
        "commitment_version": 4,
    })
    stale_commitment = commitment.model_copy(update={"commitment_version": 4})
    with pytest.raises(DomainError, match="not for the current Commitment version"):
        repository.create_or_get_active_case(
            session,
            _candidate(stale_commitment, stale_trigger),
            stale_trigger,
        )

    another_trigger = _trigger(commitment, event_id="evt_case_conflict", assessment_id="fa_changed")
    with pytest.raises(DomainError, match="Recovery Case version is stale"):
        repository.mark_needs_replan(
            session,
            tenant_id=commitment.tenant_id,
            case_id=case.case_id,
            candidate_case=_candidate(commitment, another_trigger).model_copy(update={"case_id": case.case_id}),
            trigger=another_trigger,
            expected_case_version=case.case_version + 10,
        )
    after = repository.get_case_by_id(session, commitment.tenant_id, case.case_id)
    assert after is not None
    assert after.trigger_events == [trigger]
    assert after.case_version == case.case_version
