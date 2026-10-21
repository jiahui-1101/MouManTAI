"""P2-local API router; P5 owns application mounting and trust integration."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext, get_db, get_request_context
from app.core.errors import DomainError
from app.core.service import CommitmentService
from app.core.schemas import Commitment, FeasibilityAssessment

from .api_dependencies import (
    get_assessment_history,
    get_assessment_writer,
    get_evaluation_input_authority,
    get_impact_reader,
    get_internal_request_context,
    get_supplier_delay_processor,
)
from .api_schemas import AssessCommitmentRequest, FeasibilityEvaluateRequest, SupplierDelayRequest
from .currentness import require_current_snapshot
from .impact import ImpactAssessment
from .ports import (
    AssessmentHistoryReader,
    AssessmentWriter,
    EvaluationInputAuthority,
    ImpactReader,
    SupplierDelayProcessor,
)
from .service import EvaluationResult, evaluate


router = APIRouter(tags=["feasibility"])
Db = Annotated[Session, Depends(get_db)]
Context = Annotated[RequestContext, Depends(get_request_context)]
InternalContext = Annotated[RequestContext | None, Depends(get_internal_request_context)]
EvaluationAuthority = Annotated[
    EvaluationInputAuthority | None, Depends(get_evaluation_input_authority)
]
AssessmentWriterDependency = Annotated[AssessmentWriter | None, Depends(get_assessment_writer)]
AssessmentHistoryDependency = Annotated[
    AssessmentHistoryReader | None, Depends(get_assessment_history)
]
SupplierDelayProcessorDependency = Annotated[
    SupplierDelayProcessor | None, Depends(get_supplier_delay_processor)
]
ImpactReaderDependency = Annotated[ImpactReader | None, Depends(get_impact_reader)]

commitment_service = CommitmentService()


def _commitment_binding_mismatches(expected: Commitment, actual: Commitment) -> list[str]:
    """Return identity and confirmed-term fields that differ between typed commitments."""

    mismatches = [
        field
        for field in (
            "tenant_id",
            "commitment_id",
            "commitment_version",
            "order_id",
            "customer_id",
            "agreement_state",
        )
        if getattr(expected, field) != getattr(actual, field)
    ]
    mismatches.extend(
        f"terms.{field}"
        for field in (
            "sku",
            "quantity",
            "unit",
            "deadline",
            "special_instructions",
        )
        if getattr(expected.terms, field) != getattr(actual.terms, field)
    )
    return mismatches


def _raise_commitment_binding_mismatch(
    mismatched_fields: list[str], *, correlation_id: str | None
) -> None:
    raise DomainError(
        "COMMITMENT_BINDING_MISMATCH",
        "Resolved commitment does not match the requested or Core commitment identity and confirmed terms",
        status_code=409,
        details={"mismatched_fields": mismatched_fields},
        correlation_id=correlation_id,
    )


def _blocked(code: str, message: str, *, correlation_id: str | None = None) -> DomainError:
    return DomainError(code, message, status_code=503, correlation_id=correlation_id)


def _require_tenant(context: RequestContext, *tenant_ids: str) -> None:
    if any(tenant_id != context.tenant_id for tenant_id in tenant_ids):
        raise DomainError(
            "TENANT_SCOPE_MISMATCH",
            "Request data is outside the resolved tenant scope",
            status_code=403,
            correlation_id=context.correlation_id,
        )


@router.post("/internal/feasibility/evaluate", response_model=EvaluationResult)
def evaluate_feasibility(
    request: FeasibilityEvaluateRequest,
    context: InternalContext,
    authority: EvaluationAuthority,
) -> EvaluationResult:
    """Evaluate a trusted snapshot without persistence or operational writes."""

    if context is None:
        raise _blocked(
            "P2_INTERNAL_AUTH_NOT_CONFIGURED",
            "P5 has not configured the internal feasibility authorization boundary",
        )
    if context.actor_role not in {"SERVICE", "SYSTEM"}:
        raise DomainError(
            "P2_INTERNAL_CALLER_NOT_AUTHORIZED",
            "Internal feasibility evaluation requires a trusted SERVICE or SYSTEM context",
            status_code=403,
            correlation_id=context.correlation_id,
        )
    tenant_ids = [request.snapshot.operational.tenant_id, request.commitment.tenant_id]
    if request.proposed_changes is not None:
        tenant_ids.append(request.proposed_changes.tenant_id)
    _require_tenant(context, *tenant_ids)
    if request.proposed_changes is not None and (
        request.proposed_changes.commitment_id != request.commitment.commitment_id
    ):
        raise DomainError(
            "EVALUATION_INPUT_CONFLICT",
            "Proposed changes target a different commitment",
            status_code=409,
            correlation_id=context.correlation_id,
        )
    if authority is None:
        raise _blocked(
            "P2_EVALUATION_AUTHORITY_NOT_CONFIGURED",
            "P5 has not configured authoritative commitment and snapshot resolution",
            correlation_id=context.correlation_id,
        )

    snapshot, commitment = authority.resolve(context, request)
    _require_tenant(context, snapshot.operational.tenant_id)
    if (
        snapshot.operational.snapshot_id != request.snapshot.operational.snapshot_id
        or snapshot.operational.snapshot_version != request.snapshot.operational.snapshot_version
        or commitment.commitment_id != request.commitment.commitment_id
        or commitment.commitment_version != request.commitment.commitment_version
    ):
        raise DomainError(
            "EVALUATION_INPUT_VERSION_CONFLICT",
            "Authoritative input does not match the requested snapshot or commitment version",
            status_code=409,
            correlation_id=context.correlation_id,
        )
    mismatched_fields = _commitment_binding_mismatches(request.commitment, commitment)
    if mismatched_fields:
        _raise_commitment_binding_mismatch(
            mismatched_fields,
            correlation_id=context.correlation_id,
        )
    try:
        return evaluate(snapshot, request.proposed_changes, commitment)
    except ValueError as exc:
        raise DomainError(
            "EVALUATION_INPUT_CONFLICT",
            str(exc),
            status_code=409,
            correlation_id=context.correlation_id,
        ) from exc


@router.post("/v1/commitments/{commitment_id}/assess", response_model=FeasibilityAssessment)
def assess_commitment(
    commitment_id: str,
    request: AssessCommitmentRequest,
    db: Db,
    context: Context,
    writer: AssessmentWriterDependency,
    authority: EvaluationAuthority,
) -> FeasibilityAssessment:
    """Evaluate trusted current input, then persist that exact result through P5."""

    commitment = commitment_service.get(db, context, commitment_id)
    if commitment.commitment_version != request.expected_commitment_version:
        raise DomainError(
            "COMMITMENT_VERSION_CONFLICT",
            "Commitment version is stale",
            status_code=409,
            details={"current_commitment_version": commitment.commitment_version},
            correlation_id=context.correlation_id,
        )
    if commitment.agreement_state.value != "CONFIRMED":
        raise DomainError(
            "COMMITMENT_NOT_CONFIRMED",
            "Only a confirmed commitment can be assessed as an active commitment",
            status_code=409,
            correlation_id=context.correlation_id,
        )
    if writer is None:
        raise _blocked(
            "P2_ASSESSMENT_PERSISTENCE_NOT_CONFIGURED",
            "P5 has not approved assessment persistence, audit, and outbox integration",
            correlation_id=context.correlation_id,
        )
    if authority is None:
        raise _blocked(
            "P2_ASSESSMENT_INPUT_AUTHORITY_NOT_CONFIGURED",
            "P5 has not configured authoritative current snapshot resolution",
            correlation_id=context.correlation_id,
        )

    snapshot, authoritative_commitment = authority.resolve_current(
        context,
        commitment_id,
        request.expected_commitment_version,
    )
    _require_tenant(
        context,
        snapshot.operational.tenant_id,
    )
    if (
        authoritative_commitment.commitment_id != commitment_id
        or authoritative_commitment.commitment_version != request.expected_commitment_version
        or authoritative_commitment.commitment_version != commitment.commitment_version
    ):
        raise DomainError(
            "COMMITMENT_VERSION_CONFLICT",
            "Authoritative commitment identity or version is stale",
            status_code=409,
            correlation_id=context.correlation_id,
        )
    mismatched_fields = _commitment_binding_mismatches(commitment, authoritative_commitment)
    if mismatched_fields:
        _raise_commitment_binding_mismatch(
            mismatched_fields,
            correlation_id=context.correlation_id,
        )
    require_current_snapshot(snapshot, correlation_id=context.correlation_id)
    try:
        result = evaluate(snapshot, None, authoritative_commitment)
    except ValueError as exc:
        raise DomainError(
            "ASSESSMENT_INPUT_CONFLICT",
            str(exc),
            status_code=409,
            correlation_id=context.correlation_id,
        ) from exc
    return writer.assess(
        db,
        context,
        authoritative_commitment,
        request,
        snapshot=snapshot,
        result=result,
    )


@router.get(
    "/v1/commitments/{commitment_id}/assessments",
    response_model=list[FeasibilityAssessment],
)
def list_assessments(
    commitment_id: str,
    db: Db,
    context: Context,
    history: AssessmentHistoryDependency,
) -> list[FeasibilityAssessment]:
    commitment_service.get(db, context, commitment_id)
    if history is None:
        raise _blocked(
            "P2_ASSESSMENT_HISTORY_NOT_CONFIGURED",
            "P5 has not approved durable assessment-history storage",
            correlation_id=context.correlation_id,
        )
    return history.list_for_commitment(db, context, commitment_id)


@router.post("/v1/operations/events/supplier-delay", response_model=ImpactAssessment)
def process_supplier_delay(
    request: SupplierDelayRequest,
    db: Db,
    context: Context,
    processor: SupplierDelayProcessorDependency,
) -> ImpactAssessment:
    """Require P5's atomic snapshot update, deduplication, and outbox service."""

    _require_tenant(
        context,
        request.change.tenant_id,
        request.source_evidence.tenant_id,
    )
    if processor is None:
        raise _blocked(
            "P2_SUPPLIER_DELAY_OUTBOX_NOT_CONFIGURED",
            "P5 has not configured transactional supplier-event processing and outbox",
            correlation_id=context.correlation_id,
        )
    return processor.process(db, context, request)


@router.get("/v1/impacts/{impact_id}", response_model=ImpactAssessment)
def get_impact(
    impact_id: str,
    db: Db,
    context: Context,
    reader: ImpactReaderDependency,
) -> ImpactAssessment:
    if reader is None:
        raise _blocked(
            "P2_IMPACT_PERSISTENCE_NOT_CONFIGURED",
            "P5 has not approved durable impact-result storage",
            correlation_id=context.correlation_id,
        )
    return reader.get(db, context, impact_id)
