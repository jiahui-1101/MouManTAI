from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.core.schemas import ConstraintReason, FeasibilityState, SolverStatus


def fixture():
    from app.feasibility.production_fixtures import build_production_example
    return build_production_example()


def run(snapshot, changes=None, commitment=None):
    from app.feasibility.service import evaluate
    return evaluate(snapshot, changes, fixture()[1] if commitment is None else commitment)


def changed(snapshot, mutate):
    from app.feasibility.production import EvaluationSnapshot
    data = snapshot.model_dump(exclude_computed_fields=True)
    mutate(data)
    return EvaluationSnapshot.model_validate(data)


def competing_snapshot():
    """Two versioned commitments sharing one SKU, ordered by material-use time."""
    from app.feasibility.production import EvaluationSnapshot

    snapshot, commitment = fixture()
    data = snapshot.model_dump(exclude_computed_fields=True)
    for lot in data['operational']['inventory_lots']:
        if lot['sku_id'] != 'PATTY':
            lot['quantity'] = '180'
    original = data['operational']['confirmed_commitments'][0]
    original_line = original['lines'][0]
    at_a = datetime.fromisoformat('2026-10-23T10:40:00+08:00')
    at_b = datetime.fromisoformat('2026-10-23T12:00:00+08:00')
    deadline = datetime.fromisoformat('2026-10-24T15:00:00+08:00')
    commitment_a = {
        **original,
        'commitment_id': 'commitment-A',
        'delivery_deadline': deadline,
        'lines': ({**original_line, 'line_id': 'line-A', 'quantity': '80', 'material_use_at': at_a},),
    }
    commitment_b = {
        **original,
        'commitment_id': 'commitment-B',
        'delivery_deadline': deadline,
        'lines': ({**original_line, 'line_id': 'line-B', 'quantity': '100', 'material_use_at': at_b},),
    }
    data['operational']['confirmed_commitments'] = (commitment_a, commitment_b)
    data['production']['plans'] = (
        {**data['production']['plans'][0], 'commitment_id': 'commitment-A', 'line_id': 'line-A', 'start_at': at_a},
        {**data['production']['plans'][0], 'commitment_id': 'commitment-B', 'line_id': 'line-B', 'start_at': at_b},
    )
    core_b = commitment.model_copy(update={
        'commitment_id': 'commitment-B',
        'terms': commitment.terms.model_copy(update={'deadline': deadline}),
    })
    return EvaluationSnapshot.model_validate(data), core_b


def test_four_statuses_and_shared_constraint_mapping():
    snapshot, commitment = fixture()
    assert run(snapshot).status is FeasibilityState.FEASIBLE
    short = changed(snapshot, lambda d: d['operational']['inventory_lots'][0].update(quantity='70'))
    result = run(short)
    assert result.status is FeasibilityState.INFEASIBLE
    constraint = next(c for c in result.constraints if c.code == 'MATERIAL_SHORTAGE')
    assert isinstance(constraint, ConstraintReason)
    assert (constraint.resource_id, constraint.shortage, constraint.unit, constraint.severity) == ('PATTY', Decimal('30'), 'pcs', 'HARD')
    assert constraint.deadline == snapshot.operational.confirmed_commitments[0].lines[0].material_use_at
    assert constraint.evidence_refs
    assert result.materials.materials[0].required == 100
    unknown = changed(snapshot, lambda d: d['production'].update(jobs=None))
    assert run(unknown).status is FeasibilityState.UNKNOWN
    from app.feasibility.production import ProposedChanges
    changes = ProposedChanges(tenant_id=commitment.tenant_id, commitment_id=commitment.commitment_id,
        expected_commitment_version=1, expected_snapshot_version=1, quantity='50',
        evidence_refs=('synthetic-p3-partial-proposal',))
    assert run(snapshot, changes).status is FeasibilityState.CONDITIONAL


def test_material_covered_does_not_override_missing_capacity():
    snapshot, _ = fixture()
    snapshot = changed(snapshot, lambda d: d.update(production=None))
    result = run(snapshot)
    assert result.materials.status == 'COVERED'
    assert result.status is FeasibilityState.UNKNOWN


