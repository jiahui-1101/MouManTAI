import pytest

from app.context.ai.protocol import MODEL_CONFIG, Observation
from app.context.ai.service import ModelProposalService
from app.context.deterministic_extraction import ProductAlias, PROVISIONAL_PRODUCTS, extract_explicit_fields
from app.context.tests.test_deterministic_extraction import stored

CATALOG = (*PROVISIONAL_PRODUCTS, ProductAlias('synthetic_tenant_a','BREAD',('bread','roti','bun burger'),'pcs'))


@pytest.mark.parametrize('alias,sku', [('roti burger','BURGER'),('bun burger','BREAD')])
def test_full_catalog_compound_shadows_short_alias_without_losing_quantity(alias,sku):
    text = f'Tolong sediakan 47 {alias} esok'
    result = extract_explicit_fields(stored(text), catalog=CATALOG)
    products = [f for f in result.fields if f.field_name == 'sku']
    assert [(p.value,p.validation_status) for p in products] == [(sku,'VALID')]
    assert any(f.field_name == 'quantity' and f.value == '47' and f.validation_status == 'VALID' for f in result.fields)
    observation = Observation(field='product', message_id='m1', quote=alias,
        start=text.index(alias), end=text.index(alias)+len(alias))
    candidate = ModelProposalService._candidate(observation,stored(text),CATALOG,*MODEL_CONFIG['gliner'])
    assert candidate.value == sku and candidate.metadata['domain_supported'] == 'true'


def test_distinct_products_and_same_span_catalog_conflicts_are_preserved():
    for text,catalog in [('Need 13 roti burger and 9 bread',CATALOG),
                         ('Need 13 bread',(*CATALOG,ProductAlias('synthetic_tenant_a','OTHER',('bread',),'box')))]:
        result = extract_explicit_fields(stored(text),catalog=catalog)
        assert not any(f.field_name=='quantity' and f.validation_status=='VALID' for f in result.fields)
        assert len([f for f in result.fields if f.field_name=='sku']) >= 2


@pytest.mark.parametrize('expression,hour', [('petang pukul 4',16),('pagi jam 8',8),('下午三点',15),('下午两点半',14),('noon',12)])
def test_literal_times_normalize_without_losing_original_evidence(expression,hour):
    text=f'Need 17 pcs burgers tomorrow {expression}'
    result=extract_explicit_fields(stored(text),catalog=PROVISIONAL_PRODUCTS)
    delivery=next(f for f in result.fields if f.field_name=='requested_delivery_at')
    assert delivery.validation_status=='VALID'
    from datetime import datetime
    assert datetime.fromisoformat(delivery.value).hour==hour
    assert all(text[e.start:e.end]==e.quote for e in delivery.evidence)


@pytest.mark.parametrize('text', ['The 17 burgers arrived today, thanks', '今天送来的17个汉堡很好，谢谢',
    'Batal pesanan 17 biji burger esok', 'Jangan hantar 17 biji burger esok'])
def test_completed_feedback_and_cancellation_never_become_requested_terms(text):
    result=extract_explicit_fields(stored(text),catalog=PROVISIONAL_PRODUCTS)
    assert not any(f.field_name in {'quantity','requested_delivery_at'} and f.validation_status=='VALID' for f in result.fields)


def test_single_explicit_amendment_is_a_requested_target_not_a_confirmation():
    result=extract_explicit_fields(stored('Please update the order to 47 pcs burgers tomorrow instead'),catalog=PROVISIONAL_PRODUCTS)
    assert any(f.field_name=='quantity' and f.value=='47' and f.validation_status=='VALID' for f in result.fields)
    unsafe=extract_explicit_fields(stored('Change 17 burgers to 47 burgers instead'),catalog=PROVISIONAL_PRODUCTS)
    assert not any(f.field_name=='quantity' and f.validation_status=='VALID' for f in unsafe.fields)


@pytest.mark.parametrize('field,quote,text',[('quantity','47 guests','Need burgers for 47 guests'),
    ('quantity','47/19','Need burgers for 47/19 people'),('product','burger sauce','Need 47 burger sauce')])
def test_gliner_cannot_validate_partial_product_or_first_number(field,quote,text):
    obs=Observation(field=field,message_id='m1',quote=quote,start=text.index(quote),end=text.index(quote)+len(quote))
    candidate=ModelProposalService._candidate(obs,stored(text),CATALOG,*MODEL_CONFIG['gliner'])
    assert candidate.metadata['domain_supported']=='false'
