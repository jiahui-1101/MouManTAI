from datetime import datetime, timezone
import hashlib

import pytest

from app.context.deterministic_extraction import PROVISIONAL_PRODUCTS, VERSION, ProductAlias, extract_explicit_fields
from app.context.fixture_repository import load_catalog
from app.context.ingestion_schemas import StoredMessage
from app.context.schemas import NormalizedMessage, RawMessageEnvelope


def stored(text, tenant="synthetic_tenant_a", received_at=None, tz="Asia/Kuala_Lumpur"):
    now = received_at or datetime(2026, 10, 20, 2, tzinfo=timezone.utc)
    return StoredMessage(message_id="msg_rule_test", raw=RawMessageEnvelope(
        tenant_id=tenant, channel="WHATSAPP", provider_message_id="provider_rule_test",
        sender_identity_id="unverified_sender", sender_alias="Synthetic buyer", received_at=now,
        business_timezone=tz, text=text),
        synthetic_provider="SYNTHETIC_WHATSAPP", content_sha256=hashlib.sha256(text.encode()).hexdigest(),
        processing_status="RECEIVED", ingested_at=now, updated_at=now)


def run(text, catalog=PROVISIONAL_PRODUCTS):
    return extract_explicit_fields(stored(text), catalog=catalog)


def named(result, name):
    return [field for field in result.fields if field.field_name == name]


@pytest.mark.parametrize("text,quantity", [("Please send 24 pcs burgers", "24"),
                                           ("Need 18 burgers", "18"), ("12 pieces BURGER", "12")])
def test_supported_product_and_explicit_quantity(text, quantity):
    result = run(text)
    assert [(f.value, f.validation_status) for f in named(result, "sku")] == [("BURGER", "VALID")]
    assert [(f.value, f.validation_status) for f in named(result, "quantity")] == [(quantity, "VALID")]
    assert result.status == "AVAILABLE" and "manual review" in result.reason
    assert "READY" not in result.model_dump_json()
    if "pcs" not in text and "pieces" not in text:
        assert named(result, "unit")[0].validation_status == "MISSING"


def test_order_reference_is_literal_not_verified_order_or_identity():
    result = run("ORD-773: Need 24 burgers for synthetic_order_a101")
    assert [(f.value, f.validation_status) for f in named(result, "order_id")] == [
        ("ORD-773", "UNRESOLVED"), ("synthetic_order_a101", "UNRESOLVED")]
    assert named(result, "quantity")[0].value == "24"
    assert not named(result, "customer_id")


@pytest.mark.parametrize("text", ["burgers please", "Need burger tomorrow"])
def test_missing_quantity(text):
    assert named(run(text), "quantity")[0].validation_status == "MISSING"


@pytest.mark.parametrize("text", ["24 widgets", "24 cheeseburgers", "24 burgerish"])
def test_unknown_product_does_not_acquire_quantity_or_sku(text):
    result = run(text)
    assert named(result, "sku")[0].validation_status == "UNRESOLVED"
    assert not any(f.validation_status == "VALID" for f in result.fields)


@pytest.mark.parametrize("quantity", ["0", "-4", "+4", "2.5", "1,000"])
def test_invalid_or_unsupported_count_is_never_coerced(quantity):
    assert named(run(f"{quantity} pcs burgers"), "quantity")[0].validation_status != "VALID"


def test_unsupported_unit_is_invalid():
    result = run("24 kg burgers")
    assert named(result, "quantity")[0].validation_status == "INVALID"
    assert named(result, "unit")[0].validation_status == "INVALID"


@pytest.mark.parametrize("text", ["24 or 36 burgers", "24 burgers and buns", "24 burgers; 36 burger",
                                "burgers 24", "Do not send 24 burgers", "24 burgers, maybe 36"])
def test_ambiguous_association_is_unresolved(text):
    result = run(text)
    assert named(result, "quantity")[0].validation_status == "UNRESOLVED"
    assert not any(f.field_name == "quantity" and f.validation_status == "VALID" for f in result.fields)


