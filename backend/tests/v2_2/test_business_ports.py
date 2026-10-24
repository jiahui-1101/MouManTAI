import pytest
from pydantic import ValidationError


def terms_data(**updates):
    values = {
        "tenant_id": "tenant_a",
        "order_request_id": "order_a",
        "customer_id": "customer_a",
        "terms_revision": 2,
        "items": [
            {
                "sku": "CUP",
                "variant": "500ml",
                "quantity": "100",
                "unit": "pcs",
                "unit_price": "2",
            }
        ],
        "fulfilment_method": "DELIVERY",
        "location_ref": "address_v1",
        "window_start": "2026-10-25T10:00:00+08:00",
        "window_end": "2026-10-25T11:00:00+08:00",
        "business_timezone": "Asia/Kuala_Lumpur",
        "currency": "MYR",
        "fees": "5",
        "tax": "0",
        "discount": "0",
        "total": "205",
        "price_source": {
            "source_type": "APPROVED_CATALOG",
            "source_id": "catalog_a",
            "source_version": "3",
            "policy_ref": "pricing_v3",
            "disclosed_at": "2026-10-23T01:00:00Z",
            "evidence_refs": ["evidence_disclosure"],
        },
        "binding_policy_ref": "policy_v1",
        "source_message_ids": ["message_a"],
        "evidence_refs": ["evidence_order"],
    }
    return values | updates


def command_data(**updates):
    values = {
        "tenant_id": "tenant_a",
        "order_request_id": "order_a",
        "request_version": 5,
        "terms": terms_data(),
        "snapshot_id": "snapshot_a",
        "snapshot_version": 3,
        "assessment_id": "assessment_a",
        "idempotency_key": "reserve_a",
    }
    return values | updates


def make_command(**updates):
    from app.integrations.business_ports import ReservationCommand

    return ReservationCommand.model_validate(command_data(**updates))


def receipt_data(**updates):
    from app.orders.terms import OrderTerms

    terms = OrderTerms.model_validate(terms_data())
    values = {
        "tenant_id": "tenant_a",
        "order_request_id": "order_a",
        "operation_id": "op_a",
        "idempotency_key": "reserve_a",
        "request_version": 5,
        "terms_hash": terms.terms_hash,
        "terms_revision": 2,
        "snapshot_id": "snapshot_a",
        "snapshot_version": 3,
        "assessment_id": "assessment_a",
        "status": "PENDING",
        "mode": "SYNTHETIC",
        "checked_at": "2026-10-23T00:00:00Z",
        "evidence_refs": [],
    }
    return values | updates


def make_receipt(**updates):
    from app.integrations.business_ports import ReservationReceipt

    return ReservationReceipt.model_validate(receipt_data(**updates))


def bind(receipt, *, expected=None, operation_id="op_a"):
    from app.integrations.business_ports import require_receipt_binding

    require_receipt_binding(receipt, expected=expected or make_command(), operation_id=operation_id)


def assert_binding_mismatch(receipt, *, expected=None, operation_id="op_a"):
    from app.core.errors import DomainError

    with pytest.raises(DomainError) as exc:
        bind(receipt, expected=expected, operation_id=operation_id)
    assert exc.value.code == "RESERVATION_RECEIPT_MISMATCH"
    assert exc.value.status_code == 409


def test_request_and_terms_revisions_are_independent_domains():
    command = make_command()
    assert command.request_version == 5
    assert command.terms.terms_revision == 2


@pytest.mark.parametrize("changes", [{"tenant_id": "tenant_b"}, {"order_request_id": "order_b"}])
def test_command_rejects_terms_from_wrong_tenant_or_order(changes):
    from app.integrations.business_ports import ReservationCommand

    command_terms = terms_data(**changes)
    with pytest.raises(ValidationError):
        ReservationCommand.model_validate(command_data(terms=command_terms))


@pytest.mark.parametrize("request_version", [0, -1, "not-a-version", True, 1.5])
def test_command_rejects_invalid_request_version(request_version):
    from app.integrations.business_ports import ReservationCommand

    term_revision = 1 if request_version is True else 2
    with pytest.raises(ValidationError):
        ReservationCommand.model_validate(
            command_data(
                request_version=request_version,
                terms=terms_data(terms_revision=term_revision),
            )
        )


@pytest.mark.parametrize("terms_revision", [0, -1, "not-a-version", True])
def test_command_rejects_invalid_terms_revision(terms_revision):
    from app.integrations.business_ports import ReservationCommand

    with pytest.raises(ValidationError):
        ReservationCommand.model_validate(
            command_data(request_version=1, terms=terms_data(terms_revision=terms_revision))
        )


def test_command_requires_valid_order_terms_and_preserves_its_hash():
    from app.integrations.business_ports import ReservationCommand

    with pytest.raises(ValidationError):
        ReservationCommand.model_validate(command_data() | {"terms": None})
    missing_terms = command_data()
    del missing_terms["terms"]
    with pytest.raises(ValidationError):
        ReservationCommand.model_validate(missing_terms)
    with pytest.raises(ValidationError):
        ReservationCommand.model_validate(command_data(terms=terms_data(total="999")))

    command = make_command()
    assert command.terms.terms_hash.startswith("order-terms-v1:")


@pytest.mark.parametrize("status", ["PENDING", "UNKNOWN", "FAILED", "RELEASED"])
def test_pending_unknown_and_failed_are_never_confirmed_reservation(status):
    receipt = make_receipt(status=status)
    assert receipt.reservation_confirmed is False
    assert receipt.mode == "SYNTHETIC"


