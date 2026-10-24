"""Expanding-origin evaluation with no access to later observations at each origin."""

from __future__ import annotations

import itertools
from datetime import date, timedelta
from decimal import Decimal

from .baselines import ForecastModel
from .models import BacktestReport, BacktestRow, Metric
from .source_validation import ValidatedSeries


def _metric(numerator: Decimal, denominator: Decimal, reason: str) -> Metric:
    return (
        Metric(value=numerator / denominator)
        if denominator
        else Metric(value=None, unavailable_reason=reason)
    )


def backtest(
    series: ValidatedSeries,
    model: ForecastModel,
    *,
    train_cutoff: date,
    test_end: date,
    horizon: int = 1,
) -> BacktestReport:
    if series.status != "FORECAST_AVAILABLE":
        raise ValueError("validated complete series required")
    if not 1 <= horizon <= 365 or not train_cutoff < test_end <= series.manifest.complete_through:
        raise ValueError("invalid chronological holdout")
    rows: list[BacktestRow] = []
    for day_number in range(1, (test_end - train_cutoff).days + 1):
        target = train_cutoff + timedelta(days=day_number)
        origin = target - timedelta(days=horizon)
        if origin < train_cutoff:
            rows.append(
                BacktestRow(
                    origin=origin,
                    period=target,
                    prediction=None,
                    actual=series.values.get(target),
                    reason="ORIGIN_BEFORE_TRAIN_CUTOFF",
                )
            )
            continue
        history = {
            day: value
            for day, value in series.values.items()
            if day <= origin and series.available_on[day] <= origin
        }
        prediction = model.predict(history, origin, horizon)
        actual = (
            series.values.get(target)
            if series.available_on.get(target, date.max) <= test_end
            else None
        )
        rows.append(
            BacktestRow(
                origin=origin,
                period=target,
                prediction=prediction[-1] if prediction else None,
                actual=actual,
                reason="UNKNOWN_ACTUAL"
                if actual is None
                else "PREDICTION_UNAVAILABLE"
                if prediction is None
                else None,
            )
        )
    eligible = [row for row in rows if row.actual is not None and row.prediction is not None]
    abs_error = sum((abs(row.prediction - row.actual) for row in eligible), Decimal(0))
    signed_error = sum((row.prediction - row.actual for row in eligible), Decimal(0))
    actual_total = sum((row.actual for row in eligible), Decimal(0))
    training = sorted(
        (day, value)
        for day, value in series.values.items()
        if day <= train_cutoff and value is not None and series.available_on[day] <= train_cutoff
    )
    adjacent = [(a[1], b[1]) for a, b in itertools.pairwise(training) if (b[0] - a[0]).days == 1]
    scale = (
        sum((abs(a - b) for a, b in adjacent), Decimal(0)) / Decimal(len(adjacent))
        if adjacent
        else Decimal(0)
    )
    count = Decimal(len(eligible))
    mae = _metric(abs_error, count, "NO_ELIGIBLE_ACTUALS")
    return BacktestReport(
        tenant_id=series.manifest.tenant_id,
        sku_id=series.sku_id,
        model_name=model.name,
        model_version=model.version,
        cutoff=train_cutoff,
        evaluation_horizon=horizon,
        training_sample_size=len(training),
        training_naive_scale=Metric(value=scale)
        if scale
        else Metric(value=None, unavailable_reason="ZERO_OR_UNAVAILABLE_TRAINING_NAIVE_SCALE"),
        rows=tuple(rows),
        eligible_actuals=len(eligible),
        skipped_unknown_actuals=sum(row.actual is None for row in rows),
        evidence_coverage=count / Decimal(len(rows)),
        mae=mae,
        wape=_metric(abs_error, actual_total, "ZERO_ACTUAL_DEMAND"),
        mase=_metric(mae.value, scale, "ZERO_OR_UNAVAILABLE_TRAINING_NAIVE_SCALE")
        if mae.value is not None
        else Metric(value=None, unavailable_reason="NO_ELIGIBLE_ACTUALS"),
        signed_bias=_metric(signed_error, count, "NO_ELIGIBLE_ACTUALS"),
        evidence_tier=series.manifest.evidence_tier,
        integration_mode=series.manifest.integration_mode,
        source_refs=(series.manifest.source_dataset_id, series.manifest.source_snapshot_id),
        limitations=(
            "Exploratory holdout comparison; not independent model selection validation",
            "Synthetic metrics show fixture mechanics only; no real-world skill established",
        )
        if series.manifest.integration_mode == "SYNTHETIC"
        else ("Exploratory holdout; independent validation requires separate final test",),
    )


def compare_on_same_holdout(
    series: ValidatedSeries,
    models: tuple[ForecastModel, ...],
    *,
    train_cutoff: date,
    test_end: date,
    horizon: int = 1,
) -> tuple[BacktestReport, ...]:
    reports = tuple(
        backtest(series, model, train_cutoff=train_cutoff, test_end=test_end, horizon=horizon)
        for model in models
    )
    common = (
        set.intersection(
            *(
                {
                    row.period
                    for row in report.rows
                    if row.prediction is not None and row.actual is not None
                }
                for report in reports
            )
        )
        if reports
        else set()
    )
    # Recompute on identical eligible periods; absent predictions remain visible as rows.
    from .models import BacktestReport as Report

    result = []
    for report in reports:
        selected = [row for row in report.rows if row.period in common]
        error = sum((abs(row.prediction - row.actual) for row in selected), Decimal(0))
        actuals = sum((row.actual for row in selected), Decimal(0))
        bias = sum((row.prediction - row.actual for row in selected), Decimal(0))
        n = Decimal(len(selected))
        scale = report.training_naive_scale.value
        result.append(
            Report.model_validate(
                {
                    **report.model_dump(),
                    "eligible_actuals": len(selected),
                    "evidence_coverage": n / Decimal(len(report.rows)),
                    "mae": _metric(error, n, "NO_COMMON_ACTUALS"),
                    "wape": _metric(error, actuals, "ZERO_ACTUAL_DEMAND"),
                    "signed_bias": _metric(bias, n, "NO_COMMON_ACTUALS"),
                    "mase": _metric(error / n, scale, "ZERO_OR_UNAVAILABLE_TRAINING_NAIVE_SCALE")
                    if scale and n
                    else Metric(
                        value=None, unavailable_reason="ZERO_OR_UNAVAILABLE_TRAINING_NAIVE_SCALE"
                    ),
                }
            )
        )
    return tuple(result)