def test_multiple_supported_products_never_flatten_into_one_item():
    catalog = (*PROVISIONAL_PRODUCTS, ProductAlias("synthetic_tenant_a", "TEST_BUN", ("buns",), "pcs"))
    result = run("24 burgers and 36 buns", catalog)
    assert len(named(result, "sku")) == 2
    assert named(result, "quantity")[0].value is None
    assert named(result, "quantity")[0].validation_status == "UNRESOLVED"


def test_exact_unicode_evidence_and_no_mutation_of_persisted_message():
    message = stored("🍔 请要 24 pcs burgers ORD-773")
    before = message.model_dump(mode="json")
    result = extract_explicit_fields(message, catalog=PROVISIONAL_PRODUCTS)
    for field in result.fields:
        for evidence in field.evidence:
            assert message.raw.text[evidence.start:evidence.end] == evidence.quote
            assert evidence.message_id == message.message_id
            assert (evidence.method, evidence.method_version) == ("RULE", VERSION)
    quantity = named(result, "quantity")[0]
    assert quantity.evidence[0].start == 5  # Emoji is one Unicode code point, not two UTF-16 units.
    assert message.model_dump(mode="json") == before
    NormalizedMessage(message_id=message.message_id, raw=message.raw, content_sha256=message.content_sha256,
                      processing_status=message.processing_status, fields=result.fields)


def test_catalog_is_provisional_fixture_aligned_and_tenant_scoped():
    fixture_rows = {(p.tenant_id, p.sku, p.unit) for p in load_catalog().skus}
    assert {(p.tenant_id, p.sku, p.unit) for p in PROVISIONAL_PRODUCTS} <= fixture_rows
    result = extract_explicit_fields(stored("24 burgers", tenant="another_tenant"), catalog=PROVISIONAL_PRODUCTS)
    assert not any(f.validation_status == "VALID" for f in result.fields)


def test_non_order_tokens_and_extra_numbers_do_not_get_associated():
    result = run("XORD-773 ORD-12suffix: 24 burgers for 60 guests")
    assert not named(result, "order_id")
    assert named(result, "quantity")[0].validation_status == "UNRESOLVED"


# ---------------------------------------------------------------------------
# 1. English and Chinese Demo Expressions
# ---------------------------------------------------------------------------

