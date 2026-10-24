from datetime import datetime, timezone
import pytest
from app.orders.models import P4OrderRecord

HEADERS = {"X-Tenant-ID": "tenant_demo_01", "X-Actor-ID": "user_owner_01"}


@pytest.fixture(autouse=True)
def setup_orders(session):
    now = datetime.now(timezone.utc)
    records = [
        P4OrderRecord(
            tenant_id="tenant_demo_01",
            order_id="ord_normal_01",
            commitment_id="com_normal_01",
            customer_display_name="Classic Burger Demo Customer",
            requested_items=[{"sku": "BURGER_CLASSIC", "quantity": "50", "unit": "pcs"}],
            requested_delivery_at=datetime(2026, 10, 27, 8, 0, tzinfo=timezone.utc),
            received_at=datetime(2026, 10, 23, 0, 0, tzinfo=timezone.utc),
            lifecycle_status="UNKNOWN",
            source_channel="SYNTHETIC",
            evidence_refs=["synthetic://ord_normal_01"],
            integration_mode="SYNTHETIC",
            evidence_tier="DEMO-ONLY",
            created_at=now,
            updated_at=now,
        ),
        P4OrderRecord(
            tenant_id="tenant_demo_01",
            order_id="ord_hero_001",
            commitment_id="com_001",
            customer_display_name="Premium Burger Demo Customer",
            requested_items=[{"sku": "BURGER_PREMIUM", "quantity": "100", "unit": "pcs"}],
            requested_delivery_at=datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc),
            received_at=datetime(2026, 10, 23, 1, 0, tzinfo=timezone.utc),
            lifecycle_status="UNKNOWN",
            source_channel="SYNTHETIC",
            evidence_refs=["synthetic://ord_hero_001"],
            integration_mode="SYNTHETIC",
            evidence_tier="DEMO-ONLY",
            created_at=now,
            updated_at=now,
        ),
    ]
    for r in records:
        session.add(r)
    session.commit()


def test_list_orders_from_db(client):
    response = client.get("/v1/orders", headers=HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data["tenant_id"] == "tenant_demo_01"
    assert data["actor_id"] == "user_owner_01"
    assert data["read_authorized"] is True
    assert data["coverage"] == "partial"
    assert len(data["orders"]) == 2
    order_ids = [o["order_id"] for o in data["orders"]]
    assert "ord_normal_01" in order_ids
    assert "ord_hero_001" in order_ids


def test_list_orders_cross_tenant_isolation(client):
    response = client.get("/v1/orders", headers={"X-Tenant-ID": "tenant_other", "X-Actor-ID": "user_owner_01"})
    assert response.status_code == 200
    data = response.json()
    assert len(data["orders"]) == 0


@pytest.mark.parametrize("actor", ["user_owner_01", "user_manager_01", "user_staff_01"])
def test_allowed_human_roles(client, actor):
    res = client.get("/v1/orders", headers={"X-Tenant-ID": "tenant_demo_01", "X-Actor-ID": actor})
    assert res.status_code == 200


@pytest.mark.parametrize("actor", ["unknown_user", "system", "service_core"])
def test_rejected_actor_roles(client, actor):
    res = client.get("/v1/orders", headers={"X-Tenant-ID": "tenant_demo_01", "X-Actor-ID": actor})
    assert res.status_code == 403


def test_fail_closed_production(client, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    res = client.get("/v1/orders", headers=HEADERS)
    assert res.status_code == 503
    assert res.json()["code"] == "SYNTHETIC_ORDERS_DISABLED"


def test_missing_auth_headers(client):
    res = client.get("/v1/orders")
    assert res.status_code == 400


def test_calendar_valid_range(client):
    params = {
        "from_date": "2026-10-24",
        "to_exclusive": "2026-10-31",
        "time_zone": "Asia/Kuala_Lumpur",
    }
    res = client.get("/v1/orders/planning/calendar", headers=HEADERS, params=params)
    assert res.status_code == 200
    data = res.json()
    assert data["window"]["from_date"] == "2026-10-24"
    assert data["window"]["to_exclusive"] == "2026-10-31"
    assert len(data["orders"]) == 2


def test_calendar_invalid_window_and_tz(client):
    # Invalid window: to_exclusive before from_date
    res = client.get("/v1/orders/planning/calendar", headers=HEADERS, params={"from_date": "2026-10-31", "to_exclusive": "2026-10-24"})
    assert res.status_code == 422
    # Invalid timezone
    res = client.get("/v1/orders/planning/calendar", headers=HEADERS, params={"from_date": "2026-10-24", "to_exclusive": "2026-10-31", "time_zone": "Invalid/Timezone"})
    assert res.status_code == 422


def test_get_order_detail_existing_and_missing(client):
    res = client.get("/v1/orders/ord_normal_01", headers=HEADERS)
    assert res.status_code == 200
    data = res.json()
    assert data["order"]["order_id"] == "ord_normal_01"
    assert data["assessment_availability"] == "UNAVAILABLE"

    res_missing = client.get("/v1/orders/ord_nonexistent", headers=HEADERS)
    assert res_missing.status_code == 404
    assert res_missing.json()["code"] == "ORDER_NOT_FOUND"


def test_mutations_forbidden(client):
    assert client.post("/v1/orders", headers=HEADERS).status_code == 405
    assert client.delete("/v1/orders/ord_normal_01", headers=HEADERS).status_code == 405
    assert client.put("/v1/orders/ord_normal_01", headers=HEADERS).status_code == 405
    assert client.patch("/v1/orders/ord_normal_01", headers=HEADERS).status_code == 405
