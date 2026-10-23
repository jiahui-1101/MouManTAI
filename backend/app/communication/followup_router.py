"""P4 deterministic scheduling surface. Authorization is closed by default."""
from typing import Annotated
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext, get_db, get_request_context
from .confirmation_authority import ExistingP4ConfirmationAuthority
from .confirmations import ConfirmationService
from .followup import FollowUpService, RuntimeFollowUpAuthority
from .followup_schemas import CancelFollowUp, FollowUpView, ScheduleFollowUp


def get_followup_authority():
    # Neither demo headers nor SEND_MESSAGE policy authorize repeat contact.
    # P5 owns binding authenticated principals to per-policy reminder grants.
    return RuntimeFollowUpAuthority()


def build_followup_router(get_outbound_service, get_preference_service, get_draft_authority, get_review_authority):
    router = APIRouter(prefix="/v1/follow-ups", tags=["follow-ups"])

    def get_service(db: Annotated[Session, Depends(get_db)], authority=Depends(get_followup_authority),
                    outbound=Depends(get_outbound_service), preferences=Depends(get_preference_service),
                    drafts=Depends(get_draft_authority), reviews=Depends(get_review_authority)):
        # Internal basis reading reuses the existing P4 guards; no response processor grant.
        confirmations = ConfirmationService(db, None, ExistingP4ConfirmationAuthority(drafts, reviews), None)
        return FollowUpService(db, authority, confirmations, outbound, preferences)

    Service = Annotated[FollowUpService, Depends(get_service)]
    Context = Annotated[RequestContext, Depends(get_request_context)]

    @router.get("", response_model=list[FollowUpView])
    def list_tasks(service: Service, context: Context):
        return service.list(context)

    @router.post("", response_model=FollowUpView)
    def schedule_task(command: ScheduleFollowUp, service: Service, context: Context):
        return service.schedule(context, command)

    @router.post("/run-due", response_model=list[FollowUpView])
    def run_due(service: Service, context: Context):
        return service.run_due(context)

    @router.post("/{task_id}/cancel", response_model=FollowUpView)
    def cancel_task(task_id: str, command: CancelFollowUp, service: Service, context: Context):
        return service.cancel(context, task_id, command.reason)

    return router