def test_demo_english_and_chinese_expressions():
    # 1. "I need 100 burgers tomorrow before 3pm"
    # received_at = 2026-10-20 10:00:00+08:00 (Oct 20) -> tomorrow is Oct 21
    msg1 = stored("I need 100 burgers tomorrow before 3pm")
    res1 = extract_explicit_fields(msg1, catalog=PROVISIONAL_PRODUCTS)
    assert named(res1, "sku")[0].value == "BURGER"
    assert named(res1, "quantity")[0].value == "100"
    delivery1 = named(res1, "requested_delivery_at")[0]
    assert delivery1.validation_status == "VALID"
    assert delivery1.value == "2026-10-21T15:00:00+08:00"
    assert delivery1.qualifier == "DEADLINE"
    assert delivery1.evidence[0].quote == "tomorrow before 3pm"

    # 2. "Deliver 100 burgers on 24 October 2026 at 3pm"
    msg2 = stored("Deliver 100 burgers on 24 October 2026 at 3pm")
    res2 = extract_explicit_fields(msg2, catalog=PROVISIONAL_PRODUCTS)
    assert named(res2, "quantity")[0].value == "100"
    delivery2 = named(res2, "requested_delivery_at")[0]
    assert delivery2.validation_status == "VALID"
    assert delivery2.value == "2026-10-24T15:00:00+08:00"
    assert delivery2.qualifier == "EXACT"

    # 3. "Need 100 burgers by 15:00 tomorrow"
    msg3 = stored("Need 100 burgers by 15:00 tomorrow")
    res3 = extract_explicit_fields(msg3, catalog=PROVISIONAL_PRODUCTS)
    delivery3 = named(res3, "requested_delivery_at")[0]
    assert delivery3.validation_status == "VALID"
    assert delivery3.value == "2026-10-21T15:00:00+08:00"
    assert delivery3.qualifier == "DEADLINE"

    # 4. "明天下午3点前要100个burger"
    msg4 = stored("明天下午3点前要100个burger")
    res4 = extract_explicit_fields(msg4, catalog=PROVISIONAL_PRODUCTS)
    assert named(res4, "sku")[0].value == "BURGER"
    assert named(res4, "quantity")[0].value == "100"
    assert named(res4, "unit")[0].value == "pcs"
    assert named(res4, "unit")[0].validation_status == "VALID"
    assert named(res4, "unit")[0].evidence[0].quote == "个"
    delivery4 = named(res4, "requested_delivery_at")[0]
    assert delivery4.validation_status == "VALID"
    assert delivery4.value == "2026-10-21T15:00:00+08:00"
    assert delivery4.qualifier == "DEADLINE"
    assert delivery4.evidence[0].quote == "明天下午3点前"

    # 5. "Please deliver on 2026-10-24"
    msg5 = stored("Please deliver on 2026-10-24")
    res5 = extract_explicit_fields(msg5, catalog=PROVISIONAL_PRODUCTS)
    delivery5 = named(res5, "requested_delivery_at")[0]
    assert delivery5.validation_status == "VALID"
    assert delivery5.value == "2026-10-24"
    assert delivery5.qualifier == "DATE_ONLY"

    # 6. "Deliver today before 5pm"
    msg6 = stored("Deliver today before 5pm")
    res6 = extract_explicit_fields(msg6, catalog=PROVISIONAL_PRODUCTS)
    delivery6 = named(res6, "requested_delivery_at")[0]
    assert delivery6.validation_status == "VALID"
    assert delivery6.value == "2026-10-20T17:00:00+08:00"
    assert delivery6.qualifier == "DEADLINE"


# ---------------------------------------------------------------------------
# 2. Relative Dates Around Midnight
# ---------------------------------------------------------------------------

def test_relative_dates_around_midnight():
    # 23:55 local time on Oct 20 (UTC 15:55 on Oct 20)
    t_before = datetime(2026, 10, 20, 15, 55, tzinfo=timezone.utc)
    msg_before = stored("Need 10 burgers tomorrow before 3pm", received_at=t_before)
    res_before = extract_explicit_fields(msg_before, catalog=PROVISIONAL_PRODUCTS)
    delivery_before = named(res_before, "requested_delivery_at")[0]
    # In Asia/Kuala_Lumpur, local date is Oct 20. Tomorrow is Oct 21.
    assert delivery_before.value == "2026-10-21T15:00:00+08:00"

    # 00:05 local time on Oct 21 (UTC 16:05 on Oct 20)
    t_after = datetime(2026, 10, 20, 16, 5, tzinfo=timezone.utc)
    msg_after = stored("Need 10 burgers tomorrow before 3pm", received_at=t_after)
    res_after = extract_explicit_fields(msg_after, catalog=PROVISIONAL_PRODUCTS)
    delivery_after = named(res_after, "requested_delivery_at")[0]
    # In Asia/Kuala_Lumpur, local date is Oct 21. Tomorrow is Oct 22.
    assert delivery_after.value == "2026-10-22T15:00:00+08:00"


# ---------------------------------------------------------------------------
# 3. Timezone Offsets and Date Boundaries
# ---------------------------------------------------------------------------