def test_f2_10_hypothetical_quantity_reuses_atp_and_preserves_every_input():
    from app.feasibility.production import ProposedChanges
    snapshot, commitment = fixture()
    snapshot = changed(snapshot, lambda d: d['operational']['inventory_lots'][0].update(quantity='70'))
    changes = ProposedChanges(tenant_id=commitment.tenant_id, commitment_id=commitment.commitment_id,
        expected_commitment_version=1, expected_snapshot_version=1, quantity='60',
        evidence_refs=('synthetic-p3-partial-proposal',))
    before = (snapshot.model_dump_json(), commitment.model_dump_json(), changes.model_dump_json())
    assert run(snapshot).status is FeasibilityState.INFEASIBLE
    result = run(snapshot, changes)
    assert result.status is FeasibilityState.CONDITIONAL
    assert next(r for r in result.materials.materials if r.sku_id == 'PATTY').required == 60
    assert result.capacity.operations[0].required_minutes == 60
    assert run(snapshot, changes) == result
    assert before == (snapshot.model_dump_json(), commitment.model_dump_json(), changes.model_dump_json())


def test_hypothetical_reschedule_does_not_remove_competing_jobs():
    from app.feasibility.production import ProposedChanges
    from app.feasibility.tests.test_capacity import dt
    snapshot, commitment = fixture()
    def mutate(data):
        data['production']['jobs'] = ({'job_id': 'existing', 'tenant_id': commitment.tenant_id,
            'resource_ids': ('kitchen-line-1',), 'start_at': dt('09:00:00'), 'end_at': dt('10:00:00'), 'source_refs': ('production-jobs',)},)
    snapshot = changed(snapshot, mutate)
    assert run(snapshot).status is FeasibilityState.INFEASIBLE
    changes = ProposedChanges(tenant_id=commitment.tenant_id, commitment_id=commitment.commitment_id,
        expected_commitment_version=1, expected_snapshot_version=1, production_start_at=dt('10:00:00'),
        evidence_refs=('synthetic-p3-reschedule-proposal',))
    assert run(snapshot, changes).status is FeasibilityState.CONDITIONAL
    assert snapshot.production.jobs[0].start_at == dt('09:00:00')


@pytest.mark.parametrize('mode', ['snapshot_version', 'commitment_version', 'tenant', 'terms', 'copied_tenant'])
def test_version_tenant_terms_and_validator_bypass_are_refused(mode):
    from app.feasibility.production import ProposedChanges
    snapshot, commitment = fixture()
    kwargs = dict(tenant_id=commitment.tenant_id, commitment_id=commitment.commitment_id,
        expected_commitment_version=1, expected_snapshot_version=1, quantity='60', evidence_refs=('p3-proposal',))
    if mode == 'snapshot_version':
        kwargs['expected_snapshot_version'] = 2
    elif mode == 'commitment_version':
        kwargs['expected_commitment_version'] = 2
    elif mode == 'tenant':
        kwargs['tenant_id'] = 'other'
    elif mode == 'terms':
        commitment = commitment.model_copy(update={'terms': commitment.terms.model_copy(update={'quantity': Decimal('999')})})
    else:
        bad = snapshot.production.resources[0].model_copy(update={'tenant_id': 'other'})
        snapshot = snapshot.model_copy(update={'production': snapshot.production.model_copy(update={'resources': (bad,)})})
    with pytest.raises(ValueError):
        run(snapshot, ProposedChanges(**kwargs), commitment)


def test_stale_sources_and_declared_current_version_are_not_safe():
    snapshot, _ = fixture()
    stale = changed(snapshot, lambda d: d.update(current_snapshot_version=2))
    result = run(stale)
    assert result.status is FeasibilityState.UNKNOWN
    assert result.solver_status is SolverStatus.STALE
    stale = changed(snapshot, lambda d: d.update(as_of=d['as_of'] + timedelta(days=5)))
    assert run(stale).status is FeasibilityState.UNKNOWN


