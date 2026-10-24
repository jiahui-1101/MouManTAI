"""Tenant-bound Mock supplier sources, real comparison and human choice."""

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import AwareDatetime, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.models import OutboxEventRecord
from app.orders.terms import ImmutableContract
from app.suppliers.comparison import (
    CategorySpec,
    OfferComparison,
    SupplierOffer,
    SupplierRequirement,
    compare_offers,
)
from app.suppliers.models import (
    MockSupplierAuditRecord,
    MockSupplierDatasetRecord,
    MockSupplierSelectionRecord,
)


class MockSupplierDatasetCreate(ImmutableContract):
    dataset_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    dataset_version: int = Field(ge=1, strict=True)
    spec: CategorySpec
    requirement: SupplierRequirement
    offers: tuple[SupplierOffer, ...] = Field(min_length=1)
    observed_at: AwareDatetime
    valid_through: AwareDatetime


class MockSupplierDatasetView(MockSupplierDatasetCreate):
    tenant_id: str
    actor_id: str
    integration_mode: Literal["MOCK"] = "MOCK"
    evidence_tier: Literal["DEMO-ONLY"] = "DEMO-ONLY"


class MockSupplierComparisonView(ImmutableContract):
    dataset_id: str
    dataset_version: int
    compared_at: AwareDatetime
    results: tuple[OfferComparison, ...]
    purchasing_authorized: Literal[False] = False
    integration_mode: Literal["MOCK"] = "MOCK"
    evidence_tier: Literal["DEMO-ONLY"] = "DEMO-ONLY"


class MockSupplierSelectionCommand(ImmutableContract):
    expected_dataset_version: int = Field(ge=1, strict=True)
    quote_id: str = Field(min_length=1, max_length=128)
    quote_version: int = Field(ge=1, strict=True)
    request_key: str = Field(pattern=r"^[A-Za-z0-9_-]{8,128}$")
    reason: str = Field(min_length=1, max_length=1000)


class MockSupplierSelectionView(ImmutableContract):
    selection_id: str
    dataset_id: str
    dataset_version: int
    supplier_id: str
    quote_id: str
    quote_version: int
    comparison_status: Literal["MATCHES", "CONDITIONAL"]
    actor_id: str
    reason: str
    evidence_refs: tuple[str, ...]
    selected_at: AwareDatetime
    purchasing_authorized: Literal[False] = False
    integration_mode: Literal["MOCK"] = "MOCK"
    evidence_tier: Literal["DEMO-ONLY"] = "DEMO-ONLY"


class MockRfqDraft(ImmutableContract):
    dataset_id: str
    category_id: str
    quantity: str
    unit: str
    needed_by: AwareDatetime
    required_properties: tuple[dict[str, str | bool | None], ...]
    status: Literal["DRAFT_ONLY"] = "DRAFT_ONLY"
    send_authorized: Literal[False] = False
    integration_mode: Literal["MOCK"] = "MOCK"
    evidence_tier: Literal["DEMO-ONLY"] = "DEMO-ONLY"


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _synthetic(refs) -> bool:
    return bool(refs) and all(ref.startswith("synthetic://") for ref in refs)


def _validate_source(context: RequestContext, command: MockSupplierDatasetCreate,
                     now: datetime) -> None:
    spec, requirement = command.spec, command.requirement
    if (spec.tenant_id != context.tenant_id or requirement.tenant_id != context.tenant_id
            or any(offer.tenant_id != context.tenant_id for offer in command.offers)
            or spec.category_id != requirement.category_id
            or spec.version != requirement.spec_version
            or spec.authority != "SME_CONFIG"
            or not spec.approval_ref or not spec.approval_ref.startswith("synthetic://")
            or not _synthetic(spec.evidence_refs)
            or not all(_synthetic(prop.evidence_refs) for prop in requirement.properties)
            or not all(_synthetic(offer.evidence_refs)
                       and all(_synthetic(prop.evidence_refs) for prop in offer.properties)
                       and (not offer.pack_evidence_refs or _synthetic(offer.pack_evidence_refs))
                       and (not offer.availability_evidence_refs or _synthetic(offer.availability_evidence_refs))
                       and (not offer.verification_evidence_refs or _synthetic(offer.verification_evidence_refs))
                       and (not offer.arrival_evidence_refs or _synthetic(offer.arrival_evidence_refs))
                       for offer in command.offers)
            or len({(offer.quote_id, offer.quote_version) for offer in command.offers}) != len(command.offers)
            or not _utc(command.observed_at) <= now < _utc(command.valid_through)):
        raise DomainError("MOCK_SUPPLIER_SOURCE_INVALID",
                          "Supplier fixture must be current, tenant-bound and explicitly synthetic",
                          status_code=422)


