"""P3-governed recovery execution orchestration.

Internal-only. There is intentionally no public execution route. Live execution
is disabled by default; simulation requires explicit test-double provenance.
All orchestration/recovery state in this module is in-memory and non-durable.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from enum import StrEnum
from threading import RLock
from typing import Any, Literal, Protocol
from uuid import uuid4

from pydantic import ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.schemas import Commitment, ContractModel, FeasibilityState, OffsetAwareDatetime

from .actions import (
    ActionResult,
    ActionStatus,
    RecoveryActionType,
    SyntheticActionAdapter,
    SyntheticActionCommand,
)
from .eventing import (
    ActionCompletedPayload,
    ActionFailedPayload,
    RecoveryEventType,
    ReplanRequiredPayload,
)
from .integrations import (
    CommitmentReader,
    IntegrationSource,
    OperationalSnapshotProvider,
    P2FeasibilityEvaluatorAdapter,
    VerifiedActorContextProvider,
    VersionedSnapshot,
    require_verified_actor,
    validate_snapshot_binding,
)
from .models import (
    ApprovalDecision,
    ApprovalDecisionInput,
    ApprovalDecisionState,
    RecoveryPlanVersion,
    ValidationSource,
)
from .proposal_mapping import P2ProposalMapping, ProposalMappingStatus
from .service import RecoveryPlanner

logger = logging.getLogger(__name__)


class WorkflowStatus(StrEnum):
    PENDING = "PENDING"
    VALIDATING = "VALIDATING"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    NEEDS_REPLAN = "NEEDS_REPLAN"
    NEEDS_RECONCILIATION = "NEEDS_RECONCILIATION"


class ExecutionMode(StrEnum):
    CONTROLLED_TEST_SIMULATION = "CONTROLLED_TEST_SIMULATION"
    LIVE_DISABLED = "LIVE_DISABLED"
    LIVE = "LIVE"


class PlanReevaluation(ContractModel):
    """Bound P2 result for re-evaluating a stored plan against a fresh snapshot."""

    model_config = ConfigDict(frozen=True)

    evaluation_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    commitment_id: str = Field(min_length=1)
    commitment_version: int = Field(ge=1)
    plan_id: str = Field(min_length=1)
    plan_version: int = Field(ge=1)
    snapshot_id: str = Field(min_length=1)
    snapshot_version: int = Field(ge=1)
    status: FeasibilityState
    source: IntegrationSource
    evidence_refs: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    constraints: tuple[dict[str, Any], ...] = ()
    solver_status: str | None = None
    evidence_complete: bool | None = None
    allocation_dependent: bool | None = None
    evaluated_at: OffsetAwareDatetime
    evaluation_origin: Literal["P2", "P3_UNSUPPORTED_MAPPING"] = "P2"
    source_assessment_id: str | None = None
    unsupported_reason_code: str | None = None


class PlanRevalidator(Protocol):
    """Adapter that delegates all feasibility calculations to P2."""

    def evaluate_plan(
        self, snapshot: VersionedSnapshot, plan: RecoveryPlanVersion, commitment: Commitment
    ) -> PlanReevaluation: ...


class P2ProposalBuilder(Protocol):
    """Maps the complete stored P3 plan into P2's agreed typed proposal object."""

    def build(self, plan: RecoveryPlanVersion, snapshot: VersionedSnapshot,
              commitment: Commitment) -> object: ...


