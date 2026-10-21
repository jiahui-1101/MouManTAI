import pytest

from app.context.deterministic_extraction import ProductAlias, PROVISIONAL_PRODUCTS, extract_explicit_fields
from app.context.tests.test_deterministic_extraction import stored, named


@pytest.mark.parametrize("unit", ["kg", "kilograms", "box", "boxes"])
def test_normalized_unit_must_match_sku_without_conversion(unit):
    result = extract_explicit_fields(stored(f"20 {unit} burgers"), catalog=PROVISIONAL_PRODUCTS)
    assert named(result, "quantity")[0].validation_status == "INVALID"
    assert named(result, "unit")[0].validation_status == "INVALID"


@pytest.mark.parametrize("unit,token", [("kg", "kilograms"), ("box", "boxes")])
def test_explicit_matching_unit_keeps_original_quote(unit, token):
    catalog = [ProductAlias("synthetic_tenant_a", "TEST_PRODUCT", ("testproduct",), unit)]
    result = extract_explicit_fields(stored(f"20 {token} testproduct"), catalog=catalog)
    assert named(result, "quantity")[0].validation_status == "VALID"
    field = named(result, "unit")[0]
    assert field.validation_status == "VALID" and field.value == unit
    assert field.evidence[0].quote == token


@pytest.mark.parametrize("second_sku,second_unit", [("OTHER_BURGER", "pcs"), ("BURGER", "box")])
def test_alias_with_multiple_catalog_meanings_cannot_be_validated(second_sku, second_unit):
    catalog = (*PROVISIONAL_PRODUCTS,
               ProductAlias("synthetic_tenant_a", second_sku, ("burgers",), second_unit))
    result = extract_explicit_fields(stored("20 pcs burgers"), catalog=catalog)
    assert all(f.validation_status == "UNRESOLVED" for f in named(result, "sku"))
    assert named(result, "quantity")[0].validation_status == "UNRESOLVED"


def test_non_delivery_candidates_do_not_become_authorized_identity_or_ready_context():
    result = extract_explicit_fields(stored("ORD-124 20 pcs burgers tomorrow after 3pm"), catalog=PROVISIONAL_PRODUCTS)
    assert named(result, "order_id")[0].validation_status == "UNRESOLVED"
    assert not named(result, "customer_id")
    assert named(result, "requested_delivery_at")[0].validation_status == "UNRESOLVED"
    assert "READY" not in result.model_dump_json()
