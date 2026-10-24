"""Bounded CP-SAT compiler for a P2-authored, versioned constraint specification."""

from __future__ import annotations

from decimal import Decimal

from .models import (
    CandidateBinding,
    LotAllocation,
    P2ConstraintSpec,
    PortfolioRequest,
    ProductionTask,
    ProjectedPortfolio,
    ScheduledTask,
    SolverStatus,
    Strategy,
)
from .scaling import MAX_INT, ScalingError, scaled, unscaled

try:
    from ortools import __version__ as ORTOOLS_VERSION
    from ortools.sat.python import cp_model
except ImportError:  # No production claim without the actual native solver.
    cp_model = None
    ORTOOLS_VERSION = "UNAVAILABLE"


def _allowed_starts(task: ProductionTask, spec: P2ConstraintSpec) -> list[tuple[int, int]]:
    intervals = [(task.earliest_start_minute, task.latest_end_minute - task.duration_minutes)]
    resources = {r.resource_id: r for r in spec.resources}
    for resource_id in task.resource_ids:
        next_intervals = []
        for lower, upper in intervals:
            for window in resources[resource_id].windows:
                start = max(lower, window.start_minute)
                end = min(upper, window.end_minute - task.duration_minutes)
                if start <= end:
                    next_intervals.append((start, end))
        intervals = next_intervals
    return sorted(set(intervals))


