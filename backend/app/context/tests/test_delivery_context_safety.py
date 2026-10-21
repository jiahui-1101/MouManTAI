from datetime import datetime, timezone

import pytest

from app.context.deterministic_extraction import PROVISIONAL_PRODUCTS, extract_explicit_fields
from app.context.schemas import RawMessageEnvelope
from app.context.tests.test_deterministic_extraction import stored, named


def extract(message):
    return named(extract_explicit_fields(message, catalog=PROVISIONAL_PRODUCTS), "requested_delivery_at")[0]


def test_omitted_and_null_timezone_are_not_a_business_default():
    original = stored("Deliver tomorrow at 3pm")
    payload = original.raw.model_dump()
    payload.pop("business_timezone")
    raw = RawMessageEnvelope.model_validate(payload)
    assert raw.business_timezone is None
    assert "business_timezone" not in raw.model_fields_set
    field = extract(original.model_copy(update={"raw": raw}))
    assert field.validation_status == "UNRESOLVED" and field.value is None
    assert field.metadata["timezone_source"] == "missing"
    assert extract(stored("Deliver tomorrow at 3pm", tz=None)).validation_status == "UNRESOLVED"


def test_explicit_timezone_is_declared_input_not_an_invented_tenant_default():
    field = extract(stored("Deliver tomorrow at 3pm"))
    assert field.value == "2026-10-21T15:00:00+08:00"
    assert field.metadata["timezone_source"] == "message.business_timezone"
    assert field.metadata["source_timestamp_policy"] == "message_at_else_received_at_v1"


@pytest.mark.parametrize("text", [
    "Deliver 10月24日 at 3pm", "Deliver on October 24 at 3pm", "Deliver on 24 October",
    "Deliver on 10/24 at 15:00", "Deliver on 24/10/2026 at 15:00",
])
@pytest.mark.parametrize("tz", [None, "Asia/Kuala_Lumpur"])
def test_yearless_or_ambiguous_dates_require_explicit_unambiguous_year(text, tz):
    field = extract(stored(text, tz=tz))
    assert field.validation_status == "UNRESOLVED" and field.value is None
    assert field.evidence


def test_relative_date_uses_message_at_across_delayed_midnight_ingestion():
    message = stored("Deliver tomorrow at 3pm", received_at=datetime(2026, 10, 21, 2, tzinfo=timezone.utc))
    raw = message.raw.model_copy(update={"message_at": datetime(2026, 10, 20, 15, 55, tzinfo=timezone.utc)})
    field = extract(message.model_copy(update={"raw": raw}))
    assert field.value == "2026-10-21T15:00:00+08:00"
    assert field.metadata["source_timestamp_source"] == "message_at"
    assert field.metadata["source_timestamp"] == "2026-10-20T15:55:00+00:00"


def test_received_at_is_explicit_fallback_not_processing_clock():
    field = extract(stored("Deliver tomorrow at 3pm"))
    assert field.metadata["source_timestamp_source"] == "received_at"
    assert field.metadata["source_timestamp"] == "2026-10-20T02:00:00+00:00"


def test_future_source_timestamp_does_not_anchor_delivery():
    message = stored("Deliver tomorrow at 3pm")
    raw = message.raw.model_copy(update={"message_at": datetime(2026, 10, 22, tzinfo=timezone.utc)})
    field = extract(message.model_copy(update={"raw": raw}))
    assert field.validation_status == "UNRESOLVED" and field.value is None
    assert "message_at" in field.metadata["reason"]
