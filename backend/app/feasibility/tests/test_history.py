import pytest

from app.feasibility.history import AssessmentRecord, SyntheticHistoryRepository, to_core_assessment
from app.feasibility.impact import ImpactClassification
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
    assert assessment.assessment_id == result.assessment_id
    assert assessment.status == result.status
    assert assessment.solver_status == result.solver_status
    assert assessment.constraints == list(result.constraints)
    assert assessment.evidence_refs == list(result.evidence_refs)
    assert assessment.assumptions == list(result.assumptions)
    assert assessment.assessed_at == result.assessed_at
    impact = recalculate_supplier_delay(inputs, tenant_id=result.tenant_id)
    assert impact.confirmed_impacted_commitment_ids == ('com-001',)
    assert to_core_assessment(result, impact=impact).affected_commitment_ids == []
    bad = impact.model_copy(update={'after_snapshot_version': 99})
    with pytest.raises(ValueError, match='binding'):
        to_core_assessment(result, impact=bad)


def test_mapping_preserves_other_confirmed_impacts_in_original_order():
    inputs = build_pipeline_example(two_affected=True)
    result = evaluate(inputs.after, None, inputs.after_commitments[0])
    impact = recalculate_supplier_delay(inputs, tenant_id=result.tenant_id)
    assert impact.confirmed_impacted_commitment_ids == ('com-001', 'com-002')

    # This mapping-only synthetic extension exercises ordered filtering of
    # multiple confirmed downstream IDs; it is not calculation or source evidence.
    source = next(row for row in impact.impacts if row.commitment_id == 'com-002')
    extra_rows = []
    for commitment_id in ('com-003', 'com-004'):
        row_data = source.model_dump(exclude_computed_fields=True)
        row_data['commitment_id'] = commitment_id
        row_data['event_intents'] = ()
        for field in ('before_assessment', 'after_assessment'):
            if row_data[field] is not None:
                row_data[field]['commitment_id'] = commitment_id
                row_data[field]['assessment_id'] += '-' + commitment_id
        extra_rows.append(type(source).model_validate(row_data))
    impact = impact.model_copy(update={
        'candidate_commitment_ids': (*impact.candidate_commitment_ids, 'com-003', 'com-004'),
        'impacts': (*impact.impacts, *extra_rows),
    })
    result_before = result.model_dump_json(exclude_computed_fields=True)
    impact_before = impact.model_dump_json(exclude_computed_fields=True)

    assessment = to_core_assessment(result, impact=impact)

    assert assessment.affected_commitment_ids == ['com-002', 'com-003', 'com-004']
    assert result.model_dump_json(exclude_computed_fields=True) == result_before
    assert impact.model_dump_json(exclude_computed_fields=True) == impact_before


@pytest.mark.parametrize('mode, excluded_classification', [
    ('complete', ImpactClassification.VERIFIED_UNAFFECTED),
    ('missing_supplier', ImpactClassification.UNKNOWN),
    ('preexisting', ImpactClassification.PRE_EXISTING_UNCHANGED),
])
def test_mapping_excludes_unconfirmed_and_candidate_commitments(mode, excluded_classification):
    inputs = build_pipeline_example(mode=mode)
    result = evaluate(inputs.after, None, inputs.after_commitments[0])
    impact = recalculate_supplier_delay(inputs, tenant_id=result.tenant_id)
    excluded_ids = {row.commitment_id for row in impact.impacts
                    if row.classification is excluded_classification}

    assessment = to_core_assessment(result, impact=impact)

    assert excluded_ids
    assert not (excluded_ids & set(assessment.affected_commitment_ids))
    unconfirmed_candidate_ids = (set(impact.candidate_commitment_ids)
                                 - set(impact.confirmed_impacted_commitment_ids))
    assert not (unconfirmed_candidate_ids & set(assessment.affected_commitment_ids))


@pytest.mark.parametrize(('field', 'value'), [
    ('tenant_id', 'foreign-tenant'),
    ('after_snapshot_id', 'wrong-after-snapshot'),
    ('after_snapshot_version', 99),
])
def test_mapping_rejects_impact_identity_binding_mismatches(field, value):
    inputs = build_pipeline_example()
    result = evaluate(inputs.after, None, inputs.after_commitments[0])
    impact = recalculate_supplier_delay(inputs, tenant_id=result.tenant_id)
    invalid = impact.model_copy(update={field: value})

    with pytest.raises(ValueError, match='binding'):
        to_core_assessment(result, impact=invalid)


def test_mapping_rejects_non_exact_after_assessment_binding():
    inputs = build_pipeline_example(two_affected=True)
    result = evaluate(inputs.after, None, inputs.after_commitments[0])
    other_result = evaluate(inputs.after, None, inputs.after_commitments[1])
    impact = recalculate_supplier_delay(inputs, tenant_id=result.tenant_id)
    invalid_rows = tuple(row.model_copy(update={'after_assessment': other_result})
                         if row.commitment_id == result.commitment_id else row
                         for row in impact.impacts)
    invalid = impact.model_copy(update={'impacts': invalid_rows})

    with pytest.raises(ValueError, match='binding'):
        to_core_assessment(result, impact=invalid)


