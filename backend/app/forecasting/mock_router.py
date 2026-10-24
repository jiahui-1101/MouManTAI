"""Registered source-backed, advisory-only Mock forecasting routes."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext, get_db
from app.forecasting.mock_models import MockForecastDatasetRecord
from app.forecasting.mock_service import (
    MockForecastBacktestView,
    MockForecastBaselineView,
    MockForecastDatasetCreate,
    MockForecastDatasetView,
    _view,
    backtest,
    baseline,
    get_dataset,
    seed_dataset,
)
from app.orders.router import mock_workflow_context

router = APIRouter(prefix="/v1/backend-v2/mock-forecasts", tags=["v2.2 synthetic forecasts"])
Context = Annotated[RequestContext, Depends(mock_workflow_context)]
Db = Annotated[Session, Depends(get_db)]


@router.post("/datasets", response_model=MockForecastDatasetView, status_code=201)
def create_dataset(command: MockForecastDatasetCreate, context: Context,
                   db: Db) -> MockForecastDatasetView:
    return seed_dataset(db, context, command)


@router.get("/datasets", response_model=list[MockForecastDatasetView])
def list_datasets(context: Context, db: Db) -> list[MockForecastDatasetView]:
    rows = db.scalars(select(MockForecastDatasetRecord).where(
        MockForecastDatasetRecord.tenant_id == context.tenant_id,
    ).order_by(MockForecastDatasetRecord.created_at, MockForecastDatasetRecord.dataset_id)).all()
    return [_view(row) for row in rows]


@router.get("/datasets/{dataset_id}", response_model=MockForecastDatasetView)
def read_dataset(dataset_id: str, context: Context, db: Db) -> MockForecastDatasetView:
    return _view(get_dataset(db, context, dataset_id))


@router.get("/datasets/{dataset_id}/baseline", response_model=MockForecastBaselineView)
def read_baseline(dataset_id: str, context: Context, db: Db,
                  horizon: Annotated[int, Query(ge=1, le=30)] = 7
                  ) -> MockForecastBaselineView:
    return baseline(db, context, dataset_id, horizon)


@router.get("/datasets/{dataset_id}/backtest", response_model=MockForecastBacktestView)
def read_backtest(dataset_id: str, context: Context, db: Db,
                  train_cutoff: date,
                  horizon: Annotated[int, Query(ge=1, le=30)] = 1
                  ) -> MockForecastBacktestView:
    return backtest(db, context, dataset_id, train_cutoff, horizon)
