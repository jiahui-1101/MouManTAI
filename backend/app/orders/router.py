"""Explicitly isolated v2.2 workflows backed by synthetic external facts."""

import os
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Response
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext, get_db, get_request_context
from app.core.errors import DomainError
from app.core.manager_approval import trusted_isolated_manager
from app.core.models import AuditEventRecord
from app.core.schemas import Commitment
from app.core.service import CommitmentService
from app.feasibility.production import EvaluationSnapshot
from app.feasibility.service import EvaluationResult
from app.integrations.business_ports import ReservationReceipt
from app.integrations.mock_orbyte import MockOrbyteAdapter
from app.integrations.mock_seed import MockResourceSeed, seed_mock_resources
from app.orders.acceptance import accept_mock_order, reconcile_mock_order
from app.orders.mock_feasibility import project_pending_order
from app.orders.mock_source import MockInquiryCreate, MockInquiryView, seed_mock_inquiry
from app.orders.models import OrderRequestAuditRecord, OrderRequestRecord
from app.orders.operational_evidence import OperationalEvidenceView, read_operational_evidence
from app.orders.service import get_request, import_request, review_request
from app.orders.status import CommitmentStatusPreview, read_status_preview
from app.orders.terms import (
    ImmutableContract,
    OrderTerms,
    TermsComparison,
    compare_terms,
    require_exact_terms,
)


def isolated_preview_context(
    context: Annotated[RequestContext, Depends(get_request_context)],
    x_isolated_e2e_key: str | None = Header(default=None),
) -> RequestContext:
    if os.getenv("ENVIRONMENT", "").lower() == "production":
        raise DomainError("PREVIEW_DISABLED", "Synthetic previews are disabled in production", status_code=503)
    trusted_isolated_manager(context, x_isolated_e2e_key)
    configured_tenant = os.getenv("MOUMANTAI_ISOLATED_E2E_TENANT_ID")
    if configured_tenant and context.tenant_id != configured_tenant:
        raise DomainError("TENANT_SCOPE_MISMATCH", "Tenant is outside this isolated environment",
                          status_code=403)
    # This role follows the server-configured identity plus isolated secret,
    # never the untrusted X-Actor-ID header alone.
    return RequestContext(tenant_id=context.tenant_id, actor_id=context.actor_id,
                          actor_role="MANAGER", correlation_id=context.correlation_id,
                          causation_id=context.causation_id)


router = APIRouter(prefix="/v1/backend-v2", tags=["v2.2 synthetic workflows"])
Context = Annotated[RequestContext, Depends(isolated_preview_context)]


def mock_workflow_context(context: Context) -> RequestContext:
    """Bind the isolated Mock credential to one server-owned tenant."""
    allowed_tenant = os.getenv("MOUMANTAI_ISOLATED_E2E_TENANT_ID")
    if not allowed_tenant:
        raise DomainError("MOCK_TENANT_NOT_CONFIGURED", "Mock tenant binding is unavailable", status_code=503)
    if context.tenant_id != allowed_tenant:
        raise DomainError("TENANT_SCOPE_MISMATCH", "Mock tenant is outside this isolated environment",
                          status_code=403)
    return context


MockContext = Annotated[RequestContext, Depends(mock_workflow_context)]


class TermsCheckRequest(ImmutableContract):
    original: OrderTerms
    proposed: OrderTerms
    expected_revision: int = Field(ge=1)
    expected_terms_hash: str


class TermsCheckResponse(ImmutableContract):
    comparison: TermsComparison
    source_verified: Literal[False] = False
    acceptance_enabled: Literal[False] = False
    integration_mode: Literal["SYNTHETIC"] = "SYNTHETIC"
    evidence_tier: Literal["DEMO-ONLY"] = "DEMO-ONLY"


