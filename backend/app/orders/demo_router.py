"""Opt-in synthetic reads. Header identity is a demo identity, never live auth."""
import os
from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import ACTOR_ROLES, RequestContext, get_db, get_request_context
from app.core.feasibility_adapters import AuthoritativeAssessmentHistoryReader
from app.core.schemas import FeasibilityAssessment
from app.core.service import CommitmentService
from app.core.errors import DomainError
from app.orders.demo_data import DemoContract, DemoDataset, DemoOrder, load_demo_dataset


def demo_context(context: Annotated[RequestContext, Depends(get_request_context)]) -> RequestContext:
    if (os.getenv("ENVIRONMENT", "").lower() in {"production", "prod"}
            or os.getenv("MOUMANTAI_ORDERS_DEMO") != "1"
            or os.getenv("MOUMANTAI_SYNTHETIC_MODE") != "1"):
        raise DomainError("ORDERS_DEMO_DISABLED", "Explicit non-production orders demo required", status_code=503)
    if (context.tenant_id != "tenant_demo_01" or context.actor_id not in ACTOR_ROLES
            or context.actor_role not in {"OWNER", "MANAGER", "STAFF"}):
        raise DomainError("FORBIDDEN", "Demo tenant and recognized human actor required", status_code=403)
    return context


Context = Annotated[RequestContext, Depends(demo_context)]
router = APIRouter(prefix="/v1/demo/orders", tags=["synthetic orders read-only"])


class DemoQueue(DemoDataset):
    actor_id: str
    read_authorized: Literal[True] = True


@router.get("", response_model=DemoQueue)
def queue(context: Context) -> DemoQueue:
    data = load_demo_dataset()
    return DemoQueue(**data.model_dump(), actor_id=context.actor_id)


class DemoWindow(DemoContract):
    from_date: date
    to_exclusive: date
    time_zone: str


class DemoCalendar(DemoQueue):
    window: DemoWindow


@router.get("/planning/calendar", response_model=DemoCalendar)
def calendar(context: Context, from_date: date, to_exclusive: date,
             time_zone: str = "Asia/Kuala_Lumpur") -> DemoCalendar:
    if not 0 < (to_exclusive - from_date).days <= 370:
        raise DomainError("INVALID_WINDOW", "Calendar requires a positive window of at most 370 days", status_code=422)
    try:
        zone = ZoneInfo(time_zone)
    except (ZoneInfoNotFoundError, ValueError):
        raise DomainError("INVALID_TIME_ZONE", "An IANA business timezone is required", status_code=422)
    data = load_demo_dataset()
    rows = tuple(o for o in data.orders if from_date <= o.requested_delivery_at.astimezone(zone).date() < to_exclusive)
    return DemoCalendar(**{**data.model_dump(), "orders": rows}, actor_id=context.actor_id,
                        window=DemoWindow(from_date=from_date, to_exclusive=to_exclusive, time_zone=time_zone))


class RelatedCommitment(DemoContract):
    commitment_id: str
    order_id: str
    tenant_id: str
    customer_id: str
    version: int
    agreement_state: str
    risk_state: str
    recovery_state: str
    evidence_refs: list[str]


class DemoDetail(DemoContract):
    tenant_id: str
    actor_id: str
    integration_mode: Literal["SYNTHETIC"] = "SYNTHETIC"
    evidence_tier: Literal["DEMO-ONLY"] = "DEMO-ONLY"
    source_at: str
    source: str
    order: DemoOrder
    related_commitment: RelatedCommitment | None = None
    assessment_availability: Literal["UNAVAILABLE", "UNVERIFIABLE", "HISTORICAL_ONLY"]
    assessment_reason: str
    assessments: list[FeasibilityAssessment]


def find_order(order_id: str) -> tuple[DemoDataset, DemoOrder]:
    data = load_demo_dataset()
    order = next((o for o in data.orders if o.order_id == order_id), None)
    if order is None:
        raise DomainError("ORDER_NOT_FOUND", "Synthetic request not found", status_code=404)
    return data, order


@router.get("/{order_id}", response_model=DemoDetail)
def detail(order_id: str, context: Context, db: Annotated[Session, Depends(get_db)]) -> DemoDetail:
    data, order = find_order(order_id)
    related = None
    assessments = []
    availability = "UNAVAILABLE"
    reason = "No persisted P2 assessment. Core feasibility labels are not assessment evidence."
    try:
        commitment = CommitmentService().get(db, context, order.commitment_id)
    except DomainError as exc:
        if exc.status_code != 404:
            raise
        reason = "Related Core commitment unavailable; fixture association is not verified."
    else:
        if commitment.order_id != order.order_id or commitment.tenant_id != context.tenant_id:
            raise DomainError("ORDER_LINK_MISMATCH", "Core association differs from synthetic request", status_code=409)
        related = RelatedCommitment(
            commitment_id=commitment.commitment_id, order_id=commitment.order_id,
            tenant_id=commitment.tenant_id, version=commitment.commitment_version,
            customer_id=commitment.customer_id,
            agreement_state=commitment.agreement_state.value, risk_state=commitment.risk_state.value,
            recovery_state=commitment.recovery_state.value, evidence_refs=commitment.evidence_refs,
        )
        try:
            assessments = AuthoritativeAssessmentHistoryReader().list_for_commitment(db, context, order.commitment_id)
        except DomainError as exc:
            if exc.status_code in {401, 403}:
                raise
            availability = "UNVERIFIABLE"
            reason = f"Persisted assessment provenance rejected: {exc.code}"
        else:
            if any(a.tenant_id != context.tenant_id or a.commitment_id != order.commitment_id for a in assessments):
                raise DomainError("ASSESSMENT_SCOPE_MISMATCH", "Assessment association differs", status_code=409)
            if assessments:
                availability = "HISTORICAL_ONLY"
                reason = "Commitment assessment history only; no verified request-version / current snapshot binding."
    return DemoDetail(tenant_id=context.tenant_id, actor_id=context.actor_id,
                      source_at=data.source_at.isoformat(), source=data.source, order=order,
                      related_commitment=related, assessments=assessments,
                      assessment_availability=availability, assessment_reason=reason)
