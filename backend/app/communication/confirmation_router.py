"""Authenticated processor selectors, not a public customer-identity assertion API."""
from typing import Annotated
from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext, get_db, get_request_context
from .confirmation_authority import (
    ExistingP4ConfirmationAuthority, RuntimeConfirmationAccess, UnavailableVerifiedInboundAuthority,
)
from .confirmation_schemas import (
    CreateConfirmation, ProcessConfirmationResponse, ConfirmationView, ConfirmationAttemptView, IssuedConfirmation,
)
from .confirmations import ConfirmationService



def get_confirmation_access():
    return RuntimeConfirmationAccess()


def get_verified_inbound_authority():
    return UnavailableVerifiedInboundAuthority()


def build_confirmation_router(get_draft_authority, get_review_authority):
    """Compose existing P4 dependencies without a circular module import."""
    router = APIRouter(prefix="/v1/confirmations", tags=["confirmations"])
    def get_confirmation_authority(drafts=Depends(get_draft_authority), reviews=Depends(get_review_authority)):
        return ExistingP4ConfirmationAuthority(drafts, reviews)


    def get_confirmation_service(db: Annotated[Session, Depends(get_db)],
        access=Depends(get_confirmation_access), authority=Depends(get_confirmation_authority),
        inbound=Depends(get_verified_inbound_authority)):
        return ConfirmationService(db, access, authority, inbound)


    Service = Annotated[ConfirmationService, Depends(get_confirmation_service)]
    Context = Annotated[RequestContext, Depends(get_request_context)]


    @router.post("", response_model=IssuedConfirmation)
    def create_confirmation(command: CreateConfirmation, service: Service, context: Context, response: Response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        return service.issue(context, command)


    @router.get("", response_model=list[ConfirmationView])
    def list_confirmations(service: Service, context: Context, communication_id: str | None = None):
        return service.list(context, communication_id=communication_id)


    @router.get("/{confirmation_id}", response_model=ConfirmationView)
    def get_confirmation(confirmation_id: str, service: Service, context: Context):
        return service.get(context, confirmation_id)


    @router.get("/{confirmation_id}/attempts", response_model=list[ConfirmationAttemptView])
    def confirmation_history(confirmation_id: str, service: Service, context: Context):
        return service.history(context, confirmation_id)


    @router.post("/{confirmation_id}/respond", response_model=ConfirmationAttemptView)
    def process_response(confirmation_id: str, command: ProcessConfirmationResponse, service: Service, context: Context,
                         challenge: Annotated[str | None, Header(alias="X-Confirmation-Token")] = None):
        return service.respond(context, confirmation_id, command, challenge)


    @router.post("/{confirmation_id}/revoke", response_model=ConfirmationView)
    def revoke_confirmation(confirmation_id: str, service: Service, context: Context):
        return service.revoke(context, confirmation_id)
    return router
