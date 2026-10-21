from datetime import datetime, timedelta
from decimal import Decimal, localcontext

import pytest


def dt(value):
    return datetime.fromisoformat('2026-10-23T' + value + '+08:00')


def payload():
    from app.feasibility.production_fixtures import build_production_example
    snapshot, _ = build_production_example()
    return snapshot.model_dump(exclude_computed_fields=True)


def check(data):
    from app.feasibility.production import EvaluationSnapshot
    from app.feasibility.capacity import check_capacity
    snap = EvaluationSnapshot.model_validate(data)
    return check_capacity(snap, tenant_id=snap.operational.tenant_id)


def codes(result):
    return {c.code for c in result.constraints}


def test_real_processing_duration_and_capacity_details():
    result = check(payload())
    assert result.status == 'FEASIBLE'
    row = result.operations[0]
    assert row.required_minutes == Decimal('100')
    assert row.start_at == dt('09:00:00')
    assert row.finish_at == dt('10:40:00')
    assert row.resource_ids == ('kitchen-line-1',)
    assert row.available_minutes == Decimal('480')
    assert 'synthetic-production-rate-v1' in result.evidence_refs


def test_capacity_shortage_is_not_hidden_by_daily_total():
    data = payload()
    data['production']['processes'][0]['minutes_per_unit'] = '6'
    result = check(data)
    assert result.status == 'INFEASIBLE'
    assert 'CAPACITY_WINDOW_VIOLATION' in codes(result)
    assert any(c.resource_id == 'kitchen-line-1' and c.severity == 'HARD' for c in result.constraints)


@pytest.mark.parametrize('field,value,code', [
    ('delivery_lead_minutes', '2100', 'DELIVERY_DEADLINE'),
    ('dispatch_cutoff_at', '09:30:00', 'DISPATCH_CUTOFF'),
])
def test_evidenced_transit_and_dispatch_deadlines(field, value, code):
    data = payload()
    if field == 'dispatch_cutoff_at':
        data['production']['plans'][0][field] = dt(value)
    else:
        data['production']['processes'][0][field] = value
    assert code in codes(check(data))
    assert check(data).status == 'INFEASIBLE'


@pytest.mark.parametrize('start,end,conflict', [
    ('08:30:00', '09:00:00', False),
    ('10:40:00', '11:00:00', False),
    ('09:30:00', '10:00:00', True),
])
def test_job_overlap_and_half_open_edges(start, end, conflict):
    data = payload()
    data['production']['jobs'] = ({
        'job_id': 'external-job', 'tenant_id': data['operational']['tenant_id'],
        'resource_ids': ('kitchen-line-1',), 'start_at': dt(start), 'end_at': dt(end),
        'source_refs': ('production-jobs',),
    },)
    result = check(data)
    assert ('JOB_CONFLICT' in codes(result)) == conflict
    assert result.status == ('INFEASIBLE' if conflict else 'FEASIBLE')


def test_overlapping_commitments_share_resource_and_cannot_double_book():
    data = payload()
    target = data['operational']['confirmed_commitments'][0]
    other = {**target, 'commitment_id': 'other', 'lines': ({**target['lines'][0], 'line_id': 'other-line'},)}
    data['operational']['confirmed_commitments'] = (target, other)
    data['production']['plans'] = (*data['production']['plans'], {
        **data['production']['plans'][0], 'commitment_id': 'other', 'line_id': 'other-line',
    })
    result = check(data)
    assert result.status == 'INFEASIBLE'
    assert 'COMMITMENT_RESOURCE_CONFLICT' in codes(result)


@pytest.mark.parametrize('end,expected', [('10:40:00', 'FEASIBLE'), ('10:39:59', 'INFEASIBLE')])
def test_calendar_end_boundary(end, expected):
    data = payload()
    window = data['operational']['capacity_calendars'][0]['windows'][0]
    window.update(start_at=dt('09:00:00'), end_at=dt(end), available_minutes='99' if expected == 'INFEASIBLE' else '100')
    # Incomplete daily minutes cannot locate actual breaks; exact window required.
    if expected == 'INFEASIBLE':
        window['end_at'] = dt('10:39:00')
    assert check(data).status == expected


def test_break_between_working_windows_cannot_be_spent_as_continuous_time():
    data = payload()
    window = data['operational']['capacity_calendars'][0]['windows'][0]
    data['operational']['capacity_calendars'][0]['windows'] = (
        {**window, 'start_at': dt('09:00:00'), 'end_at': dt('10:00:00'), 'available_minutes': '60'},
        {**window, 'start_at': dt('10:30:00'), 'end_at': dt('17:30:00'), 'available_minutes': '420'},
    )
    assert check(data).status == 'INFEASIBLE'


