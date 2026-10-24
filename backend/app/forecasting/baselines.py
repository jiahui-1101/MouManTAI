from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Protocol

from .models import TARGET, ForecastPoint, ForecastRun, ForecastStatus
from .source_validation import ValidatedSeries


class ForecastModel(Protocol):
    name: str
    version: str

    def predict(
        self, values: dict[date, Decimal | None], cutoff: date, horizon: int
    ) -> tuple[Decimal, ...] | None: ...


class MovingAverage:
    name = "MOVING_AVERAGE"
    version = "1"

    def __init__(self, lookback: int = 7):
        if not 1 <= lookback <= 365:
            raise ValueError("lookback out of bounds")
        self.lookback = lookback

    def predict(
        self, values: dict[date, Decimal | None], cutoff: date, horizon: int
    ) -> tuple[Decimal, ...] | None:
        sample = [values.get(cutoff - timedelta(days=i)) for i in range(self.lookback)]
        if any(v is None for v in sample):
            return None
        estimate = sum(sample, Decimal(0)) / Decimal(self.lookback)
        return (estimate,) * horizon


class SeasonalNaive:
    name = "SEASONAL_NAIVE"
    version = "1"

    def __init__(self, period: int = 7):
        if not 1 <= period <= 365:
            raise ValueError("seasonal period out of bounds")
        self.period = period

    def predict(
        self, values: dict[date, Decimal | None], cutoff: date, horizon: int
    ) -> tuple[Decimal, ...] | None:
        result = []
        for step in range(1, horizon + 1):
            source = cutoff + timedelta(days=step)
            while source > cutoff:
                source -= timedelta(days=self.period)
            value = values.get(source)
            if value is None:
                return None
            result.append(value)
        return tuple(result)


class Naive:
    name = "NAIVE"
    version = "1"

    def predict(
        self, values: dict[date, Decimal | None], cutoff: date, horizon: int
    ) -> tuple[Decimal, ...] | None:
        last = values.get(cutoff)
        return None if last is None else (last,) * horizon


def _identity_value(value):
    """Convert supported model settings to stable JSON values; reject opaque state."""
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("forecast model configuration must be finite")
        return {"float_hex": value.hex()}
    if isinstance(value, Decimal):
        return {"decimal": str(value)}
    if isinstance(value, datetime):
        return {"datetime": value.isoformat()}
    if isinstance(value, date):
        return {"date": value.isoformat()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("forecast model configuration keys must be strings")
        return {key: _identity_value(value[key]) for key in sorted(value)}
    if isinstance(value, (tuple, list)):
        return [_identity_value(item) for item in value]
    raise TypeError(f"unsupported forecast model setting: {type(value).__qualname__}")


def _run_identity(series: ValidatedSeries, model: ForecastModel, cutoff: date, horizon: int) -> str:
    manifest = series.manifest
    parameters = _identity_value(vars(model) if hasattr(model, "__dict__") else {})
    identity = {
        "identity_version": 2,
        "tenant_id": manifest.tenant_id,
        "sku_id": series.sku_id,
        "unit": series.unit,
        "source_dataset_id": manifest.source_dataset_id,
        "source_snapshot_id": manifest.source_snapshot_id,
        "source_snapshot_version": manifest.source_snapshot_version,
        "source_input_version": manifest.input_version,
        "source_watermark": manifest.source_watermark.isoformat(),
        "target_definition": TARGET,
        "model_type": f"{type(model).__module__}.{type(model).__qualname__}",
        "model_name": model.name,
        "model_version": model.version,
        "model_parameters": parameters,
        "training_cutoff": cutoff.isoformat(),
        "forecast_horizon": horizon,
    }
    payload = json.dumps(
        identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    return f"forecast-v2:{digest}"


def forecast(
    series: ValidatedSeries,
    model: ForecastModel,
    *,
    cutoff: date,
    horizon: int,
    generated_at: datetime,
) -> ForecastRun:
    if not 1 <= horizon <= 365:
        raise ValueError("horizon out of bounds")
    status = series.status
    predictions = None
    if status == ForecastStatus.AVAILABLE:
        known = {
            day: value
            for day, value in series.values.items()
            if day <= cutoff and series.available_on[day] <= cutoff
        }
        predictions = model.predict(known, cutoff, horizon)
        if predictions is None:
            status = ForecastStatus.INSUFFICIENT
    points = tuple(
        ForecastPoint(period=cutoff + timedelta(days=i + 1), quantity=value)
        for i, value in enumerate(predictions or ())
    )
    return ForecastRun(
        run_id=_run_identity(series, model, cutoff, horizon),
        tenant_id=series.manifest.tenant_id,
        sku_id=series.sku_id,
        target_definition=TARGET,
        model_name=model.name,
        model_version=model.version,
        training_cutoff=cutoff,
        input_window_start=series.manifest.historical_window_start,
        horizon=horizon,
        points=points,
        unit=series.unit,
        evidence_tier=series.manifest.evidence_tier,
        integration_mode=series.manifest.integration_mode,
        source_refs=(series.manifest.source_dataset_id, series.manifest.source_snapshot_id),
        status=status,
        diagnostics=series.diagnostics
        if predictions is not None
        else series.diagnostics
        + (("REQUIRED_HISTORY_MISSING",) if status == ForecastStatus.INSUFFICIENT else ()),
        assumptions=(f"{model.name} baseline; observed accepted demand only",),
        limitations=("Baseline estimate; not a future order or reservation",),
        generated_at=generated_at,
    )
