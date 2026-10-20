from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from .dependencies import RequestContext, get_db, get_request_context
from .schemas import (
    AuditEvent,
    Commitment,
    CommitmentCreateRequest,
    CommitmentTransitionRequest,
    CommitmentTransitionResponse,
    DomainEvent,
)
from .service import CommitmentService


router = APIRouter(prefix="/v1", tags=["commitments"])
service = CommitmentService()
Db = Annotated[Session, Depends(get_db)]
Context = Annotated[RequestContext, Depends(get_request_context)]


@router.post("/commitments", response_model=Commitment, status_code=status.HTTP_201_CREATED)
def create_commitment(request: CommitmentCreateRequest, db: Db, context: Context) -> Commitment:
    return service.create_request(db, context, request)


@router.get("/commitments", response_model=list[Commitment])
def list_commitments(db: Db, context: Context) -> list[Commitment]:
    return service.list(db, context)


@router.get("/commitments/{commitment_id}", response_model=Commitment)
def get_commitment(commitment_id: str, db: Db, context: Context) -> Commitment:
    return service.get(db, context, commitment_id)


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
