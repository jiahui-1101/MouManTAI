"""Validate reader-supplied history. Model validation alone is not authentication."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from .models import (
    DemandKind,
    DemandObservation,
    ForecastSourceManifest,
    ForecastStatus,
    Mode,
    Tier,
)


@dataclass(frozen=True)
class ValidatedSeries:
    manifest: ForecastSourceManifest
    sku_id: str
    unit: str
    values: dict[date, Decimal | None]
    available_on: dict[date, date]
    status: ForecastStatus
    diagnostics: tuple[str, ...]


def validate_series(
    manifest: ForecastSourceManifest,
    observations: tuple[DemandObservation, ...],
    *,
    tenant_id: str,
    sku_id: str,
    unit: str,
    cutoff: date,
    now: datetime,
    trusted_reader: bool,
    max_age_days: int = 7,
    max_observations: int = 5000,
) -> ValidatedSeries:
    errors: list[str] = []
    if not trusted_reader or not manifest.reader_attestation:
        return ValidatedSeries(
            manifest,
            sku_id,
            unit,
            {},
            {},
            ForecastStatus.UNAVAILABLE,
            ("TRUSTED_READER_UNAVAILABLE",),
        )
    if manifest.tenant_id != tenant_id:
        errors.append("TENANT_MISMATCH")
    if (
        not manifest.source_snapshot_id
        or not manifest.source_snapshot_version
        or not manifest.input_version
    ):
        errors.append("SNAPSHOT_IDENTITY_MISSING")
    if not manifest.evidence_refs:
        errors.append("PROVENANCE_MISSING")
    if manifest.integration_mode == Mode.SYNTHETIC and manifest.evidence_tier != Tier.DEMO_ONLY:
        errors.append("SYNTHETIC_TIER_MISMATCH")
    if manifest.integration_mode == Mode.MOCK and manifest.evidence_tier in (
        Tier.VALIDATED,
        Tier.LIVE,
    ):
        errors.append("MOCK_TIER_MISMATCH")
    if manifest.integration_mode != Mode.LIVE and manifest.evidence_tier == Tier.LIVE:
        errors.append("LIVE_TIER_MISMATCH")
    if manifest.evidence_tier in (Tier.VALIDATED, Tier.LIVE):
        errors.append("PRODUCTION_EVIDENCE_GATE_DISABLED")
    if cutoff > manifest.complete_through or cutoff > manifest.historical_window_end:
        errors.append("CUTOFF_NOT_COMPLETE")
    if (
        manifest.historical_window_start > cutoff
        or manifest.historical_window_end < manifest.historical_window_start
    ):
        errors.append("WINDOW_INVALID")
    if manifest.captured_at > now or manifest.source_watermark > now:
        errors.append("FUTURE_SOURCE")
    if len(observations) > max_observations:
        errors.append("HISTORY_LIMIT_EXCEEDED")
    if (
        not manifest.pagination_complete
        or not manifest.source_population_complete
        or manifest.missing_source_ids
    ):
        errors.append("SOURCE_INCOMPLETE")
    if (now - manifest.source_watermark).total_seconds() > max_age_days * 86400:
        errors.append("SOURCE_STALE")

    by_id: dict[str, DemandObservation] = {}
    last_period: date | None = None
    for obs in observations:
        if obs.tenant_id != tenant_id or obs.sku_id != sku_id or obs.unit != unit:
            errors.append("IDENTITY_OR_UNIT_MISMATCH")
        if (
            obs.evidence_tier != manifest.evidence_tier
            or obs.integration_mode != manifest.integration_mode
        ):
            errors.append("EVIDENCE_MODE_MISMATCH")
        if obs.source_version != manifest.source_snapshot_version:
            errors.append("SOURCE_VERSION_MISMATCH")
        if not obs.source_event_ref or not obs.evidence_ref or not obs.source_version:
            errors.append("OBSERVATION_PROVENANCE_MISSING")
        if (
            obs.period > cutoff
            or obs.recorded_at > now
            or obs.period < manifest.historical_window_start
        ):
            errors.append("OBSERVATION_OUTSIDE_CUTOFF")
        if obs.recorded_at > manifest.captured_at:
            errors.append("OBSERVATION_AFTER_SNAPSHOT")
        if last_period is not None and obs.period < last_period:
            errors.append("NOT_CHRONOLOGICAL")
        last_period = obs.period
        prior = by_id.get(obs.observation_id)
        if prior is None:
            by_id[obs.observation_id] = obs
        elif prior == obs:
            continue  # identical transport replay
        elif (
            obs.observation_version > prior.observation_version
            and obs.supersedes_version == prior.observation_version
        ):
            by_id[obs.observation_id] = obs
        else:
            errors.append("CONFLICTING_DUPLICATE_OR_UNVERIFIED_CORRECTION")

    values: dict[date, Decimal | None] = {}
    available_on: dict[date, date] = {}
    for obs in by_id.values():
        if obs.kind in (DemandKind.ACCEPTED, DemandKind.KNOWN_ZERO, DemandKind.UNKNOWN):
            if obs.period in values:
                errors.append("DUPLICATE_PERIOD_BUCKET")
            values[obs.period] = obs.quantity
            available_on[obs.period] = obs.recorded_at.astimezone(
                ZoneInfo(obs.business_timezone)
            ).date()
    if errors:
        status = (
            ForecastStatus.INVALID
            if any(e not in {"SOURCE_INCOMPLETE", "SOURCE_STALE"} for e in errors)
            else ForecastStatus.INCOMPLETE
            if "SOURCE_INCOMPLETE" in errors
            else ForecastStatus.STALE
        )
        return ValidatedSeries(manifest, sku_id, unit, {}, {}, status, tuple(sorted(set(errors))))
    return ValidatedSeries(
        manifest, sku_id, unit, values, available_on, ForecastStatus.AVAILABLE, ()
    )
