"""Pure advisory orchestration and the fail-closed P2 verification boundary."""

from __future__ import annotations

import hashlib
import json

from .cp_sat import ORTOOLS_VERSION, solve
from .models import (
    CandidateBinding,
    ComparisonResult,
    Exclusion,
    JointVerificationResult,
    P2ConstraintSpec,
    PortfolioRequest,
    PortfolioScenario,
    ProjectedPortfolio,
    SolverStatus,
    Strategy,
)
from .ports import ConstraintSpecProvider, JointPortfolioVerifier
from .validation import validate_spec


class VerifierUnavailable(RuntimeError):
    pass


def _digest(value) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    elif isinstance(value, tuple):
        value = [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else item for item in value
        ]
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def allocation_digest(projection: ProjectedPortfolio) -> str:
    return _digest(projection.allocations)


def schedule_digest(projection: ProjectedPortfolio) -> str:
    return _digest(projection.schedule)


def projected_portfolio_digest(projection: ProjectedPortfolio) -> str:
    return _digest(projection)


def _result(
    request: PortfolioRequest, trigger: str, *, scenarios=(), limitations=()
) -> ComparisonResult:
    scenarios = tuple(
        PortfolioScenario.model_validate(
            {
                **scenario.model_dump(),
                "tenant_id": request.tenant_id,
                "snapshot_id": request.snapshot_id,
                "snapshot_version": request.snapshot_version,
                "constraint_spec_version": request.constraint_spec_version,
                "integration_mode": request.integration_mode,
                "solver_version": ORTOOLS_VERSION,
                "evidence_refs": tuple(sorted({*request.evidence_refs, *scenario.evidence_refs})),
                "evidence_maturity": (
                    "TEST_FIXTURE"
                    if request.integration_mode == "SYNTHETIC"
                    else (
                        "P2_VERIFIED"
                        if scenario.validation_status == "P2_VALIDATED"
                        else "UNVERIFIED"
                    )
                ),
                "limitations": (
                    "No operational authority; SME decision and P5 revalidation required.",
                    *(
                        ("Synthetic fixture only.",)
                        if request.integration_mode == "SYNTHETIC"
                        else ()
                    ),
                ),
            }
        )
        for scenario in scenarios
    )
    return ComparisonResult(
        tenant_id=request.tenant_id,
        portfolio_run_id=request.portfolio_run_id,
        snapshot_id=request.snapshot_id,
        snapshot_version=request.snapshot_version,
        constraint_spec_version=request.constraint_spec_version,
        trigger=trigger,
        integration_mode=request.integration_mode,
        scenarios=scenarios,
        limitation_codes=tuple(limitations),
    )


def _verify(
    request: PortfolioRequest, projection: ProjectedPortfolio, verifier: JointPortfolioVerifier
) -> JointVerificationResult:
    if request.integration_mode == "LIVE":
        # There is no ratified P2 joint-portfolio receipt contract in this PR's owner interface.
        raise VerifierUnavailable("P2_JOINT_VERIFIER_UNAVAILABLE")
    if getattr(verifier, "authority", None) != "SYNTHETIC_TEST_FIXTURE":
        raise VerifierUnavailable("SYNTHETIC_VERIFIER_PROVENANCE_UNAVAILABLE")
    try:
        receipt = verifier.verify(request, projection)
    except (LookupError, TimeoutError, ConnectionError, NotImplementedError) as error:
        raise VerifierUnavailable from error
    selected = set(projection.selected_order_ids)
    expected_bindings = tuple(
        CandidateBinding(
            order_request_id=c.order_request_id,
            request_version=c.request_version,
            terms_revision=c.terms_revision,
            terms_hash=c.terms_hash,
            source_identity=c.source_identity,
            evidence_refs=c.evidence_refs,
        )
        for c in sorted(request.candidates, key=lambda candidate: candidate.order_request_id)
        if c.order_request_id in selected
    )
    if (
        projection.tenant_id != request.tenant_id
        or projection.portfolio_run_id != request.portfolio_run_id
        or projection.snapshot_id != request.snapshot_id
        or projection.snapshot_version != request.snapshot_version
        or projection.spec_version != request.constraint_spec_version
        or projection.assessment_watermark != request.assessment_watermark
        or len(projection.selected_order_ids) != len(selected)
        or not selected.issubset({c.order_request_id for c in request.candidates})
        or projection.selected_order_bindings != expected_bindings
    ):
        raise ValueError("PROJECTED_PORTFOLIO_BINDING_MISMATCH")

    if (
        receipt.status != "FIXTURE_VALIDATED"
        or receipt.source_authority != "SYNTHETIC_TEST_FIXTURE"
        or not receipt.source_version
        or receipt.tenant_id != request.tenant_id
        or receipt.snapshot_id != request.snapshot_id
        or receipt.snapshot_version != request.snapshot_version
        or receipt.constraint_spec_version != request.constraint_spec_version
        or receipt.assessment_watermark != request.assessment_watermark
        or receipt.portfolio_run_id != request.portfolio_run_id
        or receipt.validated_order_ids != projection.selected_order_ids
        or receipt.validated_order_bindings != projection.selected_order_bindings
        or receipt.allocation_digest != allocation_digest(projection)
        or receipt.schedule_digest != schedule_digest(projection)
        or receipt.projected_portfolio_digest != projected_portfolio_digest(projection)
        or receipt.evaluated_at != request.evaluated_at
        or receipt.valid_through != request.source_valid_through
        or receipt.valid_through < receipt.evaluated_at
        or not receipt.portfolio_validation_id
        or not receipt.evidence_refs
    ):
        raise ValueError("VALIDATION_MISMATCH")
    return receipt