class P2PlanRevalidatorAdapter:
    """Calls P2's evaluator; proposal conversion is injected to avoid guessing P2 types."""

    def __init__(
        self,
        evaluator: object,
        proposal_builder: P2ProposalBuilder,
        *,
        allow_test_double: bool = False,
    ) -> None:
        self.evaluator = evaluator
        self.proposal_builder = proposal_builder
        self.allow_test_double = allow_test_double

    def evaluate_plan(self, snapshot: VersionedSnapshot, plan: RecoveryPlanVersion,
                      commitment: Commitment) -> PlanReevaluation:
        if (snapshot.source is IntegrationSource.SYNTHETIC_TEST_DOUBLE
                and not self.allow_test_double):
            raise DomainError(
                "AUTHORITATIVE_INPUT_REQUIRED",
                "Test-double P2 revalidation is available only to explicitly isolated tests",
                status_code=409,
            )
        if snapshot.source not in (
            IntegrationSource.AUTHORITATIVE,
            IntegrationSource.SYNTHETIC_FIXTURE,
            IntegrationSource.SYNTHETIC_TEST_DOUBLE,
        ):
            raise DomainError("P2_INPUT_PROVENANCE_INVALID", "P2 input provenance is unsupported", status_code=409)
        mapping = self.proposal_builder.build(plan, snapshot, commitment)
        if isinstance(mapping, P2ProposalMapping):
            if mapping.status is ProposalMappingStatus.UNSUPPORTED:
                return PlanReevaluation(
                    evaluation_id=f"p3-unsupported-{plan.plan_id}-v{plan.plan_version}",
                    tenant_id=commitment.tenant_id,
                    commitment_id=commitment.commitment_id,
                    commitment_version=commitment.commitment_version,
                    plan_id=plan.plan_id,
                    plan_version=plan.plan_version,
                    snapshot_id=snapshot.snapshot_id,
                    snapshot_version=snapshot.snapshot_version,
                    status=FeasibilityState.CONDITIONAL,
                    source=snapshot.source,
                    evidence_refs=mapping.evidence_refs,
                    assumptions=mapping.assumptions,
                    evaluated_at=datetime.now(UTC),
                    evaluation_origin="P3_UNSUPPORTED_MAPPING",
                    source_assessment_id=mapping.source_assessment_id,
                    unsupported_reason_code=mapping.reason_code,
                )
            proposal = mapping.proposed_changes
            mapping_evidence_refs = mapping.evidence_refs
            mapping_assumptions = mapping.assumptions
            source_assessment_id = mapping.source_assessment_id
        else:
            # Preserve the original protocol's direct P2 proposal behavior for
            # existing injected builders while the concrete typed mapper rolls out.
            proposal = mapping
            mapping_evidence_refs = ()
            mapping_assumptions = ()
            source_assessment_id = plan.based_on_assessment_id
        result = P2FeasibilityEvaluatorAdapter(
            self.evaluator, allow_test_double=self.allow_test_double
        ).evaluate(snapshot, proposal, commitment)
        result_binding = (
            getattr(result, "tenant_id", None), getattr(result, "commitment_id", None),
            getattr(result, "commitment_version", None), getattr(result, "snapshot_id", None),
            getattr(result, "snapshot_version", None),
        )
        expected = (commitment.tenant_id, commitment.commitment_id, commitment.commitment_version,
                    snapshot.snapshot_id, snapshot.snapshot_version)
        if result_binding != expected:
            raise DomainError("P2_RESULT_VERSION_MISMATCH", "P2 result does not match its authoritative inputs", status_code=409)
        status = getattr(result, "status", None)
        if status is None:
            raise DomainError("P2_RESULT_INVALID", "P2 result has no feasibility status", status_code=409)
        evaluation_id = getattr(result, "assessment_id", None) or getattr(result, "evaluation_id", None)
        evaluated_at = getattr(result, "assessed_at", None) or getattr(result, "evaluated_at", None)
        if not evaluation_id or evaluated_at is None:
            raise DomainError("P2_RESULT_INVALID", "P2 result must include its evaluation ID and timestamp", status_code=409)
        constraints = []
        for constraint in getattr(result, "constraints", ()):
            if hasattr(constraint, "model_dump"):
                constraints.append(constraint.model_dump(mode="json"))
            elif isinstance(constraint, dict):
                constraints.append(dict(constraint))
            else:
                constraints.append({"reason": str(constraint)})
        solver_status = getattr(result, "solver_status", None)
        if solver_status is not None:
            solver_status = getattr(solver_status, "value", solver_status)
        return PlanReevaluation(
            evaluation_id=str(evaluation_id),
            tenant_id=commitment.tenant_id, commitment_id=commitment.commitment_id,
            commitment_version=commitment.commitment_version, plan_id=plan.plan_id,
            plan_version=plan.plan_version, snapshot_id=snapshot.snapshot_id,
            snapshot_version=snapshot.snapshot_version, status=FeasibilityState(status),
            source=snapshot.source,
            evidence_refs=tuple(dict.fromkeys((
                *getattr(result, "evidence_refs", ()), *mapping_evidence_refs,
            ))),
            assumptions=tuple(dict.fromkeys((
                *getattr(result, "assumptions", ()), *mapping_assumptions,
            ))),
            constraints=tuple(constraints),
            solver_status=str(solver_status) if solver_status is not None else None,
            evidence_complete=getattr(result, "evidence_complete", None),
            allocation_dependent=getattr(result, "allocation_dependent", None),
            evaluated_at=evaluated_at,
            evaluation_origin="P2",
            source_assessment_id=source_assessment_id,
        )


