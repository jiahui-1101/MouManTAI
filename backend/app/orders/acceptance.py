"""SME approval -> fresh P2 -> atomic Mock reservation -> Core acceptance."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.service import CommitmentService
from app.integrations.business_ports import ReservationCommand, ReservationReceipt
from app.integrations.mock_orbyte import MockOrbyteAdapter
from app.orders.mock_feasibility import project_pending_order
from app.orders.models import MockOrbyteReservationRecord, OrderRequestRecord
from app.orders.service import _event, _now, _source_and_terms, get_request
from app.orders.terms import OrderTerms, require_exact_terms


def accept_mock_order(db: Session, context: RequestContext, order_request_id: str, *,
                      expected_request_version: int, expected_terms_hash: str,
                      expected_snapshot_version: int, idempotency_key: str,
                      reason: str) -> tuple[OrderRequestRecord, ReservationReceipt]:
    """All local Mock effects commit together; no external atomicity is claimed."""
    row = get_request(db, context, order_request_id, lock=True)
    previous = db.scalar(select(MockOrbyteReservationRecord).where(
        MockOrbyteReservationRecord.tenant_id == context.tenant_id,
        MockOrbyteReservationRecord.idempotency_key == idempotency_key,
    ))
    if previous is not None:
        if (previous.order_request_id != order_request_id
                or previous.request_version != expected_request_version
                or previous.terms_hash != expected_terms_hash
                or previous.snapshot_version != expected_snapshot_version):
            raise DomainError("IDEMPOTENCY_CONFLICT", "Key already belongs to another command", status_code=409)
        if (row.decision_status == "ACCEPTED" and row.commitment_id == f"com_{order_request_id}"
                and previous.status == "CONFIRMED"):
            return row, ReservationReceipt.model_validate(previous.receipt)
        if row.decision_status == "RESERVATION_UNKNOWN" and previous.status == "UNKNOWN":
            return row, ReservationReceipt.model_validate(previous.receipt)
        if previous.status == "FAILED":
            failed_receipt = ReservationReceipt.model_validate(previous.receipt)
            if f"mock-orbyte:rejected:{failed_receipt.operation_id}" in failed_receipt.evidence_refs:
                return row, failed_receipt
            raise DomainError("IDEMPOTENCY_KEY_RETIRED", "Reconciled operation requires a new key",
                              status_code=409)
        raise DomainError("RESERVATION_RECONCILIATION_REQUIRED", "Reservation outcome needs reconciliation",
                          status_code=409)
    if row.request_version != expected_request_version:
        raise DomainError("STALE_REQUEST_VERSION", "Request version changed", status_code=409)
    if row.decision_status != "REVIEWED":
        raise DomainError("REVIEW_REQUIRED", "Human review must precede SME acceptance", status_code=409)
    if row.terms_hash != expected_terms_hash:
        raise DomainError("TERMS_MISMATCH", "Exact reviewed terms are required", status_code=409)
    source, current_terms = _source_and_terms(db, context.tenant_id, row.source_id, _now())
    if source.source_version != row.source_version:
        raise DomainError("STALE_SOURCE_VERSION", "Mock customer source changed", status_code=409)
    stored_terms = OrderTerms.model_validate(row.terms)
    require_exact_terms(stored_terms, current_terms, tenant_id=context.tenant_id,
                        expected_revision=stored_terms.terms_revision,
                        expected_terms_hash=expected_terms_hash)
    if stored_terms.model_dump(mode="json") != current_terms.model_dump(mode="json"):
        raise DomainError("TERMS_MISMATCH", "Source evidence changed", status_code=409)
    adapter = MockOrbyteAdapter(db)
    state, snapshot = adapter.read_state(context.tenant_id, lock=True)
    if state.snapshot_version != expected_snapshot_version:
        raise DomainError("STALE_RESOURCE_VERSION", "Mock resource snapshot changed", status_code=409)
    now = _now()
    commitment_id = f"com_{order_request_id}"
    projected, assessment = project_pending_order(
        snapshot, stored_terms, commitment_id=commitment_id, checked_at=now,
    )
    command = ReservationCommand(
        tenant_id=context.tenant_id, order_request_id=order_request_id,
        request_version=row.request_version, terms=stored_terms,
        snapshot_id=snapshot.operational.snapshot_id,
        snapshot_version=snapshot.operational.snapshot_version,
        assessment_id=assessment.assessment_id, idempotency_key=idempotency_key,
    )
    try:
        receipt = adapter.reserve_resources(command, projected=projected, assessment=assessment,
                                            actor_id=context.actor_id, approval_reason=reason)
        if receipt.status == "UNKNOWN":
            row.decision_status = "RESERVATION_UNKNOWN"
            row.request_version += 1
            row.updated_at = now
            _event(db, context, row, "order.reservation_unknown", reason, now,
                   additional_evidence_refs=receipt.evidence_refs,
                   reservation_operation_id=receipt.operation_id)
            db.commit()
            return row, receipt
        if receipt.status == "FAILED":
            _event(db, context, row, "order.reservation_rejected", reason, now,
                   additional_evidence_refs=receipt.evidence_refs,
                   reservation_operation_id=receipt.operation_id)
            db.commit()
            return row, receipt
        CommitmentService().create_accepted_mock_order(
            db, context, commitment_id=commitment_id, terms=stored_terms,
            request_version=row.request_version, receipt=receipt,
            reservation_command=command, assessment=assessment,
            source_evidence_refs=row.source_evidence_refs, reason=reason,
        )
        row.decision_status = "ACCEPTED"
        row.request_version += 1
        row.commitment_id = commitment_id
        row.updated_at = now
        _event(db, context, row, "order.request_accepted", reason, now,
               additional_evidence_refs=receipt.evidence_refs,
               reservation_operation_id=receipt.operation_id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return row, receipt


def reconcile_mock_order(db: Session, context: RequestContext, order_request_id: str,
                         operation_id: str) -> tuple[OrderRequestRecord, ReservationReceipt]:
    row = get_request(db, context, order_request_id, lock=True)
    if row.decision_status != "RESERVATION_UNKNOWN":
        raise DomainError("RECONCILIATION_NOT_REQUIRED", "Request is not awaiting reconciliation",
                          status_code=409)
    operation = db.get(MockOrbyteReservationRecord, operation_id)
    if operation is None or operation.tenant_id != context.tenant_id or operation.order_request_id != order_request_id:
        raise DomainError("MOCK_RESERVATION_NOT_FOUND", "Mock reservation not found", status_code=404)
    adapter = MockOrbyteAdapter(db)
    try:
        receipt = adapter.reconcile_unknown(context.tenant_id, operation_id)
        if receipt.status != "FAILED":
            raise DomainError("MOCK_RECONCILIATION_UNSAFE", "Reservation may have had an effect",
                              status_code=409)
        row.decision_status = "REVIEWED"
        row.request_version += 1
        row.updated_at = _now()
        _event(db, context, row, "order.reservation_reconciled", "Mock confirmed no resource effect",
               row.updated_at, additional_evidence_refs=receipt.evidence_refs,
               reservation_operation_id=receipt.operation_id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return row, receipt
