from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator


def aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("offset-aware datetime required")
    return value


def finite_nonnegative(value: Decimal) -> Decimal:
    if not value.is_finite() or value < 0:
        raise ValueError("finite nonnegative quantity required")
    return value


Aware = Annotated[datetime, AfterValidator(aware)]
Quantity = Annotated[Decimal, AfterValidator(finite_nonnegative)]


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Mode(StrEnum):
    SYNTHETIC = "SYNTHETIC"
    MOCK = "MOCK"
    LIVE = "LIVE"


class Tier(StrEnum):
    DEMO_ONLY = "DEMO-ONLY"
    TARGET = "TARGET"
    VALIDATED = "VALIDATED"
    LIVE = "LIVE"


class DemandKind(StrEnum):
    INQUIRY = "INQUIRY"
    DRAFT = "DRAFT"
    PENDING = "PENDING_ACCEPTANCE"
    ACCEPTED = "ACCEPTED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"
    KNOWN_ZERO = "KNOWN_ZERO"
    UNKNOWN = "UNKNOWN"


TARGET = "accepted-order quantity by SKU and business day"


class ForecastSourceManifest(Frozen):
    tenant_id: str
    source_dataset_id: str
    source_snapshot_id: str
    source_snapshot_version: str
    source_system: str
    integration_mode: Mode
    evidence_tier: Tier
    captured_at: Aware
    complete_through: date
    historical_window_start: date
    historical_window_end: date
    source_watermark: Aware
    pagination_complete: bool
    source_population_complete: bool
    input_version: str
    missing_source_ids: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...]
    reader_attestation: str


class DemandObservation(Frozen):
    tenant_id: str
    sku_id: str
    observation_id: str
    observation_version: int = Field(ge=1)
    supersedes_version: int | None = None
    period: date
    quantity: Quantity | None
    unit: str
    kind: DemandKind
    source_event_ref: str
    acceptance_ref: str | None = None
    evidence_ref: str
    source_version: str
    recorded_at: Aware
    business_timezone: str
    evidence_tier: Tier
    integration_mode: Mode

    @model_validator(mode="after")
    def coherent(self) -> DemandObservation:
        ZoneInfo(self.business_timezone)
        if self.kind in (DemandKind.ACCEPTED, DemandKind.KNOWN_ZERO):
            if self.quantity is None:
                raise ValueError("known demand requires quantity")
            if self.kind == DemandKind.KNOWN_ZERO and self.quantity != 0:
                raise ValueError("known zero must equal zero")
            if self.kind == DemandKind.ACCEPTED and not self.acceptance_ref:
                raise ValueError("accepted demand requires acceptance provenance")
        elif self.quantity is not None:
            raise ValueError("non-target or unknown observation cannot carry quantity")
        return self


class ForecastStatus(StrEnum):
    AVAILABLE = "FORECAST_AVAILABLE"
    INSUFFICIENT = "INSUFFICIENT_HISTORY"
    INCOMPLETE = "SOURCE_INCOMPLETE"
    STALE = "SOURCE_STALE"
    UNSUPPORTED = "UNSUPPORTED_TARGET"
    INVALID = "INVALID_INPUT"
    UNAVAILABLE = "SOURCE_UNAVAILABLE"


class ForecastPoint(Frozen):
    period: date
    quantity: Quantity


class ForecastRun(Frozen):
    run_id: str
    tenant_id: str
    sku_id: str
    target_definition: str = TARGET
    model_name: str
    model_version: str = "1"
    training_cutoff: date
    input_window_start: date | None
    horizon: int = Field(ge=1, le=365)
    points: tuple[ForecastPoint, ...] = ()
    unit: str
    evidence_tier: Tier
    integration_mode: Mode
    source_refs: tuple[str, ...]
    status: ForecastStatus
    diagnostics: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    generated_at: Aware


class Metric(Frozen):
    value: Decimal | None
    unavailable_reason: str | None = None


class BacktestRow(Frozen):
    origin: date
    period: date
    prediction: Decimal | None
    actual: Decimal | None
    reason: str | None = None


class BacktestReport(Frozen):
    tenant_id: str
    sku_id: str
    target_definition: str = TARGET
    model_name: str
    model_version: str = "1"
    cutoff: date
    evaluation_horizon: int
    training_sample_size: int
    training_naive_scale: Metric
    rows: tuple[BacktestRow, ...]
    eligible_actuals: int
    skipped_unknown_actuals: int
    evidence_coverage: Decimal
    mae: Metric
    wape: Metric
    mase: Metric
    signed_bias: Metric
    evidence_tier: Tier
    integration_mode: Mode
    source_refs: tuple[str, ...]
    limitations: tuple[str, ...]


class RiskFamily(StrEnum):
    DEMAND = "DEMAND"
    STOCKOUT_OR_EXPIRY = "STOCKOUT_OR_EXPIRY"
    SUPPLIER_DELAY = "SUPPLIER_DELAY"
    CAPACITY_OR_DEADLINE = "CAPACITY_OR_DEADLINE"


class ForecastAlert(Frozen):
    alert_id: str
    tenant_id: str
    target_id: str
    family: RiskFamily
    forecast_run_id: str
    period: date
    status: str
    exposure: str
    magnitude: Quantity | None = None
    unit: str | None = None
    source_versions: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    evidence_tier: Tier
    integration_mode: Mode
    assumptions: tuple[str, ...] = ()
    uncertainty: str
    missing_data: tuple[str, ...] = ()
    explanation_codes: tuple[str, ...] = ()
    source_freshness: Aware | None = None
    preparation_options: tuple[str, ...] = ()
    required_human_review: bool = True
    operational_action_authorized: bool = False

    @model_validator(mode="after")
    def advisory_only(self) -> ForecastAlert:
        if self.operational_action_authorized:
            raise ValueError("forecasts cannot authorize operational actions")
        return self


class SourceUnavailable(Frozen):
    status: ForecastStatus = ForecastStatus.UNAVAILABLE
    diagnostics: tuple[str, ...] = ("TRUSTED_READER_UNAVAILABLE",)
