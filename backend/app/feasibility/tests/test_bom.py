from decimal import Decimal, localcontext

import pytest
from pydantic import ValidationError

from backend.app.feasibility.fixtures import build_supplier_delay_scenario
from backend.app.feasibility.models import OperationalSnapshot


def payload():
    return build_supplier_delay_scenario().before.model_dump(exclude_computed_fields=True)


def explode(data):
    from backend.app.feasibility.bom import explode_bom
    snapshot = OperationalSnapshot.model_validate(data)
    return explode_bom(snapshot, tenant_id=snapshot.tenant_id)


def test_recursive_bom_propagates_units_waste_and_source_paths():
    data = payload()
    data['sku_catalog'] = (*data['sku_catalog'], {
        **data['sku_catalog'][0], 'sku_id': 'DOUGH', 'base_unit': 'kg',
    })
    data['bom_components'][0].update(component_sku_id='DOUGH', quantity='250', unit='g', waste_multiplier='1.1')
    data['bom_components'] = (*data['bom_components'], {
        **data['bom_components'][1], 'component_id': 'dough-patty',
        'parent_sku_id': 'DOUGH', 'component_sku_id': 'PATTY', 'quantity': '2',
    })
    data['unit_conversions'] = ({
        'conversion_id': 'dough-g-kg', 'tenant_id': data['tenant_id'],
        'sku_id': 'DOUGH', 'from_unit': 'g', 'to_unit': 'kg',
        'factor': '0.001', 'source_refs': ('source-bom-001',),
    },)
    result = explode(data)
    assert result.status == 'COMPLETE'
    patty = next(r for r in result.requirements if r.commitment_id == 'com-001' and r.sku_id == 'PATTY')
    assert patty.quantity == Decimal('55')
    assert patty.unit == 'pcs'
    assert ('BURGER', 'DOUGH', 'PATTY') in patty.paths
    assert 'bom-burger-v1' in patty.evidence_refs
    assert any('1.1' in a for a in result.assumptions)
    assert any('dough-g-kg' in a for a in result.assumptions)


def test_branching_bom_aggregates_shared_leaf_without_losing_paths():
    data = payload()
    data['bom_components'][1].update(component_sku_id='PATTY', quantity='0.5')
    result = explode(data)
    patty = next(r for r in result.requirements if r.commitment_id == 'com-001' and r.sku_id == 'PATTY')
    assert patty.quantity == Decimal('150')
    assert len(patty.component_paths) == 2


def test_f2_07_bom_cycle_and_missing_bom_are_unknown():
    data = payload()
    data['bom_components'][0]['component_sku_id'] = 'BURGER'
    result = explode(data)
    assert result.status == 'UNKNOWN'
    assert not result.requirements
    assert 'BOM_CYCLE' in {i.code for i in result.issues}
    data = payload()
    data['bom_components'] = ()
    assert explode(data).status == 'UNKNOWN'


def test_units_require_explicit_sku_specific_source_backed_conversion():
    data = payload()
    data['bom_components'][0]['unit'] = 'box'
    with pytest.raises(ValidationError, match='unit mismatch'):
        OperationalSnapshot.model_validate(data)
    mapping = dict(conversion_id='patty-box', tenant_id=data['tenant_id'], sku_id='PATTY',
                   from_unit='box', to_unit='pcs', factor='10', source_refs=('source-bom-001',))
    data['unit_conversions'] = (mapping,)
    assert next(r for r in explode(data).requirements if r.sku_id == 'PATTY').quantity == Decimal('1000')
    data['unit_conversions'] = (mapping, {**mapping, 'conversion_id': 'conflict', 'factor': '12'})
    with pytest.raises(ValidationError, match='conversion'):
        OperationalSnapshot.model_validate(data)
    data['unit_conversions'] = ({**mapping, 'source_refs': ()},)
    with pytest.raises(ValidationError, match='source'):
        OperationalSnapshot.model_validate(data)


def test_bom_arithmetic_does_not_depend_on_decimal_context():
    data = payload()
    data['bom_components'][0]['quantity'] = '0.123456789123456789'
    with localcontext() as context:
        context.prec = 4
        result = explode(data)
    assert next(r for r in result.requirements if r.sku_id == 'PATTY').quantity == Decimal('12.345678912345678900')


def test_bom_cross_tenant_request_is_refused():
    from backend.app.feasibility.bom import explode_bom
    with pytest.raises(ValueError, match='tenant'):
        explode_bom(build_supplier_delay_scenario().before, tenant_id='other')


@pytest.mark.parametrize('field,value', [('factor', 1.2), ('factor', '0'), ('factor', 'NaN')])
def test_conversion_rejects_inexact_or_invalid_factor(field, value):
    data = payload()
    data['unit_conversions'] = ({'conversion_id': 'x', 'tenant_id': data['tenant_id'], 'sku_id': 'PATTY',
                                'from_unit': 'box', 'to_unit': 'pcs', 'source_refs': ('source-bom-001',),
                                field: value},)
    with pytest.raises(ValidationError):
        OperationalSnapshot.model_validate(data)


def test_bom_revalidates_copied_snapshot_before_calculation():
    from backend.app.feasibility.bom import explode_bom
    snapshot = build_supplier_delay_scenario().before
    foreign = snapshot.sku_catalog[0].model_copy(update={'tenant_id': 'other'})
    bypassed = snapshot.model_copy(update={'sku_catalog': (foreign, *snapshot.sku_catalog[1:])})
    with pytest.raises(ValidationError, match='tenant'):
        explode_bom(bypassed, tenant_id=snapshot.tenant_id)


@pytest.mark.parametrize('value', [0.9, '0.9', 'NaN'])
def test_waste_multiplier_rejects_implicit_gain_and_inexact_input(value):
    data = payload()
    data['bom_components'][0]['waste_multiplier'] = value
    with pytest.raises(ValidationError):
        OperationalSnapshot.model_validate(data)
