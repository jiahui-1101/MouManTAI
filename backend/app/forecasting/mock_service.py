"""Mock source adapter for the existing forecasting engine."""

from datetime import UTC, date, datetime
from typing import Literal
from uuid import uuid4

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.errors import DomainError
from app.core.models import OutboxEventRecord
from app.forecasting.mock_models import MockForecastAuditRecord, MockForecastDatasetRecord
from app.forecasting.models import (
    BacktestReport,
    DemandKind,
    DemandObservation,
    ForecastAlert,
    ForecastRun,
    ForecastSourceManifest,
    ForecastStatus,
    Mode,
    Tier,
)
from app.forecasting.service import ForecastService
from app.forecasting.source_validation import validate_series
from app.orders.terms import ImmutableContract


class MockForecastDatasetCreate(ImmutableContract):
    dataset_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")
    sku_id: str = Field(min_length=1, max_length=128)
    unit: str = Field(min_length=1, max_length=64)
    manifest: ForecastSourceManifest
    observations: tuple[DemandObservation, ...] = Field(min_length=1, max_length=5000)


class MockForecastDatasetView(MockForecastDatasetCreate):
    tenant_id: str
    actor_id: str
    integration_mode: Literal["MOCK"] = "MOCK"
    evidence_tier: Literal["DEMO-ONLY"] = "DEMO-ONLY"


class MockForecastBaselineView(ImmutableContract):
    dataset_id: str
    run: ForecastRun
    alerts: tuple[ForecastAlert, ...]
    integration_mode: Literal["MOCK"] = "MOCK"
    evidence_tier: Literal["DEMO-ONLY"] = "DEMO-ONLY"
    operational_action_authorized: Literal[False] = False


class MockForecastBacktestView(ImmutableContract):
    dataset_id: str
    status: ForecastStatus
    diagnostics: tuple[str, ...]
    reports: tuple[BacktestReport, ...]
    integration_mode: Literal["MOCK"] = "MOCK"
    evidence_tier: Literal["DEMO-ONLY"] = "DEMO-ONLY"
    real_world_skill_established: Literal[False] = False


def _synthetic(ref: str) -> bool:
    return ref.startswith("synthetic://")


def _validate_source(context: RequestContext, command: MockForecastDatasetCreate) -> ForecastSourceManifest:
    m = command.manifest
    if (m.tenant_id != context.tenant_id or m.source_dataset_id != command.dataset_id
            or m.source_system != "MOCK_ORBYTE" or m.integration_mode != Mode.MOCK
            or m.evidence_tier != Tier.DEMO_ONLY or not m.evidence_refs
            or not all(_synthetic(ref) for ref in m.evidence_refs)
            or (m.missing_source_ids and not all(_synthetic(ref) for ref in m.missing_source_ids))
            or m.captured_at > datetime.now(UTC) or m.source_watermark > datetime.now(UTC)
            or m.captured_at < m.source_watermark
            or any(obs.tenant_id != context.tenant_id or obs.sku_id != command.sku_id
                   or obs.unit != command.unit or obs.integration_mode != Mode.MOCK
                   or obs.evidence_tier != Tier.DEMO_ONLY
                   or not _synthetic(obs.source_event_ref)
                   or not _synthetic(obs.evidence_ref)
                   or obs.recorded_at > m.source_watermark
                   or (obs.acceptance_ref is not None and not _synthetic(obs.acceptance_ref))
                   or (obs.kind == DemandKind.ACCEPTED and obs.acceptance_ref is None)
                   for obs in command.observations)):
        raise DomainError("MOCK_FORECAST_SOURCE_INVALID",
                          "Demand history must be tenant-bound and explicitly synthetic",
                          status_code=422)
    # The caller's attestation has no authority. The persisted reader is attested by this service.
    m = m.model_copy(update={"reader_attestation": f"synthetic://persisted/{command.dataset_id}"})
    series = validate_series(m, command.observations, tenant_id=context.tenant_id,
                             sku_id=command.sku_id, unit=command.unit,
                             cutoff=m.complete_through, now=datetime.now(UTC), trusted_reader=True)
    if series.status == ForecastStatus.INVALID:
        raise DomainError("MOCK_FORECAST_SOURCE_INVALID",
                          "Demand history failed source validation", status_code=422,
                          details={"diagnostics": series.diagnostics})
    return m


def _view(row: MockForecastDatasetRecord) -> MockForecastDatasetView:
    return MockForecastDatasetView(
        dataset_id=row.dataset_id, sku_id=row.sku_id, unit=row.unit,
        tenant_id=row.tenant_id, actor_id=row.actor_id,
        manifest=ForecastSourceManifest.model_validate(row.manifest),
        observations=tuple(DemandObservation.model_validate(item) for item in row.observations),
    )


