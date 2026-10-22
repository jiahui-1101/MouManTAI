from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .audit import build_timeline_entries, redact_payload, redact_text
from .commitments import get_overview
from .dependencies import RequestContext
from .errors import DomainError
from .events import CoreEventType, OutboxStatus
from .models import AuditEventRecord, CommitmentProposalRecord, CommitmentRecord, OutboxEventRecord
from .schemas import (
    AgreementState,
    AuditEvent,
    Commitment,
    CommitmentCreateRequest,
    CommitmentTransitionRequest,
    CommitmentTransitionResponse,
    CustomerIdentityStatus,
    DomainEvent,
    FeasibilityAssessment,
    FeasibilityState,
    FulfilmentState,
    OverviewResponse,
    ProposalConfirmRequest,
    ProposalCreateRequest,
    RecordFulfilmentRequest,
    RecoveryState,
    RiskState,
    TimelineEntry,
)


TRANSITIONS: dict[str, dict[str, set[str]]] = {
    "agreement": {
        "REQUESTED": {"OFFERED", "CANCELLED"},
        "OFFERED": {"CONFIRMED", "REJECTED", "CANCELLED"},
        "CONFIRMED": {"CANCELLED"},
        "REJECTED": set(),
        "CANCELLED": set(),
    },
    "feasibility": {
        "NOT_ASSESSED": {"FEASIBLE", "CONDITIONAL", "INFEASIBLE", "UNKNOWN"},
        "FEASIBLE": {"CONDITIONAL", "INFEASIBLE", "UNKNOWN"},
        "CONDITIONAL": {"FEASIBLE", "INFEASIBLE", "UNKNOWN"},
        "INFEASIBLE": {"FEASIBLE", "CONDITIONAL", "UNKNOWN"},
        "UNKNOWN": {"FEASIBLE", "CONDITIONAL", "INFEASIBLE"},
    },
    "risk": {
        "NORMAL": {"AT_RISK", "BREACHED"},
        "AT_RISK": {"RESOLVED", "BREACHED"},
        "BREACHED": {"RESOLVED"},
        "RESOLVED": {"AT_RISK", "BREACHED"},
    },
    "recovery": {
        "NONE": {"PLANNING", "RECOVERY_REQUIRED"},
        "PLANNING": {"PENDING_APPROVAL", "RECOVERY_REQUIRED"},
        "PENDING_APPROVAL": {"EXECUTING", "RECOVERY_REQUIRED"},
        "EXECUTING": {"COMPLETED", "RECOVERY_REQUIRED"},
        "COMPLETED": {"PLANNING"},
        "RECOVERY_REQUIRED": {"PLANNING"},
    },
    "fulfilment": {
        "NOT_STARTED": {"IN_PROGRESS", "PARTIALLY_FULFILLED", "UNVERIFIED"},
        "IN_PROGRESS": {"PARTIALLY_FULFILLED", "FULFILLED", "UNVERIFIED"},
        "PARTIALLY_FULFILLED": {"IN_PROGRESS", "FULFILLED", "UNVERIFIED"},
        "UNVERIFIED": {"IN_PROGRESS", "PARTIALLY_FULFILLED", "FULFILLED"},
        "FULFILLED": set(),
    },
}