@router.post("/terms/check", response_model=TermsCheckResponse)
def check_terms(command: TermsCheckRequest, context: Context) -> TermsCheckResponse:
    """Input consistency only: supplied original is NOT authenticated customer assent."""
    require_exact_terms(command.original, command.proposed, tenant_id=context.tenant_id,
                        expected_revision=command.expected_revision, expected_terms_hash=command.expected_terms_hash)
    return TermsCheckResponse(comparison=compare_terms(command.original, command.proposed))


@router.get("/commitments/{commitment_id}/status-preview", response_model=CommitmentStatusPreview)
def status_preview(commitment_id: str, context: Context,
                   db: Annotated[Session, Depends(get_db)]) -> CommitmentStatusPreview:
    return read_status_preview(db, context, commitment_id)


@router.get("/commitments/{commitment_id}/operational-evidence", response_model=OperationalEvidenceView)
def operational_evidence(commitment_id: str, context: MockContext,
                         db: Annotated[Session, Depends(get_db)]) -> OperationalEvidenceView:
    return read_operational_evidence(db, context, commitment_id)


class ImportMockRequest(ImmutableContract):
    source_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    expected_source_version: int = Field(ge=1, strict=True)


class ReviewMockRequest(ImmutableContract):
    expected_request_version: int = Field(ge=1, strict=True)
    decision: Literal["REVIEWED", "REJECTED"]
    reason: str = Field(min_length=1, max_length=1000)


class MockOrderRequestView(ImmutableContract):
    tenant_id: str
    order_request_id: str
    customer_id: str
    source_id: str
    source_version: int
    source_evidence_refs: tuple[str, ...]
    source_observed_at: str
    source_valid_through: str
    terms: OrderTerms
    terms_hash: str
    request_version: int
    decision_status: Literal["PENDING", "REVIEWED", "RESERVATION_UNKNOWN", "REJECTED", "ACCEPTED"]
    review_actor_id: str | None
    review_reason: str | None
    commitment_id: str | None
    created_at: str
    updated_at: str
    integration_mode: Literal["MOCK"] = "MOCK"
    evidence_tier: Literal["DEMO-ONLY"] = "DEMO-ONLY"


def _view(row: OrderRequestRecord) -> MockOrderRequestView:
    return MockOrderRequestView(
        tenant_id=row.tenant_id, order_request_id=row.order_request_id,
        customer_id=row.customer_id, source_id=row.source_id, source_version=row.source_version,
        source_evidence_refs=tuple(row.source_evidence_refs),
        source_observed_at=row.source_observed_at.isoformat(),
        source_valid_through=row.source_valid_through.isoformat(),
        terms=OrderTerms.model_validate(row.terms), terms_hash=row.terms_hash,
        request_version=row.request_version, decision_status=row.decision_status,
        review_actor_id=row.review_actor_id, review_reason=row.review_reason,
        commitment_id=row.commitment_id, created_at=row.created_at.isoformat(),
        updated_at=row.updated_at.isoformat(),
    )


Db = Annotated[Session, Depends(get_db)]


@router.post("/mock-orbyte/inquiries", response_model=MockInquiryView, status_code=201)
def create_mock_inquiry(command: MockInquiryCreate, context: MockContext, db: Db) -> MockInquiryView:
    return seed_mock_inquiry(db, context, command)


@router.post("/order-requests/import-mock", response_model=MockOrderRequestView, status_code=201)
def import_mock_order_request(command: ImportMockRequest, context: MockContext, db: Db) -> MockOrderRequestView:
    """Import an existing controlled Mock source; submitted terms are never authority."""
    return _view(import_request(db, context, command.source_id, command.expected_source_version))


@router.get("/order-requests", response_model=list[MockOrderRequestView])
def list_mock_order_requests(context: MockContext, db: Db) -> list[MockOrderRequestView]:
    rows = db.scalars(select(OrderRequestRecord).where(
        OrderRequestRecord.tenant_id == context.tenant_id,
    ).order_by(OrderRequestRecord.created_at.desc())).all()
    return [_view(row) for row in rows]


