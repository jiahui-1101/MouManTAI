"""Exact interval validation of supplied fixed, non-preemptible bookings.

No scheduler optimization or guessed production/transport rate. Half-open
intervals permit one job to start exactly when another finishes. An interval
must be covered by real working windows, not just a daily minutes budget.
"""

from datetime import datetime, timedelta
from decimal import Context, Decimal, DecimalException, localcontext

from app.core.schemas import ConstraintReason, FeasibilityState

from .bom import evidence_for, source_issues
from .models import FrozenModel, SkuSupplyType, SourceKind, _utc
from .production import EvaluationSnapshot
from .quantities import add, multiply


def microseconds(start, end):
    duration = _utc(end) - _utc(start)
    return (duration.days * 86400 + duration.seconds) * 1_000_000 + duration.microseconds


def duration_delta(minutes):
    units = multiply(minutes, Decimal(60_000_000))
    if units != units.to_integral_value():
        raise ValueError('sub-microsecond production durations unsupported')
    return timedelta(microseconds=int(units))


def diagnostic_minutes(units):
    # Diagnostic precision is explicit and independent of ambient Decimal
    # settings; feasibility itself compares exact integer microseconds.
    with localcontext(Context(prec=40)):
        return Decimal(units) / Decimal(60_000_000)


class OperationResult(FrozenModel):
    commitment_id: str
    commitment_version: int
    line_id: str
    resource_ids: tuple[str, ...]
    start_at: datetime
    finish_at: datetime
    required_minutes: Decimal
    available_minutes: Decimal | None
    evidence_refs: tuple[str, ...]


