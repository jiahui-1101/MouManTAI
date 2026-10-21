from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from app.core.dependencies import RequestContext
from app.core.schemas import FeasibilityState, PlannedAction
from app.recovery.actions import (
    ActionStatus,
    FailureMode,
    RecoveryActionType,
    SyntheticActionAdapter,
)
from app.recovery.integrations import ActorContext, IntegrationSource, VersionedSnapshot
from app.recovery.models import (
    ApprovalDecisionInput,
    ApprovalRequestInput,
    ValidationSource,
)
from app.recovery.orchestrator import (
    ExecutionMode,
    ExecutionRequest,
    GovernedRecoveryOrchestrator,
    InMemoryActionDependencyProvider,
    P2PlanRevalidatorAdapter,
    PlanReevaluation,
    WorkflowStatus,
)
from app.recovery.service import RecoveryPlanner, RecoveryRepository


class ActorProvider:
    def __init__(self, actor):
        self.actor = actor

    def get_verified_context(self, context):
        del context
        return self.actor


class CommitmentProvider:
    def __init__(self, commitment):
        self.commitment = commitment

    def get_commitment(self, db, context, commitment_id, *, expected_commitment_version=None):
        del db, context
        assert commitment_id == self.commitment.commitment_id
        if expected_commitment_version is not None:
            assert expected_commitment_version == self.commitment.commitment_version
        return self.commitment


class SnapshotProvider:
    def __init__(self, plan, *, version=None, source=IntegrationSource.SYNTHETIC_TEST_DOUBLE):
        self.plan = plan
        self.version = version or plan.snapshot_version
        self.source = source

    def get_snapshot(self, context, commitment, *, expected_snapshot_version=None):
        del context, expected_snapshot_version
        return VersionedSnapshot(
            snapshot=SimpleNamespace(
                tenant_id=commitment.tenant_id, commitment_id=commitment.commitment_id,
                snapshot_id=f"snap_{self.version}", snapshot_version=self.version,
            ),
            tenant_id=commitment.tenant_id, commitment_id=commitment.commitment_id,
            commitment_version=commitment.commitment_version, snapshot_id=f"snap_{self.version}",
            snapshot_version=self.version, captured_at=datetime.now(UTC), source=self.source,
        )


class Revalidator:
    def __init__(self, status="FEASIBLE", source=IntegrationSource.SYNTHETIC_TEST_DOUBLE):
        self.status = status
        self.source = source
        self.calls = []

    def evaluate_plan(self, snapshot, plan, commitment):
        self.calls.append((snapshot.snapshot_version, plan.plan_version, commitment.commitment_version))
        return PlanReevaluation(
            evaluation_id="eval_latest", tenant_id=commitment.tenant_id,
            commitment_id=commitment.commitment_id, commitment_version=commitment.commitment_version,
            plan_id=plan.plan_id, plan_version=plan.plan_version,
            snapshot_id=snapshot.snapshot_id, snapshot_version=snapshot.snapshot_version,
            status=self.status, source=self.source, evidence_refs=("ev_latest_eval",),
            evaluated_at=datetime.now(UTC),
        )


