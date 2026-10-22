"""Conversational development regressions; no model or wall clock dependency."""
from datetime import datetime, timezone

import pytest

from app.context.deterministic_extraction import PROVISIONAL_PRODUCTS, extract_explicit_fields
from app.context.ingestion_schemas import StoredMessage
from app.context.schemas import RawMessageEnvelope


def extract(text, zone="Asia/Kuala_Lumpur"):
    now = datetime(2026, 10, 20, 2, tzinfo=timezone.utc)
    raw = RawMessageEnvelope(tenant_id="synthetic_tenant_a", channel="WHATSAPP",
        provider_message_id="audit-dev", sender_identity_id="unverified", sender_alias="Synthetic",
        text=text, received_at=now, message_at=now, business_timezone=zone)
    message = StoredMessage(message_id="audit-dev", raw=raw, synthetic_provider="SYNTHETIC_WHATSAPP",
        content_sha256="a" * 64, processing_status="RECEIVED", ingested_at=now, updated_at=now)
    return extract_explicit_fields(message, catalog=PROVISIONAL_PRODUCTS)


@pytest.mark.parametrize("text", [
    "Hello boss, urgently need 40 burgers for tomorrow 3pm to Bangsar branch",
    "Hi boss 😊 can send 40 burgers tomorrow before 3pm? Thanks!",
    "Morning, 40 pcs burgers please. Delivery tomorrow at 3pm.",
    "老板你好，明天下午3点前要40个burger，谢谢",
    "Hi boss, esok sebelum pukul 3 petang nak 40 burger, boleh?",
    "40 burgers tomorrow before 3pm; phone 0123456789 reference 99881",
])
def test_explicit_item_survives_conversational_wrapping(text):
    result = extract(text)
    qty = next(f for f in result.fields if f.field_name == "quantity")
    assert (qty.value, qty.validation_status) == ("40", "VALID")
    assert qty.evidence[0].quote == "40"
    assert text[qty.evidence[0].start:qty.evidence[0].end] == "40"


@pytest.mark.parametrize("text", [
    "40 burgers, sorry make that 50", "40 or 50 burgers", "not 40 burgers",
    "40 burgers, cancel please", "40 burgers and 6 buns", "40 burgers 99881",
    "40 kg burgers", "-40 burgers", "40.5 burgers",
])
def test_wrapping_fix_does_not_relax_quantity_safety(text):
    qty = next(f for f in extract(text).fields if f.field_name == "quantity")
    assert qty.validation_status != "VALID"


def test_missing_timezone_does_not_block_quantity_or_invent_date():
    fields = {f.field_name: f for f in extract("Hello boss, need 40 burgers tomorrow 3pm", None).fields}
    assert fields["quantity"].value == "40"
    assert fields["requested_delivery_at"].validation_status == "UNRESOLVED"
