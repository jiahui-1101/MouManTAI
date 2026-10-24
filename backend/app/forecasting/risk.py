from __future__ import annotations

from datetime import date, datetime

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
    *,
    as_of: datetime | None,
) -> ForecastAlert:
    period = run.points[0].period if run.points else run.training_cutoff
    reasons: list[str] = []
    if run.status != ForecastStatus.AVAILABLE:
        reasons.append("FORECAST_UNAVAILABLE")
    if snapshot is None:
        reasons.append("CURRENT_SNAPSHOT_UNAVAILABLE")
    elif snapshot.tenant_id != run.tenant_id or snapshot.sku_id != run.sku_id:
        reasons.append("SNAPSHOT_SCOPE_MISMATCH")
    elif not snapshot.evidence_refs:
        reasons.append("SNAPSHOT_EVIDENCE_MISSING")
    if attestation is None:
        reasons.append("P2_EVALUATION_UNAVAILABLE")
    else:
        if attestation.tenant_id != run.tenant_id or attestation.sku_id != run.sku_id:
            reasons.append("P2_TENANT_OR_SKU_MISMATCH")
        if attestation.forecast_run_id != run.run_id:
            reasons.append("P2_FORECAST_RUN_MISMATCH")
        if attestation.risk_family != family:
            reasons.append("P2_RISK_FAMILY_MISMATCH")
        if attestation.target_period != period or not (
            attestation.coverage_start <= period <= attestation.coverage_end
        ):
            reasons.append("P2_COVERAGE_MISMATCH")
        if not attestation.evidence_refs:
            reasons.append("P2_EVIDENCE_MISSING")
        if attestation.assessment_status != "SUPPORTED":
            reasons.append("P2_ASSESSMENT_NOT_SUPPORTED")
    if snapshot is not None and attestation is not None:
        if (
            attestation.snapshot_id != snapshot.snapshot_id
            or attestation.snapshot_version != snapshot.snapshot_version
        ):
            reasons.append("P2_SNAPSHOT_VERSION_MISMATCH")
        if attestation.source_watermark != snapshot.captured_at:
            reasons.append("P2_SOURCE_WATERMARK_MISMATCH")
    if as_of is None or as_of.tzinfo is None or as_of.utcoffset() is None:
        reasons.append("TRUSTED_AS_OF_REQUIRED")
    elif snapshot is not None:
        if snapshot.captured_at > as_of:
            reasons.append("SNAPSHOT_CAPTURED_IN_FUTURE")
        if snapshot.valid_through < as_of:
            reasons.append("SNAPSHOT_STALE_AT_AS_OF")
    if (
        as_of is not None
        and as_of.tzinfo is not None
        and as_of.utcoffset() is not None
        and attestation is not None
    ):
        if attestation.evaluated_at < attestation.source_watermark:
            reasons.append("P2_EVALUATION_PRECEDES_SOURCE")
        if attestation.evaluated_at > as_of:
            reasons.append("P2_EVALUATION_IN_FUTURE")
        if attestation.valid_through < as_of:
            reasons.append("P2_ATTESTATION_STALE_AT_AS_OF")
    if run.integration_mode.value == "LIVE":
        # The typed forward-scenario contract is provisional until P2 ratifies it.
        reasons.append("P2_FORWARD_CONTRACT_NOT_RATIFIED")
    if reasons:
        return alert(
            run,
            family,
            period,
            status="UNKNOWN",
            exposure="P2 forward evaluation unavailable or stale",
            codes=tuple(dict.fromkeys(reasons)),
            missing=tuple(dict.fromkeys(reasons)),
            options=("Open the existing P2 assessment",),
        )
    return alert(
        run,
        family,
        period,
        status="FUTURE_RISK_ADVISORY",
        exposure=f"Conditional P2 scenario: {attestation.exposure}",
        codes=("P2_SCENARIO_ATTESTED", *attestation.reason_codes),
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
