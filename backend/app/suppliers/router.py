"""Registered Mock supplier advisory API in the isolated synthetic tenant."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext, get_db
from app.orders.router import mock_workflow_context
from app.suppliers.mock_service import (
    MockRfqDraft,
    MockSupplierComparisonView,
    MockSupplierDatasetCreate,
    MockSupplierDatasetView,
    MockSupplierSelectionCommand,
    MockSupplierSelectionView,
    _selection_view,
    _view,
    compare_dataset,
    get_dataset,
    rfq_draft,
    seed_dataset,
    select_supplier,
)
from app.suppliers.models import MockSupplierDatasetRecord, MockSupplierSelectionRecord

router = APIRouter(prefix="/v1/backend-v2/mock-suppliers", tags=["v2.2 synthetic suppliers"])
Context = Annotated[RequestContext, Depends(mock_workflow_context)]
Db = Annotated[Session, Depends(get_db)]


@router.post("/datasets", response_model=MockSupplierDatasetView, status_code=201)
def create_dataset(command: MockSupplierDatasetCreate, context: Context, db: Db) -> MockSupplierDatasetView:
    return seed_dataset(db, context, command)


@router.get("/datasets", response_model=list[MockSupplierDatasetView])
def list_datasets(context: Context, db: Db) -> list[MockSupplierDatasetView]:
    rows = db.scalars(select(MockSupplierDatasetRecord).where(
        MockSupplierDatasetRecord.tenant_id == context.tenant_id,
    ).order_by(MockSupplierDatasetRecord.created_at, MockSupplierDatasetRecord.dataset_id)).all()
    return [_view(row) for row in rows]


@router.get("/datasets/{dataset_id}", response_model=MockSupplierDatasetView)
def read_dataset(dataset_id: str, context: Context, db: Db) -> MockSupplierDatasetView:
    return _view(get_dataset(db, context, dataset_id))


@router.get("/datasets/{dataset_id}/comparison", response_model=MockSupplierComparisonView)
def read_comparison(dataset_id: str, context: Context, db: Db) -> MockSupplierComparisonView:
    return compare_dataset(db, context, dataset_id)


@router.post("/datasets/{dataset_id}/selection", response_model=MockSupplierSelectionView,
             status_code=201)
def choose_supplier(dataset_id: str, command: MockSupplierSelectionCommand,
                    context: Context, db: Db) -> MockSupplierSelectionView:
    return select_supplier(db, context, dataset_id, command)


@router.get("/datasets/{dataset_id}/selection", response_model=MockSupplierSelectionView)
def read_selection(dataset_id: str, context: Context, db: Db) -> MockSupplierSelectionView:
    get_dataset(db, context, dataset_id)
    row = db.scalar(select(MockSupplierSelectionRecord).where(
        MockSupplierSelectionRecord.tenant_id == context.tenant_id,
        MockSupplierSelectionRecord.dataset_id == dataset_id,
    ))
    if row is None:
        from app.core.errors import DomainError
        raise DomainError("MOCK_SUPPLIER_SELECTION_NOT_FOUND", "No supplier has been selected",
                          status_code=404)
    return _selection_view(row)


@router.get("/datasets/{dataset_id}/rfq-draft", response_model=MockRfqDraft)
def read_rfq_draft(dataset_id: str, context: Context, db: Db) -> MockRfqDraft:
    return rfq_draft(db, context, dataset_id)
