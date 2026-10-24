"""Registered DEMO decision-memory insight routes."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext, get_db
from app.decision_memory.mock_models import MockMemoryDatasetRecord
from app.decision_memory.mock_service import (
    MockMemoryDatasetCreate,
    MockMemoryDatasetView,
    MockMemoryInsightView,
    _view,
    get_dataset,
    insights,
    seed_dataset,
)
from app.decision_memory.models import CurrentSituation
from app.orders.router import mock_workflow_context

router = APIRouter(prefix="/v1/backend-v2/mock-memory", tags=["v2.2 synthetic decision memory"])
Context = Annotated[RequestContext, Depends(mock_workflow_context)]
Db = Annotated[Session, Depends(get_db)]


@router.post("/datasets", response_model=MockMemoryDatasetView, status_code=201)
def create_dataset(command: MockMemoryDatasetCreate, context: Context,
                   db: Db) -> MockMemoryDatasetView:
    return seed_dataset(db, context, command)


@router.get("/datasets", response_model=list[MockMemoryDatasetView])
def list_datasets(context: Context, db: Db) -> list[MockMemoryDatasetView]:
    rows = db.scalars(select(MockMemoryDatasetRecord).where(
        MockMemoryDatasetRecord.tenant_id == context.tenant_id,
    ).order_by(MockMemoryDatasetRecord.created_at, MockMemoryDatasetRecord.dataset_id)).all()
    return [_view(row) for row in rows]


@router.get("/datasets/{dataset_id}", response_model=MockMemoryDatasetView)
def read_dataset(dataset_id: str, context: Context, db: Db) -> MockMemoryDatasetView:
    return _view(get_dataset(db, context, dataset_id))


@router.post("/datasets/{dataset_id}/insights", response_model=MockMemoryInsightView)
def read_insights(dataset_id: str, current: CurrentSituation,
                  context: Context, db: Db) -> MockMemoryInsightView:
    """Read-only analysis; POST carries structured context but mutates no business state."""
    return insights(db, context, dataset_id, current)
