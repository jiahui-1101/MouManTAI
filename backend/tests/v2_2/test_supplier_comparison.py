from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

NOW = datetime(2026, 10, 23, tzinfo=UTC)


def spec(**changes):
    from app.suppliers.comparison import CategorySpec

    return CategorySpec.model_validate(
        {
            "tenant_id": "a",
            "category_id": "food_container",
            "version": 1,
            "authority": "SME_CONFIG",
            "approval_ref": "category_approval_v1",
            "evidence_refs": ["category_source"],
            "hard_fields": [
                {"name": "capacity_ml", "kind": "DECIMAL", "unit": "ml"},
                {"name": "material", "kind": "TEXT"},
                {"name": "food_safe", "kind": "BOOLEAN"},
            ],
        }
        | changes
    )


def requirement(**changes):
    from app.suppliers.comparison import SupplierRequirement

    return SupplierRequirement.model_validate(
        {
            "tenant_id": "a",
            "category_id": "food_container",
            "spec_version": 1,
            "quantity": "100",
            "unit": "pcs",
            "needed_by": NOW + timedelta(days=3),
            "currency": "MYR",
            "properties": [
                {"name": "capacity_ml", "value": "500", "unit": "ml"},
                {"name": "material", "value": "PP"},
                {"name": "food_safe", "value": True},
            ],
        }
        | changes
    )


def offer(**changes):
    from app.suppliers.comparison import SupplierOffer

    return SupplierOffer.model_validate(
        {
            "tenant_id": "a",
            "supplier_id": "supplier_a",
            "quote_id": "q1",
            "quote_version": 1,
            "category_id": "food_container",
            "spec_version": 1,
            "evidence_refs": ["supplier_message_q1"],
            "properties": [
                {
                    "name": "capacity_ml",
                    "value": "500.0",
                    "unit": "ml",
                    "evidence_refs": ["capacity_source"],
                },
                {"name": "material", "value": "PP", "evidence_refs": ["material_source"]},
                {"name": "food_safe", "value": True, "evidence_refs": ["safety_source"]},
            ],
            "price_per_pack": "20",
            "units_per_pack": "10",
            "unit": "pcs",
            "moq": "10",
            "currency": "MYR",
            "pack_evidence_refs": ["pack_source"],
            "availability": "CLAIMED",
            "available_quantity": "1000",
            "quoted_arrival": NOW + timedelta(days=2),
            "valid_until": NOW + timedelta(days=1),
        }
        | changes
    )


def compare(offers=None, schema=None, req=None):
    from app.suppliers.comparison import compare_offers

    return compare_offers(schema or spec(), req or requirement(), offers or [offer()], now=NOW)


def test_three_quotes_hard_mismatch_unknown_and_conditional_are_not_interchangeable():
    mismatch = offer(
        quote_id="q2",
        properties=[
            {"name": "capacity_ml", "value": "400", "unit": "ml", "evidence_refs": ["cap2"]},
            {"name": "material", "value": "PP", "evidence_refs": ["mat2"]},
            {"name": "food_safe", "value": True, "evidence_refs": ["safe2"]},
        ],
    )
    unknown = offer(quote_id="q3", properties=[])
    result = compare([offer(), mismatch, unknown])
    assert [r.status for r in result] == ["CONDITIONAL", "INCOMPATIBLE", "UNKNOWN"]
    assert "capacity_ml" in result[1].violated_fields
    assert "food_safe" in result[2].missing_fields
    assert all(r.purchasing_authorized is False for r in result)
    assert result[0].quote_version == 1
    assert result[0].normalized_unit_cost == Decimal(2)
    assert result[0].cost_basis == "20 / 10 pcs; rounded to 6 decimal places (HALF_UP)"
    assert result[0].recovery_feasibility == "CONDITIONAL"


@pytest.mark.parametrize(
    "schema_changes",
    [
        {"authority": "EXAMPLE"},
        {"approval_ref": None},
        {"evidence_refs": []},
    ],
)
def test_unapproved_category_examples_are_spec_unknown(schema_changes):
    result = compare(schema=spec(**schema_changes))[0]
    assert result.status == "UNKNOWN"
    assert "SPEC_UNKNOWN" in result.reason_codes
    assert result.normalized_unit_cost is None


