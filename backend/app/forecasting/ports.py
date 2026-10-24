"""Owner supplied readers and attestations; no local operational authority."""

from __future__ import annotations

from datetime import date
from typing import Literal, Protocol

from pydantic import Field, model_validator

from .models import (
    Aware,
    DemandObservation,
    ForecastSourceManifest,
    Frozen,
    Mode,
    RiskFamily,
    Tier,
)


class DemandReader(Protocol):
    """An authenticated server-side adapter, never a caller-provided manifest."""

    def read(
        self, tenant_id: str, sku_id: str, cutoff: date
    ) -> tuple[ForecastSourceManifest, tuple[DemandObservation, ...]]: ...


class P2ScenarioAttestation(Frozen):
    """Provisional, family-scoped result. It is not a live P2 authority contract."""

    tenant_id: str = Field(min_length=1)
    sku_id: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    snapshot_version: str = Field(min_length=1)
    source_watermark: Aware
    evaluator_version: str = Field(min_length=1)
    forecast_run_id: str = Field(min_length=1)
    risk_family: RiskFamily
    target_period: date
    coverage_start: date
    coverage_end: date
    assessment_status: Literal["SUPPORTED", "UNSUPPORTED", "INCOMPLETE", "UNKNOWN"]
    exposure: str = Field(min_length=1)  # P2 owner-defined result, never recalculated here
    reason_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    evaluated_at: Aware
    valid_through: Aware

    @model_validator(mode="after")
    def valid_window(self) -> P2ScenarioAttestation:
        if self.coverage_end < self.coverage_start:
            raise ValueError("P2 coverage window is inverted")
        if self.evaluated_at < self.source_watermark:
            raise ValueError("P2 evaluation predates its source watermark")
        if self.valid_through < self.evaluated_at:
            raise ValueError("P2 attestation expires before evaluation")
        return self


class P2ForwardScenarioReader(Protocol):
    def evaluate(
        self,
        tenant_id: str,
        sku_id: str,
        snapshot_id: str,
        snapshot_version: str,
        forecast_run_id: str,
        risk_family: RiskFamily,
        target_period: date,
        as_of: Aware,
    ) -> P2ScenarioAttestation: ...


class SupplierHistorySummary(Frozen):
    tenant_id: str
    supplier_id: str
    source_version: str
    sample_size: int
    source_cutoff: date
    coverage: str
    lead_time_summary: str
    eta: date | None
    eta_is_verified: bool
    evidence_refs: tuple[str, ...]
    evidence_tier: Tier
    integration_mode: Mode


class SupplierHistoryReader(Protocol):
    def read(self, tenant_id: str, supplier_id: str) -> SupplierHistorySummary: ...


class CurrentSnapshot(Frozen):
    tenant_id: str
    sku_id: str
    snapshot_id: str
    snapshot_version: str
    captured_at: Aware
    valid_through: Aware
    business_timezone: str
    evidence_refs: tuple[str, ...]

    @model_validator(mode="after")
    def valid_window(self) -> CurrentSnapshot:
        if self.valid_through < self.captured_at:
            raise ValueError("snapshot expires before capture")
        return self


class CurrentSnapshotReader(Protocol):
    def read(self, tenant_id: str, sku_id: str) -> CurrentSnapshot: ...