class ActionDependencyProvider(Protocol):
    def dependencies_for(self, plan: RecoveryPlanVersion) -> tuple[tuple[str, str], ...]: ...


class EmptyActionDependencyProvider:
    """No extra graph exists in today's shared PlannedAction contract."""

    def dependencies_for(self, plan: RecoveryPlanVersion) -> tuple[tuple[str, str], ...]:
        del plan
        return ()


class InMemoryActionDependencyProvider:
    """P3-owned dependency graph for explicit orchestration tests/simulation."""

    def __init__(self, dependencies: dict[tuple[str, int], tuple[tuple[str, str], ...]] | None = None) -> None:
        self._dependencies = dependencies or {}

    def dependencies_for(self, plan: RecoveryPlanVersion) -> tuple[tuple[str, str], ...]:
        return self._dependencies.get((plan.plan_id, plan.plan_version), ())


class ExecutionRequest(ContractModel):
    plan_id: str = Field(min_length=1)
    commitment_id: str = Field(min_length=1)
    expected_plan_version: int = Field(ge=1)
    expected_commitment_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1, max_length=128)


class OrchestrationAttempt(ContractModel):
    model_config = ConfigDict(frozen=True)

    attempt_id: str
    status: WorkflowStatus
    occurred_at: OffsetAwareDatetime
    detail_code: str | None = None


class ExecutionRecord(ContractModel):
    model_config = ConfigDict(frozen=True)

    execution_id: str
    tenant_id: str
    commitment_id: str
    plan_id: str
    plan_version: int
    idempotency_key: str
    status: WorkflowStatus
    mode: ExecutionMode
    attempts: tuple[OrchestrationAttempt, ...]
    action_results: tuple[ActionResult, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    error_code: str | None = None
    persistence_mode: str = "IN_MEMORY_NON_DURABLE"
    created_at: OffsetAwareDatetime
    updated_at: OffsetAwareDatetime


class InMemoryExecutionRepository:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str], list[ExecutionRecord]] = {}
        self._lock = RLock()

    @property
    def durable(self) -> bool:
        return False

    def latest(self, tenant_id: str, idempotency_key: str) -> ExecutionRecord | None:
        with self._lock:
            rows = self._records.get((tenant_id, idempotency_key), ())
            return rows[-1] if rows else None

    def latest_by_execution_id(self, tenant_id: str, execution_id: str) -> ExecutionRecord | None:
        with self._lock:
            matches = [rows[-1] for (stored_tenant, _), rows in self._records.items()
                       if stored_tenant == tenant_id and rows and rows[-1].execution_id == execution_id]
            return matches[-1] if matches else None

    def append(self, record: ExecutionRecord) -> None:
        with self._lock:
            self._records.setdefault((record.tenant_id, record.idempotency_key), []).append(record)


