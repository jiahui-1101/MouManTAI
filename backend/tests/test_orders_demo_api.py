from fastapi.testclient import TestClient
import pytest
from app.main import app

HEADERS = {"X-Tenant-ID": "tenant_demo_01", "X-Actor-ID": "user_owner_01"}


@pytest.fixture
def demo(monkeypatch):
    monkeypatch.setenv("MOUMANTAI_SYNTHETIC_MODE", "1")
    monkeypatch.setenv("MOUMANTAI_ORDERS_DEMO", "1")
    monkeypatch.setenv("ENVIRONMENT", "development")
    # No lifespan: do not start any channel workers.
    return TestClient(app)


def test_queue_partial_provenance_stable_and_read_only(demo):
    first = demo.get("/v1/demo/orders", headers=HEADERS)
    assert first.status_code == 200
    data = first.json()
    assert data == demo.get("/v1/demo/orders", headers=HEADERS).json()
    assert data["coverage"] == "partial" and data["integration_mode"] == "SYNTHETIC"
    assert data["actor_id"] == HEADERS["X-Actor-ID"]
    assert len(data["orders"]) == 5
    assert all(o["lifecycle_status"] == "UNKNOWN" for o in data["orders"])
    assert "source_at" in data and "evidence_refs" in data["orders"][0]
    assert demo.post("/v1/demo/orders", headers=HEADERS).status_code == 405


@pytest.mark.parametrize("tenant,actor", [
    ("another_tenant", "user_owner_01"), ("tenant_demo_01", "unknown"),
    ("tenant_demo_01", "system"), ("tenant_demo_01", "service_core"),
])
def test_no_cross_tenant_or_unrecognized_actor_reads(demo, tenant, actor):
    response = demo.get("/v1/demo/orders", headers={"X-Tenant-ID": tenant, "X-Actor-ID": actor})
    assert response.status_code == 403
    assert "ord_hero_001" not in response.text


@pytest.mark.parametrize("actor", ["user_owner_01", "user_manager_01", "user_staff_01"])
def test_human_demo_roles(demo, actor):
    assert demo.get("/v1/demo/orders", headers={**HEADERS, "X-Actor-ID": actor}).status_code == 200


@pytest.mark.parametrize("key,value,code", [
    ("MOUMANTAI_ORDERS_DEMO", "0", 503), ("MOUMANTAI_SYNTHETIC_MODE", "0", 403),
    ("ENVIRONMENT", "production", 503), ("ENVIRONMENT", "prod", 503),
])
def test_fail_closed(demo, monkeypatch, key, value, code):
    monkeypatch.setenv(key, value)
    assert demo.get("/v1/demo/orders", headers=HEADERS).status_code == code


def test_missing_identity(demo):
    assert demo.get("/v1/demo/orders").status_code == 400
