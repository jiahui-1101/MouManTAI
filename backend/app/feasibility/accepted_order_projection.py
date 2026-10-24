"""Project verified accepted orders into P2's immutable operational snapshot.

Core remains the Commitment authority and Orders remains the accepted request
authority. P2 adds a derived demand row only when its own current production
plan supplies a fresh, exact schedule for that accepted Commitment.
"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.models import AuditEventRecord, CommitmentRecord, OutboxEventRecord
from app.feasibility.models import CommitmentLine, ConfirmedCommitment, SourceEvidence, SourceKind
from app.feasibility.persisted_sources import OperationalSnapshotRecord, _snapshot_from_record
from app.feasibility.production import EvaluationSnapshot
from app.integrations.business_ports import ReservationReceipt
from app.orders.models import MockOrbyteReservationRecord, OrderRequestRecord
from app.orders.status import read_status_preview
from app.orders.terms import OrderTerms


class AcceptedOrderProjection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["PROJECTED", "ALREADY_PROJECTED", "UNRESOLVED"]
    acceptance_event_id: str | None = None
    snapshot_id: str | None = None
    snapshot_version: int | None = None
    reason_codes: tuple[str, ...] = ()
    integration_mode: Literal["MOCK"] = "MOCK"
    evidence_tier: Literal["DEMO-ONLY"] = "DEMO-ONLY"


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _unresolved(*codes: str, event_id: str | None = None) -> AcceptedOrderProjection:
    return AcceptedOrderProjection(
        status="UNRESOLVED", acceptance_event_id=event_id, reason_codes=tuple(codes),
    )


def project_accepted_order(
    db: Session, context: RequestContext, order_request_id: str,
) -> AcceptedOrderProjection:
    """Consume the persisted acceptance event and append one P2 snapshot.

    The caller commits the transaction. Unavailable, stale or ambiguous P2
    schedules return an unresolved result and leave the current snapshot alone.
    Replaying the existing accept command safely retries this projection.
    """
    request = db.scalar(select(OrderRequestRecord).where(
        OrderRequestRecord.tenant_id == context.tenant_id,
        OrderRequestRecord.order_request_id == order_request_id,
    ))
    if request is None or request.decision_status != "ACCEPTED" or not request.commitment_id:
        return _unresolved("ACCEPTED_ORDER_REQUEST_UNAVAILABLE")

    commitment = db.scalar(select(CommitmentRecord).where(
        CommitmentRecord.tenant_id == context.tenant_id,
        CommitmentRecord.commitment_id == request.commitment_id,
    ).with_for_update().execution_options(populate_existing=True))
    if commitment is None or commitment.agreement_state != "CONFIRMED":
        return _unresolved("CORE_COMMITMENT_NOT_CONFIRMED")

    events = db.scalars(select(OutboxEventRecord).where(
        OutboxEventRecord.tenant_id == context.tenant_id,
        OutboxEventRecord.event_type == "commitment.mock_order_accepted",
        OutboxEventRecord.commitment_id == commitment.commitment_id,
    )).all()
    audits = db.scalars(select(AuditEventRecord).where(
        AuditEventRecord.tenant_id == context.tenant_id,
        AuditEventRecord.commitment_id == commitment.commitment_id,
        AuditEventRecord.event_type == "commitment.mock_order_accepted",
    )).all()
    reservations = db.scalars(select(MockOrbyteReservationRecord).where(
        MockOrbyteReservationRecord.tenant_id == context.tenant_id,
        MockOrbyteReservationRecord.order_request_id == order_request_id,
        MockOrbyteReservationRecord.status == "CONFIRMED",
    )).all()
    if len(events) != 1 or len(audits) != 1 or len(reservations) != 1:
        return _unresolved("ORDER_ACCEPTANCE_EVIDENCE_NOT_UNIQUE")
    event, audit, reservation = events[0], audits[0], reservations[0]
    try:
        receipt = ReservationReceipt.model_validate(reservation.receipt)
        terms = OrderTerms.model_validate(request.terms)
    except ValidationError:
        return _unresolved("ORDER_ACCEPTANCE_EVIDENCE_INVALID", event_id=event.event_id)

    payload = event.payload if isinstance(event.payload, dict) else {}
    core_terms = commitment.terms if isinstance(commitment.terms, dict) else {}
    if len(terms.items) != 1:
        return _unresolved("P2_ACCEPTED_ORDER_LINE_SHAPE_UNSUPPORTED", event_id=event.event_id)
    accepted_line = terms.items[0]
    try:
        core_deadline = datetime.fromisoformat(core_terms["deadline"])
        core_quantity_matches = str(terms.items[0].quantity) == str(core_terms["quantity"])
    except (KeyError, TypeError, ValueError):
        return _unresolved("CORE_ACCEPTED_TERMS_INVALID", event_id=event.event_id)

    if (
        terms.tenant_id != context.tenant_id
        or terms.order_request_id != order_request_id
        or terms.customer_id != request.customer_id
        or terms.terms_hash != request.terms_hash
        or request.commitment_id != commitment.commitment_id
        or commitment.order_id != order_request_id
        or commitment.customer_id != request.customer_id
        or commitment.commitment_version < 1
        or request.request_version != receipt.request_version + 1
        or commitment.agreement_state != "CONFIRMED"
        or core_terms.get("mock_terms_hash") != request.terms_hash
        or core_terms.get("mock_order_request_version") != receipt.request_version
        or not core_quantity_matches
        or core_terms.get("sku") != accepted_line.sku
        or core_terms.get("unit") != accepted_line.unit
        or _utc(core_deadline) != _utc(terms.window_end)
        or receipt.mode != "MOCK"
        or receipt.status != "CONFIRMED"
        or not receipt.reservation_confirmed
        or receipt.tenant_id != context.tenant_id
        or receipt.order_request_id != order_request_id
        or receipt.operation_id != reservation.operation_id
        or receipt.terms_hash != request.terms_hash
        or receipt.request_version != audit.new_state.get("request_version")
        or audit.new_state.get("order_request_id") != order_request_id
        or audit.new_state.get("terms_hash") != request.terms_hash
        or audit.new_state.get("reservation_operation_id") != receipt.operation_id
        or audit.new_state.get("commitment_version") != commitment.commitment_version
        or audit.actor_role not in {"OWNER", "MANAGER"}
        or audit.causation_id != receipt.operation_id
        or _utc(audit.occurred_at) != _utc(event.occurred_at)
        or audit.correlation_id != event.correlation_id
        or event.causation_id != receipt.operation_id
        or event.commitment_version != commitment.commitment_version
        or payload.get("commitment_id") != commitment.commitment_id
        or payload.get("order_request_id") != order_request_id
        or payload.get("reservation_operation_id") != receipt.operation_id
        or payload.get("audit_id") != audit.audit_id
        or payload.get("integration_mode") != "MOCK"
        or not set(receipt.evidence_refs) <= set(commitment.evidence_refs)
        or not set(request.source_evidence_refs) <= set(commitment.evidence_refs)
    ):
        return _unresolved("ORDER_ACCEPTANCE_EVIDENCE_BINDING_MISMATCH", event_id=event.event_id)
    try:
        if not read_status_preview(db, context, commitment.commitment_id).acceptance_verified:
            return _unresolved("ORDER_ACCEPTANCE_NOT_VERIFIED", event_id=event.event_id)
    except DomainError:
        return _unresolved("ORDER_ACCEPTANCE_NOT_VERIFIED", event_id=event.event_id)

    current_rows = db.scalars(select(OperationalSnapshotRecord).where(
        OperationalSnapshotRecord.tenant_id == context.tenant_id,
        OperationalSnapshotRecord.is_current.is_(True),
    ).with_for_update().execution_options(populate_existing=True)).all()
    if len(current_rows) != 1:
        return _unresolved("P2_OPERATIONAL_SNAPSHOT_UNAVAILABLE", event_id=event.event_id)
    current_record = current_rows[0]
    latest_version = db.scalar(select(func.max(OperationalSnapshotRecord.snapshot_version)).where(
        OperationalSnapshotRecord.tenant_id == context.tenant_id,
    ))
    if latest_version != current_record.snapshot_version:
        return _unresolved("P2_STAGED_SNAPSHOT_PENDING", event_id=event.event_id)
    try:
        current = _snapshot_from_record(current_record)
    except DomainError:
        return _unresolved("P2_OPERATIONAL_SNAPSHOT_INVALID", event_id=event.event_id)
    if (
        current.current_snapshot_version != current.operational.snapshot_version
        or current.operational.tenant_id != context.tenant_id
    ):
        return _unresolved("P2_OPERATIONAL_SNAPSHOT_VERSION_OR_TIME_MISMATCH", event_id=event.event_id)

    source_digest = sha256(f"{context.tenant_id}:{event.event_id}".encode()).hexdigest()[:24]
    projection_source_id = f"accepted-order-{source_digest}"
    prior_row = next((row for row in current.operational.confirmed_commitments
                      if row.commitment_id == commitment.commitment_id), None)
    if prior_row is not None:
        projection_provenance = next((row for row in current.operational.sources
                                      if row.source_id == projection_source_id), None)
        expected_evidence = {event.event_id, audit.audit_id, receipt.operation_id}
        expected_line = prior_row.lines[0] if len(prior_row.lines) == 1 else None
        current_plans = tuple(
            plan for plan in (current.production.plans if current.production is not None else ())
            if plan.commitment_id == commitment.commitment_id
        )
        current_sources = ({source.source_id: source for source in current.production.sources}
                           if current.production is not None else {})
        current_plan_sources = (
            tuple(current_sources.get(ref) for ref in current_plans[0].source_refs)
            if len(current_plans) == 1 else ()
        )
        now = datetime.now(UTC)
        schedule_is_current = (
            len(current_plans) == 1
            and current_plans[0].tenant_id == context.tenant_id
            and current_plans[0].commitment_version == commitment.commitment_version
            and _utc(current_plans[0].start_at) >= now
            and all(source is not None
                    and source.kind == "plans"
                    and source.tenant_id == context.tenant_id
                    and _utc(source.observed_at) <= now
                    and _utc(source.valid_through) >= now
                    for source in current_plan_sources)
            and bool(current_plan_sources)
        )
        schedule_matches_projection = (
            schedule_is_current
            and expected_line is not None
            and current_plans[0].line_id == expected_line.line_id
            and _utc(current_plans[0].start_at) == _utc(expected_line.material_use_at)
            and set(ref for source in current_plan_sources if source is not None
                    for ref in source.evidence_refs)
            <= set(projection_provenance.evidence_refs if projection_provenance else ())
        )
        if (
            prior_row.tenant_id == context.tenant_id
            and prior_row.commitment_version == commitment.commitment_version
            and _utc(prior_row.delivery_deadline) == _utc(terms.window_end)
            and expected_line is not None
            and expected_line.sku_id == accepted_line.sku
            and expected_line.quantity == accepted_line.quantity
            and expected_line.unit == accepted_line.unit
            and len(current_plans) == 1
            and current_plans[0].line_id == expected_line.line_id
            and prior_row.source_refs == (projection_source_id,)
            and projection_provenance is not None
            and expected_evidence <= set(projection_provenance.evidence_refs)
            and schedule_matches_projection
        ):
            return AcceptedOrderProjection(
                status="ALREADY_PROJECTED", acceptance_event_id=event.event_id,
                snapshot_id=current.operational.snapshot_id,
                snapshot_version=current.operational.snapshot_version,
            )
        if not schedule_is_current:
            return _unresolved("P2_SCHEDULE_STALE_OR_INVALID", event_id=event.event_id)
        if not schedule_matches_projection:
            return _unresolved("P2_SCHEDULE_CHANGED_AFTER_PROJECTION", event_id=event.event_id)
        return _unresolved("P2_COMMITMENT_PROJECTION_CONFLICT", event_id=event.event_id)

    if _utc(current.operational.captured_at) > _utc(event.occurred_at):
        return _unresolved("P2_SOURCE_CAPTURED_AFTER_ACCEPTANCE", event_id=event.event_id)
    production = current.production
    if production is None:
        return _unresolved("P2_SCHEDULING_EVIDENCE_MISSING", event_id=event.event_id)
    candidate_plans = tuple(
        plan for plan in production.plans if plan.commitment_id == commitment.commitment_id
    )
    if not candidate_plans:
        return _unresolved("P2_SCHEDULE_MISSING", event_id=event.event_id)
    if len(candidate_plans) != 1:
        return _unresolved("P2_SCHEDULE_AMBIGUOUS", event_id=event.event_id)
    plan = candidate_plans[0]
    if plan.tenant_id != context.tenant_id or plan.commitment_version != commitment.commitment_version:
        return _unresolved("P2_SCHEDULE_VERSION_MISMATCH", event_id=event.event_id)
    if (
        _utc(plan.start_at) < _utc(event.occurred_at)
        or _utc(plan.start_at) >= _utc(plan.dispatch_cutoff_at)
        or _utc(plan.dispatch_cutoff_at) > _utc(terms.window_end)
    ):
        return _unresolved("P2_SCHEDULE_STALE_OR_OUTSIDE_ACCEPTED_WINDOW", event_id=event.event_id)

    production_sources = {source.source_id: source for source in production.sources}
    schedule_sources = tuple(production_sources.get(ref) for ref in plan.source_refs)
    if any(source is None for source in schedule_sources):
        return _unresolved("P2_SCHEDULE_SOURCE_MISSING", event_id=event.event_id)
    if any(
        source.kind != "plans"
        or source.tenant_id != context.tenant_id
        or _utc(source.observed_at) > _utc(event.occurred_at)
        or _utc(source.valid_through) < _utc(event.occurred_at)
        for source in schedule_sources if source is not None
    ):
        return _unresolved("P2_SCHEDULE_STALE_OR_INVALID", event_id=event.event_id)

    try:
        source_refs = tuple(sorted({
            *request.source_evidence_refs,
            *receipt.evidence_refs,
            receipt.operation_id,
            audit.audit_id,
            event.event_id,
            *(ref for source in schedule_sources if source is not None for ref in source.evidence_refs),
        }))
        expiry = min(_utc(source.valid_through) for source in schedule_sources if source is not None)
        p2_commitment = ConfirmedCommitment(
            commitment_id=commitment.commitment_id,
            tenant_id=context.tenant_id,
            commitment_version=commitment.commitment_version,
            delivery_deadline=terms.window_end,
            lines=(CommitmentLine(
                line_id=plan.line_id,
                sku_id=accepted_line.sku,
                quantity=accepted_line.quantity,
                unit=accepted_line.unit,
                material_use_at=plan.start_at,
            ),),
            source_refs=(projection_source_id,),
        )
        operational_data = current.operational.model_dump(exclude_computed_fields=True)
        next_version = current_record.snapshot_version + 1
        snapshot_digest = sha256(f"{context.tenant_id}:{event.event_id}:v{next_version}".encode()).hexdigest()[:24]
        operational_data.update(
            snapshot_id=f"p2-accepted-{snapshot_digest}",
            snapshot_version=next_version,
            captured_at=_utc(event.occurred_at),
            sources=(*operational_data["sources"], SourceEvidence(
                source_id=projection_source_id,
                tenant_id=context.tenant_id,
                kind=SourceKind.CONFIRMED_COMMITMENTS,
                source_ref=f"synthetic://p2/accepted-order/{event.event_id}",
                observed_at=_utc(event.occurred_at),
                valid_through=expiry,
                evidence_refs=source_refs,
            )),
            confirmed_commitments=(*operational_data["confirmed_commitments"], p2_commitment),
        )
        snapshot_data = current.model_dump(exclude_computed_fields=True)
        snapshot_data.update(
            operational=operational_data,
            as_of=_utc(event.occurred_at),
            current_snapshot_version=next_version,
        )
        projected = EvaluationSnapshot.model_validate(snapshot_data)
    except (ValidationError, ValueError, TypeError):
        return _unresolved("P2_SNAPSHOT_SOURCE_VALIDATION_FAILED", event_id=event.event_id)

    # Do not silently resurrect a projection removed by a later P2 source
    # correction. A new explicit P2 lifecycle/refresh contract is needed.
    historical = db.scalars(select(OperationalSnapshotRecord).where(
        OperationalSnapshotRecord.tenant_id == context.tenant_id,
        OperationalSnapshotRecord.snapshot_version < current_record.snapshot_version,
    )).all()
    if any(
        projection_source_id in {
            source.get("source_id") for source in row.payload.get("operational", {}).get("sources", [])
            if isinstance(source, dict)
        }
        for row in historical
    ):
        return _unresolved("P2_PRIOR_PROJECTION_NOT_CURRENT", event_id=event.event_id)

    current_record.is_current = False
    db.flush()
    projected_record = OperationalSnapshotRecord(
        tenant_id=context.tenant_id,
        snapshot_version=projected.operational.snapshot_version,
        snapshot_id=projected.operational.snapshot_id,
        payload=projected.model_dump(mode="json", exclude_computed_fields=True),
        is_current=True,
        created_at=datetime.now(UTC),
    )
    db.add(projected_record)
    db.flush()
    return AcceptedOrderProjection(
        status="PROJECTED", acceptance_event_id=event.event_id,
        snapshot_id=projected.operational.snapshot_id,
        snapshot_version=projected.operational.snapshot_version,
    )
