from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.events import OutboxStatus, create_domain_event
from app.core.models import CommitmentRecord, OutboxEventRecord, ProcessedEventRecord
from app.core.outbox import OutboxDispatcher
from app.core.schemas import (
    AgreementState,
    Commitment,
    ConstraintReason,
    FeasibilityState,
    FulfilmentState,
    RecoveryState,
    RiskState,
)
from app.recovery import router as recovery_api
from app.recovery.fixtures import load_demo_recovery_inputs
from app.recovery.integrations import ActorContext, P5CommitmentReader
from app.recovery.models import ApprovalDecisionInput, RecoveryCaseStatus
from app.recovery.service import RecoveryPlanner, RecoveryRepository
from app.recovery.triggers import (
    RecoveryTriggerConsumer,
    RecoveryTriggerStatus,
    canonical_domain_event_digest,
    register_with_p5_dispatcher,
)


def _commitment(tenant_id: str = "tenant_demo_01", commitment_id: str = "com_trigger_01") -> Commitment:
    source = load_demo_recovery_inputs().commitment
    return source.model_copy(update={
        "tenant_id": tenant_id,
        "commitment_id": commitment_id,
        "agreement_state": AgreementState.CONFIRMED,
        "feasibility_state": FeasibilityState.INFEASIBLE,
        "risk_state": RiskState.AT_RISK,
        "recovery_state": RecoveryState.RECOVERY_REQUIRED,
        "fulfilment_state": FulfilmentState.NOT_STARTED,
        "commitment_version": 5,
    })


def _save_commitment(session, commitment: Commitment) -> None:
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
    session.commit()


def _event(
    commitment: Commitment,
    *,
    event_id: str = "evt_risk_001",
    version: int | None = None,
    assessment_id: str = "fa_risk_001",
    tenant_id: str | None = None,
    feasibility_status: str | None = None,
    assessment_commitment_version: int | None = None,
    evaluated_commitment_version: int | None = None,
    snapshot_id: str | None = None,
    evidence_refs: list[str] | None = None,
):
    payload = {
        "commitment_id": commitment.commitment_id,
        "assessment_id": assessment_id,
        "snapshot_version": 142,
        "constraints": [ConstraintReason(
            code="MATERIAL_SHORTAGE",
            resource_id="PACKAGING",
            shortage=Decimal(2),
            unit="pcs",
            severity="HARD",
            evidence_refs=["ev_shortage_01"],
        ).model_dump(mode="json")],
        "affected_commitment_ids": [commitment.commitment_id],
    }
    if snapshot_id is not None:
        payload["snapshot_id"] = snapshot_id
    if evidence_refs is not None:
        payload["evidence_refs"] = evidence_refs
    if feasibility_status is not None:
        payload["feasibility_status"] = feasibility_status
    if assessment_commitment_version is not None:
        payload["assessment_commitment_version"] = assessment_commitment_version
    if evaluated_commitment_version is not None:
        payload["evaluated_commitment_version"] = evaluated_commitment_version
    return create_domain_event(
        event_id=event_id,
        event_type="commitment.at_risk",
        tenant_id=tenant_id or commitment.tenant_id,
        commitment_id=commitment.commitment_id,
        commitment_version=version or commitment.commitment_version,
        correlation_id="corr_trigger_01",
        causation_id="assessment-command-01",
        occurred_at=datetime(2026, 10, 21, 10, 0, tzinfo=UTC),
        payload=payload,
    )


def _resolution_event(commitment: Commitment, *, event_id: str = "evt_resolved_001", version: int = 6):
    return create_domain_event(
        event_id=event_id,
        event_type="commitment.lifecycle_changed",
        tenant_id=commitment.tenant_id,
        commitment_id=commitment.commitment_id,
        commitment_version=version,
        correlation_id="corr_resolution_01",
        causation_id="assessment-feasible-01",
        occurred_at=datetime(2026, 10, 21, 10, 5, tzinfo=UTC),
        payload={
            "commitment_id": commitment.commitment_id,
            "assessment_id": "fa_resolved_001",
            "feasibility_state": "FEASIBLE",
        },
    )


