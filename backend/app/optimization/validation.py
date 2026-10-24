"""Fail-closed bindings between verified request and P2-supplied compiled facts."""

from .models import P2ConstraintSpec, PortfolioRequest


def validate_spec(request: PortfolioRequest, spec: P2ConstraintSpec) -> None:
    if request.integration_mode == "LIVE" and spec.owner != "P2":
        raise ValueError("P2_CONSTRAINT_SPEC_UNAVAILABLE")
    if request.integration_mode == "SYNTHETIC" and spec.owner != "SYNTHETIC_TEST_FIXTURE":
        raise ValueError("SYNTHETIC_SPEC_REQUIRED")
    for name, expected, actual in (
        ("tenant", request.tenant_id, spec.tenant_id),
        ("snapshot", request.snapshot_id, spec.snapshot_id),
        ("snapshot version", request.snapshot_version, spec.snapshot_version),
        ("spec version", request.constraint_spec_version, spec.spec_version),
        ("assessment", request.assessment_watermark, spec.assessment_watermark),
    ):
        if expected != actual:
            raise ValueError(f"STALE_OR_CROSS_TENANT_{name.upper().replace(' ', '_')}")
    if not spec.accepted_reservations_protected:
        raise ValueError("UNPROTECTED_ACCEPTED_RESERVATIONS")
    if (
        len(spec.lots) > request.solver.max_lots
        or len({lot.sku_id for lot in spec.lots}) > request.solver.max_skus
        or len(spec.requirements) > request.solver.max_requirements
        or len(spec.tasks) > request.solver.max_tasks
        or len(spec.fixed_jobs) > request.solver.max_fixed_jobs
        or len(spec.resources) > request.solver.max_resources
        or spec.horizon_minutes > request.solver.max_horizon_minutes
    ):
        raise ValueError("MODEL_LIMIT_EXCEEDED")
    candidates = {c.order_request_id: c for c in request.candidates}
    bindings = {b.order_request_id: b for b in spec.candidate_bindings}
    if len(bindings) != len(spec.candidate_bindings) or set(bindings) != set(candidates):
        raise ValueError("P2_CANDIDATE_BINDING_MISMATCH")
    for candidate in request.candidates:
        binding = bindings[candidate.order_request_id]
        if (
            binding.request_version != candidate.request_version
            or binding.terms_revision != candidate.terms_revision
            or binding.terms_hash != candidate.terms_hash
            or binding.source_identity != candidate.source_identity
        ):
            raise ValueError("P2_CANDIDATE_BINDING_MISMATCH")
    lots = {lot.lot_id: lot for lot in spec.lots}
    resources = {r.resource_id: r for r in spec.resources}
    tasks = {task.task_id: task for task in spec.tasks}
    for rows, key in (
        (spec.lots, "lot_id"),
        (spec.resources, "resource_id"),
        (spec.tasks, "task_id"),
        (spec.fixed_jobs, "job_id"),
    ):
        if len({getattr(row, key) for row in rows}) != len(rows):
            raise ValueError("DUPLICATE_SPEC_ID")
    if not spec.tasks or not spec.requirements:
        raise ValueError("INCOMPLETE_P2_SPEC")
    for task in spec.tasks:
        candidate = candidates.get(task.order_request_id)
        if candidate is None or task.line_id not in {line.line_id for line in candidate.lines}:
            raise ValueError("UNBOUND_P2_TASK")
        if any(r not in resources for r in task.resource_ids):
            raise ValueError("UNKNOWN_P2_RESOURCE")
        if task.latest_end_minute > spec.horizon_minutes:
            raise ValueError("TASK_OUTSIDE_HORIZON")
    for job in spec.fixed_jobs:
        if any(r not in resources for r in job.resource_ids):
            raise ValueError("UNKNOWN_FIXED_RESOURCE")
        if job.end_minute > spec.horizon_minutes:
            raise ValueError("FIXED_JOB_OUTSIDE_HORIZON")
    for requirement in spec.requirements:
        candidate = candidates.get(requirement.order_request_id)
        if candidate is None or requirement.line_id not in {
            line.line_id for line in candidate.lines
        }:
            raise ValueError("UNBOUND_P2_REQUIREMENT")
        task = tasks.get(requirement.material_use_task_id)
        if task is None or task.order_request_id != requirement.order_request_id:
            raise ValueError("UNBOUND_MATERIAL_USE_TASK")
        for lot_id in requirement.compatible_lot_ids:
            lot = lots.get(lot_id)
            if lot is None or lot.sku_id != requirement.sku_id or lot.unit != requirement.unit:
                raise ValueError("INVALID_P2_LOT_COMPATIBILITY")
    for candidate in request.candidates:
        if not any(t.order_request_id == candidate.order_request_id for t in spec.tasks):
            raise ValueError("MISSING_P2_TASK")
        if not any(r.order_request_id == candidate.order_request_id for r in spec.requirements):
            raise ValueError("MISSING_P2_REQUIREMENT")
