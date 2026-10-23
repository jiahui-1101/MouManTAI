"""Persist P3 plan alternatives against exact P2 source and Core risk evidence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.events import CoreEventType
from app.core.models import AuditEventRecord, CommitmentProposalRecord, OutboxEventRecord
from app.core.schemas import (
    AgreementState,
    ApprovalState,
    CommitmentTerms,
    DomainEvent,
    ExecutionState,
    FeasibilityState,
)
from app.core.service import CommitmentService
from app.db.base import Base
from app.feasibility.persisted_sources import read_snapshot
from app.feasibility.production import ProposedChanges
from app.feasibility.service import evaluate

from .models import (
    BusinessPreferences,
    PlanEvaluation,
    RecoveryCaseStatus,
    RecoveryPlanVersion,
    RecoveryStrategy,
    RiskLevel,
    SolverReadiness,
    ValidationSource,
)
from .persistence import RecoveryCaseRecord, SqlAlchemyRecoveryRepository
from .proposal_identity import proposal_id_for_plan
from .ranking import RankingCandidate, rank_candidates
from .trigger_persistence import PersistedCoreAssessmentLookup

if TYPE_CHECKING:
    from app.core.manager_approval import ManagerApprovalRecord


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
        CheckConstraint(
            "core_commitment_version > evaluated_commitment_version",
            name="ck_recovery_plan_core_after_evaluation",
        ),
        Index("ix_recovery_plan_case", "tenant_id", "case_id"),
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

    @staticmethod
    def require_authorized_offer_transition(
        db: Session,
        *,
        tenant_id: str,
        commitment,
        case_record: RecoveryCaseRecord,
        prior_plan_record: RecoveryPlanRecord,
        prior_plan: RecoveryPlanVersion,
        proposal: CommitmentProposalRecord,
        approval: ManagerApprovalRecord,
        response_event: DomainEvent,
    ) -> None:
        """Prove this exact approved P3 offer caused the current Core version.

        A version increment by itself is never accepted as provenance. The
        proposal row, durable approval, Core proposal-offered outbox event and
        its immutable before/after audit record must all agree.
        """
        def reject() -> None:
            raise DomainError(
                "CORE_OFFER_PROVENANCE_INVALID",
                "The current Core proposal is not proven to be this approved Recovery plan's offer",
                status_code=409,
            )

        def value(raw):
            return raw.value if hasattr(raw, "value") else raw

        def aware(raw: datetime) -> datetime:
            return raw if raw.tzinfo is not None else raw.replace(tzinfo=UTC)

        try:
            expected_proposal_id, expected_proposal_version = proposal_id_for_plan(
                prior_plan.plan_id, prior_plan.plan_version,
            ), prior_plan.plan_version
            approved_terms = CommitmentTerms.model_validate(approval.approved_terms).model_dump(mode="json")
            offered_terms = CommitmentTerms.model_validate(proposal.revised_terms).model_dump(mode="json")
        except Exception as exc:
            raise DomainError(
                "CORE_OFFER_PROVENANCE_INVALID",
                "Persisted Core offer or approval terms are malformed",
                status_code=409,
            ) from exc

        original_version = prior_plan.core_commitment_version
        current_version = commitment.commitment_version
        evaluated_version = prior_plan_record.evaluated_commitment_version
        expected_refs = [approval.audit_id, prior_plan_record.assessment_id, prior_plan_record.snapshot_id]
        if (
            not tenant_id
            or (commitment.tenant_id, commitment.commitment_id, current_version)
            != (tenant_id, prior_plan.commitment_id, response_event.commitment_version)
            or value(commitment.agreement_state) != AgreementState.OFFERED.value
            or (case_record.tenant_id, case_record.case_id, case_record.commitment_id)
            != (tenant_id, prior_plan.recovery_case_id, prior_plan.commitment_id)
            or (prior_plan_record.tenant_id, prior_plan_record.plan_id, prior_plan_record.plan_version,
                prior_plan_record.case_id, prior_plan_record.commitment_id,
                prior_plan_record.core_commitment_version, evaluated_version)
            != (tenant_id, prior_plan.plan_id, prior_plan.plan_version,
                prior_plan.recovery_case_id, prior_plan.commitment_id, original_version,
                prior_plan.evaluation.commitment_version)
            or (proposal.tenant_id, proposal.commitment_id, proposal.proposal_id,
                proposal.proposal_version, proposal.status)
            != (tenant_id, prior_plan.commitment_id, expected_proposal_id,
                expected_proposal_version, "ACTIVE")
            or proposal.revised_terms is None
            or offered_terms != approved_terms
            or list(proposal.evidence_refs or []) != expected_refs
            or (approval.tenant_id, approval.commitment_id, approval.case_id,
                approval.plan_id, approval.plan_version, approval.proposal_id,
                approval.proposal_version, approval.commitment_version, approval.decision)
            != (tenant_id, prior_plan.commitment_id, prior_plan.recovery_case_id,
                prior_plan.plan_id, prior_plan.plan_version, expected_proposal_id,
                expected_proposal_version, original_version, "APPROVED")
            or approval.actor_role not in {"MANAGER", "OWNER"}
            or "CREATE_DELIVERY_CHANGE_PROPOSAL" not in approval.action_scope
            or approval.approved_terms != offered_terms
            or not original_version
            or original_version <= evaluated_version
            or current_version != original_version + 1
        ):
            reject()

        approval_audit = db.get(AuditEventRecord, approval.audit_id)
        if (
            approval_audit is None
            or (approval_audit.tenant_id, approval_audit.commitment_id,
                approval_audit.event_type, approval_audit.actor_id, approval_audit.actor_role)
            != (tenant_id, prior_plan.commitment_id, "recovery.plan_approved",
                approval.actor_id, approval.actor_role)
            or not isinstance(approval_audit.new_state, dict)
            or approval_audit.new_state.get("approval_id") != approval.approval_id
            or approval_audit.new_state.get("decision") != "APPROVED"
            or approval_audit.new_state.get("plan_id") != prior_plan.plan_id
            or approval_audit.new_state.get("plan_version") != prior_plan.plan_version
            or approval_audit.new_state.get("commitment_version") != original_version
        ):
            reject()

        offer_events = db.scalars(select(OutboxEventRecord).where(
            OutboxEventRecord.tenant_id == tenant_id,
            OutboxEventRecord.commitment_id == prior_plan.commitment_id,
            OutboxEventRecord.event_type == CoreEventType.COMMITMENT_PROPOSAL_OFFERED.value,
            OutboxEventRecord.commitment_version == current_version,
            OutboxEventRecord.causation_id == approval.approval_id,
        ).order_by(OutboxEventRecord.occurred_at, OutboxEventRecord.event_id)).all()
        if len(offer_events) != 1:
            reject()
        offer = offer_events[0]
        payload = offer.payload
        if not isinstance(payload, dict):
            reject()
        audit_id = payload.get("audit_id")
        if not isinstance(audit_id, str) or not audit_id:
            reject()
        expected_offer_payload = {
            "commitment_id": prior_plan.commitment_id,
            "proposal_id": expected_proposal_id,
            "proposal_version": expected_proposal_version,
            "audit_id": audit_id,
            "evidence_refs": expected_refs,
        }
        offer_audit = db.get(AuditEventRecord, audit_id)
        if (
            payload != expected_offer_payload
            or offer.causation_id != approval.approval_id
            or offer.commitment_version != current_version
            or aware(offer.occurred_at) > aware(response_event.occurred_at)
            or offer_audit is None
            or (offer_audit.tenant_id, offer_audit.commitment_id, offer_audit.event_type,
                offer_audit.dimension, offer_audit.causation_id, offer_audit.correlation_id)
            != (tenant_id, prior_plan.commitment_id, CoreEventType.COMMITMENT_PROPOSAL_OFFERED.value,
                "agreement", approval.approval_id, offer.correlation_id)
            or offer_audit.evidence_refs != expected_refs
            or aware(offer_audit.occurred_at) != aware(offer.occurred_at)
        ):
            reject()

        state_fields = {
            "agreement_state", "feasibility_state", "risk_state", "recovery_state",
            "fulfilment_state", "commitment_version",
        }
        expected_after = {
            "agreement_state": AgreementState.OFFERED.value,
            "feasibility_state": value(commitment.feasibility_state),
            "risk_state": value(commitment.risk_state),
            "recovery_state": value(commitment.recovery_state),
            "fulfilment_state": value(commitment.fulfilment_state),
            "commitment_version": current_version,
        }
        expected_before = {
            **expected_after,
            "agreement_state": AgreementState.CONFIRMED.value,
            "commitment_version": original_version,
        }
        if (
            not isinstance(offer_audit.previous_state, dict)
            or not isinstance(offer_audit.new_state, dict)
            or set(offer_audit.previous_state) != state_fields
            or set(offer_audit.new_state) != state_fields
            or offer_audit.previous_state != expected_before
            or offer_audit.new_state != expected_after
        ):
            reject()

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
            plan = RecoveryPlanVersion.model_validate(row.payload)
            if row.status in {"NEEDS_REPLAN", "SUPERSEDED"}:
                plan = plan.model_copy(update={
                    "approval_state": ApprovalState.INVALIDATED,
                    "execution_state": ExecutionState.NEEDS_REPLAN,
                    "recommended": False,
                })
            latest.setdefault(row.plan_id, plan)
        return list(latest.values())

    def get_plan(self, db: Session, context: RequestContext, plan_id: str) -> RecoveryPlanVersion:
        row = db.scalar(select(RecoveryPlanRecord).where(
            RecoveryPlanRecord.tenant_id == context.tenant_id,
            RecoveryPlanRecord.plan_id == plan_id,
        ).order_by(RecoveryPlanRecord.plan_version.desc()).limit(1))
        if row is None:
            raise DomainError("RECOVERY_PLAN_NOT_FOUND", "Recovery plan was not found", status_code=404)
        plan = RecoveryPlanVersion.model_validate(row.payload)
        if row.status in {"NEEDS_REPLAN", "SUPERSEDED"}:
            plan = plan.model_copy(update={
                "approval_state": ApprovalState.INVALIDATED,
                "execution_state": ExecutionState.NEEDS_REPLAN,
                "recommended": False,
            })
        return plan

    def apply_counteroffer(
        self,
        db: Session,
        *,
        tenant_id: str,
        commitment,
        case_record: RecoveryCaseRecord,
        case,
        prior_plan_record: RecoveryPlanRecord,
        prior_plan: RecoveryPlanVersion,
        proposal,
        approval: ManagerApprovalRecord,
        counteroffer: dict[str, str],
        response_event,
    ):
        """Persist a P2-checked successor plan without accepting the offer in Core."""
        from app.feasibility.persisted_sources import read_snapshot
        from app.feasibility.production import ProposedChanges
        from app.feasibility.service import evaluate

        now = response_event.occurred_at
        if proposal.revised_terms is None:
            raise DomainError("P4_PROPOSAL_TERMS_MISSING", "Linked proposal terms are unavailable", status_code=409)
        self.require_authorized_offer_transition(
            db,
            tenant_id=tenant_id,
            commitment=commitment,
            case_record=case_record,
            prior_plan_record=prior_plan_record,
            prior_plan=prior_plan,
            proposal=proposal,
            approval=approval,
            response_event=response_event,
        )
        original_terms = CommitmentTerms.model_validate(proposal.revised_terms)
        revised_data = original_terms.model_dump(mode="json")
        if "quantity" in counteroffer:
            revised_data["quantity"] = counteroffer["quantity"]
        if "deadline" in counteroffer:
            revised_data["deadline"] = counteroffer["deadline"]
        if "special_instructions" in counteroffer:
            revised_data["special_instructions"] = counteroffer["special_instructions"]
        revised_terms = CommitmentTerms.model_validate(revised_data)

        if revised_terms.special_instructions != commitment.terms.special_instructions:
            # P2's current canonical candidate contract cannot evaluate instruction
            # semantics. Preserve the exact P4 response and force a manual replan.
            prior_plan_record.status = "NEEDS_REPLAN"
            case.status = RecoveryCaseStatus.NEEDS_REPLAN
            case.plans = [
                item.model_copy(update={
                    "approval_state": ApprovalState.INVALIDATED,
                    "execution_state": ExecutionState.NEEDS_REPLAN,
                    "recommended": False,
                }) if item.plan_id == prior_plan.plan_id and item.plan_version == prior_plan.plan_version else item
                for item in case.plans
            ]
            return prior_plan_record, case, prior_plan, "REPLAN_REQUIRED"

        snapshot = read_snapshot(db, tenant_id)
        if (snapshot.operational.snapshot_id, snapshot.operational.snapshot_version) != (
            prior_plan.snapshot_id, prior_plan.snapshot_version,
        ):
            raise DomainError("SNAPSHOT_DRIFT_CONFLICT", "Counteroffer source snapshot advanced", status_code=409)
        if commitment.commitment_version != response_event.commitment_version:
            raise DomainError("COMMITMENT_VERSION_CONFLICT", "Counteroffer response does not match current Core", status_code=409)
        source = next((row for row in snapshot.operational.confirmed_commitments
                       if row.commitment_id == commitment.commitment_id), None)
        if source is None or source.commitment_version != prior_plan.evaluation.commitment_version:
            raise DomainError("P2_COMMITMENT_BINDING_MISMATCH", "P2 source commitment changed", status_code=409)

        proposed = ProposedChanges(
            tenant_id=tenant_id,
            commitment_id=commitment.commitment_id,
            expected_commitment_version=source.commitment_version,
            expected_snapshot_version=snapshot.operational.snapshot_version,
            quantity=revised_terms.quantity,
            deadline=revised_terms.deadline,
            evidence_refs=tuple(dict.fromkeys([
                *prior_plan.evidence_refs,
                *response_event.payload["evidence_refs"],
                f"counteroffer:{response_event.event_id}",
            ])),
        )
        historical = commitment.model_copy(update={
            "commitment_version": source.commitment_version,
            "agreement_state": AgreementState.CONFIRMED,
        })
        result = evaluate(snapshot, proposed, historical)
        latest_version = db.scalar(select(RecoveryPlanRecord.plan_version).where(
            RecoveryPlanRecord.tenant_id == tenant_id,
            RecoveryPlanRecord.plan_id == prior_plan.plan_id,
        ).order_by(RecoveryPlanRecord.plan_version.desc()).limit(1))
        if latest_version is None:
            raise DomainError("RECOVERY_PLAN_NOT_FOUND", "Current Recovery plan version is unavailable", status_code=404)
        next_version = latest_version + 1
        next_proposal_id = proposal_id_for_plan(prior_plan.plan_id, next_version)

        constraints = [f"{item.code}:{item.resource_id}" for item in result.constraints]
        constraints.append("CUSTOMER_COUNTEROFFER_REQUIRES_FRESH_APPROVAL")
        if revised_terms.quantity != commitment.terms.quantity or revised_terms.deadline != commitment.terms.deadline:
            constraints.append("CUSTOMER_ACCEPTANCE_REQUIRED_FOR_TERMS_CHANGE")
        evaluation = prior_plan.evaluation.model_copy(update={
            "evaluation_id": f"eval_{prior_plan.plan_id}_v{next_version}",
            "plan_version": next_version,
            "feasibility_status": result.status,
            "validation_source": ValidationSource.REAL_P2_VALIDATED,
            "readiness": _status_readiness(result.status),
            "solver_status": result.solver_status.value,
            "constraints": constraints,
            "hard_constraint_reasons": [
                f"{item.code}:{item.resource_id}" for item in result.constraints
                if item.severity == "HARD"
            ],
            "affected_commitment_ids": list(prior_plan.evaluation.affected_commitment_ids),
            "evidence_refs": list(dict.fromkeys([
                *prior_plan.evaluation.evidence_refs,
                *result.evidence_refs,
                *response_event.payload["evidence_refs"],
            ])),
            "assumptions": [*result.assumptions, "Counteroffer is not accepted Core state"],
            "evaluated_at": now,
        })
        actions = [action.model_dump(mode="json") for action in prior_plan.actions]
        for action in actions:
            action["action_id"] = f"{prior_plan.plan_id}_v{next_version}_{action['type'].lower()}"
            action["idempotency_key"] = f"{prior_plan.plan_id}_v{next_version}_{action['type'].lower()}"
            if "proposal" in action["parameters"]:
                action["parameters"]["proposal"] = proposed.model_dump(mode="json")
            if action["type"] == "CREATE_DELIVERY_CHANGE_PROPOSAL":
                action["parameters"] = {
                    "partial_quantity": str(revised_terms.quantity),
                    "new_deadline": revised_terms.deadline.isoformat() if revised_terms.deadline else None,
                    "proposal": proposed.model_dump(mode="json"),
                }
                action["preconditions"] = [
                    "Current Core and P2 versions", "Fresh Durable Manager Approval",
                    "Separate customer acceptance before revised terms take effect",
                ]
        feasible_for_review = result.status in {FeasibilityState.FEASIBLE, FeasibilityState.CONDITIONAL}
        data = prior_plan.model_dump(mode="python")
        data.update({
            "plan_version": next_version,
            "proposal_id": next_proposal_id,
            "proposal_version": next_version,
            "feasibility_status": result.status,
            "actions": actions,
            "approval_state": ApprovalState.PENDING,
            "execution_state": ExecutionState.NOT_STARTED if feasible_for_review else ExecutionState.NEEDS_REPLAN,
            "constraints": constraints,
            "risks": constraints,
            "evidence_refs": evaluation.evidence_refs,
            "assumptions": evaluation.assumptions,
            "recommended": False,
            "recommendation_label": None,
            "recommendation_qualification": "P2 evaluated customer counteroffer; fresh manager approval required",
            "recommendation_reason": None,
            "rank": None,
            "ranking_score": None,
            "score_breakdown": None,
            "ranking_exclusion_reasons": [],
            "evaluation": evaluation,
        })
        new_plan = RecoveryPlanVersion.model_validate(data)
        prior_plan_record.status = "SUPERSEDED" if feasible_for_review else "NEEDS_REPLAN"
        db.add(RecoveryPlanRecord(
            tenant_id=tenant_id,
            plan_id=prior_plan.plan_id,
            plan_version=next_version,
            case_id=case_record.case_id,
            commitment_id=commitment.commitment_id,
            assessment_id=prior_plan_record.assessment_id,
            snapshot_id=snapshot.operational.snapshot_id,
            snapshot_version=snapshot.operational.snapshot_version,
            core_commitment_version=commitment.commitment_version,
            evaluated_commitment_version=source.commitment_version,
            payload=new_plan.model_dump(mode="json"),
            status="PENDING_APPROVAL" if feasible_for_review else "NEEDS_REPLAN",
            created_at=now,
        ))
        case.plans = [
            item for item in case.plans
            if not (item.plan_id == prior_plan.plan_id and item.plan_version == prior_plan.plan_version)
        ] + [new_plan]
        case.status = RecoveryCaseStatus.OPTIONS_READY if feasible_for_review else RecoveryCaseStatus.NEEDS_REPLAN
        case.commitment_version = commitment.commitment_version
        case.updated_at = now
        return prior_plan_record, case, new_plan, "REPLANNED" if feasible_for_review else "REPLAN_REQUIRED"

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
        rejected_offer_replan = (
            case.status == RecoveryCaseStatus.NEEDS_REPLAN
            and any(item.intent == "REJECT" for item in case.customer_response_events)
            and commitment.agreement_state.value == "OFFERED"
        )
        confirmed_at_risk = commitment.agreement_state.value == "CONFIRMED"
        if not (confirmed_at_risk or rejected_offer_replan) or (
            commitment.risk_state.value, commitment.feasibility_state.value
        ) != ("AT_RISK", "INFEASIBLE"):
            raise DomainError("RECOVERY_COMMITMENT_NOT_ELIGIBLE", "Commitment is not at risk", status_code=409)
        source = next((row for row in snapshot.operational.confirmed_commitments
                       if row.commitment_id == commitment_id), None)
        if source is None or source.commitment_version != assessment.commitment_version:
            raise DomainError("P2_COMMITMENT_BINDING_MISMATCH", "Evaluated source version is missing", status_code=409)
        if commitment.commitment_version <= assessment.commitment_version:
            raise DomainError(
                "P2_COMMITMENT_BINDING_MISMATCH",
                "The authoritative recovery version must advance beyond its evaluated source version",
                status_code=409,
            )
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
            "agreement_state": AgreementState.CONFIRMED,
        })
        policy = preferences or BusinessPreferences()
        existing = self.list(db, context, commitment_id)
        existing_rows = db.scalars(select(RecoveryPlanRecord).where(
            RecoveryPlanRecord.tenant_id == context.tenant_id,
            RecoveryPlanRecord.case_id == case.case_id,
        ).order_by(RecoveryPlanRecord.plan_id, RecoveryPlanRecord.plan_version.desc())).all()
        latest_rows: dict[str, RecoveryPlanRecord] = {}
        for row in existing_rows:
            latest_rows.setdefault(row.plan_id, row)
        replan_ids = {
            plan_id for plan_id, row in latest_rows.items()
            if row.status == "NEEDS_REPLAN"
        }
        if existing:
            if case.status == RecoveryCaseStatus.NEEDS_REPLAN and replan_ids:
                pass
            elif all(row.snapshot_version == snapshot.operational.snapshot_version
                   and row.based_on_assessment_id == assessment.assessment_id
                   and row.evaluation.commitment_version == assessment.commitment_version
                   for row in existing):
                return existing
            else:
                raise DomainError("RECOVERY_PLAN_SUPERSESSION_REQUIRED", "Existing plans need explicit invalidation", status_code=409)

        # Alternative supply is only a review candidate: P2 has no verified
        # substitution input, so evaluating the unchanged source cannot invent it.
        deadline = commitment.terms.deadline + timedelta(days=1)
        partial = max(Decimal(1), commitment.terms.quantity / Decimal(2))
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
        if replan_ids:
            names_to_replan = {
                name for name in ("alternative_supply", "revised_schedule")
                if f"{case.case_id}_{name}" in replan_ids
            }
            proposals = tuple(item for item in proposals if item[0] in names_to_replan)
            if not proposals:
                raise DomainError("RECOVERY_PLAN_SUPERSESSION_REQUIRED", "Invalidated plan identity is unsupported", status_code=409)
        now = datetime.now(UTC)
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
            plan_version = latest_rows[plan_id].plan_version + 1 if plan_id in replan_ids else 1
            proposal_id = proposal_id_for_plan(plan_id, plan_version)
            decision = ranking[plan_id]
            action_type = "CREATE_INTERNAL_REVIEW_TASK"
            action_params = {"strategy": strategy.value, "proposal": proposal.model_dump(mode="json") if proposal else None}
            constraints = [f"{item.code}:{item.resource_id}" for item in result.constraints]
            if name == "alternative_supply":
                constraints.append("SUPPLIER_AVAILABILITY_UNVERIFIED")
            if confirmation:
                constraints.append("CUSTOMER_ACCEPTANCE_REQUIRED_FOR_TERMS_CHANGE")
            evaluation = PlanEvaluation(
                evaluation_id=f"eval_{plan_id}_v{plan_version}", tenant_id=context.tenant_id,
                commitment_id=commitment_id, plan_id=plan_id, plan_version=plan_version,
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
            actions = [{
                "action_id": f"{plan_id}_v{plan_version}_task", "type": action_type,
                "requires_approval": True, "idempotency_key": f"{plan_id}_v{plan_version}_task",
                "parameters": action_params,
                "preconditions": ["Current Core and P2 versions", "Durable Manager Approval"],
            }]
            if confirmation and proposal is not None:
                actions.append({
                    "action_id": f"{plan_id}_v{plan_version}_proposal", "type": "CREATE_DELIVERY_CHANGE_PROPOSAL",
                    "requires_approval": True, "idempotency_key": f"{plan_id}_v{plan_version}_proposal",
                    "parameters": {"partial_quantity": str(proposal.quantity),
                                   "new_deadline": proposal.deadline.isoformat()},
                    "preconditions": ["Current Core and P2 versions", "Durable Manager Approval",
                                      "Separate customer acceptance before revised terms take effect"],
                })
            plan = RecoveryPlanVersion(
                tenant_id=context.tenant_id, recovery_case_id=case.case_id,
                plan_id=plan_id, plan_version=plan_version,
                proposal_id=proposal_id, proposal_version=plan_version,
                commitment_id=commitment_id,
                based_on_assessment_id=assessment.assessment_id,
                snapshot_id=snapshot.operational.snapshot_id,
                core_commitment_version=commitment.commitment_version,
                snapshot_version=snapshot.operational.snapshot_version,
                feasibility_status=result.status, estimated_extra_cost=cost, currency="MYR",
                estimated_delay_minutes=delay, risks=constraints,
                actions=actions,
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
                tenant_id=context.tenant_id, plan_id=plan_id, plan_version=plan_version,
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
        case.plans = [item for item in existing if item.plan_id not in replan_ids] + plans
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