@pytest.mark.parametrize('mode', ['rate', 'lead', 'jobs', 'horizon', 'calendar_minutes', 'plan', 'production', 'stale', 'missing_evidence', 'nested_bom'])
def test_missing_or_unsupported_inputs_are_unknown(mode):
    data = payload()
    production = data['production']
    if mode == 'rate':
        production['processes'][0]['minutes_per_unit'] = None
    elif mode == 'lead':
        production['processes'][0]['delivery_lead_minutes'] = None
    elif mode == 'jobs':
        production['jobs'] = None
    elif mode == 'horizon':
        production['jobs_covered_through'] = dt('10:00:00')
    elif mode == 'calendar_minutes':
        data['operational']['capacity_calendars'][0]['windows'][0]['available_minutes'] = '400'
    elif mode == 'plan':
        production['plans'] = ()
    elif mode == 'production':
        data['production'] = None
    elif mode == 'stale':
        production['sources'][0]['valid_through'] = data['as_of'] - timedelta(seconds=1)
        production['sources'][0]['observed_at'] = data['as_of'] - timedelta(days=1)
    elif mode == 'missing_evidence':
        production['sources'] = production['sources'][1:]
    else:
        data['operational']['sku_catalog'][1]['supply_type'] = 'MANUFACTURED'
    result = check(data)
    assert result.status == 'UNKNOWN'
    assert result.constraints


def test_multiple_resources_are_occupied_simultaneously():
    data = payload()
    production = data['production']
    production['resources'] = (*production['resources'], {**production['resources'][0], 'resource_id': 'operator'})
    production['processes'][0]['resource_ids'] = ('kitchen-line-1', 'operator')
    data['operational']['capacity_calendars'] = (*data['operational']['capacity_calendars'], {
        **data['operational']['capacity_calendars'][0], 'calendar_id': 'operator-calendar', 'resource_id': 'operator',
    })
    production['jobs'] = ({'job_id': 'operator-job', 'tenant_id': data['operational']['tenant_id'],
        'resource_ids': ('operator',), 'start_at': dt('10:00:00'), 'end_at': dt('11:00:00'), 'source_refs': ('production-jobs',)},)
    assert any(c.code == 'JOB_CONFLICT' and c.resource_id == 'operator' for c in check(data).constraints)


def test_soft_finish_preference_does_not_change_hard_feasibility():
    data = payload()
    data['production']['plans'][0]['preferred_finish_at'] = dt('10:00:00')
    result = check(data)
    assert result.status == 'FEASIBLE'
    assert any(c.code == 'PREFERRED_FINISH_MISSED' and c.severity == 'SOFT' for c in result.constraints)


def test_available_minutes_stop_at_dispatch_cutoff_and_existing_job():
    data = payload()
    data['production']['plans'][0]['dispatch_cutoff_at'] = dt('10:45:00')
    assert check(data).operations[0].available_minutes == 105
    data['production']['jobs'] = ({'job_id': 'next-job', 'tenant_id': data['operational']['tenant_id'],
        'resource_ids': ('kitchen-line-1',), 'start_at': dt('10:40:00'), 'end_at': dt('17:00:00'),
        'source_refs': ('production-jobs',)},)
    assert check(data).operations[0].available_minutes == 100


def test_missing_competitor_plan_cannot_claim_known_free_minutes():
    data = payload()
    target = data['operational']['confirmed_commitments'][0]
    data['operational']['confirmed_commitments'] = (target, {
        **target, 'commitment_id': 'other', 'lines': ({**target['lines'][0], 'line_id': 'other-line'},),
    })
    result = check(data)
    assert result.status == 'UNKNOWN'
    assert result.operations[0].available_minutes is None


def test_decimal_context_and_input_order_do_not_change_result():
    data = payload()
    expected = check(data)
    with localcontext() as context:
        context.prec = 1
        assert check(data) == expected
    data['production']['sources'] = tuple(reversed(data['production']['sources']))
    assert check(data) == expected


def test_exact_calendar_validation_ignores_ambient_decimal_precision():
    data = payload()
    window = data['operational']['capacity_calendars'][0]['windows'][0]
    window.update(start_at=dt('09:00:00'), end_at=dt('11:09:00'), available_minutes='129')
    expected = check(data)
    with localcontext() as context:
        context.prec = 1
        assert check(data) == expected


@pytest.mark.parametrize('duration', ['1e999999', '0.00000000000001'])
def test_unsupported_duration_limits_return_unknown_without_guessing(duration):
    data = payload()
    data['production']['processes'][0]['minutes_per_unit'] = duration
    result = check(data)
    assert result.status == 'UNKNOWN'
    assert 'UNSUPPORTED_PRODUCTION_DURATION' in codes(result)


@pytest.mark.parametrize('mode', ['tenant', 'duplicate', 'negative', 'float', 'naive', 'zero_job'])
def test_invalid_production_data_is_refused(mode):
    data = payload()
    production = data['production']
    if mode == 'tenant':
        production['resources'][0]['tenant_id'] = 'other'
    elif mode == 'duplicate':
        production['processes'] = (*production['processes'], production['processes'][0])
    elif mode == 'negative':
        production['processes'][0]['setup_minutes'] = '-1'
    elif mode == 'float':
        production['processes'][0]['minutes_per_unit'] = 0.1
    elif mode == 'naive':
        production['plans'][0]['start_at'] = datetime(2026, 10, 23, 9)
    else:
        production['jobs'] = ({'job_id': 'invalid', 'tenant_id': data['operational']['tenant_id'],
            'resource_ids': ('kitchen-line-1',), 'start_at': dt('10:00:00'), 'end_at': dt('10:00:00'), 'source_refs': ('production-jobs',)},)
    with pytest.raises(ValueError):
        check(data)