class CapacityResult(FrozenModel):
    status: FeasibilityState
    operations: tuple[OperationResult, ...] = ()
    constraints: tuple[ConstraintReason, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = (
        'Supplied fixed bookings only; INFEASIBLE does not prove all reschedules impossible.',
        'Resources are exclusive and occupied simultaneously; operations are non-preemptible.',
        'Explicit delivery lead time follows production; dispatch cutoff is separate from inbound receiving cutoff.',
    )


def check_capacity(snapshot: EvaluationSnapshot, *, tenant_id: str,
                   commitment_id: str | None = None) -> CapacityResult:
    if tenant_id != snapshot.operational.tenant_id:
        raise ValueError('tenant scope mismatch')
    snapshot = EvaluationSnapshot.model_validate(snapshot.model_dump(exclude_computed_fields=True))
    operational, production = snapshot.operational, snapshot.production
    constraints, operations, refs = [], [], set()
    finish_bounds = {}
    unknown = False
    active_commitment = None

    def reason(code, resource, *, missing=False, shortage=None, deadline=None, evidence=(), severity='HARD', owners=None):
        nonlocal unknown
        scope = owners if owners is not None else ((active_commitment,) if active_commitment else ())
        # Missing competing production inputs can hide a shared-resource booking,
        # so remain conservative globally. Known unrelated hard/soft violations
        # must not falsely turn the target into an affected commitment.
        if not missing and commitment_id and scope and commitment_id not in scope:
            return
        unknown |= missing
        constraints.append(ConstraintReason(code=code, resource_id=resource, shortage=shortage,
            unit='minutes' if shortage is not None else None, deadline=deadline,
            severity='INFORMATIONAL' if missing else severity, evidence_refs=sorted(set(evidence))))
        refs.update(evidence)

    for issue in source_issues(operational, (SourceKind.CAPACITY_CALENDARS,), snapshot.as_of):
        reason(issue.code, issue.resource_id or 'capacity', missing=True, evidence=issue.evidence_refs)
    if production is None:
        reason('MISSING_PRODUCTION_DATA', 'production', missing=True)
        return CapacityResult(status=FeasibilityState.UNKNOWN, constraints=tuple(constraints), evidence_refs=tuple(sorted(refs)))

    sources = {s.source_id: s for s in production.sources}
    for kind in ('resources', 'processes', 'jobs', 'plans'):
        if not any(s.kind == kind for s in production.sources):
            reason('MISSING_PRODUCTION_SOURCE', kind, missing=True)
    for source in production.sources:
        refs.update((source.source_id, *source.evidence_refs))
        if _utc(source.valid_through) < _utc(snapshot.as_of):
            reason('STALE_PRODUCTION_SOURCE', source.source_id, missing=True, evidence=source.evidence_refs)

    def evidence(row):
        missing = [key for key in row.source_refs if key not in sources]
        if missing:
            reason('MISSING_PRODUCTION_EVIDENCE', missing[0], missing=True)
        return tuple(sorted({*row.source_refs, *(r for key in row.source_refs if key in sources for r in sources[key].evidence_refs)}))

    for row in (*production.resources, *production.processes, *production.plans, *(production.jobs or ())):
        refs.update(evidence(row))
    if production.jobs is None:
        reason('MISSING_JOB_LEDGER', 'jobs', missing=True)

    resources = {r.resource_id: r for r in production.resources}
    processes = {p.sku_id: p for p in production.processes}
    plans = {(p.commitment_id, p.line_id): p for p in production.plans}
    commitments = {c.commitment_id: c for c in operational.confirmed_commitments}
    if commitment_id is not None and commitment_id not in commitments:
        raise ValueError('capacity target not in snapshot')
    skus = {s.sku_id: s for s in operational.sku_catalog}
    for plan in production.plans:
        owner = commitments.get(plan.commitment_id)
        if owner is None or owner.commitment_version != plan.commitment_version or not any(l.line_id == plan.line_id for l in owner.lines):
            reason('UNRESOLVED_PLAN_VERSION', plan.commitment_id, missing=True, evidence=evidence(plan))

    # All manufactured intermediate routing needs an explicit multi-step model;
    # current implementation only supports a single process with purchased leaves.
    for component in operational.bom_components:
        if skus[component.component_sku_id].supply_type == SkuSupplyType.MANUFACTURED:
            reason('UNSUPPORTED_PRODUCTION_ROUTING', component.component_sku_id, missing=True)

    occupied = []
    for job in sorted(production.jobs or (), key=lambda j: j.job_id):
        for resource in job.resource_ids:
            if resource not in resources:
                reason('UNKNOWN_JOB_RESOURCE', resource, missing=True, evidence=evidence(job))
            occupied.append((resource, _utc(job.start_at), _utc(job.end_at), job.job_id, None, evidence(job)))

    for commitment in sorted(operational.confirmed_commitments, key=lambda c: c.commitment_id):
        active_commitment = commitment.commitment_id
        for line in sorted(commitment.lines, key=lambda l: l.line_id):
            if skus[line.sku_id].supply_type != SkuSupplyType.MANUFACTURED:
                reason('UNSUPPORTED_PURCHASED_FULFILMENT', line.sku_id, missing=True)
                continue
            process, plan = processes.get(line.sku_id), plans.get((commitment.commitment_id, line.line_id))
            if process is None or plan is None:
                reason('MISSING_PROCESS_OR_PLAN', line.sku_id, missing=True)
                continue
            row_refs = tuple(sorted({*evidence(process), *evidence(plan)}))
            if process.minutes_per_unit is None or process.delivery_lead_minutes is None:
                reason('MISSING_PROCESSING_OR_TRANSIT_TIME', process.process_id, missing=True, evidence=row_refs)
                continue
            if process.unit != skus[line.sku_id].base_unit:
                reason('UNSUPPORTED_PROCESS_UNIT', process.process_id, missing=True, evidence=row_refs)
                continue
            if _utc(plan.start_at) != _utc(line.material_use_at) or _utc(plan.start_at) < _utc(snapshot.as_of):
                reason('UNSUPPORTED_PRODUCTION_START', line.line_id, missing=True, evidence=row_refs)
                continue
            try:
                minutes = add(process.setup_minutes, multiply(
                    operational.quantity_in_base(line.sku_id, line.quantity, line.unit), process.minutes_per_unit))
                finish = _utc(plan.start_at) + duration_delta(minutes)
                delivery = finish + duration_delta(process.delivery_lead_minutes)
                finish_bounds[(commitment.commitment_id, line.line_id)] = min(
                    _utc(plan.dispatch_cutoff_at),
                    _utc(commitment.delivery_deadline) - duration_delta(process.delivery_lead_minutes),
                    _utc(production.jobs_covered_through))
            except (DecimalException, OverflowError, ValueError):
                reason('UNSUPPORTED_PRODUCTION_DURATION', process.process_id, missing=True, evidence=row_refs)
                continue
            start = _utc(plan.start_at)
            if start < _utc(production.jobs_covered_from) or finish > _utc(production.jobs_covered_through):
                reason('INCOMPLETE_JOB_HORIZON', 'jobs', missing=True, evidence=row_refs)
            if delivery > _utc(commitment.delivery_deadline):
                reason('DELIVERY_DEADLINE', line.sku_id, deadline=commitment.delivery_deadline, evidence=row_refs)
            if finish > _utc(plan.dispatch_cutoff_at):
                reason('DISPATCH_CUTOFF', line.sku_id, deadline=plan.dispatch_cutoff_at, evidence=row_refs)
            if plan.preferred_finish_at and finish > _utc(plan.preferred_finish_at):
                reason('PREFERRED_FINISH_MISSED', line.sku_id, deadline=plan.preferred_finish_at, evidence=row_refs, severity='SOFT')
            for resource in process.resource_ids:
                if resource not in resources:
                    reason('UNKNOWN_PRODUCTION_RESOURCE', resource, missing=True, evidence=row_refs)
                    continue
                calendars = [c for c in operational.capacity_calendars if c.resource_id == resource]
                if not calendars:
                    reason('MISSING_RESOURCE_CALENDAR', resource, missing=True, evidence=row_refs)
                    continue
                calendar_refs = evidence_for(operational, tuple(sorted({ref for c in calendars for ref in c.source_refs})))
                refs.update(calendar_refs)
                windows = sorted((w for c in calendars for w in c.windows), key=lambda w: _utc(w.start_at))
                ambiguous = any(multiply(w.available_minutes, Decimal(60_000_000)) != Decimal(microseconds(w.start_at, w.end_at)) for w in windows)
                if ambiguous:
                    reason('UNLOCATED_WORKING_BREAKS', resource, missing=True, evidence=calendar_refs)
                    continue
                cursor, total_us = start, 0
                for window in windows:
                    left, right = max(start, _utc(window.start_at)), min(finish, _utc(window.end_at))
                    if left < right:
                        total_us += microseconds(left, right)
                    if _utc(window.start_at) <= cursor < _utc(window.end_at):
                        cursor = max(cursor, min(finish, _utc(window.end_at)))
                if cursor < finish:
                    # Exact missing microseconds / 60e6 may be repeating; report
                    # no numeric shortage rather than round evidence silently.
                    gap = microseconds(start, finish) - total_us
                    reason('CAPACITY_WINDOW_VIOLATION', resource,
                           shortage=diagnostic_minutes(gap) if gap % 3 == 0 else None,
                           deadline=commitment.delivery_deadline, evidence=calendar_refs)
                occupied.append((resource, start, finish, f'{commitment.commitment_id}/{line.line_id}', commitment.commitment_id,
                                 tuple(sorted({*row_refs, *calendar_refs}))))
            operations.append(OperationResult(commitment_id=commitment.commitment_id,
                commitment_version=commitment.commitment_version, line_id=line.line_id,
                resource_ids=process.resource_ids, start_at=plan.start_at, finish_at=finish,
                required_minutes=minutes, available_minutes=None, evidence_refs=row_refs))

    ordered = sorted(occupied, key=lambda r: (r[0], r[1], r[2], r[3]))
    active_commitment = None
    for i, left in enumerate(ordered):
        for right in ordered[i + 1:]:
            if left[0] != right[0]:
                break
            if right[1] >= left[2]:
                break
            if left[1] < right[2]:
                code = 'COMMITMENT_RESOURCE_CONFLICT' if left[4] and right[4] else 'JOB_CONFLICT'
                reason(code, left[0], missing=left[4] is None and right[4] is None,
                       evidence=(*left[5], *right[5]), owners=tuple(c for c in (left[4], right[4]) if c))
    # Continuous free time from the supplied start, capped by real work,
    # dispatch/customer deadline, ledger horizon and every other booking.
    # None is deliberate when missing data prevents a trustworthy diagnostic.
    for i, operation in enumerate(operations):
        start = _utc(operation.start_at)
        bound = finish_bounds[(operation.commitment_id, operation.line_id)]
        limits = []
        complete = not unknown and production.jobs is not None and start >= _utc(production.jobs_covered_from)
        for resource in operation.resource_ids:
            windows = sorted((w for c in operational.capacity_calendars if c.resource_id == resource for w in c.windows),
                             key=lambda w: _utc(w.start_at))
            if resource not in resources or not windows or any(
                    multiply(w.available_minutes, Decimal(60_000_000)) != Decimal(microseconds(w.start_at, w.end_at))
                    for w in windows):
                complete = False
                continue
            cursor = start
            for window in windows:
                if _utc(window.start_at) <= cursor < _utc(window.end_at):
                    cursor = _utc(window.end_at)
            end = min(cursor, bound)
            own_booking = f'{operation.commitment_id}/{operation.line_id}'
            for occupied_resource, left, right, booking, owner, _ in occupied:
                if occupied_resource != resource or (owner == operation.commitment_id and booking == own_booking):
                    continue
                if left <= start < right:
                    end = start
                elif start < left:
                    end = min(end, left)
            limits.append(max(0, microseconds(start, end)))
        operations[i] = operation.model_copy(update={
            'available_minutes': diagnostic_minutes(min(limits)) if complete and limits else None})
    status = (FeasibilityState.UNKNOWN if unknown else FeasibilityState.INFEASIBLE
              if any(c.severity == 'HARD' for c in constraints) else FeasibilityState.FEASIBLE)
    constraints.sort(key=lambda c: (c.code, c.resource_id, str(c.deadline), tuple(c.evidence_refs)))
    return CapacityResult(status=status, operations=tuple(operations), constraints=tuple(constraints), evidence_refs=tuple(sorted(refs)))
