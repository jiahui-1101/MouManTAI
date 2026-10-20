from datetime import datetime, timedelta
from decimal import Decimal, localcontext

import pytest

from app.feasibility.fixtures import build_supplier_delay_scenario, build_two_affected_scenario
from app.feasibility.models import OperationalSnapshot


def stock_payload(on_hand='70'):
    data = build_supplier_delay_scenario().before.model_dump(exclude_computed_fields=True)
    data['confirmed_commitments'] = data['confirmed_commitments'][:1]
    data['inventory_lots'][0]['quantity'] = on_hand
    data['reservations'] = ()
    data['incoming_deliveries'] = ()
    for source in data['sources']:
        source['supplier_delivery_evidence'] = ()
    return data


def calculate(data, **kwargs):
    from app.feasibility.inventory import calculate_atp
    snapshot = OperationalSnapshot.model_validate(data)
    return calculate_atp(snapshot, tenant_id=snapshot.tenant_id, **kwargs)


def patty(result, commitment='com-001'):
    return next(r for r in result.materials if r.commitment_id == commitment and r.sku_id == 'PATTY')


def test_f2_01_required_100_usable_70_shortage_30_with_evidence():
    result = calculate(stock_payload())
    row = patty(result)
    assert result.status == 'SHORTAGE'
    assert (row.required, row.usable, row.shortage, row.unit) == (Decimal('100'), Decimal('70'), Decimal('30'), 'pcs')
    assert row.needed_by == datetime.fromisoformat('2026-10-23T09:00:00+08:00')
    assert 'stocktake-patty-v1' in row.evidence_refs
    assert row.code == 'MATERIAL_SHORTAGE'


def test_f2_02_reservation_is_credited_only_to_owner_and_subtracted_once():
    data = build_supplier_delay_scenario().before.model_dump(exclude_computed_fields=True)
    data['inventory_lots'][0]['quantity'] = '100'
    data['reservations'][0]['quantity'] = '60'
    data['incoming_deliveries'] = ()
    for s in data['sources']:
        s['supplier_delivery_evidence'] = ()
    result = calculate(data)
    assert patty(result).shortage == Decimal('60')
    assert patty(result, 'com-002').reserved == Decimal('20')
    assert patty(result, 'com-002').shortage == 0
    assert sum(a.quantity for r in result.materials if r.sku_id == 'PATTY' for a in r.allocations) == 60


def test_f2_03_and_f2_04_confirmed_receipt_timing_and_no_unconfirmed_supply():
    before = build_supplier_delay_scenario().before.model_dump(exclude_computed_fields=True)
    after = build_supplier_delay_scenario().after.model_dump(exclude_computed_fields=True)
    first, second = calculate(before), calculate(after)
    assert patty(first).shortage == 0
    assert patty(first).confirmed_incoming == 40
    assert patty(second).shortage == 40
    assert patty(second).confirmed_incoming == 0
    assert 'supplier-eta-change-delivery-patty-001-v2' in patty(second).evidence_refs
    assert all(a.supply_id != 'delivery-unconfirmed-001' for r in first.materials for a in r.allocations)


@pytest.mark.parametrize('offset,shortage', [(-1, 0), (0, 0), (1, 40)])
def test_eta_cutoff_equality_is_inclusive(offset, shortage):
    data = build_two_affected_scenario().before.model_dump(exclude_computed_fields=True)
    eta = data['logistics_cutoff_at'] + timedelta(microseconds=offset)
    data['incoming_deliveries'][0]['expected_at'] = eta
    result = calculate(data)
    assert patty(result).shortage == shortage + (30 if offset == 1 else 0)


@pytest.mark.parametrize('offset,shortage', [(0, 0), (1, 40)])
def test_eta_material_use_equality_is_inclusive(offset, shortage):
    data = build_supplier_delay_scenario().before.model_dump(exclude_computed_fields=True)
    data['incoming_deliveries'][0]['expected_at'] = data['confirmed_commitments'][0]['lines'][0]['material_use_at'] + timedelta(microseconds=offset)
    assert patty(calculate(data)).shortage == shortage


def test_expiry_at_material_use_excludes_lot_and_owned_reservation():
    data = build_supplier_delay_scenario().before.model_dump(exclude_computed_fields=True)
    data['inventory_lots'][0]['expires_at'] = data['confirmed_commitments'][1]['lines'][0]['material_use_at']
    result = calculate(data)
    assert patty(result).shortage == 0
    assert patty(result, 'com-002').shortage == 20
    assert patty(result, 'com-002').reserved == 0


def test_already_expired_lot_is_not_usable():
    data = stock_payload()
    data['inventory_lots'][0]['expires_at'] = data['captured_at']
    assert patty(calculate(data)).shortage == 100


