"""P1 review boundary: a human correction does not create catalog membership."""
from collections.abc import Sequence

from .deterministic_extraction import ProductAlias
from .order_context_schemas import RequestedItem


def approved_review_products(tenant_id: str, catalog: Sequence[ProductAlias]) -> list[dict[str, str]]:
    return [dict(sku=sku, unit=unit) for sku, unit in sorted({
        (p.sku, p.unit) for p in catalog if p.tenant_id == tenant_id
    })]


def review_item_errors(tenant_id: str, items: Sequence[RequestedItem],
                       catalog: Sequence[ProductAlias]) -> list[str]:
    allowed = {(p['sku'], p['unit']) for p in approved_review_products(tenant_id, catalog)}
    return [f"Item #{i}: SKU/unit is not in this tenant's approved catalog; map the product or leave unresolved"
            for i, item in enumerate(items, 1) if (item.sku, item.unit) not in allowed]
