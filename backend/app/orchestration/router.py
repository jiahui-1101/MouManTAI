"""Registered reference-only APIs for the synthetic orchestration projection."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext, get_db, get_request_context
from app.core.errors import DomainError
from app.feasibility.persisted_sources import SupplierDelayEventRecord

from .models import BusinessImpactLinkRecord
from .schemas import CommitmentTimelineView, ImpactResolutionView, NotificationIntentView
from .service import (
    commitment_timeline,
    list_notification_intents,
    notification_intent,
    resolve_impact_links,
)

router = APIRouter(prefix="/v1/orchestration", tags=["business orchestration v1"])
Context = Annotated[RequestContext, Depends(get_request_context)]
Db = Annotated[Session, Depends(get_db)]


@router.post("/impacts/{impact_id}/resolve", response_model=ImpactResolutionView)
def resolve_persisted_impact(impact_id: str, context: Context, db: Db) -> ImpactResolutionView:
    """Materialize evidence-backed links for an existing persisted P2 impact."""
    if context.actor_role not in {"OWNER", "MANAGER"}:
        raise DomainError("FORBIDDEN", "Owner or Manager role is required to record an impact linkage review", status_code=403)
    result = resolve_impact_links(db, context, impact_id)
    db.commit()
    return result


@router.get("/impacts/{impact_id}", response_model=ImpactResolutionView)
def get_impact_links(impact_id: str, context: Context, db: Db) -> ImpactResolutionView:
    event_rows = db.scalars(select(SupplierDelayEventRecord).where(
        SupplierDelayEventRecord.tenant_id == context.tenant_id,
        SupplierDelayEventRecord.impact_id == impact_id,
    )).all()
    if len(event_rows) != 1:
        raise DomainError("IMPACT_NOT_FOUND", "Persisted P2 impact was not found", status_code=404)
    from app.feasibility.impact import ImpactAssessment

    try:
        impact = ImpactAssessment.model_validate(event_rows[0].impact_payload)
    except Exception as exc:
        raise DomainError("P2_IMPACT_CORRUPT", "Persisted P2 impact is invalid", status_code=500) from exc
    if impact.tenant_id != context.tenant_id:
        raise DomainError("TENANT_SCOPE_MISMATCH", "Impact tenant does not match request", status_code=403)
    rows = db.scalars(select(BusinessImpactLinkRecord).where(
        BusinessImpactLinkRecord.tenant_id == context.tenant_id,
        BusinessImpactLinkRecord.impact_id == impact_id,
    ).order_by(BusinessImpactLinkRecord.commitment_id)).all()
    from app.orchestration.service import _link_view
    links = [_link_view(row) for row in rows]
    unresolved = (
        not impact.discovery_complete
        or not impact.impacts
        or len(rows) != len(impact.impacts)
        or any(item.link_status.startswith("UNRESOLVED") for item in links)
    )
    return ImpactResolutionView(
        tenant_id=context.tenant_id, impact_id=impact_id, event_id=event_rows[0].event_id,
        discovery_complete=impact.discovery_complete,
        overall_status="UNRESOLVED_HUMAN_REVIEW" if unresolved else "LINKED",
        links=links,
    )


@router.get("/commitments/{commitment_id}/timeline", response_model=CommitmentTimelineView)
def get_commitment_timeline(commitment_id: str, context: Context, db: Db) -> CommitmentTimelineView:
    return commitment_timeline(db, context, commitment_id)


@router.get("/commitments/{commitment_id}/notification-intents",
            response_model=list[NotificationIntentView])
def get_commitment_notification_intents(
    commitment_id: str, context: Context, db: Db,
) -> list[NotificationIntentView]:
    return list_notification_intents(db, context, commitment_id)


@router.get("/notification-intents/{intent_id}", response_model=NotificationIntentView)
def get_notification_intent(intent_id: str, context: Context, db: Db) -> NotificationIntentView:
    return notification_intent(db, context, intent_id)
