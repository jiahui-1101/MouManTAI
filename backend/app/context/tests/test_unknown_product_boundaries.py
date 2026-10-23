"""Literal unknown items remain separate observations, never approved SKUs."""

from app.context.deterministic_extraction import PROVISIONAL_PRODUCTS, UNIT_NORMALIZATION
from app.context.unknown_products import literal_product_observations


def observations(text):
    return list(literal_product_observations(
        text, catalog=PROVISIONAL_PRODUCTS, tenant_id="synthetic_tenant_a",
        units=UNIT_NORMALIZATION, excluded_spans=[],
    ))


def test_two_unapproved_items_keep_their_own_quantity_and_unit():
    text = ("Need 7 trays of pandan tarts and 3 bottles of calamansi juice "
            "delivered 29 October 2026 before noon.")
    items = observations(text)
    assert [(item["product"], item["quantity"], item["unit"]) for item in items] == [
        ("pandan tarts", "7", "trays"),
        ("calamansi juice", "3", "bottles"),
    ]
    assert all(item["approved"] is None for item in items)
    assert all(text[s:e] == item["product"] for item in items
               for s, e in [item["product_span"]])


def test_known_product_followed_by_quantity_does_not_invent_second_product():
    items = observations("Boss, burger 9 pcs boleh? hantar 28/10/2026 lepas 2pm.")
    assert not any(item["product"].casefold() == "boleh" for item in items)
