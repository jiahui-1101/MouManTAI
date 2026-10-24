import pytest
from pydantic import ValidationError
from app.orders.demo_data import DemoDataset, load_demo_dataset


def test_shared_requests_are_distinct_from_commitment_decisions():
    data = load_demo_dataset()
    assert data.coverage == "partial"
    assert {o.order_id: o.commitment_id for o in data.orders} == {
        "ord_normal_01": "com_normal_01", "ord_hero_001": "com_001",
        "ord_delay_01": "com_delay_01", "ord_ambiguous_01": "com_ambiguous_01",
        "ord_fulfilled_01": "com_fulfilled_01",
    }
    assert all(o.lifecycle_status == "UNKNOWN" and o.evidence_refs for o in data.orders)
    assert all(o.received_at.tzinfo and o.requested_delivery_at.tzinfo for o in data.orders)


def test_reject_duplicate_identity_and_fabricated_acceptance():
    raw = load_demo_dataset().model_dump(mode="json")
    raw["orders"].append(raw["orders"][0])
    with pytest.raises(ValidationError):
        DemoDataset.model_validate(raw)
    raw["orders"].pop()
    raw["orders"][0]["lifecycle_status"] = "ACCEPTED"
    with pytest.raises(ValidationError):
        DemoDataset.model_validate(raw)
