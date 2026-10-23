"""Forward risk composition delegates resource semantics to P2."""

from __future__ import annotations

from .models import ForecastAlert, ForecastRun, RiskFamily
from .ports import CurrentSnapshot, P2ScenarioAttestation
from .risk import p2_alert


def stockout_or_expiry(
    run: ForecastRun, snapshot: CurrentSnapshot | None, attestation: P2ScenarioAttestation | None
) -> ForecastAlert:
    return p2_alert(run, RiskFamily.STOCKOUT_OR_EXPIRY, snapshot, attestation)


def capacity_or_deadline(
    run: ForecastRun, snapshot: CurrentSnapshot | None, attestation: P2ScenarioAttestation | None
) -> ForecastAlert:
    return p2_alert(run, RiskFamily.CAPACITY_OR_DEADLINE, snapshot, attestation)
