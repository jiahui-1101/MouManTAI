"""Provisional P1 routes. All calls use the server-side development tenant."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response

from .association_schemas import AssociationDecisionRequest, MessageAssociationRecord
from .association_service import AssociationService
from .context_service import ContextService
from .dependencies import development_context, local_repository
from .ingestion import IngestionService
from .ingestion_schemas import (
    ApiError,
    DevelopmentContext,
    ExtractionAttemptRecord,
    ExtractionHistoryResponse,
    IngestResponse,
    MessagePage,
    ProcessResponse,
    StoredMessage,
)
from .order_context_schemas import (
    ContextReviewRecord,
    ContextReviewRequest,
    ContextUpdateRequest,
    OrderContextRecord,
    OrderContextVersionRecord,
)
from .repository import MessageRepository
from .schemas import Channel, ProcessingStatus, RawMessageEnvelope

router = APIRouter(tags=["P1 synthetic ingestion — provisional"])
Tenant = Annotated[DevelopmentContext, Depends(development_context)]
Repository = Annotated[MessageRepository, Depends(local_repository)]
errors = {403: {"model": ApiError}, 503: {"model": ApiError}}


@router.get("/dev/p1/config", response_model=DevelopmentContext)
def local_config(tenant: Tenant) -> DevelopmentContext:
    return tenant


@router.post("/v1/messages/ingest", response_model=IngestResponse, status_code=201,
             responses={**errors, 200: {"model": IngestResponse}, 409: {"model": ApiError}, 422: {"description": "Invalid envelope or unimplemented channel"}})
def ingest_message(envelope: RawMessageEnvelope, response: Response, tenant: Tenant, repository: Repository) -> IngestResponse:
    result = IngestionService(repository).ingest(envelope, tenant.tenant_id)
    response.status_code = 200 if result.duplicate else 201
    return result


@router.get("/v1/messages", response_model=MessagePage, responses=errors)
def list_messages(tenant: Tenant, repository: Repository, channel: Channel | None = None,
                  search: Annotated[str, Query(max_length=200)] = "",
                  processing_status: ProcessingStatus | None = None,
                  limit: Annotated[int, Query(ge=1, le=100)] = 25,
                  offset: Annotated[int, Query(ge=0, le=10_000)] = 0) -> MessagePage:
    return repository.list(tenant.tenant_id, channel=channel, search=search,
                           processing_status=processing_status, limit=limit, offset=offset)


@router.get("/v1/messages/{message_id}", response_model=StoredMessage,
            responses={**errors, 404: {"model": ApiError}})
def get_message(message_id: str, tenant: Tenant, repository: Repository) -> StoredMessage:
    message = repository.get(tenant.tenant_id, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    return message


@router.post("/v1/messages/{message_id}/process", response_model=ProcessResponse,
             responses={**errors, 404: {"model": ApiError}, 409: {"model": ApiError}})
def process_message(message_id: str, tenant: Tenant, repository: Repository,
                    reprocess: Annotated[bool, Query()] = False) -> ProcessResponse:
    return repository.process(tenant.tenant_id, message_id, reprocess=reprocess)


@router.get("/v1/messages/{message_id}/extraction", response_model=ExtractionAttemptRecord,
            responses={**errors, 404: {"model": ApiError}})
def get_message_extraction(message_id: str, tenant: Tenant, repository: Repository) -> ExtractionAttemptRecord:
    result = repository.get_latest_extraction(tenant.tenant_id, message_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Extraction attempt not found")
    return result


@router.get("/v1/messages/{message_id}/attempts", response_model=ExtractionHistoryResponse,
            responses={**errors, 404: {"model": ApiError}})
def list_message_attempts(message_id: str, tenant: Tenant, repository: Repository) -> ExtractionHistoryResponse:
    items = repository.list_extraction_attempts(tenant.tenant_id, message_id)
    return ExtractionHistoryResponse(items=items)


@router.get("/v1/messages/{message_id}/association", response_model=MessageAssociationRecord,
            responses={**errors, 404: {"model": ApiError}})
def get_message_association(message_id: str, tenant: Tenant, repository: Repository) -> MessageAssociationRecord:
    existing = repository.get_association(tenant.tenant_id, message_id)
    if existing is not None:
        return existing

    message = repository.get(tenant.tenant_id, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")

    extracted_fields = None
    try:
        attempt = repository.get_latest_extraction(tenant.tenant_id, message_id)
        if attempt:
            extracted_fields = [f.model_dump(mode="json") for f in attempt.fields]
    except Exception:
        extracted_fields = None

    svc = AssociationService()
    record = svc.evaluate_association(message, extracted_fields)
    return repository.save_association(record)


@router.post("/v1/messages/{message_id}/association", response_model=MessageAssociationRecord,
             responses={**errors, 404: {"model": ApiError}, 409: {"model": ApiError}})
def decide_message_association(
    message_id: str,
    request: AssociationDecisionRequest,
    tenant: Tenant,
    repository: Repository,
    x_actor_id: Annotated[str | None, Header(alias="X-Actor-ID")] = None,
    x_actor_role: Annotated[str | None, Header(alias="X-Actor-Role")] = None,
) -> MessageAssociationRecord:
    actor_id = x_actor_id or "user_staff_01"
    actor_role = x_actor_role or "STAFF"
    return repository.decide_association(tenant.tenant_id, message_id, request, actor_id=actor_id, actor_role=actor_role)


@router.get("/v1/contexts/{context_id}", response_model=OrderContextRecord,
            responses={**errors, 404: {"model": ApiError}})
def get_order_context(context_id: str, tenant: Tenant, repository: Repository) -> OrderContextRecord:
    ctx = repository.get_order_context(tenant.tenant_id, context_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Order context not found")
    return ctx


@router.get("/v1/contexts/by-order/{order_id}", response_model=OrderContextRecord,
            responses={**errors, 404: {"model": ApiError}})
def get_order_context_by_order(order_id: str, tenant: Tenant, repository: Repository) -> OrderContextRecord:
    ctx = repository.get_order_context_by_order(tenant.tenant_id, order_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail=f"Order context for order {order_id} not found")
    return ctx


@router.post("/v1/contexts/from-message/{message_id}", response_model=OrderContextRecord, status_code=201,
             responses={**errors, 404: {"model": ApiError}, 409: {"model": ApiError}})
def create_or_update_context_from_message(
    message_id: str,
    tenant: Tenant,
    repository: Repository,
) -> OrderContextRecord:
    svc = ContextService(repository)
    return svc.create_or_update_from_message(tenant.tenant_id, message_id)


@router.post("/v1/contexts/{context_id}/review", response_model=OrderContextRecord,
             responses={**errors, 404: {"model": ApiError}, 409: {"model": ApiError}})
def review_order_context(
    context_id: str,
    request: ContextReviewRequest,
    tenant: Tenant,
    repository: Repository,
    x_actor_id: Annotated[str | None, Header(alias="X-Actor-ID")] = None,
    x_actor_role: Annotated[str | None, Header(alias="X-Actor-Role")] = None,
) -> OrderContextRecord:
    actor_id = x_actor_id or "user_staff_01"
    actor_role = x_actor_role or "STAFF"
    svc = ContextService(repository)
    return svc.review_context(tenant.tenant_id, context_id, request, actor_id=actor_id, actor_role=actor_role)


@router.patch("/v1/contexts/{context_id}", response_model=OrderContextRecord,
              responses={**errors, 404: {"model": ApiError}, 409: {"model": ApiError}})
def update_order_context(
    context_id: str,
    request: ContextUpdateRequest,
    tenant: Tenant,
    repository: Repository,
    x_actor_id: Annotated[str | None, Header(alias="X-Actor-ID")] = None,
    x_actor_role: Annotated[str | None, Header(alias="X-Actor-Role")] = None,
) -> OrderContextRecord:
    actor_id = x_actor_id or "user_staff_01"
    actor_role = x_actor_role or "STAFF"
    svc = ContextService(repository)
    return svc.update_context(tenant.tenant_id, context_id, request, actor_id=actor_id, actor_role=actor_role)


@router.get("/v1/contexts/{context_id}/versions", response_model=list[OrderContextVersionRecord],
            responses={**errors, 404: {"model": ApiError}})
def list_context_versions(context_id: str, tenant: Tenant, repository: Repository) -> list[OrderContextVersionRecord]:
    ctx = repository.get_order_context(tenant.tenant_id, context_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Order context not found")
    return repository.list_context_versions(tenant.tenant_id, context_id)


@router.get("/v1/contexts/{context_id}/reviews", response_model=list[ContextReviewRecord],
            responses={**errors, 404: {"model": ApiError}})
def list_context_reviews(context_id: str, tenant: Tenant, repository: Repository) -> list[ContextReviewRecord]:
    ctx = repository.get_order_context(tenant.tenant_id, context_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Order context not found")
    return repository.list_context_reviews(tenant.tenant_id, context_id)

