"""Core Integration Facade and P1–P4 handshake handlers.

Per REQUIREMENTS_SYSTEM.md §4 and PERSON_5 BE-06:
Features P1–P4 interact with P5 Core via this typed facade or through
subscribed domain events, preserving the invariant that feature-local code
never directly mutates the authoritative commitments table.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .dependencies import RequestContext
from .errors import DomainError
from .events import CoreEventType, create_domain_event
from .models import AuditEventRecord, CommitmentProposalRecord, CommitmentRecord, OutboxEventRecord
from .schemas import (
    AgreementState,
    BusinessContext,
    Commitment,
    CommitmentTerms,
    CommitmentTransitionRequest,
    CommitmentTransitionResponse,
    ContextStatus,
    CustomerIdentityStatus,
    DomainEvent,
    FeasibilityAssessment,
    FeasibilityState,
    FulfilmentState,
    ProposalConfirmRequest,
    ProposalCreateRequest,
    RecordFulfilmentRequest,
    RecoveryExecuteRequest,
    RecoveryPlan,
    RecoveryState,
    RecoveryStartRequest,
    RiskState,
)
from .service import CommitmentService

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


def _commitment_snapshot(record: CommitmentRecord) -> dict[str, object]:
    return {
        "agreement_state": record.agreement_state,
        "feasibility_state": record.feasibility_state,
        "risk_state": record.risk_state,
        "recovery_state": record.recovery_state,
        "fulfilment_state": record.fulfilment_state,
        "commitment_version": record.commitment_version,
    }


CONSEQUENTIAL_ACTIONS = {
    "CREATE_PURCHASE_REQUEST",
    "REALLOCATE_STOCK",
    "ADJUST_DELIVERY_TERMS",
    "MODIFY_TERMS",
    "EXPEDITE_SUPPLIER",
    "APPROVE_PLAN",
    "EXECUTE_PLAN",
    "CANCEL_COMMITMENT",
    "RECOVERY_EXECUTION",
}


class CoreIntegrationFacade:
    def __init__(self, service: CommitmentService | None = None) -> None:
        self.service = service or CommitmentService()

    # -------------------------------------------------------------------------
    # 1. P1 → P5 / P2 Handshake (BE-06a)
    # -------------------------------------------------------------------------
    def handle_context_updated(
        self,
        db: Session,
        context: RequestContext,
        business_context: BusinessContext,
    ) -> Commitment:
        """Process updated BusinessContext from P1.

        - If READY, LINK_VERIFIED, and no conflicts/missing fields: create or update
          commitment request (agreement_state=REQUESTED) and emit commitment.created / context_ready.
        - If conflicts or missing fields exist: keep commitment unconfirmed and flag
          MANUAL_REVIEW attention item (REQUESTED != CONFIRMED).
        - OCR receipt evidence (ev_receipt_*) is recorded as evidence only and NEVER
          auto-confirms or marks payment verified (UT-09).
        """
        now = _now()
        is_ready = business_context.status == ContextStatus.INFORMATION_READY
        is_verified = (
            business_context.customer_identity_status == CustomerIdentityStatus.LINK_VERIFIED
        )
        has_conflicts = bool(business_context.conflicts)
        has_missing_fields = bool(business_context.missing_fields)

        order_id = business_context.order_id or f"ord_{business_context.context_id}"
        customer_id = business_context.customer_id or "cust_unverified"

        # Build terms from first requested item
        first_item = business_context.requested_items[0]
        delivery_at = business_context.requested_delivery_at or now

        # Aggregate evidence refs from field_evidence
        evidence_refs: list[str] = []
        for refs in business_context.field_evidence.values():
            evidence_refs.extend(refs)
        if not evidence_refs:
            evidence_refs = [f"ev_ctx_{business_context.context_id}"]

        terms_dict: dict[str, Any] = {
            "sku": first_item.sku,
            "quantity": str(first_item.quantity),
            "unit": first_item.unit,
            "deadline": delivery_at.isoformat(),
            "special_instructions": business_context.special_instructions,
        }

        # Check existing commitment for this order
        record = db.scalar(
            select(CommitmentRecord).where(
                CommitmentRecord.tenant_id == context.tenant_id,
                CommitmentRecord.order_id == order_id,
            )
        )

        requires_review = has_conflicts or has_missing_fields or not is_verified or not is_ready
        if requires_review:
            terms_dict["requires_manual_review"] = True
            terms_dict["conflicts"] = business_context.conflicts
            terms_dict["missing_fields"] = business_context.missing_fields
            terms_dict["customer_identity_status"] = business_context.customer_identity_status.value

        if record is None:
            commitment_id = business_context.commitment_id or _id("com")
            record = CommitmentRecord(
                tenant_id=context.tenant_id,
                commitment_id=commitment_id,
                order_id=order_id,
                customer_id=customer_id,
                terms=terms_dict,
                agreement_state=AgreementState.REQUESTED.value,
                feasibility_state=FeasibilityState.NOT_ASSESSED.value,
                risk_state=RiskState.NORMAL.value,
                recovery_state=RecoveryState.NONE.value,
                fulfilment_state=FulfilmentState.NOT_STARTED.value,
                commitment_version=1,
                evidence_refs=list(dict.fromkeys(evidence_refs)),
                updated_at=now,
            )
            event_type = (
                CoreEventType.COMMITMENT_CREATED.value
                if not requires_review
                else CoreEventType.COMMITMENT_LIFECYCLE_CHANGED.value
            )
            audit = self.service._audit(
                context=context,
                commitment_id=commitment_id,
                event_type=event_type,
                dimension="agreement",
                previous_state=None,
                new_state=_commitment_snapshot(record),
                evidence_refs=evidence_refs,
                reason=(
                    "Commitment created from verified business context"
                    if not requires_review
                    else f"Context requires review: conflicts={business_context.conflicts}, missing={business_context.missing_fields}"
                ),
                occurred_at=now,
                causation_id=business_context.context_id,
            )
            event = self.service._outbox(
                context=context,
                event_id=_id("evt"),
                event_type=CoreEventType.COMMITMENT_CONTEXT_READY.value if not requires_review else CoreEventType.COMMITMENT_CREATED.value,
                commitment_id=commitment_id,
                commitment_version=1,
                payload={
                    "commitment_id": commitment_id,
                    "order_id": order_id,
                    "context_id": business_context.context_id,
                    "audit_id": audit.audit_id,
                },
                occurred_at=now,
                causation_id=business_context.context_id,
            )
            db.add_all([record, audit, event])
        else:
            # Update existing draft
            previous_state = _commitment_snapshot(record)
            record.terms = terms_dict
            record.evidence_refs = list(dict.fromkeys([*record.evidence_refs, *evidence_refs]))
            record.commitment_version += 1
            record.updated_at = now
            new_state = _commitment_snapshot(record)

            audit = self.service._audit(
                context=context,
                commitment_id=record.commitment_id,
                event_type=CoreEventType.COMMITMENT_LIFECYCLE_CHANGED.value,
                dimension="agreement",
                previous_state=previous_state,
                new_state=new_state,
                evidence_refs=evidence_refs,
                reason=f"Business context updated: conflicts={business_context.conflicts}",
                occurred_at=now,
                causation_id=business_context.context_id,
            )
            event = self.service._outbox(
                context=context,
                event_id=_id("evt"),
                event_type=CoreEventType.COMMITMENT_CONTEXT_READY.value if not requires_review else CoreEventType.COMMITMENT_LIFECYCLE_CHANGED.value,
                commitment_id=record.commitment_id,
                commitment_version=record.commitment_version,
                payload={
                    "commitment_id": record.commitment_id,
                    "order_id": record.order_id,
                    "context_id": business_context.context_id,
                },
                occurred_at=now,
                causation_id=business_context.context_id,
            )
            db.add_all([audit, event])

        db.commit()
        db.refresh(record)
        return self.service.get(db, context, record.commitment_id)

    # -------------------------------------------------------------------------
    # 2. P2 → P5 / P3 Handshake (BE-06b)
    # -------------------------------------------------------------------------
    def handle_feasibility_assessment(
        self,
        db: Session,
        context: RequestContext,
        commitment_id: str,
        assessment: FeasibilityAssessment,
    ) -> Commitment:
        """Process FeasibilityAssessment from P2.

        - Rejects stale assessments with 409 Conflict.
        - If CONFIRMED + INFEASIBLE: transitions risk_state=AT_RISK, recovery_state=RECOVERY_REQUIRED,
          and emits commitment.at_risk for P3.
        - If UNKNOWN: keeps UNKNOWN without falsely marking INFEASIBLE (UNKNOWN != INFEASIBLE).
        """
        return self.service.assess(db, context, commitment_id, assessment)

    # -------------------------------------------------------------------------
    # 3. P3 → P5 / P4 Handshake (BE-06c)
    # -------------------------------------------------------------------------
    def authorize(
        self,
        actor: str,
        actor_role: str,
        action_type: str,
        plan_version: int | None = None,
    ) -> None:
        """Enforce role-based authorization for recovery actions (BE-05c)."""
        if action_type in CONSEQUENTIAL_ACTIONS:
            if actor_role not in {"OWNER", "MANAGER"}:
                raise DomainError(
                    "APPROVAL_REQUIRED",
                    f"Role '{actor_role}' is not authorized to execute consequential action '{action_type}'; manager or owner authorization required",
                    status_code=403,
                )

    def start_recovery(
        self,
        db: Session,
        context: RequestContext,
        commitment_id: str,
        request: RecoveryStartRequest,
    ) -> CommitmentTransitionResponse:
        """Initiate recovery planning on an at-risk commitment."""
        return self.service.transition(
            db,
            context,
            commitment_id,
            CommitmentTransitionRequest(
                dimension="recovery",
                target_state="PLANNING",
                expected_commitment_version=request.expected_commitment_version,
                reason=request.reason,
                causation_id=request.causation_id,
            ),
        )

    def execute_recovery_plan(
        self,
        db: Session,
        context: RequestContext,
        commitment_id: str,
        request: RecoveryExecuteRequest,
    ) -> CommitmentTransitionResponse:
        """Revalidate recovery plan before execution and offer customer terms if needed.

        Invariants (E2E-04, UT-08):
        - Snapshot drift check: plan.snapshot_version == current_snapshot_version
        - Approval expiry check: _now() <= approval_expires_at
        - Commitment version check: commitment_version == expected_commitment_version
        If any validation fails: block execution (409 Conflict), invalidate approval,
        and set recovery_state=RECOVERY_REQUIRED.
        """
        self.authorize(context.actor_id, context.actor_role, "EXECUTE_PLAN", request.plan.plan_version)

        record = db.scalar(
            select(CommitmentRecord)
            .where(
                CommitmentRecord.tenant_id == context.tenant_id,
                CommitmentRecord.commitment_id == commitment_id,
            )
            .with_for_update()
        )
        if record is None:
            raise DomainError("COMMITMENT_NOT_FOUND", "Commitment not found", status_code=404)

        now = _now()
        # 1. Snapshot drift guard (E2E-04)
        if request.plan.snapshot_version != request.current_snapshot_version:
            record.recovery_state = RecoveryState.RECOVERY_REQUIRED.value
            record.updated_at = now
            db.commit()
            raise DomainError(
                "SNAPSHOT_DRIFT_CONFLICT",
                f"Operational snapshot drifted (plan snapshot {request.plan.snapshot_version} != current {request.current_snapshot_version}); execution blocked and approval invalidated",
                status_code=409,
                details={
                    "plan_snapshot_version": request.plan.snapshot_version,
                    "current_snapshot_version": request.current_snapshot_version,
                },
            )

        # 2. Approval expiry guard (UT-08)
        if now > _aware(request.approval_expires_at):
            record.recovery_state = RecoveryState.RECOVERY_REQUIRED.value
            record.updated_at = now
            db.commit()
            raise DomainError(
                "APPROVAL_EXPIRED",
                "Manager approval has expired; re-approval required before execution",
                status_code=409,
                details={"approval_expires_at": request.approval_expires_at.isoformat()},
            )

        # 3. Commitment version check
        if record.commitment_version != request.expected_commitment_version:
            record.recovery_state = RecoveryState.RECOVERY_REQUIRED.value
            record.updated_at = now
            db.commit()
            raise DomainError(
                "COMMITMENT_VERSION_CONFLICT",
                "Commitment version has drifted since plan approval",
                status_code=409,
                details={"current_commitment_version": record.commitment_version},
            )

        # Revalidation passed. Check if customer terms need proposal to P4.
        requires_customer_terms = (
            request.revised_terms is not None
            or any(a.type in {"ADJUST_DELIVERY_TERMS", "MODIFY_TERMS", "CUSTOMER_PROPOSAL"} for a in request.plan.actions)
        )

        if requires_customer_terms:
            proposal_res = self.service.create_proposal(
                db,
                context,
                commitment_id,
                ProposalCreateRequest(
                    proposal_id=f"prop_{request.plan.plan_id}",
                    proposal_version=request.plan.plan_version,
                    expected_commitment_version=record.commitment_version,
                    revised_terms=request.revised_terms,
                    reason=f"Recovery plan {request.plan.plan_id} offered revised terms: {request.reason}",
                    evidence_refs=[f"ev_plan_{request.plan.plan_id}"],
                    causation_id=request.causation_id,
                ),
            )
            # Emit recovery.communication_requested for P4
            comm_event = self.service._outbox(
                context=context,
                event_id=_id("evt"),
                event_type=CoreEventType.RECOVERY_COMMUNICATION_REQUESTED.value,
                commitment_id=commitment_id,
                commitment_version=proposal_res.commitment.commitment_version,
                payload={
                    "commitment_id": commitment_id,
                    "plan_id": request.plan.plan_id,
                    "plan_version": request.plan.plan_version,
                    "proposal_id": f"prop_{request.plan.plan_id}",
                    "proposal_version": request.plan.plan_version,
                },
                occurred_at=now,
                causation_id=request.causation_id,
            )
            db.add(comm_event)
            db.commit()
            return proposal_res

        # Internal operational execution
        return self.service.transition(
            db,
            context,
            commitment_id,
            CommitmentTransitionRequest(
                dimension="recovery",
                target_state="EXECUTING",
                expected_commitment_version=record.commitment_version,
                reason=request.reason,
                causation_id=request.causation_id,
            ),
        )

    # -------------------------------------------------------------------------
    # 4. P4 → P5 / P3 Handshake (BE-06d, UT-10)
    # -------------------------------------------------------------------------
    def record_communication_status(
        self,
        db: Session,
        context: RequestContext,
        commitment_id: str,
        message_status: str,
        evidence_refs: list[str],
    ) -> None:
        """Record communication delivery updates (MESSAGE_SENT, DELIVERED, READ).

        Invariant (E2E-07):
        Delivery state updates record audit and outbox ONLY; they NEVER mutate
        agreement_state or fulfilment_state.
        """
        record = db.scalar(
            select(CommitmentRecord).where(
                CommitmentRecord.tenant_id == context.tenant_id,
                CommitmentRecord.commitment_id == commitment_id,
            )
        )
        if record is None:
            raise DomainError("COMMITMENT_NOT_FOUND", "Commitment not found", status_code=404)

        now = _now()
        audit = self.service._audit(
            context=context,
            commitment_id=commitment_id,
            event_type=CoreEventType.COMMITMENT_LIFECYCLE_CHANGED.value,
            dimension="agreement",
            previous_state=_commitment_snapshot(record),
            new_state=_commitment_snapshot(record),
            evidence_refs=evidence_refs,
            reason=f"Communication status: {message_status} (delivery tracking only)",
            occurred_at=now,
            causation_id=context.causation_id,
        )
        event = self.service._outbox(
            context=context,
            event_id=_id("evt"),
            event_type=CoreEventType.COMMITMENT_LIFECYCLE_CHANGED.value,
            commitment_id=commitment_id,
            commitment_version=record.commitment_version,
            payload={
                "commitment_id": commitment_id,
                "message_status": message_status,
                "evidence_refs": evidence_refs,
            },
            occurred_at=now,
            causation_id=context.causation_id,
        )
        db.add_all([audit, event])
        db.commit()

    def record_ambiguous_response(
        self,
        db: Session,
        context: RequestContext,
        commitment_id: str,
        customer_message: str,
        evidence_refs: list[str],
    ) -> None:
        """Handle vague or ambiguous customer response (E2E-05).

        Invariant: Keeps confirmation pending (AWAITING_RESPONSE) and flags attention
        item UNRESOLVED_CONFIRMATION; NEVER auto-confirms a commitment.
        """
        record = db.scalar(
            select(CommitmentRecord)
            .where(
                CommitmentRecord.tenant_id == context.tenant_id,
                CommitmentRecord.commitment_id == commitment_id,
            )
            .with_for_update()
        )
        if record is None:
            raise DomainError("COMMITMENT_NOT_FOUND", "Commitment not found", status_code=404)

        now = _now()
        # Mark ambiguous in terms for attention queue reflection
        terms = dict(record.terms) if isinstance(record.terms, dict) else {}
        terms["confirmation_ambiguous"] = True
        record.terms = terms
        record.updated_at = now
        record.evidence_refs = list(dict.fromkeys([*record.evidence_refs, *evidence_refs]))

        audit = self.service._audit(
            context=context,
            commitment_id=commitment_id,
            event_type=CoreEventType.COMMITMENT_LIFECYCLE_CHANGED.value,
            dimension="agreement",
            previous_state=_commitment_snapshot(record),
            new_state=_commitment_snapshot(record),
            evidence_refs=evidence_refs,
            reason=f"Ambiguous response received ('{customer_message}'); auto-confirmation blocked, clarification required",
            occurred_at=now,
            causation_id=context.causation_id,
        )
        db.add(audit)
        db.commit()

    def confirm_proposal(
        self,
        db: Session,
        context: RequestContext,
        commitment_id: str,
        request: ProposalConfirmRequest,
    ) -> CommitmentTransitionResponse:
        """Confirm or reject a customer terms proposal.

        Enforces E2E-06 (stale proposal version rejection) and UT-10 (terms update
        without marking fulfilment).
        """
        return self.service.confirm_proposal(db, context, commitment_id, request)

    # -------------------------------------------------------------------------
    # 5. Operational Fulfilment (BE-02h, UT-10, E2E-12)
    # -------------------------------------------------------------------------
    def record_fulfilment(
        self,
        db: Session,
        context: RequestContext,
        commitment_id: str,
        request: RecordFulfilmentRequest,
    ) -> CommitmentTransitionResponse:
        """Verify and record actual operational fulfilment.

        Enforces E2E-12: Trusted operational delivery evidence required,
        manager role, and CONFIRMED agreement state.
        """
        return self.service.record_fulfilment(db, context, commitment_id, request)