def test_mapping_rejects_result_without_matching_impact_commitment():
    inputs = build_pipeline_example()
    result = evaluate(inputs.after, None, inputs.after_commitments[0])
    impact = recalculate_supplier_delay(inputs, tenant_id=result.tenant_id)
    wrong_commitment = result.model_copy(update={'commitment_id': 'com-other'})

    with pytest.raises(ValueError, match='binding'):
        to_core_assessment(wrong_commitment, impact=impact)


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
    repo = SyntheticHistoryRepository()
    assert repo.append_assessment(saved)
    assert not repo.append_assessment(saved)
    assert repo.list_assessments(row.commitment.tenant_id, row.commitment.commitment_id) == (saved,)


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


@pytest.mark.parametrize('field,value', [
    ('status', 'FEASIBLE'),
    ('constraints', ()),
    ('solver_status', 'UNKNOWN'),
    ('evidence_refs', ('tampered-evidence',)),
    ('assumptions', ('tampered-assumption',)),
    ('materials.evidence_refs', ('tampered-material-evidence',)),
    ('capacity.evidence_refs', ('tampered-capacity-evidence',)),
])
def test_first_assessment_insert_rejects_tampering_with_unchanged_input_identity(field, value):
    repo = SyntheticHistoryRepository()
    genuine = record()
    data = genuine.model_dump(exclude_computed_fields=True)
    target = data['result']
    parts = field.split('.')
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = value
    tampered = AssessmentRecord.model_validate(data)
    assert tampered.result != genuine.result
    assert tampered.result.assessment_id == genuine.result.assessment_id
    assert tampered.snapshot == genuine.snapshot
    assert repo.list_assessments(genuine.result.tenant_id, genuine.result.commitment_id) == ()

    with pytest.raises(ValueError, match='result verification'):
        repo.append_assessment(tampered)

    assert repo.list_assessments(genuine.result.tenant_id, genuine.result.commitment_id) == ()
    assert repo.append_assessment(genuine)
    assert not repo.append_assessment(genuine)
    assert repo.list_assessments(genuine.result.tenant_id, genuine.result.commitment_id) == (genuine,)


@pytest.mark.parametrize('field', [
    'classification', 'event_intents', 'row_event_intents', 'event_payload', 'evidence', 'discovery_complete',
])
def test_first_impact_insert_rejects_tampering_with_unchanged_input_digest(field):
    repo = SyntheticHistoryRepository()
    inputs = build_pipeline_example()
    tenant = inputs.request.change.tenant_id
    genuine = recalculate_supplier_delay(inputs, tenant_id=tenant)
    data = genuine.model_dump(exclude_computed_fields=True)
    if field == 'classification':
        data['impacts'][0]['classification'] = 'VERIFIED_UNAFFECTED'
    elif field == 'event_intents':
        data['event_intents'] = ()
    elif field == 'row_event_intents':
        data['impacts'][0]['event_intents'] = ()
    elif field == 'event_payload':
        data['event_intents'][0]['event']['payload']['tampered'] = True
    elif field == 'evidence':
        data['impacts'][0]['evidence_refs'] = ('tampered-evidence',)
    else:
        data['discovery_complete'] = not genuine.discovery_complete
    tampered = type(genuine).model_validate(data)
    assert tampered != genuine
    assert tampered.impact_id == genuine.impact_id
    assert tampered.calculation_input_digest == genuine.calculation_input_digest
    assert repo.get_impact(tenant, genuine.impact_id) is None

    with pytest.raises(ValueError, match='result verification'):
        repo.append_impact(inputs, tampered)

    assert repo.get_impact(tenant, genuine.impact_id) is None
    assert repo.append_impact(inputs, genuine) == genuine.event_intents
    assert repo.append_impact(inputs, genuine) == ()
    assert repo.get_impact(tenant, genuine.impact_id) == genuine


@pytest.mark.parametrize('mode', ['material_only', 'stale_inventory', 'stale_production'])
def test_deterministic_verification_preserves_genuine_unknown_assessments_and_impacts(mode):
    inputs = build_pipeline_example(mode=mode)
    commitment = inputs.after_commitments[0]
    result = evaluate(inputs.after, None, commitment)
    assert result.status == 'UNKNOWN'
    row = AssessmentRecord(snapshot=inputs.after, commitment=commitment, result=result)
    repo = SyntheticHistoryRepository()
    assert repo.append_assessment(row)
    assert not repo.append_assessment(row)
    impact = recalculate_supplier_delay(inputs, tenant_id=commitment.tenant_id)
    assert 'com-001' in impact.unknown_commitment_ids
    assert repo.append_impact(inputs, impact) == impact.event_intents
    assert repo.append_impact(inputs, impact) == ()
