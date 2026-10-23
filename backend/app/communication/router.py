"""P4 routes. Application registration and trusted authority wiring remain P5-owned."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header
import os
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext, get_db, get_request_context

from .schemas import (
    CommunicationRequestView, CommunicationSummary, CreateCommunicationRequest, MessageDraftView,
    ApproveDraftRequest, DraftReviewView, PrepareDraftRequest, RejectDraftRequest, RequestStatus,
)
from .drafting import DraftAuthority, MessageDraftService
from .service import CommunicationRequestService, RequestAuthority
from .review import DraftReviewService, ReviewAuthority
from .authority_adapters import (
    IsolatedRecoveryRequestAuthority, RuntimeDraftAuthority, RuntimeRequestAuthority, RuntimeReviewAuthority,
)
from .outbound import OutboundService, RuntimeSendAuthority, SendAuthority
from .providers import LocalMockProvider, OutboundProvider
from .schemas import OutboundMessageView, SendEligibility, SendMessageRequest
from .demo_policy import SyntheticScope
from .contacts import DirectoryContactAdapter, get_customer_directory
from .preferences import PreferenceCommand, PreferenceService, PreferenceView
from .synthetic_authorities import (
    SyntheticRequestAuthority, SyntheticDraftAuthority, SyntheticReviewAuthority,
    SyntheticSendAuthority, ConsentBoundDraftAuthority,
)


router = APIRouter(prefix="/v1/communications", tags=["communications"])


def get_trusted_authority(db=Depends(get_db), directory=Depends(get_customer_directory),
    x_isolated_e2e_key: str | None = Header(default=None), x_p4_processor_key: str | None = Header(default=None)):
    from .trusted_runtime import enabled, IsolatedPrincipal, PersistedCommunicationAuthority
    if enabled():
        return PersistedCommunicationAuthority(IsolatedPrincipal(db, x_isolated_e2e_key,
            processor_key=x_p4_processor_key), directory)
    return None


def get_request_authority(x_isolated_e2e_key: str | None = Header(default=None), trusted=Depends(get_trusted_authority)) -> RequestAuthority:
    from .trusted_runtime import PersistedCommunicationAuthority
    if isinstance(trusted, PersistedCommunicationAuthority):
        return trusted
    if os.getenv("MOUMANTAI_ISOLATED_E2E") == "1":
        return IsolatedRecoveryRequestAuthority(x_isolated_e2e_key)
    scope = SyntheticScope.from_environment()
    if scope.enabled:
        return SyntheticRequestAuthority(scope)
    return RuntimeRequestAuthority()


def get_draft_authority(directory=Depends(get_customer_directory), trusted=Depends(get_trusted_authority)) -> DraftAuthority:
    from .trusted_runtime import PersistedCommunicationAuthority
    if isinstance(trusted, PersistedCommunicationAuthority):
        return trusted
    scope = SyntheticScope.from_environment()
    if scope.enabled:
        return ConsentBoundDraftAuthority(SyntheticDraftAuthority(scope), scope, directory)
    return RuntimeDraftAuthority()


def get_review_authority(trusted=Depends(get_trusted_authority)) -> ReviewAuthority:
    from .trusted_runtime import PersistedCommunicationAuthority
    if isinstance(trusted, PersistedCommunicationAuthority):
        return trusted
    scope = SyntheticScope.from_environment()
    if scope.enabled:
        return SyntheticReviewAuthority(scope)
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
def get_communication_context(context=Depends(get_request_context), trusted=Depends(get_trusted_authority)):
    from .trusted_runtime import PersistedCommunicationAuthority
    if isinstance(trusted, PersistedCommunicationAuthority):
        trusted.principal.require(context, "READ_DRAFT")
    return context


Context = Annotated[RequestContext, Depends(get_communication_context)]
DraftService = Annotated[MessageDraftService, Depends(get_draft_service)]
ReviewService = Annotated[DraftReviewService, Depends(get_review_service)]


def get_send_authority(trusted=Depends(get_trusted_authority)) -> SendAuthority:
    from .trusted_runtime import PersistedCommunicationAuthority
    if isinstance(trusted, PersistedCommunicationAuthority):
        return trusted
    scope = SyntheticScope.from_environment()
    if scope.enabled:
        return SyntheticSendAuthority(scope)
    return RuntimeSendAuthority()


def get_outbound_provider() -> OutboundProvider:
    from .challenge_delivery import isolated_delivery_sink
    return LocalMockProvider(receipt_sink=isolated_delivery_sink())


def get_outbound_service(db: Annotated[Session, Depends(get_db)],
    drafts: Annotated[DraftAuthority | None, Depends(get_draft_authority)],
    reviews: Annotated[ReviewAuthority | None, Depends(get_review_authority)],
    authority: Annotated[SendAuthority, Depends(get_send_authority)],
    provider: Annotated[OutboundProvider, Depends(get_outbound_provider)]) -> OutboundService:
    from .trusted_runtime import PersistedCommunicationAuthority
    from .confirmation_authority import ExistingP4ConfirmationAuthority
    from .challenge_delivery import BoundChallengeDelivery
    challenge = (BoundChallengeDelivery(ExistingP4ConfirmationAuthority(drafts, reviews))
                 if isinstance(authority, PersistedCommunicationAuthority) else None)
    return OutboundService(db, drafts, reviews, authority, provider, challenge_delivery=challenge)


Outbound = Annotated[OutboundService, Depends(get_outbound_service)]


def get_preference_service(db: Annotated[Session, Depends(get_db)],
                           directory=Depends(get_customer_directory), trusted=Depends(get_trusted_authority)) -> PreferenceService:
    from .trusted_runtime import PersistedCommunicationAuthority, IsolatedPreferenceScope
    if isinstance(trusted, PersistedCommunicationAuthority):
        return PreferenceService(db, IsolatedPreferenceScope(trusted.principal), directory)
    return PreferenceService(db, SyntheticScope.from_environment(), directory)


Preferences = Annotated[PreferenceService, Depends(get_preference_service)]


@router.get("/runtime-capabilities")
def runtime_capabilities(context: Context, directory=Depends(get_customer_directory), trusted=Depends(get_trusted_authority)):
    from .service import _require_context
    from app.core.policy import CONSEQUENTIAL_ACTIONS
    _require_context(context)
    from .trusted_runtime import PersistedCommunicationAuthority
    if isinstance(trusted, PersistedCommunicationAuthority):
        from .challenge_delivery import isolated_delivery_sink
        return {"tenant_id":context.tenant_id,"mode":"SYNTHETIC",
            "label":"Isolated authenticated runtime — no real messages sent",
            "can_record_preferences":context.actor_role=="MANAGER", "can_revoke_preferences":context.actor_role=="MANAGER",
            "integrated_demo_ready":False,"blockers":["P5_VERIFIED_CONFIRMATION_PORT_UNAVAILABLE"]+
                ([] if isolated_delivery_sink() is not None else ["CUSTOMER_DELIVERY_PORT_UNAVAILABLE"])}
    scope = SyntheticScope.from_environment()
    in_scope = scope.enabled and context.tenant_id in scope.tenants
    manager = in_scope and context.actor_role in {"OWNER", "MANAGER"}
    contact = DirectoryContactAdapter(directory).connected
    policies_ready = {"APPROVE_DRAFT", "REJECT_DRAFT", "SEND_MESSAGE"} <= CONSEQUENTIAL_ACTIONS
    return {"tenant_id": context.tenant_id, "mode": "SYNTHETIC" if in_scope else "CLOSED",
        "label": "Synthetic Demo — No Real Messages Sent" if in_scope else "Trusted authority unavailable",
        "can_record_preferences": bool(manager and contact), "can_revoke_preferences": bool(manager),
        "integrated_demo_ready": False,
        "blockers": ["CORE_APPROVAL_PRODUCER_UNAVAILABLE"] +
            ([] if policies_ready else ["CORE_ACTION_POLICY_UNAVAILABLE"]) +
            ([] if contact else ["P1_CONTACT_CONTRACT_UNAVAILABLE"]) +
            ([] if in_scope else ["PRODUCTION_AUTH_UNAVAILABLE"])}


@router.get("/recipient-preferences", response_model=list[PreferenceView])
def recipient_preferences(service: Preferences, context: Context):
    return service.list(context)


@router.post("/recipient-preferences", response_model=PreferenceView)
def save_recipient_preference(command: PreferenceCommand, service: Preferences, context: Context):
    return service.save(context, command)


@router.get("/{communication_id}/outbound", response_model=list[OutboundMessageView])
def outbound_history(communication_id: str, service: Outbound, context: Context):
    return service.history(context, communication_id)


@router.get("/{communication_id}/drafts/{draft_id}/send-eligibility", response_model=SendEligibility)
def send_eligibility(communication_id: str, draft_id: str, service: Outbound, context: Context):
    return service.eligibility(context, communication_id, draft_id)


@router.post("/{communication_id}/drafts/{draft_id}/send", response_model=OutboundMessageView)
def send_message(communication_id: str, draft_id: str, command: SendMessageRequest, service: Outbound, context: Context):
    return service.send(context, communication_id, draft_id, command)


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


# Keep the application's existing P4 registration. Both owned API prefixes are
# composed here exactly once, so no shared main.py replacement is necessary.
communications_router = router
from .confirmation_router import build_confirmation_router
confirmation_router = build_confirmation_router(get_draft_authority, get_review_authority)
router = APIRouter()
router.include_router(communications_router)
router.include_router(confirmation_router)
from .followup_router import build_followup_router
router.include_router(build_followup_router(
    get_outbound_service, get_preference_service, get_draft_authority, get_review_authority))
