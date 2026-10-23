import pytest
from pydantic import ValidationError


def receipt_data():
    return dict(tenant_id="tenant_a", order_request_id="order_a", operation_id="op_a",
                idempotency_key="reserve_a", request_version=1, terms_hash="order-terms-v1:" + "a" * 64,
                status="PENDING", mode="SYNTHETIC", snapshot_version=3,
                checked_at="2026-10-23T00:00:00Z", evidence_refs=[])


def test_pending_unknown_and_failed_are_never_confirmed_reservation():
    from app.integrations.business_ports import ReservationReceipt
    for status in ["PENDING", "UNKNOWN", "FAILED", "RELEASED"]:
        receipt = ReservationReceipt.model_validate(receipt_data() | {"status": status})
        assert receipt.reservation_confirmed is False
        assert receipt.mode == "SYNTHETIC"


def test_confirmed_requires_resource_receipt_evidence():
    from app.integrations.business_ports import ReservationReceipt
    with pytest.raises(ValidationError):
        ReservationReceipt.model_validate(receipt_data() | {"status": "CONFIRMED"})
    result = ReservationReceipt.model_validate(receipt_data() | {
        "status": "CONFIRMED", "reservation_ids": ["res_a"], "evidence_refs": ["receipt_a"],
    })
    assert result.reservation_confirmed


@pytest.mark.parametrize("changes", [
    {"checked_at": "2026-10-23T00:00:00"}, {"mode": "ASSUMED_LIVE"},
    {"snapshot_version": 0}, {"terms_hash": "unbound"}, {"actor_role": "OWNER"},
    {"evidence_refs": [""]}, {"operation_id": " "},
])
def test_invalid_receipt_fails_closed(changes):
    from app.integrations.business_ports import ReservationReceipt
    with pytest.raises(ValidationError):
        ReservationReceipt.model_validate(receipt_data() | changes)


def test_receipt_binding_rejects_cross_order_tenant_terms_version_and_operation():
    from app.core.errors import DomainError
    from app.integrations.business_ports import ReservationReceipt, require_receipt_binding
    receipt = ReservationReceipt.model_validate(receipt_data())
    binding = {key: receipt_data()[key] for key in (
        "tenant_id", "order_request_id", "operation_id", "idempotency_key", "request_version", "terms_hash",
    )}
    require_receipt_binding(receipt, **binding)
    for key in binding:
        with pytest.raises(DomainError) as exc:
            require_receipt_binding(receipt, **(binding | {key: "other"}))
        assert exc.value.code == "RESERVATION_RECEIPT_MISMATCH"


def test_ports_use_actual_shared_p2_snapshot_and_have_no_live_implementation():
    from app.integrations.business_ports import BusinessDataReader, BusinessCommandPort, ApprovalNotificationPort
    from typing import get_type_hints
    from app.feasibility.production import EvaluationSnapshot
    assert get_type_hints(BusinessDataReader.get_operational_snapshot)["return"] is EvaluationSnapshot
    assert all(port._is_protocol for port in [BusinessDataReader, BusinessCommandPort, ApprovalNotificationPort])
