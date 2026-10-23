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



def get_confirmation_access(db=Depends(get_db), x_isolated_e2e_key: str | None = Header(default=None),
                            x_p4_processor_key: str | None = Header(default=None)):
    from .trusted_runtime import enabled, IsolatedPrincipal, IsolatedConfirmationAccess
    if enabled():
        return IsolatedConfirmationAccess(IsolatedPrincipal(db, x_isolated_e2e_key, processor_key=x_p4_processor_key))
    return RuntimeConfirmationAccess()


def get_verified_inbound_authority(db=Depends(get_db), x_isolated_e2e_key: str | None = Header(default=None),
                                  x_p4_processor_key: str | None = Header(default=None)):
    from .trusted_runtime import enabled, IsolatedPrincipal, IsolatedPreferenceScope
    if enabled():
        from .contacts import get_customer_directory
        from .inbound_processor import P1BoundReplyAdapter
        from app.context.postgres_repository import PostgresMessageRepository
        principal = IsolatedPrincipal(db, x_isolated_e2e_key, processor_key=x_p4_processor_key)
        return P1BoundReplyAdapter(PostgresMessageRepository(db.get_bind().engine),
            get_customer_directory(), IsolatedPreferenceScope(principal))
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
        from .inbound_processor import P1BoundReplyAdapter
        if isinstance(service.inbound, P1BoundReplyAdapter):
            service.inbound.target = confirmation_id
        return service.respond(context, confirmation_id, command, challenge)


    @router.post("/{confirmation_id}/revoke", response_model=ConfirmationView)
    def revoke_confirmation(confirmation_id: str, service: Service, context: Context):
        return service.revoke(context, confirmation_id)
    @router.post("/process-inbound", response_model=ConfirmationAttemptView)
    def process_p1_response(command: ProcessConfirmationResponse, service: Service, context: Context):
        from .inbound_processor import process_persisted_inbound
        return process_persisted_inbound(service, context, command)
    return router