@router.get("/order-requests/{order_request_id}", response_model=MockOrderRequestView)
def get_mock_order_request(order_request_id: str, context: MockContext, db: Db) -> MockOrderRequestView:
    return _view(get_request(db, context, order_request_id))


@router.post("/order-requests/{order_request_id}/review", response_model=MockOrderRequestView)
def review_mock_order_request(order_request_id: str, command: ReviewMockRequest,
                              context: MockContext, db: Db) -> MockOrderRequestView:
    return _view(review_request(db, context, order_request_id,
                                command.expected_request_version, command.decision, command.reason))


class AcceptMockRequest(ImmutableContract):
    expected_request_version: int = Field(ge=1, strict=True)
    expected_terms_hash: str = Field(pattern=r"^order-terms-v1:[0-9a-f]{64}$")
    expected_snapshot_version: int = Field(ge=1, strict=True)
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_-]{8,128}$")
    reason: str = Field(min_length=1, max_length=1000)


class AcceptMockResponse(ImmutableContract):
    order_request: MockOrderRequestView
    reservation: ReservationReceipt
    commitment: Commitment | None = None
    integration_mode: Literal["MOCK"] = "MOCK"
    evidence_tier: Literal["DEMO-ONLY"] = "DEMO-ONLY"


class MockResourceView(ImmutableContract):
    snapshot: EvaluationSnapshot
    integration_mode: Literal["MOCK"] = "MOCK"
    evidence_tier: Literal["DEMO-ONLY"] = "DEMO-ONLY"


@router.post("/mock-orbyte/resources", response_model=MockResourceView, status_code=201)
def create_mock_resources(command: MockResourceSeed, context: MockContext, db: Db) -> MockResourceView:
    return MockResourceView(snapshot=seed_mock_resources(db, context, command))


class MockFeasibilityView(ImmutableContract):
    order_request_id: str
    request_version: int
    terms_hash: str
    assessment: EvaluationResult
    integration_mode: Literal["MOCK"] = "MOCK"
    evidence_tier: Literal["DEMO-ONLY"] = "DEMO-ONLY"


@router.get("/mock-orbyte/resources", response_model=MockResourceView)
def read_mock_resources(context: MockContext, db: Db) -> MockResourceView:
    _, snapshot = MockOrbyteAdapter(db).read_state(context.tenant_id)
    return MockResourceView(snapshot=snapshot)


@router.get("/order-requests/{order_request_id}/feasibility", response_model=MockFeasibilityView)
def read_mock_feasibility(order_request_id: str, context: MockContext, db: Db) -> MockFeasibilityView:
    row = get_request(db, context, order_request_id)
    if row.decision_status != "REVIEWED":
        raise DomainError("REVIEW_REQUIRED", "Reviewed pending order required", status_code=409)
    _, snapshot = MockOrbyteAdapter(db).read_state(context.tenant_id)
    terms = OrderTerms.model_validate(row.terms)
    _, assessment = project_pending_order(
        snapshot, terms, commitment_id=f"com_{order_request_id}",
        checked_at=datetime.now(UTC), require_feasible=False,
    )
    return MockFeasibilityView(order_request_id=order_request_id,
                               request_version=row.request_version,
                               terms_hash=row.terms_hash, assessment=assessment)


@router.get("/mock-orbyte/reservations/{operation_id}", response_model=ReservationReceipt)
def read_mock_reservation(operation_id: str, context: MockContext, db: Db) -> ReservationReceipt:
    return MockOrbyteAdapter(db).read_reservation_status(context.tenant_id, operation_id)


