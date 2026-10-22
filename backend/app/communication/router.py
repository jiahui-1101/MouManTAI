"""P4 routes. Application registration and trusted authority wiring remain P5-owned."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext, get_db, get_request_context

from .schemas import (
    CommunicationRequestView, CommunicationSummary, CreateCommunicationRequest, MessageDraftView,
    ApproveDraftRequest, DraftReviewView, PrepareDraftRequest, RejectDraftRequest, RequestStatus,
)
from .drafting import DraftAuthority, MessageDraftService
from .service import CommunicationRequestService, RequestAuthority
from .review import DraftReviewService, ReviewAuthority
from .authority_adapters import RuntimeDraftAuthority, RuntimeRequestAuthority, RuntimeReviewAuthority


router = APIRouter(prefix="/v1/communications", tags=["communications"])


def get_request_authority() -> RequestAuthority:
    return RuntimeRequestAuthority()


def get_draft_authority() -> DraftAuthority:
    return RuntimeDraftAuthority()


def get_review_authority() -> ReviewAuthority:
    return RuntimeReviewAuthority()


def get_review_service(
    db: Annotated[Session, Depends(get_db)],
    drafts: Annotated[DraftAuthority | None, Depends(get_draft_authority)],
    authority: Annotated[ReviewAuthority | None, Depends(get_review_authority)],
) -> DraftReviewService:
    return DraftReviewService(db, drafts, authority)


def get_draft_service(
    db: Annotated[Session, Depends(get_db)],
    authority: Annotated[DraftAuthority | None, Depends(get_draft_authority)],
) -> MessageDraftService:
    return MessageDraftService(db, authority)


def get_service(
    db: Annotated[Session, Depends(get_db)],
    authority: Annotated[RequestAuthority | None, Depends(get_request_authority)],
) -> CommunicationRequestService:
    return CommunicationRequestService(db, authority)


Service = Annotated[CommunicationRequestService, Depends(get_service)]
Context = Annotated[RequestContext, Depends(get_request_context)]
DraftService = Annotated[MessageDraftService, Depends(get_draft_service)]
ReviewService = Annotated[DraftReviewService, Depends(get_review_service)]


@router.get("/{communication_id}/drafts/{draft_id}/review", response_model=DraftReviewView)
def read_draft_review(communication_id: str, draft_id: str, service: ReviewService, context: Context):
    return service.get(context, communication_id, draft_id)


@router.post("/{communication_id}/drafts/{draft_id}/approve", response_model=DraftReviewView)
def approve_message_draft(communication_id: str, draft_id: str, command: ApproveDraftRequest,
                          service: ReviewService, context: Context):
    return service.approve(context, communication_id, draft_id, command)


@router.post("/{communication_id}/drafts/{draft_id}/reject", response_model=DraftReviewView)
def reject_message_draft(communication_id: str, draft_id: str, command: RejectDraftRequest,
                         service: ReviewService, context: Context):
    return service.reject(context, communication_id, draft_id, command)


@router.post("/{communication_id}/prepare", response_model=MessageDraftView)
def prepare_draft(
    communication_id: str, command: PrepareDraftRequest, service: DraftService, context: Context,
):
    return service.prepare(context, communication_id, command)


@router.get("/{communication_id}/drafts/{draft_id}", response_model=MessageDraftView)
def retrieve_draft(communication_id: str, draft_id: str, service: DraftService, context: Context):
    return service.get(context, communication_id, draft_id)


@router.post("/requests", response_model=CommunicationRequestView)
def create_request(command: CreateCommunicationRequest, service: Service, context: Context):
    # 200 denotes a persisted intake result (including idempotent replay), never a send.
    return service.create(context, command)


@router.get("", response_model=list[CommunicationRequestView])
def list_requests(
    service: Service, context: Context, commitment_id: str | None = None,
    request_status: RequestStatus | None = None,
):
    return service.list(context, commitment_id=commitment_id, request_status=request_status)


# Static path must precede the dynamic /{communication_id} route.
@router.get("/summary", response_model=CommunicationSummary)
def communication_summary(service: DraftService, context: Context):
    return service.summary(context)


@router.get("/{communication_id}", response_model=CommunicationRequestView)
def get_request(communication_id: str, service: Service, context: Context):
    return service.get(context, communication_id)
