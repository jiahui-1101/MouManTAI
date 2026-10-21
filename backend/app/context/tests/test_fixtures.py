import hashlib
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.context.dev_app import app
from app.context.fixture_models import InboxRecord
from app.context.fixture_repository import load_catalog


def test_catalog_references_and_labels_are_consistent():
    catalog = load_catalog()
    assert len(catalog.records) == 9
    assert len({r.scenario_id for r in catalog.records}) == 9
    assert {r.scenario_id for r in catalog.records} == {e.scenario_id for e in catalog.expectations}
    customers = {(c.tenant_id, c.customer_id) for c in catalog.customers}
    orders = {(o.tenant_id, o.order_id): o for o in catalog.orders}
    skus = {(s.tenant_id, s.sku) for s in catalog.skus}
    for record, expected in zip(catalog.records, catalog.expectations, strict=True):
        raw, context = record.message.raw, record.context
        assert record.message.content_sha256 == hashlib.sha256(raw.text.encode()).hexdigest()
        assert context.status == expected.expected_readiness
        assert context.order_id == expected.expected_order_id
        if context.customer_id:
            assert (context.tenant_id, context.customer_id) in customers
        if context.order_id:
            assert orders[(context.tenant_id, context.order_id)].customer_id == context.customer_id
        for item in context.requested_items:
            assert (context.tenant_id, item.sku) in skus
            assert item.quantity == expected.expected_quantity
        if expected.expected_delivery_at:
            assert context.requested_delivery_at == datetime.fromisoformat(expected.expected_delivery_at)


def rows():
    return {r.scenario_id: r for r in load_catalog().records}


def test_duplicate_fixture_preserves_raw_delivery_key_without_claiming_deduplication():
    data = rows()
    first, second = data["valid"].message, data["duplicate"].message
    key = lambda m: (m.raw.tenant_id, m.raw.channel, m.raw.provider_message_id)
    assert key(first) == key(second)
    assert first.content_sha256 == second.content_sha256
    assert first.message_id != second.message_id  # Both remain in this fixture-only preview.


def test_unsafe_association_and_confirmed_term_labels():
    data, catalog = rows(), load_catalog()
    assert data["ambiguous"].context.order_id is None
    assert data["cross_tenant"].context.order_id is None
    assert data["conflict"].context.status == "CONFLICT"
    confirmed = next(o for o in catalog.orders if o.order_id == "synthetic_order_a102")
    assert confirmed.items[0].quantity == "80"
    assert data["conflict"].context.requested_items[0].quantity == "150"
    assert data["followup"].message.raw.reply_to_provider_message_id == "provider_valid"


def test_tomorrow_is_fixed_to_message_business_date():
    message = rows()["valid"].message
    zone = ZoneInfo(message.raw.business_timezone)
    assert message.raw.received_at.astimezone(zone).date().isoformat() == "2026-10-20"
    assert rows()["valid"].context.requested_delivery_at.astimezone(zone).isoformat() == "2026-10-21T15:00:00+08:00"


@pytest.mark.parametrize("mutation", ["tenant", "context", "evidence", "version"])
def test_invalid_record_references_rejected(mutation):
    data = deepcopy(rows()["valid"].model_dump(mode="json"))
    if mutation == "tenant":
        data["review"]["tenant_id"] = "synthetic_tenant_b"
    elif mutation == "context":
        data["review"]["context_id"] = "other"
    elif mutation == "version":
        data["review"]["expected_context_version"] = 99
    else:
        data["context"]["field_evidence"]["quantity"] = ["missing_evidence"]
    with pytest.raises(ValidationError):
        InboxRecord(**data)


def test_preview_endpoint_is_explicit_and_read_only():
    client = TestClient(app)
    response = client.get("/dev/p1/inbox")
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "SYNTHETIC_FIXTURES"
    assert len(payload["records"]) == 9
    assert {r["message"]["raw"]["tenant_id"] for r in payload["records"]} == {"synthetic_tenant_a"}
    assert "customers" not in payload
    assert client.post("/dev/p1/inbox", json={}).status_code == 405
    assert client.post("/v1/messages/ingest", json={}).status_code == 404
