"""Pending-order projection through the existing P2 kernel for Mock Orbyte.

P2's current evaluator requires a confirmed target inside its input snapshot.
This adapter creates that target only in a throwaway typed copy. It never
persists or reports confirmation before the approval/reservation transaction.
"""

from datetime import datetime

from app.core.errors import DomainError
from app.core.schemas import Commitment, FeasibilityState
from app.feasibility.production import EvaluationSnapshot
from app.feasibility.service import EvaluationResult, evaluate
from app.orders.terms import OrderTerms


def project_pending_order(snapshot: EvaluationSnapshot, terms: OrderTerms,
                          *, commitment_id: str, checked_at: datetime,
                          require_feasible: bool = True) -> tuple[EvaluationSnapshot, EvaluationResult]:
    if snapshot.operational.tenant_id != terms.tenant_id:
        raise DomainError("MOCK_RESOURCE_TENANT_MISMATCH", "Mock resource tenant mismatch", status_code=409)
    if snapshot.current_snapshot_version != snapshot.operational.snapshot_version:
        raise DomainError("STALE_RESOURCE_VERSION", "Mock resource snapshot changed", status_code=409)
    if len(terms.items) != 1:
        raise DomainError("MULTILINE_REVIEW_REQUIRED", "Multi-line P2 mapping needs review", status_code=409)
    line = terms.items[0]
    if checked_at >= terms.window_start or terms.window_end <= checked_at:
        raise DomainError("DELIVERY_WINDOW_STALE", "Delivery window is no longer current", status_code=409)
    if any(row.commitment_id == commitment_id for row in snapshot.operational.confirmed_commitments):
        raise DomainError("MOCK_TARGET_EXISTS", "Target already occupies the resource snapshot", status_code=409)
    source = next((row for row in snapshot.operational.sources if row.kind == "confirmed_commitments"), None)
    if source is None:
        raise DomainError("MOCK_RESOURCE_INCOMPLETE", "Commitment source is missing", status_code=409)
    if snapshot.production is None:
        raise DomainError("MOCK_RESOURCE_INCOMPLETE", "Production capacity is missing", status_code=409)
    plan_source = next((row for row in snapshot.production.sources if row.kind == "plans"), None)
    if plan_source is None:
        raise DomainError("MOCK_RESOURCE_INCOMPLETE", "Production plan source is missing", status_code=409)

    data = snapshot.model_dump(mode="python", exclude_computed_fields=True)
    data["operational"]["confirmed_commitments"] = [*data["operational"]["confirmed_commitments"], {
        "commitment_id": commitment_id, "tenant_id": terms.tenant_id, "commitment_version": 1,
        "delivery_deadline": terms.window_end,
        "lines": ({"line_id": f"{commitment_id}-line-1", "sku_id": line.sku,
                   "quantity": line.quantity, "unit": line.unit,
                   "material_use_at": terms.window_start, "warehouse_id": None},),
        "source_refs": (source.source_id,),
    }]
    data["production"]["plans"] = [*data["production"]["plans"], {
        "tenant_id": terms.tenant_id, "commitment_id": commitment_id,
        "commitment_version": 1, "line_id": f"{commitment_id}-line-1",
        "start_at": terms.window_start, "dispatch_cutoff_at": terms.window_end,
        "source_refs": (plan_source.source_id,),
    }]
    data["as_of"] = checked_at
    try:
        projected = EvaluationSnapshot.model_validate(data)
        target = Commitment.model_validate({
            "tenant_id": terms.tenant_id, "commitment_id": commitment_id,
            "order_id": terms.order_request_id, "customer_id": terms.customer_id,
            "terms": {"sku": line.sku, "quantity": line.quantity, "unit": line.unit,
                      "deadline": terms.window_end,
                      "items": [{"sku": line.sku, "quantity": line.quantity, "unit": line.unit}]},
            "agreement_state": "CONFIRMED", "feasibility_state": "NOT_ASSESSED",
            "risk_state": "NORMAL", "recovery_state": "NONE", "fulfilment_state": "NOT_STARTED",
            "commitment_version": 1, "evidence_refs": list(terms.evidence_refs), "updated_at": checked_at,
        })
        result = evaluate(projected, None, target)
    except ValueError as exc:
        raise DomainError("P2_INPUT_UNSUPPORTED", "Mock P2 input cannot be safely evaluated",
                          status_code=409) from exc
    if require_feasible and (result.status is not FeasibilityState.FEASIBLE
                             or not result.evidence_complete or result.allocation_dependent):
        raise DomainError("P2_NOT_FEASIBLE", "Fresh P2 assessment did not prove feasibility",
                          status_code=409, details={"status": result.status.value,
                                                    "reason_codes": sorted({c.code for c in result.constraints})})
    return projected, result
