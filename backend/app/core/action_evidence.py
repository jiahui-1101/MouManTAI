"""Core audit/outbox boundary for a verified synthetic internal task."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.models import AuditEventRecord, CommitmentRecord, OutboxEventRecord


def stage_verified_internal_task(
    db: Session, context: RequestContext, *, commitment_id: str,
    expected_commitment_version: int, plan_id: str, approval_id: str,
    task_id: str, receipt_ref: str,
) -> str:
    """Record evidence without treating task creation as fulfilment or resolution."""
    row = db.scalar(select(CommitmentRecord).where(
        CommitmentRecord.tenant_id == context.tenant_id,
        CommitmentRecord.commitment_id == commitment_id,
    ).with_for_update())
    if row is None:
        raise DomainError("COMMITMENT_NOT_FOUND", "Commitment was not found", status_code=404)
    if row.commitment_version != expected_commitment_version:
        raise DomainError("COMMITMENT_VERSION_CONFLICT", "Action source version is stale", status_code=409)
    now = datetime.now(timezone.utc)
    audit_id = f"aud_{uuid4().hex[:16]}"
    db.add(AuditEventRecord(
        audit_id=audit_id, tenant_id=context.tenant_id, commitment_id=commitment_id,
        event_type="recovery.internal_task_created", actor_id=context.actor_id,
        actor_role=context.actor_role, dimension="recovery",
        previous_state={"commitment_version": row.commitment_version,
                        "recovery_state": row.recovery_state},
        new_state={"commitment_version": row.commitment_version,
                   "recovery_state": row.recovery_state,
                   "plan_id": plan_id, "approval_id": approval_id, "task_id": task_id},
        evidence_refs=[receipt_ref, approval_id],
        reason="Verified synthetic internal review task created; customer terms unchanged",
        correlation_id=context.correlation_id, causation_id=context.causation_id,
        occurred_at=now,
    ))
    db.add(OutboxEventRecord(
        event_id=f"evt_{uuid4().hex[:16]}", tenant_id=context.tenant_id,
        event_type="recovery.internal_task_created", commitment_id=commitment_id,
        commitment_version=row.commitment_version, correlation_id=context.correlation_id,
        causation_id=context.causation_id, occurred_at=now,
        payload={"plan_id": plan_id, "approval_id": approval_id,
                 "task_id": task_id, "audit_id": audit_id, "receipt_ref": receipt_ref},
        status="PENDING", attempts=0,
    ))
    return audit_id


def stage_failed_internal_task(
    db: Session, context: RequestContext, *, commitment_id: str,
    plan_id: str, execution_id: str, error_code: str,
) -> str:
    """Record a failed attempt without altering Commitment business state."""
    now = datetime.now(timezone.utc)
    audit_id = f"aud_{uuid4().hex[:16]}"
    db.add(AuditEventRecord(
        audit_id=audit_id, tenant_id=context.tenant_id, commitment_id=commitment_id,
        event_type="recovery.internal_task_failed", actor_id=context.actor_id,
        actor_role=context.actor_role, dimension="recovery",
        previous_state={"plan_id": plan_id},
        new_state={"plan_id": plan_id, "execution_id": execution_id,
                   "status": "FAILED", "error_code": error_code},
        evidence_refs=[], reason="Synthetic internal task attempt failed",
        correlation_id=context.correlation_id, causation_id=context.causation_id,
        occurred_at=now,
    ))
    return audit_id
