import pytest
from pydantic import ValidationError

from app.context.order_context_schemas import ContextReviewRequest, ContextUpdateRequest


@pytest.mark.parametrize('edits', [
    {'tenant_id': 'other'}, {'status': 'INFORMATION_READY'}, {'core_commitment_id': 'com-other'},
    {'field_evidence': {'sku': ['invented']}}, {'requested_delivery_at': '2026-10-23T15:00:00'},
    {'requested_items': [{'sku': 'BURGER', 'quantity': 'Infinity', 'unit': 'pcs'}]},
])
def test_review_rejects_authority_changes_and_untrusted_time_or_quantity(edits):
    with pytest.raises(ValidationError):
        ContextReviewRequest(expected_context_version=1, action='EDIT_FIELD', field_edits=edits)


def test_explicit_offset_human_edit_is_preserved():
    r = ContextReviewRequest(expected_context_version=1, action='EDIT_FIELD',
        field_edits={'requested_delivery_at': '2026-10-23T15:00:00+08:00'})
    assert r.field_edits['requested_delivery_at'].endswith('+08:00')
    with pytest.raises(ValidationError):
        ContextUpdateRequest(expected_context_version=1, requested_delivery_at='2026-10-23T15:00:00')
