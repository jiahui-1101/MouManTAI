"""Judge-facing L0 cases retain honest item evidence without GPU."""

from app.context.tests.test_deterministic_extraction import run


def item_fields(text):
    return [(f.field_name, f.value, f.validation_status)
            for f in run(text).fields if f.field_name in {"sku", "quantity", "unit"}]


def test_delivery_conjunction_does_not_make_known_quantity_ambiguous():
    fields = item_fields("Kindly reserve 18 pcs burgers and deliver on 28 October 2026 at 2:30pm.")
    assert ("sku", "BURGER", "VALID") in fields
    assert ("quantity", "18", "VALID") in fields
    assert ("unit", "pcs", "VALID") in fields


def test_unknown_jar_keeps_name_quantity_and_literal_packaging():
    fields = item_fields("Can you send 24 jars of sambal belacan by 30 October 2026?")
    assert ("sku", "sambal belacan", "UNRESOLVED") in fields
    assert ("quantity", "24", "UNRESOLVED") in fields
    assert ("unit", "jar", "UNRESOLVED") in fields


def test_multiple_unknown_items_keep_separate_observations():
    fields = item_fields("Need 7 trays of pandan tarts and 3 bottles of calamansi juice "
                         "delivered 29 October 2026 before noon.")
    assert ("sku", "pandan tarts", "UNRESOLVED") in fields
    assert ("sku", "calamansi juice", "UNRESOLVED") in fields
    assert ("quantity", "7", "UNRESOLVED") in fields
    assert ("quantity", "3", "UNRESOLVED") in fields
