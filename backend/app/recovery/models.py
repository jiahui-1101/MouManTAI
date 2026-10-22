from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from app.core.schemas import (
    ApprovalState,
    Commitment,
    ConstraintReason,
    ContractModel,
    FeasibilityAssessment,
    FeasibilityState,
    NonNegativeDecimal,
    OffsetAwareDatetime,
    PlannedAction,
    RecoveryPlan,
)


class RecoveryCaseStatus(StrEnum):
    OPEN = "OPEN"
    AWAITING_EVALUATION_INPUTS = "AWAITING_EVALUATION_INPUTS"
    OPTIONS_READY = "OPTIONS_READY"
    NO_SAFE_PLAN = "NO_SAFE_PLAN"
    NEEDS_REPLAN = "NEEDS_REPLAN"
    COMPLETED = "COMPLETED"


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
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PENDING = "PENDING"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


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


class RecoveryTriggerReference(ContractModel):
    """P5 at-risk event provenance retained by the P3 case repository."""

    event_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    commitment_id: str = Field(min_length=1)
    commitment_version: int = Field(ge=1)
    assessment_id: str = Field(min_length=1)
    assessment_commitment_version: int | None = Field(default=None, ge=1)
    source_event_digest: str | None = Field(default=None, pattern="^[0-9a-f]{64}$")
    assessment_provenance_status: Literal[
        "SOURCE_COMMITMENT_VERSION_MISSING",
        "SOURCE_COMMITMENT_VERSION_RECORDED_UNVERIFIED",
        "VERIFIED_AUTHORITATIVE",
    ]
    snapshot_id: str | None = None
    snapshot_version: int = Field(ge=1)
    constraints: list[ConstraintReason] = Field(default_factory=list)
    affected_commitment_ids: list[str] = Field(default_factory=list)
    correlation_id: str = Field(min_length=1)
    causation_id: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    occurred_at: OffsetAwareDatetime

    @model_validator(mode="after")
    def provenance_matches_source_version(self) -> RecoveryTriggerReference:
        if self.assessment_commitment_version is None:
            if self.assessment_provenance_status != "SOURCE_COMMITMENT_VERSION_MISSING":
                raise ValueError("missing assessment source version must be reported explicitly")
        elif self.assessment_provenance_status not in {
            "SOURCE_COMMITMENT_VERSION_RECORDED_UNVERIFIED", "VERIFIED_AUTHORITATIVE",
        }:
            raise ValueError("provided assessment source version has an invalid provenance status")
        if self.assessment_provenance_status == "VERIFIED_AUTHORITATIVE" and (
            not self.snapshot_id or not self.source_event_digest
        ):
            raise ValueError("verified provenance requires exact snapshot and event digest")
        if (
            self.assessment_commitment_version is not None
            and self.assessment_commitment_version >= self.commitment_version
        ):
            raise ValueError("evaluated Commitment version must precede the post-transition event version")
        return self


class RecoveryResolutionReference(ContractModel):
    """P5 lifecycle event proving the authoritative risk episode has resolved."""

    event_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    commitment_id: str = Field(min_length=1)
    commitment_version: int = Field(ge=1)
    assessment_id: str | None = None
    correlation_id: str = Field(min_length=1)
    causation_id: str | None = None
    occurred_at: OffsetAwareDatetime


class CustomerResponseEvidence(ContractModel):
    """Reference-bound P4 response retained in the P3 Recovery Case history."""

    event_id: str = Field(min_length=1)
    confirmation_id: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    proposal_version: int = Field(ge=1)
    intent: Literal["REJECT", "COUNTEROFFER"]
    outcome: Literal["REPLAN_REQUIRED", "REPLANNED", "STALE_IGNORED"]
    proposed_terms: dict[str, str] | None = None
    evidence_refs: list[str] = Field(min_length=1)
    received_at: OffsetAwareDatetime


