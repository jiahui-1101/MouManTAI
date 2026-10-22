from app.context.document_extractor import extract_document_fields
from app.context.document_schemas import DocumentEvidence


def ev(quote):
    return DocumentEvidence(evidence_id='ev1', evidence_ref='att1', attachment_id='att1',
        page_number=1, quote=quote, method='PDF_TEXT', method_version='test')


def test_document_success_does_not_validate_implicit_units_or_deadlines():
    fields = extract_document_fields([ev('40 burgers\nDelivery 2026-10-24')], tenant_id='synthetic_tenant_a')
    assert all(f['validation_status'] != 'VALID' for f in fields)
    item = next(f for f in fields if f['field_name'] == 'item')
    assert item['unit'] is None
    assert item['quote'] == '40 burgers\nDelivery 2026-10-24'
    assert next(f for f in fields if f['field_name'] == 'requested_delivery_at')['qualifier'] == 'DATE_ONLY'


def test_document_does_not_borrow_other_tenant_catalog():
    fields = extract_document_fields([ev('40 pcs burgers')], tenant_id='no-approved-catalog')
    assert not any(f['field_name'] == 'item' for f in fields)
