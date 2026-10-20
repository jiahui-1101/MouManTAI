from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .dependencies import RequestContext
from .errors import DomainError
from .models import AuditEventRecord, CommitmentRecord, OutboxEventRecord
from .schemas import (
    AgreementState,
    AuditEvent,
    Commitment,
    CommitmentCreateRequest,
    CommitmentTransitionRequest,
    CommitmentTransitionResponse,
    DomainEvent,
    FeasibilityState,
    FulfilmentState,
    RecoveryState,
    RiskState,
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
    return Commitment.model_validate(
        {
            "tenant_id": record.tenant_id,
            "commitment_id": record.commitment_id,
            "order_id": record.order_id,
            "customer_id": record.customer_id,
            "terms": record.terms,
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


def _to_audit(record: AuditEventRecord) -> AuditEvent:
    return AuditEvent.model_validate(
        {
            "audit_id": record.audit_id,
            "tenant_id": record.tenant_id,
            "commitment_id": record.commitment_id,
            "event_type": record.event_type,
            "actor_id": record.actor_id,
            "actor_role": record.actor_role,
            "dimension": record.dimension,
            "previous_state": record.previous_state,
            "new_state": record.new_state,
            "evidence_refs": record.evidence_refs,
            "reason": record.reason,
            "correlation_id": record.correlation_id,
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
    def create_request(self, db: Session, context: RequestContext, request: CommitmentCreateRequest) -> Commitment:
        now = _now()
        commitment_id = _id("com")
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
            event_type="commitment.created",
            dimension="agreement",
            previous_state=None,
            new_state=_commitment_snapshot(record),
            evidence_refs=request.evidence_refs,
            reason="Commitment request created",
            occurred_at=now,
        )
        event = self._outbox(
            context=context,
            event_id=_id("evt"),
            event_type="commitment.created",
            commitment_id=commitment_id,
            commitment_version=1,
            payload={"commitment_id": commitment_id, "audit_id": audit.audit_id},
            occurred_at=now,
        )
        try:
            db.add_all([record, audit, event])
            db.commit()
            db.refresh(record)
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
            audit_event=_to_audit(audit),
            domain_event=_to_event(event),
        )

    def audit(self, db: Session, context: RequestContext, commitment_id: str | None) -> list[AuditEvent]:
        query = select(AuditEventRecord).where(AuditEventRecord.tenant_id == context.tenant_id)
        if commitment_id:
            query = query.where(AuditEventRecord.commitment_id == commitment_id)
        records = db.scalars(query.order_by(AuditEventRecord.occurred_at.asc())).all()
        return [_to_audit(record) for record in records]

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
        if dimension == "agreement" and target_state == "CONFIRMED":
            return "commitment.confirmed"
        if dimension == "risk" and target_state == "AT_RISK":
            return "commitment.at_risk"
        if dimension == "fulfilment" and target_state == "FULFILLED":
            return "commitment.fulfilment_verified"
        return "commitment.lifecycle_changed"

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
    ) -> OutboxEventRecord:
        return OutboxEventRecord(
            event_id=event_id,
            tenant_id=context.tenant_id,
            event_type=event_type,
            commitment_id=commitment_id,
            commitment_version=commitment_version,
            correlation_id=context.correlation_id,
            payload=payload,
            occurred_at=occurred_at,
            attempts=0,
        )