def _consumer() -> tuple[RecoveryTriggerConsumer, RecoveryPlanner]:
    planner = RecoveryPlanner(repository=RecoveryRepository())
    return RecoveryTriggerConsumer(
        planner=planner,
        commitment_reader=P5CommitmentReader(),
        allow_synthetic_processing_for_tests=True,
    ), planner


def test_at_risk_event_creates_trigger_only_case_and_preserves_event_without_core_mutation(session) -> None:
    commitment = _commitment()
    _save_commitment(session, commitment)
    consumer, planner = _consumer()

    outcome = consumer.handle(session, _event(commitment))

    assert outcome.status == RecoveryTriggerStatus.CASE_CREATED
    case = planner.get_case(commitment.tenant_id, commitment.commitment_id)
    assert case is not None
    assert case.status == RecoveryCaseStatus.AWAITING_EVALUATION_INPUTS
    assert case.commitment_version == commitment.commitment_version
    assert case.trigger_assessment is None
    assert case.operational_snapshot is None
    assert case.plans == []
    assert len(case.trigger_events) == 1
    trigger = case.trigger_events[0]
    assert (trigger.event_id, trigger.tenant_id, trigger.commitment_id) == (
        "evt_risk_001", commitment.tenant_id, commitment.commitment_id,
    )
    assert trigger.commitment_version == commitment.commitment_version
    assert trigger.assessment_id == "fa_risk_001"
    assert trigger.assessment_commitment_version is None
    assert trigger.assessment_provenance_status == "SOURCE_COMMITMENT_VERSION_MISSING"
    assert trigger.snapshot_version == 142
    assert trigger.affected_commitment_ids == [commitment.commitment_id]
    assert trigger.correlation_id == "corr_trigger_01"
    assert trigger.causation_id == "assessment-command-01"
    assert trigger.evidence_refs == ["ev_shortage_01"]
    with pytest.raises(DomainError) as exc_info:
        planner.get_case("tenant_other", commitment.commitment_id)
    assert exc_info.value.code == "RECOVERY_CASE_NOT_FOUND"

    current = P5CommitmentReader().get_commitment(
        session,
        # The consumer constructs the same internal read-only context.
        RequestContext(
            tenant_id=commitment.tenant_id,
            actor_id="service_core",
            actor_role="SERVICE",
            correlation_id="corr_readback",
        ),
        commitment.commitment_id,
    )
    after = (
        current.terms.model_dump(mode="json"),
        current.agreement_state.value,
        current.feasibility_state.value,
        current.risk_state.value,
        current.recovery_state.value,
        current.fulfilment_state.value,
        current.commitment_version,
        current.evidence_refs,
    )
    assert after == (
        commitment.terms.model_dump(mode="json"),
        commitment.agreement_state.value,
        commitment.feasibility_state.value,
        commitment.risk_state.value,
        commitment.recovery_state.value,
        commitment.fulfilment_state.value,
        commitment.commitment_version,
        commitment.evidence_refs,
    )


def test_duplicate_event_is_idempotent_and_distinct_alert_for_same_assessment_reuses_case(session) -> None:
    commitment = _commitment()
    _save_commitment(session, commitment)
    consumer, planner = _consumer()
    first_event = _event(commitment)

    first = consumer.handle(session, first_event)
    duplicate = consumer.handle(session, first_event)
    retry_with_new_event_id = consumer.handle(
        session,
        _event(commitment, event_id="evt_risk_retry", assessment_id="fa_risk_001"),
    )
    row = session.get(CommitmentRecord, (commitment.tenant_id, commitment.commitment_id))
    assert row is not None
    row.risk_state = RiskState.RESOLVED.value
    row.commitment_version += 1
    session.commit()
    duplicate_after_state_change = consumer.handle(session, first_event)

    assert first.status == RecoveryTriggerStatus.CASE_CREATED
    assert duplicate.status == RecoveryTriggerStatus.DUPLICATE
    assert duplicate_after_state_change.status == RecoveryTriggerStatus.DUPLICATE
    assert retry_with_new_event_id.status == RecoveryTriggerStatus.CASE_REUSED
    case = planner.repository.get_case(commitment.tenant_id, commitment.commitment_id)
    assert case is not None
    assert case.case_id == first.recovery_case_id == retry_with_new_event_id.recovery_case_id
    assert [item.event_id for item in case.trigger_events] == ["evt_risk_001", "evt_risk_retry"]