def _event(db: Session, context: RequestContext, dataset_id: str, event_type: str,
           reason: str, refs: list[str], now: datetime, detail: dict) -> None:
    audit_id = f"aud_{uuid4().hex}"
    db.add(MockSupplierAuditRecord(
        audit_id=audit_id, tenant_id=context.tenant_id, dataset_id=dataset_id,
        event_type=event_type, actor_id=context.actor_id, evidence_refs=refs,
        reason=reason, occurred_at=now,
    ))
    db.add(OutboxEventRecord(
        event_id=f"evt_{uuid4().hex}", tenant_id=context.tenant_id,
        event_type=event_type, commitment_id=None, commitment_version=None,
        correlation_id=context.correlation_id, causation_id=context.causation_id,
        occurred_at=now, payload={"dataset_id": dataset_id, "audit_id": audit_id,
                                  "integration_mode": "MOCK", "evidence_tier": "DEMO-ONLY",
                                  **detail},
        published_at=None, attempts=0, status="PENDING", last_error=None, next_retry_at=None,
    ))


def _view(row: MockSupplierDatasetRecord) -> MockSupplierDatasetView:
    return MockSupplierDatasetView(
        tenant_id=row.tenant_id, dataset_id=row.dataset_id,
        dataset_version=row.dataset_version,
        spec=CategorySpec.model_validate(row.spec),
        requirement=SupplierRequirement.model_validate(row.requirement),
        offers=tuple(SupplierOffer.model_validate(item) for item in row.offers),
        observed_at=_utc(row.observed_at), valid_through=_utc(row.valid_through),
        actor_id=row.actor_id,
    )


def seed_dataset(db: Session, context: RequestContext,
                 command: MockSupplierDatasetCreate) -> MockSupplierDatasetView:
    now = datetime.now(UTC)
    _validate_source(context, command, now)
    existing = db.get(MockSupplierDatasetRecord, (context.tenant_id, command.dataset_id))
    if existing is not None:
        if (existing.dataset_version != command.dataset_version
                or existing.spec != command.spec.model_dump(mode="json")
                or existing.requirement != command.requirement.model_dump(mode="json")
                or existing.offers != [offer.model_dump(mode="json") for offer in command.offers]):
            raise DomainError("MOCK_SUPPLIER_DATASET_CONFLICT", "Dataset ID already has other facts",
                              status_code=409)
        return _view(existing)
    row = MockSupplierDatasetRecord(
        tenant_id=context.tenant_id, dataset_id=command.dataset_id,
        dataset_version=command.dataset_version, category_id=command.spec.category_id,
        spec=command.spec.model_dump(mode="json"),
        requirement=command.requirement.model_dump(mode="json"),
        offers=[offer.model_dump(mode="json") for offer in command.offers],
        observed_at=command.observed_at, valid_through=command.valid_through,
        actor_id=context.actor_id, created_at=now,
    )
    db.add(row)
    _event(db, context, row.dataset_id, "supplier.mock_dataset_seeded",
           "Controlled synthetic supplier dataset", list(command.spec.evidence_refs), now,
           {"dataset_version": row.dataset_version})
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return _view(row)


def get_dataset(db: Session, context: RequestContext, dataset_id: str,
                *, lock: bool = False) -> MockSupplierDatasetRecord:
    stmt = select(MockSupplierDatasetRecord).where(
        MockSupplierDatasetRecord.tenant_id == context.tenant_id,
        MockSupplierDatasetRecord.dataset_id == dataset_id,
    )
    row = db.scalar(stmt.with_for_update() if lock else stmt)
    if row is None:
        raise DomainError("MOCK_SUPPLIER_DATASET_NOT_FOUND", "Supplier dataset not found", status_code=404)
    return row


def compare_dataset(db: Session, context: RequestContext,
                    dataset_id: str) -> MockSupplierComparisonView:
    row = get_dataset(db, context, dataset_id)
    now = datetime.now(UTC)
    if not _utc(row.observed_at) <= now < _utc(row.valid_through):
        raise DomainError("MOCK_SUPPLIER_SOURCE_STALE", "Supplier dataset is expired", status_code=409)
    try:
        data = _view(row)
        results = compare_offers(data.spec, data.requirement, data.offers, now=now)
    except (ValueError, ValidationError) as exc:
        raise DomainError("MOCK_SUPPLIER_SOURCE_INVALID", "Saved supplier dataset is invalid",
                          status_code=409) from exc
    return MockSupplierComparisonView(dataset_id=dataset_id, dataset_version=row.dataset_version,
                                      compared_at=now, results=results)


