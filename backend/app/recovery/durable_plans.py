"""Persist P3 plan alternatives against exact P2 source and Core risk evidence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, ForeignKeyConstraint, Integer, JSON, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.schemas import ApprovalState, FeasibilityState, ExecutionState
from app.core.service import CommitmentService
from app.db.base import Base
from app.feasibility.persisted_sources import read_snapshot
from app.feasibility.production import ProposedChanges
from app.feasibility.service import evaluate

from .models import (
    BusinessPreferences, PlanEvaluation, RecoveryCaseStatus, RecoveryPlanVersion,
    RecoveryStrategy, RiskLevel, SolverReadiness, ValidationSource,
)
from .persistence import RecoveryCaseRecord, SqlAlchemyRecoveryRepository
from .ranking import RankingCandidate, rank_candidates
from .trigger_persistence import PersistedCoreAssessmentLookup


class RecoveryPlanRecord(Base):
    __tablename__ = "recovery_plan_versions"

    tenant_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    plan_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    plan_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(String(128), nullable=False)
    commitment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    assessment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    snapshot_id: Mapped[str] = mapped_column(String(128), nullable=False)
    snapshot_version: Mapped[int] = mapped_column(Integer, nullable=False)
    core_commitment_version: Mapped[int] = mapped_column(Integer, nullable=False)
    evaluated_commitment_version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "case_id", "commitment_id"],
            ["recovery_cases.tenant_id", "recovery_cases.case_id", "recovery_cases.commitment_id"],
            ondelete="RESTRICT", name="fk_recovery_plan_case",
        ),
    )


def _status_readiness(status: FeasibilityState) -> SolverReadiness:
    return {
        FeasibilityState.FEASIBLE: SolverReadiness.VALIDATED,
        FeasibilityState.CONDITIONAL: SolverReadiness.CONDITIONAL,
        FeasibilityState.INFEASIBLE: SolverReadiness.INFEASIBLE,
        FeasibilityState.UNKNOWN: SolverReadiness.UNKNOWN,
        FeasibilityState.NOT_ASSESSED: SolverReadiness.PENDING_EVALUATION,
    }[status]


class DurablePlanService:
    def __init__(self) -> None:
        self.cases = SqlAlchemyRecoveryRepository()
        self.core = CommitmentService()
        self.proof = PersistedCoreAssessmentLookup()

    def _current(self, db: Session, context: RequestContext, commitment_id: str):
        commitment = self.core.get(db, context, commitment_id)
        case = self.cases.get_active_case(db, context.tenant_id, commitment_id, for_update=True)
        if case is None:
            raise DomainError("RECOVERY_CASE_NOT_FOUND", "Recovery case was not found", status_code=404)
        if case.commitment_version != commitment.commitment_version or not case.trigger_events:
            raise DomainError("RECOVERY_CASE_VERSION_CONFLICT", "Recovery trigger is stale", status_code=409)
        trigger = case.trigger_events[-1]
        if trigger.assessment_provenance_status != "VERIFIED_AUTHORITATIVE":
            raise DomainError("ASSESSMENT_PROVENANCE_MISSING", "Verified risk assessment is required", status_code=409)
        proof = self.proof.lookup(
            db, context.tenant_id, commitment_id, trigger.assessment_id, trigger.event_id,
        )
        if proof is None or proof.snapshot_id != trigger.snapshot_id:
            raise DomainError("ASSESSMENT_PROVENANCE_MISSING", "Risk assessment lookup failed", status_code=409)
        snapshot = read_snapshot(db, context.tenant_id)
        if (snapshot.operational.snapshot_id, snapshot.operational.snapshot_version) != (
            trigger.snapshot_id, trigger.snapshot_version,
        ):
            raise DomainError("SNAPSHOT_DRIFT_CONFLICT", "Operational snapshot advanced", status_code=409)
        if proof.assessment.commitment_version != trigger.assessment_commitment_version:
            raise DomainError("ASSESSMENT_PROVENANCE_MISSING", "Evaluated version changed", status_code=409)
        return case, commitment, snapshot, proof.assessment

    def list(self, db: Session, context: RequestContext, commitment_id: str) -> list[RecoveryPlanVersion]:
        case = self.cases.get_active_case(db, context.tenant_id, commitment_id)
        if case is None:
            raise DomainError("RECOVERY_CASE_NOT_FOUND", "Recovery case was not found", status_code=404)
        rows = db.scalars(select(RecoveryPlanRecord).where(
            RecoveryPlanRecord.tenant_id == context.tenant_id,
            RecoveryPlanRecord.case_id == case.case_id,
        ).order_by(RecoveryPlanRecord.plan_id, RecoveryPlanRecord.plan_version.desc())).all()
        latest: dict[str, RecoveryPlanVersion] = {}
        for row in rows:
            latest.setdefault(row.plan_id, RecoveryPlanVersion.model_validate(row.payload))
        return list(latest.values())

    def get_plan(self, db: Session, context: RequestContext, plan_id: str) -> RecoveryPlanVersion:
        row = db.scalar(select(RecoveryPlanRecord).where(
            RecoveryPlanRecord.tenant_id == context.tenant_id,
            RecoveryPlanRecord.plan_id == plan_id,
        ).order_by(RecoveryPlanRecord.plan_version.desc()).limit(1))
        if row is None:
            raise DomainError("RECOVERY_PLAN_NOT_FOUND", "Recovery plan was not found", status_code=404)
        return RecoveryPlanVersion.model_validate(row.payload)

    def generate(
        self, db: Session, context: RequestContext, commitment_id: str,
        *, expected_commitment_version: int, assessment_id: str | None,
        preferences: BusinessPreferences | None = None,
    ) -> list[RecoveryPlanVersion]:
        case, commitment, snapshot, assessment = self._current(db, context, commitment_id)
        if commitment.commitment_version != expected_commitment_version:
            raise DomainError("COMMITMENT_VERSION_CONFLICT", "Commitment version is stale", status_code=409)
        if assessment_id is not None and assessment.assessment_id != assessment_id:
            raise DomainError("ASSESSMENT_NOT_FOUND", "Assessment identity does not match", status_code=404)
        if (commitment.agreement_state.value, commitment.risk_state.value,
            commitment.feasibility_state.value) != ("CONFIRMED", "AT_RISK", "INFEASIBLE"):
            raise DomainError("RECOVERY_COMMITMENT_NOT_ELIGIBLE", "Commitment is not at risk", status_code=409)
        source = next((row for row in snapshot.operational.confirmed_commitments
                       if row.commitment_id == commitment_id), None)
        if source is None or source.commitment_version != assessment.commitment_version:
            raise DomainError("P2_COMMITMENT_BINDING_MISMATCH", "Evaluated source version is missing", status_code=409)
        if len(source.lines) != 1 or (
            source.lines[0].sku_id, source.lines[0].quantity, source.lines[0].unit,
            source.delivery_deadline,
        ) != (
            commitment.terms.sku, commitment.terms.quantity, commitment.terms.unit,
            commitment.terms.deadline,
        ):
            raise DomainError("P2_COMMITMENT_BINDING_MISMATCH", "Core terms differ from source", status_code=409)
        evaluated_commitment = commitment.model_copy(update={
            "commitment_version": assessment.commitment_version,
        })
        policy = preferences or BusinessPreferences()
        existing = self.list(db, context, commitment_id)
        if existing:
            if all(row.snapshot_version == snapshot.operational.snapshot_version
                   and row.based_on_assessment_id == assessment.assessment_id
                   and row.evaluation.commitment_version == assessment.commitment_version
                   for row in existing):
                return existing
            raise DomainError("RECOVERY_PLAN_SUPERSESSION_REQUIRED", "Existing plans need explicit invalidation", status_code=409)

        # Alternative supply is only a review candidate: P2 has no verified
        # substitution input, so evaluating the unchanged source cannot invent it.
        deadline = commitment.terms.deadline + timedelta(days=1)
        partial = max(Decimal("1"), commitment.terms.quantity / Decimal("2"))
        proposals = (
            ("alternative_supply", RecoveryStrategy.ALTERNATIVE_SUPPLY, None,
             Decimal("80.00"), 0, False, Decimal(5)),
            ("revised_schedule", RecoveryStrategy.RESCHEDULE_PARTIAL_FULFILMENT,
             ProposedChanges(
                 tenant_id=context.tenant_id, commitment_id=commitment_id,
                 expected_commitment_version=assessment.commitment_version,
                 expected_snapshot_version=snapshot.operational.snapshot_version,
                 quantity=partial, deadline=deadline,
                 evidence_refs=(f"assessment:{assessment.assessment_id}",),
             ), Decimal("0.00"), 1440, True, Decimal(0)),
        )
        now = datetime.now(timezone.utc)
        candidates = []
        for name, strategy, proposal, cost, delay, confirmation, uncertainty in proposals:
            result = evaluate(snapshot, proposal, evaluated_commitment)
            if name == "alternative_supply" and result.status == FeasibilityState.FEASIBLE:
                raise DomainError("SUPPLIER_AVAILABILITY_UNVERIFIED", "Alternative supply has no verified source", status_code=409)
            candidates.append((name, strategy, result, proposal, cost, delay, confirmation, uncertainty))
        ranking = rank_candidates([
            RankingCandidate(
                plan_id=f"{case.case_id}_{name}", feasibility_status=result.status,
                validation_source=ValidationSource.REAL_P2_VALIDATED,
                additional_cost_myr=cost, delivery_delay_minutes=delay,
                affected_commitment_ids=tuple(assessment.affected_commitment_ids),
                operational_disruption_level=Decimal(2), supplier_uncertainty_level=uncertainty,
                customer_confirmation_required=confirmation,
                hard_constraint_reasons=tuple(f"{item.code}:{item.resource_id}" for item in result.constraints
                                              if item.severity == "HARD"),
            ) for name, _, result, _, cost, delay, confirmation, uncertainty in candidates
        ], policy)
        plans = []
        for name, strategy, result, proposal, cost, delay, confirmation, uncertainty in candidates:
            plan_id = f"{case.case_id}_{name}"
            decision = ranking[plan_id]
            action_type = "CREATE_INTERNAL_REVIEW_TASK"
            action_params = {"strategy": strategy.value, "proposal": proposal.model_dump(mode="json") if proposal else None}
            constraints = [f"{item.code}:{item.resource_id}" for item in result.constraints]
            if name == "alternative_supply":
                constraints.append("SUPPLIER_AVAILABILITY_UNVERIFIED")
            if confirmation:
                constraints.append("CUSTOMER_ACCEPTANCE_REQUIRED_FOR_TERMS_CHANGE")
            evaluation = PlanEvaluation(
                evaluation_id=f"eval_{plan_id}_v1", tenant_id=context.tenant_id,
                commitment_id=commitment_id, plan_id=plan_id, plan_version=1,
                commitment_version=assessment.commitment_version,
                snapshot_version=snapshot.operational.snapshot_version,
                feasibility_status=result.status, validation_source=ValidationSource.REAL_P2_VALIDATED,
                readiness=_status_readiness(result.status), solver_status=result.solver_status.value,
                constraints=constraints,
                hard_constraint_reasons=list(decision.exclusion_reasons),
                affected_commitment_ids=list(assessment.affected_commitment_ids),
                evidence_refs=list(dict.fromkeys([*assessment.evidence_refs, *result.evidence_refs])),
                assumptions=[*result.assumptions, "Internal task does not change accepted customer terms"],
                evaluated_at=now,
            )
            plan = RecoveryPlanVersion(
                tenant_id=context.tenant_id, recovery_case_id=case.case_id,
                plan_id=plan_id, plan_version=1, commitment_id=commitment_id,
                based_on_assessment_id=assessment.assessment_id,
                snapshot_version=snapshot.operational.snapshot_version,
                feasibility_status=result.status, estimated_extra_cost=cost, currency="MYR",
                estimated_delay_minutes=delay, risks=constraints,
                actions=[{
                    "action_id": f"{plan_id}_task", "type": action_type,
                    "requires_approval": True, "idempotency_key": f"{plan_id}_v1_task",
                    "parameters": action_params,
                    "preconditions": ["Current Core and P2 versions", "Durable Manager Approval"],
                }],
                approval_state=ApprovalState.PENDING, execution_state=ExecutionState.NOT_STARTED,
                option_id=name, strategy=strategy,
                risk_level=RiskLevel.HIGH if uncertainty else RiskLevel.MEDIUM,
                customer_impact="REVIEW_REQUIRED", affected_commitment_count=len(assessment.affected_commitment_ids),
                operational_disruption_level=Decimal(2), supplier_uncertainty_level=uncertainty,
                customer_confirmation_required=confirmation, constraints=constraints,
                evidence_refs=evaluation.evidence_refs, assumptions=evaluation.assumptions,
                ranking_score=decision.score_breakdown.total_score if decision.score_breakdown else None,
                score_breakdown=decision.score_breakdown, rank=decision.rank,
                ranking_exclusion_reasons=list(decision.exclusion_reasons),
                recommended=decision.recommended,
                recommendation_label=decision.recommendation_label,
                recommendation_qualification=decision.recommendation_qualification,
                recommendation_reason=decision.recommendation_reason, evaluation=evaluation,
            )
            db.add(RecoveryPlanRecord(
                tenant_id=context.tenant_id, plan_id=plan_id, plan_version=1,
                case_id=case.case_id, commitment_id=commitment_id,
                assessment_id=assessment.assessment_id, snapshot_id=snapshot.operational.snapshot_id,
                snapshot_version=snapshot.operational.snapshot_version,
                core_commitment_version=commitment.commitment_version,
                evaluated_commitment_version=assessment.commitment_version,
                payload=plan.model_dump(mode="json"), status="PENDING_APPROVAL", created_at=now,
            ))
            plans.append(plan)
        row = db.get(RecoveryCaseRecord, (context.tenant_id, case.case_id))
        case.trigger_assessment = assessment
        case.operational_snapshot = {
            "snapshot_id": snapshot.operational.snapshot_id,
            "snapshot_version": snapshot.operational.snapshot_version,
            "captured_at": snapshot.operational.captured_at,
            "source": "P2_PERSISTED_OPERATIONAL_SOURCE",
            "evidence_refs": list(assessment.evidence_refs),
        }
        case.plans = plans
        case.preferences = policy
        case.status = RecoveryCaseStatus.OPTIONS_READY if any(item.rank for item in plans) else RecoveryCaseStatus.NO_SAFE_PLAN
        case.case_version += 1
        case.updated_at = now
        # Revalidate the aggregate before persisting its JSON projection.
        case = type(case).model_validate(case.model_dump(mode="json"))
        self.cases._copy_case_columns(row, case)
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
        return plans
