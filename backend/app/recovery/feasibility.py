from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.core.schemas import Commitment, FeasibilityAssessment, FeasibilityState

from .models import OperationalSnapshotReference, ValidationSource


@dataclass(frozen=True)
class FeasibilityResult:
    status: FeasibilityState
    solver_status: str
    constraints: list[str]
    evidence_refs: list[str]
    assumptions: list[str]
    validation_source: ValidationSource


class FeasibilityEvaluator(Protocol):
    """Compatibility boundary for P2's pure evaluator.

    P2's production contract is evaluate(snapshot, proposed_changes, commitment).
    P3 does not calculate ATP or BOM; it only supplies a snapshot reference and
    normalizes the result for the recovery planner.
    """

    def evaluate(
        self,
        snapshot: OperationalSnapshotReference,
        proposed_changes: dict[str, Any],
        commitment: Commitment,
    ) -> FeasibilityResult: ...


def _normalise_result(result: Any, source: ValidationSource) -> FeasibilityResult:
    if isinstance(result, FeasibilityResult):
        return FeasibilityResult(
            status=result.status,
            solver_status=result.solver_status,
            constraints=list(result.constraints),
            evidence_refs=list(result.evidence_refs),
            assumptions=list(result.assumptions),
            validation_source=source,
        )

    if isinstance(result, FeasibilityAssessment):
        return FeasibilityResult(
            status=result.status,
            solver_status=result.solver_status.value,
            constraints=[constraint.code for constraint in result.constraints],
            evidence_refs=list(result.evidence_refs),
            assumptions=list(result.assumptions),
            validation_source=source,
        )

    return FeasibilityResult(
        status=FeasibilityState(str(getattr(result, "status", FeasibilityState.UNKNOWN))),
        solver_status=str(getattr(result, "solver_status", "UNKNOWN")),
        constraints=list(getattr(result, "constraints", [])),
        evidence_refs=list(getattr(result, "evidence_refs", [])),
        assumptions=list(getattr(result, "assumptions", [])),
        validation_source=source,
    )


class P2FeasibilityAdapter:
    """Adapter for the real P2 evaluator without importing P2 implementation code."""

    def __init__(self, evaluator: Any) -> None:
        self._evaluator = evaluator

    def evaluate(
        self,
        snapshot: OperationalSnapshotReference,
        proposed_changes: dict[str, Any],
        commitment: Commitment,
    ) -> FeasibilityResult:
        result = self._evaluator.evaluate(snapshot, proposed_changes, commitment)
        return _normalise_result(result, ValidationSource.REAL_P2_VALIDATED)


class SyntheticP2Evaluator:
    """Contract-compatible P2 test double for the first independent P3 slice.

    Outcomes are supplied as fixtures. This class deliberately does not inspect
    inventory, run ATP, or calculate a BOM. The real P2 evaluator can replace it
    through the same interface once its authoritative adapter is available.
    """

    def __init__(self, outcomes: dict[str, FeasibilityResult] | None = None) -> None:
        self._outcomes = outcomes or {
            "ALTERNATIVE_SUPPLY": FeasibilityResult(
                status=FeasibilityState.CONDITIONAL,
                solver_status="COMPLETED",
                constraints=["SUPPLIER_AVAILABILITY_UNCONFIRMED"],
                evidence_refs=["ev_supplier_003", "ev_alt_supply_request_001"],
                assumptions=["Alternative supplier availability is not confirmed."],
                validation_source=ValidationSource.TEST_DOUBLE_VALIDATED,
            ),
            "RESCHEDULE_PARTIAL_FULFILMENT": FeasibilityResult(
                status=FeasibilityState.FEASIBLE,
                solver_status="COMPLETED",
                constraints=["CUSTOMER_ACCEPTANCE_REQUIRED"],
                evidence_refs=["ev_stock_001", "ev_customer_accept_001"],
                assumptions=["The customer accepts the revised delivery window."],
                validation_source=ValidationSource.TEST_DOUBLE_VALIDATED,
            ),
        }

    def evaluate(
        self,
        snapshot: OperationalSnapshotReference,
        proposed_changes: dict[str, Any],
        commitment: Commitment,
    ) -> FeasibilityResult:
        del snapshot, commitment
        strategy = str(proposed_changes.get("strategy", ""))
        result = self._outcomes.get(
            strategy,
            FeasibilityResult(
                status=FeasibilityState.UNKNOWN,
                solver_status="UNKNOWN",
                constraints=["NO_EVALUATOR_RESULT"],
                evidence_refs=[],
                assumptions=["No P2 evaluation result was available."],
                validation_source=ValidationSource.TEST_DOUBLE_VALIDATED,
            ),
        )
        return _normalise_result(result, ValidationSource.TEST_DOUBLE_VALIDATED)