def test_metadata_evidence_time_assumptions_and_no_invented_affected_ids():
    snapshot, commitment = fixture()
    result = run(snapshot)
    assert result.tenant_id == commitment.tenant_id
    assert result.commitment_id == commitment.commitment_id
    assert result.commitment_version == 1
    assert result.snapshot_version == 1
    assert result.assessed_at == snapshot.as_of
    assert result.solver_status is SolverStatus.COMPLETED
    assert result.evidence_refs and result.assumptions
    assert 'affected_commitment_ids' not in result.model_dump()
    assert result.shared_output_blocker == 'P5_AFFECTED_COMMITMENT_IDS_EMPTY_SCHEMA_SUPPORT'
    assert run(snapshot) == result


def test_unknown_evidence_takes_precedence_over_unproven_schedule_failure():
    snapshot, _ = fixture()
    def mutate(d):
        d['production']['jobs'] = None
        d['production']['processes'][0]['minutes_per_unit'] = '10'
    assert run(changed(snapshot, mutate)).status is FeasibilityState.UNKNOWN


def test_unrelated_commitment_deadline_failure_does_not_make_target_infeasible():
    from app.feasibility.tests.test_capacity import dt
    snapshot, _ = fixture()
    def mutate(data):
        target = data['operational']['confirmed_commitments'][0]
        data['operational']['confirmed_commitments'] = (target, {
            **target, 'commitment_id': 'other', 'delivery_deadline': dt('11:00:00'),
            'lines': ({**target['lines'][0], 'line_id': 'other-line', 'quantity': '20', 'material_use_at': dt('11:00:00')},),
        })
        data['operational']['inventory_lots'][0]['quantity'] = '120'
        data['production']['plans'] = (*data['production']['plans'], {
            **data['production']['plans'][0], 'commitment_id': 'other', 'line_id': 'other-line', 'start_at': dt('11:00:00'),
        })
    result = run(changed(snapshot, mutate))
    assert result.status is FeasibilityState.FEASIBLE
    assert all(c.code != 'DELIVERY_DEADLINE' for c in result.constraints)


def test_hypothetical_supply_insertion_and_job_deletion_are_not_supported_inputs():
    from app.feasibility.production import ProposedChanges
    snapshot, commitment = fixture()
    for key in ('supplier_deliveries', 'remove_jobs', 'approved'):
        with pytest.raises(ValueError):
            ProposedChanges.model_validate(dict(tenant_id=commitment.tenant_id, commitment_id=commitment.commitment_id,
                expected_commitment_version=1, expected_snapshot_version=1, quantity='50',
                evidence_refs=('synthetic-proposal',), **{key: []}))


def test_returned_constraint_mutation_cannot_change_subsequent_evaluations():
    snapshot, _ = fixture()
    snapshot = changed(snapshot, lambda d: d['operational']['inventory_lots'][0].update(quantity='70'))
    first = run(snapshot)
    first.constraints[0].evidence_refs.clear()
    assert run(snapshot).constraints[0].evidence_refs


def test_hypothetical_quantity_cannot_hide_new_shortage_for_competing_commitment():
    from app.feasibility.production import ProposedChanges
    from app.feasibility.tests.test_capacity import dt
    snapshot, commitment = fixture()
    def mutate(data):
        target = data['operational']['confirmed_commitments'][0]
        data['operational']['confirmed_commitments'] = (target, {
            **target, 'commitment_id': 'other',
            'lines': ({**target['lines'][0], 'line_id': 'other-line', 'quantity': '20', 'material_use_at': dt('11:00:00')},),
        })
        data['operational']['inventory_lots'][0]['quantity'] = '120'
        data['production']['plans'] = (*data['production']['plans'], {
            **data['production']['plans'][0], 'commitment_id': 'other', 'line_id': 'other-line', 'start_at': dt('11:00:00'),
        })
    snapshot = changed(snapshot, mutate)
    assert run(snapshot).status is FeasibilityState.FEASIBLE
    proposal = ProposedChanges(tenant_id=commitment.tenant_id, commitment_id=commitment.commitment_id,
        expected_commitment_version=1, expected_snapshot_version=1, quantity='110', evidence_refs=('synthetic-proposal',))
    result = run(snapshot, proposal)
    assert result.status is FeasibilityState.INFEASIBLE
    assert any(c.code == 'HYPOTHETICAL_COMPETING_MATERIAL_SHORTAGE' and c.resource_id == 'PATTY'
        and c.shortage == 10 for c in result.constraints)


