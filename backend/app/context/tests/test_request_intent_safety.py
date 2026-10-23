import pytest

from app.context.deterministic_extraction import PROVISIONAL_PRODUCTS, extract_explicit_fields
from app.context.tests.test_deterministic_extraction import stored


@pytest.mark.parametrize('text', [
    'How much for 40 pcs burgers?',
    'Yesterday 40 pcs burgers were great, thanks',
    '40个汉堡昨天送来的很好，谢谢',
    '40 biji burger semalam sedap',
    'Mungkin nak 40 biji burger esok, belum pasti',
    'Might need 40 pcs burgers tomorrow, will confirm later',
])
def test_non_order_and_tentative_observations_cannot_be_ready_terms(text):
    result = extract_explicit_fields(stored(text), catalog=PROVISIONAL_PRODUCTS)
    assert not any(f.field_name in {'quantity','requested_delivery_at'} and f.validation_status == 'VALID' for f in result.fields)
    assert all(e.quote == text[e.start:e.end] for f in result.fields for e in f.evidence)


def test_clear_new_request_survives_price_question_and_past_feedback():
    result = extract_explicit_fields(stored('Yesterday delivery was great. Need 40 pcs burgers tomorrow, how much?'), catalog=PROVISIONAL_PRODUCTS)
    assert any(f.field_name == 'quantity' and f.value == '40' and f.validation_status == 'VALID' for f in result.fields)


@pytest.mark.parametrize('unit', ['paket','bungkus'])
def test_packaging_is_not_implicitly_converted_to_pieces(unit):
    result = extract_explicit_fields(stored(f'Need 40 {unit} burgers tomorrow'), catalog=PROVISIONAL_PRODUCTS)
    assert not any(f.field_name == 'unit' and f.validation_status == 'VALID' and f.value == 'pcs' for f in result.fields)
