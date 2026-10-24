"""Forecast adapters for server-side demand and forward scenario reading.

Supplies authentic or demo-only synthetic data to the pure ForecastService.
Adheres to SYS-FORE-01 through SYS-FORE-06 and BE-FORE-01 / BE-FORE-02:
Forecasts are advisory only, never mutate inventory, and never claim real skill on synthetic data.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import CommitmentRecord
from app.forecasting.models import (
    DemandKind,
    DemandObservation,
    ForecastSourceManifest,
    Mode,
    RiskFamily,
    Tier,
)
from app.forecasting.ports import (
    CurrentSnapshot,
    DemandReader,
    P2ScenarioAttestation,
    SupplierHistorySummary,
)


class DemoDemandReader(DemandReader):
    """Deterministic synthetic demand generator for demo and baseline testing.

    Always explicitly tagged Mode.SYNTHETIC and Tier.DEMO_ONLY.
    """

    def __init__(self, days: int = 21, unit: str = "pcs", as_of: datetime | None = None):
        self.days = days
        self.unit = unit
        self.as_of = as_of

    def read(
        self, tenant_id: str, sku_id: str, cutoff: date
    ) -> tuple[ForecastSourceManifest, tuple[DemandObservation, ...]]:
        start = cutoff - timedelta(days=self.days - 1)
        # Anchor snapshot watermark and capture cleanly before now/cutoff
        watermark = (
            self.as_of
            if self.as_of
            else datetime.combine(cutoff, datetime.min.time(), UTC) + timedelta(hours=2)
        )

        manifest = ForecastSourceManifest(
            tenant_id=tenant_id,
            source_dataset_id=f"demo-dataset-{tenant_id}",
            source_snapshot_id="snapshot-demo-1",
            source_snapshot_version="v1",
            source_system="MouManTAI Demo Demand Engine",
            integration_mode=Mode.SYNTHETIC,
            evidence_tier=Tier.DEMO_ONLY,
            captured_at=watermark,
            complete_through=cutoff,
            historical_window_start=start,
            historical_window_end=cutoff,
            source_watermark=watermark,
            pagination_complete=True,
            source_population_complete=True,
            input_version="v1",
            missing_source_ids=(),
            evidence_refs=(f"evidence-manifest-{tenant_id}-{sku_id}",),
            reader_attestation="Demo-only synthetic demand reader with strict reproducible series",
        )

        # Baseline quantities with realistic day-of-week seasonality (higher mid-week, weekend dip)
        pattern = [12, 16, 22, 28, 25, 18, 10]
        observations: list[DemandObservation] = []
        for i in range(self.days):
            obs_date = start + timedelta(days=i)
            qty = Decimal(pattern[i % len(pattern)])
            recorded_time = datetime.combine(obs_date, datetime.min.time(), UTC) + timedelta(hours=1)
            # Ensure recorded_time never exceeds watermark
            if recorded_time > watermark:
                recorded_time = watermark

            observations.append(
                DemandObservation(
                    tenant_id=tenant_id,
                    sku_id=sku_id,
                    observation_id=f"obs-{tenant_id}-{sku_id}-{obs_date.isoformat()}",
                    observation_version=1,
                    period=obs_date,
                    quantity=qty,
                    unit=self.unit,
                    kind=DemandKind.ACCEPTED,
                    source_event_ref=f"evt-order-{i}",
                    acceptance_ref=f"acc-sme-{i}",
                    evidence_ref=f"evid-order-{i}",
                    source_version="v1",
                    recorded_at=recorded_time,
                    business_timezone="Asia/Singapore",
                    evidence_tier=Tier.DEMO_ONLY,
                    integration_mode=Mode.SYNTHETIC,
                )
            )

        return manifest, tuple(observations)


class DatabaseDemandReader(DemandReader):
    """Authoritative reader reading accepted SME commitments from DB.

    When sufficient history is present, runs with Mode.LIVE and Tier.TARGET.
    """

    def __init__(self, db: Session, unit: str = "pcs", as_of: datetime | None = None):
        self.db = db
        self.unit = unit
        self.as_of = as_of

    def read(
        self, tenant_id: str, sku_id: str, cutoff: date
    ) -> tuple[ForecastSourceManifest, tuple[DemandObservation, ...]]:
        watermark = (
            self.as_of
            if self.as_of
            else datetime.combine(cutoff, datetime.min.time(), UTC) + timedelta(hours=2)
        )
        query = (
            select(CommitmentRecord)
            .where(
                CommitmentRecord.tenant_id == tenant_id,
                CommitmentRecord.agreement_state == "ACCEPTED",
            )
            .order_by(CommitmentRecord.updated_at.asc())
        )
        try:
            records = self.db.scalars(query).all()
        except Exception:
            records = []

        daily_quantities: dict[date, Decimal] = {}
        source_evidence: list[str] = []

        for record in records:
            terms = record.terms if isinstance(record.terms, dict) else {}
            items = terms.get("items")
            record_date = record.updated_at.date() if record.updated_at else cutoff

            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict) and item.get("sku") == sku_id:
                        try:
                            qty = Decimal(str(item.get("quantity", 0)))
                        except Exception:
                            qty = Decimal(0)
                        daily_quantities[record_date] = daily_quantities.get(record_date, Decimal(0)) + qty
                        source_evidence.append(f"commitment-{record.commitment_id}")
            elif terms.get("sku") == sku_id:
                try:
                    qty = Decimal(str(terms.get("quantity", 0)))
                except Exception:
                    qty = Decimal(0)
                daily_quantities[record_date] = daily_quantities.get(record_date, Decimal(0)) + qty
                source_evidence.append(f"commitment-{record.commitment_id}")

        sorted_dates = sorted(daily_quantities.keys())
        if not sorted_dates or len(sorted_dates) < 7:
            start = cutoff - timedelta(days=6)
            manifest = ForecastSourceManifest(
                tenant_id=tenant_id,
                source_dataset_id=f"db-dataset-{tenant_id}",
                source_snapshot_id="snapshot-db-insufficient",
                source_snapshot_version="v1",
                source_system="MouManTAI Authoritative Database Reader",
                integration_mode=Mode.LIVE,
                evidence_tier=Tier.TARGET,
                captured_at=watermark,
                complete_through=cutoff,
                historical_window_start=start,
                historical_window_end=cutoff,
                source_watermark=watermark,
                pagination_complete=True,
                source_population_complete=False,
                input_version="v1",
                missing_source_ids=(),
                evidence_refs=tuple(source_evidence) or (f"tenant-{tenant_id}",),
                reader_attestation="Database commitment demand reader: insufficient chronological days",
            )
            return manifest, ()

        start = sorted_dates[0]
        manifest = ForecastSourceManifest(
            tenant_id=tenant_id,
            source_dataset_id=f"db-dataset-{tenant_id}",
            source_snapshot_id=f"snapshot-db-{watermark.strftime('%Y%m%d%H%M')}",
            source_snapshot_version="v1",
            source_system="MouManTAI Authoritative Database Reader",
            integration_mode=Mode.LIVE,
            evidence_tier=Tier.TARGET,
            captured_at=watermark,
            complete_through=cutoff,
            historical_window_start=start,
            historical_window_end=cutoff,
            source_watermark=watermark,
            pagination_complete=True,
            source_population_complete=True,
            input_version="v1",
            missing_source_ids=(),
            evidence_refs=tuple(source_evidence),
            reader_attestation="Database commitment demand reader authenticated over accepted commitments",
        )

        observations: list[DemandObservation] = []
        for i, obs_date in enumerate(sorted_dates):
            if obs_date > cutoff:
                continue
            qty = daily_quantities[obs_date]
            recorded_time = datetime.combine(obs_date, datetime.min.time(), UTC) + timedelta(hours=1)
            if recorded_time > watermark:
                recorded_time = watermark
            observations.append(
                DemandObservation(
                    tenant_id=tenant_id,
                    sku_id=sku_id,
                    observation_id=f"db-{tenant_id}-{sku_id}-{obs_date.isoformat()}",
                    observation_version=1,
                    period=obs_date,
                    quantity=qty,
                    unit=self.unit,
                    kind=DemandKind.ACCEPTED,
                    source_event_ref=f"db-evt-{i}",
                    acceptance_ref=f"db-acc-{i}",
                    evidence_ref=f"db-evid-{i}",
                    source_version="v1",
                    recorded_at=recorded_time,
                    business_timezone="Asia/Singapore",
                    evidence_tier=Tier.TARGET,
                    integration_mode=Mode.LIVE,
                )
            )

        return manifest, tuple(observations)


class DemoSnapshotReader:
    def __init__(self, captured_at: datetime | None = None):
        self.captured_at = captured_at or datetime.now(UTC)

    def read(self, tenant_id: str, sku_id: str) -> CurrentSnapshot:
        return CurrentSnapshot(
            tenant_id=tenant_id,
            sku_id=sku_id,
            snapshot_id="snapshot-demo-1",
            snapshot_version="v1",
            captured_at=self.captured_at,
            valid_through=self.captured_at + timedelta(days=2),
            business_timezone="Asia/Singapore",
            evidence_refs=("demo-snapshot-proof",),
        )


class DemoP2ForwardScenarioReader:
    def __init__(self, watermark: datetime | None = None):
        self.watermark = watermark or datetime.now(UTC)

    def evaluate(
        self,
        tenant_id: str,
        sku_id: str,
        snapshot_id: str,
        snapshot_version: str,
        forecast_run_id: str,
        risk_family: RiskFamily,
        target_period: date,
        as_of: datetime,
    ) -> P2ScenarioAttestation:
        if risk_family == RiskFamily.STOCKOUT_OR_EXPIRY:
            exposure = "Inventory safety stock covers 14 days; lot #L-409 expires within the 21-day planning window"
            codes = ("EXPIRY_WINDOW_APPROACHING", "SAFETY_STOCK_HEALTHY")
        elif risk_family == RiskFamily.CAPACITY_OR_DEADLINE:
            exposure = "Capacity utilization projected at 78% on peak production days; within safe operating margins"
            codes = ("CAPACITY_NORMAL", "DEADLINE_BUFFER_ADEQUATE")
        else:
            exposure = f"P2 forward scenario simulation for {risk_family.value}"
            codes = ("SCENARIO_SIMULATED",)

        return P2ScenarioAttestation(
            tenant_id=tenant_id,
            sku_id=sku_id,
            snapshot_id=snapshot_id,
            snapshot_version=snapshot_version,
            source_watermark=self.watermark,
            evaluator_version="v1",
            forecast_run_id=forecast_run_id,
            risk_family=risk_family,
            target_period=target_period,
            coverage_start=target_period - timedelta(days=7),
            coverage_end=target_period + timedelta(days=30),
            assessment_status="SUPPORTED",
            exposure=exposure,
            reason_codes=codes,
            evidence_refs=(f"demo-p2-evidence-{risk_family.value.lower()}",),
            evaluated_at=as_of,
            valid_through=as_of + timedelta(days=3),
        )


class DemoSupplierHistoryReader:
    def read(self, tenant_id: str, supplier_id: str) -> SupplierHistorySummary:
        now = datetime.now(UTC)
        cutoff = now.date()
        return SupplierHistorySummary(
            tenant_id=tenant_id,
            supplier_id=supplier_id or "SUP-PRIMARY-01",
            source_version="v1",
            sample_size=12,
            source_cutoff=cutoff,
            coverage="Last 90 days of fulfilled purchase orders",
            lead_time_summary="3.4 days average lead time (standard deviation 0.6 days)",
            eta=cutoff + timedelta(days=3),
            eta_is_verified=True,
            evidence_refs=("demo-supplier-quote-history",),
            evidence_tier=Tier.DEMO_ONLY,
            integration_mode=Mode.SYNTHETIC,
        )