class BusinessPreferences(ContractModel):
    """Owner policy weights; score units are cost/100 MYR and delay/24 hours."""

    cost_weight: NonNegativeDecimal = Field(default=Decimal(2), description="Points per MYR 100 of extra cost")
    delay_weight: NonNegativeDecimal = Field(default=Decimal(4), description="Points per 1,440 minutes of delay")
    affected_commitments_weight: NonNegativeDecimal = Field(
        default=Decimal(5), description="Points per affected commitment"
    )
    operational_disruption_weight: NonNegativeDecimal = Field(
        default=Decimal(3), description="Points per operational disruption level, on a 0–5 scale"
    )
    supplier_uncertainty_weight: NonNegativeDecimal = Field(
        default=Decimal(4), description="Points per supplier uncertainty level, on a 0–5 scale"
    )
    customer_confirmation_weight: NonNegativeDecimal = Field(
        default=Decimal(3), description="Points when customer confirmation is required"
    )
    max_extra_cost: NonNegativeDecimal | None = None

    @model_validator(mode="after")
    def require_ranking_signal(self) -> BusinessPreferences:
        if sum(
            (
                self.cost_weight,
                self.delay_weight,
                self.affected_commitments_weight,
                self.operational_disruption_weight,
                self.supplier_uncertainty_weight,
                self.customer_confirmation_weight,
            ),
            Decimal(0),
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
    hard_constraint_reasons: list[str] = Field(default_factory=list)
    affected_commitment_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    evaluated_at: OffsetAwareDatetime


class PlanScoreBreakdown(ContractModel):
    additional_cost_myr: NonNegativeDecimal
    delivery_delay_minutes: int = Field(ge=0)
    affected_commitment_count: int = Field(ge=0)
    operational_disruption_level: NonNegativeDecimal = Field(le=5)
    supplier_uncertainty_level: NonNegativeDecimal = Field(le=5)
    customer_confirmation_required: bool
    cost_score: NonNegativeDecimal
    delay_score: NonNegativeDecimal
    affected_commitments_score: NonNegativeDecimal
    operational_disruption_score: NonNegativeDecimal
    supplier_uncertainty_score: NonNegativeDecimal
    customer_confirmation_score: NonNegativeDecimal
    total_score: NonNegativeDecimal
    policy_weights: BusinessPreferences


class RecoveryPlanVersion(ContractModel):
    """P3-owned plan envelope that remains mappable to the shared RecoveryPlan."""

    tenant_id: str = Field(min_length=1)
    recovery_case_id: str = Field(min_length=1)
    plan_id: str = Field(min_length=1)
    plan_version: int = Field(ge=1)
    proposal_id: str | None = None
    proposal_version: int | None = Field(default=None, ge=1)
    commitment_id: str = Field(min_length=1)
    based_on_assessment_id: str = Field(min_length=1)
    snapshot_id: str | None = None
    core_commitment_version: int | None = Field(default=None, ge=1)
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
    affected_commitment_count: int = Field(ge=0)
    operational_disruption_level: NonNegativeDecimal = Field(le=5)
    supplier_uncertainty_level: NonNegativeDecimal = Field(le=5)
    customer_confirmation_required: bool
    constraints: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    ranking_score: NonNegativeDecimal | None = None
    score_breakdown: PlanScoreBreakdown | None = None
    rank: int | None = Field(default=None, ge=1)
    ranking_exclusion_reasons: list[str] = Field(default_factory=list)
    recommended: bool = False
    recommendation_label: Literal["RECOMMENDED_UNDER_POLICY"] | None = None
    recommendation_qualification: str | None = None
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
    affected_commitment_count: int = Field(ge=0)
    operational_disruption_level: NonNegativeDecimal = Field(le=5)
    supplier_uncertainty_level: NonNegativeDecimal = Field(le=5)
    customer_confirmation_required: bool
    ranking_score: NonNegativeDecimal | None = None
    score_breakdown: PlanScoreBreakdown | None = None
    rank: int | None = Field(default=None, ge=1)
    ranking_exclusion_reasons: list[str] = Field(default_factory=list)
    recommended: bool = False
    recommendation_label: Literal["RECOMMENDED_UNDER_POLICY"] | None = None
    recommendation_qualification: str | None = None
    recommendation_reason: str | None = None


class ApprovalDecision(ContractModel):
    model_config = ConfigDict(frozen=True)

    approval_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    recovery_case_id: str | None = None
    commitment_id: str = Field(min_length=1)
    commitment_version: int | None = Field(default=None, ge=1)
    plan_id: str = Field(min_length=1)
    plan_version: int = Field(ge=1)
    proposal_id: str | None = None
    proposal_version: int | None = Field(default=None, ge=1)
    snapshot_id: str | None = None
    snapshot_version: int = Field(ge=1)
    action_scope: list[str] = Field(default_factory=list)
    actor_id: str = Field(min_length=1)
    actor_role: str = Field(min_length=1)
    decision: ApprovalDecisionState
    approved_cost_limit: NonNegativeDecimal | None = None
    reason: str = Field(min_length=1)
    decided_at: OffsetAwareDatetime | None = None
    approved_at: OffsetAwareDatetime | None = None
    expires_at: OffsetAwareDatetime | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    audit_refs: list[str] = Field(default_factory=list)
    idempotency_key: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None
    persistence_mode: Literal["IN_MEMORY_NON_DURABLE", "DURABLE_DATABASE"] = "IN_MEMORY_NON_DURABLE"


class ApprovalRequestInput(ContractModel):
    expected_commitment_version: int = Field(ge=1)
    expected_plan_version: int = Field(ge=1)
    expected_snapshot_version: int = Field(ge=1)
    action_scope: list[str] = Field(min_length=1)
    maximum_approved_amount: NonNegativeDecimal
    reason: str = Field(min_length=1)
    expires_at: OffsetAwareDatetime
    idempotency_key: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)


