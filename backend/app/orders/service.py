"""Transaction-bound request import and human review for isolated Mock evidence."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.models import OutboxEventRecord
from app.orders.models import MockOrderSourceRecord, OrderRequestAuditRecord, OrderRequestRecord
from app.orders.terms import OrderTerms


def _now() -> datetime:
    return datetime.now(UTC)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _source_and_terms(db: Session, tenant_id: str, source_id: str, now: datetime) -> tuple[MockOrderSourceRecord, OrderTerms]:
    source = db.get(MockOrderSourceRecord, (tenant_id, source_id))
    if source is None:
        raise DomainError("MOCK_SOURCE_NOT_FOUND", "Mock source not found", status_code=404)
    if source.status != "CURRENT" or not (_utc(source.observed_at) <= now < _utc(source.valid_through)):
        raise DomainError("MOCK_SOURCE_STALE", "Mock source is expired or revoked", status_code=409)
    try:
        terms = OrderTerms.model_validate(source.terms)
    except ValueError as exc:
        raise DomainError("MOCK_SOURCE_INVALID", "Mock source terms are invalid", status_code=409) from exc
    if (terms.tenant_id != tenant_id or terms.customer_id != source.customer_id
            or source.customer_request_ref not in terms.evidence_refs
            or source.price_disclosure_ref not in terms.price_source.evidence_refs
            or source.price_disclosure_ref not in terms.evidence_refs):
        raise DomainError("MOCK_SOURCE_INVALID", "Mock source binding is invalid", status_code=409)
    return source, terms


def _event(db: Session, context: RequestContext, row: OrderRequestRecord,
           event_type: str, reason: str, now: datetime, *,
           additional_evidence_refs: tuple[str, ...] = (),
           reservation_operation_id: str | None = None) -> None:
    refs = list(dict.fromkeys([*row.source_evidence_refs, *additional_evidence_refs]))
    audit_id = f"aud_{uuid4().hex}"
    db.add(OrderRequestAuditRecord(
        audit_id=audit_id, tenant_id=row.tenant_id, order_request_id=row.order_request_id,
        event_type=event_type, actor_id=context.actor_id, request_version=row.request_version,
        evidence_refs=refs, reason=reason, occurred_at=now,
    ))
    db.add(OutboxEventRecord(
        event_id=f"evt_{uuid4().hex}", tenant_id=row.tenant_id, event_type=event_type,
        commitment_id=None, commitment_version=None, correlation_id=context.correlation_id,
        causation_id=context.causation_id, occurred_at=now,
        payload={"order_request_id": row.order_request_id, "request_version": row.request_version,
                 "status": row.decision_status, "audit_id": audit_id, "integration_mode": "MOCK",
                 "reservation_operation_id": reservation_operation_id},
        published_at=None, attempts=0, status="PENDING", last_error=None, next_retry_at=None,
    ))


def import_request(db: Session, context: RequestContext, source_id: str,
                   expected_source_version: int) -> OrderRequestRecord:
    now = _now()
    source, terms = _source_and_terms(db, context.tenant_id, source_id, now)
    if source.source_version != expected_source_version:
        raise DomainError("STALE_SOURCE_VERSION", "Mock source version changed", status_code=409)
    row = db.get(OrderRequestRecord, (context.tenant_id, terms.order_request_id))
    if row is not None:
        if (row.source_id, row.source_version, row.terms_hash) != (
                source_id, source.source_version, terms.terms_hash):
            raise DomainError("ORDER_REQUEST_CONFLICT", "Request already exists with different source terms", status_code=409)
        return row
    row = OrderRequestRecord(
        tenant_id=context.tenant_id, order_request_id=terms.order_request_id,
        customer_id=source.customer_id, source_id=source_id, source_version=source.source_version,
        source_observed_at=source.observed_at, source_valid_through=source.valid_through,
        source_evidence_refs=list(dict.fromkeys((source.customer_request_ref,
                                                 source.price_disclosure_ref, *terms.evidence_refs))),
        terms=terms.model_dump(mode="json"), terms_hash=terms.terms_hash, request_version=1,
        decision_status="PENDING", review_actor_id=None, review_reason=None, commitment_id=None,
        created_at=now, updated_at=now,
    )
    try:
        db.add(row)
        _event(db, context, row, "order.request_imported", "Controlled Mock source imported", now)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return row


def get_request(db: Session, context: RequestContext, order_request_id: str,
                *, lock: bool = False) -> OrderRequestRecord:
    statement = select(OrderRequestRecord).where(
        OrderRequestRecord.tenant_id == context.tenant_id,
        OrderRequestRecord.order_request_id == order_request_id,
    )
    row = db.scalar(statement.with_for_update() if lock else statement)
    if row is None:
        raise DomainError("ORDER_REQUEST_NOT_FOUND", "Order request not found", status_code=404)
    return row


def review_request(db: Session, context: RequestContext, order_request_id: str,
                   expected_request_version: int, decision: str, reason: str) -> OrderRequestRecord:
    row = get_request(db, context, order_request_id, lock=True)
    if row.request_version != expected_request_version:
        raise DomainError("STALE_REQUEST_VERSION", "Request version changed", status_code=409)
    if row.decision_status != "PENDING":
        raise DomainError("INVALID_REQUEST_STATE", "Only pending requests may be reviewed", status_code=409)
    source, terms = _source_and_terms(db, context.tenant_id, row.source_id, _now())
    if (source.source_version != row.source_version or terms.terms_hash != row.terms_hash
            or terms.model_dump(mode="json") != row.terms):
        raise DomainError("STALE_SOURCE_VERSION", "Mock source changed since import", status_code=409)
    now = _now()
    row.decision_status = decision
    row.request_version += 1
    row.review_actor_id = context.actor_id
    row.review_reason = reason
    row.updated_at = now
    try:
        _event(db, context, row, "order.request_reviewed" if decision == "REVIEWED"
               else "order.request_rejected", reason, now)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return row
