import hashlib
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Response, UploadFile

from .association_schemas import AssociationDecisionRequest, MessageAssociationRecord
from .association_service import AssociationService
from .attachment_validator import validate_attachment
from .context_service import ContextService
from .core_publisher import CoreContextPublisher, IneligibleContextError
from .document_extractor import extract_pdf_document
from .document_schemas import AttachmentRecord, DocumentExtractionResult
from .dependencies import development_context, local_repository
from app.core.dependencies import RequestContext
from sqlalchemy.orm import Session
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
                    reprocess: Annotated[bool, Query()] = False,
                    x_p1_operation_id: Annotated[str | None, Header(max_length=64, pattern=r"^[A-Za-z0-9_-]+$")] = None) -> ProcessResponse:
    if x_p1_operation_id:
        return repository.process(tenant.tenant_id, message_id, reprocess=reprocess, operation_id=x_p1_operation_id)
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


@router.post("/v1/contexts/{context_id}/publish", response_model=OrderContextRecord,
             responses={**errors, 404: {"model": ApiError}, 422: {"model": ApiError}})
def publish_order_context_to_core(
    context_id: str,
    tenant: Tenant,
    repository: Repository,
    x_actor_id: Annotated[str | None, Header(alias="X-Actor-ID")] = None,
    x_actor_role: Annotated[str | None, Header(alias="X-Actor-Role")] = None,
    x_correlation_id: Annotated[str | None, Header(alias="X-Correlation-ID")] = None,
) -> OrderContextRecord:
    ctx = repository.get_order_context(tenant.tenant_id, context_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail="Order context not found")

    publisher = CoreContextPublisher()
    is_eligible, reasons = publisher.check_eligibility(ctx)
    if not is_eligible:
        raise HTTPException(
            status_code=422,
            detail={
                "message": f"Context '{context_id}' is ineligible for Core publication",
                "reasons": reasons,
            },
        )

    actor_id = x_actor_id or "user_staff_01"
    actor_role = x_actor_role or "STAFF"
    correlation_id = x_correlation_id or f"corr_{uuid4().hex[:12]}"
    req_context = RequestContext(
        tenant_id=tenant.tenant_id,
        actor_id=actor_id,
        actor_role=actor_role,
        correlation_id=correlation_id,
        causation_id=context_id,
    )

    engine = getattr(repository, "engine", None)
    if engine is None:
        raise HTTPException(status_code=503, detail="Database persistence engine is unavailable")

    try:
        with Session(engine) as session:
            publisher.publish_to_core(session, req_context, ctx)
    except IneligibleContextError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": exc.message,
                "reasons": exc.reasons,
            },
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Core publication failed: {exc}") from exc

    refetched = repository.get_order_context(tenant.tenant_id, context_id)
    if refetched is None:
        raise HTTPException(status_code=404, detail="Order context not found after publication")
    return refetched


@router.post("/v1/attachments/upload", response_model=AttachmentRecord, status_code=201,
             responses={**errors, 400: {"model": ApiError}, 413: {"model": ApiError}, 415: {"model": ApiError}})
async def upload_attachment(
    tenant: Tenant,
    repository: Repository,
    file: UploadFile = File(...),
) -> AttachmentRecord:
    content = await file.read()
    media_type, filename = validate_attachment(file.filename or "attachment.bin", content, file.content_type)
    content_sha256 = hashlib.sha256(content).hexdigest()
    attachment_id = f"att_{uuid4().hex[:12]}"
    evidence_ref = f"ev_att_{uuid4().hex[:12]}"

    record = AttachmentRecord(
        attachment_id=attachment_id,
        tenant_id=tenant.tenant_id,
        evidence_ref=evidence_ref,
        filename=filename,
        media_type=media_type,
        size_bytes=len(content),
        content_sha256=content_sha256,
    )
    return repository.save_attachment(tenant.tenant_id, record, content)


@router.get("/v1/attachments/{evidence_ref}/content",
            responses={**errors, 404: {"model": ApiError}})
