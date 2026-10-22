from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from .dependencies import RequestContext, get_db, get_request_context
from .errors import DomainError
from .integration import CoreIntegrationFacade
from .reservations import get_resource_snapshot, reserve_resource
from .schemas import (
    AuditEvent,
    BusinessContext,
    Commitment,
    CommitmentCreateRequest,
    CommitmentTransitionRequest,
    CommitmentTransitionResponse,
    DomainEvent,
    OverviewResponse,
    ProposalConfirmRequest,
    ProposalCreateRequest,
    RecordFulfilmentRequest,
    RecoveryExecuteRequest,
    RecoveryStartRequest,
    ResourceReservationRequest,
    ResourceReservationResponse,
    ResourceStockResponse,
    TimelineEntry,
)
from .service import CommitmentService


router = APIRouter(prefix="/v1", tags=["commitments"])
service = CommitmentService()
facade = CoreIntegrationFacade(service=service)
Db = Annotated[Session, Depends(get_db)]
Context = Annotated[RequestContext, Depends(get_request_context)]


class RecoveryExecutionAuthority(Protocol):
    """Verify trusted actor identity and durable, current, scoped plan approval."""

    def verify(
        self,
        db: Session,
        context: RequestContext,
        commitment_id: str,
        request: RecoveryExecuteRequest,
    ) -> None: ...


def get_recovery_execution_authority() -> RecoveryExecutionAuthority | None:
    # No production durable-approval authority is wired yet. Fail closed.
    return None


ExecutionAuthority = Annotated[RecoveryExecutionAuthority | None, Depends(get_recovery_execution_authority)]


@router.get("/overview", response_model=OverviewResponse)
def get_overview_endpoint(db: Db, context: Context) -> OverviewResponse:
    return service.overview(db, context)


@router.post("/commitments", response_model=Commitment, status_code=status.HTTP_201_CREATED)
def create_commitment(request: CommitmentCreateRequest, db: Db, context: Context) -> Commitment:
    return service.create_request(db, context, request)


@router.get("/commitments", response_model=list[Commitment])
def list_commitments(db: Db, context: Context) -> list[Commitment]:
    return service.list(db, context)


@router.get("/commitments/{commitment_id}", response_model=Commitment)
def get_commitment(commitment_id: str, db: Db, context: Context) -> Commitment:
    return service.get(db, context, commitment_id)


@router.get("/commitments/{commitment_id}/timeline", response_model=list[TimelineEntry])
def get_commitment_timeline(commitment_id: str, db: Db, context: Context) -> list[TimelineEntry]:
    return service.timeline(db, context, commitment_id)


@router.post(
    "/commitments/{commitment_id}/proposals",
    response_model=CommitmentTransitionResponse,
)
def create_proposal(
    commitment_id: str,
    request: ProposalCreateRequest,
    db: Db,
    context: Context,
) -> CommitmentTransitionResponse:
    return service.create_proposal(db, context, commitment_id, request)


@router.post(
    "/commitments/{commitment_id}/confirm-proposal",
    response_model=CommitmentTransitionResponse,
)
def confirm_proposal(
    commitment_id: str,
    request: ProposalConfirmRequest,
    db: Db,
    context: Context,
) -> CommitmentTransitionResponse:
    return service.confirm_proposal(db, context, commitment_id, request)


@router.post(
    "/commitments/{commitment_id}/record-fulfilment",
    response_model=CommitmentTransitionResponse,
)
def record_fulfilment(
    commitment_id: str,
    request: RecordFulfilmentRequest,
    db: Db,
    context: Context,
) -> CommitmentTransitionResponse:
    return service.record_fulfilment(db, context, commitment_id, request)




@router.post(
    "/integration/context-updated",
    response_model=Commitment,
)
def context_updated_endpoint(
    business_context: BusinessContext,
    db: Db,
    context: Context,
) -> Commitment:
    return facade.handle_context_updated(db, context, business_context)


@router.post(
    "/commitments/{commitment_id}/recovery/start",
    response_model=CommitmentTransitionResponse,
)
def start_recovery_endpoint(
    commitment_id: str,
    request: RecoveryStartRequest,
    db: Db,
    context: Context,
) -> CommitmentTransitionResponse:
    return facade.start_recovery(db, context, commitment_id, request)