class GovernedRecoveryOrchestrator:
    """Runs approved plans internally and fails closed unless explicitly simulated."""

    def __init__(
        self,
        *,
        planner: RecoveryPlanner,
        actor_provider: VerifiedActorContextProvider,
        commitment_reader: CommitmentReader,
        snapshot_provider: OperationalSnapshotProvider,
        revalidator: PlanRevalidator,
        action_adapter: SyntheticActionAdapter,
        dependency_provider: ActionDependencyProvider | None = None,
        execution_repository: InMemoryExecutionRepository | None = None,
        simulation_enabled: bool = False,
        live_execution_enabled: bool = False,
        durable_persistence_enabled: bool = False,
    ) -> None:
        self.planner = planner
        self.actor_provider = actor_provider
        self.commitment_reader = commitment_reader
        self.snapshot_provider = snapshot_provider
        self.revalidator = revalidator
        self.action_adapter = action_adapter
        self.dependency_provider = dependency_provider or EmptyActionDependencyProvider()
        self.repository = execution_repository or InMemoryExecutionRepository()
        self.simulation_enabled = simulation_enabled
        self.live_execution_enabled = live_execution_enabled
        self.durable_persistence_enabled = durable_persistence_enabled

    @staticmethod
    def _record(
        *, prior: ExecutionRecord | None, tenant_id: str, request: ExecutionRequest,
        status: WorkflowStatus, mode: ExecutionMode, detail: str | None = None,
        action_results: tuple[ActionResult, ...] | None = None, evidence_refs: tuple[str, ...] | None = None,
    ) -> ExecutionRecord:
        now = datetime.now(UTC)
        execution_id = prior.execution_id if prior else f"exec_{uuid4().hex}"
        attempts = prior.attempts if prior else ()
        attempts += (OrchestrationAttempt(
            attempt_id=f"orcha_{uuid4().hex}", status=status, occurred_at=now, detail_code=detail,
        ),)
        return ExecutionRecord(
            execution_id=execution_id, tenant_id=tenant_id, commitment_id=request.commitment_id,
            plan_id=request.plan_id, plan_version=request.expected_plan_version,
            idempotency_key=request.idempotency_key, status=status,
            mode=mode, attempts=attempts,
            action_results=action_results if action_results is not None else (prior.action_results if prior else ()),
            evidence_refs=evidence_refs if evidence_refs is not None else (prior.evidence_refs if prior else ()),
            error_code=detail, created_at=prior.created_at if prior else now, updated_at=now,
        )

    def _save(self, record: ExecutionRecord) -> ExecutionRecord:
        self.repository.append(record)
        if record.status in {WorkflowStatus.SUCCEEDED, WorkflowStatus.FAILED, WorkflowStatus.NEEDS_REPLAN}:
            try:
                plan = self.planner.get_plan(record.tenant_id, record.plan_id)
                case = self.planner.repository.get_case(record.tenant_id, record.commitment_id)
                if case is None:
                    return record
                if record.status == WorkflowStatus.SUCCEEDED:
                    event_type = RecoveryEventType.ACTION_COMPLETED
                    payload = ActionCompletedPayload(
                        action_ids=tuple(result.action_id for result in record.action_results),
                        operation_refs=tuple(result.operation_ref for result in record.action_results
                                             if result.operation_ref),
                    )
                    if len(payload.action_ids) != len(payload.operation_refs):
                        return record
                elif record.status == WorkflowStatus.NEEDS_REPLAN:
                    event_type = RecoveryEventType.REPLAN_REQUIRED
                    payload = ReplanRequiredPayload(
                        reason_code=record.error_code or "PLAN_REVALIDATION_REQUIRED",
                        source_event_id=record.execution_id,
                        invalidated_plan_ids=(record.plan_id,),
                    )
                else:
                    failed = tuple(result for result in record.action_results
                                   if result.status != ActionStatus.SUCCEEDED)
                    if not failed:
                        return record
                    event_type = RecoveryEventType.ACTION_FAILED
                    payload = ActionFailedPayload(
                        action_ids=tuple(result.action_id for result in failed),
                        reason_codes=tuple(result.error_code or "ACTION_FAILED" for result in failed),
                    )
                event = self.planner.event_coordinator.prepare(
                    event_type=event_type,
                    tenant_id=record.tenant_id,
                    commitment_id=record.commitment_id,
                    commitment_version=case.commitment_version,
                    recovery_case_id=case.case_id,
                    plan_id=record.plan_id,
                    plan_version=record.plan_version,
                    snapshot_version=plan.snapshot_version,
                    correlation_id=f"recovery-execution:{record.execution_id}",
                    causation_id=record.execution_id,
                    evidence_refs=record.evidence_refs,
                    payload=payload,
                )
                # P3 prepares and queues in-process; no unsupported CoreEventType is added.
                self.planner.event_coordinator.publish(event)
            except Exception:
                # Event preparation must not turn an action outcome into a false execution result.
                logger.warning("Recovery event preparation/publication failed", exc_info=True)
        return record

    def _topological_actions(self, plan: RecoveryPlanVersion):
        actions = {action.action_id: action for action in plan.actions}
        if len(actions) != len(plan.actions):
            raise DomainError("DUPLICATE_PLAN_ACTION_ID", "Plan action IDs must be unique", status_code=409)
        edges = self.dependency_provider.dependencies_for(plan)
        for before, after in edges:
            if before not in actions or after not in actions or before == after:
                raise DomainError("INVALID_ACTION_DEPENDENCY", "Action dependency references an invalid action", status_code=409)
        incoming = {action_id: set() for action_id in actions}
        outgoing = {action_id: set() for action_id in actions}
        for before, after in edges:
            incoming[after].add(before)
            outgoing[before].add(after)
        original_order = {action.action_id: index for index, action in enumerate(plan.actions)}
        ready = sorted((key for key, deps in incoming.items() if not deps), key=original_order.get)
        ordered = []
        while ready:
            action_id = ready.pop(0)
            ordered.append(actions[action_id])
            for child in sorted(outgoing[action_id], key=original_order.get):
                incoming[child].remove(action_id)
                if not incoming[child] and child not in {item.action_id for item in ordered} and child not in ready:
                    ready.append(child)
                    ready.sort(key=original_order.get)
        if len(ordered) != len(actions):
            raise DomainError("ACTION_DEPENDENCY_CYCLE", "Plan action dependencies contain a cycle", status_code=409)
        return tuple(ordered)

    def execute(self, context: RequestContext, db: Session, request: ExecutionRequest) -> ExecutionRecord:
        with self.repository._lock:
            return self._execute_locked(context, db, request)

    def _execute_locked(self, context: RequestContext, db: Session,
                        request: ExecutionRequest) -> ExecutionRecord:
        """Execute internally. Callers cannot supply actor role or approval state."""
        prior = self.repository.latest(context.tenant_id, request.idempotency_key)
        if prior:
            if (prior.plan_id, prior.commitment_id, prior.plan_version) != (
                request.plan_id, request.commitment_id, request.expected_plan_version
            ):
                raise DomainError("EXECUTION_IDEMPOTENCY_CONFLICT", "Execution key belongs to different request data", status_code=409)
            if prior.status in {WorkflowStatus.SUCCEEDED, WorkflowStatus.NEEDS_RECONCILIATION}:
                return prior
            if prior.status in {WorkflowStatus.PENDING, WorkflowStatus.VALIDATING, WorkflowStatus.EXECUTING, WorkflowStatus.VERIFYING}:
                return prior

        plan = self.planner.get_plan(context.tenant_id, request.plan_id)  # 1. Stored plan lookup
        if plan.tenant_id != context.tenant_id or plan.commitment_id != request.commitment_id:
            raise DomainError("RECOVERY_PLAN_NOT_FOUND", "Plan is outside the requested tenant/commitment", status_code=404)
        mode = (ExecutionMode.CONTROLLED_TEST_SIMULATION if self.simulation_enabled
                else ExecutionMode.LIVE_DISABLED)
        record = self._record(prior=prior, tenant_id=plan.tenant_id, request=request,
                              status=WorkflowStatus.PENDING, mode=mode)
        self._save(record)
        try:
            if request.expected_plan_version != plan.plan_version:
                raise DomainError("RECOVERY_PLAN_VERSION_CONFLICT", "Plan version is stale", status_code=409)
            if request.expected_commitment_version != plan.evaluation.commitment_version:
                raise DomainError("COMMITMENT_VERSION_CONFLICT", "Plan commitment version is stale", status_code=409)

            actor = self.actor_provider.get_verified_context(context)  # 3. Trusted server-side actor
            require_verified_actor(actor)
            if actor.tenant_id != plan.tenant_id or actor.actor_role.upper() not in {"OWNER", "MANAGER"}:
                raise DomainError("ACTION_FORBIDDEN", "Verified owner/manager tenant context is required", status_code=403)
            trusted_context = RequestContext(
                tenant_id=actor.tenant_id, actor_id=actor.actor_id, actor_role=actor.actor_role,
                correlation_id=actor.correlation_id, causation_id=actor.causation_id,
            )
            record = self._record(prior=record, tenant_id=plan.tenant_id, request=request,
                                  status=WorkflowStatus.VALIDATING, mode=mode)
            self._save(record)

            # 4–5. Authoritative P5 commitment and exact version bindings.
            commitment = self.commitment_reader.get_commitment(
                db, trusted_context, plan.commitment_id,
                expected_commitment_version=request.expected_commitment_version,
            )
            if (commitment.tenant_id, commitment.commitment_id, commitment.commitment_version) != (
                plan.tenant_id, plan.commitment_id, request.expected_commitment_version
            ):
                raise DomainError("COMMITMENT_VERSION_CONFLICT", "Authoritative Commitment does not match plan", status_code=409)

            # 6–7. Load an immutable stored approval and enforce its complete binding.
            case = self.planner.get_case(plan.tenant_id, plan.commitment_id)
            approvals = [d for d in case.approval_decisions if d.plan_id == plan.plan_id
                         and d.plan_version == plan.plan_version and d.decision == ApprovalDecisionState.APPROVED]
            approval = approvals[-1] if approvals else None
            now = datetime.now(UTC)
            if approval is None or plan.approval_state.value != "APPROVED":
                raise DomainError("APPROVAL_NOT_ACTIVE", "No persisted approved decision exists", status_code=409)
            if (approval.tenant_id, approval.commitment_id, approval.commitment_version,
                approval.recovery_case_id, approval.plan_id, approval.plan_version) != (
                plan.tenant_id, plan.commitment_id, request.expected_commitment_version,
                plan.recovery_case_id, plan.plan_id, plan.plan_version
            ):
                raise DomainError("APPROVAL_BINDING_MISMATCH", "Approval is bound to another plan or version", status_code=409)
            if (approval.actor_role.upper() not in {"OWNER", "MANAGER"} or not approval.actor_id
                    or approval.approved_at is None or approval.expires_at is None or approval.expires_at <= now):
                raise DomainError("APPROVAL_INVALID", "Approval actor, role, or expiry is invalid", status_code=409)
            expected_scope = sorted({action.type for action in plan.actions})
            if sorted(approval.action_scope) != expected_scope:
                raise DomainError("APPROVAL_SCOPE_MISMATCH", "Approval does not cover the plan action scope", status_code=409)
            if approval.approved_cost_limit is None or approval.approved_cost_limit < plan.estimated_extra_cost:
                raise DomainError("APPROVAL_COST_LIMIT_EXCEEDED", "Approved cost limit is below plan cost", status_code=409)

            # 8–9. Fresh P2 snapshot and exact-plan reevaluation (P3 does no feasibility math).
            snapshot = self.snapshot_provider.get_snapshot(trusted_context, commitment)
            validate_snapshot_binding(snapshot, commitment)
            reevaluation = self.revalidator.evaluate_plan(snapshot, plan, commitment)
            expected_binding = (
                plan.tenant_id, plan.commitment_id, commitment.commitment_version,
                plan.plan_id, plan.plan_version, snapshot.snapshot_id, snapshot.snapshot_version,
            )
            actual_binding = (
                reevaluation.tenant_id, reevaluation.commitment_id, reevaluation.commitment_version,
                reevaluation.plan_id, reevaluation.plan_version, reevaluation.snapshot_id,
                reevaluation.snapshot_version,
            )
            if actual_binding != expected_binding:
                raise DomainError("P2_RESULT_VERSION_MISMATCH", "Re-evaluation identity/version binding is stale", status_code=409)
            if reevaluation.evaluation_origin != "P2":
                raise DomainError(
                    "PLAN_REVALIDATION_BLOCKED",
                    "P2 did not evaluate this plan because its proposal strategy is unsupported",
                    status_code=409,
                    details={"unsupported_reason_code": reevaluation.unsupported_reason_code},
                )
            if (snapshot.source != IntegrationSource.AUTHORITATIVE
                    or reevaluation.source != IntegrationSource.AUTHORITATIVE
                    or plan.evaluation.validation_source != ValidationSource.REAL_P2_VALIDATED):
                if not (self.simulation_enabled
                        and plan.evaluation.validation_source == ValidationSource.TEST_DOUBLE_VALIDATED
                        and snapshot.source == IntegrationSource.SYNTHETIC_TEST_DOUBLE
                        and reevaluation.source == IntegrationSource.SYNTHETIC_TEST_DOUBLE):
                    raise DomainError("AUTHORITATIVE_VALIDATION_REQUIRED", "Test doubles cannot authorize live execution", status_code=409)
                mode = ExecutionMode.CONTROLLED_TEST_SIMULATION
            if (snapshot.snapshot_version != plan.snapshot_version
                    or approval.snapshot_version != snapshot.snapshot_version
                    or request.expected_commitment_version != approval.commitment_version):
                raise DomainError("SNAPSHOT_VERSION_CONFLICT", "Plan approval is stale against the latest snapshot", status_code=409)
            if reevaluation.status != FeasibilityState.FEASIBLE:
                raise DomainError("PLAN_REVALIDATION_BLOCKED", "Only a freshly feasible plan may execute", status_code=409,
                                  details={"feasibility_status": reevaluation.status.value})

            # 11. Resolve allowlisted actions and deterministic dependency order before any writes.
            ordered_actions = self._topological_actions(plan)
            commands: list[SyntheticActionCommand] = []
            for action in ordered_actions:
                try:
                    action_type = RecoveryActionType(action.type)
                except ValueError as exc:
                    raise DomainError("ACTION_TYPE_NOT_ALLOWLISTED", "Plan contains an unsupported action type", status_code=409) from exc
                if action.type not in approval.action_scope:
                    raise DomainError("APPROVAL_SCOPE_MISMATCH", "Approval does not cover a planned action", status_code=409)
                params = dict(action.parameters)
                params.setdefault("action_type", action_type.value)
                commands.append(SyntheticActionCommand(
                    action_id=action.action_id, tenant_id=plan.tenant_id,
                    commitment_id=plan.commitment_id, plan_id=plan.plan_id,
                    plan_version=plan.plan_version, action_type=action_type,
                    parameters=params, idempotency_key=f"{request.idempotency_key}:{action.idempotency_key}",
                    evidence_refs=tuple(plan.evidence_refs) + tuple(reevaluation.evidence_refs),
                ))

            # P5 currently has no approved publisher for P3-owned action event types.
            # Durable live execution stays disabled even if a generic publisher is injected.
            if not self.simulation_enabled:
                raise DomainError("PUBLIC_EXECUTION_DISABLED", "Live consequential execution is disabled", status_code=503)
            if not self.simulation_enabled:
                mode = ExecutionMode.LIVE
            if self.simulation_enabled and mode != ExecutionMode.CONTROLLED_TEST_SIMULATION:
                raise DomainError("SIMULATION_PROVENANCE_REQUIRED", "Simulation requires explicit test-double integrations", status_code=409)

            # 12–14. Idempotency is enforced by the workflow and action repositories.
            record = self._record(prior=record, tenant_id=plan.tenant_id, request=request,
                                  status=WorkflowStatus.EXECUTING, mode=mode)
            self._save(record)
            action_results: list[ActionResult] = []
            for command in commands:
                result = self.action_adapter.execute(
                    actor, command, _approval_input(approval), allow_test_simulation=self.simulation_enabled,
                )
                action_results.append(result)
                if result.status == ActionStatus.NEEDS_RECONCILIATION:
                    record = self._record(prior=record, tenant_id=plan.tenant_id, request=request,
                                          status=WorkflowStatus.NEEDS_RECONCILIATION, mode=mode,
                                          action_results=tuple(action_results))
                    return self._save(record)
                if result.status != ActionStatus.SUCCEEDED:
                    record = self._record(prior=record, tenant_id=plan.tenant_id, request=request,
                                          status=WorkflowStatus.FAILED, mode=mode,
                                          detail="SYNTHETIC_ACTION_FAILED", action_results=tuple(action_results))
                    return self._save(record)

            # 15. Verify all records again before final success.
            record = self._record(prior=record, tenant_id=plan.tenant_id, request=request,
                                  status=WorkflowStatus.VERIFYING, mode=mode,
                                  action_results=tuple(action_results))
            self._save(record)
            for result in action_results:
                stored = self.action_adapter.repository.get_record(result.tenant_id, result.operation_ref or "")
                if (stored is None or stored.action_id != result.action_id
                        or stored.plan_id != result.plan_id or stored.plan_version != result.plan_version
                        or stored.parameters != result.parameters):
                    record = self._record(prior=record, tenant_id=plan.tenant_id, request=request,
                                          status=WorkflowStatus.NEEDS_RECONCILIATION, mode=mode,
                                          detail="ACTION_READBACK_UNVERIFIED", action_results=tuple(action_results))
                    return self._save(record)

            # 16. Prepare verified result event through the typed P3 port. Publication remains pending.
            evidence_refs = tuple(ref for result in action_results for ref in result.evidence_refs)
            record = self._record(prior=record, tenant_id=plan.tenant_id, request=request,
                                  status=WorkflowStatus.SUCCEEDED, mode=mode,
                                  action_results=tuple(action_results), evidence_refs=evidence_refs)
            return self._save(record)
        except DomainError as exc:
            status = WorkflowStatus.NEEDS_REPLAN if exc.code in {
                "RECOVERY_PLAN_VERSION_CONFLICT", "COMMITMENT_VERSION_CONFLICT", "SNAPSHOT_VERSION_CONFLICT",
                "P2_RESULT_VERSION_MISMATCH", "PLAN_REVALIDATION_BLOCKED", "AUTHORITATIVE_VALIDATION_REQUIRED",
            } else WorkflowStatus.FAILED
            record = self._record(prior=record, tenant_id=plan.tenant_id, request=request,
                                  status=status, mode=mode, detail=exc.code)
            return self._save(record)
        except Exception:  # noqa: BLE001 - unknown executor failure after writes is ambiguous
            # An unexpected failure after entering the side-effect phase is ambiguous.
            status = (WorkflowStatus.NEEDS_RECONCILIATION
                      if record.status in {WorkflowStatus.EXECUTING, WorkflowStatus.VERIFYING}
                      else WorkflowStatus.FAILED)
            record = self._record(prior=record, tenant_id=plan.tenant_id, request=request,
                                  status=status, mode=mode,
                                  detail="ACTION_OUTCOME_UNKNOWN" if status == WorkflowStatus.NEEDS_RECONCILIATION
                                  else "INTEGRATION_FAILURE")
            return self._save(record)

    def reconcile(self, context: RequestContext, db: Session, execution_id: str) -> ExecutionRecord:
        with self.repository._lock:
            return self._reconcile_locked(context, db, execution_id)

    def _reconcile_locked(self, context: RequestContext, db: Session,
                          execution_id: str) -> ExecutionRecord:
        """Resolve ambiguous adapter outcomes through readback, without replaying writes."""
        actor = self.actor_provider.get_verified_context(context)
        require_verified_actor(actor)
        prior = self.repository.latest_by_execution_id(actor.tenant_id, execution_id)
        if prior is None:
            raise DomainError("EXECUTION_NOT_FOUND", "Execution was not found", status_code=404)
        if prior.status != WorkflowStatus.NEEDS_RECONCILIATION:
            raise DomainError("RECONCILIATION_NOT_REQUIRED", "Execution does not require reconciliation", status_code=409)
        request = ExecutionRequest(
            plan_id=prior.plan_id, commitment_id=prior.commitment_id,
            expected_plan_version=prior.plan_version,
            expected_commitment_version=self.planner.get_plan(actor.tenant_id, prior.plan_id).evaluation.commitment_version,
            idempotency_key=prior.idempotency_key,
        )
        record = self._record(prior=prior, tenant_id=actor.tenant_id, request=request,
                              status=WorkflowStatus.VERIFYING, mode=prior.mode)
        self._save(record)
        resolved: list[ActionResult] = []
        for action_result in prior.action_results:
            outcome = action_result
            if outcome.status == ActionStatus.NEEDS_RECONCILIATION:
                outcome = self.action_adapter.reconcile(outcome.tenant_id, outcome.idempotency_key)
            if outcome.status != ActionStatus.SUCCEEDED:
                record = self._record(prior=record, tenant_id=actor.tenant_id, request=request,
                                      status=WorkflowStatus.FAILED, mode=prior.mode,
                                      detail="SYNTHETIC_ACTION_NOT_VERIFIED",
                                      action_results=tuple(resolved + [outcome]))
                return self._save(record)
            stored = self.action_adapter.repository.get_record(outcome.tenant_id, outcome.operation_ref or "")
            if stored is None or stored.action_id != outcome.action_id or stored.parameters != outcome.parameters:
                record = self._record(prior=record, tenant_id=actor.tenant_id, request=request,
                                      status=WorkflowStatus.NEEDS_RECONCILIATION, mode=prior.mode,
                                      detail="ACTION_READBACK_UNVERIFIED",
                                      action_results=tuple(resolved + [outcome]))
                return self._save(record)
            resolved.append(outcome)
        evidence_refs = tuple(ref for result in resolved for ref in result.evidence_refs)
        record = self._record(prior=record, tenant_id=actor.tenant_id, request=request,
                              status=WorkflowStatus.SUCCEEDED, mode=prior.mode,
                              action_results=tuple(resolved), evidence_refs=evidence_refs)
        return self._save(record)


def _approval_input(approval: ApprovalDecision):
    """Build the existing approval-service check from persisted, server-loaded values."""
    return ApprovalDecisionInput(
        expected_commitment_version=approval.commitment_version or 0,
        expected_plan_version=approval.plan_version,
        expected_snapshot_version=approval.snapshot_version,
        reason="Internal orchestrator active-approval check",
        evidence_refs=list(approval.evidence_refs),
    )
