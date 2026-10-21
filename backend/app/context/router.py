"""Provisional P1 routes. All calls use the server-side development tenant."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response

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
