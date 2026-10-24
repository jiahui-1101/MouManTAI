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
from app.integrations.business_ports import ReservationReceipt
from app.orders.models import MockOrbyteReservationRecord, OrderRequestRecord
from app.orders.terms import ImmutableContract, Text


class CommitmentStatusPreview(ImmutableContract):
    commitment_id: Text
    commitment_version: int
    agreement_state: Text
    fulfilment_state: Text
    customer_status: Literal["REQUEST_RECEIVED", "CHANGE_PROPOSED", "REJECTED", "CANCELLED",
                             "ORDER_ACCEPTANCE_UNVERIFIED", "ORDER_ACCEPTED",
                             "COMPLETION_VERIFICATION_PENDING", "COMPLETED"]
    acceptance_verified: bool = False
    fulfilment_verified: bool
    evidence_refs: tuple[Text, ...]
    updated_at: AwareDatetime
    integration_mode: Literal["SYNTHETIC", "MOCK"] = "SYNTHETIC"
    evidence_tier: Literal["DEMO-ONLY"] = "DEMO-ONLY"


def read_status_preview(db: Session, context: RequestContext, commitment_id: str) -> CommitmentStatusPreview:
    record = db.get(CommitmentRecord, (context.tenant_id, commitment_id))
    if record is None:
        raise DomainError("COMMITMENT_NOT_FOUND", "Commitment was not found", status_code=404)
    status = {"REQUESTED": "REQUEST_RECEIVED", "OFFERED": "CHANGE_PROPOSED",
              "REJECTED": "REJECTED", "CANCELLED": "CANCELLED"}.get(
                  record.agreement_state, "ORDER_ACCEPTANCE_UNVERIFIED")
    acceptance_verified = False
    integration_mode = "SYNTHETIC"
    if record.agreement_state == "CONFIRMED":
        request = db.scalar(select(OrderRequestRecord).where(
            OrderRequestRecord.tenant_id == context.tenant_id,
            OrderRequestRecord.commitment_id == commitment_id,
            OrderRequestRecord.decision_status == "ACCEPTED",
        ))
        if request is not None and isinstance(record.terms, dict):
            reservation = db.scalar(select(MockOrbyteReservationRecord).where(
                MockOrbyteReservationRecord.tenant_id == context.tenant_id,
                MockOrbyteReservationRecord.order_request_id == request.order_request_id,
                MockOrbyteReservationRecord.status == "CONFIRMED",
            ))
            audit = db.scalar(select(AuditEventRecord).where(
                AuditEventRecord.tenant_id == context.tenant_id,
                AuditEventRecord.commitment_id == commitment_id,
                AuditEventRecord.event_type == "commitment.mock_order_accepted",
            ))
            if reservation is not None and audit is not None:
                try:
                    receipt = ReservationReceipt.model_validate(reservation.receipt)
                    acceptance_verified = (
                        receipt.mode == "MOCK" and receipt.reservation_confirmed
                        and receipt.tenant_id == context.tenant_id
                        and receipt.order_request_id == request.order_request_id
                        and receipt.terms_hash == request.terms_hash == record.terms.get("mock_terms_hash")
                        and receipt.request_version == record.terms.get("mock_order_request_version")
                        and audit.new_state.get("reservation_operation_id") == receipt.operation_id
                        and audit.actor_role in {"OWNER", "MANAGER"}
                        and set(receipt.evidence_refs) <= set(record.evidence_refs)
                    )
                except ValueError:
                    acceptance_verified = False
                if acceptance_verified:
                    status = "ORDER_ACCEPTED"
                    integration_mode = "MOCK"
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
        customer_status=status, acceptance_verified=acceptance_verified,
        fulfilment_verified=bool(evidence), evidence_refs=evidence,
        updated_at=record.updated_at if record.updated_at.tzinfo else record.updated_at.replace(tzinfo=UTC),
        integration_mode=integration_mode,
    )