DIMENSION_FIELD = {
    "agreement": "agreement_state",
    "feasibility": "feasibility_state",
    "risk": "risk_state",
    "recovery": "recovery_state",
    "fulfilment": "fulfilment_state",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


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


def _to_commitment(record: CommitmentRecord) -> Commitment:
    terms_dict = record.terms
    if isinstance(terms_dict, dict):
        terms_dict = {
            k: v
            for k, v in terms_dict.items()
            if k in {"sku", "quantity", "unit", "deadline", "special_instructions"}
        }
    return Commitment.model_validate(
        {
            "tenant_id": record.tenant_id,
            "commitment_id": record.commitment_id,
            "order_id": record.order_id,
            "customer_id": record.customer_id,
            "terms": terms_dict,
            "agreement_state": record.agreement_state,
            "feasibility_state": record.feasibility_state,
            "risk_state": record.risk_state,
            "recovery_state": record.recovery_state,
            "fulfilment_state": record.fulfilment_state,
            "commitment_version": record.commitment_version,
            "evidence_refs": record.evidence_refs,
            "updated_at": _aware(record.updated_at),
        }
    )



def _to_audit(record: AuditEventRecord, role: str = "STAFF") -> AuditEvent:
    return AuditEvent.model_validate(
        {
            "audit_id": record.audit_id,
            "tenant_id": record.tenant_id,
            "commitment_id": record.commitment_id,
            "event_type": record.event_type,
            "actor_id": record.actor_id,
            "actor_role": record.actor_role,
            "dimension": record.dimension,
            "previous_state": redact_payload(record.previous_state, role),
            "new_state": redact_payload(record.new_state, role),
            "evidence_refs": record.evidence_refs,
            "reason": redact_text(record.reason, role),
            "correlation_id": record.correlation_id,
            "causation_id": record.causation_id,
            "occurred_at": _aware(record.occurred_at),
        }
    )


def _to_event(record: OutboxEventRecord) -> DomainEvent:
    return DomainEvent.model_validate(
        {
            "event_id": record.event_id,
            "schema_version": 1,
            "event_type": record.event_type,
            "tenant_id": record.tenant_id,
            "commitment_id": record.commitment_id,
            "commitment_version": record.commitment_version,
            "correlation_id": record.correlation_id,
            "causation_id": record.causation_id,
            "occurred_at": _aware(record.occurred_at),
            "payload": record.payload,
        }
    )


class CommitmentService:
    def create_request(
        self,
        db: Session,
        context: RequestContext,
        request: CommitmentCreateRequest,
        commit: bool = True,
    ) -> Commitment:
        now = _now()
        commitment_id = request.commitment_id or _id("com")
        causation_id = request.causation_id or context.causation_id
        record = CommitmentRecord(
            tenant_id=context.tenant_id,
            commitment_id=commitment_id,
            order_id=request.order_id,
            customer_id=request.customer_id,
            terms=request.terms.model_dump(mode="json"),
            agreement_state=AgreementState.REQUESTED.value,
            feasibility_state=FeasibilityState.NOT_ASSESSED.value,
            risk_state=RiskState.NORMAL.value,
            recovery_state=RecoveryState.NONE.value,
            fulfilment_state=FulfilmentState.NOT_STARTED.value,
            commitment_version=1,
            evidence_refs=list(request.evidence_refs),
            updated_at=now,
        )
        audit = self._audit(
            context=context,
            commitment_id=commitment_id,
            event_type=CoreEventType.COMMITMENT_CREATED.value,
            dimension="agreement",
            previous_state=None,
            new_state=_commitment_snapshot(record),
            evidence_refs=request.evidence_refs,
            reason="Commitment request created",
            occurred_at=now,
            causation_id=causation_id,
        )
        event = self._outbox(
            context=context,
            event_id=_id("evt"),
            event_type=CoreEventType.COMMITMENT_CREATED.value,
            commitment_id=commitment_id,
            commitment_version=1,
            payload={"commitment_id": commitment_id, "audit_id": audit.audit_id},
            occurred_at=now,
            causation_id=causation_id,
        )
        try:
            db.add_all([record, audit, event])
            if commit:
                db.commit()
                db.refresh(record)
            else:
                db.flush()
        except Exception:
            db.rollback()
            raise
        return _to_commitment(record)

    def get(self, db: Session, context: RequestContext, commitment_id: str) -> Commitment:
        record = db.get(CommitmentRecord, (context.tenant_id, commitment_id))
        if record is None:
            raise DomainError("COMMITMENT_NOT_FOUND", "Commitment not found", status_code=404)
        return _to_commitment(record)

    def list(self, db: Session, context: RequestContext) -> list[Commitment]:
        records = db.scalars(
            select(CommitmentRecord)
            .where(CommitmentRecord.tenant_id == context.tenant_id)
            .order_by(CommitmentRecord.updated_at.desc())
        ).all()
        return [_to_commitment(record) for record in records]

    def transition(
        self,
        db: Session,
        context: RequestContext,
        commitment_id: str,
        request: CommitmentTransitionRequest,
        commit: bool = True,
    ) -> CommitmentTransitionResponse:
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
        if record.commitment_version != request.expected_commitment_version:
            raise DomainError(
                "COMMITMENT_VERSION_CONFLICT",
                "Commitment version is stale",
                status_code=409,
                details={"current_commitment_version": record.commitment_version},
            )

        dimension = request.dimension
        field = DIMENSION_FIELD[dimension]
        current_state = getattr(record, field)
        target_state = request.target_state.upper()
        allowed = TRANSITIONS[dimension].get(current_state, set())
        if target_state not in allowed:
            raise DomainError(
                "INVALID_STATE_TRANSITION",
                f"Cannot transition {dimension} from {current_state} to {target_state}",
                status_code=409,
            )
        self._authorize_transition(context, dimension, target_state, request.evidence_refs)

        causation_id = request.causation_id or context.causation_id
        previous_state = _commitment_snapshot(record)
        setattr(record, field, target_state)
        record.commitment_version += 1
        record.updated_at = _now()
        record.evidence_refs = list(dict.fromkeys([*record.evidence_refs, *request.evidence_refs]))
        new_state = _commitment_snapshot(record)
        event_type = self._event_type(dimension, target_state)
        audit = self._audit(
            context=context,
            commitment_id=commitment_id,
            event_type=event_type,
            dimension=dimension,
            previous_state=previous_state,
            new_state=new_state,
            evidence_refs=request.evidence_refs,
            reason=request.reason,
            occurred_at=record.updated_at,
            causation_id=causation_id,
        )
        event = self._outbox(
            context=context,
            event_id=_id("evt"),
            event_type=event_type,
            commitment_id=commitment_id,
            commitment_version=record.commitment_version,
            payload={
                "commitment_id": commitment_id,
                "dimension": dimension,
                "target_state": target_state,
                "audit_id": audit.audit_id,
            },
            occurred_at=record.updated_at,
            causation_id=causation_id,
        )
        try:
            db.add_all([audit, event])
            db.commit()
            db.refresh(record)
        except Exception:
            db.rollback()
            raise
        return CommitmentTransitionResponse(
            commitment=_to_commitment(record),
            audit_event=_to_audit(audit, role=context.actor_role),
            domain_event=_to_event(event),
        )

    def overview(self, db: Session, context: RequestContext) -> OverviewResponse:
        return get_overview(db, context)

    def timeline(self, db: Session, context: RequestContext, commitment_id: str) -> list[TimelineEntry]:
        commitment = db.get(CommitmentRecord, (context.tenant_id, commitment_id))
        if commitment is None:
            raise DomainError("COMMITMENT_NOT_FOUND", "Commitment not found", status_code=404)

        audit_records = db.scalars(
            select(AuditEventRecord)
            .where(
                AuditEventRecord.tenant_id == context.tenant_id,
                AuditEventRecord.commitment_id == commitment_id,
            )
            .order_by(AuditEventRecord.occurred_at.asc())
        ).all()

        outbox_records = db.scalars(
            select(OutboxEventRecord)
            .where(
                OutboxEventRecord.tenant_id == context.tenant_id,
                OutboxEventRecord.commitment_id == commitment_id,
            )
            .order_by(OutboxEventRecord.occurred_at.asc())
        ).all()

        return build_timeline_entries(commitment, audit_records, outbox_records, role=context.actor_role)

    def create_proposal(
        self,
        db: Session,
        context: RequestContext,
        commitment_id: str,
        request: ProposalCreateRequest,
        commit: bool = True,
    ) -> CommitmentTransitionResponse:
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

        if record.commitment_version != request.expected_commitment_version:
            raise DomainError(
                "COMMITMENT_VERSION_CONFLICT",
                "Commitment version is stale",
                status_code=409,
                details={"current_commitment_version": record.commitment_version},
            )

        if record.agreement_state == AgreementState.CANCELLED.value:
            raise DomainError(
                "INVALID_STATE_TRANSITION",
                "Cannot offer proposal for a cancelled commitment",
                status_code=409,
            )

        proposal_id = request.proposal_id or _id("prop")
        previous_state = _commitment_snapshot(record)

        # Mark existing active proposals for this commitment as SUPERSEDED
        existing_active = db.scalars(
            select(CommitmentProposalRecord).where(
                CommitmentProposalRecord.tenant_id == context.tenant_id,
                CommitmentProposalRecord.commitment_id == commitment_id,
                CommitmentProposalRecord.status == "ACTIVE",
            )
        ).all()
        for p in existing_active:
            p.status = "SUPERSEDED"
            p.updated_at = _now()

        proposal_record = CommitmentProposalRecord(
            tenant_id=context.tenant_id,
            proposal_id=proposal_id,
            commitment_id=commitment_id,
            proposal_version=request.proposal_version,
            revised_terms=request.revised_terms.model_dump(mode="json") if request.revised_terms else None,
            status="ACTIVE",
            reason=request.reason,
            evidence_refs=request.evidence_refs,
            created_at=_now(),
            updated_at=_now(),
        )

        record.agreement_state = AgreementState.OFFERED.value
        # D-015: Offering a proposal preserves existing accepted Commitment terms;
        # revised_terms are stored on the CommitmentProposalRecord and only applied upon customer ACCEPT.
        record.commitment_version += 1
        record.updated_at = _now()
        record.evidence_refs = list(dict.fromkeys([*record.evidence_refs, *request.evidence_refs]))
        new_state = _commitment_snapshot(record)

        causation_id = request.causation_id or context.causation_id
        audit = self._audit(
            context=context,
            commitment_id=commitment_id,
            event_type=CoreEventType.COMMITMENT_PROPOSAL_OFFERED.value,
            dimension="agreement",
            previous_state=previous_state,
            new_state=new_state,
            evidence_refs=request.evidence_refs,
            reason=request.reason,
            occurred_at=record.updated_at,
            causation_id=causation_id,
        )
        event = self._outbox(
            context=context,
            event_id=_id("evt"),
            event_type=CoreEventType.COMMITMENT_PROPOSAL_OFFERED.value,
            commitment_id=commitment_id,
            commitment_version=record.commitment_version,
            payload={
                "commitment_id": commitment_id,
                "proposal_id": proposal_id,
                "proposal_version": request.proposal_version,
                "audit_id": audit.audit_id,
                "evidence_refs": request.evidence_refs,
            },
            occurred_at=record.updated_at,
            causation_id=causation_id,
        )
        if commit:
            try:
                db.add_all([audit, event, proposal_record])
                db.commit()
                db.refresh(record)
            except Exception:
                db.rollback()
                raise
        else:
            db.add_all([audit, event, proposal_record])
            db.flush()

        return CommitmentTransitionResponse(
            commitment=_to_commitment(record),
            audit_event=_to_audit(audit, role=context.actor_role),
            domain_event=_to_event(event),
        )

    def confirm_proposal(
        self,
        db: Session,
        context: RequestContext,
        commitment_id: str,
        request: ProposalConfirmRequest,
        commit: bool = True,
    ) -> CommitmentTransitionResponse:
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

        if record.commitment_version != request.expected_commitment_version:
            raise DomainError(
                "COMMITMENT_VERSION_CONFLICT",
                "Commitment version is stale",
                status_code=409,
                details={"current_commitment_version": record.commitment_version},
            )

        if record.agreement_state != AgreementState.OFFERED.value:
            raise DomainError(
                "INVALID_STATE_TRANSITION",
                f"Cannot confirm proposal when agreement state is {record.agreement_state} (expected OFFERED)",
                status_code=409,
            )

        if context.actor_role not in {"OWNER", "MANAGER"}:
            raise DomainError("APPROVAL_REQUIRED", "Manager or owner approval is required to confirm proposal", status_code=403)

        if not request.evidence_refs:
            raise DomainError("EVIDENCE_REQUIRED", "Confirmation evidence is required", status_code=422)

        # Check latest proposal version (E2E-06: reject stale signed confirmation)
        latest_proposal = db.scalars(
            select(CommitmentProposalRecord)
            .where(
                CommitmentProposalRecord.tenant_id == context.tenant_id,
                CommitmentProposalRecord.commitment_id == commitment_id,
            )
            .order_by(CommitmentProposalRecord.proposal_version.desc())
        ).first()

        if latest_proposal is not None and request.proposal_version != latest_proposal.proposal_version:
            raise DomainError(
                "STALE_PROPOSAL_VERSION",
                f"Proposal version {request.proposal_version} is stale; latest active version is {latest_proposal.proposal_version}",
                status_code=409,
                details={
                    "active_proposal_version": latest_proposal.proposal_version,
                    "submitted_proposal_version": request.proposal_version,
                },
            )

        # Check customer identity link
        if request.customer_identity_status == CustomerIdentityStatus.UNVERIFIED or (
            isinstance(record.terms, dict)
            and record.terms.get("customer_identity_status") == CustomerIdentityStatus.UNVERIFIED.value
        ):
            raise DomainError(
                "UNVERIFIED_IDENTITY",
                "Customer identity must be verified before confirming proposal",
                status_code=422,
            )

        # Invariant: OCR receipt alone never confirms a commitment (UT-09)
        if all(ref.startswith("ev_receipt_") or "receipt" in ref.lower() for ref in request.evidence_refs):
            raise DomainError(
                "RECEIPT_CANNOT_CONFIRM",
                "Receipt evidence alone cannot confirm a commitment; signed agreement or confirmation required",
                status_code=422,
            )

        previous_state = _commitment_snapshot(record)
        if request.decision == "ACCEPT":
            record.agreement_state = AgreementState.CONFIRMED.value
            if latest_proposal is not None and latest_proposal.revised_terms:
                record.terms = latest_proposal.revised_terms
            if latest_proposal is not None:
                latest_proposal.status = "ACCEPTED"
                latest_proposal.updated_at = _now()
            event_type = CoreEventType.COMMITMENT_CONFIRMED.value
        else:
            record.agreement_state = AgreementState.REJECTED.value
            record.recovery_state = RecoveryState.RECOVERY_REQUIRED.value
            if latest_proposal is not None:
                latest_proposal.status = "REJECTED"
                latest_proposal.updated_at = _now()
            event_type = CoreEventType.COMMITMENT_PROPOSAL_REJECTED.value

        record.commitment_version += 1
        record.updated_at = _now()
        record.evidence_refs = list(dict.fromkeys([*record.evidence_refs, *request.evidence_refs]))
        new_state = _commitment_snapshot(record)

        causation_id = request.causation_id or context.causation_id
        audit = self._audit(
            context=context,
            commitment_id=commitment_id,
            event_type=event_type,
            dimension="agreement",
            previous_state=previous_state,
            new_state=new_state,
            evidence_refs=request.evidence_refs,
            reason=request.reason,
            occurred_at=record.updated_at,
            causation_id=causation_id,
        )
        event = self._outbox(
            context=context,
            event_id=_id("evt"),
            event_type=event_type,
            commitment_id=commitment_id,
            commitment_version=record.commitment_version,
            payload={
                "commitment_id": commitment_id,
                "proposal_id": request.proposal_id,
                "proposal_version": request.proposal_version,
                "decision": request.decision,
                "audit_id": audit.audit_id,
                "evidence_refs": request.evidence_refs,
            },
            occurred_at=record.updated_at,
            causation_id=causation_id,
        )
        if commit:
            try:
                db.add_all([audit, event])
                db.commit()
                db.refresh(record)
            except Exception:
                db.rollback()
                raise
        else:
            db.add_all([audit, event])
            db.flush()

        return CommitmentTransitionResponse(
            commitment=_to_commitment(record),
            audit_event=_to_audit(audit, role=context.actor_role),
            domain_event=_to_event(event),
        )

    def record_fulfilment(
        self,
        db: Session,
        context: RequestContext,
        commitment_id: str,
        request: RecordFulfilmentRequest,
        commit: bool = True,
    ) -> CommitmentTransitionResponse:
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

        if record.commitment_version != request.expected_commitment_version:
            raise DomainError(
                "COMMITMENT_VERSION_CONFLICT",
                "Commitment version is stale",
                status_code=409,
                details={"current_commitment_version": record.commitment_version},
            )

        if context.actor_role not in {"OWNER", "MANAGER"}:
            raise DomainError("APPROVAL_REQUIRED", "Manager or owner evidence is required for fulfilment", status_code=403)

        if not request.evidence_refs:
            raise DomainError("EVIDENCE_REQUIRED", "Operational fulfilment evidence is required", status_code=422)

        # Operational delivery evidence verification (BE-02h, UT-10, E2E-12)
        trusted_delivery = any(
            ref.startswith("ev_ops_delivery_")
            or ref.startswith("ev_pod_")
            or ref.startswith("ev_delivery_")
            or ref.startswith("ev_ops_")
            or ref.startswith("ev_shipping_")
            or "delivery" in ref.lower()
            or "delivered" in ref.lower()
            or "pod" in ref.lower()
            for ref in request.evidence_refs
        )
        is_only_receipt_or_msg = all(
            (
                ref.startswith("ev_receipt_")
                or ref.startswith("ev_msg_")
                or ref.startswith("ev_chat_")
                or ref.startswith("ev_ocr_")
                or "receipt" in ref.lower()
            )
            and not (
                "delivery" in ref.lower()
                or "delivered" in ref.lower()
                or "pod" in ref.lower()
                or "ops" in ref.lower()
            )
            for ref in request.evidence_refs
        )
        if not trusted_delivery or is_only_receipt_or_msg:
            raise DomainError(
                "INVALID_FULFILMENT_EVIDENCE",
                "Trusted operational delivery evidence (e.g. ev_ops_delivery_* or ev_pod_*) is required for fulfilment",
                status_code=422,
            )

        if record.agreement_state != AgreementState.CONFIRMED.value:
            raise DomainError(
                "INVALID_STATE_TRANSITION",
                f"Cannot record fulfilment for commitment with agreement state {record.agreement_state}; must be CONFIRMED",
                status_code=409,
            )

        if record.fulfilment_state == FulfilmentState.FULFILLED.value:
            raise DomainError(
                "INVALID_STATE_TRANSITION",
                "Commitment is already fulfilled",
                status_code=409,
            )

        previous_state = _commitment_snapshot(record)
        record.fulfilment_state = request.fulfilment_state
        if request.fulfilment_state == FulfilmentState.FULFILLED.value:
            record.risk_state = RiskState.RESOLVED.value
        record.commitment_version += 1
        record.updated_at = _now()
        record.evidence_refs = list(dict.fromkeys([*record.evidence_refs, *request.evidence_refs]))
        new_state = _commitment_snapshot(record)

        causation_id = request.causation_id or context.causation_id
        audit = self._audit(
            context=context,
            commitment_id=commitment_id,
            event_type=CoreEventType.COMMITMENT_FULFILMENT_VERIFIED.value,
            dimension="fulfilment",
            previous_state=previous_state,
            new_state=new_state,
            evidence_refs=request.evidence_refs,
            reason=request.reason,
            occurred_at=record.updated_at,
            causation_id=causation_id,
        )
        event = self._outbox(
            context=context,
            event_id=_id("evt"),
            event_type=CoreEventType.COMMITMENT_FULFILMENT_VERIFIED.value,
            commitment_id=commitment_id,
            commitment_version=record.commitment_version,
            payload={
                "commitment_id": commitment_id,
                "fulfilment_state": request.fulfilment_state,
                "audit_id": audit.audit_id,
                "evidence_refs": request.evidence_refs,
            },
            occurred_at=record.updated_at,
            causation_id=causation_id,
        )
        if commit:
            try:
                db.add_all([audit, event])
                db.commit()
                db.refresh(record)
            except Exception:
                db.rollback()
                raise
        else:
            db.add_all([audit, event])
            db.flush()

        return CommitmentTransitionResponse(
            commitment=_to_commitment(record),
            audit_event=_to_audit(audit, role=context.actor_role),
            domain_event=_to_event(event),
        )

    def assess(
        self,
        db: Session,
        context: RequestContext,
        commitment_id: str,
        assessment: FeasibilityAssessment,
        commit: bool = True,
    ) -> Commitment:
        # 1. Caller Authorization Guard: only trusted internal/service principal is permitted (D-013)
        if context.actor_role not in {"SERVICE", "SYSTEM"}:
            raise DomainError(
                "CALLER_NOT_AUTHORIZED",
                f"Actor '{context.actor_id}' with role '{context.actor_role}' is not authorized to invoke internal assessment writer; trusted service principal required",
                status_code=403,
            )

        # 2. Identity Guard: Assessment tenant must match authenticated context tenant
        if assessment.tenant_id != context.tenant_id:
            raise DomainError(
                "TENANT_MISMATCH",
                f"Assessment tenant_id '{assessment.tenant_id}' does not match authenticated context tenant '{context.tenant_id}'",
                status_code=400,
            )

        # 3. Identity Guard: Assessment commitment_id must match target argument
        if assessment.commitment_id != commitment_id:
            raise DomainError(
                "COMMITMENT_ID_MISMATCH",
                f"Assessment commitment_id '{assessment.commitment_id}' does not match target commitment '{commitment_id}'",
                status_code=400,
            )

        # 4. Tenant Isolation: Load commitment strictly by (tenant_id, commitment_id)
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

        # 5. Idempotency Guard: if assessment_id has already been applied, return without duplicate mutation/audit
        if assessment.assessment_id in record.evidence_refs:
            return _to_commitment(record)

        # 6. Concurrency Guard: check commitment_version against expected version
        if assessment.commitment_version != record.commitment_version:
            raise DomainError(
                "COMMITMENT_VERSION_CONFLICT",
                f"Assessment commitment version {assessment.commitment_version} does not match current commitment version {record.commitment_version}",
                status_code=409,
                details={"current_commitment_version": record.commitment_version},
            )

        previous_state = _commitment_snapshot(record)
        record.feasibility_state = assessment.status.value
        new_evidence = [assessment.assessment_id, *assessment.evidence_refs]
        record.evidence_refs = list(dict.fromkeys([*record.evidence_refs, *new_evidence]))

        causation_id = context.causation_id
        if record.agreement_state == AgreementState.CONFIRMED.value and assessment.status == FeasibilityState.INFEASIBLE:
            is_new_risk_edge = (previous_state["risk_state"] != RiskState.AT_RISK.value)
            record.risk_state = RiskState.AT_RISK.value
            record.recovery_state = RecoveryState.RECOVERY_REQUIRED.value
            record.commitment_version += 1
            record.updated_at = _now()
            assessment_state = {
                **_commitment_snapshot(record),
                "assessment_id": assessment.assessment_id,
                "snapshot_version": assessment.snapshot_version,
                "feasibility_state": assessment.status.value,
                "constraints": [
                    c.model_dump(mode="json") if hasattr(c, "model_dump") else c
                    for c in assessment.constraints
                ],
                "affected_commitment_ids": assessment.affected_commitment_ids,
                "evidence_refs": assessment.evidence_refs,
                "assessed_at": _aware(assessment.assessed_at).isoformat(),
            }
            new_state = assessment_state

            if is_new_risk_edge:
                # Single-edge risk transition: emit COMMITMENT_AT_RISK only on edge entering AT_RISK
                audit = self._audit(
                    context=context,
                    commitment_id=commitment_id,
                    event_type=CoreEventType.COMMITMENT_AT_RISK.value,
                    dimension="risk",
                    previous_state=previous_state,
                    new_state=new_state,
                    evidence_refs=assessment.evidence_refs,
                    reason=f"Assessment {assessment.assessment_id} evaluated INFEASIBLE on confirmed commitment",
                    occurred_at=record.updated_at,
                    causation_id=causation_id,
                )
                event = self._outbox(
                    context=context,
                    event_id=_id("evt"),
                    event_type=CoreEventType.COMMITMENT_AT_RISK.value,
                    commitment_id=commitment_id,
                    commitment_version=record.commitment_version,
                    payload={
                        "commitment_id": commitment_id,
                        "assessment_id": assessment.assessment_id,
                        "snapshot_version": assessment.snapshot_version,
                        "constraints": [c.model_dump(mode="json") for c in assessment.constraints],
                        "affected_commitment_ids": assessment.affected_commitment_ids,
                    },
                    occurred_at=record.updated_at,
                    causation_id=causation_id,
                )
            else:
                # Repeated INFEASIBLE during active risk episode updates state without duplicate at_risk outbox event
                audit = self._audit(
                    context=context,
                    commitment_id=commitment_id,
                    event_type=CoreEventType.COMMITMENT_LIFECYCLE_CHANGED.value,
                    dimension="feasibility",
                    previous_state=previous_state,
                    new_state=new_state,
                    evidence_refs=assessment.evidence_refs,
                    reason=f"Subsequent assessment {assessment.assessment_id} evaluated INFEASIBLE while already AT_RISK",
                    occurred_at=record.updated_at,
                    causation_id=causation_id,
                )
                event = self._outbox(
                    context=context,
                    event_id=_id("evt"),
                    event_type=CoreEventType.COMMITMENT_LIFECYCLE_CHANGED.value,
                    commitment_id=commitment_id,
                    commitment_version=record.commitment_version,
                    payload={
                        "commitment_id": commitment_id,
                        "assessment_id": assessment.assessment_id,
                        "feasibility_state": "INFEASIBLE",
                    },
                    occurred_at=record.updated_at,
                    causation_id=causation_id,
                )
        elif assessment.status == FeasibilityState.UNKNOWN:
            record.commitment_version += 1
            record.updated_at = _now()
            new_state = {
                **_commitment_snapshot(record),
                "assessment_id": assessment.assessment_id,
                "snapshot_version": assessment.snapshot_version,
                "feasibility_state": assessment.status.value,
                "constraints": [
                    c.model_dump(mode="json") if hasattr(c, "model_dump") else c
                    for c in assessment.constraints
                ],
                "affected_commitment_ids": assessment.affected_commitment_ids,
                "evidence_refs": assessment.evidence_refs,
                "assessed_at": _aware(assessment.assessed_at).isoformat(),
            }

            audit = self._audit(
                context=context,
                commitment_id=commitment_id,
                event_type=CoreEventType.COMMITMENT_LIFECYCLE_CHANGED.value,
                dimension="feasibility",
                previous_state=previous_state,
                new_state=new_state,
                evidence_refs=assessment.evidence_refs,
                reason=f"Assessment {assessment.assessment_id} evaluated UNKNOWN feasibility; evaluation pending",
                occurred_at=record.updated_at,
                causation_id=causation_id,
            )
            event = self._outbox(
                context=context,
                event_id=_id("evt"),
                event_type=CoreEventType.COMMITMENT_LIFECYCLE_CHANGED.value,
                commitment_id=commitment_id,
                commitment_version=record.commitment_version,
                payload={
                    "commitment_id": commitment_id,
                    "assessment_id": assessment.assessment_id,
                    "feasibility_state": "UNKNOWN",
                },
                occurred_at=record.updated_at,
                causation_id=causation_id,
            )
        else:
            if assessment.status == FeasibilityState.FEASIBLE and record.risk_state == RiskState.AT_RISK.value:
                record.risk_state = RiskState.RESOLVED.value
                record.recovery_state = RecoveryState.COMPLETED.value
            record.commitment_version += 1
            record.updated_at = _now()
            new_state = {
                **_commitment_snapshot(record),
                "assessment_id": assessment.assessment_id,
                "snapshot_version": assessment.snapshot_version,
                "feasibility_state": assessment.status.value,
                "constraints": [
                    c.model_dump(mode="json") if hasattr(c, "model_dump") else c
                    for c in assessment.constraints
                ],
                "affected_commitment_ids": assessment.affected_commitment_ids,
                "evidence_refs": assessment.evidence_refs,
                "assessed_at": _aware(assessment.assessed_at).isoformat(),
            }

            audit = self._audit(
                context=context,
                commitment_id=commitment_id,
                event_type=CoreEventType.COMMITMENT_LIFECYCLE_CHANGED.value,
                dimension="feasibility",
                previous_state=previous_state,
                new_state=new_state,
                evidence_refs=assessment.evidence_refs,
                reason=f"Assessment {assessment.assessment_id} evaluated {assessment.status.value}",
                occurred_at=record.updated_at,
                causation_id=causation_id,
            )
            event = self._outbox(
                context=context,
                event_id=_id("evt"),
                event_type=CoreEventType.COMMITMENT_LIFECYCLE_CHANGED.value,
                commitment_id=commitment_id,
                commitment_version=record.commitment_version,
                payload={
                    "commitment_id": commitment_id,
                    "assessment_id": assessment.assessment_id,
                    "feasibility_state": assessment.status.value,
                },
                occurred_at=record.updated_at,
                causation_id=causation_id,
            )

        if commit:
            try:
                db.add_all([audit, event])
                db.commit()
                db.refresh(record)
            except Exception:
                db.rollback()
                raise
        else:
            db.add_all([audit, event])
            db.flush()

        return _to_commitment(record)

    def record_advisory_assessment(
        self,
        db: Session,
        context: RequestContext,
        assessment: FeasibilityAssessment,
        commit: bool = True,
    ) -> AuditEvent:
        """Record an advisory or pre-commitment feasibility assessment (D-033).

        Advisory assessments are append-only audit rows and NEVER mutate the
        authoritative CommitmentRecord or touch CommitmentTerms.
        """
        if context.actor_role not in {"SERVICE", "SYSTEM"}:
            raise DomainError(
                "CALLER_NOT_AUTHORIZED",
                f"Actor '{context.actor_id}' with role '{context.actor_role}' is not authorized to record advisory assessment; trusted service principal required",
                status_code=403,
            )
        if assessment.tenant_id != context.tenant_id:
            raise DomainError(
                "TENANT_MISMATCH",
                f"Assessment tenant_id '{assessment.tenant_id}' does not match context tenant '{context.tenant_id}'",
                status_code=400,
            )

        now = _now()
        audit = AuditEventRecord(
            audit_id=_id("aud"),
            tenant_id=assessment.tenant_id,
            commitment_id=assessment.commitment_id,
            event_type="commitment.advisory_feasibility_assessed",
            actor_id=context.actor_id,
            actor_role=context.actor_role,
            dimension="feasibility",
            previous_state=None,
            new_state={
                "advisory": True,
                "assessment_id": assessment.assessment_id,
                "status": assessment.status.value,
                "snapshot_version": assessment.snapshot_version,
                "commitment_version": assessment.commitment_version,
                "constraints": [c.model_dump(mode="json") for c in assessment.constraints],
                "affected_commitment_ids": assessment.affected_commitment_ids,
                "solver_status": assessment.solver_status,
                "assessed_at": assessment.assessed_at.isoformat(),
            },
            evidence_refs=assessment.evidence_refs,
            reason=f"Advisory feasibility assessed: {assessment.status.value}",
            occurred_at=now,
            causation_id=context.causation_id,
            correlation_id=context.correlation_id,
        )
        if commit:
            try:
                db.add(audit)
                db.commit()
                db.refresh(audit)
            except Exception:
                db.rollback()
                raise
        else:
            db.add(audit)
            db.flush()

        return _to_audit(audit, role=context.actor_role)

    def audit(self, db: Session, context: RequestContext, commitment_id: str | None) -> list[AuditEvent]:
        if commitment_id:
            commitment = db.get(CommitmentRecord, (context.tenant_id, commitment_id))
            if commitment is None:
                raise DomainError("COMMITMENT_NOT_FOUND", "Commitment not found", status_code=404)

        query = select(AuditEventRecord).where(AuditEventRecord.tenant_id == context.tenant_id)
        if commitment_id:
            query = query.where(AuditEventRecord.commitment_id == commitment_id)
        records = db.scalars(query.order_by(AuditEventRecord.occurred_at.asc())).all()
        return [_to_audit(record, role=context.actor_role) for record in records]

    def event(self, db: Session, context: RequestContext, event_id: str) -> DomainEvent:
        record = db.get(OutboxEventRecord, event_id)
        if record is None or record.tenant_id != context.tenant_id:
            raise DomainError("EVENT_NOT_FOUND", "Event not found", status_code=404)
        return _to_event(record)

    @staticmethod
    def _authorize_transition(
        context: RequestContext,
        dimension: str,
        target_state: str,
        evidence_refs: list[str],
    ) -> None:
        if dimension == "agreement" and target_state == "CONFIRMED":
            if context.actor_role not in {"OWNER", "MANAGER"}:
                raise DomainError("APPROVAL_REQUIRED", "Manager or owner approval is required", status_code=403)
            if not evidence_refs:
                raise DomainError("EVIDENCE_REQUIRED", "Confirmation evidence is required", status_code=422)
        if dimension == "fulfilment" and target_state == "FULFILLED":
            if context.actor_role not in {"OWNER", "MANAGER"}:
                raise DomainError("APPROVAL_REQUIRED", "Manager or owner evidence is required", status_code=403)
            if not evidence_refs:
                raise DomainError("EVIDENCE_REQUIRED", "Operational fulfilment evidence is required", status_code=422)
        if dimension == "recovery" and target_state in {"EXECUTING", "COMPLETED"}:
            if context.actor_role not in {"OWNER", "MANAGER"}:
                raise DomainError("APPROVAL_REQUIRED", "Manager or owner approval is required", status_code=403)

    @staticmethod
    def _event_type(dimension: str, target_state: str) -> str:
        if dimension == "agreement" and target_state == "OFFERED":
            return CoreEventType.COMMITMENT_PROPOSAL_OFFERED.value
        if dimension == "agreement" and target_state == "CONFIRMED":
            return CoreEventType.COMMITMENT_CONFIRMED.value
        if dimension == "risk" and target_state == "AT_RISK":
            return CoreEventType.COMMITMENT_AT_RISK.value
        if dimension == "risk" and target_state == "RESOLVED":
            return CoreEventType.COMMITMENT_RISK_RESOLVED.value
        if dimension == "fulfilment" and target_state == "FULFILLED":
            return CoreEventType.COMMITMENT_FULFILMENT_VERIFIED.value
        return CoreEventType.COMMITMENT_LIFECYCLE_CHANGED.value

    @staticmethod
    def _audit(
        *,
        context: RequestContext,
        commitment_id: str,
        event_type: str,
        dimension: str,
        previous_state: dict[str, object] | None,
        new_state: dict[str, object],
        evidence_refs: list[str],
        reason: str,
        occurred_at: datetime,
        causation_id: str | None = None,
    ) -> AuditEventRecord:
        return AuditEventRecord(
            audit_id=_id("audit"),
            tenant_id=context.tenant_id,
            commitment_id=commitment_id,
            event_type=event_type,
            actor_id=context.actor_id,
            actor_role=context.actor_role,
            dimension=dimension,
            previous_state=previous_state,
            new_state=new_state,
            evidence_refs=evidence_refs,
            reason=reason,
            correlation_id=context.correlation_id,
            causation_id=causation_id,
            occurred_at=occurred_at,
        )

    @staticmethod
    def _outbox(
        *,
        context: RequestContext,
        event_id: str,
        event_type: str,
        commitment_id: str,
        commitment_version: int,
        payload: dict[str, object],
        occurred_at: datetime,
        causation_id: str | None = None,
    ) -> OutboxEventRecord:
        return OutboxEventRecord(
            event_id=event_id,
            tenant_id=context.tenant_id,
            event_type=event_type,
            commitment_id=commitment_id,
            commitment_version=commitment_version,
            correlation_id=context.correlation_id,
            causation_id=causation_id,
            payload=payload,
            occurred_at=occurred_at,
            attempts=0,
            status=OutboxStatus.PENDING.value,
            last_error=None,
            next_retry_at=None,
        )

    # -------------------------------------------------------------------------
    # Section 4 Thin Alias Methods (R55, D-002)
    # -------------------------------------------------------------------------
    def request(
        self,
        db: Session,
        context: RequestContext,
        request: CommitmentCreateRequest,
        *,
        commit: bool = True,
    ) -> Commitment:
        """Alias for create_request matching Section 4 domain vocabulary."""
        return self.create_request(db, context, request, commit=commit)

    def offer(
        self,
        db: Session,
        context: RequestContext,
        commitment_id: str,
        request: ProposalCreateRequest,
        *,
        commit: bool = True,
    ) -> CommitmentTransitionResponse:
        """Alias for create_proposal matching Section 4 domain vocabulary."""
        return self.create_proposal(db, context, commitment_id, request, commit=commit)

    def confirm(
        self,
        db: Session,
        context: RequestContext,
        commitment_id: str,
        request: ProposalConfirmRequest,
        *,
        commit: bool = True,
    ) -> CommitmentTransitionResponse:
        """Alias for confirm_proposal matching Section 4 domain vocabulary."""
        return self.confirm_proposal(db, context, commitment_id, request, commit=commit)

    def verify_fulfilment(
        self,
        db: Session,
        context: RequestContext,
        commitment_id: str,
        request: RecordFulfilmentRequest,
        *,
        commit: bool = True,
    ) -> CommitmentTransitionResponse:
        """Alias for record_fulfilment matching Section 4 domain vocabulary."""
        return self.record_fulfilment(db, context, commitment_id, request, commit=commit)

    def mark_risk(
        self,
        db: Session,
        context: RequestContext,
        commitment_id: str,
        assessment: FeasibilityAssessment,
        *,
        commit: bool = True,
    ) -> Commitment:
        """Delegate for marking risk on a commitment matching Section 4 domain vocabulary."""
        return self.assess(db, context, commitment_id, assessment, commit=commit)

    def start_recovery(
        self,
        db: Session,
        context: RequestContext,
        commitment_id: str,
        *,
        expected_commitment_version: int,
        reason: str = "Recovery started",
        causation_id: str | None = None,
        commit: bool = True,
    ) -> CommitmentTransitionResponse:
        """Delegate for initiating recovery matching Section 4 domain vocabulary."""
        return self.transition(
            db,
            context,
            commitment_id,
            CommitmentTransitionRequest(
                dimension="recovery",
                target_state="PLANNING",
                expected_commitment_version=expected_commitment_version,
                reason=reason,
                causation_id=causation_id,
            ),
            commit=commit,
        )

    def record_action_outcome(
        self,
        db: Session,
        context: RequestContext,
        commitment_id: str,
        *,
        expected_commitment_version: int,
        dimension: str,
        target_state: str,
        reason: str,
        evidence_refs: list[str] | None = None,
        causation_id: str | None = None,
        commit: bool = True,
    ) -> CommitmentTransitionResponse:
        """Delegate for recording action outcome matching Section 4 domain vocabulary."""
        return self.transition(
            db,
            context,
            commitment_id,
            CommitmentTransitionRequest(
                dimension=dimension,
                target_state=target_state,
                expected_commitment_version=expected_commitment_version,
                reason=reason,
                evidence_refs=evidence_refs,
                causation_id=causation_id,
            ),
            commit=commit,
        )
