from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from threading import RLock
from typing import Any

from app.core.errors import DomainError
from app.core.schemas import ApprovalState, Commitment, ExecutionState, FeasibilityState

from .feasibility import FeasibilityEvaluator, SyntheticP2Evaluator
from .fixtures import DemoRecoveryInputs, load_demo_recovery_inputs
from .models import (
    BusinessPreferences,
    PlanEvaluation,
    RecoveryCase,
    RecoveryCaseStatus,
    RecoveryOption,
    RecoveryPlanList,
    RecoveryPlanVersion,
    RecoveryStrategy,
    RiskLevel,
    SolverReadiness,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _risk_score(level: RiskLevel) -> Decimal:
    return {
        RiskLevel.LOW: Decimal("0"),
        RiskLevel.MEDIUM: Decimal("1"),
        RiskLevel.HIGH: Decimal("2"),
        RiskLevel.UNKNOWN: Decimal("3"),
    }[level]


def _impact_score(value: str) -> Decimal:
    return {
        "LOW": Decimal("0"),
        "MEDIUM": Decimal("1"),
        "HIGH": Decimal("2"),
        "UNKNOWN": Decimal("3"),
    }.get(value.upper(), Decimal("3"))


def _ranking_score(
    *,
    cost: Decimal,
    delay_minutes: int,
    risk: RiskLevel,
    customer_impact: str,
    preferences: BusinessPreferences,
) -> Decimal:
    # The score is a transparent weighted comparison, not a universal BEST rule.
    return (
        preferences.cost_weight * (cost / Decimal("100"))
        + preferences.delay_weight * (Decimal(delay_minutes) / Decimal("1440"))
        + preferences.risk_weight * _risk_score(risk)
        + preferences.customer_impact_weight * _impact_score(customer_impact)
    ).quantize(Decimal("0.01"))


def _readiness(status: FeasibilityState) -> SolverReadiness:
    return {
        FeasibilityState.FEASIBLE: SolverReadiness.VALIDATED,
        FeasibilityState.CONDITIONAL: SolverReadiness.CONDITIONAL,
        FeasibilityState.INFEASIBLE: SolverReadiness.INFEASIBLE,
        FeasibilityState.UNKNOWN: SolverReadiness.UNKNOWN,
        FeasibilityState.NOT_ASSESSED: SolverReadiness.PENDING_EVALUATION,
    }[status]


@dataclass(frozen=True)
class _Candidate:
    option_id: str
    plan_id: str
    strategy: RecoveryStrategy
    label: str
    estimated_extra_cost: Decimal
    estimated_delay_minutes: int
    risk_level: RiskLevel
    customer_impact: str
    risks: list[str]
    constraints: list[str]
    evidence_refs: list[str]
    assumptions: list[str]
    proposed_changes: dict[str, Any]
    action_type: str
    action_parameters: dict[str, Any]
    action_preconditions: list[str]


class RecoveryRepository:
    """Tenant-scoped synthetic repository used until P3 persistence is agreed."""

    def __init__(self) -> None:
        self._cases: dict[tuple[str, str], RecoveryCase] = {}
        self._plans: dict[tuple[str, str], RecoveryPlanVersion] = {}
        self._lock = RLock()

    @staticmethod
    def _copy(value: RecoveryCase | RecoveryPlanVersion) -> RecoveryCase | RecoveryPlanVersion:
        return type(value).model_validate(value.model_dump(mode="python"))

    def get_case(self, tenant_id: str, commitment_id: str) -> RecoveryCase | None:
        with self._lock:
            case = self._cases.get((tenant_id, commitment_id))
            return self._copy(case) if case else None  # type: ignore[return-value]

    def save_case(self, case: RecoveryCase) -> RecoveryCase:
        with self._lock:
            self._cases[(case.tenant_id, case.commitment_id)] = self._copy(case)  # type: ignore[assignment]
            for plan in case.plans:
                self._plans[(case.tenant_id, plan.plan_id)] = self._copy(plan)  # type: ignore[assignment]
            return self._copy(case)  # type: ignore[return-value]

    def get_plan(self, tenant_id: str, plan_id: str) -> RecoveryPlanVersion | None:
        with self._lock:
            plan = self._plans.get((tenant_id, plan_id))
            return self._copy(plan) if plan else None  # type: ignore[return-value]


class RecoveryPlanner:
    def __init__(
        self,
        *,
        inputs: DemoRecoveryInputs | None = None,
        repository: RecoveryRepository | None = None,
        evaluator: FeasibilityEvaluator | None = None,
    ) -> None:
        self.inputs = inputs or load_demo_recovery_inputs()
        self.repository = repository or RecoveryRepository()
        self.evaluator = evaluator or SyntheticP2Evaluator()

    def _assert_tenant(self, tenant_id: str, commitment: Commitment) -> None:
        if tenant_id != commitment.tenant_id:
            raise DomainError(
                "TENANT_SCOPE_VIOLATION",
                "Recovery case is not available for this tenant",
                status_code=404,
                details={"commitment_id": commitment.commitment_id},
            )

    def _get_commitment(self, tenant_id: str, commitment_id: str) -> Commitment:
        commitment = self.inputs.commitment
        if commitment_id != commitment.commitment_id:
            raise DomainError(
                "RECOVERY_CASE_NOT_FOUND",
                "Recovery case was not found",
                status_code=404,
                details={"commitment_id": commitment_id},
            )
        self._assert_tenant(tenant_id, commitment)
        return commitment

    def _skeleton(self, tenant_id: str, commitment_id: str) -> RecoveryCase:
        commitment = self._get_commitment(tenant_id, commitment_id)
        now = _now()
        return RecoveryCase(
            case_id="rc_001" if commitment_id == "com_001" else f"rc_{commitment_id}",
            tenant_id=tenant_id,
            commitment_id=commitment_id,
            case_version=1,
            commitment_version=commitment.commitment_version,
            status=RecoveryCaseStatus.OPEN,
            commitment=commitment,
            trigger_assessment=self.inputs.assessment,
            operational_snapshot=self.inputs.snapshot,
            preferences=BusinessPreferences(),
            approval_decisions=[self.inputs.approval],
            customer_confirmation_evidence_refs=self.inputs.customer_confirmation_evidence_refs,
            fulfilment_evidence_refs=self.inputs.fulfilment_evidence_refs,
            evidence_refs=self.inputs.incident_evidence_refs,
            created_at=now,
            updated_at=now,
        )

    def get_case(self, tenant_id: str, commitment_id: str) -> RecoveryCase:
        self._get_commitment(tenant_id, commitment_id)
        stored = self.repository.get_case(tenant_id, commitment_id)
        if stored:
            return stored
        return self.repository.save_case(self._skeleton(tenant_id, commitment_id))

    def _candidates(self, case: RecoveryCase) -> list[_Candidate]:
        assessment = case.trigger_assessment
        evidence_refs = _unique(assessment.evidence_refs + self.inputs.snapshot.evidence_refs)
        return [
            _Candidate(
                option_id="option_a",
                plan_id="plan_a",
                strategy=RecoveryStrategy.ALTERNATIVE_SUPPLY,
                label="Alternative supply for packaging shortage",
                estimated_extra_cost=Decimal("80.00"),
                estimated_delay_minutes=0,
                risk_level=RiskLevel.HIGH,
                customer_impact="LOW",
                risks=["ALTERNATIVE_SUPPLY_PENDING"],
                constraints=[
                    "Supplier availability is not confirmed",
                    "Manager approval is required before any purchase request",
                ],
                evidence_refs=evidence_refs + ["ev_alt_supply_request_001"],
                assumptions=["An alternative supplier can offer 20 PACKAGING units before cutoff."],
                proposed_changes={
                    "strategy": RecoveryStrategy.ALTERNATIVE_SUPPLY.value,
                    "resource_id": "PACKAGING",
                    "quantity": "20",
                    "supplier_id": "supplier_alt_01",
                },
                action_type="CREATE_PURCHASE_REQUEST",
                action_parameters={
                    "resource_id": "PACKAGING",
                    "quantity": "20",
                    "supplier_id": "supplier_alt_01",
                },
                action_preconditions=[
                    "Supplier availability confirmation is recorded",
                    "Manager approval is recorded for this plan version",
                    "P2 evaluation is not stale",
                ],
            ),
            _Candidate(
                option_id="option_b",
                plan_id="plan_b",
                strategy=RecoveryStrategy.RESCHEDULE_PARTIAL_FULFILMENT,
                label="Reschedule with partial fulfilment proposal",
                estimated_extra_cost=Decimal("0.00"),
                estimated_delay_minutes=1440,
                risk_level=RiskLevel.MEDIUM,
                customer_impact="MEDIUM",
                risks=["CUSTOMER_ACCEPTANCE_REQUIRED"],
                constraints=[
                    "Customer acceptance is required for the revised deadline",
                    "No fulfilment execution evidence exists yet",
                ],
                evidence_refs=evidence_refs + ["ev_customer_accept_001", "fev_001"],
                assumptions=["The customer accepts a 24-hour delivery-window change."],
                proposed_changes={
                    "strategy": RecoveryStrategy.RESCHEDULE_PARTIAL_FULFILMENT.value,
                    "quantity": "80",
                    "deadline": "2026-10-25T15:00:00+08:00",
                },
                action_type="CREATE_DELIVERY_CHANGE_PROPOSAL",
                action_parameters={
                    "new_deadline": "2026-10-25T15:00:00+08:00",
                    "partial_quantity": "80",
                },
                action_preconditions=[
                    "Manager approval is recorded for this plan version",
                    "Customer accepts the revised proposal version",
                ],
            ),
        ]

    def generate(
        self,
        tenant_id: str,
        commitment_id: str,
        *,
        expected_commitment_version: int,
        assessment_id: str | None = None,
        preferences: BusinessPreferences | None = None,
    ) -> RecoveryCase:
        commitment = self._get_commitment(tenant_id, commitment_id)
        if expected_commitment_version != commitment.commitment_version:
            raise DomainError(
                "COMMITMENT_VERSION_CONFLICT",
                "Recovery planning requires the current commitment version",
                status_code=409,
                details={
                    "expected_commitment_version": expected_commitment_version,
                    "current_commitment_version": commitment.commitment_version,
                },
            )

        assessment = self.inputs.assessment
        if assessment_id and assessment_id != assessment.assessment_id:
            raise DomainError(
                "ASSESSMENT_NOT_FOUND",
                "The requested feasibility assessment was not found",
                status_code=404,
                details={"assessment_id": assessment_id},
            )
        if assessment.commitment_version > commitment.commitment_version:
            raise DomainError(
                "ASSESSMENT_VERSION_CONFLICT",
                "The feasibility assessment is newer than the commitment version",
                status_code=409,
                details={
                    "assessment_commitment_version": assessment.commitment_version,
                    "current_commitment_version": commitment.commitment_version,
                },
            )

        existing = self.repository.get_case(tenant_id, commitment_id)
        if existing and existing.plans and existing.trigger_assessment.assessment_id == assessment.assessment_id:
            return existing

        case = existing or self._skeleton(tenant_id, commitment_id)
        case.preferences = preferences or case.preferences
        generated_at = _now()
        plans: list[RecoveryPlanVersion] = []
        for candidate in self._candidates(case):
            result = self.evaluator.evaluate(case.operational_snapshot, candidate.proposed_changes, commitment)
            score = _ranking_score(
                cost=candidate.estimated_extra_cost,
                delay_minutes=candidate.estimated_delay_minutes,
                risk=candidate.risk_level,
                customer_impact=candidate.customer_impact,
                preferences=case.preferences,
            )
            evaluation = PlanEvaluation(
                evaluation_id=f"eval_{candidate.plan_id}_v1",
                tenant_id=tenant_id,
                commitment_id=commitment_id,
                plan_id=candidate.plan_id,
                plan_version=1,
                commitment_version=commitment.commitment_version,
                snapshot_version=case.operational_snapshot.snapshot_version,
                feasibility_status=result.status,
                validation_source=result.validation_source,
                readiness=_readiness(result.status),
                solver_status=result.solver_status,
                constraints=_unique(candidate.constraints + result.constraints),
                evidence_refs=_unique(candidate.evidence_refs + result.evidence_refs),
                assumptions=_unique(candidate.assumptions + result.assumptions),
                evaluated_at=generated_at,
            )
            plans.append(
                RecoveryPlanVersion(
                    tenant_id=tenant_id,
                    recovery_case_id=case.case_id,
                    plan_id=candidate.plan_id,
                    plan_version=1,
                    commitment_id=commitment_id,
                    based_on_assessment_id=assessment.assessment_id,
                    snapshot_version=case.operational_snapshot.snapshot_version,
                    feasibility_status=result.status,
                    estimated_extra_cost=candidate.estimated_extra_cost,
                    currency="MYR",
                    estimated_delay_minutes=candidate.estimated_delay_minutes,
                    risks=candidate.risks,
                    actions=[
                        {
                            "action_id": f"{candidate.plan_id}_action_001",
                            "type": candidate.action_type,
                            "requires_approval": True,
                            "idempotency_key": f"{candidate.plan_id}_v1_action_001",
                            "parameters": candidate.action_parameters,
                            "preconditions": candidate.action_preconditions,
                        }
                    ],
                    approval_state=ApprovalState.PENDING,
                    execution_state=ExecutionState.NOT_STARTED,
                    option_id=candidate.option_id,
                    strategy=candidate.strategy,
                    risk_level=candidate.risk_level,
                    customer_impact=candidate.customer_impact,
                    constraints=evaluation.constraints,
                    evidence_refs=evaluation.evidence_refs,
                    assumptions=evaluation.assumptions,
                    ranking_score=score,
                    evaluation=evaluation,
                )
            )

        eligible = [
            plan
            for plan in plans
            if plan.feasibility_status not in {FeasibilityState.INFEASIBLE, FeasibilityState.UNKNOWN}
            and (
                case.preferences.max_extra_cost is None
                or plan.estimated_extra_cost <= case.preferences.max_extra_cost
            )
        ]
        if eligible:
            recommended = min(eligible, key=lambda plan: plan.ranking_score)
            recommendation_reason = (
                "Lowest weighted score under the supplied cost, delay, risk, and customer-impact preferences; "
                "conditional options remain review-only until their constraints are cleared."
            )
            for plan in plans:
                plan.recommended = plan.plan_id == recommended.plan_id
                plan.recommendation_reason = recommendation_reason if plan.recommended else None

        case.plans = plans
        case.options = [
            RecoveryOption(
                option_id=plan.option_id,
                plan_id=plan.plan_id,
                strategy=plan.strategy,
                label=next(c.label for c in self._candidates(case) if c.plan_id == plan.plan_id),
                estimated_extra_cost=plan.estimated_extra_cost,
                currency=plan.currency,
                estimated_delay_minutes=plan.estimated_delay_minutes,
                feasibility_status=plan.feasibility_status,
                validation_source=plan.evaluation.validation_source,
                risk_level=plan.risk_level,
                customer_impact=plan.customer_impact,
                constraints=plan.constraints,
                evidence_refs=plan.evidence_refs,
                assumptions=plan.assumptions,
                ranking_score=plan.ranking_score,
                recommended=plan.recommended,
                recommendation_reason=plan.recommendation_reason,
            )
            for plan in plans
        ]
        case.case_version += 1
        case.status = RecoveryCaseStatus.OPTIONS_READY if eligible else RecoveryCaseStatus.NO_SAFE_PLAN
        case.commitment_version = commitment.commitment_version
        case.updated_at = generated_at
        return self.repository.save_case(case)

    def list_plans(self, tenant_id: str, commitment_id: str) -> RecoveryPlanList:
        case = self.get_case(tenant_id, commitment_id)
        return RecoveryPlanList(
            tenant_id=tenant_id,
            commitment_id=commitment_id,
            case_id=case.case_id,
            plans=case.plans,
        )

    def get_plan(self, tenant_id: str, plan_id: str) -> RecoveryPlanVersion:
        plan = self.repository.get_plan(tenant_id, plan_id)
        if not plan:
            raise DomainError(
                "RECOVERY_PLAN_NOT_FOUND",
                "Recovery plan was not found",
                status_code=404,
                details={"plan_id": plan_id},
            )
        return plan


default_recovery_planner = RecoveryPlanner()
