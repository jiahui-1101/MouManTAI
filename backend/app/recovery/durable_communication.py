"""Isolated, versioned P3 proposal handoff to P4's persisted event boundary."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.events import create_domain_event
from app.core.manager_approval import ManagerApprovalService, trusted_isolated_manager
from app.core.models import CommitmentProposalRecord, CommitmentRecord, OutboxEventRecord
from app.core.schemas import AgreementState, CommitmentTerms, ContractModel, ProposalCreateRequest
from app.core.service import CommitmentService
from app.feasibility.persisted_sources import read_snapshot
from app.feasibility.production import ProposedChanges
from app.feasibility.service import evaluate

from .durable_plans import RecoveryPlanRecord
from .models import RecoveryPlanVersion
from .proposal_identity import proposal_id_for_plan, require_proposal_binding


class RequestCommunicationInput(ContractModel):
    expected_plan_version: int = Field(ge=1)
    expected_commitment_version: int = Field(ge=1)
    expected_snapshot_version: int = Field(ge=1)


class CommunicationHandoffView(ContractModel):
    tenant_id: str
    commitment_id: str
    plan_id: str
    plan_version: int
    proposal_id: str
    proposal_version: int
    approval_id: str
    source_event_id: str
    commitment_version: int
    approved_terms: CommitmentTerms
    status: str = "COMMUNICATION_REQUESTED"


class DurableCommunicationHandoff:
    def request(
        self, db: Session, context: RequestContext, key: str | None, plan_id: str,
        command: RequestCommunicationInput,
    ) -> CommunicationHandoffView:
        manager_id = trusted_isolated_manager(context, key)
        plan = db.get(RecoveryPlanRecord, (context.tenant_id, plan_id, command.expected_plan_version))
        if plan is None:
            raise DomainError("RECOVERY_PLAN_NOT_FOUND", "Recovery plan was not found", status_code=404)
        if plan.status != "PENDING_APPROVAL":
            raise DomainError("PLAN_VERSION_NOT_ACTIVE", "This plan version is no longer actionable", status_code=409)
        typed = RecoveryPlanVersion.model_validate(plan.payload)
        if (typed.tenant_id, typed.commitment_id, typed.plan_id, typed.plan_version) != (
            context.tenant_id, plan.commitment_id, plan_id, plan.plan_version,
        ):
            raise DomainError("RECOVERY_PLAN_BINDING_MISMATCH", "Persisted plan identity is inconsistent", status_code=409)
        proposal_id, proposal_version = require_proposal_binding(
            plan_id, plan.plan_version, typed.proposal_id, typed.proposal_version,
        )
        commitment = db.scalar(select(CommitmentRecord).where(
            CommitmentRecord.tenant_id == context.tenant_id,
            CommitmentRecord.commitment_id == plan.commitment_id,
        ).with_for_update())
        if commitment is None:
            raise DomainError("COMMITMENT_NOT_FOUND", "Commitment was not found", status_code=404)
        existing = db.scalars(select(OutboxEventRecord).where(
            OutboxEventRecord.tenant_id == context.tenant_id,
            OutboxEventRecord.commitment_id == plan.commitment_id,
            OutboxEventRecord.event_type == "recovery.communication_requested",
        )).all()
        for source in existing:
            if (source.payload.get("plan_id"), source.payload.get("plan_version")) != (
                plan_id, plan.plan_version,
            ):
                continue
            if (source.payload.get("proposal_id"), source.payload.get("proposal_version")) != (
                proposal_id, proposal_version,
            ):
                raise DomainError("PROPOSAL_PLAN_IDENTITY_CONFLICT", "Offered proposal does not match plan version", status_code=409)
            proposal = db.get(CommitmentProposalRecord, (context.tenant_id, proposal_id))
            if (proposal is None or proposal.status != "ACTIVE"
                or proposal.proposal_version != proposal_version
                or proposal.commitment_id != plan.commitment_id
                or commitment.commitment_version != source.commitment_version):
                raise DomainError("PROPOSAL_SUPERSEDED", "Communication proposal is no longer current", status_code=409)
            approval = ManagerApprovalService().require_active(db, context, plan)
            if (approval.proposal_id, approval.proposal_version) != (proposal_id, proposal_version):
                raise DomainError("APPROVAL_SCOPE_CONFLICT", "Manager approval binds another proposal", status_code=409)
            if approval.approval_id != source.payload["approval_id"]:
                raise DomainError("APPROVAL_SUPERSEDED", "Communication approval is no longer current", status_code=409)
            return CommunicationHandoffView(
                tenant_id=context.tenant_id, commitment_id=plan.commitment_id,
                plan_id=plan_id, plan_version=plan.plan_version,
                proposal_id=proposal.proposal_id, proposal_version=proposal.proposal_version,
                approval_id=source.payload["approval_id"], source_event_id=source.event_id,
                commitment_version=source.commitment_version,
                approved_terms=CommitmentTerms.model_validate(proposal.revised_terms),
            )
        snapshot = read_snapshot(db, context.tenant_id)
        if (plan.core_commitment_version, command.expected_commitment_version,
            commitment.commitment_version) != (commitment.commitment_version,) * 3:
            raise DomainError("COMMITMENT_VERSION_CONFLICT", "Proposal plan is stale", status_code=409)
        if (plan.snapshot_id, plan.snapshot_version, command.expected_snapshot_version) != (
            snapshot.operational.snapshot_id, snapshot.operational.snapshot_version,
            snapshot.operational.snapshot_version,
        ):
            raise DomainError("SNAPSHOT_DRIFT_CONFLICT", "Proposal source is stale", status_code=409)
        action = next((item for item in typed.actions if item.type == "CREATE_DELIVERY_CHANGE_PROPOSAL"), None)
        if typed.option_id != "revised_schedule" or action is None or not typed.customer_confirmation_required:
            raise DomainError("PROPOSAL_NOT_ALLOWED", "Plan has no customer terms proposal", status_code=409)
        approval = ManagerApprovalService().require_active(db, context, plan)
        if (approval.proposal_id, approval.proposal_version) != (proposal_id, proposal_version):
            raise DomainError("APPROVAL_SCOPE_CONFLICT", "Manager approval binds another proposal", status_code=409)
        if "CREATE_DELIVERY_CHANGE_PROPOSAL" not in approval.action_scope:
            raise DomainError("APPROVAL_SCOPE_CONFLICT", "Manager did not approve revised terms", status_code=409)
        current_terms = dict(commitment.terms)
        # Core retains Mock acceptance provenance on the accepted record;
        # it cannot become part of a customer-facing revised-terms proposal.
        current_terms.pop("mock_order_request_version", None)
        current_terms.pop("mock_terms_hash", None)
        try:
            revised = CommitmentTerms.model_validate({
                **current_terms,
                "quantity": action.parameters["partial_quantity"],
                "deadline": action.parameters["new_deadline"],
            })
        except ValidationError as exc:
            raise DomainError("PROPOSAL_TERMS_INVALID", "Revised terms are invalid", status_code=409) from exc
        if revised.model_dump(mode="json") != approval.approved_terms:
            raise DomainError("APPROVED_TERMS_MISMATCH", "Manager approval does not bind exact terms", status_code=409)
        source = next((row for row in snapshot.operational.confirmed_commitments
                       if row.commitment_id == plan.commitment_id), None)
        if source is None or source.commitment_version != plan.evaluated_commitment_version:
            raise DomainError("P2_COMMITMENT_BINDING_MISMATCH", "P2 source changed", status_code=409)
        current = CommitmentService().get(db, context, plan.commitment_id)
        if current.agreement_state == AgreementState.OFFERED:
            prior_offer = db.scalar(select(CommitmentProposalRecord).where(
                CommitmentProposalRecord.tenant_id == context.tenant_id,
                CommitmentProposalRecord.commitment_id == plan.commitment_id,
                CommitmentProposalRecord.status == "ACTIVE",
                CommitmentProposalRecord.proposal_version < proposal_version,
            ))
            if prior_offer is None or prior_offer.proposal_id != proposal_id_for_plan(
                plan_id, prior_offer.proposal_version,
            ):
                raise DomainError("PROPOSAL_SOURCE_CONFLICT", "No prior active offer supports replanning", status_code=409)
        elif current.agreement_state != AgreementState.CONFIRMED:
            raise DomainError("PROPOSAL_SOURCE_CONFLICT", "Commitment is not eligible for a recovery offer", status_code=409)
        historical = current.model_copy(update={
            "commitment_version": plan.evaluated_commitment_version,
            "agreement_state": AgreementState.CONFIRMED,
        })
        proposed = ProposedChanges.model_validate(typed.actions[0].parameters["proposal"])
        result = evaluate(snapshot, proposed, historical)
        if (result.status, result.solver_status.value, result.snapshot_id) != (
            typed.feasibility_status, typed.evaluation.solver_status, plan.snapshot_id,
        ) or result.status not in {"FEASIBLE", "CONDITIONAL"}:
            raise DomainError("PLAN_REVALIDATION_FAILED", "P2 result changed", status_code=409)
        if db.get(CommitmentProposalRecord, (context.tenant_id, proposal_id)) is not None:
            raise DomainError("PROPOSAL_ID_CONFLICT", "Proposal identity is already in use", status_code=409)
        trusted = RequestContext(context.tenant_id, manager_id, "MANAGER", context.correlation_id,
                                 context.causation_id or approval.approval_id)
        try:
            offered = CommitmentService().create_proposal(
                db, trusted, plan.commitment_id,
                ProposalCreateRequest(
                    proposal_id=proposal_id, proposal_version=proposal_version,
                    expected_commitment_version=plan.core_commitment_version,
                    revised_terms=revised, reason=f"Approved recovery plan {plan_id} v{plan.plan_version}",
                    evidence_refs=[approval.audit_id, plan.assessment_id, plan.snapshot_id],
                    causation_id=approval.approval_id,
                ), commit=False,
            )
            event = create_domain_event(
                event_type="recovery.communication_requested", tenant_id=context.tenant_id,
                commitment_id=plan.commitment_id,
                commitment_version=offered.commitment.commitment_version,
                correlation_id=context.correlation_id, causation_id=approval.approval_id,
                payload={"commitment_id": plan.commitment_id, "plan_id": plan_id,
                         "plan_version": plan.plan_version, "proposal_id": proposal_id,
                         "proposal_version": proposal_version, "snapshot_id": plan.snapshot_id,
                         "snapshot_version": plan.snapshot_version, "approval_id": approval.approval_id,
                         "approval_evidence_ref": approval.audit_id,
                         "approved_terms": revised.model_dump(mode="json")},
            )
            db.add(OutboxEventRecord(
                event_id=event.event_id, tenant_id=context.tenant_id,
                event_type=event.event_type, commitment_id=plan.commitment_id,
                commitment_version=event.commitment_version,
                correlation_id=event.correlation_id, causation_id=event.causation_id,
                occurred_at=datetime.now(UTC), payload=event.payload,
                attempts=0, status="PENDING",
            ))
            db.commit()
        except Exception:
            db.rollback()
            raise
        return CommunicationHandoffView(
            tenant_id=context.tenant_id, commitment_id=plan.commitment_id,
            plan_id=plan_id, plan_version=plan.plan_version,
            proposal_id=proposal_id, proposal_version=proposal_version,
            approval_id=approval.approval_id, source_event_id=event.event_id,
            commitment_version=offered.commitment.commitment_version,
            approved_terms=revised,
        )