def get_attachment_content(
    evidence_ref: str,
    tenant: Tenant,
    repository: Repository,
) -> Response:
    res = repository.get_attachment(tenant.tenant_id, evidence_ref)
    if res is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    rec, content = res
    return Response(
        content=content,
        media_type=rec.media_type,
        headers={"Content-Disposition": f'inline; filename="{rec.filename}"'},
    )


@router.get("/v1/attachments/{evidence_ref}/page-count",
            responses={**errors, 404: {"model": ApiError}})
def get_attachment_page_count(
    evidence_ref: str,
    tenant: Tenant,
    repository: Repository,
) -> dict:
    res = repository.get_attachment(tenant.tenant_id, evidence_ref)
    if res is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    rec, content = res
    if rec.media_type == "application/pdf":
        try:
            import pymupdf
            doc = pymupdf.open(stream=content, filetype="pdf")
            return {"total_pages": len(doc), "media_type": rec.media_type}
        except Exception:
            return {"total_pages": 1, "media_type": rec.media_type}
    return {"total_pages": 1, "media_type": rec.media_type}


@router.get("/v1/attachments/{evidence_ref}/pages/{page_number}",
            responses={**errors, 404: {"model": ApiError}, 400: {"model": ApiError}, 415: {"model": ApiError}})
def get_attachment_page(
    evidence_ref: str,
    page_number: int,
    tenant: Tenant,
    repository: Repository,
    rotate: int = 0,
) -> Response:
    res = repository.get_attachment(tenant.tenant_id, evidence_ref)
    if res is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    rec, content = res
    if rec.media_type == "application/pdf":
        try:
            import pymupdf
            doc = pymupdf.open(stream=content, filetype="pdf")
            total = len(doc)
            if page_number < 1 or page_number > total:
                raise HTTPException(status_code=400, detail=f"Page number {page_number} out of range (1..{total})")
            page = doc[page_number - 1]
            if rotate % 360 != 0:
                page.set_rotation(rotate % 360)
            pix = page.get_pixmap(dpi=150)
            return Response(
                content=pix.tobytes("png"),
                media_type="image/png",
                headers={
                    "X-Total-Pages": str(total),
                    "X-Current-Page": str(page_number),
                    "Cache-Control": "public, max-age=3600",
                },
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to render PDF page: {exc}")
    elif rec.media_type.startswith("image/"):
        return Response(
            content=content,
            media_type=rec.media_type,
            headers={"X-Total-Pages": "1", "X-Current-Page": "1"},
        )
    else:
        raise HTTPException(status_code=415, detail="Unsupported media type for page rendering")



@router.get("/v1/attachments/{evidence_ref}/metadata", response_model=AttachmentRecord,
            responses={**errors, 404: {"model": ApiError}})
def get_attachment_metadata(
    evidence_ref: str,
    tenant: Tenant,
    repository: Repository,
) -> AttachmentRecord:
    res = repository.get_attachment(tenant.tenant_id, evidence_ref)
    if res is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    rec, _ = res
    return rec


@router.post("/v1/attachments/{evidence_ref}/extract", response_model=DocumentExtractionResult,
             responses={**errors, 404: {"model": ApiError}, 415: {"model": ApiError}})
def extract_attachment(
    evidence_ref: str,
    tenant: Tenant,
    repository: Repository,
) -> DocumentExtractionResult:
    res = repository.get_attachment(tenant.tenant_id, evidence_ref)
    if res is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    record, content = res
    if record.media_type == "application/pdf":
        result = extract_pdf_document(record, content)
    elif record.media_type in ("image/png", "image/jpeg"):
        from .document_extractor import extract_image_ocr
        result = extract_image_ocr(record, content)
    else:
        raise HTTPException(status_code=415, detail=f"Unsupported attachment type for extraction: {record.media_type}")

    return repository.save_document_extraction(tenant.tenant_id, result)


@router.get("/v1/attachments/{evidence_ref}/extraction", response_model=DocumentExtractionResult,
            responses={**errors, 404: {"model": ApiError}})
def get_attachment_extraction(
    evidence_ref: str,
    tenant: Tenant,
    repository: Repository,
) -> DocumentExtractionResult:
    result = repository.get_document_extraction(tenant.tenant_id, evidence_ref)
    if result is None:
        raise HTTPException(status_code=404, detail="Document extraction not found for this attachment")
    return result

