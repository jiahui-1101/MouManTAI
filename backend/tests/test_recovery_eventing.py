from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.core.schemas import ApprovalState, FeasibilityState
from app.recovery.eventing import (
    EventPublicationStatus,
    P5OutboxPublisherAdapter,
    PendingRecoveryEventPublisher,
    PlanGeneratedPayload,
    RecoveryEventCoordinator,
    RecoveryEventType,
)
from app.recovery.fixtures import load_demo_recovery_inputs
from app.recovery.handoff import (
    ConfirmationDisposition,
    ConfirmationOutcomeType,
    P4ConfirmationOutcomeHandler,
    PlannerRecoveryInvalidator,
    ProposalHandoffResult,
    ProposalHandoffStatus,
    RecoveryCommunicationHandoff,
    UnavailableP5ProposalPort,
    VerifiedConfirmationOutcome,
    VersionedProposalSnapshot,
)
from app.recovery.models import ApprovalDecision, ApprovalDecisionState
from app.recovery.service import RecoveryPlanner


def test_recovery_event_metadata_and_pending_publisher_are_explicit():
    coordinator = RecoveryEventCoordinator(PendingRecoveryEventPublisher())
    event = coordinator.prepare(
        event_type=RecoveryEventType.PLAN_GENERATED,
        tenant_id="tenant_a",
        commitment_id="com_001",
        commitment_version=4,
        recovery_case_id="case_a",
        plan_id="plan_a",
        plan_version=2,
        snapshot_version=8,
        correlation_id="corr_a",
        causation_id="assessment_a",
        evidence_refs=("ev_a",),
        payload=PlanGeneratedPayload(
            evaluation_id="eval_a", feasibility_status=FeasibilityState.CONDITIONAL,
            action_types=("CREATE_PURCHASE_REQUEST",), recommended_under_policy=False,
        ),
    )
    receipt = coordinator.publish(event)
    assert event.to_p5_domain_event().payload["plan_version"] == 2
    assert event.to_p5_domain_event().payload["evidence_refs"] == ["ev_a"]
    assert receipt.status == EventPublicationStatus.INTEGRATION_PENDING
    assert coordinator.publish(event).event_id == receipt.event_id
    assert len(coordinator.pending_events("tenant_a")) == 1


def test_plan_generation_prepares_events_without_claiming_publication():
    planner = RecoveryPlanner()
    case = planner.generate(
        "tenant_demo_01", "com_001",
        expected_commitment_version=load_demo_recovery_inputs().commitment.commitment_version,
        correlation_id="corr_test", causation_id="cause_test",
    )
    pending = planner.event_coordinator.pending_events("tenant_demo_01")
    assert len(pending) == len(case.plans)
    assert {event.event_type for event in pending} == {RecoveryEventType.PLAN_GENERATED}
    assert all(event.commitment_version == case.commitment_version for event in pending)


def _outcome(event_id: str, kind: ConfirmationOutcomeType, *, proposal_version: int = 1,
             happened: datetime | None = None) -> VerifiedConfirmationOutcome:
    return VerifiedConfirmationOutcome(
        event_id=event_id, event_type=kind, tenant_id="tenant_demo_01", commitment_id="com_001",
        commitment_version=load_demo_recovery_inputs().commitment.commitment_version,
        recovery_case_id="rc_001", plan_id="plan_b", plan_version=1,
        proposal_id="proposal_a", proposal_version=proposal_version,
        occurred_at=happened or datetime.now(UTC), evidence_refs=("customer-response-evidence",),
    )


def test_accepted_response_stays_pending_without_authoritative_p5_p4_dependencies():
    handler = P4ConfirmationOutcomeHandler()
    result = handler.handle(_outcome("evt_accept", ConfirmationOutcomeType.ACCEPTED))
    assert result.disposition == ConfirmationDisposition.INTEGRATION_PENDING


