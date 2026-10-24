"""Read-only Core, Recovery and Mock communication evidence projection."""

from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.communication.models import (
    CommunicationRequestRecord,
    OutboundMessageRecord,
    SendAttemptRecord,
)
from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.models import AuditEventRecord, CommitmentRecord
from app.orders.status import CommitmentStatusPreview, read_status_preview
from app.orders.terms import ImmutableContract
from app.recovery.durable_actions import InternalRecoveryTaskRecord, RecoveryActionExecutionRecord
from app.recovery.persistence import RecoveryCaseRecord


class RecoveryEvidence(ImmutableContract):
    case_id: str
    case_status: str
    case_version: int
    execution_status: Literal["NOT_AVAILABLE", "IN_PROGRESS", "FAILED", "VERIFIED_INTERNAL_TASK", "UNVERIFIED"]
    execution_id: str | None = None
    receipt_ref: str | None = None


class CommunicationEvidence(ImmutableContract):
    communication_id: str
    request_status: str
    outbound_status: Literal["NOT_AVAILABLE", "QUEUED", "FAILED", "DELIVERY_UNKNOWN", "MOCK_PROVIDER_SENT", "UNVERIFIED"]
    outbound_id: str | None = None
    provider_receipt_ref: str | None = None
    customer_delivery: Literal["NOT_AVAILABLE"] = "NOT_AVAILABLE"
    customer_agreement: Literal["NOT_AVAILABLE"] = "NOT_AVAILABLE"


class OperationalEvidenceView(ImmutableContract):
    commitment_id: str
    core: CommitmentStatusPreview
    recovery: RecoveryEvidence | None
    communications: tuple[CommunicationEvidence, ...]
    actual_production: Literal["NOT_AVAILABLE"] = "NOT_AVAILABLE"
    actual_delivery: Literal["NOT_AVAILABLE"] = "NOT_AVAILABLE"
    integration_mode: Literal["MOCK"] = "MOCK"
    evidence_tier: Literal["DEMO-ONLY"] = "DEMO-ONLY"


def _recovery(db: Session, tenant_id: str, commitment_id: str) -> RecoveryEvidence | None:
    case = db.scalar(select(RecoveryCaseRecord).where(
        RecoveryCaseRecord.tenant_id == tenant_id,
        RecoveryCaseRecord.commitment_id == commitment_id,
    ).order_by(RecoveryCaseRecord.created_at.desc()).limit(1))
    if case is None:
        return None
    execution = db.scalar(select(RecoveryActionExecutionRecord).where(
        RecoveryActionExecutionRecord.tenant_id == tenant_id,
        RecoveryActionExecutionRecord.commitment_id == commitment_id,
    ).order_by(RecoveryActionExecutionRecord.created_at.desc()).limit(1))
    if execution is None:
        return RecoveryEvidence(case_id=case.case_id, case_status=case.status,
                                case_version=case.case_version, execution_status="NOT_AVAILABLE")
    status = execution.status if execution.status in {"IN_PROGRESS", "FAILED"} else "UNVERIFIED"
    receipt_ref = None
    if execution.status == "SUCCEEDED" and execution.task_id and execution.receipt_ref and execution.audit_id:
        task = db.get(InternalRecoveryTaskRecord, (tenant_id, execution.task_id))
        audit = db.get(AuditEventRecord, execution.audit_id)
        if (task is not None and task.commitment_id == commitment_id
                and task.plan_id == execution.plan_id and task.status == "OPEN"
                and audit is not None and audit.tenant_id == tenant_id
                and audit.commitment_id == commitment_id
                and audit.event_type == "recovery.internal_task_created"
                and audit.new_state.get("task_id") == execution.task_id
                and execution.receipt_ref in audit.evidence_refs):
            status = "VERIFIED_INTERNAL_TASK"
            receipt_ref = execution.receipt_ref
    return RecoveryEvidence(case_id=case.case_id, case_status=case.status,
                            case_version=case.case_version, execution_status=status,
                            execution_id=execution.execution_id, receipt_ref=receipt_ref)


def _communications(db: Session, tenant_id: str, commitment_id: str) -> tuple[CommunicationEvidence, ...]:
    requests = db.scalars(select(CommunicationRequestRecord).where(
        CommunicationRequestRecord.tenant_id == tenant_id,
        CommunicationRequestRecord.commitment_id == commitment_id,
    ).order_by(CommunicationRequestRecord.created_at.desc())).all()
    rows = []
    for request in requests:
        outbound = db.scalar(select(OutboundMessageRecord).where(
            OutboundMessageRecord.tenant_id == tenant_id,
            OutboundMessageRecord.communication_id == request.communication_id,
        ).order_by(OutboundMessageRecord.created_at.desc()).limit(1))
        if outbound is None:
            rows.append(CommunicationEvidence(communication_id=request.communication_id,
                                              request_status=request.request_status,
                                              outbound_status="NOT_AVAILABLE"))
            continue
        status = outbound.status if outbound.status in {"QUEUED", "FAILED", "DELIVERY_UNKNOWN"} else "UNVERIFIED"
        receipt = None
        if (outbound.status == "SENT" and outbound.provider_confirmed
                and outbound.provider_reference and outbound.provider_reference.startswith("mock_")
                and outbound.sent_at is not None):
            attempt = db.get(SendAttemptRecord, (tenant_id, outbound.outbound_id, 1))
            audits = db.scalars(select(AuditEventRecord).where(
                AuditEventRecord.tenant_id == tenant_id,
                AuditEventRecord.commitment_id == commitment_id,
                AuditEventRecord.event_type == "communication.mock_sent",
            )).all()
            if (attempt is not None and attempt.status == "SENT"
                    and attempt.provider_reference == outbound.provider_reference
                    and any(isinstance(audit.new_state, dict)
                            and audit.new_state.get("outbound_id") == outbound.outbound_id
                            and audit.new_state.get("provider_reference") == outbound.provider_reference
                            for audit in audits)):
                status = "MOCK_PROVIDER_SENT"
                receipt = outbound.provider_reference
        rows.append(CommunicationEvidence(communication_id=request.communication_id,
                                          request_status=request.request_status,
                                          outbound_status=status, outbound_id=outbound.outbound_id,
                                          provider_receipt_ref=receipt))
    return tuple(rows)


def read_operational_evidence(db: Session, context: RequestContext,
                              commitment_id: str) -> OperationalEvidenceView:
    if db.get(CommitmentRecord, (context.tenant_id, commitment_id)) is None:
        raise DomainError("COMMITMENT_NOT_FOUND", "Commitment was not found", status_code=404)
    return OperationalEvidenceView(
        commitment_id=commitment_id,
        core=read_status_preview(db, context, commitment_id),
        recovery=_recovery(db, context.tenant_id, commitment_id),
        communications=_communications(db, context.tenant_id, commitment_id),
    )
