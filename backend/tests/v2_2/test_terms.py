from copy import deepcopy
from decimal import Decimal, localcontext

import pytest
from pydantic import ValidationError


def terms_data():
    return {
        "tenant_id": "tenant_a", "order_request_id": "order_a", "customer_id": "customer_a",
        "terms_revision": 1,
        "items": [{"sku": "CUP", "variant": "500ml", "quantity": "100.00", "unit": "pcs",
                   "unit_price": "2.00"}],
        "fulfilment_method": "DELIVERY", "location_ref": "address_v1",
        "window_start": "2026-10-25T10:00:00+08:00",
        "window_end": "2026-10-25T11:00:00+08:00", "business_timezone": "Asia/Kuala_Lumpur",
        "currency": "MYR", "fees": "5.00", "tax": "0", "discount": "0", "total": "205.00",
        "price_source": {"source_type": "APPROVED_CATALOG", "source_id": "catalog_a",
                         "source_version": "3", "policy_ref": "pricing_v3",
                         "disclosed_at": "2026-10-23T01:00:00+00:00",
                         "evidence_refs": ["evidence_disclosure"]},
        "special_conditions": ["food safe"], "binding_policy_ref": "policy_v1",
        "source_message_ids": ["message_a"], "evidence_refs": ["evidence_order"],
    }


def make_terms(**updates):
    from app.orders.terms import OrderTerms
    return OrderTerms.model_validate(terms_data() | updates)


def test_hash_is_stable_across_decimal_context_timezone_and_input_order():
    from app.orders.terms import OrderTerms
    original = make_terms()
    equivalent = terms_data()
    equivalent["items"][0]["quantity"] = "100"
    equivalent["window_start"] = "2026-10-25T02:00:00Z"
    equivalent["window_end"] = "2026-10-25T03:00:00Z"
    with localcontext() as ctx:
        ctx.prec = 2
        assert original.terms_hash == OrderTerms.model_validate(equivalent).terms_hash
    assert original.terms_hash.startswith("order-terms-v1:")
    assert original.model_dump(mode="json")["items"][0]["quantity"] == "100.00"


@pytest.mark.parametrize("field,value", [
    ("fees", "6"), ("tax", "1"), ("discount", "1"), ("currency", "USD"),
    ("location_ref", "address_v2"), ("window_end", "2026-10-25T12:00:00+08:00"),
    ("special_conditions", ["new condition"]), ("binding_policy_ref", "policy_v2"),
])
def test_material_term_changes_require_proposal(field, value):
    from app.orders.terms import compare_terms
    original = make_terms()
    data = terms_data() | {field: value}
    if field in {"fees", "tax"}:
        data["total"] = "206"
    elif field == "discount":
        data["total"] = "204"
    result = compare_terms(original, make_terms(**data))
    assert result.matches is False
    assert field in result.changed_fields
    assert result.required_action == "PROPOSAL_REQUIRED"


@pytest.mark.parametrize("field,value", [("sku", "BOX"), ("variant", "400ml"),
                                          ("quantity", "80"), ("unit", "boxes"),
                                          ("unit_price", "3")])
def test_all_line_terms_bound_to_hash(field, value):
    original = make_terms()
    data = terms_data()
    data["items"][0][field] = value
    data["total"] = str(Decimal(data["items"][0]["quantity"]) *
                        Decimal(data["items"][0]["unit_price"]) + 5)
    assert original.terms_hash != make_terms(**data).terms_hash


@pytest.mark.parametrize("mutate", [
    lambda d: d.pop("price_source"),
    lambda d: d["price_source"].pop("disclosed_at"),
    lambda d: d["price_source"].update(evidence_refs=[]),
    lambda d: d["price_source"].update(source_version=""),
    lambda d: d.update(window_start="2026-10-25T10:00:00"),
    lambda d: d.update(window_end=d["window_start"]),
    lambda d: d.update(business_timezone="invented/zone"),
    lambda d: d.update(location_ref=""),
    lambda d: d.update(total="1"),
    lambda d: d.update(discount="999"),
    lambda d: d["items"][0].update(quantity="NaN"),
    lambda d: d["items"][0].update(quantity=1.1),
    lambda d: d["items"][0].update(quantity="0.0000001"),
    lambda d: d["items"].append(deepcopy(d["items"][0])),
    lambda d: d.update(evidence_refs=[""]),
    lambda d: d.update(approved=True),
])
def test_incomplete_untrusted_or_imprecise_terms_rejected(mutate):
    from app.orders.terms import OrderTerms
    data = terms_data()
    mutate(data)
    with pytest.raises(ValidationError):
        OrderTerms.model_validate(data)


def test_terms_are_deeply_immutable_and_revisions_do_not_change_business_hash():
    original = make_terms()
    with pytest.raises(ValidationError):
        original.items[0].quantity = Decimal(80)
    assert original.terms_hash == make_terms(terms_revision=2, evidence_refs=["extra"]).terms_hash


def test_exact_guard_rejects_tenant_version_hash_and_material_mismatch():
    from app.core.errors import DomainError
    from app.orders.terms import require_exact_terms
    original = make_terms()
    assert require_exact_terms(original, original, tenant_id="tenant_a", expected_revision=1,
                               expected_terms_hash=original.terms_hash) is None
    cases = [
        ({"tenant_id": "tenant_b"}, "TERMS_NOT_FOUND", 404),
        ({"expected_revision": 2}, "STALE_TERMS_VERSION", 409),
        ({"expected_terms_hash": "order-terms-v1:wrong"}, "TERMS_MISMATCH", 409),
    ]
    for changed, code, status in cases:
        kwargs = dict(tenant_id="tenant_a", expected_revision=1, expected_terms_hash=original.terms_hash)
        with pytest.raises(DomainError) as exc:
            require_exact_terms(original, original, **(kwargs | changed))
        assert (exc.value.code, exc.value.status_code) == (code, status)
    with pytest.raises(DomainError, match="proposal"):
        require_exact_terms(original, make_terms(location_ref="other"), tenant_id="tenant_a",
                            expected_revision=1, expected_terms_hash=original.terms_hash)


def test_provenance_version_and_customer_identity_bound_to_hash():
    data = terms_data()
    data["price_source"]["source_version"] = "4"
    assert make_terms().terms_hash != make_terms(**data).terms_hash
    assert make_terms().terms_hash != make_terms(customer_id="other").terms_hash