def test_pending_accepted_event_can_retry_and_resume_only_after_exact_version_match():
    handler = P4ConfirmationOutcomeHandler()
    outcome = _outcome("evt_accept_retry", ConfirmationOutcomeType.ACCEPTED)
    assert handler.handle(outcome).disposition == ConfirmationDisposition.INTEGRATION_PENDING

    class Reader:
        def get_proposal(self, tenant_id, commitment_id, proposal_id):
            return VersionedProposalSnapshot(
                tenant_id=tenant_id, commitment_id=commitment_id,
                commitment_version=outcome.commitment_version, proposal_id=proposal_id,
                proposal_version=outcome.proposal_version, status="ACCEPTED", accepted_terms_match=True,
            )

    class Preconditions:
        def validate(self, _outcome, _proposal):
            return True

    class Resumer:
        resumed = False

        def resume(self, _outcome):
            self.resumed = True

    resumer = Resumer()
    handler.proposal_reader = Reader()
    handler.precondition = Preconditions()
    handler.resumer = resumer
    assert handler.handle(outcome).disposition == ConfirmationDisposition.RESUMED
    assert resumer.resumed


def test_p5_adapter_refuses_event_types_not_registered_in_core():
    class Boundary:
        called = False

        def publish(self, *_args):
            self.called = True

    boundary = Boundary()
    coordinator = RecoveryEventCoordinator(P5OutboxPublisherAdapter(boundary))
    event = coordinator.prepare(
        event_type=RecoveryEventType.PLAN_GENERATED, tenant_id="t", commitment_id="c",
        commitment_version=1, recovery_case_id="r", plan_id="p", plan_version=1,
        snapshot_version=1, correlation_id="corr", causation_id=None, evidence_refs=(),
        payload=PlanGeneratedPayload(
            evaluation_id="eval", feasibility_status=FeasibilityState.FEASIBLE,
            action_types=("CREATE_PRODUCTION_TASK",), recommended_under_policy=True,
        ),
    )
    receipt = coordinator.publish(event)
    assert receipt.status == EventPublicationStatus.INTEGRATION_PENDING
    assert receipt.detail_code == "P5_CORE_EVENT_TYPE_UNSUPPORTED"
    assert not boundary.called


def test_rejected_response_invalidates_only_matching_p3_plan_and_is_idempotent():
    planner = RecoveryPlanner()
    planner.generate("tenant_demo_01", "com_001", expected_commitment_version=load_demo_recovery_inputs().commitment.commitment_version)
    handler = P4ConfirmationOutcomeHandler(invalidator=PlannerRecoveryInvalidator(planner))
    outcome = _outcome("evt_reject", ConfirmationOutcomeType.REJECTED)
    result = handler.handle(outcome)
    assert result.disposition == ConfirmationDisposition.INVALIDATED_REPLAN_REQUIRED
    updated = planner.get_plan("tenant_demo_01", "plan_b")
    assert updated.approval_state.value == "INVALIDATED"
    assert updated.execution_state == "NEEDS_REPLAN"
    assert planner.repository.get_case("tenant_demo_01", "com_001").status.value == "NEEDS_REPLAN"
    assert any(event.event_type == RecoveryEventType.REPLAN_REQUIRED
               for event in planner.event_coordinator.pending_events("tenant_demo_01"))
    assert handler.handle(outcome).disposition == ConfirmationDisposition.DUPLICATE


def test_out_of_order_confirmation_event_is_ignored():
    class Invalidate:
        def invalidate(self, _outcome):
            return None

    handler = P4ConfirmationOutcomeHandler(invalidator=Invalidate())
    first = _outcome("evt_new", ConfirmationOutcomeType.REJECTED, proposal_version=2,
                     happened=datetime.now(UTC))
    stale = _outcome("evt_old", ConfirmationOutcomeType.ACCEPTED, proposal_version=1,
                     happened=datetime.now(UTC) - timedelta(minutes=1))
    handler.handle(first)
    assert handler.handle(stale).disposition == ConfirmationDisposition.OUT_OF_ORDER


