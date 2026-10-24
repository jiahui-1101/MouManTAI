"""Database-backed P4 Orders API.

Queries persisted orders from PostgreSQL (p4_orders table).
Does not reload JSON fixtures at runtime.
Includes tenant isolation, human role checks, and safe Core commitment association.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import os
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import ACTOR_ROLES, RequestContext, get_db, get_request_context
from app.core.errors import DomainError
from app.core.feasibility_adapters import AuthoritativeAssessmentHistoryReader
from app.core.schemas import FeasibilityAssessment
from app.core.service import CommitmentService
from app.orders.models import P4OrderRecord


def orders_context(context: Annotated[RequestContext, Depends(get_request_context)]) -> RequestContext:
    if os.getenv("ENVIRONMENT", "").lower() in {"production", "prod"}:
        raise DomainError("SYNTHETIC_ORDERS_DISABLED", "Synthetic orders are disabled in production", status_code=503)
    if context.actor_id not in ACTOR_ROLES or context.actor_role not in {"OWNER", "MANAGER", "STAFF"}:
        raise DomainError("FORBIDDEN", "Recognized human actor role required", status_code=403)
    return context


Context = Annotated[RequestContext, Depends(orders_context)]
router = APIRouter(prefix="/v1/orders", tags=["orders-database-backed"])


class OrderContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OrderItemDto(OrderContract):
    sku: str = Field(min_length=1)
    quantity: str = Field(pattern=r"^[1-9][0-9]*$")
    unit: str = Field(min_length=1)


class OrderDto(OrderContract):
    order_id: str = Field(min_length=1)
    commitment_id: str = Field(min_length=1)
    customer_display_name: str = Field(min_length=1)
    requested_items: tuple[OrderItemDto, ...] = Field(min_length=1)
    requested_delivery_at: AwareDatetime
    received_at: AwareDatetime
    lifecycle_status: Literal["UNKNOWN"] = "UNKNOWN"
    source_channel: Literal["SYNTHETIC"] = "SYNTHETIC"
    evidence_refs: tuple[str, ...] = Field(min_length=1)


class OrdersQueueResponse(OrderContract):
    schema_version: Literal["orders-demo-v1"] = "orders-demo-v1"
    tenant_id: str
    actor_id: str
    read_authorized: Literal[True] = True
    integration_mode: Literal["SYNTHETIC"] = "SYNTHETIC"
    evidence_tier: Literal["DEMO-ONLY"] = "DEMO-ONLY"
    source: str
    source_at: AwareDatetime
    valid_until: AwareDatetime
    coverage: Literal["partial"] = "partial"
    orders: tuple[OrderDto, ...]


class CalendarWindowDto(OrderContract):
    from_date: date
    to_exclusive: date
    time_zone: str


class OrdersCalendarResponse(OrdersQueueResponse):
    window: CalendarWindowDto


class RelatedCommitmentDto(OrderContract):
    commitment_id: str
    order_id: str
    tenant_id: str
    customer_id: str
    version: int
    agreement_state: str
    risk_state: str
    recovery_state: str
    evidence_refs: list[str]


class OrderDetailResponse(OrderContract):
    tenant_id: str
    actor_id: str
    integration_mode: Literal["SYNTHETIC"] = "SYNTHETIC"
    evidence_tier: Literal["DEMO-ONLY"] = "DEMO-ONLY"
    source_at: str
    source: str
    order: OrderDto
    related_commitment: RelatedCommitmentDto | None = None
    assessment_availability: Literal["UNAVAILABLE", "UNVERIFIABLE", "HISTORICAL_ONLY"]
    assessment_reason: str
    assessments: list[FeasibilityAssessment]


def _ensure_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _record_to_dto(r: P4OrderRecord) -> OrderDto:
    items = tuple(
        OrderItemDto(
            sku=item["sku"],
            quantity=str(item["quantity"]),
            unit=item["unit"],
        )
        for item in r.requested_items
    )
    return OrderDto(
        order_id=r.order_id,
        commitment_id=r.commitment_id or f"com_{r.order_id}",
        customer_display_name=r.customer_display_name,
        requested_items=items,
        requested_delivery_at=_ensure_aware(r.requested_delivery_at),
        received_at=_ensure_aware(r.received_at),
        lifecycle_status="UNKNOWN",
        source_channel="SYNTHETIC",
        evidence_refs=tuple(r.evidence_refs),
    )


@router.get("", response_model=OrdersQueueResponse)
def list_orders(context: Context, db: Annotated[Session, Depends(get_db)]) -> OrdersQueueResponse:
    records = db.scalars(
        select(P4OrderRecord)
        .where(P4OrderRecord.tenant_id == context.tenant_id)
        .order_by(P4OrderRecord.received_at.asc(), P4OrderRecord.order_id.asc())
    ).all()

    now = datetime.now(timezone.utc)
    valid_until = now + timedelta(days=30)
    orders = tuple(_record_to_dto(r) for r in records)

    return OrdersQueueResponse(
        tenant_id=context.tenant_id,
        actor_id=context.actor_id,
        source="persisted://postgresql/p4_orders",
        source_at=now,
        valid_until=valid_until,
        orders=orders,
    )


@router.get("/planning/calendar", response_model=OrdersCalendarResponse)
def get_calendar(
    context: Context,
    from_date: date,
    to_exclusive: date,
    time_zone: str = "Asia/Kuala_Lumpur",
    db: Annotated[Session, Depends(get_db)] = None,
) -> OrdersCalendarResponse:
    if not 0 < (to_exclusive - from_date).days <= 370:
        raise DomainError("INVALID_WINDOW", "Calendar requires a positive window of at most 370 days", status_code=422)
    try:
        zone = ZoneInfo(time_zone)
    except (ZoneInfoNotFoundError, ValueError):
        raise DomainError("INVALID_TIME_ZONE", "An IANA business timezone is required", status_code=422)

    records = db.scalars(
        select(P4OrderRecord)
        .where(P4OrderRecord.tenant_id == context.tenant_id)
        .order_by(P4OrderRecord.requested_delivery_at.asc())
    ).all()

    rows = []
    for r in records:
        delivery_local = _ensure_aware(r.requested_delivery_at).astimezone(zone).date()
        if from_date <= delivery_local < to_exclusive:
            rows.append(_record_to_dto(r))

    now = datetime.now(timezone.utc)
    valid_until = now + timedelta(days=30)

    return OrdersCalendarResponse(
        tenant_id=context.tenant_id,
        actor_id=context.actor_id,
        source="persisted://postgresql/p4_orders",
        source_at=now,
        valid_until=valid_until,
        orders=tuple(rows),
        window=CalendarWindowDto(from_date=from_date, to_exclusive=to_exclusive, time_zone=time_zone),
    )


@router.get("/{order_id}", response_model=OrderDetailResponse)
def get_order_detail(
    order_id: str,
    context: Context,
    db: Annotated[Session, Depends(get_db)],
) -> OrderDetailResponse:
    record = db.scalars(
        select(P4OrderRecord).where(
            P4OrderRecord.tenant_id == context.tenant_id,
            P4OrderRecord.order_id == order_id,
        )
    ).first()

    if record is None:
        raise DomainError("ORDER_NOT_FOUND", f"Order {order_id} not found in persisted orders", status_code=404)

    order_dto = _record_to_dto(record)

    related = None
    assessments = []
    availability = "UNAVAILABLE"
    reason = "No persisted P2 assessment. Core feasibility labels are not assessment evidence."

    if record.commitment_id:
        try:
            commitment = CommitmentService().get(db, context, record.commitment_id)
        except DomainError as exc:
            if exc.status_code != 404:
                raise
            reason = "Related Core commitment unavailable; association is not verified."
        else:
            if commitment.order_id != order_dto.order_id or commitment.tenant_id != context.tenant_id:
                raise DomainError("ORDER_LINK_MISMATCH", "Core association differs from synthetic request", status_code=409)
            related = RelatedCommitmentDto(
                commitment_id=commitment.commitment_id,
                order_id=commitment.order_id,
                tenant_id=commitment.tenant_id,
                version=commitment.commitment_version,
                customer_id=commitment.customer_id,
                agreement_state=commitment.agreement_state.value,
                risk_state=commitment.risk_state.value,
                recovery_state=commitment.recovery_state.value,
                evidence_refs=commitment.evidence_refs,
            )
            try:
                assessments = AuthoritativeAssessmentHistoryReader().list_for_commitment(db, context, record.commitment_id)
            except DomainError as exc:
                if exc.status_code in {401, 403}:
                    raise
                availability = "UNVERIFIABLE"
                reason = f"Persisted assessment provenance rejected: {exc.code}"
            else:
                if any(a.tenant_id != context.tenant_id or a.commitment_id != record.commitment_id for a in assessments):
                    raise DomainError("ASSESSMENT_SCOPE_MISMATCH", "Assessment association differs", status_code=409)
                if assessments:
                    availability = "HISTORICAL_ONLY"
                    reason = "Commitment assessment history only; no verified request-version / current snapshot binding."

    now_iso = datetime.now(timezone.utc).isoformat()
    return OrderDetailResponse(
        tenant_id=context.tenant_id,
        actor_id=context.actor_id,
        source_at=now_iso,
        source="persisted://postgresql/p4_orders",
        order=order_dto,
        related_commitment=related,
        assessments=assessments,
        assessment_availability=availability,
        assessment_reason=reason,
    )