def test_same_event_id_with_changed_domain_event_content_is_an_integrity_conflict(session) -> None:
    commitment = _commitment()
    _save_commitment(session, commitment)
    consumer, _ = _consumer()
    original = _event(commitment, event_id="evt_content_conflict")
    assert consumer.handle(session, original).status == RecoveryTriggerStatus.CASE_CREATED

    changed = _event(
        commitment,
        event_id="evt_content_conflict",
        evidence_refs=["ev_changed_after_delivery"],
    )
    with pytest.raises(DomainError) as exc_info:
        consumer.handle(session, changed)

    assert exc_info.value.code == "RECOVERY_EVENT_ID_CONFLICT"


def test_stale_and_future_event_versions_are_rejected_without_case_creation(session) -> None:
    commitment = _commitment()
    _save_commitment(session, commitment)
    consumer, planner = _consumer()

    stale = consumer.handle(session, _event(commitment, event_id="evt_stale", version=4))
    future = consumer.handle(session, _event(commitment, event_id="evt_future", version=6))

    assert stale.status == RecoveryTriggerStatus.REJECTED_STALE
    assert future.status == RecoveryTriggerStatus.REJECTED_VERSION_MISMATCH
    assert planner.repository.get_case(commitment.tenant_id, commitment.commitment_id) is None


def test_pre_transition_assessment_version_is_not_compared_equal_to_event_version(session) -> None:
    commitment = _commitment()
    _save_commitment(session, commitment)
    consumer, planner = _consumer()

    outcome = consumer.handle(
        session,
        _event(commitment, assessment_commitment_version=3),
    )
    assert outcome.status == RecoveryTriggerStatus.CASE_CREATED
    trigger = planner.get_case(commitment.tenant_id, commitment.commitment_id).trigger_events[0]
    assert trigger.commitment_version == 5
    assert trigger.assessment_commitment_version == 3
    assert trigger.assessment_provenance_status == "SOURCE_COMMITMENT_VERSION_RECORDED_UNVERIFIED"

    same_version = consumer.handle(
        session,
        _event(commitment, event_id="evt_same_source_version", assessment_commitment_version=5),
    )
    assert same_version.status == RecoveryTriggerStatus.REJECTED_MALFORMED
    assert len(planner.get_case(commitment.tenant_id, commitment.commitment_id).trigger_events) == 1


def test_canonical_p2_assessment_fields_and_constraints_are_preserved_as_unverified(session) -> None:
    commitment = _commitment()
    _save_commitment(session, commitment)
    consumer, planner = _consumer()
    event = _event(
        commitment,
        event_id="evt_canonical_payload",
        evaluated_commitment_version=3,
        snapshot_id="snapshot_p2_142",
        evidence_refs=["ev_p2_top_level"],
    )

    outcome = consumer.handle(session, event)

    assert outcome.status == RecoveryTriggerStatus.CASE_CREATED
    trigger = planner.get_case(commitment.tenant_id, commitment.commitment_id).trigger_events[0]
    assert trigger.assessment_commitment_version == 3
    assert trigger.assessment_provenance_status == "SOURCE_COMMITMENT_VERSION_RECORDED_UNVERIFIED"
    assert trigger.commitment_version == 5
    assert (trigger.snapshot_id, trigger.snapshot_version) == ("snapshot_p2_142", 142)
    assert trigger.evidence_refs == ["ev_p2_top_level", "ev_shortage_01"]
    assert trigger.constraints[0].code == "MATERIAL_SHORTAGE"
    assert trigger.constraints[0].severity == "HARD"
    assert trigger.constraints[0].evidence_refs == ["ev_shortage_01"]
    assert (trigger.correlation_id, trigger.causation_id) == ("corr_trigger_01", "assessment-command-01")
    assert trigger.source_event_digest == canonical_domain_event_digest(event)
    assert trigger.source_event_digest is not None


def test_conflicting_canonical_and_legacy_assessed_version_aliases_fail_closed(session) -> None:
    commitment = _commitment()
    _save_commitment(session, commitment)
    consumer, planner = _consumer()
    conflicting = _event(
        commitment,
        event_id="evt_conflicting_version_aliases",
        assessment_commitment_version=2,
        evaluated_commitment_version=3,
    )

    outcome = consumer.handle(session, conflicting)

    assert outcome.status == RecoveryTriggerStatus.REJECTED_MALFORMED
    assert planner.repository.get_case(commitment.tenant_id, commitment.commitment_id) is None


