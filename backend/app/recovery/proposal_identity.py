"""P3 plan-to-Core proposal identity contract.

Existing version-one offers keep their original plan ID. Each later offer has
its own Core proposal row while the logical Recovery plan ID stays stable.
"""

from app.core.errors import DomainError


def proposal_id_for_plan(plan_id: str, plan_version: int) -> str:
    if not plan_id or plan_version < 1:
        raise DomainError("PROPOSAL_PLAN_IDENTITY_CONFLICT", "Invalid Recovery plan identity", status_code=409)
    return plan_id if plan_version == 1 else f"{plan_id}_v{plan_version}"


def require_proposal_binding(
    plan_id: str, plan_version: int, proposal_id: str | None, proposal_version: int | None,
) -> tuple[str, int]:
    expected_id = proposal_id_for_plan(plan_id, plan_version)
    # Older V1 plan payloads may omit the explicit proposal fields.
    if plan_version == 1 and proposal_id is None and proposal_version is None:
        return expected_id, 1
    if (proposal_id, proposal_version) != (expected_id, plan_version):
        raise DomainError(
            "PROPOSAL_PLAN_IDENTITY_CONFLICT",
            "Proposal identity does not match the versioned Recovery plan",
            status_code=409,
        )
    return expected_id, plan_version
