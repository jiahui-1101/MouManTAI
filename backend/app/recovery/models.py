from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from app.core.schemas import (
    ApprovalState,
    Commitment,
    FeasibilityAssessment,
    FeasibilityState,
    NonNegativeDecimal,
    OffsetAwareDatetime,
    PlannedAction,
    RecoveryPlan,
    ContractModel,
)


class RecoveryCaseStatus(StrEnum):
    OPEN = "OPEN"
    OPTIONS_READY = "OPTIONS_READY"
    NO_SAFE_PLAN = "NO_SAFE_PLAN"
    NEEDS_REPLAN = "NEEDS_REPLAN"


class ValidationSource(StrEnum):
    REAL_P2_VALIDATED = "REAL_P2_VALIDATED"
    TEST_DOUBLE_VALIDATED = "TEST_DOUBLE_VALIDATED"


class SolverReadiness(StrEnum):
    PENDING_EVALUATION = "PENDING_EVALUATION"
    VALIDATED = "VALIDATED"
    CONDITIONAL = "CONDITIONAL"
    INFEASIBLE = "INFEASIBLE"
    UNKNOWN = "UNKNOWN"


class RecoveryStrategy(StrEnum):
    RESCHEDULE_PARTIAL_FULFILMENT = "RESCHEDULE_PARTIAL_FULFILMENT"
    ALTERNATIVE_SUPPLY = "ALTERNATIVE_SUPPLY"


