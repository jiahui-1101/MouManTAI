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


@pytest.fixture
def detail_db(demo, session):
    from app.core.dependencies import get_db
    app.dependency_overrides[get_db] = lambda: session
    yield session
    app.dependency_overrides.pop(get_db, None)


def add_commitment(session, order_id="ord_hero_001", tenant="tenant_demo_01"):
    from datetime import datetime, timezone
    from app.core.models import CommitmentRecord
    session.add(CommitmentRecord(tenant_id=tenant, commitment_id="com_001", order_id=order_id,
        customer_id="customer_demo", terms={"sku": "BURGER_PREMIUM", "quantity": "100", "unit": "pcs",
        "deadline": "2026-10-26T08:00:00Z"}, agreement_state="CONFIRMED", feasibility_state="FEASIBLE",
        risk_state="NORMAL", recovery_state="NONE", fulfilment_state="FULFILLED", commitment_version=1,
        evidence_refs=["synthetic://test"], updated_at=datetime.now(timezone.utc)))
    session.commit()


def test_detail_does_not_promote_core_states_to_order_decisions(demo, detail_db):
    add_commitment(detail_db)
    response = demo.get("/v1/demo/orders/ord_hero_001", headers=HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data["order"]["lifecycle_status"] == "UNKNOWN"
    assert data["related_commitment"]["commitment_id"] == "com_001"
    assert data["assessment_availability"] == "UNAVAILABLE"
    assert data["assessments"] == []
    assert demo.get("/v1/demo/orders/no_such_order", headers=HEADERS).status_code == 404


def test_detail_without_core_and_other_tenant_core(demo, detail_db):
    add_commitment(detail_db, tenant="another_tenant")
    data = demo.get("/v1/demo/orders/ord_hero_001", headers=HEADERS).json()
    assert data["related_commitment"] is None
    assert data["assessment_availability"] == "UNAVAILABLE"
    assert "another_tenant" not in str(data)


def test_wrong_link_rejected(demo, detail_db):
    add_commitment(detail_db, order_id="other_order")
    assert demo.get("/v1/demo/orders/ord_hero_001", headers=HEADERS).status_code == 409


def test_bad_assessment_provenance_is_explicit(demo, detail_db, monkeypatch):
    from app.core.feasibility_adapters import AuthoritativeAssessmentHistoryReader
    from app.core.errors import DomainError
    add_commitment(detail_db)
    def invalid(*args):
        raise DomainError("ASSESSMENT_PROVENANCE_MISSING", "Missing provenance", status_code=409)
    monkeypatch.setattr(AuthoritativeAssessmentHistoryReader, "list_for_commitment", invalid)
    data = demo.get("/v1/demo/orders/ord_hero_001", headers=HEADERS).json()
    assert data["assessment_availability"] == "UNVERIFIABLE"
    assert "ASSESSMENT_PROVENANCE_MISSING" in data["assessment_reason"]
    assert data["assessments"] == []
