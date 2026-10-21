import pytest

from app.feasibility.history import AssessmentRecord, SyntheticHistoryRepository, to_core_assessment
from app.feasibility.pipeline_fixtures import build_pipeline_example
from app.feasibility.supplier_pipeline import recalculate_supplier_delay
from app.feasibility.service import evaluate
from app.feasibility.production import ProposedChanges


def record():
    inputs = build_pipeline_example()
    commitment = inputs.after_commitments[0]
    result = evaluate(inputs.after, None, commitment)
    return AssessmentRecord(snapshot=inputs.after, commitment=commitment, result=result)


def test_history_is_tenant_scoped_append_only_and_defensively_copied():
    row = record()
    repo = SyntheticHistoryRepository()
    assert repo.append_assessment(row)
    assert not repo.append_assessment(row)
    assert repo.list_assessments('foreign', row.commitment.commitment_id) == ()
    read = repo.list_assessments(row.commitment.tenant_id, row.commitment.commitment_id)[0]
    read.result.constraints[0].code = 'corrupted-output'
    assert repo.list_assessments(row.commitment.tenant_id, row.commitment.commitment_id)[0] == row
    changed = row.model_dump(exclude_computed_fields=True)
    changed['result']['status'] = 'FEASIBLE'
    with pytest.raises(ValueError, match='conflict'):
        repo.append_assessment(AssessmentRecord.model_validate(changed))


@pytest.mark.parametrize('field,value', [('tenant_id', 'foreign'), ('snapshot_version', 99),
                                         ('snapshot_id', 'wrong'), ('commitment_version', 99),
                                         ('commitment_id', 'wrong')])
def test_history_rejects_wrong_result_binding(field, value):
    data = record().model_dump(exclude_computed_fields=True)
    data['result'][field] = value
    with pytest.raises(ValueError, match='binding'):
        AssessmentRecord.model_validate(data)


def test_mapping_preserves_exact_result_and_actual_impact_set():
    inputs = build_pipeline_example()
    result = evaluate(inputs.after, None, inputs.after_commitments[0])
    assessment = to_core_assessment(result)
    assert assessment.affected_commitment_ids == []
    assert assessment.status == result.status
    assert assessment.solver_status == result.solver_status
    assert assessment.constraints == list(result.constraints)
    assert assessment.evidence_refs == list(result.evidence_refs)
    impact = recalculate_supplier_delay(inputs, tenant_id=result.tenant_id)
    assert to_core_assessment(result, impact=impact).affected_commitment_ids == ['com-001']
    bad = impact.model_copy(update={'after_snapshot_version': 99})
    with pytest.raises(ValueError, match='binding'):
        to_core_assessment(result, impact=bad)


def test_impact_replay_records_one_set_of_intents_and_rejects_changed_cause():
    inputs = build_pipeline_example()
    tenant = inputs.request.change.tenant_id
    result = recalculate_supplier_delay(inputs, tenant_id=tenant)
    repo = SyntheticHistoryRepository()
    first_intents = repo.append_impact(inputs, result)
    assert first_intents == result.event_intents
    assert repo.append_impact(inputs, result) == ()
    assert repo.get_impact('foreign', result.impact_id) is None
    assert repo.get_impact(tenant, result.impact_id) == result
    changed = inputs.model_dump(exclude_computed_fields=True)
    changed['request']['change']['correlation_id'] = 'changed-under-same-event'
    with pytest.raises(ValueError, match='conflict'):
        repo.append_impact(type(inputs).model_validate(changed), result)


def test_history_never_promotes_insertion_order_to_current_authority():
    row = record()
    assert row.currentness == 'HISTORICAL_UNVERIFIED'
    assert not hasattr(row, 'current_snapshot_version')


def test_hypothetical_history_requires_exact_proposal_for_reproduction():
    row = record()
    proposal = ProposedChanges(tenant_id=row.commitment.tenant_id,
                               commitment_id=row.commitment.commitment_id,
                               expected_commitment_version=row.commitment.commitment_version,
                               expected_snapshot_version=row.snapshot.operational.snapshot_version,
                               quantity='50', evidence_refs=('synthetic-what-if',))
    result = evaluate(row.snapshot, proposal, row.commitment)
    with pytest.raises(ValueError, match='binding'):
        AssessmentRecord(snapshot=row.snapshot, commitment=row.commitment, result=result)
    saved = AssessmentRecord(snapshot=row.snapshot, commitment=row.commitment, result=result,
                            proposed_changes=proposal)
    assert saved.proposed_changes == proposal


def test_impact_history_rejects_result_computed_from_other_snapshot_contents():
    inputs = build_pipeline_example()
    other = build_pipeline_example(mode='confounded')
    # Same event/snapshot identity metadata, different underlying stock contents.
    data = other.model_dump(exclude_computed_fields=True)
    data['request'] = inputs.request.model_dump()
    data['updated_eta'] = inputs.updated_eta
    for delivery in data['after']['operational']['incoming_deliveries']:
        if delivery['delivery_id'] == inputs.request.change.resource_keys[0].resource_id:
            delivery['expected_at'] = inputs.updated_eta
    other = type(inputs).model_validate(data)
    result = recalculate_supplier_delay(other, tenant_id=other.request.change.tenant_id)
    with pytest.raises(ValueError, match='binding'):
        SyntheticHistoryRepository().append_impact(inputs, result)


def test_missing_core_results_cannot_be_stored_against_other_complete_inputs():
    inputs = build_pipeline_example()
    unknown_inputs = inputs.model_copy(update={'before_commitments': (), 'after_commitments': ()})
    unknown_result = recalculate_supplier_delay(unknown_inputs, tenant_id=inputs.request.change.tenant_id)
    assert all(row.after_assessment is None for row in unknown_result.impacts)
    with pytest.raises(ValueError, match='binding'):
        SyntheticHistoryRepository().append_impact(inputs, unknown_result)
    # Legitimate missing-Core UNKNOWN remains recordable against its own inputs.
    assert SyntheticHistoryRepository().append_impact(unknown_inputs, unknown_result)
