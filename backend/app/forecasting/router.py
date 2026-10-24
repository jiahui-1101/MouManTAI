"""HTTP router for Forecast & Forward Planning.

Adheres strictly to REQUIREMENTS_BACKEND.md Section 10 and REQUIREMENTS_FRONTEND.md Section 7:
- GET /v1/forecasts: Baseline predictions, retrospective backtest metrics, and 4-family risk advisories
- Proactive risk views: DEMAND, STOCKOUT_OR_EXPIRY, SUPPLIER_DELAY, CAPACITY_OR_DEADLINE
- Evidence-gated: Prominently marks synthetic data as DEMO-ONLY with uncalibrated uncertainty
- Forecasts are advisory only and NEVER mutate inventory or authorize operational actions
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.dependencies import ACTOR_ROLES, RequestContext, get_db
from app.forecasting.adapters import (
    DatabaseDemandReader,
    DemoDemandReader,
    DemoP2ForwardScenarioReader,
    DemoSnapshotReader,
    DemoSupplierHistoryReader,
)
from app.forecasting.baselines import MovingAverage, Naive, SeasonalNaive
from app.forecasting.models import (
    ForecastAlert,
    ForecastPoint,
    ForecastRun,
    ForecastStatus,
    Mode,
    RiskFamily,
    SourceUnavailable,
    Tier,
)
from app.forecasting.service import ForecastService
from app.forecasting.source_validation import ValidatedSeries

router = APIRouter(prefix="/v1/forecasts", tags=["forecasting"])


def get_forecast_context(
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
    x_actor_id: Annotated[str | None, Header(alias="X-Actor-ID")] = None,
    x_correlation_id: Annotated[str | None, Header(alias="X-Correlation-ID")] = None,
) -> RequestContext:
    tenant = x_tenant_id or "demo-tenant"
    actor = x_actor_id or "user_manager_01"
    role = ACTOR_ROLES.get(actor, "MANAGER")
    correlation = x_correlation_id or f"corr_{uuid4().hex}"
    return RequestContext(
        tenant_id=tenant,
        actor_id=actor,
        actor_role=role,
        correlation_id=correlation,
    )


class HistoricalPointSchema(BaseModel):
    period: str
    quantity: Decimal
    unit: str
    kind: str
    evidence_ref: str


class ForecastPointSchema(BaseModel):
    period: str
    quantity: Decimal
    unit: str


class MetricSchema(BaseModel):
    value: Decimal | None = None
    unavailable_reason: str | None = None


class BacktestSummarySchema(BaseModel):
    model_name: str
    model_version: str
    mae: MetricSchema
    wape: MetricSchema
    mase: MetricSchema
    signed_bias: MetricSchema
    evidence_coverage: Decimal
    eligible_actuals: int


class ForecastAlertSchema(BaseModel):
    alert_id: str
    family: str
    target_id: str
    period: str
    status: str
    exposure: str
    unit: str | None = None
    magnitude: Decimal | None = None
    evidence_tier: str
    integration_mode: str
    uncertainty: str
    missing_data: list[str]
    explanation_codes: list[str]
    preparation_options: list[str]
    required_human_review: bool = True
    operational_action_authorized: bool = False


class SkuOption(BaseModel):
    sku_id: str
    name: str
    category: str
    unit: str


class ForecastResponse(BaseModel):
    tenant_id: str
    sku_id: str
    available_skus: list[SkuOption]
    unit: str
    target_definition: str
    status: str
    evidence_tier: str
    integration_mode: str
    is_synthetic: bool
    demo_badge: bool
    training_cutoff: str
    horizon: int
    model_name: str
    model_version: str
    run_id: str
    generated_at: str
    historical_points: list[HistoricalPointSchema]
    forecast_points: list[ForecastPointSchema]
    backtest_metrics: list[BacktestSummarySchema]
    advisories: list[ForecastAlertSchema]
    diagnostics: list[str]
    assumptions: list[str]
    limitations: list[str]
    disclaimer: str


DEFAULT_SKUS = [
    SkuOption(sku_id="SKU-PROD-A", name="Custom Artisan Pastry Box", category="Bakery", unit="boxes"),
    SkuOption(sku_id="SKU-PROD-B", name="Specialty Sourdough Loaf", category="Bakery", unit="loaves"),
    SkuOption(sku_id="SKU-PACK-01", name="Eco Gift Packaging 250g", category="Packaging", unit="packs"),
    SkuOption(sku_id="SKU-RAW-FLOUR", name="Organic Stoneground Wheat Flour", category="Raw Material", unit="kg"),
]


@router.get("", response_model=ForecastResponse)
def get_forecasts(
    context: Annotated[RequestContext, Depends(get_forecast_context)],
    db: Annotated[Session, Depends(get_db)],
    sku_id: str = Query(default="SKU-PROD-A", description="Target SKU identifier"),
    horizon: int = Query(default=7, ge=1, le=30, description="Forward forecast horizon in days"),
    model: str = Query(default="moving_average", description="Baseline model: moving_average, seasonal_naive, naive"),
    mode: str = Query(default="auto", description="Data mode: auto, synthetic, or db"),
    supplier_id: str | None = Query(default=None, description="Optional supplier ID for delay advisory"),
) -> ForecastResponse:
    now = datetime.now(UTC)
    cutoff = now.date()
    # Keep snapshot captured_at strictly in the past relative to now
    snapshot_time = now - timedelta(seconds=1)

    selected_model = (
        SeasonalNaive(7)
        if model == "seasonal_naive"
        else Naive()
        if model == "naive"
        else MovingAverage(7)
    )

    # Determine reader: DB or Demo
    is_synthetic = False
    chosen_reader = None

    if mode == "db":
        db_reader = DatabaseDemandReader(db, unit="pcs", as_of=snapshot_time)
        service = ForecastService(
            demand_reader=db_reader,
            snapshot_reader=None,
            p2_reader=None,
            supplier_reader=None,
        )
        readiness = service.readiness(context.tenant_id, sku_id, "pcs", cutoff, now)
        if isinstance(readiness, ValidatedSeries) and readiness.status == ForecastStatus.AVAILABLE:
            chosen_reader = db_reader
        else:
            return ForecastResponse(
                tenant_id=context.tenant_id,
                sku_id=sku_id,
                available_skus=DEFAULT_SKUS,
                unit="pcs",
                target_definition="accepted-order quantity by SKU and business day",
                status=ForecastStatus.INSUFFICIENT.value,
                evidence_tier=Tier.TARGET.value,
                integration_mode=Mode.LIVE.value,
                is_synthetic=False,
                demo_badge=False,
                training_cutoff=cutoff.isoformat(),
                horizon=horizon,
                model_name=selected_model.name,
                model_version=selected_model.version,
                run_id=f"insufficient-db-{context.tenant_id}-{sku_id}",
                generated_at=now.isoformat(),
                historical_points=[],
                forecast_points=[],
                backtest_metrics=[],
                advisories=[
                    ForecastAlertSchema(
                        alert_id=f"alert-insufficient-{sku_id}",
                        family=RiskFamily.DEMAND.value,
                        target_id=sku_id,
                        period=cutoff.isoformat(),
                        status="INSUFFICIENT_HISTORY",
                        exposure="Fewer than 7 days of accepted commitments found in database for this SKU.",
                        evidence_tier=Tier.TARGET.value,
                        integration_mode=Mode.LIVE.value,
                        uncertainty="Cannot construct forecast without sufficient historical observations.",
                        missing_data=["At least 7 daily accepted order observations required."],
                        explanation_codes=["INSUFFICIENT_HISTORY"],
                        preparation_options=["Switch to 'Demo / Synthetic' mode to view interactive baseline mechanics."],
                        required_human_review=True,
                        operational_action_authorized=False,
                    )
                ],
                diagnostics=["INSUFFICIENT_HISTORY"],
                assumptions=["Requires verified chronological accepted commitments."],
                limitations=["No authoritative predictions available until sufficient order history accumulates."],
                disclaimer="Authoritative DB mode: Real historical data is insufficient. Switch to Demo mode to preview baseline algorithms.",
            )
    elif mode == "auto":
        db_reader = DatabaseDemandReader(db, unit="pcs", as_of=snapshot_time)
        check_service = ForecastService(demand_reader=db_reader)
        readiness = check_service.readiness(context.tenant_id, sku_id, "pcs", cutoff, now)
        if isinstance(readiness, ValidatedSeries) and readiness.status == ForecastStatus.AVAILABLE:
            chosen_reader = db_reader
            is_synthetic = False
        else:
            chosen_reader = DemoDemandReader(days=21, unit="pcs", as_of=snapshot_time)
            is_synthetic = True
    else:
        chosen_reader = DemoDemandReader(days=21, unit="pcs", as_of=snapshot_time)
        is_synthetic = True

    # Assemble service with scenario readers
    if is_synthetic:
        snapshot_reader = DemoSnapshotReader(captured_at=snapshot_time)
        p2_reader = DemoP2ForwardScenarioReader(watermark=snapshot_time)
        supplier_reader = DemoSupplierHistoryReader()
    else:
        snapshot_reader = None
        p2_reader = None
        supplier_reader = None

    service = ForecastService(
        demand_reader=chosen_reader,
        snapshot_reader=snapshot_reader,
        p2_reader=p2_reader,
        supplier_reader=supplier_reader,
    )

    manifest, observations = chosen_reader.read(context.tenant_id, sku_id, cutoff)
    run = service.baseline(
        context.tenant_id,
        sku_id,
        "pcs",
        cutoff=cutoff,
        horizon=horizon,
        now=now,
        model=selected_model,
    )

    if isinstance(run, SourceUnavailable):
        status_val = ForecastStatus.UNAVAILABLE.value
        points: list[ForecastPointSchema] = []
        diagnostics = ["SOURCE_UNAVAILABLE"]
        run_id = f"unavailable-{sku_id}"
    else:
        status_val = run.status.value
        points = [
            ForecastPointSchema(
                period=p.period.isoformat(),
                quantity=p.quantity,
                unit=run.unit,
            )
            for p in run.points
        ]
        diagnostics = list(run.diagnostics)
        run_id = run.run_id

    # Compute backtest retrospective metrics on previous window
    backtest_reports = []
    try:
        eval_reports = service.evaluate(
            context.tenant_id,
            sku_id,
            "pcs",
            cutoff=cutoff - timedelta(days=7),
            test_end=cutoff,
            now=now,
            horizon=1,
        )
        if eval_reports and not isinstance(eval_reports, SourceUnavailable):
            for report in eval_reports:
                backtest_reports.append(
                    BacktestSummarySchema(
                        model_name=report.model_name,
                        model_version=report.model_version,
                        mae=MetricSchema(value=report.mae.value, unavailable_reason=report.mae.unavailable_reason),
                        wape=MetricSchema(value=report.wape.value, unavailable_reason=report.wape.unavailable_reason),
                        mase=MetricSchema(value=report.mase.value, unavailable_reason=report.mase.unavailable_reason),
                        signed_bias=MetricSchema(value=report.signed_bias.value, unavailable_reason=report.signed_bias.unavailable_reason),
                        evidence_coverage=report.evidence_coverage,
                        eligible_actuals=report.eligible_actuals,
                    )
                )
    except Exception:
        backtest_reports = []

    # Advisories
    advisories: list[ForecastAlertSchema] = []
    if not isinstance(run, SourceUnavailable):
        raw_advisories = service.advisories(run, supplier_id=supplier_id, as_of=now)
        for a in raw_advisories:
            advisories.append(
                ForecastAlertSchema(
                    alert_id=a.alert_id,
                    family=a.family.value,
                    target_id=a.target_id,
                    period=a.period.isoformat(),
                    status=a.status,
                    exposure=a.exposure,
                    unit=a.unit,
                    magnitude=a.magnitude,
                    evidence_tier=a.evidence_tier.value,
                    integration_mode=a.integration_mode.value,
                    uncertainty=a.uncertainty,
                    missing_data=list(a.missing_data),
                    explanation_codes=list(a.explanation_codes),
                    preparation_options=list(a.preparation_options),
                    required_human_review=a.required_human_review,
                    operational_action_authorized=a.operational_action_authorized,
                )
            )

    historical_points = [
        HistoricalPointSchema(
            period=obs.period.isoformat(),
            quantity=obs.quantity or Decimal(0),
            unit=obs.unit,
            kind=obs.kind.value,
            evidence_ref=obs.evidence_ref,
        )
        for obs in observations
        if obs.quantity is not None
    ]

    tier = Tier.DEMO_ONLY.value if is_synthetic else Tier.TARGET.value
    mode_val = Mode.SYNTHETIC.value if is_synthetic else Mode.LIVE.value
    disclaimer = (
        "DEMO-ONLY: This forecast is derived from synthetic baseline mechanics. "
        "It does not demonstrate real-world predictive accuracy. Forecast advisories "
        "NEVER mutate authoritative inventory or trigger automated recovery actions."
        if is_synthetic
        else "Authoritative baseline: Calculated from accepted SME commitments. "
        "Advisory only; does not replace human reservation authority."
    )

    return ForecastResponse(
        tenant_id=context.tenant_id,
        sku_id=sku_id,
        available_skus=DEFAULT_SKUS,
        unit="pcs",
        target_definition="accepted-order quantity by SKU and business day",
        status=status_val,
        evidence_tier=tier,
        integration_mode=mode_val,
        is_synthetic=is_synthetic,
        demo_badge=is_synthetic,
        training_cutoff=cutoff.isoformat(),
        horizon=horizon,
        model_name=selected_model.name,
        model_version=selected_model.version,
        run_id=run_id,
        generated_at=now.isoformat(),
        historical_points=historical_points,
        forecast_points=points,
        backtest_metrics=backtest_reports,
        advisories=advisories,
        diagnostics=diagnostics,
        assumptions=[f"{selected_model.name} algorithm; observed accepted daily demand only"],
        limitations=["Planning guidance only; not a confirmed booking or reservation."],
        disclaimer=disclaimer,
    )


@router.get("/skus", response_model=list[SkuOption])
def list_skus() -> list[SkuOption]:
    return DEFAULT_SKUS