def test_timezone_offsets_and_date_boundaries():
    # Fixed UTC moment: 2026-10-20 16:30:00 UTC
    t_utc = datetime(2026, 10, 20, 16, 30, tzinfo=timezone.utc)

    # In Tokyo (UTC+9), 16:30 UTC is Oct 21 01:30 AM -> tomorrow is Oct 22
    msg_tokyo = stored("Need 10 burgers tomorrow before 3pm", received_at=t_utc, tz="Asia/Tokyo")
    res_tokyo = extract_explicit_fields(msg_tokyo, catalog=PROVISIONAL_PRODUCTS)
    assert named(res_tokyo, "requested_delivery_at")[0].value == "2026-10-22T15:00:00+09:00"

    # In New York (UTC-4 in Oct / EDT), 16:30 UTC is Oct 20 12:30 PM -> tomorrow is Oct 21
    msg_ny = stored("Need 10 burgers tomorrow before 3pm", received_at=t_utc, tz="America/New_York")
    res_ny = extract_explicit_fields(msg_ny, catalog=PROVISIONAL_PRODUCTS)
    assert named(res_ny, "requested_delivery_at")[0].value == "2026-10-21T15:00:00-04:00"


# ---------------------------------------------------------------------------
# 4. 'before 3pm' vs 'at 3pm' (Deadline vs Exact)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("phrase,expected_qualifier", [
    ("before 3pm", "DEADLINE"),
    ("by 3pm", "DEADLINE"),
    ("no later than 3pm", "DEADLINE"),
    ("prior to 3pm", "DEADLINE"),
    ("at 3pm", "EXACT"),
    ("on 3pm", "EXACT"),
    ("3pm前", "DEADLINE"),
    ("3pm之前", "DEADLINE"),
    ("下午3点前", "DEADLINE"),
    ("下午3点", "EXACT"),
])
def test_deadline_vs_exact_qualifiers(phrase, expected_qualifier):
    msg = stored(f"Deliver 10 burgers on 2026-10-24 {phrase}")
    res = extract_explicit_fields(msg, catalog=PROVISIONAL_PRODUCTS)
    delivery = named(res, "requested_delivery_at")[0]
    assert delivery.validation_status == "VALID"
    assert delivery.qualifier == expected_qualifier
    assert "15:00:00" in delivery.value


# ---------------------------------------------------------------------------
# 5. Date-Only Expressions
# ---------------------------------------------------------------------------

def test_date_only_expressions_do_not_invent_time():
    msg = stored("Please deliver on 2026-10-24")
    res = extract_explicit_fields(msg, catalog=PROVISIONAL_PRODUCTS)
    delivery = named(res, "requested_delivery_at")[0]
    assert delivery.validation_status == "VALID"
    assert delivery.value == "2026-10-24"
    assert delivery.qualifier == "DATE_ONLY"
    assert "00:00:00" not in delivery.value
    assert "15:00:00" not in delivery.value


# ---------------------------------------------------------------------------
# 6. Invalid Calendar Dates
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_date_text", [
    "Deliver 10 burgers on 2026-02-30",
    "Deliver on 31 April 2026 at 3pm",
    "Deliver on 2026-13-40",
])
def test_invalid_calendar_dates(bad_date_text):
    msg = stored(bad_date_text)
    res = extract_explicit_fields(msg, catalog=PROVISIONAL_PRODUCTS)
    delivery = named(res, "requested_delivery_at")[0]
    assert delivery.validation_status == "INVALID"
    assert delivery.value is None


# ---------------------------------------------------------------------------
# 7. Missing or Ambiguous Timezone
# ---------------------------------------------------------------------------

def test_missing_or_ambiguous_timezone():
    # Relative date "tomorrow" cannot be resolved without a valid timezone
    msg = stored("Need 10 burgers tomorrow before 3pm", tz=None)
    res = extract_explicit_fields(msg, catalog=PROVISIONAL_PRODUCTS)
    delivery = named(res, "requested_delivery_at")[0]
    assert delivery.validation_status == "UNRESOLVED"
    assert delivery.value is None
    assert "timezone" in delivery.metadata.get("reason", "").lower()


