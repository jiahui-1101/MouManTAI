from datetime import datetime, timezone
import hashlib

import pytest

from app.context.deterministic_extraction import PROVISIONAL_PRODUCTS, VERSION, ProductAlias, extract_explicit_fields
from app.context.fixture_repository import load_catalog
from app.context.ingestion_schemas import StoredMessage
from app.context.schemas import NormalizedMessage, RawMessageEnvelope


def stored(text, tenant="synthetic_tenant_a"):
    now = datetime(2026, 10, 20, 2, tzinfo=timezone.utc)
    return StoredMessage(message_id="msg_rule_test", raw=RawMessageEnvelope(
        tenant_id=tenant, channel="WHATSAPP", provider_message_id="provider_rule_test",
        sender_identity_id="unverified_sender", sender_alias="Synthetic buyer", received_at=now, text=text),
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