@router.post("/order-requests/{order_request_id}/accept-mock", response_model=AcceptMockResponse)
def accept_mock_order_request(order_request_id: str, command: AcceptMockRequest,
                              context: MockContext, db: Db, response: Response) -> AcceptMockResponse:
    row, receipt = accept_mock_order(
        db, context, order_request_id,
        expected_request_version=command.expected_request_version,
        expected_terms_hash=command.expected_terms_hash,
        expected_snapshot_version=command.expected_snapshot_version,
        idempotency_key=command.idempotency_key, reason=command.reason,
    )
    if receipt.status == "UNKNOWN":
        response.status_code = 202
        return AcceptMockResponse(order_request=_view(row), reservation=receipt)
    if receipt.status == "FAILED":
        raise DomainError("MOCK_RESERVATION_REJECTED", "Mock Orbyte rejected reservation",
                          status_code=409, details={"operation_id": receipt.operation_id})
    return AcceptMockResponse(order_request=_view(row), reservation=receipt,
                              commitment=CommitmentService().get(db, context, row.commitment_id))


class ReconcileMockRequest(ImmutableContract):
    operation_id: str = Field(pattern=r"^mop_[0-9a-f]{32}$")


@router.post("/order-requests/{order_request_id}/reconcile-mock", response_model=AcceptMockResponse)
def reconcile_mock_order_request(order_request_id: str, command: ReconcileMockRequest,
                                 context: MockContext, db: Db) -> AcceptMockResponse:
    row, receipt = reconcile_mock_order(db, context, order_request_id, command.operation_id)
    return AcceptMockResponse(order_request=_view(row), reservation=receipt)


class MockTimelineEntry(ImmutableContract):
    event_type: str
    actor_id: str
    occurred_at: str
    evidence_refs: tuple[str, ...]
    source: Literal["ORDER_REQUEST", "CORE"]
    integration_mode: Literal["MOCK"] = "MOCK"


@router.get("/order-requests/{order_request_id}/timeline", response_model=list[MockTimelineEntry])
def mock_order_timeline(order_request_id: str, context: MockContext, db: Db) -> list[MockTimelineEntry]:
    row = get_request(db, context, order_request_id)
    events = [MockTimelineEntry(event_type=a.event_type, actor_id=a.actor_id,
                                occurred_at=a.occurred_at.isoformat(),
                                evidence_refs=tuple(a.evidence_refs), source="ORDER_REQUEST")
              for a in db.scalars(select(OrderRequestAuditRecord).where(
                  OrderRequestAuditRecord.tenant_id == context.tenant_id,
                  OrderRequestAuditRecord.order_request_id == order_request_id,
              )).all()]
    if row.commitment_id:
        events.extend(MockTimelineEntry(
            event_type=a.event_type, actor_id=a.actor_id,
            occurred_at=a.occurred_at.isoformat(),
            evidence_refs=tuple(a.evidence_refs), source="CORE",
        ) for a in db.scalars(select(AuditEventRecord).where(
            AuditEventRecord.tenant_id == context.tenant_id,
            AuditEventRecord.commitment_id == row.commitment_id,
        )).all())
    return sorted(events, key=lambda event: event.occurred_at)


class MockOperationalStatus(ImmutableContract):
    order_request_id: str
    commitment_id: str | None
    decision_status: str
    customer_status: str
    planned_delivery_at: str
    actual_production: Literal["NOT_AVAILABLE"] = "NOT_AVAILABLE"
    actual_delivery: Literal["NOT_AVAILABLE"] = "NOT_AVAILABLE"
    evidence_refs: tuple[str, ...]
    integration_mode: Literal["MOCK"] = "MOCK"
    evidence_tier: Literal["DEMO-ONLY"] = "DEMO-ONLY"


@router.get("/order-requests/{order_request_id}/operational-status", response_model=MockOperationalStatus)
def mock_operational_status(order_request_id: str, context: MockContext, db: Db) -> MockOperationalStatus:
    row = get_request(db, context, order_request_id)
    status = (read_status_preview(db, context, row.commitment_id).customer_status
              if row.commitment_id else "REQUEST_RECEIVED")
    terms = OrderTerms.model_validate(row.terms)
    return MockOperationalStatus(
        order_request_id=order_request_id, commitment_id=row.commitment_id,
        decision_status=row.decision_status, customer_status=status,
        planned_delivery_at=terms.window_end.isoformat(),
        evidence_refs=tuple(row.source_evidence_refs),
    )
