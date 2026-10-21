"""Contract-boundary tests; no P1/P3 implementation or live services required."""

import pytest
from pydantic import ValidationError

from app.communication.schemas import RecoveryCommunicationReference
from app.communication.service import inspect_recovery_communication_event
from app.core.errors import DomainError
from app.core.events import CoreEventType, create_domain_event
from app.core.fixture_loader import load_demo_fixture
from app.core.schemas import CommunicationRequest, Confirmation, DomainEvent


@pytest.fixture
def event_data():
    # Actual producer payload: core/integration.py execute_recovery_plan.
    # Different version numbers intentionally prove they are independent concepts.
    return {
        "event_id": "evt_recovery_001", "schema_version": 1,
        "event_type": CoreEventType.RECOVERY_COMMUNICATION_REQUESTED.value,
        "tenant_id": "tenant_demo_01", "commitment_id": "com_001",
        "commitment_version": 11, "correlation_id": "corr_001",
        "causation_id": "evt_plan_001", "occurred_at": "2026-10-21T10:00:00+08:00",
        "payload": {
            "commitment_id": "com_001", "plan_id": "plan_001", "plan_version": 2,
            "proposal_id": "prop_plan_001", "proposal_version": 3,
        },
    }


def inspect(data):
    return inspect_recovery_communication_event(
        DomainEvent.model_validate(data), expected_tenant_id="tenant_demo_01",
    )


def test_reference_preserves_provenance_and_independent_versions(event_data):
    reference = inspect(event_data)
    assert reference.source_event_id == "evt_recovery_001"
    assert reference.correlation_id == "corr_001"
    assert reference.causation_id == "evt_plan_001"
    assert reference.tenant_id == "tenant_demo_01"
    assert reference.commitment_id == "com_001"
    assert reference.plan_id == "plan_001"
    assert reference.proposal_id == "prop_plan_001"
    assert (reference.plan_version, reference.proposal_version, reference.commitment_version) == (
        2, 3, 11,
    )
    assert reference.occurred_at.isoformat() == "2026-10-21T10:00:00+08:00"


def test_existing_core_event_factory_is_compatible(event_data):
    event = create_domain_event(**DomainEvent.model_validate(event_data).model_dump())
    assert inspect_recovery_communication_event(
        event, expected_tenant_id="tenant_demo_01",
    ).source_event_id == event.event_id


@pytest.mark.parametrize("field", [
    "plan_id", "plan_version", "proposal_id", "proposal_version",
])
def test_missing_payload_reference_is_rejected(event_data, field):
    event_data["payload"].pop(field)
    with pytest.raises(DomainError) as caught:
        inspect(event_data)
    assert caught.value.code == "INVALID_COMMUNICATION_REFERENCE"
    assert caught.value.status_code == 422


@pytest.mark.parametrize("value", [0, -1, True, "3", None])
def test_invalid_payload_version_is_not_coerced(event_data, value):
    event_data["payload"]["proposal_version"] = value
    with pytest.raises(DomainError) as caught:
        inspect(event_data)
    assert caught.value.code == "INVALID_COMMUNICATION_REFERENCE"


@pytest.mark.parametrize("field,value,code,status", [
    ("tenant_id", "other_tenant", "TENANT_MISMATCH", 403),
    ("event_type", "confirmation.accepted", "UNSUPPORTED_COMMUNICATION_EVENT", 422),
    ("schema_version", 2, "UNSUPPORTED_EVENT_SCHEMA", 422),
    ("commitment_id", "other_commitment", "COMMITMENT_ID_MISMATCH", 422),
    ("commitment_id", None, "COMMITMENT_ID_MISMATCH", 422),
    ("commitment_version", None, "INVALID_COMMUNICATION_REFERENCE", 422),
])
def test_envelope_boundaries(event_data, field, value, code, status):
    event_data[field] = value
    with pytest.raises(DomainError) as caught:
        inspect(event_data)
    assert (caught.value.code, caught.value.status_code) == (code, status)


def test_missing_payload_target_is_not_filled_from_envelope(event_data):
    event_data["payload"].pop("commitment_id")
    with pytest.raises(DomainError) as caught:
        inspect(event_data)
    assert caught.value.code == "COMMITMENT_ID_MISMATCH"


def test_blank_id_is_not_treated_as_a_valid_reference(event_data):
    event_data["payload"]["plan_id"] = "   "
    with pytest.raises(DomainError) as caught:
        inspect(event_data)
    assert caught.value.code == "INVALID_COMMUNICATION_REFERENCE"


def test_missing_resolved_tenant_fails_closed(event_data):
    with pytest.raises(DomainError) as caught:
        inspect_recovery_communication_event(
            DomainEvent.model_validate(event_data), expected_tenant_id=" ",
        )
    assert caught.value.code == "TENANT_REQUIRED"


def test_projection_has_no_business_side_effect_or_implied_authority(event_data):
    event_data["payload"].update({"approved": True, "revised_terms": {"quantity": "999"}})
    event = DomainEvent.model_validate(event_data)
    original = event.model_dump(mode="json")
    reference = inspect_recovery_communication_event(event, expected_tenant_id=event.tenant_id)
    assert event.model_dump(mode="json") == original
    assert not {"approved", "revised_terms", "message_status", "confirmation_state"}.intersection(
        reference.model_dump()
    )
    assert reference == inspect_recovery_communication_event(event, expected_tenant_id=event.tenant_id)


def test_reference_rejects_naive_time(event_data):
    data = inspect(event_data).model_dump()
    data["occurred_at"] = "2026-10-21T10:00:00"
    with pytest.raises(ValidationError):
        RecoveryCommunicationReference.model_validate(data)


def test_shared_communication_and_confirmation_contracts_are_reused():
    fixture = load_demo_fixture()
    assert type(fixture.communication_request) is CommunicationRequest
    assert type(fixture.confirmation) is Confirmation
    assert fixture.communication_request.proposal_version == fixture.confirmation.proposal_version
    assert CommunicationRequest.model_validate(
        fixture.communication_request.model_dump(mode="json")
    ) == fixture.communication_request
    assert Confirmation.model_validate(
        fixture.confirmation.model_dump(mode="json")
    ) == fixture.confirmation
