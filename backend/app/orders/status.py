"""Read-only diagnostic projection from existing Core state and audit.

Legacy CONFIRMED has no v2.2 order-acceptance receipt linkage. Never infer
ORDER_ACCEPTED from it. This is an internal synthetic preview, not a customer
status API; a verified customer/order link is still required before disclosure.
"""

from datetime import UTC
from typing import Literal

from pydantic import AwareDatetime
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.fulfilment_evidence import are_trusted_synthetic_delivery_refs
from app.core.models import AuditEventRecord, CommitmentRecord
from app.orders.terms import ImmutableContract, Text


class CommitmentStatusPreview(ImmutableContract):
    commitment_id: Text
    commitment_version: int
    agreement_state: Text
    fulfilment_state: Text
    customer_status: Literal["REQUEST_RECEIVED", "CHANGE_PROPOSED", "REJECTED", "CANCELLED",
                             "ORDER_ACCEPTANCE_UNVERIFIED", "COMPLETION_VERIFICATION_PENDING", "COMPLETED"]
    acceptance_verified: Literal[False] = False
    fulfilment_verified: bool
    evidence_refs: tuple[Text, ...]
    updated_at: AwareDatetime
    integration_mode: Literal["SYNTHETIC"] = "SYNTHETIC"
    evidence_tier: Literal["DEMO-ONLY"] = "DEMO-ONLY"


def read_status_preview(db: Session, context: RequestContext, commitment_id: str) -> CommitmentStatusPreview:
    record = db.get(CommitmentRecord, (context.tenant_id, commitment_id))
    if record is None:
        raise DomainError("COMMITMENT_NOT_FOUND", "Commitment was not found", status_code=404)
    status = {"REQUESTED": "REQUEST_RECEIVED", "OFFERED": "CHANGE_PROPOSED",
              "REJECTED": "REJECTED", "CANCELLED": "CANCELLED"}.get(
                  record.agreement_state, "ORDER_ACCEPTANCE_UNVERIFIED")
    evidence: tuple[str, ...] = ()
    if record.fulfilment_state == "FULFILLED":
        audits = db.scalars(select(AuditEventRecord).where(
            AuditEventRecord.tenant_id == context.tenant_id,
            AuditEventRecord.commitment_id == commitment_id,
            AuditEventRecord.event_type == "commitment.fulfilment_verified",
            AuditEventRecord.dimension == "fulfilment",
        ).order_by(AuditEventRecord.occurred_at.desc())).all()
        for audit in audits:
            state = audit.new_state
            version = state.get("commitment_version") if isinstance(state, dict) else None
            if (isinstance(version, int) and not isinstance(version, bool)
                    and 1 <= version <= record.commitment_version
                    and state.get("fulfilment_state") == "FULFILLED"
                    and are_trusted_synthetic_delivery_refs(audit.evidence_refs,
                                                           tenant_id=context.tenant_id,
                                                           commitment_id=commitment_id)
                    and set(audit.evidence_refs) <= set(record.evidence_refs)):
                evidence = tuple(audit.evidence_refs)
                break
        status = "COMPLETED" if evidence else "COMPLETION_VERIFICATION_PENDING"
    elif record.fulfilment_state == "UNVERIFIED":
        status = "COMPLETION_VERIFICATION_PENDING"
    return CommitmentStatusPreview(
        commitment_id=record.commitment_id, commitment_version=record.commitment_version,
        agreement_state=record.agreement_state, fulfilment_state=record.fulfilment_state,
        customer_status=status, fulfilment_verified=bool(evidence), evidence_refs=evidence,
        updated_at=record.updated_at if record.updated_at.tzinfo else record.updated_at.replace(tzinfo=UTC),
    )