def test_missing_spec_and_spec_version_mismatch_fail_closed():
    from app.suppliers.comparison import compare_offers

    assert compare_offers(None, requirement(), [offer()], now=NOW)[0].reason_codes == (
        "SPEC_UNKNOWN",
    )
    assert "SPEC_UNKNOWN" in compare(schema=spec(version=2))[0].reason_codes


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"valid_until": NOW}, "QUOTE_EXPIRED"),
        ({"moq": "200"}, "MOQ_NOT_MET"),
        ({"available_quantity": "50", "availability": "VERIFIED"}, "INSUFFICIENT_AVAILABILITY"),
        ({"quoted_arrival": NOW + timedelta(days=4)}, "ARRIVAL_AFTER_REQUIREMENT"),
        ({"unit": "kg"}, "UNIT_MISMATCH"),
    ],
)
def test_known_hard_violations_remain_incompatible(changes, reason):
    result = compare([offer(**changes)])[0]
    assert result.status == "INCOMPATIBLE"
    assert reason in result.reason_codes


def test_missing_pack_conversion_never_invents_comparable_cost():
    result = compare([offer(pack_evidence_refs=[])])[0]
    assert result.normalized_unit_cost is None
    assert "COST_BASIS_UNVERIFIED" in result.reason_codes


def test_numeric_comparison_does_not_coerce_boolean_or_guess_units():
    props = [dict(p) for p in offer().model_dump()["properties"]]
    props[0]["value"] = True
    assert "capacity_ml" in compare([offer(properties=props)])[0].missing_fields
    props[0]["value"] = "0.5"
    props[0]["unit"] = "litre"
    assert compare([offer(properties=props)])[0].status == "UNKNOWN"


def test_cross_tenant_quote_is_not_disclosed():
    from app.core.errors import DomainError

    with pytest.raises(DomainError) as exc:
        compare([offer(tenant_id="b")])
    assert exc.value.status_code == 404
    assert "supplier_a" not in str(exc.value)


def test_configurable_examples_are_not_preapproved_business_policy():
    from app.suppliers.comparison import category_examples

    examples = category_examples("a")
    assert {s.category_id for s in examples} == {
        "food_container",
        "perishable_ingredient",
        "general_supply",
    }
    assert all(s.authority == "EXAMPLE" and s.approval_ref is None for s in examples)
    assert all(s.evidence_refs == () for s in examples)


def test_schema_and_offer_are_deeply_immutable():
    with pytest.raises(ValidationError):
        offer().properties[0].value = "999"


def test_explicit_extra_hard_requirement_cannot_be_silently_ignored():
    props = [dict(p) for p in requirement().model_dump()["properties"]]
    props.append({"name": "heat_safe", "value": True})
    result = compare(req=requirement(properties=props))[0]
    assert result.status == "UNKNOWN"
    assert "heat_safe" in result.missing_fields


def test_verified_match_still_grants_no_purchase_or_recovery_authority():
    result = compare(
        [
            offer(
                availability="VERIFIED",
                availability_evidence_refs=["availability_proof"],
                verified_property_names=["capacity_ml", "material", "food_safe"],
                verification_evidence_refs=["spec_proof"],
                arrival_evidence_refs=["arrival_proof"],
            )
        ]
    )[0]
    assert result.status == "MATCHES"
    assert result.purchasing_authorized is False
    assert result.recovery_feasibility == "CONDITIONAL"


def test_elapsed_requirement_is_not_a_current_compatible_sourcing_recommendation():
    result = compare(
        [
            offer(
                quoted_arrival=NOW - timedelta(days=2),
                availability="VERIFIED",
                availability_evidence_refs=["availability_proof"],
                verified_property_names=["capacity_ml", "material", "food_safe"],
                verification_evidence_refs=["spec_proof"],
                arrival_evidence_refs=["arrival_proof"],
            )
        ],
        req=requirement(needed_by=NOW - timedelta(days=1)),
    )[0]
    assert result.status == "INCOMPATIBLE"
    assert "REQUIREMENT_EXPIRED" in result.reason_codes


@pytest.mark.parametrize("numeric", [0, 1, 0.0, 1.0])
def test_numeric_safety_value_cannot_be_coerced_to_boolean(numeric):
    from app.suppliers.comparison import PropertyValue

    with pytest.raises(ValidationError):
        PropertyValue(name="food_safe", value=numeric)
