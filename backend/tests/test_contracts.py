from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.core.fixture_loader import load_demo_fixture
from app.core.schemas import BusinessContext, DomainEvent


def test_demo_fixture_validates_all_shared_contracts() -> None:
    fixture = load_demo_fixture()

    assert fixture.tenant_id == "tenant_demo_01"
    assert fixture.commitment.commitment_id == "com_001"
    assert fixture.commitment.agreement_state.value == "CONFIRMED"
    assert fixture.feasibility_assessment.status.value == "INFEASIBLE"
    assert len(fixture.recovery_plans) == 2
    assert fixture.confirmation.state.value == "ACCEPTED"
    assert fixture.commitment.fulfilment_state.value == "NOT_STARTED"
    assert fixture.fulfilment_evidence["verified"] is False


def test_decimal_values_are_serialized_as_wire_strings() -> None:
    fixture = load_demo_fixture()

    assert fixture.commitment.terms.quantity == Decimal("100")
    assert fixture.recovery_plans[0].model_dump(mode="json")["estimated_extra_cost"] == "80.00"


def test_legacy_ready_input_is_normalized_to_canonical_status() -> None:
    context = BusinessContext.model_validate(
        {
            "tenant_id": "tenant_demo_01",
            "context_id": "ctx_legacy",
            "source_message_ids": ["msg_legacy"],
            "requested_items": [{"sku": "BURGER", "quantity": "1", "unit": "pcs"}],
            "context_version": 1,
            "status": "READY",
        }
    )

    assert context.status.value == "INFORMATION_READY"


def test_naive_timestamps_are_rejected() -> None:
    with pytest.raises(ValidationError, match="explicit UTC offset"):
        DomainEvent.model_validate(
            {
                "event_id": "evt_001",
                "schema_version": 1,
                "event_type": "commitment.created",
                "tenant_id": "tenant_demo_01",
                "correlation_id": "corr_001",
                "occurred_at": "2026-10-21T10:00:00",
            }
        )