def solve(
    request: PortfolioRequest,
    spec: P2ConstraintSpec,
    strategy: Strategy,
    *,
    forced_selected: frozenset[str] | None = None,
) -> tuple[SolverStatus, ProjectedPortfolio | None, Decimal | None, str | None]:
    """Return a mathematical candidate, never a P2 feasibility certificate."""
    if cp_model is None:
        return SolverStatus.SOLVER_UNAVAILABLE, None, None, None
    if strategy not in (Strategy.PROFIT, Strategy.EXPIRY_AWARE, Strategy.FCFS):
        raise ValueError("unsupported strategy")
    model = cp_model.CpModel()
    if sum(scaled(lot.free_quantity, request.solver.quantity_scale) for lot in spec.lots) > MAX_INT:
        raise ScalingError("SCALING_OVERFLOW")
    if (
        sum(scaled(req.quantity, request.solver.quantity_scale) for req in spec.requirements)
        > MAX_INT
    ):
        raise ScalingError("SCALING_OVERFLOW")
    ids = sorted(c.order_request_id for c in request.candidates)
    x = {oid: model.NewBoolVar(f"select_{oid}") for oid in ids}
    if forced_selected is not None:
        for oid in ids:
            model.Add(x[oid] == int(oid in forced_selected))
    starts = {}
    ends = {}
    intervals_by_resource: dict[str, list] = {r.resource_id: [] for r in spec.resources}
    for task in sorted(spec.tasks, key=lambda t: t.task_id):
        allowed = _allowed_starts(task, spec)
        if not allowed:
            model.Add(x[task.order_request_id] == 0)
            continue
        start = model.NewIntVarFromDomain(
            cp_model.Domain.FromIntervals(allowed), f"start_{task.task_id}"
        )
        end = model.NewIntVar(0, spec.horizon_minutes, f"end_{task.task_id}")
        model.Add(end == start + task.duration_minutes)
        starts[task.task_id] = start
        ends[task.task_id] = end
        for resource_id in task.resource_ids:
            interval = model.NewOptionalIntervalVar(
                start,
                task.duration_minutes,
                end,
                x[task.order_request_id],
                f"interval_{task.task_id}_{resource_id}",
            )
            intervals_by_resource[resource_id].append(interval)
    for job in spec.fixed_jobs:
        for resource_id in job.resource_ids:
            intervals_by_resource[resource_id].append(
                model.NewIntervalVar(
                    job.start_minute,
                    job.end_minute - job.start_minute,
                    job.end_minute,
                    f"fixed_{job.job_id}_{resource_id}",
                )
            )
    for intervals in intervals_by_resource.values():
        if intervals:
            model.AddNoOverlap(intervals)

    lots = {lot.lot_id: lot for lot in spec.lots}
    allocations = {}
    for index, req in enumerate(spec.requirements):
        needed = scaled(req.quantity, request.solver.quantity_scale)
        parts = []
        for lot_id in sorted(set(req.compatible_lot_ids)):
            lot = lots[lot_id]
            cap = scaled(lot.free_quantity, request.solver.quantity_scale)
            y = model.NewIntVar(0, min(cap, needed), f"allocate_{index}_{lot_id}")
            allocations[index, lot_id] = y
            parts.append(y)
            use = model.NewBoolVar(f"uses_{index}_{lot_id}")
            model.Add(y >= 1).OnlyEnforceIf(use)
            model.Add(y == 0).OnlyEnforceIf(use.Not())
            start = starts.get(req.material_use_task_id)
            if start is None:
                model.Add(y == 0)
            else:
                model.Add(start >= lot.available_minute).OnlyEnforceIf(use)
                if lot.expires_minute is not None:
                    model.Add(start < lot.expires_minute).OnlyEnforceIf(use)
        model.Add(sum(parts) == needed * x[req.order_request_id])
    for lot_id, lot in lots.items():
        cap = scaled(lot.free_quantity, request.solver.quantity_scale)
        model.Add(sum(y for (index, key), y in allocations.items() if key == lot_id) <= cap)

    objective_unit = None
    if strategy == Strategy.PROFIT:
        coefficients = {}
        for candidate in request.candidates:
            finance = candidate.financial
            if finance is None:
                raise ValueError("PROFIT_COMPARISON_UNAVAILABLE")
            coefficients[candidate.order_request_id] = (
                scaled(finance.revenue, request.solver.currency_scale)
                - scaled(finance.material_cost, request.solver.currency_scale)
                - scaled(finance.labor_cost, request.solver.currency_scale)
                - scaled(finance.freight_cost, request.solver.currency_scale)
            )
        if sum(abs(v) for v in coefficients.values()) > MAX_INT:
            raise ScalingError("SCALING_OVERFLOW")
        model.Maximize(sum(coefficients[oid] * x[oid] for oid in ids))
        objective_unit = request.candidates[0].financial.currency
    elif strategy == Strategy.EXPIRY_AWARE:
        weights = {
            lot_id: spec.horizon_minutes - lot.expires_minute + 1
            for lot_id, lot in lots.items()
            if lot.expires_minute is not None
        }
        if len(weights) != len(lots):
            raise ValueError("EXPIRY_COMPARISON_UNAVAILABLE")
        secondary_bound = sum(
            scaled(lot.free_quantity, request.solver.quantity_scale) * weights[lot.lot_id]
            for lot in spec.lots
        )
        if secondary_bound > MAX_INT // (len(ids) + 1) - 1:
            raise ScalingError("SCALING_OVERFLOW")
        primary_weight = secondary_bound + 1
        model.Maximize(
            primary_weight * sum(x.values())
            + sum(weights[lot_id] * variable for (_, lot_id), variable in allocations.items())
        )
        objective_unit = "orders_served_then_FEFO"
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(request.solver.max_seconds)
    solver.parameters.random_seed = request.solver.random_seed
    solver.parameters.num_search_workers = request.solver.workers
    outcome = solver.Solve(model)
    status = {
        cp_model.OPTIMAL: SolverStatus.OPTIMAL,
        cp_model.FEASIBLE: SolverStatus.FEASIBLE_NOT_PROVEN_OPTIMAL,
        cp_model.INFEASIBLE: SolverStatus.INFEASIBLE,
        cp_model.UNKNOWN: SolverStatus.UNKNOWN,
        cp_model.MODEL_INVALID: SolverStatus.MODEL_INVALID,
    }[outcome]
    if outcome not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return status, None, None, objective_unit
    selected = tuple(oid for oid in ids if solver.Value(x[oid]))
    rows = []
    for (index, lot_id), variable in sorted(allocations.items()):
        quantity = solver.Value(variable)
        if quantity:
            req = spec.requirements[index]
            rows.append(
                LotAllocation(
                    order_request_id=req.order_request_id,
                    line_id=req.line_id,
                    lot_id=lot_id,
                    quantity=unscaled(quantity, request.solver.quantity_scale),
                )
            )
    schedule = tuple(
        ScheduledTask(
            task_id=task.task_id,
            order_request_id=task.order_request_id,
            start_minute=solver.Value(starts[task.task_id]),
            end_minute=solver.Value(ends[task.task_id]),
        )
        for task in spec.tasks
        if task.order_request_id in selected
    )
    projection = ProjectedPortfolio(
        tenant_id=request.tenant_id,
        portfolio_run_id=request.portfolio_run_id,
        snapshot_id=request.snapshot_id,
        snapshot_version=request.snapshot_version,
        spec_version=spec.spec_version,
        assessment_watermark=request.assessment_watermark,
        selected_order_ids=selected,
        selected_order_bindings=tuple(
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
        ),
        allocations=tuple(rows),
        schedule=schedule,
    )
    if strategy == Strategy.PROFIT:
        value = unscaled(sum(coefficients[oid] for oid in selected), request.solver.currency_scale)
    elif strategy == Strategy.EXPIRY_AWARE:
        value = Decimal(len(selected))
    else:
        value = None
    return status, projection, value, objective_unit
