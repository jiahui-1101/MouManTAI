"""Owner supplied readers and attestations; no local operational authority."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from .models import Aware, DemandObservation, ForecastSourceManifest, Frozen, Mode, Tier


class DemandReader(Protocol):
    """An authenticated server-side adapter, never a caller-provided manifest."""

    def read(
        self, tenant_id: str, sku_id: str, cutoff: date
    ) -> tuple[ForecastSourceManifest, tuple[DemandObservation, ...]]: ...


class P2ScenarioAttestation(Frozen):
    tenant_id: str
    sku_id: str
    snapshot_id: str
    snapshot_version: str
    evaluator_version: str
    forecast_run_id: str
    target_period: date
    exposure: str  # P2 owner-defined result, never recalculated here
    evidence_refs: tuple[str, ...]
    evaluated_at: Aware


class P2ForwardScenarioReader(Protocol):
    def evaluate(
        self, tenant_id: str, sku_id: str, forecast_run_id: str, target_period: date
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
    business_timezone: str
    evidence_refs: tuple[str, ...]


class CurrentSnapshotReader(Protocol):
    def read(self, tenant_id: str, sku_id: str) -> CurrentSnapshot: ...