def test_proposal_handoff_is_pending_without_mutating_confirmed_commitment():
    planner = RecoveryPlanner()
    case = planner.generate("tenant_demo_01", "com_001", expected_commitment_version=load_demo_recovery_inputs().commitment.commitment_version)
    plan = planner.get_plan("tenant_demo_01", "plan_b")
    approval = ApprovalDecision(
        approval_id="approval_a", tenant_id=case.tenant_id, recovery_case_id=case.case_id,
        commitment_id=case.commitment_id, commitment_version=case.commitment_version,
        plan_id=plan.plan_id, plan_version=plan.plan_version, snapshot_version=plan.snapshot_version,
        action_scope=["CREATE_DELIVERY_CHANGE_PROPOSAL"], actor_id="manager_a", actor_role="MANAGER",
        decision=ApprovalDecisionState.APPROVED, approved_cost_limit=Decimal("0.00"),
        reason="approved for test", approved_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(hours=1), evidence_refs=["approval-evidence"],
    )
    case.approval_decisions.append(approval)
    plan.approval_state = ApprovalState.APPROVED
    original_terms = case.commitment.terms.model_dump(mode="json")
    result = RecoveryCommunicationHandoff(proposal_port=UnavailableP5ProposalPort()).prepare(
        case=case, plan=plan, approval=approval, correlation_id="corr_a",
    )
    assert result.communication_event is None
    assert result.status.value == "INTEGRATION_PENDING"
    assert case.commitment.terms.model_dump(mode="json") == original_terms


def test_communication_request_contains_exact_created_proposal_and_version():
    planner = RecoveryPlanner()
    case = planner.generate(
        "tenant_demo_01", "com_001",
        expected_commitment_version=load_demo_recovery_inputs().commitment.commitment_version,
    )
    plan = planner.get_plan(case.tenant_id, "plan_b")
    approval = ApprovalDecision(
        approval_id="approval_ref", tenant_id=case.tenant_id, recovery_case_id=case.case_id,
        commitment_id=case.commitment_id, commitment_version=case.commitment_version,
        plan_id=plan.plan_id, plan_version=plan.plan_version, snapshot_version=plan.snapshot_version,
        action_scope=[action.type for action in plan.actions], actor_id="manager_ref", actor_role="MANAGER",
        decision=ApprovalDecisionState.APPROVED, approved_cost_limit=Decimal("0.00"),
        reason="approved for handoff test", approved_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(hours=1), evidence_refs=["ev_approval_ref"],
    )
    case.approval_decisions.append(approval)
    plan.approval_state = ApprovalState.APPROVED

    class ProposalPort:
        command = None

        def create_recovery_proposal(self, command):
            self.command = command
            return ProposalHandoffResult(
                status=ProposalHandoffStatus.CREATED,
                tenant_id=command.tenant_id,
                commitment_id=command.commitment_id,
                proposal_id="proposal_exact_7",
                proposal_version=7,
                commitment_version=command.expected_commitment_version,
                confirmed_terms_preserved=True,
            )

    proposal_port = ProposalPort()
    coordinator = RecoveryEventCoordinator(PendingRecoveryEventPublisher())
    result = RecoveryCommunicationHandoff(
        proposal_port=proposal_port, events=coordinator,
    ).prepare(case=case, plan=plan, approval=approval, correlation_id="corr_exact")
    assert proposal_port.command.confirmed_terms == case.commitment.terms
    assert result.communication_request_id == "commreq_proposal_exact_7_v7"
    assert result.communication_event.status == EventPublicationStatus.INTEGRATION_PENDING
    event = coordinator.pending_events(case.tenant_id)[0]
    assert event.event_type == RecoveryEventType.COMMUNICATION_REQUESTED
    assert event.payload.proposal_id == "proposal_exact_7"
    assert event.payload.proposal_version == 7
    assert event.payload.communication_request_id == result.communication_request_id
    assert event.plan_id == plan.plan_id and event.plan_version == plan.plan_version
