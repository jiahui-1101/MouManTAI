"""Read-only P2 baseline checks before any future portfolio optimization.

Only existing confirmed demand is evaluated. Pending OrderRequests have no
reviewed P2 target representation and are explicitly unsupported here.
"""

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime

from app.core.schemas import FeasibilityState

from .capacity import check_capacity
from .inventory import calculate_atp
from .models import FrozenModel, _utc
from .production import EvaluationSnapshot


class PortfolioInputReadiness(FrozenModel):
    tenant_id: str
    snapshot_id: str | None = None
    snapshot_version: int | None = None
    checked_at: AwareDatetime
    status: Literal[
        "BASELINE_COMPLETE", "BASELINE_BLOCKED", "UNKNOWN", "PENDING_TARGET_UNSUPPORTED"
    ]
    blocker_codes: tuple[str, ...]
    material_status: str | None = None
    capacity_status: FeasibilityState | None = None
    evidence_refs: tuple[str, ...] = ()
    profit_strategy_available: Literal[False] = False
    expiry_strategy_available: Literal[False] = False
    allocation_authorized: Literal[False] = False


def inspect_portfolio_inputs(
    *,
    tenant_id: str,
    snapshot: EvaluationSnapshot | None,
    checked_at: datetime,
    pending_order_request_ids: tuple[str, ...] = (),
) -> PortfolioInputReadiness:
    """Check trusted-source prerequisites and existing confirmed P2 baseline.

    The caller must obtain the snapshot from a server-owned current reader.
    This function cannot authenticate that reader or protect its version against
    a later write. It never evaluates, allocates or accepts pending orders.
    """
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        raise ValueError("checked_at must be offset-aware")
    if not tenant_id.strip():
        raise ValueError("tenant_id is required")
    if len(set(pending_order_request_ids)) != len(pending_order_request_ids) or any(
        not value.strip() for value in pending_order_request_ids
    ):
        raise ValueError("pending request IDs must be unique and nonblank")
    base = {"tenant_id": tenant_id, "checked_at": checked_at}

    def result(status: str, *codes: str, **extra) -> PortfolioInputReadiness:
        return PortfolioInputReadiness(**base, status=status, blocker_codes=tuple(codes), **extra)

    if snapshot is None:
        return result("UNKNOWN", "SNAPSHOT_UNAVAILABLE")
    operational = snapshot.operational
    base.update(snapshot_id=operational.snapshot_id, snapshot_version=operational.snapshot_version)
    if operational.tenant_id != tenant_id:
        return result("UNKNOWN", "TENANT_MISMATCH")
    if snapshot.current_snapshot_version is None:
        return result("UNKNOWN", "CURRENT_VERSION_UNAVAILABLE")
    if snapshot.current_snapshot_version != operational.snapshot_version:
        return result("UNKNOWN", "SNAPSHOT_VERSION_CONFLICT")
    if _utc(checked_at) < _utc(operational.captured_at):
        return result("UNKNOWN", "SNAPSHOT_FROM_FUTURE")
    if not operational.sources or any(
        source.source_ref is not None and not source.evidence_refs for source in operational.sources
    ):
        return result("UNKNOWN", "SOURCE_PROVENANCE_INCOMPLETE")

    # Revalidate a copy at the requested instant. P2 remains the only source of
    # material and fixed-booking capacity results, including UNKNOWN semantics.
    candidate = EvaluationSnapshot.model_validate(
        snapshot.model_copy(update={"as_of": checked_at}).model_dump(exclude_computed_fields=True)
    )
    materials = calculate_atp(candidate.operational, tenant_id=tenant_id, as_of=checked_at)
    capacity = check_capacity(candidate, tenant_id=tenant_id)
    codes = tuple(
        sorted(
            {
                *(issue.code for issue in materials.issues),
                *(constraint.code for constraint in capacity.constraints),
            }
        )
    )
    refs = tuple(sorted({*materials.evidence_refs, *capacity.evidence_refs}))
    extra = {
        "material_status": materials.status,
        "capacity_status": capacity.status,
        "evidence_refs": refs,
    }
    if pending_order_request_ids:
        return result("PENDING_TARGET_UNSUPPORTED", "PENDING_TARGET_UNSUPPORTED", *codes, **extra)
    if materials.status == "UNKNOWN" or capacity.status is FeasibilityState.UNKNOWN:
        return result("UNKNOWN", *codes, **extra)
    if materials.status == "SHORTAGE" or capacity.status is FeasibilityState.INFEASIBLE:
        return result("BASELINE_BLOCKED", *codes, **extra)
    return result("BASELINE_COMPLETE", *codes, **extra)