def _scenario(
    request: PortfolioRequest,
    spec: P2ConstraintSpec,
    verifier: JointPortfolioVerifier,
    strategy: Strategy,
) -> PortfolioScenario:
    if strategy == Strategy.PROFIT:
        finances = [c.financial for c in request.candidates]
        if (
            any(
                f is None or f.valid_through < request.evaluated_at or f.approved_policy_id == ""
                for f in finances
            )
            or len({f.currency for f in finances if f}) != 1
        ):
            return PortfolioScenario(
                strategy=strategy, validation_status="PROFIT_COMPARISON_UNAVAILABLE"
            )
    if strategy == Strategy.EXPIRY_AWARE and any(lot.expires_minute is None for lot in spec.lots):
        return PortfolioScenario(
            strategy=strategy, validation_status="EXPIRY_COMPARISON_UNAVAILABLE"
        )
    try:
        status, projection, value, unit = solve(request, spec, strategy)
    except ValueError as error:
        return PortfolioScenario(strategy=strategy, validation_status=str(error))
    if projection is None:
        return PortfolioScenario(
            strategy=strategy,
            solver_status=status,
            validation_status="NOT_VALIDATED",
            diagnostics=(f"ortools={ORTOOLS_VERSION}",),
        )
    try:
        receipt = _verify(request, projection, verifier)
    except VerifierUnavailable:
        return PortfolioScenario(
            strategy=strategy,
            solver_status=status,
            validation_status="P2_JOINT_VERIFIER_UNAVAILABLE",
        )
    except ValueError:
        return PortfolioScenario(
            strategy=strategy, solver_status=status, validation_status="VALIDATION_MISMATCH"
        )
    selected = set(projection.selected_order_ids)
    exclusions = []
    for candidate in request.candidates:
        if candidate.order_request_id in selected:
            continue
        single_status = solve(
            request, spec, Strategy.FCFS, forced_selected=frozenset({candidate.order_request_id})
        )[0]
        reason = (
            "INDIVIDUAL_HARD_CONSTRAINT"
            if single_status == SolverStatus.INFEASIBLE
            else "NOT_SELECTED_UNDER_OBJECTIVE"
            if single_status == SolverStatus.OPTIMAL
            else "UNDETERMINED_CONSTRAINT"
        )
        exclusions.append(
            Exclusion(order_request_id=candidate.order_request_id, reason_code=reason)
        )
    return PortfolioScenario(
        strategy=strategy,
        selected_order_ids=projection.selected_order_ids,
        exclusions=tuple(exclusions),
        allocations=projection.allocations,
        schedule=projection.schedule,
        solver_status=status,
        validation_status=receipt.status,
        validation_id=receipt.portfolio_validation_id,
        objective_value=value,
        objective_unit=unit,
        evidence_refs=tuple(sorted({*spec.source_refs, *receipt.evidence_refs})),
        diagnostics=(f"ortools={ORTOOLS_VERSION}",),
    )


