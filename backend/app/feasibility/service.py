"""Pure P2 evaluation, using the existing batch ATP/BOM and capacity checks.

P5's shared FeasibilityAssessment accepts an empty actual-impact set. This P2
result remains a calculation projection with detailed operational output, not a
replacement shared contract or a persistence adapter. No affected IDs are
inferred from assessment scope.
"""

from datetime import datetime
from decimal import Decimal
from hashlib import sha256

from app.core.schemas import Commitment, ConstraintReason, FeasibilityState, SolverStatus

from .capacity import CapacityResult, check_capacity
from .inventory import calculate_atp
from .materials import MaterialATP, MaterialAvailability
from .models import FrozenModel, _utc
from .production import EvaluationSnapshot, ProposedChanges
from .quantities import add, subtract


class EvaluationResult(FrozenModel):
    assessment_id: str
    tenant_id: str
    commitment_id: str
    commitment_version: int
    snapshot_id: str
    snapshot_version: int
    status: FeasibilityState
    solver_status: SolverStatus
    evidence_complete: bool
    allocation_dependent: bool
    assessed_at: datetime
    constraints: tuple[ConstraintReason, ...]
    assumptions: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    materials: MaterialATP
    capacity: CapacityResult


def _allocation_can_cover_target(snapshot: EvaluationSnapshot, materials: MaterialATP,
                                 target_row: MaterialAvailability) -> tuple[bool, Decimal]:
    """Return whether currently allocated, target-eligible supply could cover a short row.

    This is a status proof over the existing ATP allocation evidence, not a
    second inventory calculator or a proposed stock reallocation. Reservations
    are deliberately excluded: they remain protected for their owners.
    """
    operational = snapshot.operational
    lots = {lot.lot_id: lot for lot in operational.inventory_lots}
    deliveries = {delivery.delivery_id: delivery for delivery in operational.incoming_deliveries}
    reassignable = Decimal(0)

    for competing in materials.materials:
        if (competing.commitment_id == target_row.commitment_id
                or competing.sku_id != target_row.sku_id
                or competing.unit != target_row.unit):
            continue
        for allocation in competing.allocations:
            if allocation.kind == 'LOT':
                supply = lots.get(allocation.supply_id)
                eligible = (supply is not None
                    and (target_row.warehouse_id is None or supply.warehouse_id == target_row.warehouse_id)
                    and not supply.is_expired_at(target_row.needed_by))
            elif allocation.kind == 'RECEIPT':
                supply = deliveries.get(allocation.supply_id)
                eligible = (supply is not None and supply.confirmation_status == 'CONFIRMED'
                    and (target_row.warehouse_id is None or supply.warehouse_id == target_row.warehouse_id)
                    and _utc(supply.expected_at) <= _utc(target_row.needed_by)
                    and _utc(supply.expected_at) <= _utc(operational.logistics_cutoff_at))
            else:
                # An active reservation is owned supply, never a free pool.
                eligible = False
            if eligible:
                reassignable = add(reassignable, allocation.quantity)

    current_target_supply = subtract(target_row.required, target_row.shortage)
    return add(current_target_supply, reassignable) >= target_row.required, reassignable


def _batch_shortage(materials: MaterialATP, target_row: MaterialAvailability) -> Decimal:
    total = Decimal(0)
    for row in materials.materials:
        if row.sku_id == target_row.sku_id and row.unit == target_row.unit:
            total = add(total, row.shortage)
    return total