class ApprovalDecisionState(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PENDING = "PENDING"


class ActionExecutionState(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    BLOCKED = "BLOCKED"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    NEEDS_REPLAN = "NEEDS_REPLAN"


class ActionAttemptState(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class OperationalSnapshotReference(ContractModel):
    snapshot_id: str = Field(min_length=1)
    snapshot_version: int = Field(ge=1)
    captured_at: OffsetAwareDatetime
    source: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)


class BusinessPreferences(ContractModel):
    cost_weight: NonNegativeDecimal = Decimal("2")
    delay_weight: NonNegativeDecimal = Decimal("4")
    risk_weight: NonNegativeDecimal = Decimal("5")
    customer_impact_weight: NonNegativeDecimal = Decimal("3")
    max_extra_cost: NonNegativeDecimal | None = None

    @model_validator(mode="after")
    def require_ranking_signal(self) -> "BusinessPreferences":
        if sum(
            (
                self.cost_weight,
                self.delay_weight,
                self.risk_weight,
                self.customer_impact_weight,
            ),
            Decimal("0"),
        ) <= 0:
            raise ValueError("at least one preference weight must be greater than zero")
        return self


class PlanEvaluation(ContractModel):
    evaluation_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    commitment_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    plan_version: int = Field(ge=1)
    commitment_version: int = Field(ge=1)
    snapshot_version: int = Field(ge=1)
    feasibility_status: FeasibilityState
    validation_source: ValidationSource
    readiness: SolverReadiness
    solver_status: str = Field(min_length=1)
    constraints: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    evaluated_at: OffsetAwareDatetime


class RecoveryPlanVersion(ContractModel):
    """P3-owned plan envelope that remains mappable to the shared RecoveryPlan."""

    tenant_id: str = Field(min_length=1)
    recovery_case_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    plan_version: int = Field(ge=1)
    commitment_id: str = Field(min_length=1)
    based_on_assessment_id: str = Field(min_length=1)
    snapshot_version: int = Field(ge=1)
    feasibility_status: FeasibilityState
    estimated_extra_cost: NonNegativeDecimal
    currency: str = Field(pattern="^[A-Z]{3}$")
    estimated_delay_minutes: int = Field(ge=0)
    risks: list[str] = Field(default_factory=list)
    actions: list[PlannedAction] = Field(min_length=1)
    approval_state: ApprovalState
    execution_state: str = Field(min_length=1)
    option_id: str = Field(min_length=1)
    strategy: RecoveryStrategy
    risk_level: RiskLevel
    customer_impact: str = Field(min_length=1)
    constraints: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    ranking_score: NonNegativeDecimal
    recommended: bool = False
    recommendation_reason: str | None = None
    evaluation: PlanEvaluation

    def as_shared_plan(self) -> RecoveryPlan:
        return RecoveryPlan.model_validate(
            self.model_dump(
                mode="python",
                include={
                    "tenant_id",
                    "recovery_case_id",
                    "plan_id",
                    "plan_version",
                    "commitment_id",
                    "based_on_assessment_id",
                    "snapshot_version",
                    "feasibility_status",
                    "estimated_extra_cost",
                    "currency",
                    "estimated_delay_minutes",
                    "risks",
                    "actions",
                    "approval_state",
                    "execution_state",
                },
            )
        )


class RecoveryOption(ContractModel):
    option_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    strategy: RecoveryStrategy
    label: str = Field(min_length=1)
    estimated_extra_cost: NonNegativeDecimal
    currency: str = Field(pattern="^[A-Z]{3}$")
    estimated_delay_minutes: int = Field(ge=0)
    feasibility_status: FeasibilityState
    validation_source: ValidationSource
    risk_level: RiskLevel
    customer_impact: str = Field(min_length=1)
    constraints: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    ranking_score: NonNegativeDecimal
    recommended: bool = False
    recommendation_reason: str | None = None


class ApprovalDecision(ContractModel):
    approval_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    commitment_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    plan_version: int = Field(ge=1)
    snapshot_version: int = Field(ge=1)
    actor_id: str = Field(min_length=1)
    actor_role: str = Field(min_length=1)
    decision: ApprovalDecisionState
    approved_cost_limit: NonNegativeDecimal | None = None
    reason: str = Field(min_length=1)
    decided_at: OffsetAwareDatetime | None = None
    expires_at: OffsetAwareDatetime | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class ActionAttempt(ContractModel):
    attempt_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    commitment_id: str = Field(min_length=1)
    action_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    state: ActionAttemptState
    started_at: OffsetAwareDatetime | None = None
    completed_at: OffsetAwareDatetime | None = None
    provider_operation_ref: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None


class ActionExecution(ContractModel):
    execution_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    commitment_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    action_id: str = Field(min_length=1)
    state: ActionExecutionState
    idempotency_key: str = Field(min_length=1)
    attempts: list[ActionAttempt] = Field(default_factory=list)
    provider_operation_ref: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class RecoveryCase(ContractModel):
    case_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    commitment_id: str = Field(min_length=1)
    case_version: int = Field(ge=1)
    commitment_version: int = Field(ge=1)
    status: RecoveryCaseStatus
    commitment: Commitment
    trigger_assessment: FeasibilityAssessment
    operational_snapshot: OperationalSnapshotReference
    preferences: BusinessPreferences
    options: list[RecoveryOption] = Field(default_factory=list)
    plans: list[RecoveryPlanVersion] = Field(default_factory=list)
    approval_decisions: list[ApprovalDecision] = Field(default_factory=list)
    customer_confirmation_evidence_refs: list[str] = Field(default_factory=list)
    fulfilment_evidence_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    storage_mode: Literal["IN_MEMORY_SYNTHETIC"] = "IN_MEMORY_SYNTHETIC"
    created_at: OffsetAwareDatetime
    updated_at: OffsetAwareDatetime


class GenerateRecoveryRequest(ContractModel):
    expected_commitment_version: int = Field(ge=1)
    assessment_id: str | None = Field(default=None, min_length=1)
    preferences: BusinessPreferences | None = None
    causation_id: str | None = None


class RecoveryPlanList(ContractModel):
    tenant_id: str = Field(min_length=1)
    commitment_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    plans: list[RecoveryPlanVersion] = Field(default_factory=list)


class FeasibilityEvaluationResult(ContractModel):
    status: FeasibilityState
    solver_status: str = Field(min_length=1)
    constraints: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