def _fcfs(
    request: PortfolioRequest, spec: P2ConstraintSpec, verifier: JointPortfolioVerifier
) -> PortfolioScenario:
    selected: frozenset[str] = frozenset()
    exclusions = []
    current: ProjectedPortfolio | None = None
    receipt: JointVerificationResult | None = None
    for candidate in sorted(request.candidates, key=lambda c: (c.received_at, c.order_request_id)):
        proposed = selected | {candidate.order_request_id}
        status, projection, _, _ = solve(
            request, spec, Strategy.FCFS, forced_selected=frozenset(proposed)
        )
        if status == SolverStatus.INFEASIBLE:
            single_status = solve(
                request,
                spec,
                Strategy.FCFS,
                forced_selected=frozenset({candidate.order_request_id}),
            )[0]
            exclusions.append(
                Exclusion(
                    order_request_id=candidate.order_request_id,
                    reason_code=(
                        "INDIVIDUAL_HARD_CONSTRAINT"
                        if single_status == SolverStatus.INFEASIBLE
                        else "JOINT_RESOURCE_CONTENTION"
                        if single_status == SolverStatus.OPTIMAL
                        else "UNDETERMINED_CONSTRAINT"
                    ),
                )
            )
            continue
        if projection is None:
            return PortfolioScenario(
                strategy=Strategy.FCFS, solver_status=status, validation_status="NOT_VALIDATED"
            )
        try:
            candidate_receipt = _verify(request, projection, verifier)
        except VerifierUnavailable:
            return PortfolioScenario(
                strategy=Strategy.FCFS, validation_status="P2_JOINT_VERIFIER_UNAVAILABLE"
            )
        except ValueError:
            return PortfolioScenario(
                strategy=Strategy.FCFS, validation_status="VALIDATION_MISMATCH"
            )
        selected = frozenset(proposed)
        current = projection
        receipt = candidate_receipt
    return PortfolioScenario(
        strategy=Strategy.FCFS,
        selected_order_ids=tuple(sorted(selected)),
        exclusions=tuple(exclusions),
        allocations=current.allocations if current else (),
        schedule=current.schedule if current else (),
        validation_status=receipt.status if receipt else "NOT_VALIDATED",
        validation_id=receipt.portfolio_validation_id if receipt else None,
        evidence_refs=(
            tuple(sorted({*spec.source_refs, *receipt.evidence_refs}))
            if current and receipt
            else ()
        ),
        diagnostics=("Deterministic verified received_at, then order_request_id.",),
    )


