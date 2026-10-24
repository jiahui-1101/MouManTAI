"""Registered, isolated synthetic portfolio comparison API."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext, get_db
from app.optimization.mock_models import MockOptimizationDatasetRecord
from app.optimization.mock_service import (
    MockOptimizationComparisonView,
    MockOptimizationDatasetCreate,
    MockOptimizationDatasetView,
    _view,
    compare_dataset,
    get_dataset,
    seed_dataset,
)
from app.orders.router import mock_workflow_context

router = APIRouter(prefix="/v1/backend-v2/mock-optimization", tags=["v2.2 synthetic optimization"])
Context = Annotated[RequestContext, Depends(mock_workflow_context)]
Db = Annotated[Session, Depends(get_db)]


@router.post("/datasets", response_model=MockOptimizationDatasetView, status_code=201)
def create_dataset(command: MockOptimizationDatasetCreate, context: Context,
                   db: Db) -> MockOptimizationDatasetView:
    return seed_dataset(db, context, command)


@router.get("/datasets", response_model=list[MockOptimizationDatasetView])
def list_datasets(context: Context, db: Db) -> list[MockOptimizationDatasetView]:
    rows = db.scalars(select(MockOptimizationDatasetRecord).where(
        MockOptimizationDatasetRecord.tenant_id == context.tenant_id,
    ).order_by(MockOptimizationDatasetRecord.created_at, MockOptimizationDatasetRecord.dataset_id)).all()
    return [_view(row) for row in rows]


@router.get("/datasets/{dataset_id}", response_model=MockOptimizationDatasetView)
def read_dataset(dataset_id: str, context: Context, db: Db) -> MockOptimizationDatasetView:
    return _view(get_dataset(db, context, dataset_id))


@router.get("/datasets/{dataset_id}/comparison", response_model=MockOptimizationComparisonView)
def read_comparison(dataset_id: str, context: Context,
                    db: Db) -> MockOptimizationComparisonView:
    return compare_dataset(db, context, dataset_id)