def test_offered_agreement_state_remains_ineligible_until_p5_separates_proposal_lifecycle() -> None:
    commitment = _commitment().model_copy(update={"agreement_state": AgreementState.OFFERED})
    planner = RecoveryPlanner(repository=RecoveryRepository())

    class OfferedCommitmentReader:
        def get_commitment(self, db, context, commitment_id):
            return commitment

    consumer = RecoveryTriggerConsumer(
        planner=planner,
        commitment_reader=OfferedCommitmentReader(),
        allow_synthetic_processing_for_tests=True,
    )
    outcome = consumer.handle(None, _event(commitment))

    assert outcome.status == RecoveryTriggerStatus.REJECTED_INELIGIBLE
    assert planner.repository.get_case(commitment.tenant_id, commitment.commitment_id) is None


def test_wrong_tenant_and_non_infeasible_authoritative_commitments_are_rejected(session) -> None:
    commitment = _commitment()
    _save_commitment(session, commitment)
    consumer, planner = _consumer()

    wrong_tenant = consumer.handle(
        session,
        _event(commitment, event_id="evt_wrong_tenant", tenant_id="tenant_other"),
    )
    assert wrong_tenant.status == RecoveryTriggerStatus.REJECTED_WRONG_TENANT_OR_MISSING

    # Even a mislabeled at-risk event cannot override the authoritative state.
    row = session.get(CommitmentRecord, (commitment.tenant_id, commitment.commitment_id))
    assert row is not None
    row.feasibility_state = FeasibilityState.CONDITIONAL.value
    session.commit()
    conditional = consumer.handle(session, _event(commitment, event_id="evt_conditional"))
    assert conditional.status == RecoveryTriggerStatus.REJECTED_INELIGIBLE
    assert planner.repository.get_case(commitment.tenant_id, commitment.commitment_id) is None


def test_unknown_or_conditional_trigger_claim_and_malformed_payload_never_create_case(session) -> None:
    commitment = _commitment()
    _save_commitment(session, commitment)
    consumer, planner = _consumer()

    conditional_claim = consumer.handle(
        session,
        _event(commitment, event_id="evt_conditional_claim", feasibility_status="CONDITIONAL"),
    )
    unknown_claim = consumer.handle(
        session,
        _event(commitment, event_id="evt_unknown_claim", feasibility_status="UNKNOWN"),
    )
    malformed = create_domain_event(
        event_id="evt_malformed",
        event_type="commitment.at_risk",
        tenant_id=commitment.tenant_id,
        commitment_id=commitment.commitment_id,
        commitment_version=commitment.commitment_version,
        correlation_id="corr_malformed",
        occurred_at=datetime(2026, 10, 21, 10, 0, tzinfo=UTC),
        payload={"snapshot_version": 142},
    )
    mismatched_identity = _event(commitment, event_id="evt_payload_identity_mismatch").model_copy(
        update={"payload": {**_event(commitment).payload, "commitment_id": "com_other"}},
    )
    malformed_result = consumer.handle(session, malformed)
    mismatched_result = consumer.handle(session, mismatched_identity)

    assert conditional_claim.status == RecoveryTriggerStatus.REJECTED_MALFORMED
    assert unknown_claim.status == RecoveryTriggerStatus.REJECTED_MALFORMED
    assert malformed_result.status == RecoveryTriggerStatus.REJECTED_MALFORMED
    assert mismatched_result.status == RecoveryTriggerStatus.REJECTED_MALFORMED
    assert planner.repository.get_case(commitment.tenant_id, commitment.commitment_id) is None