def make_orchestrator(*, status="FEASIBLE", snapshot_version=None, actor_overrides=None,
                      dependencies=(), action_defs=None, live_candidate=False, source=None):
    planner = RecoveryPlanner(repository=RecoveryRepository())
    inputs = planner.inputs
    case = planner.generate(
        inputs.commitment.tenant_id, inputs.commitment.commitment_id,
        expected_commitment_version=inputs.commitment.commitment_version,
    )
    plan = case.plans[0]
    if action_defs is None:
        action_defs = [("act_purchase", RecoveryActionType.CREATE_PURCHASE_REQUEST, {
            "resource_id": "PACKAGING", "supplier_id": "SUPPLIER_1", "quantity": "2.5",
            "unit": "box", "estimated_cost_myr": "10.05",
        })]
    plan.actions = [PlannedAction(
        action_id=action_id, type=action_type.value, requires_approval=True,
        idempotency_key=f"idem_{action_id}", parameters={"action_type": action_type.value, **params},
    ) for action_id, action_type, params in action_defs]
    plan.evaluation.validation_source = ValidationSource.REAL_P2_VALIDATED
    planner.repository.save_case(case)
    actor = ActorContext(case.tenant_id, "manager_1", "MANAGER", "corr_exec", "cause_exec", True)
    request = ApprovalRequestInput(
        expected_commitment_version=plan.evaluation.commitment_version,
        expected_plan_version=plan.plan_version, expected_snapshot_version=plan.snapshot_version,
        action_scope=sorted({action.type for action in plan.actions}),
        maximum_approved_amount=Decimal("100.00"), reason="Synthetic test approval",
        expires_at=datetime.now(UTC) + timedelta(hours=1), idempotency_key="approval_exec",
    )
    planner.request_approval(actor, plan.plan_id, request)
    approval_check = ApprovalDecisionInput(
        expected_commitment_version=plan.evaluation.commitment_version,
        expected_plan_version=plan.plan_version, expected_snapshot_version=plan.snapshot_version,
        reason="Approved in test setup",
    )
    planner.approve_plan(actor, plan.plan_id, approval_check)
    # Explicitly designate this execution as test-double-only after creating a stored approval.
    case = planner.get_case(case.tenant_id, case.commitment_id)
    plan = case.plans[0]
    plan.evaluation.validation_source = (
        ValidationSource.REAL_P2_VALIDATED if live_candidate else ValidationSource.TEST_DOUBLE_VALIDATED
    )
    planner.repository.save_case(case)

    trusted_actor = actor
    if actor_overrides:
        trusted_actor = ActorContext(
            actor_overrides.get("tenant_id", actor.tenant_id), actor_overrides.get("actor_id", actor.actor_id),
            actor_overrides.get("actor_role", actor.actor_role), actor.correlation_id, actor.causation_id,
            actor_overrides.get("verified", actor.verified),
        )
    commitment = inputs.commitment
    sim_source = source or IntegrationSource.SYNTHETIC_TEST_DOUBLE
    revalidator = Revalidator(status, source=sim_source)
    snapshot_provider = SnapshotProvider(plan, version=snapshot_version, source=sim_source)
    action_adapter = SyntheticActionAdapter(planner)
    orchestrator = GovernedRecoveryOrchestrator(
        planner=planner, actor_provider=ActorProvider(trusted_actor),
        commitment_reader=CommitmentProvider(commitment), snapshot_provider=snapshot_provider,
        revalidator=revalidator, action_adapter=action_adapter,
        dependency_provider=InMemoryActionDependencyProvider({(plan.plan_id, plan.plan_version): dependencies}),
        simulation_enabled=not live_candidate,
    )
    context = RequestContext(case.tenant_id, "header_actor_untrusted", "STAFF", "corr_request")
    request = ExecutionRequest(
        plan_id=plan.plan_id, commitment_id=plan.commitment_id,
        expected_plan_version=plan.plan_version,
        expected_commitment_version=plan.evaluation.commitment_version,
        idempotency_key="workflow_1",
    )
    return orchestrator, context, request, plan, revalidator


def test_orchestrator_simulation_observes_governed_order_and_does_not_change_commitment():
    orchestrator, context, request, plan, revalidator = make_orchestrator()
    original_commitment = orchestrator.planner.inputs.commitment.model_dump(mode="python")
    result = orchestrator.execute(context, None, request)
    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.mode == ExecutionMode.CONTROLLED_TEST_SIMULATION
    assert [attempt.status for attempt in result.attempts] == [
        WorkflowStatus.PENDING, WorkflowStatus.VALIDATING, WorkflowStatus.EXECUTING,
        WorkflowStatus.VERIFYING, WorkflowStatus.SUCCEEDED,
    ]
    assert result.action_results[0].status == ActionStatus.SUCCEEDED
    assert revalidator.calls == [(plan.snapshot_version, plan.plan_version, plan.evaluation.commitment_version)]
    assert orchestrator.planner.inputs.commitment.model_dump(mode="python") == original_commitment
    assert result.persistence_mode == "IN_MEMORY_NON_DURABLE"


def test_orchestrator_idempotency_returns_prior_result_without_duplicate_record():
    orchestrator, context, request, _, _ = make_orchestrator()
    first = orchestrator.execute(context, None, request)
    second = orchestrator.execute(context, None, request)
    assert first == second
    assert len(orchestrator.action_adapter.repository._records) == 1


def test_stale_snapshot_and_unknown_p2_result_block_before_action_writes():
    stale, context, request, _, _ = make_orchestrator(snapshot_version=plan_snapshot_plus_one())
    stale_result = stale.execute(context, None, request)
    assert stale_result.status == WorkflowStatus.NEEDS_REPLAN
    assert stale.action_adapter.repository._records == {}

    unknown, context, request, _, _ = make_orchestrator(status="UNKNOWN")
    unknown_result = unknown.execute(context, None, request)
    assert unknown_result.status == WorkflowStatus.NEEDS_REPLAN
    assert unknown.action_adapter.repository._records == {}

    infeasible, context, request, _, _ = make_orchestrator(status="INFEASIBLE")
    infeasible_result = infeasible.execute(context, None, request)
    assert infeasible_result.status == WorkflowStatus.NEEDS_REPLAN
    assert infeasible.action_adapter.repository._records == {}


def plan_snapshot_plus_one():
    return 2