def test_competing_orders_share_receipts_and_stock_once_with_stable_order():
    data = build_two_affected_scenario().after.model_dump(exclude_computed_fields=True)
    result = calculate(data)
    assert (patty(result).shortage, patty(result, 'com-002').shortage) == (70, 40)
    data['confirmed_commitments'] = tuple(reversed(data['confirmed_commitments']))
    data['inventory_lots'] = tuple(reversed(data['inventory_lots']))
    assert calculate(data) == result
    before = calculate(build_two_affected_scenario().before.model_dump(exclude_computed_fields=True))
    assert sum(r.confirmed_incoming for r in before.materials if r.sku_id == 'PATTY') == 110


def test_owner_reservation_cannot_be_reused_on_multiple_lines():
    data = stock_payload('60')
    line = data['confirmed_commitments'][0]['lines'][0]
    line['quantity'] = '40'
    data['confirmed_commitments'][0]['lines'] = (line, {**line, 'line_id': 'second'})
    original = build_supplier_delay_scenario().before.reservations[0].model_dump()
    data['reservations'] = ({**original, 'commitment_id': 'com-001', 'quantity': '60'},)
    result = calculate(data)
    rows = [r for r in result.materials if r.sku_id == 'PATTY']
    assert sum(r.reserved for r in rows) == 60
    assert sum(r.shortage for r in rows) == 20


@pytest.mark.parametrize('mode', ['missing', 'stale', 'as_of_stale', 'missing_bom', 'cycle', 'past_demand', 'overdue_receipt'])
def test_f2_07_insufficient_inputs_are_unknown(mode):
    data = stock_payload()
    kwargs = {}
    if mode == 'missing':
        data['inventory_lots'] = ()
        data['sources'] = tuple(s for s in data['sources'] if s['kind'] != 'inventory')
    elif mode in ('stale', 'as_of_stale'):
        source = next(s for s in data['sources'] if s['kind'] == 'inventory')
        if mode == 'stale':
            source['observed_at'] -= timedelta(days=2)
            source['valid_through'] = data['captured_at'] - timedelta(seconds=1)
        else:
            kwargs['as_of'] = source['valid_through'] + timedelta(seconds=1)
    elif mode == 'missing_bom':
        data['bom_components'] = ()
    elif mode == 'cycle':
        data['bom_components'][0]['component_sku_id'] = 'BURGER'
    elif mode == 'past_demand':
        data['confirmed_commitments'][0]['lines'][0]['material_use_at'] = data['captured_at'] - timedelta(seconds=1)
    else:
        data = build_supplier_delay_scenario().before.model_dump(exclude_computed_fields=True)
        data['incoming_deliveries'][0]['expected_at'] = data['captured_at']
    result = calculate(data, **kwargs)
    assert result.status == 'UNKNOWN'
    assert result.issues
    assert not result.materials


def test_stale_supplier_confirmation_source_is_not_safe_supply():
    data = build_supplier_delay_scenario().before.model_dump(exclude_computed_fields=True)
    source = next(s for s in data['sources'] if s['source_id'] == 'source-deliveries-001')
    source['valid_through'] = data['captured_at'] - timedelta(seconds=1)
    source['observed_at'] = source['valid_through']
    result = calculate(data)
    assert result.status == 'UNKNOWN'


def test_warehouse_mismatch_cannot_supply_demand():
    data = stock_payload('100')
    data['confirmed_commitments'][0]['lines'][0]['warehouse_id'] = 'another-warehouse'
    assert patty(calculate(data)).shortage == 100


def test_decimal_precision_and_input_immutability():
    from app.feasibility.inventory import calculate_atp
    data = stock_payload('0.2')
    data['confirmed_commitments'][0]['lines'][0]['quantity'] = '0.3'
    snapshot = OperationalSnapshot.model_validate(data)
    original = snapshot.model_dump_json()
    with localcontext() as context:
        context.prec = 1
        result = calculate_atp(snapshot, tenant_id=snapshot.tenant_id)
    assert patty(result).shortage == Decimal('0.1')
    assert result.snapshot_id == snapshot.snapshot_id
    assert result.snapshot_version == snapshot.snapshot_version
    assert result.tenant_id == snapshot.tenant_id
    assert snapshot.model_dump_json() == original
    assert calculate_atp(snapshot, tenant_id=snapshot.tenant_id) == result


def test_atp_rejects_wrong_tenant_and_naive_as_of():
    from app.feasibility.inventory import calculate_atp
    snapshot = build_supplier_delay_scenario().before
    with pytest.raises(ValueError, match='tenant'):
        calculate_atp(snapshot, tenant_id='other')
    with pytest.raises(ValueError, match='offset-aware'):
        calculate_atp(snapshot, tenant_id=snapshot.tenant_id, as_of=datetime(2026, 10, 23))


