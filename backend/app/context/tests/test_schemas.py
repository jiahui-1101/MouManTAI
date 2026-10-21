from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.context.extraction import UnavailableExtractor
from app.context.schemas import BusinessContext, ContextReview, NormalizedMessage, RawMessageEnvelope, RequestedItem


def raw_data():
    return dict(tenant_id="tenant_a", channel="WHATSAPP", provider_message_id="provider_1",
                sender_identity_id="identity_1", sender_alias="Synthetic buyer",
                received_at="2026-10-20T10:00:00+08:00", text="100 burgers")


def message_data():
    return dict(message_id="msg_1", raw=raw_data(), content_sha256="a" * 64,
                processing_status="PROCESSED", fields=[dict(field_name="quantity", value="100",
                validation_status="VALID", evidence=[dict(evidence_id="ev_1", message_id="msg_1",
                quote="100", start=0, end=3, method="FIXTURE", method_version="p1-00")])])


def context_data():
    return dict(tenant_id="tenant_a", context_id="ctx_1", source_message_ids=["msg_1"],
                customer_id="customer_1", customer_identity_status="LINK_VERIFIED", order_id="order_1",
                requested_items=[dict(sku="BURGER", quantity="100", unit="pcs")],
                requested_delivery_at="2026-10-21T15:00:00+08:00", context_version=1, status="READY")


def test_timezone_normalizes_to_utc_without_clock_dependency():
    raw = RawMessageEnvelope(**raw_data())
    assert raw.received_at.isoformat() == "2026-10-20T02:00:00+00:00"
    assert raw.business_timezone is None  # Missing timezone must stay missing.


@pytest.mark.parametrize("change", [
    {"tenant_id": " "}, {"received_at": "2026-10-20T10:00:00"},
    {"channel": "SMS"}, {"business_timezone": "Mars/Nowhere"},
    {"actor_role": "admin"}, {"adapter_mode": "LIVE"},
])
def test_invalid_envelopes_rejected(change):
    with pytest.raises(ValidationError):
        RawMessageEnvelope(**(raw_data() | change))


def test_required_provider_reference():
    data = raw_data()
    del data["provider_message_id"]
    with pytest.raises(ValidationError):
        RawMessageEnvelope(**data)


@pytest.mark.parametrize("quantity", ["0", "-1", "NaN", "Infinity", "one", 100])
def test_quantity_must_be_positive_decimal_string(quantity):
    with pytest.raises(ValidationError):
        RequestedItem(sku="BURGER", quantity=quantity, unit="pcs")


def test_fractional_quantity_and_partial_context_are_valid():
    assert RequestedItem(sku="FLOUR", quantity="0.25", unit="kg").quantity == "0.25"
    data = context_data() | {"status": "PARTIAL", "requested_delivery_at": None, "missing_fields": ["requested_delivery_at"]}
    assert BusinessContext(**data).status == "PARTIAL"


@pytest.mark.parametrize("change", [
    {"context_version": 0}, {"status": "CONFIRMED"}, {"requested_items": []},
    {"requested_delivery_at": None}, {"missing_fields": ["sku"]},
    {"conflicts": ["quantity changed"]}, {"customer_identity_status": "AMBIGUOUS"},
    {"source_message_ids": []},
])
def test_invalid_context_claims_rejected(change):
    with pytest.raises(ValidationError):
        BusinessContext(**(context_data() | change))


def test_verified_context_and_separate_review_validate():
    assert BusinessContext(**context_data()).status == "READY"
    review = ContextReview(tenant_id="tenant_a", context_id="ctx_1", review_id="r1",
                           expected_context_version=1, status="PENDING")
    assert review.status == "PENDING"  # Ready information can still await review.


def test_accepted_review_requires_actor_and_timestamp():
    with pytest.raises(ValidationError):
        ContextReview(tenant_id="tenant_a", context_id="ctx_1", review_id="r1",
                      expected_context_version=1, status="ACCEPTED")
    assert ContextReview(tenant_id="tenant_a", context_id="ctx_1", review_id="r1",
                         expected_context_version=1, status="ACCEPTED", actor_id="staff_1",
                         reviewed_at="2026-10-20T12:00:00+08:00").actor_id == "staff_1"


@pytest.mark.parametrize("mutation", ["quote", "source", "offset", "no_evidence", "confidence", "hash"])
def test_evidence_and_extraction_validation(mutation):
    data = deepcopy(message_data())
    field = data["fields"][0]
    if mutation == "quote":
        field["evidence"][0]["quote"] = "200"
    elif mutation == "source":
        field["evidence"][0]["message_id"] = "another_message"
    elif mutation == "offset":
        field["evidence"][0]["end"] = 2
    elif mutation == "no_evidence":
        field["evidence"] = []
    elif mutation == "confidence":
        field["confidence"] = 1.1
    else:
        data["content_sha256"] = "invalid"
    with pytest.raises(ValidationError):
        NormalizedMessage(**data)


def test_model_boundary_has_safe_unavailable_result():
    message = NormalizedMessage(**message_data())
    result = UnavailableExtractor().extract(message)
    assert result.status == "UNAVAILABLE"
    assert result.fields == []
    assert "manual review" in result.reason


def test_failure_is_not_information_readiness():
    with pytest.raises(ValidationError):
        NormalizedMessage(**(message_data() | {"processing_status": "PROCESSING_FAILED"}))
    assert NormalizedMessage(**(message_data() | {"processing_status": "PROCESSING_FAILED", "diagnostic": "adapter unavailable"})).processing_status == "PROCESSING_FAILED"