def test_p2_plan_revalidator_calls_evaluate_snapshot_proposal_commitment_contract():
    planner = RecoveryPlanner()
    case = planner.generate(
        planner.inputs.commitment.tenant_id,
        planner.inputs.commitment.commitment_id,
        expected_commitment_version=planner.inputs.commitment.commitment_version,
    )
    plan = case.plans[0]
    commitment = planner.inputs.commitment
    inner_snapshot = SimpleNamespace(
        tenant_id=commitment.tenant_id, commitment_id=commitment.commitment_id,
        snapshot_id="snapshot_authoritative_3", snapshot_version=3,
    )
    snapshot = VersionedSnapshot(
        snapshot=inner_snapshot, tenant_id=commitment.tenant_id,
        commitment_id=commitment.commitment_id, commitment_version=commitment.commitment_version,
        snapshot_id=inner_snapshot.snapshot_id, snapshot_version=3, captured_at=datetime.now(UTC),
        source=IntegrationSource.AUTHORITATIVE,
    )
    proposal = object()
    calls = []

    class Builder:
        def build(self, actual_plan, actual_snapshot, actual_commitment):
            assert (actual_plan, actual_snapshot, actual_commitment) == (plan, snapshot, commitment)
            return proposal

    class Evaluator:
        def evaluate(self, actual_snapshot, actual_proposal, actual_commitment):
            calls.append((actual_snapshot, actual_proposal, actual_commitment))
            return SimpleNamespace(
                tenant_id=commitment.tenant_id, commitment_id=commitment.commitment_id,
                commitment_version=commitment.commitment_version, snapshot_id=snapshot.snapshot_id,
                snapshot_version=snapshot.snapshot_version, status=FeasibilityState.FEASIBLE,
                assessment_id="p2_assessment_3", assessed_at=datetime.now(UTC),
                evidence_refs=["ev_p2_authoritative"], assumptions=["bound authoritative snapshot"],
            )

    result = P2PlanRevalidatorAdapter(Evaluator(), Builder()).evaluate_plan(snapshot, plan, commitment)
    assert calls == [(inner_snapshot, proposal, commitment)]
    assert result.source == IntegrationSource.AUTHORITATIVE
    assert result.evaluation_id == "p2_assessment_3"
    assert result.evidence_refs == ("ev_p2_authoritative",)


def test_untrusted_actor_or_staff_role_cannot_execute():
    for overrides in ({"verified": False}, {"actor_role": "STAFF"}, {"tenant_id": "tenant_other"}):
        orchestrator, context, request, _, _ = make_orchestrator(actor_overrides=overrides)
        result = orchestrator.execute(context, None, request)
        assert result.status == WorkflowStatus.FAILED
        assert orchestrator.action_adapter.repository._records == {}


def test_dependency_order_is_topological_and_cycles_fail_closed():
    definitions = [
        ("task_later", RecoveryActionType.CREATE_FOLLOWUP_TASK, {
            "task_code": "FOLLOW_UP", "owner_team": "OPS", "due_at": "2026-10-22T10:00:00Z",
        }),
        ("task_first", RecoveryActionType.CREATE_PRODUCTION_TASK, {
            "resource_id": "SKU_1", "quantity": "1", "unit": "pcs", "due_at": "2026-10-22T10:00:00Z",
        }),
    ]
    orchestrator, context, request, _, _ = make_orchestrator(
        action_defs=definitions, dependencies=(("task_first", "task_later"),),
    )
    result = orchestrator.execute(context, None, request)
    assert result.status == WorkflowStatus.SUCCEEDED
    assert [row.action_id for row in result.action_results] == ["task_first", "task_later"]

    cycle, context, request, _, _ = make_orchestrator(
        action_defs=definitions, dependencies=(("task_first", "task_later"), ("task_later", "task_first")),
    )
    cycle_result = cycle.execute(context, None, request)
    assert cycle_result.status == WorkflowStatus.FAILED
    assert cycle.action_adapter.repository._records == {}


def test_ambiguous_action_is_reconciled_by_readback_without_replay():
    orchestrator, context, request, _, _ = make_orchestrator()
    action_adapter = orchestrator.action_adapter
    original_execute = action_adapter.execute

    def timeout_once(actor, command, approval_check, **kwargs):
        return original_execute(actor, command, approval_check,
                                failure_mode=FailureMode.TIMEOUT_AFTER_WRITE, **kwargs)

    action_adapter.execute = timeout_once
    ambiguous = orchestrator.execute(context, None, request)
    assert ambiguous.status == WorkflowStatus.NEEDS_RECONCILIATION
    assert len(action_adapter.repository._records) == 1
    reconciled = orchestrator.reconcile(context, None, ambiguous.execution_id)
    assert reconciled.status == WorkflowStatus.SUCCEEDED
    assert len(action_adapter.repository._records) == 1


def test_live_execution_remains_disabled_even_with_authoritative_test_ports():
    orchestrator, context, request, _, _ = make_orchestrator(
        live_candidate=True, source=IntegrationSource.AUTHORITATIVE,
    )
    # Configuration flags cannot turn in-memory repositories into durable stores.
    orchestrator.live_execution_enabled = True
    orchestrator.durable_persistence_enabled = True
    result = orchestrator.execute(context, None, request)
    assert result.status == WorkflowStatus.FAILED
    assert result.error_code == "PUBLIC_EXECUTION_DISABLED"
    assert orchestrator.action_adapter.repository._records == {}
