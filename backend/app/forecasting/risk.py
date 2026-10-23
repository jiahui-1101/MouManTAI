from __future__ import annotations

from datetime import date

from .models import ForecastAlert, ForecastRun, ForecastStatus, RiskFamily
from .ports import CurrentSnapshot, P2ScenarioAttestation, SupplierHistorySummary


def alert(
    run: ForecastRun,
    family: RiskFamily,
    period: date,
    *,
    status: str,
    exposure: str,
    codes: tuple[str, ...],
    missing: tuple[str, ...] = (),
    options: tuple[str, ...] = (),
    evidence: tuple[str, ...] = (),
    versions: tuple[str, ...] = (),
) -> ForecastAlert:
    return ForecastAlert(
        alert_id=f"{run.run_id}:{family}:{period}",
        tenant_id=run.tenant_id,
        target_id=run.sku_id,
        family=family,
        forecast_run_id=run.run_id,
        period=period,
        status=status,
        exposure=exposure,
        unit=run.unit,
        source_versions=versions,
        evidence_refs=evidence or run.source_refs,
        evidence_tier=run.evidence_tier,
        integration_mode=run.integration_mode,
        assumptions=run.assumptions,
        uncertainty="Uncalibrated baseline; no risk probability",
        missing_data=missing,
        explanation_codes=codes,
        preparation_options=options,
    )


def demand_alert(run: ForecastRun) -> ForecastAlert:
    period = run.points[0].period if run.points else run.training_cutoff
    if run.status != ForecastStatus.AVAILABLE:
        return alert(
            run,
            RiskFamily.DEMAND,
            period,
            status="UNKNOWN",
            exposure="Demand forecast unavailable",
            codes=(run.status.value,),
            missing=run.diagnostics,
        )
    return alert(
        run,
        RiskFamily.DEMAND,
        period,
        status="FUTURE_RISK_ADVISORY",
        exposure="Baseline estimate of future accepted demand; not a confirmed order",
        codes=("BASELINE_DEMAND",),
        options=("Review upcoming SKU demand",),
    )


def p2_alert(
    run: ForecastRun,
    family: RiskFamily,
    snapshot: CurrentSnapshot | None,
    attestation: P2ScenarioAttestation | None,
) -> ForecastAlert:
    period = run.points[0].period if run.points else run.training_cutoff
    if (
        run.status != ForecastStatus.AVAILABLE
        or snapshot is None
        or attestation is None
        or snapshot.tenant_id != run.tenant_id
        or snapshot.sku_id != run.sku_id
        or not snapshot.evidence_refs
        or attestation.tenant_id != run.tenant_id
        or attestation.sku_id != run.sku_id
        or attestation.forecast_run_id != run.run_id
        or attestation.target_period != period
        or attestation.snapshot_id != snapshot.snapshot_id
        or attestation.snapshot_version != snapshot.snapshot_version
        or not attestation.evidence_refs
    ):
        return alert(
            run,
            family,
            period,
            status="UNKNOWN",
            exposure="P2 forward evaluation unavailable or stale",
            codes=("P2_EVALUATION_UNAVAILABLE",),
            missing=("current matching P2 scenario attestation",),
            options=("Open the existing P2 assessment",),
        )
    return alert(
        run,
        family,
        period,
        status="FUTURE_RISK_ADVISORY",
        exposure=f"Conditional P2 scenario: {attestation.exposure}",
        codes=("P2_SCENARIO_ATTESTED",),
        evidence=attestation.evidence_refs,
        versions=(snapshot.snapshot_version, attestation.evaluator_version),
        options=("Review P2 scenario with an authorized SME",),
    )


def supplier_alert(run: ForecastRun, summary: SupplierHistorySummary | None) -> ForecastAlert:
    period = run.points[0].period if run.points else run.training_cutoff
    if (
        summary is None
        or summary.tenant_id != run.tenant_id
        or summary.sample_size == 0
        or not summary.evidence_refs
        or summary.evidence_tier != run.evidence_tier
        or summary.integration_mode != run.integration_mode
    ):
        return alert(
            run,
            RiskFamily.SUPPLIER_DELAY,
            period,
            status="UNKNOWN",
            exposure="Supplier delay risk unavailable",
            codes=("INSUFFICIENT_SUPPLIER_HISTORY",),
            missing=("verified Backend E supplier history",),
            options=("Request an updated delivery ETA",),
        )
    return alert(
        run,
        RiskFamily.SUPPLIER_DELAY,
        period,
        status="CONDITIONAL",
        exposure="Supplier history and ETA require human review; no calibrated delay probability",
        codes=(
            "SUPPLIER_HISTORY_DESCRIPTIVE",
            "ETA_VERIFIED" if summary.eta_is_verified else "ETA_SUPPLIER_CLAIM",
        ),
        evidence=summary.evidence_refs,
        versions=(summary.source_version,),
        options=("Verify supplier availability",),
    )