def test_existing_unrelated_material_shortage_is_not_new_hypothetical_harm():
    from app.feasibility.production import ProposedChanges
    from app.feasibility.tests.test_capacity import dt
    snapshot, commitment = fixture()
    def mutate(data):
        target = data['operational']['confirmed_commitments'][0]
        data['operational']['confirmed_commitments'] = (target, {
            **target, 'commitment_id': 'other',
            'lines': ({**target['lines'][0], 'line_id': 'other-line', 'quantity': '20', 'material_use_at': dt('11:00:00')},),
        })
        data['production']['plans'] = (*data['production']['plans'], {
            **data['production']['plans'][0], 'commitment_id': 'other', 'line_id': 'other-line', 'start_at': dt('11:00:00'),
        })
    snapshot = changed(snapshot, mutate)
    assert run(snapshot).status is FeasibilityState.FEASIBLE
    assert any(r.commitment_id == 'other' and r.sku_id == 'PATTY' and r.shortage == 20
        for r in run(snapshot).materials.materials)
    proposal = ProposedChanges(tenant_id=commitment.tenant_id, commitment_id=commitment.commitment_id,
        expected_commitment_version=1, expected_snapshot_version=1, quantity='90', evidence_refs=('synthetic-proposal',))
    assert run(snapshot, proposal).status is FeasibilityState.CONDITIONAL


def test_hypothetical_deadline_extension_remains_pending_customer_agreement():
    from app.feasibility.production import ProposedChanges
    snapshot, commitment = fixture()
    proposal = ProposedChanges(tenant_id=commitment.tenant_id, commitment_id=commitment.commitment_id,
        expected_commitment_version=1, expected_snapshot_version=1,
        deadline=commitment.terms.deadline + timedelta(days=1), evidence_refs=('synthetic-negotiation',))
    result = run(snapshot, proposal)
    assert result.status is FeasibilityState.CONDITIONAL
    assert commitment.terms.deadline == snapshot.operational.confirmed_commitments[0].delivery_deadline


def test_stale_production_and_inventory_sources_preserve_stale_solver_status():
    snapshot, _ = fixture()
    def mutate(data):
        data['production']['sources'][0]['observed_at'] -= timedelta(days=1)
        data['production']['sources'][0]['valid_through'] = data['as_of'] - timedelta(seconds=1)
    result = run(changed(snapshot, mutate))
    assert result.status is FeasibilityState.UNKNOWN
    assert result.solver_status is SolverStatus.STALE


def test_provisional_allocation_shortage_is_unknown_with_aggregate_shortage_evidence():
    snapshot, target = competing_snapshot()

    result = run(snapshot, commitment=target)

    assert result.status is FeasibilityState.UNKNOWN
    dependency = next(c for c in result.constraints
                      if c.code == 'ALLOCATION_DEPENDENT_MATERIAL_SHORTAGE' and c.resource_id == 'PATTY')
    assert (dependency.resource_id, dependency.shortage, dependency.unit, dependency.severity) == (
        'PATTY', Decimal('80'), 'pcs', 'INFORMATIONAL')
    assert dependency.evidence_refs
    assert not any(c.code == 'MATERIAL_SHORTAGE' and c.severity == 'HARD' for c in result.constraints)
    rows = {r.commitment_id: r for r in result.materials.materials if r.sku_id == 'PATTY'}
    assert (rows['commitment-A'].shortage, rows['commitment-B'].shortage) == (0, Decimal('80'))


def test_f2_01_total_eligible_supply_shortage_remains_hard_and_infeasible():
    snapshot, _ = fixture()
    short = changed(snapshot, lambda data: data['operational']['inventory_lots'][0].update(quantity='70'))

    result = run(short)

    assert result.status is FeasibilityState.INFEASIBLE
    shortage = next(c for c in result.constraints if c.code == 'MATERIAL_SHORTAGE')
    assert (shortage.shortage, shortage.unit, shortage.severity) == (Decimal('30'), 'pcs', 'HARD')