class ApprovalDecisionInput(ContractModel):
    expected_commitment_version: int = Field(ge=1)
    expected_plan_version: int = Field(ge=1)
    expected_snapshot_version: int = Field(ge=1)
    reason: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    idempotency_key: str | None = Field(default=None, min_length=1)


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
    # Trigger-only cases may be opened from a Core event before P2's complete
    # historical assessment and current operational snapshot are resolvable.
    # Such cases must not enter planning until both authoritative inputs exist.
    trigger_assessment: FeasibilityAssessment | None = None
    operational_snapshot: OperationalSnapshotReference | None = None
    trigger_events: list[RecoveryTriggerReference] = Field(default_factory=list)
    resolution_events: list[RecoveryResolutionReference] = Field(default_factory=list)
    preferences: BusinessPreferences
    options: list[RecoveryOption] = Field(default_factory=list)
    plans: list[RecoveryPlanVersion] = Field(default_factory=list)
    approval_decisions: list[ApprovalDecision] = Field(default_factory=list)
    customer_response_events: list[CustomerResponseEvidence] = Field(default_factory=list)
    customer_confirmation_evidence_refs: list[str] = Field(default_factory=list)
    fulfilment_evidence_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    storage_mode: Literal["IN_MEMORY_SYNTHETIC", "DURABLE_DATABASE"] = "IN_MEMORY_SYNTHETIC"
    created_at: OffsetAwareDatetime
    updated_at: OffsetAwareDatetime


class RecoveryTriggerCaseView(ContractModel):
    """Safe read model for cases that exist before P2 inputs are resolvable."""

    case_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    commitment_id: str = Field(min_length=1)
    case_version: int = Field(ge=1)
    commitment_version: int = Field(ge=1)
    status: RecoveryCaseStatus
    evaluation_readiness: Literal[
        "AWAITING_EVALUATION_INPUTS",
        "CASE_COMPLETED",
    ] = "AWAITING_EVALUATION_INPUTS"
    missing_evaluation_inputs: list[str]
    trigger_events: list[RecoveryTriggerReference]
    resolution_events: list[RecoveryResolutionReference] = Field(default_factory=list)
    storage_mode: Literal["IN_MEMORY_SYNTHETIC", "DURABLE_DATABASE"] = "IN_MEMORY_SYNTHETIC"
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


class ExecuteRecoveryTaskRequest(ContractModel):
    expected_plan_version: int = Field(ge=1)
    expected_commitment_version: int = Field(ge=1)
    expected_snapshot_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=1)


class DurableActionView(ContractModel):
    execution_id: str
    tenant_id: str
    commitment_id: str
    plan_id: str
    plan_version: int
    approval_id: str
    status: str
    attempts: int
    task_id: str | None = None
    receipt_ref: str | None = None
    audit_id: str | None = None
    last_error: str | None = None
    created_at: OffsetAwareDatetime
    updated_at: OffsetAwareDatetime


class FeasibilityEvaluationResult(ContractModel):
    status: FeasibilityState
    solver_status: str = Field(min_length=1)
    constraints: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