def seed_dataset(db: Session, context: RequestContext,
                 command: MockForecastDatasetCreate) -> MockForecastDatasetView:
    manifest = _validate_source(context, command)
    stored_manifest = manifest.model_dump(mode="json")
    stored_observations = [item.model_dump(mode="json") for item in command.observations]
    existing = db.get(MockForecastDatasetRecord, (context.tenant_id, command.dataset_id))
    if existing is not None:
        if (existing.sku_id, existing.unit, existing.manifest, existing.observations) != (
                command.sku_id, command.unit, stored_manifest, stored_observations):
            raise DomainError("MOCK_FORECAST_DATASET_CONFLICT", "Dataset ID has other facts",
                              status_code=409)
        return _view(existing)
    now = datetime.now(UTC)
    row = MockForecastDatasetRecord(
        tenant_id=context.tenant_id, dataset_id=command.dataset_id,
        sku_id=command.sku_id, unit=command.unit, manifest=stored_manifest,
        observations=stored_observations, actor_id=context.actor_id, created_at=now,
    )
    db.add(row)
    audit_id = f"aud_{uuid4().hex}"
    db.add(MockForecastAuditRecord(
        audit_id=audit_id, tenant_id=context.tenant_id, dataset_id=command.dataset_id,
        event_type="forecast.mock_history_seeded", actor_id=context.actor_id,
        evidence_refs=list(manifest.evidence_refs),
        reason="Controlled synthetic demand history", occurred_at=now,
    ))
    db.add(OutboxEventRecord(
        event_id=f"evt_{uuid4().hex}", tenant_id=context.tenant_id,
        event_type="forecast.mock_history_seeded", commitment_id=None,
        commitment_version=None, correlation_id=context.correlation_id,
        causation_id=context.causation_id, occurred_at=now,
        payload={"dataset_id": command.dataset_id, "audit_id": audit_id,
                 "integration_mode": "MOCK", "evidence_tier": "DEMO-ONLY"},
        published_at=None, attempts=0, status="PENDING", last_error=None,
        next_retry_at=None,
    ))
    db.commit()
    return _view(row)


def get_dataset(db: Session, context: RequestContext, dataset_id: str) -> MockForecastDatasetRecord:
    row = db.scalar(select(MockForecastDatasetRecord).where(
        MockForecastDatasetRecord.tenant_id == context.tenant_id,
        MockForecastDatasetRecord.dataset_id == dataset_id,
    ))
    if row is None:
        raise DomainError("MOCK_FORECAST_DATASET_NOT_FOUND", "Demand dataset not found",
                          status_code=404)
    return row


class PersistedMockDemandReader:
    def __init__(self, row: MockForecastDatasetRecord):
        self.row = row

    def read(self, tenant_id: str, sku_id: str, cutoff: date):
        if self.row.tenant_id != tenant_id or self.row.sku_id != sku_id:
            raise DomainError("MOCK_FORECAST_DATASET_NOT_FOUND", "Demand dataset not found",
                              status_code=404)
        return (ForecastSourceManifest.model_validate(self.row.manifest),
                tuple(DemandObservation.model_validate(item) for item in self.row.observations))


def baseline(db: Session, context: RequestContext, dataset_id: str,
             horizon: int) -> MockForecastBaselineView:
    row = get_dataset(db, context, dataset_id)
    manifest = ForecastSourceManifest.model_validate(row.manifest)
    now = datetime.now(UTC)
    engine = ForecastService(demand_reader=PersistedMockDemandReader(row))
    run = engine.baseline(context.tenant_id, row.sku_id, row.unit,
                          manifest.complete_through, horizon, now)
    alerts = engine.advisories(run, as_of=now)
    return MockForecastBaselineView(dataset_id=dataset_id, run=run, alerts=alerts)


def backtest(db: Session, context: RequestContext, dataset_id: str,
             train_cutoff: date, horizon: int) -> MockForecastBacktestView:
    row = get_dataset(db, context, dataset_id)
    manifest = ForecastSourceManifest.model_validate(row.manifest)
    if not manifest.historical_window_start <= train_cutoff < manifest.complete_through:
        raise DomainError("MOCK_FORECAST_HOLDOUT_INVALID", "Train cutoff is outside history",
                          status_code=422)
    now = datetime.now(UTC)
    engine = ForecastService(demand_reader=PersistedMockDemandReader(row))
    series = engine.readiness(context.tenant_id, row.sku_id, row.unit,
                              manifest.complete_through, now)
    if series.status != ForecastStatus.AVAILABLE:
        return MockForecastBacktestView(dataset_id=dataset_id, status=series.status,
                                        diagnostics=series.diagnostics, reports=())
    reports = engine.evaluate(context.tenant_id, row.sku_id, row.unit,
                              train_cutoff, manifest.complete_through, now, horizon=horizon)
    return MockForecastBacktestView(dataset_id=dataset_id, status=series.status,
                                    diagnostics=series.diagnostics, reports=reports or ())