@router.post(
    "/commitments/{commitment_id}/recovery/execute",
    response_model=CommitmentTransitionResponse,
)
def execute_recovery_endpoint(
    commitment_id: str,
    request: RecoveryExecuteRequest,
    db: Db,
    context: Context,
    authority: ExecutionAuthority,
) -> CommitmentTransitionResponse:
    facade.authorize(context.actor_id, context.actor_role, "EXECUTE_PLAN", request.plan.plan_version)
    if request.plan.tenant_id != context.tenant_id or request.plan.commitment_id != commitment_id:
        raise DomainError("RECOVERY_SCOPE_MISMATCH", "Recovery plan scope does not match request", status_code=403)
    if authority is None:
        raise DomainError(
            "EXECUTION_APPROVAL_UNAVAILABLE",
            "Trusted actor identity and durable plan approval are not configured for public execution",
            status_code=503,
        )
    authority.verify(db, context, commitment_id, request)
    return facade.execute_recovery_plan(db, context, commitment_id, request)


@router.patch("/commitments/{commitment_id}")
def reject_unrestricted_patch(commitment_id: str) -> None:
    raise DomainError(
        "UNRESTRICTED_PATCH_FORBIDDEN",
        "Direct PATCH on commitments is forbidden; use typed transition/proposal/fulfilment endpoints",
        status_code=405,
    )


@router.post(
    "/commitments/{commitment_id}/transitions",
    response_model=CommitmentTransitionResponse,
)
def transition_commitment(
    commitment_id: str,
    request: CommitmentTransitionRequest,
    db: Db,
    context: Context,
) -> CommitmentTransitionResponse:
    return service.transition(db, context, commitment_id, request)


@router.get("/audit", response_model=list[AuditEvent])
def get_audit(
    db: Db,
    context: Context,
    commitment_id: str | None = Query(default=None),
) -> list[AuditEvent]:
    return service.audit(db, context, commitment_id)


@router.get("/events/{event_id}", response_model=DomainEvent)
def get_event(event_id: str, db: Db, context: Context) -> DomainEvent:
    return service.event(db, context, event_id)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


@router.get("/resources/snapshot", response_model=list[ResourceStockResponse])
def get_resource_snapshot_endpoint(
    db: Db,
    context: Context,
    resource_id: str | None = Query(default=None),
) -> list[ResourceStockResponse]:
    snapshots = get_resource_snapshot(db, context.tenant_id, [resource_id] if resource_id else None)
    return [
        ResourceStockResponse(
            tenant_id=context.tenant_id,
            resource_id=s.resource_id,
            total_quantity=s.total_quantity,
            reserved_quantity=s.reserved_quantity,
            available_quantity=s.available_quantity,
            unit=s.unit,
            snapshot_version=s.snapshot_version,
            updated_at=_aware(s.updated_at),
        )
        for s in snapshots
    ]


@router.post(
    "/resources/reserve",
    response_model=ResourceReservationResponse,
    status_code=status.HTTP_201_CREATED,
)
def reserve_resource_endpoint(
    request: ResourceReservationRequest,
    db: Db,
    context: Context,
) -> ResourceReservationResponse:
    reservation = reserve_resource(
        db,
        tenant_id=context.tenant_id,
        commitment_id=request.commitment_id,
        plan_id=request.plan_id,
        action_id=request.action_id,
        idempotency_key=request.idempotency_key,
        resource_id=request.resource_id,
        quantity=request.quantity,
        actor_id=context.actor_id,
    )
    return ResourceReservationResponse(
        reservation_id=reservation.reservation_id,
        tenant_id=reservation.tenant_id,
        commitment_id=reservation.commitment_id,
        plan_id=reservation.plan_id,
        action_id=reservation.action_id,
        idempotency_key=reservation.idempotency_key,
        resource_id=reservation.resource_id,
        quantity=reservation.quantity,
        status=reservation.status,
        created_at=_aware(reservation.created_at),
    )
