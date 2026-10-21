from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from threading import RLock
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.integration import CoreIntegrationFacade
from app.core.schemas import (
    ApprovalState,
    Commitment,
    ExecutionState,
    FeasibilityState,
    RecoveryState,
    RiskState,
)

from .eventing import (
    ApprovalRequiredPayload,
    PlanGeneratedPayload,
    RecoveryEventCoordinator,
    RecoveryEventType,
    ReplanRequiredPayload,
)
from .feasibility import FeasibilityEvaluator, SyntheticP2Evaluator
from .fixtures import DemoRecoveryInputs, load_demo_recovery_inputs
from .integrations import ActorContext, require_verified_actor
from .models import (
    ApprovalDecision,
    ApprovalDecisionInput,
    ApprovalDecisionState,
    ApprovalRequestInput,
    BusinessPreferences,
    PlanEvaluation,
    RecoveryCase,
    RecoveryCaseStatus,
    RecoveryOption,
    RecoveryPlanList,
    RecoveryPlanVersion,
    RecoveryResolutionReference,
    RecoveryStrategy,
    RecoveryTriggerReference,
    RiskLevel,
    SolverReadiness,
    ValidationSource,
)
from .ranking import RankingCandidate, rank_candidates


def _now() -> datetime:
    return datetime.now(UTC)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


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
    operational_disruption_level: Decimal
    supplier_uncertainty_level: Decimal
    customer_confirmation_required: bool
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
        self._cases_by_id: dict[tuple[str, str], RecoveryCase] = {}
        self._plans: dict[tuple[str, str], RecoveryPlanVersion] = {}
        self._processed_trigger_events: dict[tuple[str, str], str] = {}
        self._processed_resolution_events: dict[tuple[str, str], str] = {}
        self._lock = RLock()

    @property
    def durable(self) -> bool:
        return False

    @staticmethod
    def _copy(value: RecoveryCase | RecoveryPlanVersion) -> RecoveryCase | RecoveryPlanVersion:
        return type(value).model_validate(value.model_dump(mode="python"))

    def get_case(self, tenant_id: str, commitment_id: str) -> RecoveryCase | None:
        with self._lock:
            case = self._cases.get((tenant_id, commitment_id))
            return self._copy(case) if case else None  # type: ignore[return-value]

    def get_case_by_id(self, tenant_id: str, case_id: str) -> RecoveryCase | None:
        with self._lock:
            case = self._cases_by_id.get((tenant_id, case_id))
            return self._copy(case) if case else None  # type: ignore[return-value]

    def get_case_for_trigger_event(self, tenant_id: str, event_id: str) -> RecoveryCase | None:
        with self._lock:
            case_id = self._processed_trigger_events.get((tenant_id, event_id))
            case = self._cases_by_id.get((tenant_id, case_id)) if case_id else None
            return self._copy(case) if case else None  # type: ignore[return-value]

    def has_processed_resolution_event(self, tenant_id: str, event_id: str) -> bool:
        with self._lock:
            return (tenant_id, event_id) in self._processed_resolution_events

    def get_case_for_resolution_event(self, tenant_id: str, event_id: str) -> RecoveryCase | None:
        with self._lock:
            case_id = self._processed_resolution_events.get((tenant_id, event_id))
            case = self._cases_by_id.get((tenant_id, case_id)) if case_id else None
            return self._copy(case) if case else None  # type: ignore[return-value]

    def has_processed_trigger_event(self, tenant_id: str, event_id: str) -> bool:
        with self._lock:
            return (tenant_id, event_id) in self._processed_trigger_events

    def save_case(self, case: RecoveryCase) -> RecoveryCase:
        with self._lock:
            stored = self._copy(case)
            self._cases_by_id[(case.tenant_id, case.case_id)] = stored  # type: ignore[assignment]
            active_key = (case.tenant_id, case.commitment_id)
            active_case = self._cases.get(active_key)
            if active_case is None or active_case.case_id == case.case_id or active_case.status == RecoveryCaseStatus.COMPLETED:
                self._cases[active_key] = stored  # type: ignore[assignment]
            for plan in case.plans:
                self._plans[(case.tenant_id, plan.plan_id)] = self._copy(plan)  # type: ignore[assignment]
            return self._copy(case)  # type: ignore[return-value]

    @staticmethod
    def _append_approval_invalidations(case: RecoveryCase, reason: str, event_id: str) -> None:
        system_actor = ActorContext(
            case.tenant_id,
            "system:p3",
            "SYSTEM",
            f"recovery-case:{case.case_id}",
            event_id,
            True,
        )
        for plan in case.plans:
            latest = next((
                item for item in reversed(case.approval_decisions)
                if item.plan_id == plan.plan_id and item.plan_version == plan.plan_version
            ), None)
            if latest is None or latest.decision not in {
                ApprovalDecisionState.REQUESTED,
                ApprovalDecisionState.APPROVED,
            }:
                continue
            case.approval_decisions.append(RecoveryPlanner._new_approval_record(
                actor=system_actor,
                case=case,
                plan=plan,
                decision=ApprovalDecisionState.INVALIDATED,
                reason=reason,
                evidence_refs=latest.evidence_refs,
                approved_cost_limit=latest.approved_cost_limit,
                expires_at=latest.expires_at,
                action_scope=latest.action_scope,
                idempotency_key=f"{event_id}:invalidate:{plan.plan_id}:v{plan.plan_version}",
            ))

    def record_trigger_event(
        self,
        case: RecoveryCase,
        trigger: RecoveryTriggerReference,
    ) -> tuple[RecoveryCase, bool, bool]:
        """Atomically reuse/create one active case and deduplicate this event.

        Returns (case, created, duplicate). This is process-local only; P5's
        ProcessedEventRecord remains the durable dispatcher dedupe boundary.
        """
        event_key = (trigger.tenant_id, trigger.event_id)
        case_key = (trigger.tenant_id, trigger.commitment_id)
        with self._lock:
            prior_case_id = self._processed_trigger_events.get(event_key)
            if prior_case_id is not None:
                prior_case = self._cases_by_id.get((trigger.tenant_id, prior_case_id))
                if prior_case is None:
                    return self._copy(case), False, True  # type: ignore[return-value]
                return self._copy(prior_case), False, True  # type: ignore[return-value]

            existing_case = self._cases.get(case_key)
            if (existing_case is not None
                    and trigger.commitment_version < existing_case.commitment_version):
                raise DomainError(
                    "RECOVERY_TRIGGER_STALE",
                    "The P3 case already contains a newer Commitment version",
                    status_code=409,
                    details={
                        "trigger_commitment_version": trigger.commitment_version,
                        "case_commitment_version": existing_case.commitment_version,
                    },
                )
            if existing_case is not None and existing_case.status == RecoveryCaseStatus.COMPLETED:
                # A verified P5 resolution closes the previous episode. Keep it
                # addressable by case_id and start a fresh case for the new risk.
                saved_case = case
                created = True
            elif existing_case is None:
                saved_case = case
                created = True
            else:
                created = False
                saved_case = self._copy(existing_case)  # type: ignore[assignment]
                prior_assessment_ids = {item.assessment_id for item in saved_case.trigger_events}
                new_material_trigger = (
                    trigger.commitment_version != saved_case.commitment_version
                    or trigger.assessment_id not in prior_assessment_ids
                )
                saved_case.trigger_events.append(trigger)
                saved_case.evidence_refs = list(dict.fromkeys([
                    *saved_case.evidence_refs, *trigger.evidence_refs,
                ]))
                saved_case.updated_at = _now()
                if new_material_trigger:
                    saved_case.case_version += 1
                    self._append_approval_invalidations(
                        saved_case,
                        "A material commitment.at_risk trigger makes the prior approval stale",
                        trigger.event_id,
                    )
                    saved_case.commitment = case.commitment
                    saved_case.commitment_version = trigger.commitment_version
                    # Keep old plans/decisions for audit; none are current until
                    # authoritative P2 inputs are resolved and plans regenerated.
                    saved_case.trigger_assessment = None
                    saved_case.operational_snapshot = None
                    saved_case.status = (
                        RecoveryCaseStatus.NEEDS_REPLAN if saved_case.plans
                        else RecoveryCaseStatus.AWAITING_EVALUATION_INPUTS
                    )

            stored_case = self._copy(saved_case)
            self._cases[case_key] = stored_case  # type: ignore[assignment]
            self._cases_by_id[(saved_case.tenant_id, saved_case.case_id)] = stored_case  # type: ignore[assignment]
            for plan in saved_case.plans:
                self._plans[(saved_case.tenant_id, plan.plan_id)] = self._copy(plan)  # type: ignore[assignment]
            self._processed_trigger_events[event_key] = saved_case.case_id
            return self._copy(saved_case), created, False  # type: ignore[return-value]

    def complete_resolved_case(
        self,
        commitment: Commitment,
        resolution: RecoveryResolutionReference,
    ) -> tuple[RecoveryCase | None, bool]:
        """Close only a matching case after P5's current state confirms resolution."""
        event_key = (resolution.tenant_id, resolution.event_id)
        case_key = (resolution.tenant_id, resolution.commitment_id)
        with self._lock:
            prior_case_id = self._processed_resolution_events.get(event_key)
            if prior_case_id is not None:
                prior_case = self._cases_by_id.get((resolution.tenant_id, prior_case_id))
                return (self._copy(prior_case) if prior_case else None), False  # type: ignore[return-value]

            case = self._cases.get(case_key)
            if case is None:
                return None, False
            saved_case = self._copy(case)
            if saved_case.status == RecoveryCaseStatus.COMPLETED:
                self._processed_resolution_events[event_key] = saved_case.case_id
                return self._copy(saved_case), False  # type: ignore[return-value]
            if resolution.commitment_version < saved_case.commitment_version:
                raise DomainError(
                    "RECOVERY_RESOLUTION_STALE",
                    "The P3 case already contains a newer Commitment version",
                    status_code=409,
                    details={
                        "resolution_commitment_version": resolution.commitment_version,
                        "case_commitment_version": saved_case.commitment_version,
                    },
                )
            self._append_approval_invalidations(
                saved_case,
                "The authoritative Commitment risk episode resolved; prior approval is no longer applicable",
                resolution.event_id,
            )
            saved_case.resolution_events.append(resolution)
            saved_case.commitment = commitment
            saved_case.commitment_version = commitment.commitment_version
            saved_case.case_version += 1
            saved_case.status = RecoveryCaseStatus.COMPLETED
            saved_case.updated_at = _now()
            stored_case = self._copy(saved_case)
            self._cases[case_key] = stored_case  # type: ignore[assignment]
            self._cases_by_id[(saved_case.tenant_id, saved_case.case_id)] = stored_case  # type: ignore[assignment]
            for plan in saved_case.plans:
                self._plans[(saved_case.tenant_id, plan.plan_id)] = self._copy(plan)  # type: ignore[assignment]
            self._processed_resolution_events[event_key] = saved_case.case_id
            return self._copy(saved_case), True  # type: ignore[return-value]

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
        event_coordinator: RecoveryEventCoordinator | None = None,
    ) -> None:
        self.inputs = inputs or load_demo_recovery_inputs()
        self.repository = repository or RecoveryRepository()
        self.evaluator = evaluator or SyntheticP2Evaluator()
        self.event_coordinator = event_coordinator or RecoveryEventCoordinator()

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
        stored = self.repository.get_case(tenant_id, commitment_id)
        if stored:
            return stored
        self._get_commitment(tenant_id, commitment_id)
        return self.repository.save_case(self._skeleton(tenant_id, commitment_id))

    def create_trigger_case(
        self,
        commitment: Commitment,
        trigger: RecoveryTriggerReference,
    ) -> tuple[RecoveryCase, bool, bool]:
        """Create/reuse an event-triggered case without inventing P2 inputs."""
        if (commitment.tenant_id, commitment.commitment_id, commitment.commitment_version) != (
            trigger.tenant_id, trigger.commitment_id, trigger.commitment_version,
        ):
            raise DomainError(
                "RECOVERY_TRIGGER_BINDING_MISMATCH",
                "Recovery trigger does not match the authoritative Commitment",
                status_code=409,
            )
        now = _now()
        candidate = RecoveryCase(
            case_id=f"rc_{uuid4().hex[:16]}",
            tenant_id=commitment.tenant_id,
            commitment_id=commitment.commitment_id,
            case_version=1,
            commitment_version=commitment.commitment_version,
            status=RecoveryCaseStatus.AWAITING_EVALUATION_INPUTS,
            commitment=commitment,
            trigger_assessment=None,
            operational_snapshot=None,
            trigger_events=[trigger],
            preferences=BusinessPreferences(),
            evidence_refs=list(trigger.evidence_refs),
            created_at=now,
            updated_at=now,
        )
        return self.repository.record_trigger_event(candidate, trigger)

    def complete_resolved_case(
        self,
        commitment: Commitment,
        resolution: RecoveryResolutionReference,
    ) -> tuple[RecoveryCase | None, bool]:
        """Close P3 history only after a P5 event and current Commitment agree."""
        if (commitment.tenant_id, commitment.commitment_id, commitment.commitment_version) != (
            resolution.tenant_id, resolution.commitment_id, resolution.commitment_version,
        ):
            raise DomainError(
                "RECOVERY_RESOLUTION_BINDING_MISMATCH",
                "Resolution event does not match the authoritative Commitment identity and version",
                status_code=409,
            )
        if (commitment.risk_state != RiskState.RESOLVED
                or commitment.recovery_state != RecoveryState.COMPLETED):
            raise DomainError(
                "RECOVERY_RESOLUTION_NOT_AUTHORITATIVE",
                "P5 has not confirmed a resolved risk and completed recovery state",
                status_code=409,
            )
        return self.repository.complete_resolved_case(commitment, resolution)

    def _candidates(self, case: RecoveryCase) -> list[_Candidate]:
        assessment = case.trigger_assessment
        if assessment is None:
            raise DomainError(
                "AUTHORITATIVE_RECOVERY_INPUT_REQUIRED",
                "Recovery planning requires the complete triggering P2 assessment",
                status_code=409,
            )
        evidence_refs = _unique(assessment.evidence_refs + self.inputs.snapshot.evidence_refs)
        plan_prefix = "" if case.case_id == "rc_001" else f"{case.case_id}_"
        return [
            _Candidate(
                option_id="option_a",
                plan_id=f"{plan_prefix}plan_a",
                strategy=RecoveryStrategy.ALTERNATIVE_SUPPLY,
                label="Alternative supply for packaging shortage",
                estimated_extra_cost=Decimal("80.00"),
                estimated_delay_minutes=0,
                risk_level=RiskLevel.HIGH,
                customer_impact="LOW",
                operational_disruption_level=Decimal(3),
                supplier_uncertainty_level=Decimal(5),
                customer_confirmation_required=False,
                risks=["ALTERNATIVE_SUPPLY_PENDING"],
                constraints=[
                    "Supplier availability is not confirmed",
                    "Manager approval is required before any purchase request",
                ],
                evidence_refs=evidence_refs + ["ev_alt_supply_request_001"],
                assumptions=[
                    "An alternative supplier can offer 20 PACKAGING units before cutoff.",
                    "Disruption and uncertainty levels use the synthetic 0–5 policy rubric, not measured probabilities.",
                ],
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
                plan_id=f"{plan_prefix}plan_b",
                strategy=RecoveryStrategy.RESCHEDULE_PARTIAL_FULFILMENT,
                label="Reschedule with partial fulfilment proposal",
                estimated_extra_cost=Decimal("0.00"),
                estimated_delay_minutes=1440,
                risk_level=RiskLevel.MEDIUM,
                customer_impact="MEDIUM",
                operational_disruption_level=Decimal(4),
                supplier_uncertainty_level=Decimal(0),
                customer_confirmation_required=True,
                risks=["CUSTOMER_ACCEPTANCE_REQUIRED"],
                constraints=[
                    "Customer acceptance is required for the revised deadline",
                    "No fulfilment execution evidence exists yet",
                ],
                evidence_refs=evidence_refs + ["ev_customer_accept_001", "fev_001"],
                assumptions=[
                    "The customer accepts a 24-hour delivery-window change.",
                    "Disruption and uncertainty levels use the synthetic 0–5 policy rubric, not measured probabilities.",
                ],
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
        correlation_id: str | None = None,
        causation_id: str | None = None,
        db: Session | None = None,
        request_context: RequestContext | None = None,
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
        if existing and existing.status == RecoveryCaseStatus.COMPLETED:
            raise DomainError(
                "RECOVERY_CASE_COMPLETED",
                "A completed recovery episode cannot be reopened; a new P5 risk trigger creates a separate case",
                status_code=409,
                details={"recovery_case_id": existing.case_id},
            )
        if existing and existing.trigger_events and (
            existing.trigger_assessment is None or existing.operational_snapshot is None
        ):
            raise DomainError(
                "AUTHORITATIVE_RECOVERY_INPUT_REQUIRED",
                "This event-created case needs the complete P2 assessment and operational snapshot before planning",
                status_code=409,
            )
        if existing and existing.plans and existing.trigger_assessment is not None \
                and existing.trigger_assessment.assessment_id == assessment.assessment_id:
            return existing

        case = existing or self._skeleton(tenant_id, commitment_id)
        case.trigger_assessment = assessment
        snapshot = case.operational_snapshot
        if snapshot is None:
            raise DomainError(
                "AUTHORITATIVE_RECOVERY_INPUT_REQUIRED",
                "Recovery planning requires a current operational snapshot",
                status_code=409,
            )
        case.preferences = preferences or case.preferences
        generated_at = _now()
        plans: list[RecoveryPlanVersion] = []
        evaluated_candidates = []
        for candidate in self._candidates(case):
            result = self.evaluator.evaluate(snapshot, candidate.proposed_changes, commitment)
            affected_commitment_ids = result.affected_commitment_ids or assessment.affected_commitment_ids
            if not result.affected_commitment_ids and affected_commitment_ids:
                result.assumptions.append(
                    "Affected commitment count falls back to the triggering assessment until P2 returns candidate-specific impact."
                )
            ranking_candidate = RankingCandidate(
                plan_id=candidate.plan_id,
                feasibility_status=result.status,
                validation_source=result.validation_source,
                additional_cost_myr=candidate.estimated_extra_cost,
                delivery_delay_minutes=candidate.estimated_delay_minutes,
                affected_commitment_ids=tuple(affected_commitment_ids),
                operational_disruption_level=candidate.operational_disruption_level,
                supplier_uncertainty_level=candidate.supplier_uncertainty_level,
                customer_confirmation_required=candidate.customer_confirmation_required,
                hard_constraint_reasons=tuple(result.hard_constraint_reasons),
            )
            evaluated_candidates.append((candidate, result, affected_commitment_ids, ranking_candidate))

        ranking_decisions = rank_candidates([item[3] for item in evaluated_candidates], case.preferences)

        for candidate, result, affected_commitment_ids, _ in evaluated_candidates:
            decision = ranking_decisions[candidate.plan_id]
            evaluation = PlanEvaluation(
                evaluation_id=f"eval_{candidate.plan_id}_v1",
                tenant_id=tenant_id,
                commitment_id=commitment_id,
                plan_id=candidate.plan_id,
                plan_version=1,
                commitment_version=commitment.commitment_version,
                snapshot_version=snapshot.snapshot_version,
                feasibility_status=result.status,
                validation_source=result.validation_source,
                readiness=_readiness(result.status),
                solver_status=result.solver_status,
                constraints=_unique(candidate.constraints + result.constraints),
                hard_constraint_reasons=list(result.hard_constraint_reasons),
                affected_commitment_ids=list(affected_commitment_ids),
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
                    snapshot_version=snapshot.snapshot_version,
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
                    affected_commitment_count=len(set(affected_commitment_ids)),
                    operational_disruption_level=candidate.operational_disruption_level,
                    supplier_uncertainty_level=candidate.supplier_uncertainty_level,
                    customer_confirmation_required=candidate.customer_confirmation_required,
                    constraints=evaluation.constraints,
                    evidence_refs=evaluation.evidence_refs,
                    assumptions=evaluation.assumptions,
                    ranking_score=decision.score_breakdown.total_score if decision.score_breakdown else None,
                    score_breakdown=decision.score_breakdown,
                    rank=decision.rank,
                    ranking_exclusion_reasons=list(decision.exclusion_reasons),
                    recommended=decision.recommended,
                    recommendation_label=decision.recommendation_label,
                    recommendation_qualification=decision.recommendation_qualification,
                    recommendation_reason=decision.recommendation_reason,
                    evaluation=evaluation,
                )
            )

        previous_plans = {plan.plan_id: plan for plan in case.plans}
        for plan in plans:
            previous = previous_plans.get(plan.plan_id)
            if previous is None:
                continue
            before = (
                previous.based_on_assessment_id, previous.evaluation.commitment_version,
                previous.snapshot_version, previous.feasibility_status, previous.estimated_extra_cost,
                [action.model_dump(mode="json") for action in previous.actions], previous.evidence_refs,
                previous.assumptions, previous.constraints,
            )
            after = (
                plan.based_on_assessment_id, plan.evaluation.commitment_version, plan.snapshot_version,
                plan.feasibility_status, plan.estimated_extra_cost,
                [action.model_dump(mode="json") for action in plan.actions], plan.evidence_refs,
                plan.assumptions, plan.constraints,
            )
            if before == after:
                continue
            plan.plan_version = previous.plan_version + 1
            plan.evaluation.plan_version = plan.plan_version
            plan.evaluation.evaluation_id = f"eval_{plan.plan_id}_v{plan.plan_version}"
            active = [item for item in case.approval_decisions
                      if item.plan_id == previous.plan_id and item.plan_version == previous.plan_version
                      and item.decision in {ApprovalDecisionState.REQUESTED, ApprovalDecisionState.APPROVED}]
            system_actor = ActorContext(case.tenant_id, "system:p3", "SYSTEM", f"corr_{case.case_id}", None, True)
            for prior in active:
                invalidation = self._new_approval_record(
                    actor=system_actor, case=case, plan=previous,
                    decision=ApprovalDecisionState.INVALIDATED,
                    reason=f"Plan materially changed; approval for version {previous.plan_version} is no longer applicable",
                    evidence_refs=prior.evidence_refs,
                    approved_cost_limit=prior.approved_cost_limit,
                    expires_at=prior.expires_at,
                    action_scope=prior.action_scope,
                    idempotency_key=prior.idempotency_key,
                )
                case.approval_decisions.append(invalidation)

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
                affected_commitment_count=plan.affected_commitment_count,
                operational_disruption_level=plan.operational_disruption_level,
                supplier_uncertainty_level=plan.supplier_uncertainty_level,
                customer_confirmation_required=plan.customer_confirmation_required,
                ranking_score=plan.ranking_score,
                score_breakdown=plan.score_breakdown,
                rank=plan.rank,
                ranking_exclusion_reasons=plan.ranking_exclusion_reasons,
                recommended=plan.recommended,
                recommendation_label=plan.recommendation_label,
                recommendation_qualification=plan.recommendation_qualification,
                recommendation_reason=plan.recommendation_reason,
            )
            for plan in plans
        ]
        case.case_version += 1
        case.status = (
            RecoveryCaseStatus.OPTIONS_READY
            if any(plan.rank is not None for plan in plans)
            else RecoveryCaseStatus.NO_SAFE_PLAN
        )
        case.commitment_version = commitment.commitment_version
        case.updated_at = generated_at
        saved = self.repository.save_case(case)
        for plan in saved.plans:
            event = self.event_coordinator.prepare(
                event_type=RecoveryEventType.PLAN_GENERATED,
                tenant_id=saved.tenant_id,
                commitment_id=saved.commitment_id,
                commitment_version=saved.commitment_version,
                recovery_case_id=saved.case_id,
                plan_id=plan.plan_id,
                plan_version=plan.plan_version,
                snapshot_version=plan.snapshot_version,
                correlation_id=correlation_id or f"recovery:{saved.case_id}",
                causation_id=causation_id or assessment.assessment_id,
                evidence_refs=tuple(plan.evidence_refs),
                payload=PlanGeneratedPayload(
                    evaluation_id=plan.evaluation.evaluation_id,
                    feasibility_status=plan.feasibility_status,
                    action_types=tuple(action.type for action in plan.actions),
                    recommended_under_policy=plan.recommendation_label == "RECOMMENDED_UNDER_POLICY",
                ),
                occurred_at=generated_at,
            )
            self.event_coordinator.publish(event, db=db, context=request_context)
        return saved

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

    @staticmethod
    def _require_approval_actor(actor: ActorContext) -> None:
        require_verified_actor(actor)
        if not actor.tenant_id or not actor.actor_id:
            raise DomainError("AUTH_CONTEXT_REQUIRED", "Tenant and actor are required", status_code=401)

    def _approval_target(self, actor: ActorContext, plan_id: str) -> tuple[RecoveryCase, RecoveryPlanVersion]:
        indexed_plan = self.get_plan(actor.tenant_id, plan_id)
        case = self.get_case(actor.tenant_id, indexed_plan.commitment_id)
        plan = next((item for item in case.plans if item.plan_id == plan_id), None)
        if plan is None:
            raise DomainError("RECOVERY_PLAN_NOT_FOUND", "Recovery plan was not found", status_code=404,
                              details={"plan_id": plan_id})
        if plan.tenant_id != actor.tenant_id or case.case_id != plan.recovery_case_id:
            raise DomainError("TENANT_SCOPE_VIOLATION", "Recovery plan is outside the actor tenant", status_code=404)
        return case, plan

    @staticmethod
    def _assert_approval_versions(
        case: RecoveryCase,
        plan: RecoveryPlanVersion,
        *,
        expected_commitment_version: int,
        expected_plan_version: int,
        expected_snapshot_version: int,
        current_commitment_version: int,
    ) -> None:
        if expected_commitment_version != current_commitment_version:
            raise DomainError("COMMITMENT_VERSION_CONFLICT", "Commitment version is stale", status_code=409,
                              details={"current_commitment_version": current_commitment_version})
        if expected_commitment_version != case.commitment_version or expected_commitment_version != plan.evaluation.commitment_version:
            raise DomainError("COMMITMENT_VERSION_CONFLICT", "Recovery plan was evaluated against a different commitment version",
                              status_code=409, details={"case_commitment_version": case.commitment_version,
                                                       "plan_commitment_version": plan.evaluation.commitment_version})
        if expected_plan_version != plan.plan_version:
            raise DomainError("RECOVERY_PLAN_VERSION_CONFLICT", "Recovery plan version is stale", status_code=409,
                              details={"current_plan_version": plan.plan_version})
        if case.operational_snapshot is None:
            raise DomainError(
                "AUTHORITATIVE_RECOVERY_INPUT_REQUIRED",
                "The recovery case has no current operational snapshot",
                status_code=409,
            )
        if expected_snapshot_version != plan.snapshot_version or expected_snapshot_version != case.operational_snapshot.snapshot_version:
            raise DomainError("SNAPSHOT_VERSION_CONFLICT", "Operational snapshot version is stale", status_code=409,
                              details={"current_snapshot_version": case.operational_snapshot.snapshot_version})

    @staticmethod
    def _action_scope(plan: RecoveryPlanVersion) -> list[str]:
        return sorted({action.type for action in plan.actions})

    @staticmethod
    def _new_approval_record(
        *, actor: ActorContext, case: RecoveryCase, plan: RecoveryPlanVersion,
        decision: ApprovalDecisionState, reason: str, evidence_refs: list[str],
        approved_cost_limit: Decimal | None = None, expires_at: datetime | None = None,
        action_scope: list[str] | None = None, idempotency_key: str | None = None,
    ) -> ApprovalDecision:
        now = _now()
        approval_id = f"appr_{uuid4().hex[:16]}"
        return ApprovalDecision(
            approval_id=approval_id,
            tenant_id=actor.tenant_id,
            recovery_case_id=case.case_id,
            commitment_id=plan.commitment_id,
            commitment_version=plan.evaluation.commitment_version,
            plan_id=plan.plan_id,
            plan_version=plan.plan_version,
            snapshot_version=plan.snapshot_version,
            action_scope=action_scope or RecoveryPlanner._action_scope(plan),
            actor_id=actor.actor_id,
            actor_role=actor.actor_role,
            decision=decision,
            approved_cost_limit=approved_cost_limit,
            reason=reason,
            decided_at=now,
            approved_at=now if decision == ApprovalDecisionState.APPROVED else None,
            expires_at=expires_at,
            evidence_refs=list(dict.fromkeys(evidence_refs)),
            audit_refs=[f"p3_approval_audit:{approval_id}"],
            idempotency_key=idempotency_key,
            correlation_id=actor.correlation_id,
            causation_id=actor.causation_id,
        )

    def request_approval(
        self, actor: ActorContext, plan_id: str, request: ApprovalRequestInput,
        *, current_commitment_version: int | None = None, db: Session | None = None,
        request_context: RequestContext | None = None,
    ) -> ApprovalDecision:
        self._require_approval_actor(actor)
        with self.repository._lock:
            case, plan = self._approval_target(actor, plan_id)
            for existing in case.approval_decisions:
                if existing.tenant_id == actor.tenant_id and existing.idempotency_key == request.idempotency_key:
                    same_request = (
                        existing.actor_id == actor.actor_id
                        and existing.commitment_id == plan.commitment_id
                        and existing.commitment_version == request.expected_commitment_version
                        and existing.plan_id == plan.plan_id
                        and existing.plan_version == request.expected_plan_version
                        and existing.snapshot_version == request.expected_snapshot_version
                        and existing.action_scope == sorted(set(request.action_scope))
                        and existing.approved_cost_limit == request.maximum_approved_amount
                        and existing.expires_at == request.expires_at
                        and existing.reason == request.reason
                        and existing.evidence_refs == request.evidence_refs
                    )
                    if same_request:
                        return existing
                    raise DomainError("IDEMPOTENCY_KEY_REUSED", "Idempotency key was used for a different approval request",
                                      status_code=409)
            current_version = current_commitment_version if current_commitment_version is not None else case.commitment_version
            self._assert_approval_versions(
                case, plan, expected_commitment_version=request.expected_commitment_version,
                expected_plan_version=request.expected_plan_version,
                expected_snapshot_version=request.expected_snapshot_version,
                current_commitment_version=current_version,
            )
            now = _now()
            if request.expires_at <= now:
                raise DomainError("APPROVAL_EXPIRY_INVALID", "Approval expiry must be in the future", status_code=422)
            if plan.execution_state != "NOT_STARTED" or plan.approval_state != ApprovalState.PENDING:
                raise DomainError("APPROVAL_STATE_CONFLICT", "Plan is not awaiting approval", status_code=409)
            expected_scope = self._action_scope(plan)
            if plan.currency != "MYR":
                raise DomainError("APPROVAL_CURRENCY_UNSUPPORTED", "P3 approval limits are denominated in MYR",
                                  status_code=422)
            if sorted(set(request.action_scope)) != expected_scope:
                raise DomainError("APPROVAL_SCOPE_MISMATCH", "Approval scope must exactly cover this plan's action types",
                                  status_code=422, details={"required_action_scope": expected_scope})
            if request.maximum_approved_amount < plan.estimated_extra_cost:
                raise DomainError("APPROVAL_COST_LIMIT_TOO_LOW", "Requested approval limit is below plan cost",
                                  status_code=422, details={"estimated_extra_cost": str(plan.estimated_extra_cost)})
            record = self._new_approval_record(
                actor=actor, case=case, plan=plan, decision=ApprovalDecisionState.REQUESTED,
                reason=request.reason, evidence_refs=request.evidence_refs,
                approved_cost_limit=request.maximum_approved_amount, expires_at=request.expires_at,
                action_scope=expected_scope, idempotency_key=request.idempotency_key,
            )
            case.approval_decisions.append(record)
            case.updated_at = now
            self.repository.save_case(case)
            event = self.event_coordinator.prepare(
                event_type=RecoveryEventType.APPROVAL_REQUIRED,
                tenant_id=case.tenant_id,
                commitment_id=case.commitment_id,
                commitment_version=case.commitment_version,
                recovery_case_id=case.case_id,
                plan_id=plan.plan_id,
                plan_version=plan.plan_version,
                snapshot_version=plan.snapshot_version,
                correlation_id=actor.correlation_id,
                causation_id=actor.causation_id or record.approval_id,
                evidence_refs=tuple(record.evidence_refs),
                payload=ApprovalRequiredPayload(
                    approval_id=record.approval_id,
                    action_scope=tuple(record.action_scope),
                    maximum_approved_amount_myr=record.approved_cost_limit or Decimal(0),
                    approval_expires_at=record.expires_at,
                ),
            )
            self.event_coordinator.publish(event, db=db, context=request_context)
            return record

    def _decide_approval(
        self, actor: ActorContext, plan_id: str, request: ApprovalDecisionInput,
        decision: ApprovalDecisionState, *, current_commitment_version: int | None = None,
    ) -> ApprovalDecision:
        self._require_approval_actor(actor)
        CoreIntegrationFacade().authorize(
            actor.actor_id, actor.actor_role, "APPROVE_PLAN", request.expected_plan_version
        )
        with self.repository._lock:
            case, plan = self._approval_target(actor, plan_id)
            current_version = current_commitment_version if current_commitment_version is not None else case.commitment_version
            self._assert_approval_versions(
                case, plan, expected_commitment_version=request.expected_commitment_version,
                expected_plan_version=request.expected_plan_version,
                expected_snapshot_version=request.expected_snapshot_version,
                current_commitment_version=current_version,
            )
            if plan.approval_state != ApprovalState.PENDING:
                raise DomainError("APPROVAL_STATE_CONFLICT", "Plan already has a terminal approval decision",
                                  status_code=409)
            requests = [d for d in case.approval_decisions if d.plan_id == plan_id
                        and d.plan_version == plan.plan_version and d.decision == ApprovalDecisionState.REQUESTED]
            if not requests:
                raise DomainError("APPROVAL_REQUEST_NOT_FOUND", "No active approval request exists for this plan version",
                                  status_code=409)
            approval_request = requests[-1]
            now = _now()
            if approval_request.expires_at is None or approval_request.expires_at <= now:
                if not any(d.decision == ApprovalDecisionState.EXPIRED
                           and d.idempotency_key == approval_request.idempotency_key
                           for d in case.approval_decisions):
                    expiry_record = self._new_approval_record(
                        actor=ActorContext(actor.tenant_id, "system:p3", "SYSTEM", actor.correlation_id,
                                           actor.causation_id, True),
                        case=case, plan=plan, decision=ApprovalDecisionState.EXPIRED,
                        reason="Approval request expired before a decision was recorded",
                        evidence_refs=approval_request.evidence_refs,
                        approved_cost_limit=approval_request.approved_cost_limit,
                        expires_at=approval_request.expires_at,
                        action_scope=approval_request.action_scope,
                        idempotency_key=approval_request.idempotency_key,
                    )
                    case.approval_decisions.append(expiry_record)
                    case.updated_at = now
                    self.repository.save_case(case)
                raise DomainError("APPROVAL_EXPIRED", "Approval request has expired", status_code=409)
            if decision == ApprovalDecisionState.APPROVED:
                if plan.evaluation.validation_source != ValidationSource.REAL_P2_VALIDATED:
                    raise DomainError("AUTHORITATIVE_VALIDATION_REQUIRED",
                                      "Synthetic feasibility results cannot authorize a consequential plan", status_code=409)
                if approval_request.approved_cost_limit is None or approval_request.approved_cost_limit < plan.estimated_extra_cost:
                    raise DomainError("APPROVAL_COST_LIMIT_EXCEEDED", "Plan cost exceeds the requested approval limit",
                                      status_code=409)
                if approval_request.action_scope != self._action_scope(plan):
                    raise DomainError("APPROVAL_SCOPE_MISMATCH", "Approval request no longer covers the current action scope",
                                      status_code=409)
            record = self._new_approval_record(
                actor=actor, case=case, plan=plan, decision=decision,
                reason=request.reason, evidence_refs=request.evidence_refs,
                approved_cost_limit=approval_request.approved_cost_limit,
                expires_at=approval_request.expires_at,
                action_scope=approval_request.action_scope,
                idempotency_key=approval_request.idempotency_key,
            )
            case.approval_decisions.append(record)
            if decision == ApprovalDecisionState.APPROVED:
                plan.approval_state = ApprovalState.APPROVED
                # Approval is not execution; preserve NOT_STARTED.
            elif decision == ApprovalDecisionState.REJECTED:
                plan.approval_state = ApprovalState.REJECTED
            else:
                plan.approval_state = ApprovalState.INVALIDATED
                case.status = RecoveryCaseStatus.NEEDS_REPLAN
            case.updated_at = now
            self.repository.save_case(case)
            return record

    def approve_plan(self, actor: ActorContext, plan_id: str, request: ApprovalDecisionInput,
                     *, current_commitment_version: int | None = None) -> ApprovalDecision:
        return self._decide_approval(actor, plan_id, request, ApprovalDecisionState.APPROVED,
                                     current_commitment_version=current_commitment_version)

    def reject_plan(self, actor: ActorContext, plan_id: str, request: ApprovalDecisionInput,
                    *, current_commitment_version: int | None = None) -> ApprovalDecision:
        return self._decide_approval(actor, plan_id, request, ApprovalDecisionState.REJECTED,
                                     current_commitment_version=current_commitment_version)

    def request_plan_revision(self, actor: ActorContext, plan_id: str, request: ApprovalDecisionInput,
                              *, current_commitment_version: int | None = None) -> ApprovalDecision:
        return self._decide_approval(actor, plan_id, request, ApprovalDecisionState.REVISION_REQUESTED,
                                     current_commitment_version=current_commitment_version)

    def invalidate_for_customer_response(
        self, *, tenant_id: str, commitment_id: str, plan_id: str, plan_version: int,
        commitment_version: int,
        correlation_id: str, causation_id: str, evidence_refs: list[str], reason: str,
    ) -> None:
        """Invalidate only P3 recovery state; never transition the P5 Commitment."""
        with self.repository._lock:
            case = self.repository.get_case(tenant_id, commitment_id)
            if case is None:
                raise DomainError("RECOVERY_CASE_NOT_FOUND", "Recovery case was not found", status_code=404)
            plan = next((item for item in case.plans if item.plan_id == plan_id), None)
            if plan is None:
                raise DomainError("RECOVERY_PLAN_NOT_FOUND", "Recovery plan was not found", status_code=404)
            if plan.plan_version != plan_version:
                raise DomainError("RECOVERY_PLAN_VERSION_CONFLICT", "Customer response refers to a stale plan", status_code=409)
            if case.commitment_version != commitment_version or plan.evaluation.commitment_version != commitment_version:
                raise DomainError("COMMITMENT_VERSION_CONFLICT", "Customer response refers to a stale commitment version", status_code=409)
            if plan.approval_state == ApprovalState.INVALIDATED and plan.execution_state == "NEEDS_REPLAN":
                return
            plan.approval_state = ApprovalState.INVALIDATED
            plan.execution_state = "NEEDS_REPLAN"
            case.status = RecoveryCaseStatus.NEEDS_REPLAN
            latest = next((item for item in reversed(case.approval_decisions)
                           if item.plan_id == plan_id and item.plan_version == plan_version
                           and item.decision == ApprovalDecisionState.APPROVED), None)
            if latest is not None:
                system_actor = ActorContext(tenant_id, "system:p3", "SYSTEM", correlation_id, causation_id, True)
                case.approval_decisions.append(self._new_approval_record(
                    actor=system_actor, case=case, plan=plan,
                    decision=ApprovalDecisionState.INVALIDATED, reason=reason,
                    evidence_refs=evidence_refs, approved_cost_limit=latest.approved_cost_limit,
                    expires_at=latest.expires_at, action_scope=latest.action_scope,
                    idempotency_key=f"customer-response:{causation_id}",
                ))
            case.updated_at = _now()
            self.repository.save_case(case)
            event = self.event_coordinator.prepare(
                event_type=RecoveryEventType.REPLAN_REQUIRED,
                tenant_id=tenant_id, commitment_id=commitment_id,
                commitment_version=case.commitment_version, recovery_case_id=case.case_id,
                plan_id=plan_id, plan_version=plan_version, snapshot_version=plan.snapshot_version,
                correlation_id=correlation_id, causation_id=causation_id,
                evidence_refs=tuple(evidence_refs),
                payload=ReplanRequiredPayload(
                    reason_code="CUSTOMER_RESPONSE_REQUIRES_REPLAN",
                    source_event_id=causation_id, invalidated_plan_ids=(plan_id,),
                ),
            )
            self.event_coordinator.publish(event)

    def get_active_approval(
        self, actor: ActorContext, plan_id: str, request: ApprovalDecisionInput,
        *, current_commitment_version: int | None = None, allow_test_double: bool = False,
    ) -> ApprovalDecision:
        """Validate approval freshness/scope for a future executor; performs no action."""
        self._require_approval_actor(actor)
        with self.repository._lock:
            case, plan = self._approval_target(actor, plan_id)
            current_version = current_commitment_version if current_commitment_version is not None else case.commitment_version
            self._assert_approval_versions(
                case, plan, expected_commitment_version=request.expected_commitment_version,
                expected_plan_version=request.expected_plan_version,
                expected_snapshot_version=request.expected_snapshot_version,
                current_commitment_version=current_version,
            )
            decisions = [d for d in case.approval_decisions if d.plan_id == plan_id
                         and d.plan_version == plan.plan_version]
            latest_decision = decisions[-1] if decisions else None
            if (latest_decision is None
                    or latest_decision.decision != ApprovalDecisionState.APPROVED
                    or plan.approval_state != ApprovalState.APPROVED):
                raise DomainError("APPROVAL_NOT_ACTIVE", "No active approval exists for this plan version", status_code=409)
            approval = latest_decision
            now = _now()
            if approval.expires_at is None or approval.expires_at <= now:
                expired = self._new_approval_record(
                    actor=ActorContext(actor.tenant_id, "system:p3", "SYSTEM", actor.correlation_id,
                                       actor.causation_id, True),
                    case=case, plan=plan, decision=ApprovalDecisionState.EXPIRED,
                    reason="Approval expired before use", evidence_refs=approval.evidence_refs,
                    approved_cost_limit=approval.approved_cost_limit, expires_at=approval.expires_at,
                    action_scope=approval.action_scope, idempotency_key=approval.idempotency_key,
                )
                case.approval_decisions.append(expired)
                plan.approval_state = ApprovalState.EXPIRED
                case.updated_at = now
                self.repository.save_case(case)
                raise DomainError("APPROVAL_EXPIRED", "Approval has expired", status_code=409)
            if (plan.evaluation.validation_source != ValidationSource.REAL_P2_VALIDATED
                    and not (allow_test_double
                             and plan.evaluation.validation_source == ValidationSource.TEST_DOUBLE_VALIDATED)):
                raise DomainError("AUTHORITATIVE_VALIDATION_REQUIRED",
                                  "Synthetic feasibility results cannot authorize a consequential plan", status_code=409)
            if approval.action_scope != self._action_scope(plan):
                raise DomainError("APPROVAL_SCOPE_MISMATCH", "Approved action scope does not match the current plan",
                                  status_code=409)
            if approval.approved_cost_limit is None or approval.approved_cost_limit < plan.estimated_extra_cost:
                raise DomainError("APPROVAL_COST_LIMIT_EXCEEDED", "Current plan cost exceeds the approved amount",
                                  status_code=409)
            return approval


default_recovery_planner = RecoveryPlanner()
