"""Read-only orchestration. Inject authenticated owner adapters server-side."""

from __future__ import annotations

from datetime import date, datetime

from .backtesting import compare_on_same_holdout
from .baselines import ForecastModel, MovingAverage, Naive, SeasonalNaive, forecast
from .models import BacktestReport, ForecastAlert, ForecastRun, ForecastStatus, SourceUnavailable
from .ports import (
    CurrentSnapshotReader,
    DemandReader,
    P2ForwardScenarioReader,
    SupplierHistoryReader,
)
from .risk import demand_alert, supplier_alert
from .scenarios import capacity_or_deadline, stockout_or_expiry
from .source_validation import ValidatedSeries, validate_series


class ForecastService:
    def __init__(
        self,
        *,
        demand_reader: DemandReader | None = None,
        snapshot_reader: CurrentSnapshotReader | None = None,
        p2_reader: P2ForwardScenarioReader | None = None,
        supplier_reader: SupplierHistoryReader | None = None,
    ):
        self.demand_reader = demand_reader
        self.snapshot_reader = snapshot_reader
        self.p2_reader = p2_reader
        self.supplier_reader = supplier_reader

    def readiness(
        self, tenant_id: str, sku_id: str, unit: str, cutoff: date, now: datetime
    ) -> ValidatedSeries | SourceUnavailable:
        if self.demand_reader is None:
            return SourceUnavailable()
        manifest, observations = self.demand_reader.read(tenant_id, sku_id, cutoff)
        return validate_series(
            manifest,
            observations,
            tenant_id=tenant_id,
            sku_id=sku_id,
            unit=unit,
            cutoff=cutoff,
            now=now,
            trusted_reader=True,
        )

    def baseline(
        self,
        tenant_id: str,
        sku_id: str,
        unit: str,
        cutoff: date,
        horizon: int,
        now: datetime,
        model: ForecastModel | None = None,
    ) -> ForecastRun | SourceUnavailable:
        series = self.readiness(tenant_id, sku_id, unit, cutoff, now)
        if isinstance(series, SourceUnavailable):
            return series
        return forecast(
            series, model or MovingAverage(), cutoff=cutoff, horizon=horizon, generated_at=now
        )

    def evaluate(
        self,
        tenant_id: str,
        sku_id: str,
        unit: str,
        cutoff: date,
        test_end: date,
        now: datetime,
        *,
        horizon: int = 1,
    ) -> tuple[BacktestReport, ...] | SourceUnavailable | None:
        series = self.readiness(tenant_id, sku_id, unit, test_end, now)
        if isinstance(series, SourceUnavailable) or series.status != ForecastStatus.AVAILABLE:
            return SourceUnavailable() if isinstance(series, SourceUnavailable) else None
        return compare_on_same_holdout(
            series,
            (MovingAverage(), SeasonalNaive(), Naive()),
            train_cutoff=cutoff,
            test_end=test_end,
            horizon=horizon,
        )

    def advisories(
        self, run: ForecastRun, *, supplier_id: str | None = None
    ) -> tuple[ForecastAlert, ...]:
        snapshot = (
            self.snapshot_reader.read(run.tenant_id, run.sku_id) if self.snapshot_reader else None
        )
        period = run.points[0].period if run.points else run.training_cutoff
        attestation = None
        if self.p2_reader and snapshot and run.status == ForecastStatus.AVAILABLE:
            attestation = self.p2_reader.evaluate(run.tenant_id, run.sku_id, run.run_id, period)
        summary = (
            self.supplier_reader.read(run.tenant_id, supplier_id)
            if self.supplier_reader and supplier_id
            else None
        )
        return (
            demand_alert(run),
            stockout_or_expiry(run, snapshot, attestation),
            supplier_alert(run, summary),
            capacity_or_deadline(run, snapshot, attestation),
        )