def test_receipt_overdue_at_calculation_time_requires_reconciliation():
    data = build_supplier_delay_scenario().before.model_dump(exclude_computed_fields=True)
    assert calculate(data, as_of=data['incoming_deliveries'][0]['expected_at']).status == 'UNKNOWN'


def test_inventory_reservations_receipts_and_demand_convert_to_base_units():
    data = build_supplier_delay_scenario().before.model_dump(exclude_computed_fields=True)
    data['unit_conversions'] = ({
        'conversion_id': 'patty-box-pcs', 'tenant_id': data['tenant_id'], 'sku_id': 'PATTY',
        'from_unit': 'box', 'to_unit': 'pcs', 'factor': '10', 'source_refs': ('source-bom-001',),
    }, {
        'conversion_id': 'burger-box-pcs', 'tenant_id': data['tenant_id'], 'sku_id': 'BURGER',
        'from_unit': 'box', 'to_unit': 'pcs', 'factor': '10', 'source_refs': ('source-bom-001',),
    })
    data['inventory_lots'][0].update(quantity='8', unit='box')
    data['reservations'][0].update(quantity='2', unit='box')
    data['incoming_deliveries'][0].update(quantity='4', unit='box')
    data['confirmed_commitments'][0]['lines'][0].update(quantity='10', unit='box')
    result = calculate(data)
    assert result.status == 'COVERED'
    assert (patty(result).required, patty(result).usable, patty(result).confirmed_incoming) == (100, 60, 40)
    assert patty(result, 'com-002').reserved == 20
    data['reservations'][0]['quantity'] = '9'
    with pytest.raises(ValueError, match='reservations exceed'):
        OperationalSnapshot.model_validate(data)


@pytest.mark.parametrize('status', ['RELEASED', 'CONSUMED'])
def test_inactive_reservation_does_not_hold_stock(status):
    data = build_supplier_delay_scenario().after.model_dump(exclude_computed_fields=True)
    data['reservations'][0]['status'] = status
    assert patty(calculate(data)).shortage == 20


def test_receipt_with_wrong_or_unknown_warehouse_is_not_eligible_for_scoped_demand():
    data = build_supplier_delay_scenario().before.model_dump(exclude_computed_fields=True)
    data['confirmed_commitments'][0]['lines'][0]['warehouse_id'] = 'warehouse-kitchen'
    assert patty(calculate(data)).shortage == 40
    data['incoming_deliveries'][0]['warehouse_id'] = 'warehouse-kitchen'
    assert patty(calculate(data)).shortage == 0


def test_material_results_are_frozen_and_preserve_decimal_string_serialization():
    result = calculate(stock_payload())
    with pytest.raises(ValueError):
        result.status = 'COVERED'
    assert result.model_dump(mode='json')['materials'][0]['required'] == '100'


def test_inventory_conversion_overflow_returns_unknown_instead_of_crashing():
    data = stock_payload('10')
    data['unit_conversions'] = ({
        'conversion_id': 'too-large', 'tenant_id': data['tenant_id'], 'sku_id': 'PATTY',
        'from_unit': 'box', 'to_unit': 'pcs', 'factor': '1e999999', 'source_refs': ('source-bom-001',),
    },)
    data['inventory_lots'][0]['unit'] = 'box'
    result = calculate(data)
    assert result.status == 'UNKNOWN'
    assert result.issues[0].code == 'CALCULATION_LIMIT'


def test_reservation_normalization_limit_is_a_validation_error():
    from pydantic import ValidationError
    data = build_supplier_delay_scenario().before.model_dump(exclude_computed_fields=True)
    data['unit_conversions'] = ({
        'conversion_id': 'too-large', 'tenant_id': data['tenant_id'], 'sku_id': 'PATTY',
        'from_unit': 'box', 'to_unit': 'pcs', 'factor': '1e999999', 'source_refs': ('source-bom-001',),
    },)
    data['reservations'][0].update(quantity='10', unit='box')
    with pytest.raises(ValidationError, match='numeric normalization'):
        OperationalSnapshot.model_validate(data)


def test_decimal_exponent_and_trap_settings_do_not_change_material_outcome():
    from decimal import Overflow
    data = stock_payload('10')
    data['unit_conversions'] = ({
        'conversion_id': 'large', 'tenant_id': data['tenant_id'], 'sku_id': 'PATTY',
        'from_unit': 'box', 'to_unit': 'pcs', 'factor': '10000', 'source_refs': ('source-bom-001',),
    },)
    data['inventory_lots'][0]['unit'] = 'box'
    expected = calculate(data)
    with localcontext() as context:
        context.Emax = 3
        context.traps[Overflow] = False
        assert calculate(data) == expected