@pytest.mark.parametrize('eligibility', ['protected_reservation', 'wrong_location', 'expired_before_target'])
def test_protected_or_ineligible_competitor_allocations_are_not_reallocatable(eligibility):
    snapshot, target = competing_snapshot()
    def mutate(data):
        lot = data['operational']['inventory_lots'][0]
        if eligibility == 'protected_reservation':
            data['operational']['reservations'] = ({
                'reservation_id': 'reservation-A', 'tenant_id': target.tenant_id,
                'inventory_lot_id': lot['lot_id'], 'commitment_id': 'commitment-A',
                'quantity': '80', 'unit': 'pcs', 'status': 'ACTIVE',
                'source_refs': ('source-reservations-001',),
            },)
        elif eligibility == 'wrong_location':
            lot['warehouse_id'] = 'warehouse-A'
            for row in data['operational']['confirmed_commitments']:
                row['lines'][0]['warehouse_id'] = 'warehouse-A' if row['commitment_id'] == 'commitment-A' else 'warehouse-B'
        else:
            lot['expires_at'] = datetime.fromisoformat('2026-10-23T11:30:00+08:00')
    snapshot = changed(snapshot, mutate)

    result = run(snapshot, commitment=target)

    assert result.status is FeasibilityState.INFEASIBLE
    assert not any(c.code == 'ALLOCATION_DEPENDENT_MATERIAL_SHORTAGE' for c in result.constraints)
    assert any(c.code == 'MATERIAL_SHORTAGE' and c.severity == 'HARD' for c in result.constraints)


def test_hypothetical_reallocation_cannot_hide_displaced_confirmed_material_demand():
    from app.feasibility.production import ProposedChanges
    snapshot, target = competing_snapshot()
    proposal = ProposedChanges(
        tenant_id=target.tenant_id, commitment_id=target.commitment_id,
        expected_commitment_version=target.commitment_version,
        expected_snapshot_version=snapshot.operational.snapshot_version,
        production_start_at=datetime.fromisoformat('2026-10-23T09:00:00+08:00'),
        evidence_refs=('synthetic-reallocation-proposal',),
    )

    result = run(snapshot, proposal, target)

    assert result.status is FeasibilityState.INFEASIBLE
    displaced = next(c for c in result.constraints
                      if c.code == 'HYPOTHETICAL_COMPETING_MATERIAL_SHORTAGE' and c.resource_id == 'PATTY')
    assert (displaced.shortage, displaced.severity) == (Decimal('80'), 'HARD')


@pytest.mark.parametrize('failure,expected_code', [
    ('deadline', 'DELIVERY_DEADLINE'),
    ('job_conflict', 'JOB_CONFLICT'),
    ('working_window', 'CAPACITY_WINDOW_VIOLATION'),
])
def test_independent_capacity_hard_failures_remain_infeasible(failure, expected_code):
    from app.feasibility.tests.test_capacity import dt
    snapshot, commitment = fixture()
    def mutate(data):
        if failure == 'deadline':
            deadline = dt('11:00:00')
            data['operational']['confirmed_commitments'][0]['delivery_deadline'] = deadline
        elif failure == 'job_conflict':
            data['production']['jobs'] = ({
                'job_id': 'blocking-job', 'tenant_id': commitment.tenant_id,
                'resource_ids': ('kitchen-line-1',), 'start_at': dt('10:00:00'),
                'end_at': dt('11:00:00'), 'source_refs': ('production-jobs',),
            },)
        else:
            data['operational']['capacity_calendars'][0]['windows'][0]['end_at'] = dt('10:00:00')
            data['operational']['capacity_calendars'][0]['windows'][0]['available_minutes'] = '180'
    snapshot = changed(snapshot, mutate)
    if failure == 'deadline':
        commitment = commitment.model_copy(update={
            'terms': commitment.terms.model_copy(update={'deadline': dt('11:00:00')}),
        })

    result = run(snapshot, commitment=commitment)

    assert result.materials.status == 'COVERED'
    assert result.status is FeasibilityState.INFEASIBLE
    assert any(c.code == expected_code and c.severity == 'HARD' for c in result.constraints)