def evaluate(snapshot: EvaluationSnapshot, proposed_changes: ProposedChanges | None,
             commitment: Commitment) -> EvaluationResult:
    """Evaluate a version-bound target without any operational side effects.

    Currently one Core term maps to exactly one snapshot line. All competing
    snapshot commitments stay in the existing batch calculation. Missing Core
    adapters, multi-line mapping and supply substitutions are not guessed.
    """
    snapshot = EvaluationSnapshot.model_validate(snapshot.model_dump(exclude_computed_fields=True))
    commitment = Commitment.model_validate(commitment.model_dump())
    original = snapshot.operational
    if original.tenant_id != commitment.tenant_id:
        raise ValueError('tenant scope mismatch')
    target = next((c for c in original.confirmed_commitments if c.commitment_id == commitment.commitment_id), None)
    if target is None or target.commitment_version != commitment.commitment_version:
        raise ValueError('target commitment/version not in snapshot')
    if commitment.agreement_state != 'CONFIRMED':
        raise ValueError('confirmed operational target required')
    if len(target.lines) != 1:
        raise ValueError('Core-to-snapshot multi-line mapping requires reviewed adapter')
    line = target.lines[0]
    if (line.sku_id, line.quantity, line.unit, target.delivery_deadline) != (
        commitment.terms.sku, commitment.terms.quantity, commitment.terms.unit, commitment.terms.deadline):
        raise ValueError('Core terms do not match versioned snapshot target')

    proposal_assumptions, proposal_refs = [], ()
    candidate = snapshot
    if proposed_changes is not None:
        proposed_changes = ProposedChanges.model_validate(proposed_changes.model_dump())
        if (proposed_changes.tenant_id != commitment.tenant_id
                or proposed_changes.commitment_id != commitment.commitment_id):
            raise ValueError('proposal tenant/commitment mismatch')
        if (proposed_changes.expected_commitment_version != commitment.commitment_version
                or proposed_changes.expected_snapshot_version != original.snapshot_version):
            raise ValueError('stale proposal version')
        data = snapshot.model_dump(exclude_computed_fields=True)
        target_data = next(c for c in data['operational']['confirmed_commitments'] if c['commitment_id'] == commitment.commitment_id)
        if proposed_changes.quantity is not None:
            target_data['lines'][0]['quantity'] = proposed_changes.quantity
        if proposed_changes.deadline is not None:
            target_data['delivery_deadline'] = proposed_changes.deadline
        if proposed_changes.production_start_at is not None:
            target_data['lines'][0]['material_use_at'] = proposed_changes.production_start_at
            if data['production']:
                for plan in data['production']['plans']:
                    if plan['commitment_id'] == commitment.commitment_id and plan['line_id'] == line.line_id:
                        plan['start_at'] = proposed_changes.production_start_at
        candidate = EvaluationSnapshot.model_validate(data)
        proposal_assumptions.append('Hypothetical change only: required operational approval/customer agreement remains unresolved; no committed terms, jobs or reservations changed.')
        proposal_refs = proposed_changes.evidence_refs

    materials = calculate_atp(candidate.operational, tenant_id=commitment.tenant_id, as_of=candidate.as_of)
    capacity = check_capacity(candidate, tenant_id=commitment.tenant_id, commitment_id=commitment.commitment_id)
    constraints = list(capacity.constraints)
    for issue in materials.issues:
        constraints.append(ConstraintReason(code=issue.code, resource_id=issue.resource_id or 'materials',
            severity='INFORMATIONAL', evidence_refs=list(issue.evidence_refs)))
    allocation_dependent = False
    if proposed_changes is not None and materials.status != 'UNKNOWN':
        baseline = calculate_atp(original, tenant_id=commitment.tenant_id, as_of=snapshot.as_of)
        if baseline.status == 'UNKNOWN':
            constraints.append(ConstraintReason(code='UNKNOWN_BASELINE_FOR_PROPOSAL', resource_id='materials',
                severity='INFORMATIONAL', evidence_refs=list(baseline.evidence_refs)))
        else:
            before = {(r.commitment_id, r.line_id, r.sku_id): r.shortage for r in baseline.materials}
            for row in materials.materials:
                if (row.commitment_id != commitment.commitment_id
                        and row.shortage > before.get((row.commitment_id, row.line_id, row.sku_id), 0)):
                    constraints.append(ConstraintReason(code='HYPOTHETICAL_COMPETING_MATERIAL_SHORTAGE',
                        resource_id=row.sku_id, shortage=row.shortage, unit=row.unit, deadline=row.needed_by,
                        severity='HARD', evidence_refs=list(row.evidence_refs)))
    for row in materials.materials:
        if row.commitment_id == commitment.commitment_id and row.shortage > 0:
            can_cover, reassignable = _allocation_can_cover_target(candidate, materials, row)
            if reassignable > 0:
                allocation_dependent |= can_cover
                constraints.append(ConstraintReason(code='ALLOCATION_DEPENDENT_MATERIAL_SHORTAGE',
                    resource_id=row.sku_id, shortage=_batch_shortage(materials, row), unit=row.unit,
                    deadline=row.needed_by, severity='INFORMATIONAL', evidence_refs=list(row.evidence_refs)))
            if not can_cover:
                proven_shortage = subtract(row.required,
                    add(subtract(row.required, row.shortage), reassignable))
                constraints.append(ConstraintReason(code=row.code, resource_id=row.sku_id,
                    shortage=proven_shortage, unit=row.unit, deadline=row.needed_by, severity='HARD',
                    evidence_refs=list(row.evidence_refs)))
    # Query-mode proposals must not gain coverage by quietly displacing an
    # existing commitment. Compare the same batch ATP, never another calculator.
    # This is candidate validation only; no Phase 4 graph/events/risk propagation.
    stale_version = (candidate.current_snapshot_version is not None
                     and candidate.current_snapshot_version != original.snapshot_version)
    if stale_version:
        constraints.append(ConstraintReason(code='STALE_SNAPSHOT_VERSION', resource_id=original.snapshot_id,
                                            severity='INFORMATIONAL', evidence_refs=[]))
    stale = stale_version or any(c.code.startswith('STALE_') for c in constraints)
    evidence_unknown = (stale or materials.status == 'UNKNOWN' or capacity.status == FeasibilityState.UNKNOWN
                        or any(c.code == 'UNKNOWN_BASELINE_FOR_PROPOSAL' for c in constraints))
    allocation_unknown = allocation_dependent
    hard = any(c.severity == 'HARD' for c in constraints)
    # Untrusted/incomplete evidence still dominates. With complete evidence,
    # independent HARD proof applies to this supplied target/fixed booking even
    # if material coverage remains allocation-policy dependent. Allocation-only
    # uncertainty stays UNKNOWN and never implies approval to displace demand.
    status = (FeasibilityState.UNKNOWN if evidence_unknown else FeasibilityState.INFEASIBLE if hard
              else FeasibilityState.UNKNOWN if allocation_unknown
              else FeasibilityState.CONDITIONAL if proposed_changes is not None else FeasibilityState.FEASIBLE)
    if proposed_changes is not None:
        constraints.append(ConstraintReason(code='HYPOTHETICAL_CHANGE_PENDING_APPROVAL',
            resource_id=commitment.commitment_id, severity='INFORMATIONAL', evidence_refs=list(proposal_refs)))
    refs = tuple(sorted({*commitment.evidence_refs, *materials.evidence_refs, *capacity.evidence_refs, *proposal_refs}))
    material_assumptions = tuple(a for a in materials.assumptions if not a.startswith('Material-only check;'))
    allocation_assumptions = (
        'Allocation-dependent shortage is UNKNOWN; its informational amount is the current ATP batch aggregate and no confirmed demand is reprioritized.',
    ) if allocation_dependent else ()
    assumptions = (*material_assumptions, *capacity.assumptions, *proposal_assumptions,
        'Assessment time is explicit historical replay time; current operational version must be supplied by P5.',
        'affected_commitment_ids represents the actual Impact Set; no impact IDs are inferred from assessment scope.',
        *allocation_assumptions)
    identity = (snapshot.model_dump_json() + commitment.model_dump_json()
                + (proposed_changes.model_dump_json() if proposed_changes is not None else 'null'))
    return EvaluationResult(assessment_id='p2-local-' + sha256(identity.encode()).hexdigest(),
        tenant_id=commitment.tenant_id, commitment_id=commitment.commitment_id,
        commitment_version=commitment.commitment_version, snapshot_id=original.snapshot_id,
        snapshot_version=original.snapshot_version, status=status,
        evidence_complete=not evidence_unknown, allocation_dependent=allocation_dependent,
        solver_status=SolverStatus.STALE if stale else SolverStatus.UNKNOWN if (evidence_unknown or allocation_unknown)
        else SolverStatus.COMPLETED,
        assessed_at=snapshot.as_of, constraints=tuple(constraints), assumptions=tuple(assumptions),
        evidence_refs=refs, materials=materials, capacity=capacity)
