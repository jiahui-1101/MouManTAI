"""Read-only operational readiness for an existing, confirmed P2 target.

This projection is neither an order-acceptance decision nor a reservation
authority. A future pending-order adapter needs a separately reviewed mapping.
"""

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime

from app.core.schemas import Commitment, FeasibilityState

from .models import FrozenModel, _utc
from .production import EvaluationSnapshot
from .service import evaluate


class OperationalReadiness(FrozenModel):
    tenant_id: str
    commitment_id: str
    snapshot_id: str | None = None
    snapshot_version: int | None = None
    assessed_at: AwareDatetime
    status: Literal["READY_FOR_REVIEW", "BLOCKED", "UNKNOWN"]
    reason_codes: tuple[str, ...]
    assessment_id: str | None = None
    feasibility_status: FeasibilityState | None = None
    evidence_refs: tuple[str, ...] = ()
    reservation_authorized: Literal[False] = False


def assess_operational_readiness(
    *,
    tenant_id: str,
    commitment: Commitment,
    snapshot: EvaluationSnapshot | None,
    checked_at: datetime,
) -> OperationalReadiness:
    """Re-evaluate P2 at an explicit time; never read/write state or reserve.

    The caller must supply server-read, tenant-scoped current input. This
    function checks the explicit version token but cannot attest its origin or
    lock it against a later reservation transaction.
    """
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        raise ValueError("checked_at must be offset-aware")
    if not tenant_id.strip():
        raise ValueError("tenant_id is required")

    base = {
        "tenant_id": tenant_id,
        "commitment_id": commitment.commitment_id,
        "assessed_at": checked_at,
    }

    def unknown(*codes: str) -> OperationalReadiness:
        return OperationalReadiness(**base, status="UNKNOWN", reason_codes=tuple(codes))

    if commitment.tenant_id != tenant_id:
        return unknown("TENANT_MISMATCH")
    if snapshot is None:
        return unknown("SNAPSHOT_UNAVAILABLE")
    operational = snapshot.operational
    base.update(snapshot_id=operational.snapshot_id, snapshot_version=operational.snapshot_version)
    if operational.tenant_id != tenant_id:
        return unknown("TENANT_MISMATCH")
    if snapshot.current_snapshot_version is None:
        return unknown("CURRENT_VERSION_UNAVAILABLE")
    if snapshot.current_snapshot_version != operational.snapshot_version:
        return unknown("SNAPSHOT_VERSION_CONFLICT")
    if _utc(checked_at) < _utc(operational.captured_at):
        return unknown("SNAPSHOT_FROM_FUTURE")
    if not operational.sources or any(
        source.source_ref is not None and not source.evidence_refs for source in operational.sources
    ):
        return unknown("SOURCE_PROVENANCE_INCOMPLETE")

    # P2 owns source freshness, inventory/BOM ATP, capacity and contention.
    # A copied time changes only the evaluation clock, not the supplied facts.
    candidate = snapshot.model_copy(update={"as_of": checked_at})
    try:
        result = evaluate(candidate, None, commitment)
    except ValueError:
        # Includes unsupported multi-line Core/snapshot mapping and absent or
        # inconsistent target terms. Do not infer a feasible pending order.
        return unknown("UNSUPPORTED_OR_INCONSISTENT_INPUT")

    status = (
        "READY_FOR_REVIEW"
        if result.status is FeasibilityState.FEASIBLE
        and result.evidence_complete
        and not result.allocation_dependent
        else "BLOCKED"
        if result.status is FeasibilityState.INFEASIBLE
        else "UNKNOWN"
    )
    reasons = tuple(sorted({constraint.code for constraint in result.constraints}))
    return OperationalReadiness(
        **base,
        status=status,
        reason_codes=reasons,
        assessment_id=result.assessment_id,
        feasibility_status=result.status,
        evidence_refs=result.evidence_refs,
    )