def _selection_view(row: MockSupplierSelectionRecord) -> MockSupplierSelectionView:
    return MockSupplierSelectionView(
        selection_id=row.selection_id, dataset_id=row.dataset_id,
        dataset_version=row.dataset_version, supplier_id=row.supplier_id,
        quote_id=row.quote_id, quote_version=row.quote_version,
        comparison_status=row.comparison_status, actor_id=row.actor_id,
        reason=row.reason, evidence_refs=tuple(row.evidence_refs),
        selected_at=_utc(row.selected_at),
    )


def select_supplier(db: Session, context: RequestContext, dataset_id: str,
                    command: MockSupplierSelectionCommand) -> MockSupplierSelectionView:
    row = get_dataset(db, context, dataset_id, lock=True)
    prior_key = db.scalar(select(MockSupplierSelectionRecord).where(
        MockSupplierSelectionRecord.tenant_id == context.tenant_id,
        MockSupplierSelectionRecord.request_key == command.request_key,
    ))
    if prior_key is not None:
        if (prior_key.dataset_id, prior_key.dataset_version,
                prior_key.quote_id, prior_key.quote_version, prior_key.reason) != (
                dataset_id, command.expected_dataset_version,
                command.quote_id, command.quote_version, command.reason):
            raise DomainError("MOCK_SUPPLIER_KEY_CONFLICT", "Selection key has different content",
                              status_code=409)
        return _selection_view(prior_key)
    if row.dataset_version != command.expected_dataset_version:
        raise DomainError("MOCK_SUPPLIER_VERSION_CONFLICT", "Supplier dataset changed", status_code=409)
    prior_choice = db.scalar(select(MockSupplierSelectionRecord).where(
        MockSupplierSelectionRecord.tenant_id == context.tenant_id,
        MockSupplierSelectionRecord.dataset_id == dataset_id,
    ))
    if prior_choice is not None:
        raise DomainError("MOCK_SUPPLIER_ALREADY_SELECTED", "Dataset already has a human choice",
                          status_code=409)
    comparison = compare_dataset(db, context, dataset_id)
    offer = next((item for item in row.offers if item["quote_id"] == command.quote_id
                  and item["quote_version"] == command.quote_version), None)
    if offer is None:
        raise DomainError("MOCK_SUPPLIER_QUOTE_NOT_FOUND", "Quote not found", status_code=404)
    result = next(item for item in comparison.results if item.quote_id == command.quote_id
                  and item.quote_version == command.quote_version)
    if result.status not in {"MATCHES", "CONDITIONAL"}:
        raise DomainError("MOCK_SUPPLIER_NOT_SELECTABLE", "Quote fails hard requirements or source checks",
                          status_code=409)
    now = datetime.now(UTC)
    selection = MockSupplierSelectionRecord(
        tenant_id=context.tenant_id, selection_id=f"ssel_{uuid4().hex}",
        dataset_id=dataset_id, dataset_version=row.dataset_version,
        request_key=command.request_key, supplier_id=offer["supplier_id"],
        quote_id=command.quote_id, quote_version=command.quote_version,
        comparison_status=result.status, actor_id=context.actor_id,
        reason=command.reason, evidence_refs=list(result.evidence_refs), selected_at=now,
    )
    db.add(selection)
    _event(db, context, dataset_id, "supplier.mock_selection_recorded", command.reason,
           selection.evidence_refs, now,
           {"selection_id": selection.selection_id, "quote_id": selection.quote_id,
            "dataset_version": selection.dataset_version, "purchase_authorized": False})
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return _selection_view(selection)


def rfq_draft(db: Session, context: RequestContext, dataset_id: str) -> MockRfqDraft:
    row = get_dataset(db, context, dataset_id)
    if not _utc(row.observed_at) <= datetime.now(UTC) < _utc(row.valid_through):
        raise DomainError("MOCK_SUPPLIER_SOURCE_STALE", "Supplier dataset is expired", status_code=409)
    requirement = SupplierRequirement.model_validate(row.requirement)
    return MockRfqDraft(
        dataset_id=dataset_id, category_id=requirement.category_id,
        quantity=str(requirement.quantity), unit=requirement.unit,
        needed_by=requirement.needed_by,
        required_properties=tuple({"name": prop.name, "value": prop.value,
                                   "unit": prop.unit} for prop in requirement.properties),
    )