def _trigger(request: PortfolioRequest, spec: P2ConstraintSpec) -> str:
    if len(request.candidates) < 2:
        return "SINGLE_ORDER_P2"
    if request.comparison_requested:
        return "EXPLICIT_SME_COMPARISON"
    for i, left in enumerate(request.candidates):
        for right in request.candidates[i + 1 :]:
            left_id, right_id = left.order_request_id, right.order_request_id
            left_lots = {
                lot
                for req in spec.requirements
                if req.order_request_id == left_id
                for lot in req.compatible_lot_ids
            }
            right_lots = {
                lot
                for req in spec.requirements
                if req.order_request_id == right_id
                for lot in req.compatible_lot_ids
            }
            left_resources = {
                r
                for task in spec.tasks
                if task.order_request_id == left_id
                for r in task.resource_ids
            }
            right_resources = {
                r
                for task in spec.tasks
                if task.order_request_id == right_id
                for r in task.resource_ids
            }
            if not (left_lots & right_lots or left_resources & right_resources):
                continue
            singles = [
                solve(request, spec, Strategy.FCFS, forced_selected=frozenset({oid}))[0]
                for oid in (left_id, right_id)
            ]
            pair = solve(
                request, spec, Strategy.FCFS, forced_selected=frozenset({left_id, right_id})
            )[0]
            if any(
                status
                in (
                    SolverStatus.UNKNOWN,
                    SolverStatus.MODEL_INVALID,
                    SolverStatus.SOLVER_UNAVAILABLE,
                )
                for status in (*singles, pair)
            ):
                return "SOURCE_UNAVAILABLE"
            if (
                singles == [SolverStatus.OPTIMAL, SolverStatus.OPTIMAL]
                and pair == SolverStatus.INFEASIBLE
            ):
                return "JOINT_CONTENTION"
    if len(request.candidates) == 2:
        return "SINGLE_ORDER_P2"
    # Pairwise feasibility does not imply joint feasibility: three orders can
    # each use one unit of a two-unit lot while every pair remains feasible.
    selected = frozenset(candidate.order_request_id for candidate in request.candidates)
    full_status = solve(request, spec, Strategy.FCFS, forced_selected=selected)[0]
    if full_status in (
        SolverStatus.UNKNOWN,
        SolverStatus.MODEL_INVALID,
        SolverStatus.SOLVER_UNAVAILABLE,
    ):
        return "SOURCE_UNAVAILABLE"
    if full_status != SolverStatus.INFEASIBLE:
        return "SINGLE_ORDER_P2"
    single_statuses = [
        solve(request, spec, Strategy.FCFS, forced_selected=frozenset({order_id}))[0]
        for order_id in sorted(selected)
    ]
    if any(
        status
        in (SolverStatus.UNKNOWN, SolverStatus.MODEL_INVALID, SolverStatus.SOLVER_UNAVAILABLE)
        for status in single_statuses
    ):
        return "SOURCE_UNAVAILABLE"
    if all(status == SolverStatus.OPTIMAL for status in single_statuses):
        return "JOINT_CONTENTION"
    return "SINGLE_ORDER_P2"


def compare(
    request: PortfolioRequest,
    *,
    provider: ConstraintSpecProvider | None = None,
    verifier: JointPortfolioVerifier | None = None,
) -> ComparisonResult:
    """No endpoint, persistence or business command; caller must supply trusted ports."""
    try:
        request = PortfolioRequest.model_validate(request.model_dump())
    except ValueError:
        return _result(request, "INSUFFICIENT_DATA", limitations=("INVALID_PORTFOLIO_INPUT",))
    if provider is None:
        return _result(
            request, "SOURCE_UNAVAILABLE", limitations=("P2_CONSTRAINT_SPEC_UNAVAILABLE",)
        )
    try:
        spec = P2ConstraintSpec.model_validate(provider.build_for_portfolio(request).model_dump())
        validate_spec(request, spec)
    except (ValueError, AttributeError) as error:
        return _result(request, "SOURCE_UNAVAILABLE", limitations=(str(error),))
    except (LookupError, TimeoutError, ConnectionError, NotImplementedError):
        return _result(
            request, "SOURCE_UNAVAILABLE", limitations=("P2_CONSTRAINT_SPEC_UNAVAILABLE",)
        )
    if verifier is None or getattr(verifier, "authority", None) != spec.owner:
        return _result(
            request, "SOURCE_UNAVAILABLE", limitations=("P2_JOINT_VERIFIER_UNAVAILABLE",)
        )
    try:
        trigger = _trigger(request, spec)
    except ValueError as error:
        return _result(request, "SOURCE_UNAVAILABLE", limitations=(str(error),))
    if trigger == "SOURCE_UNAVAILABLE":
        return _result(request, trigger, limitations=("SOLVER_STATUS_UNKNOWN",))
    if trigger == "SINGLE_ORDER_P2":
        return _result(request, trigger, limitations=("PORTFOLIO_COMPARISON_NOT_TRIGGERED",))
    try:
        scenarios = (
            _fcfs(request, spec, verifier),
            _scenario(request, spec, verifier, Strategy.PROFIT),
            _scenario(request, spec, verifier, Strategy.EXPIRY_AWARE),
        )
    except ValueError as error:
        return _result(request, trigger, limitations=(str(error),))
    limitations = ["SYNTHETIC_TEST_FIXTURE_ONLY"] if request.integration_mode == "SYNTHETIC" else []
    if any(s.validation_status == "VALIDATION_MISMATCH" for s in scenarios):
        limitations.append("VALIDATION_MISMATCH")
    return _result(request, trigger, scenarios=scenarios, limitations=limitations)
