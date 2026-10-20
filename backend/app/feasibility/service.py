"""Pure P2 evaluation, using the existing batch ATP/BOM and capacity checks.

Final FeasibilityAssessment serialization is BLOCKED: P5 has not defined
affected_commitment_ids for ordinary single-commitment results. No affected
IDs are fabricated. This local result is not a substitute shared contract.
"""

from datetime import datetime
from hashlib import sha256

from pydantic import Field

from app.core.schemas import Commitment, ConstraintReason, FeasibilityState, SolverStatus

from .capacity import CapacityResult, check_capacity
from .inventory import calculate_atp
from .materials import MaterialATP
from .models import FrozenModel
from .production import EvaluationSnapshot, ProposedChanges


class EvaluationResult(FrozenModel):
    assessment_id: str
    tenant_id: str
    commitment_id: str
    commitment_version: int
    snapshot_id: str
    snapshot_version: int
    status: FeasibilityState
    solver_status: SolverStatus
    assessed_at: datetime
    constraints: tuple[ConstraintReason, ...]
    assumptions: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    materials: MaterialATP
    capacity: CapacityResult
    shared_output_blocker: str = Field(default='P5_AFFECTED_COMMITMENT_IDS_SEMANTICS', frozen=True)


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
    for row in materials.materials:
        if row.commitment_id == commitment.commitment_id and row.shortage > 0:
            constraints.append(ConstraintReason(code=row.code, resource_id=row.sku_id,
                shortage=row.shortage, unit=row.unit, deadline=row.needed_by, severity='HARD',
                evidence_refs=list(row.evidence_refs)))
    # Query-mode proposals must not gain coverage by quietly displacing an
    # existing commitment. Compare the same batch ATP, never another calculator.
    # This is candidate validation only; no Phase 4 graph/events/risk propagation.
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
    stale_version = (candidate.current_snapshot_version is not None
                     and candidate.current_snapshot_version != original.snapshot_version)
    if stale_version:
        constraints.append(ConstraintReason(code='STALE_SNAPSHOT_VERSION', resource_id=original.snapshot_id,
                                            severity='INFORMATIONAL', evidence_refs=[]))
    stale = stale_version or any(c.code.startswith('STALE_') for c in constraints)
    unknown = (stale or materials.status == 'UNKNOWN' or capacity.status == FeasibilityState.UNKNOWN
               or any(c.code == 'UNKNOWN_BASELINE_FOR_PROPOSAL' for c in constraints))
    hard = any(c.severity == 'HARD' for c in constraints)
    status = (FeasibilityState.UNKNOWN if unknown else FeasibilityState.INFEASIBLE if hard
              else FeasibilityState.CONDITIONAL if proposed_changes is not None else FeasibilityState.FEASIBLE)
    if proposed_changes is not None:
        constraints.append(ConstraintReason(code='HYPOTHETICAL_CHANGE_PENDING_APPROVAL',
            resource_id=commitment.commitment_id, severity='INFORMATIONAL', evidence_refs=list(proposal_refs)))
    refs = tuple(sorted({*commitment.evidence_refs, *materials.evidence_refs, *capacity.evidence_refs, *proposal_refs}))
    material_assumptions = tuple(a for a in materials.assumptions if not a.startswith('Material-only check;'))
    assumptions = (*material_assumptions, *capacity.assumptions, *proposal_assumptions,
        'Assessment time is explicit historical replay time; current operational version must be supplied by P5.',
        'Shared affected_commitment_ids semantics are unresolved; no impact IDs inferred.')
    identity = (snapshot.model_dump_json() + commitment.model_dump_json()
                + (proposed_changes.model_dump_json() if proposed_changes is not None else 'null'))
    return EvaluationResult(assessment_id='p2-local-' + sha256(identity.encode()).hexdigest(),
        tenant_id=commitment.tenant_id, commitment_id=commitment.commitment_id,
        commitment_version=commitment.commitment_version, snapshot_id=original.snapshot_id,
        snapshot_version=original.snapshot_version, status=status,
        solver_status=SolverStatus.STALE if stale else SolverStatus.UNKNOWN if unknown else SolverStatus.COMPLETED,
        assessed_at=snapshot.as_of, constraints=tuple(constraints), assumptions=tuple(assumptions),
        evidence_refs=refs, materials=materials, capacity=capacity)