def test_confirmed_requires_resource_ids_and_receipt_evidence():
    from app.integrations.business_ports import ReservationReceipt

    with pytest.raises(ValidationError):
        ReservationReceipt.model_validate(receipt_data(status="CONFIRMED"))
    with pytest.raises(ValidationError):
        ReservationReceipt.model_validate(
            receipt_data(status="CONFIRMED", reservation_ids=["res_a"])
        )
    with pytest.raises(ValidationError):
        ReservationReceipt.model_validate(
            receipt_data(status="CONFIRMED", evidence_refs=["receipt_a"])
        )

    receipt = make_receipt(
        status="CONFIRMED", reservation_ids=["res_a"], evidence_refs=["receipt_a"]
    )
    assert receipt.reservation_confirmed
    assert receipt.mode == "SYNTHETIC"


@pytest.mark.parametrize(
    "changes",
    [
        {"checked_at": "2026-10-23T00:00:00"},
        {"checked_at": "not-a-timestamp"},
        {"mode": "ASSUMED_LIVE"},
        {"status": "ACCEPTED"},
        {"snapshot_id": ""},
        {"snapshot_id": "   "},
        {"assessment_id": ""},
        {"assessment_id": "   "},
        {"snapshot_version": 0},
        {"snapshot_version": True},
        {"request_version": 0},
        {"request_version": "5"},
        {"terms_revision": 0},
        {"terms_revision": True},
        {"terms_hash": "unbound"},
        {"actor_role": "OWNER"},
        {"customer_assent": True},
        {"evidence_refs": [""]},
        {"operation_id": " "},
        {"terms_revision": None},
        {"snapshot_id": None},
        {"assessment_id": None},
    ],
)
def test_invalid_receipt_fails_closed(changes):
    from app.integrations.business_ports import ReservationReceipt

    with pytest.raises(ValidationError):
        ReservationReceipt.model_validate(receipt_data(**changes))


@pytest.mark.parametrize(
    "field", ["snapshot_id", "snapshot_version", "assessment_id", "terms_revision"]
)
def test_receipt_requires_each_exact_binding_field(field):
    from app.integrations.business_ports import ReservationReceipt

    missing = receipt_data()
    del missing[field]
    with pytest.raises(ValidationError):
        ReservationReceipt.model_validate(missing)


def test_exact_valid_receipt_binding_succeeds_without_granting_authority():
    receipt = make_receipt(
        status="CONFIRMED", reservation_ids=["res_a"], evidence_refs=["receipt_a"]
    )
    assert bind(receipt) is None
    assert receipt.reservation_confirmed
    assert receipt.mode == "SYNTHETIC"


@pytest.mark.parametrize(
    "changes",
    [
        {"tenant_id": "tenant_b"},
        {"order_request_id": "order_b"},
        {"operation_id": "op_b"},
        {"idempotency_key": "reserve_b"},
        {"request_version": 6},
        {"terms_hash": "order-terms-v1:" + "b" * 64},
        {"terms_revision": 3},
        {"snapshot_id": "snapshot_b"},
        {"snapshot_version": 4},
        {"assessment_id": "assessment_b"},
    ],
)
def test_receipt_binding_rejects_cross_order_tenant_terms_version_and_operation(changes):
    assert_binding_mismatch(make_receipt(**changes))


@pytest.mark.parametrize(
    ("command_changes", "operation_id"),
    [
        ({"request_version": 6}, "op_a"),
        ({"snapshot_id": "snapshot_b"}, "op_a"),
        ({"snapshot_version": 4}, "op_a"),
        ({"assessment_id": "assessment_b"}, "op_a"),
        ({"idempotency_key": "reserve_b"}, "op_a"),
        ({}, "op_b"),
    ],
)
def test_expected_intent_mismatches_reject(command_changes, operation_id):
    assert_binding_mismatch(
        make_receipt(), expected=make_command(**command_changes), operation_id=operation_id
    )


def test_same_snapshot_version_with_different_snapshot_id_rejects():
    assert_binding_mismatch(make_receipt(snapshot_id="snapshot_other"))


def test_same_snapshot_id_with_stale_snapshot_version_rejects():
    assert_binding_mismatch(make_receipt(snapshot_version=2))


def test_assessment_must_belong_to_the_exact_snapshot_binding():
    assert_binding_mismatch(make_receipt(assessment_id="assessment_from_old_snapshot"))


def test_same_terms_and_order_with_assessment_from_another_snapshot_rejects():
    stale_receipt = make_receipt(assessment_id="assessment_from_snapshot_b")
    assert_binding_mismatch(stale_receipt)


def test_terms_revision_is_bound_even_when_canonical_hash_is_unchanged():
    from app.orders.terms import OrderTerms

    receipt = make_receipt()
    revised_terms = OrderTerms.model_validate(terms_data(terms_revision=3))
    assert revised_terms.terms_hash == receipt.terms_hash
    assert_binding_mismatch(receipt, expected=make_command(terms=revised_terms))


def test_matching_replay_is_deterministic_but_stale_versions_do_not_reuse_authority():
    receipt = make_receipt()
    bind(receipt)
    bind(receipt)
    assert_binding_mismatch(receipt, expected=make_command(request_version=6))
    assert_binding_mismatch(receipt, expected=make_command(snapshot_version=4))


def test_ports_use_actual_shared_p2_snapshot_and_have_no_live_implementation():
    from typing import get_type_hints

    from app.feasibility.production import EvaluationSnapshot
    from app.integrations.business_ports import (
        ApprovalNotificationPort,
        BusinessCommandPort,
        BusinessDataReader,
    )

    assert (
        get_type_hints(BusinessDataReader.get_operational_snapshot)["return"] is EvaluationSnapshot
    )
    assert all(
        port._is_protocol
        for port in [BusinessDataReader, BusinessCommandPort, ApprovalNotificationPort]
    )
