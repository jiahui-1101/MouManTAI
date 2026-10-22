import asyncio
import json

from app.context.experiments.pipeline_audit import FIXTURES, evaluate, score


def test_dataset_has_disjoint_fixed_development_and_evaluation():
    fixtures = json.loads(FIXTURES.read_text(encoding='utf-8'))
    dev = {c['text'] for c in fixtures['cases'] if c['split'] == 'development'}
    evaluation = [c for c in fixtures['cases'] if c['split'] == 'evaluation']
    assert not dev & {c['text'] for c in evaluation}
    assert len(evaluation) == 16
    assert {lang: sum(c['language'] == lang for c in evaluation) for lang in ('en','zh','ms','mixed')} == dict.fromkeys(('en','zh','ms','mixed'),4)
    assert fixtures['message_timestamp'] == '2026-10-20T10:00:00+08:00'


def test_wrong_value_and_missing_field_count_as_errors():
    assert score([('quantity','99')], [('quantity','40'), ('sku','BURGER')]) == {'tp':0,'fp':1,'fn':2}


def test_offline_audit_never_claims_model_contribution():
    report = asyncio.run(evaluate('development'))
    assert report['samples'] == 10
    assert report['accepted_model_fields'] == 0
    assert report['rules'] == report['combined_accepted']
    assert not report['calls']