# ---------------------------------------------------------------------------
# 8. Conflicting Delivery Expressions
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("conflict_text", [
    "Deliver tomorrow or on 2026-10-25",
    "Deliver today or tomorrow",
    "Deliver at 3pm or 5pm",
    "Deliver 10 burgers tomorrow / 2026-10-25",
])
def test_conflicting_delivery_expressions(conflict_text):
    msg = stored(conflict_text)
    res = extract_explicit_fields(msg, catalog=PROVISIONAL_PRODUCTS)
    delivery = named(res, "requested_delivery_at")[0]
    assert delivery.validation_status == "UNRESOLVED"
    assert delivery.value is None
    assert "conflict" in delivery.metadata.get("reason", "").lower()


# ---------------------------------------------------------------------------
# 9. Unicode Evidence Spans
# ---------------------------------------------------------------------------

def test_unicode_evidence_spans_match_exact_slice():
    text = "🍔 请在明天下午3点前要100个burger ORD-881"
    msg = stored(text)
    res = extract_explicit_fields(msg, catalog=PROVISIONAL_PRODUCTS)
    for f in res.fields:
        for ev in f.evidence:
            assert text[ev.start:ev.end] == ev.quote
            assert ev.message_id == msg.message_id

    delivery = named(res, "requested_delivery_at")[0]
    assert delivery.validation_status == "VALID"
    assert delivery.evidence[0].quote in ("明天下午3点前", "在明天下午3点前")
    assert text[delivery.evidence[0].start:delivery.evidence[0].end] == delivery.evidence[0].quote


# ---------------------------------------------------------------------------
# 10. Unit Normalization Without Unsafe Conversion
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw_unit,expected_norm", [
    ("pcs", "pcs"),
    ("piece", "pcs"),
    ("pieces", "pcs"),
    ("pc", "pcs"),
    ("个", "pcs"),
    ("件", "pcs"),
])
def test_unit_normalization_to_pcs(raw_unit, expected_norm):
    msg = stored(f"Need 50 {raw_unit} burgers")
    res = extract_explicit_fields(msg, catalog=PROVISIONAL_PRODUCTS)
    assert named(res, "quantity")[0].validation_status == "VALID"
    unit_field = named(res, "unit")[0]
    assert unit_field.validation_status == "VALID"
    assert unit_field.value == expected_norm
    assert unit_field.metadata["raw_unit"] == raw_unit


def test_unsupported_unit_not_converted_unsafely():
    # BURGER catalog is 'pcs'. 'kg' and 'box' cannot be unsafely converted to pcs without approved conversion!
    msg = stored("Need 50 kg burgers")
    res = extract_explicit_fields(msg, catalog=PROVISIONAL_PRODUCTS)
    assert named(res, "quantity")[0].validation_status == "INVALID"
    assert named(res, "unit")[0].validation_status == "INVALID"
    assert named(res, "unit")[0].value == "kg"


# ---------------------------------------------------------------------------
# 11. Existing BURGER / Quantity Extraction Regression
# ---------------------------------------------------------------------------

def test_existing_burger_regression():
    msg = stored("Please send 24 pcs burgers")
    res = extract_explicit_fields(msg, catalog=PROVISIONAL_PRODUCTS)
    assert named(res, "sku")[0].value == "BURGER"
    assert named(res, "quantity")[0].value == "24"
    assert named(res, "unit")[0].value == "pcs"
    assert named(res, "requested_delivery_at")[0].validation_status == "MISSING"


# ---------------------------------------------------------------------------
# 12. Unsupported Expressions Remain Unresolved
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("unsupported_text", [
    "Need 100 burgers next Friday",
    "Deliver 100 burgers asap",
    "Same as last time for 100 burgers",
    "尽快送来100个burger",
    "老样子要100个burger",
    "下周五要100个burger",
])
def test_unsupported_expressions_remain_unresolved(unsupported_text):
    msg = stored(unsupported_text)
    res = extract_explicit_fields(msg, catalog=PROVISIONAL_PRODUCTS)
    delivery = named(res, "requested_delivery_at")[0]
    assert delivery.validation_status == "UNRESOLVED"
    assert delivery.value is None
    assert "unsupported" in delivery.metadata.get("reason", "").lower() or "ambiguous" in delivery.metadata.get("reason", "").lower()
