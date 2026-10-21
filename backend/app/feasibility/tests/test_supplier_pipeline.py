from datetime import timedelta

import pytest

from app.feasibility import supplier_pipeline as pipeline
from app.feasibility.pipeline_fixtures import build_pipeline_example


def test_complete_buffered_pipeline_replays_without_mutation():
    inputs = build_pipeline_example()
    original = inputs.model_dump_json()
    first = pipeline.recalculate_supplier_delay(inputs, tenant_id=inputs.request.change.tenant_id)
    again = pipeline.recalculate_supplier_delay(inputs, tenant_id=inputs.request.change.tenant_id)
    assert first == again
    assert first.confirmed_impacted_commitment_ids == ('com-001',)
    assert first.verified_unaffected_commitment_ids == ('com-002',)
    assert first.impacts[0].after_assessment.status == 'INFEASIBLE'
    assert inputs.model_dump_json() == original
    assert len({i.event.event_id for i in first.event_intents}) == len(first.event_intents)


def test_complete_two_impacted_pipeline():
    inputs = build_pipeline_example(two_affected=True)
    result = pipeline.recalculate_supplier_delay(inputs, tenant_id=inputs.request.change.tenant_id)
    assert result.confirmed_impacted_commitment_ids == ('com-001', 'com-002')
    assert all(row.before_assessment.status == 'FEASIBLE' for row in result.impacts)
    assert {i.event.commitment_id for i in result.event_intents
            if i.event.event_type == 'commitment.at_risk'} == {'com-001', 'com-002'}


@pytest.mark.parametrize('mode', ['material_only', 'missing_supplier', 'stale_inventory', 'stale_production'])
def test_incomplete_inputs_remain_unknown(mode):
    inputs = build_pipeline_example(mode=mode)
    result = pipeline.recalculate_supplier_delay(inputs, tenant_id=inputs.request.change.tenant_id)
    assert result.confirmed_impacted_commitment_ids == ()
    assert result.unknown_commitment_ids == ('com-001', 'com-002')
    assert not any(i.event.event_type == 'commitment.at_risk' for i in result.event_intents)


@pytest.mark.parametrize('field,value', [
    ('previous_eta', '2026-10-23T07:00:00+08:00'),
    ('updated_eta', '2026-10-23T12:00:00+08:00'),
    ('before_snapshot_id', 'wrong-before'),
    ('after_snapshot_id', 'wrong-after'),
])
def test_declared_eta_and_snapshot_bindings_reject_mismatch(field, value):
    inputs = build_pipeline_example()
    data = inputs.model_dump(exclude_computed_fields=True)
    data[field] = value
    with pytest.raises(ValueError):
        pipeline.recalculate_supplier_delay(pipeline.SupplierDelayInputs.model_validate(data),
                                           tenant_id=inputs.request.change.tenant_id)


def test_wrong_tenant_and_forged_typed_evidence_reject():
    inputs = build_pipeline_example()
    with pytest.raises(ValueError, match='tenant'):
        pipeline.recalculate_supplier_delay(inputs, tenant_id='other-tenant')
    data = inputs.model_dump(exclude_computed_fields=True)
    data['request']['source_evidence']['supplier_id'] = 'forged-supplier'
    with pytest.raises(ValueError, match='evidence'):
        pipeline.recalculate_supplier_delay(pipeline.SupplierDelayInputs.model_validate(data),
                                           tenant_id=inputs.request.change.tenant_id)


def test_stale_versions_reject_and_separate_causes_have_separate_intents():
    inputs = build_pipeline_example()
    data = inputs.model_dump(exclude_computed_fields=True)
    data['request']['change']['before_snapshot_version'] = 2
    with pytest.raises(ValueError):
        pipeline.recalculate_supplier_delay(pipeline.SupplierDelayInputs.model_validate(data),
                                           tenant_id=inputs.request.change.tenant_id)
    data = inputs.model_dump(exclude_computed_fields=True)
    data['request']['change']['event_id'] = 'distinct-cause'
    second = pipeline.recalculate_supplier_delay(pipeline.SupplierDelayInputs.model_validate(data),
                                                tenant_id=inputs.request.change.tenant_id)
    first = pipeline.recalculate_supplier_delay(inputs, tenant_id=inputs.request.change.tenant_id)
    assert {i.event.event_id for i in first.event_intents}.isdisjoint(
        i.event.event_id for i in second.event_intents)


def test_unrelated_stock_change_does_not_receive_supplier_causal_attribution():
    inputs = build_pipeline_example(mode='confounded')
    result = pipeline.recalculate_supplier_delay(inputs, tenant_id=inputs.request.change.tenant_id)
    assert result.confirmed_impacted_commitment_ids == ()
    assert 'com-001' in result.unknown_commitment_ids


def test_unchanged_preexisting_shortage_has_no_new_alert():
    inputs = build_pipeline_example(mode='preexisting')
    result = pipeline.recalculate_supplier_delay(inputs, tenant_id=inputs.request.change.tenant_id)
    assert 'com-001' in result.pre_existing_unchanged_commitment_ids
    assert not any(i.event.event_type == 'commitment.at_risk' for i in result.event_intents)