def test_event_created_case_cannot_plan_from_demo_fallback(session) -> None:
    commitment = _commitment(commitment_id="com_001").model_copy(update={"commitment_version": 3})
    _save_commitment(session, commitment)
    consumer, planner = _consumer()
    outcome = consumer.handle(session, _event(commitment))
    assert outcome.status == RecoveryTriggerStatus.CASE_CREATED

    with pytest.raises(DomainError) as exc_info:
        planner.generate(
            commitment.tenant_id,
            commitment.commitment_id,
            expected_commitment_version=commitment.commitment_version,
            assessment_id=load_demo_recovery_inputs().assessment.assessment_id,
        )
    assert exc_info.value.code == "AUTHORITATIVE_RECOVERY_INPUT_REQUIRED"
    assert exc_info.value.status_code == 409


def test_trigger_only_case_is_readable_and_legacy_case_route_reports_business_pending(
    session,
    client: TestClient,
    monkeypatch,
) -> None:
    commitment = _commitment()
    _save_commitment(session, commitment)
    consumer, planner = _consumer()
    assert consumer.handle(session, _event(commitment)).status == RecoveryTriggerStatus.CASE_CREATED
    monkeypatch.setattr(recovery_api, "default_recovery_planner", planner)

    response = client.get(
        f"/v1/recovery/cases/{commitment.commitment_id}",
        headers={"X-Tenant-ID": commitment.tenant_id, "X-Actor-ID": "user_manager_01"},
    )
    trigger_view = client.get(
        f"/v1/recovery/cases/{commitment.commitment_id}/trigger",
        headers={"X-Tenant-ID": commitment.tenant_id, "X-Actor-ID": "user_manager_01"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "RECOVERY_EVALUATION_INPUTS_PENDING"
    assert trigger_view.status_code == 200
    body = trigger_view.json()
    assert body["evaluation_readiness"] == "AWAITING_EVALUATION_INPUTS"
    assert body["missing_evaluation_inputs"] == [
        "P2_FEASIBILITY_ASSESSMENT",
        "AUTHORITATIVE_OPERATIONAL_SNAPSHOT",
    ]
    assert body["trigger_events"][0]["assessment_provenance_status"] == "SOURCE_COMMITMENT_VERSION_MISSING"


def test_new_trigger_reuses_case_and_marks_old_plans_for_replan_without_mutating_them(session) -> None:
    commitment = _commitment(commitment_id="com_001")
    _save_commitment(session, commitment)
    planner = RecoveryPlanner(repository=RecoveryRepository())
    existing = planner.generate(
        commitment.tenant_id,
        commitment.commitment_id,
        expected_commitment_version=3,
        assessment_id="fa_001",
    )
    original_plans = [plan.model_dump(mode="json") for plan in existing.plans]
    original_decisions = [item.model_dump(mode="json") for item in existing.approval_decisions]
    consumer = RecoveryTriggerConsumer(
        planner=planner,
        commitment_reader=P5CommitmentReader(),
        allow_synthetic_processing_for_tests=True,
    )

    outcome = consumer.handle(session, _event(commitment, event_id="evt_material_new_assessment"))

    updated = planner.repository.get_case(commitment.tenant_id, commitment.commitment_id)
    assert outcome.status == RecoveryTriggerStatus.CASE_REUSED
    assert updated is not None
    assert updated.case_id == existing.case_id
    assert updated.status == RecoveryCaseStatus.NEEDS_REPLAN
    assert updated.commitment_version == commitment.commitment_version
    assert [plan.model_dump(mode="json") for plan in updated.plans] == original_plans
    assert [item.model_dump(mode="json") for item in updated.approval_decisions[:len(original_decisions)]] == original_decisions
    assert updated.approval_decisions[-1].decision.value == "INVALIDATED"
    assert updated.approval_decisions[-1].plan_id == "plan_a"
    stale_approval_request = ApprovalDecisionInput(
        expected_commitment_version=3,
        expected_plan_version=1,
        expected_snapshot_version=existing.plans[0].snapshot_version,
        reason="Attempt to reuse the prior approval after a new trigger",
    )
    with pytest.raises(DomainError) as exc_info:
        planner.get_active_approval(
            ActorContext(commitment.tenant_id, "manager_01", "MANAGER", "corr_test", None, True),
            existing.plans[0].plan_id,
            stale_approval_request,
        )
    assert exc_info.value.code == "COMMITMENT_VERSION_CONFLICT"


def test_registration_fails_closed_until_durable_p3_and_authoritative_p2_are_wired() -> None:
    dispatcher = OutboxDispatcher()
    consumer = RecoveryTriggerConsumer(planner=RecoveryPlanner(repository=RecoveryRepository()))

    with pytest.raises(DomainError) as exc_info:
        register_with_p5_dispatcher(consumer, dispatcher=dispatcher)

    assert exc_info.value.code == "DURABLE_RECOVERY_INTEGRATION_PENDING"
    assert dispatcher.get_subscribers("commitment.at_risk") == []
    assert dispatcher.get_subscribers("commitment.lifecycle_changed") == []


def test_existing_p5_outbox_dispatcher_invokes_registered_p3_handler(session) -> None:
    commitment = _commitment()
    _save_commitment(session, commitment)
    event = _event(commitment)
    session.add(OutboxEventRecord(
        event_id=event.event_id,
        tenant_id=event.tenant_id,
        event_type=event.event_type,
        commitment_id=event.commitment_id,
        commitment_version=event.commitment_version,
        correlation_id=event.correlation_id,
        causation_id=event.causation_id,
        occurred_at=event.occurred_at,
        payload=event.payload,
        status=OutboxStatus.PENDING.value,
    ))
    session.commit()
    dispatcher = OutboxDispatcher()
    planner = RecoveryPlanner(repository=RecoveryRepository())
    consumer = RecoveryTriggerConsumer(planner=planner, commitment_reader=P5CommitmentReader())
    # Simulate an accidental direct registration: the handler must still fail
    # closed and the P5 dispatcher must not persist a success marker.
    dispatcher.register_subscriber(event.event_type, consumer.consumer_name, consumer.handle)

    result = dispatcher.process_outbox_batch(session)

    assert result.failed_count == 1
    assert result.published_count == 0
    assert session.get(ProcessedEventRecord, (event.tenant_id, event.event_id, consumer.consumer_name)) is None
    assert planner.repository.get_case(commitment.tenant_id, commitment.commitment_id) is None


def test_resolution_closes_old_episode_and_later_risk_creates_separate_case(session) -> None:
    commitment = _commitment()
    _save_commitment(session, commitment)
    consumer, planner = _consumer()
    first = consumer.handle(session, _event(commitment, assessment_commitment_version=3))
    assert first.status == RecoveryTriggerStatus.CASE_CREATED
    unrelated = _resolution_event(commitment, event_id="evt_unknown_lifecycle", version=5).model_copy(
        update={
            "payload": {
                "commitment_id": commitment.commitment_id,
                "assessment_id": "fa_unknown_001",
                "feasibility_state": "UNKNOWN",
            }
        }
    )
    ignored = consumer.handle_commitment_lifecycle_changed(session, unrelated)
    assert ignored.status == RecoveryTriggerStatus.IGNORED_UNRELATED
    assert planner.repository.get_case(commitment.tenant_id, commitment.commitment_id).status == (
        RecoveryCaseStatus.AWAITING_EVALUATION_INPUTS
    )

    row = session.get(CommitmentRecord, (commitment.tenant_id, commitment.commitment_id))
    assert row is not None
    row.feasibility_state = FeasibilityState.FEASIBLE.value
    row.risk_state = RiskState.RESOLVED.value
    row.recovery_state = RecoveryState.COMPLETED.value
    row.commitment_version = 6
    session.commit()
    resolution = _resolution_event(commitment, version=6)

    closed = consumer.handle_commitment_lifecycle_changed(session, resolution)
    duplicate_resolution = consumer.handle_commitment_lifecycle_changed(session, resolution)
    old_case = planner.repository.get_case_by_id(commitment.tenant_id, first.recovery_case_id)
    assert closed.status == RecoveryTriggerStatus.CASE_COMPLETED
    assert duplicate_resolution.status == RecoveryTriggerStatus.DUPLICATE
    assert old_case is not None
    assert old_case.status == RecoveryCaseStatus.COMPLETED
    assert old_case.resolution_events[0].event_id == resolution.event_id

    # A later risk episode need not be exactly version + 1; it is accepted only
    # because its own version matches the authoritative P5 Commitment.
    row.feasibility_state = FeasibilityState.INFEASIBLE.value
    row.risk_state = RiskState.AT_RISK.value
    row.recovery_state = RecoveryState.RECOVERY_REQUIRED.value
    row.commitment_version = 11
    session.commit()
    next_commitment = P5CommitmentReader().get_commitment(
        session,
        RequestContext(
            tenant_id=commitment.tenant_id,
            actor_id="service_core",
            actor_role="SERVICE",
            correlation_id="corr_next_episode",
        ),
        commitment.commitment_id,
    )
    next_event = _event(
        next_commitment,
        event_id="evt_risk_episode_2",
        assessment_id="fa_risk_002",
        version=11,
    )
    second = consumer.handle(session, next_event)
    active_case = planner.repository.get_case(commitment.tenant_id, commitment.commitment_id)
    preserved_old_case = planner.repository.get_case_by_id(commitment.tenant_id, first.recovery_case_id)
    assert second.status == RecoveryTriggerStatus.CASE_CREATED
    assert second.recovery_case_id != first.recovery_case_id
    assert active_case is not None and active_case.case_id == second.recovery_case_id
    assert preserved_old_case is not None
    assert preserved_old_case.status == RecoveryCaseStatus.COMPLETED
    assert preserved_old_case.trigger_events[0].assessment_id == "fa_risk_001"
    late_resolution = consumer.handle_commitment_lifecycle_changed(
        session,
        _resolution_event(commitment, event_id="evt_late_resolution", version=6),
    )
    assert late_resolution.status == RecoveryTriggerStatus.REJECTED_STALE
    assert planner.repository.get_case(commitment.tenant_id, commitment.commitment_id).case_id == (
        second.recovery_case_id
    )


def test_out_of_order_trigger_does_not_replace_newer_case_state(session) -> None:
    commitment = _commitment()
    _save_commitment(session, commitment)
    consumer, planner = _consumer()
    created = consumer.handle(session, _event(commitment))
    before = planner.repository.get_case(commitment.tenant_id, commitment.commitment_id)

    row = session.get(CommitmentRecord, (commitment.tenant_id, commitment.commitment_id))
    assert row is not None
    row.commitment_version = 6
    session.commit()
    stale = consumer.handle(session, _event(commitment, event_id="evt_out_of_order", version=5))
    after = planner.repository.get_case(commitment.tenant_id, commitment.commitment_id)

    assert stale.status == RecoveryTriggerStatus.REJECTED_STALE
    assert after is not None and before is not None
    assert after.case_id == created.recovery_case_id
    assert after.case_version == before.case_version
    assert after.trigger_events == before.trigger_events


def test_event_matching_core_cannot_downgrade_a_newer_p3_case_version(session) -> None:
    commitment = _commitment()
    _save_commitment(session, commitment)
    consumer, planner = _consumer()
    first = consumer.handle(session, _event(commitment))
    before = planner.repository.get_case(commitment.tenant_id, commitment.commitment_id)
    assert before is not None
    planner.repository.save_case(before.model_copy(update={"commitment_version": 7}))

    outcome = consumer.handle(
        session,
        _event(commitment, event_id="evt_downgrade_attempt", version=5),
    )
    after = planner.repository.get_case(commitment.tenant_id, commitment.commitment_id)

    assert outcome.status == RecoveryTriggerStatus.REJECTED_STALE
    assert outcome.recovery_case_id is None
    assert after is not None
    assert after.case_id == first.recovery_case_id
    assert after.commitment_version == 7
    assert after.trigger_events == before.trigger_events


def test_concurrent_delivery_creates_one_case_and_one_trigger_record() -> None:
    commitment = _commitment()
    planner = RecoveryPlanner(repository=RecoveryRepository())

    class StaticCommitmentReader:
        def get_commitment(self, db, context, commitment_id):
            return commitment

    consumer = RecoveryTriggerConsumer(
        planner=planner,
        commitment_reader=StaticCommitmentReader(),
        allow_synthetic_processing_for_tests=True,
    )
    event = _event(commitment)
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(lambda _: consumer.handle(None, event), range(16)))

    case = planner.repository.get_case(commitment.tenant_id, commitment.commitment_id)
    assert sum(outcome.status == RecoveryTriggerStatus.CASE_CREATED for outcome in outcomes) == 1
    assert sum(outcome.status == RecoveryTriggerStatus.DUPLICATE for outcome in outcomes) == 15
    assert case is not None and len(case.trigger_events) == 1
