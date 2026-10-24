"""Controlled rolling synthetic P2 and commercial evidence fixtures."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.feasibility.production import EvaluationSnapshot
from app.feasibility.production_fixtures import build_production_example
from app.orders.terms import OrderTerms


def mock_snapshot(*, stock: str = "150", tenant_id: str = "tenant_001") -> EvaluationSnapshot:
    original, _ = build_production_example()
    shift = datetime.now(UTC) - original.as_of - timedelta(minutes=1)

    def move(value):
        if isinstance(value, datetime):
            return value + shift
        if isinstance(value, dict):
            return {key: tenant_id if key == "tenant_id" else move(item)
                    for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [move(item) for item in value]
        return value

    data = move(original.model_dump(exclude_computed_fields=True))
    data["operational"]["inventory_lots"][0]["quantity"] = Decimal(stock)
    return EvaluationSnapshot.model_validate(data)


def mock_terms(tenant_id: str, *, request_id: str = "order_test", quantity: str = "10") -> OrderTerms:
    now = datetime.now(UTC)
    return OrderTerms.model_validate({
        "tenant_id": tenant_id, "order_request_id": request_id, "customer_id": "customer_test",
        "terms_revision": 1,
        "items": [{"sku": "BURGER", "quantity": quantity, "unit": "pcs", "unit_price": "2"}],
        "fulfilment_method": "DELIVERY", "location_ref": "mock_address",
        "window_start": (now + timedelta(hours=24)).isoformat(),
        "window_end": (now + timedelta(hours=27)).isoformat(),
        "business_timezone": "Asia/Kuala_Lumpur", "currency": "MYR",
        "fees": "5", "tax": "0", "discount": "0", "total": str(Decimal(quantity) * 2 + 5),
        "price_source": {"source_type": "APPROVED_CATALOG", "source_id": "mock_catalog",
                         "source_version": "1", "policy_ref": "mock_policy",
                         "disclosed_at": (now - timedelta(hours=1)).isoformat(),
                         "evidence_refs": ["evidence_disclosure"]},
        "binding_policy_ref": "mock_policy", "source_message_ids": ["mock_message"],
        "evidence_refs": ["evidence_order", "evidence_disclosure"],
    })
