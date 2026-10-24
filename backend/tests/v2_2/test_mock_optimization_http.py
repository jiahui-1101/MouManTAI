"""Persistent Mock constraints drive native advisory portfolio comparison."""

from datetime import UTC, datetime, timedelta

from mock_order_fixtures import mock_terms
from sqlalchemy import func, select

from app.core.models import OutboxEventRecord
from app.optimization.cp_sat import ORTOOLS_VERSION
from app.optimization.mock_models import MockOptimizationAuditRecord, MockOptimizationDatasetRecord
from app.optimization.tests.test_optimization import NOW, fixture
from app.orders.models import OrderRequestRecord
from app.orders.terms import OrderTerms

KEY = "synthetic-test-key-" + "a" * 32
HEADERS = {"X-Tenant-ID": "tenant_001", "X-Actor-ID": "manager_v22",
           "X-Isolated-E2E-Key": KEY}
BASE = "/v1/backend-v2/mock-optimization/datasets"
ORDER_BASE = "/v1/backend-v2"


def isolated(monkeypatch):
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E", "1")
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E_KEY", KEY)
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E_MANAGER_ID", "manager_v22")
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E_TENANT_ID", "tenant_001")


def seed_reviewed_orders(client):
    bound = {}
    for name, quantity, unit_price, fees, revenue in (
            ("A", "6", "15", "0", "90"), ("B", "7", "20", "20", "160")):
        raw = mock_terms("tenant_001", request_id=name, quantity=quantity).model_dump(mode="json")
        raw["items"] = [{"sku": "box", "quantity": quantity, "unit": "each",
                         "unit_price": unit_price, "variant": None}]
        raw["fees"], raw["total"] = fees, revenue
        terms = OrderTerms.model_validate(raw)
        now = datetime.now(UTC)
        source_id = f"source_{name}"
        inquiry = client.post(ORDER_BASE + "/mock-orbyte/inquiries", headers=HEADERS, json={
            "source_id": source_id, "source_version": 1,
            "terms": terms.model_dump(mode="json"),
            "customer_request_ref": "evidence_order",
            "price_disclosure_ref": "evidence_disclosure",
            "observed_at": (now - timedelta(minutes=1)).isoformat(),
            "valid_through": (now + timedelta(hours=2)).isoformat(),
        })
        assert inquiry.status_code == 201, inquiry.text
        imported = client.post(ORDER_BASE + "/order-requests/import-mock", headers=HEADERS,
                               json={"source_id": source_id, "expected_source_version": 1})
        assert imported.status_code == 201, imported.text
        reviewed = client.post(ORDER_BASE + f"/order-requests/{name}/review", headers=HEADERS,
                               json={"expected_request_version": 1, "decision": "REVIEWED",
                                     "reason": "Reviewed synthetic portfolio candidate"})
        assert reviewed.status_code == 200, reviewed.text
        bound[name] = (terms, imported.json()["created_at"], reviewed.json()["request_version"])
    return bound


def dataset(bound):
    request, spec = fixture()
    shift = datetime.now(UTC) - NOW

    def transform(value, key=""):
        if isinstance(value, dict):
            return {name: transform(item, name) for name, item in value.items()}
        if isinstance(value, list):
            return [transform(item, key) for item in value]
        if key == "tenant_id":
            return "tenant_001"
        if key == "actor_id":
            return "manager_v22"
        if key in {"evidence_refs", "source_refs"} and isinstance(value, str):
            return f"synthetic://{value}"
        if key in {"source_identity", "approved_policy_id"}:
            return f"synthetic://{value}"
        if isinstance(value, str) and "T" in value:
            try:
                return (datetime.fromisoformat(value) + shift).isoformat()
            except ValueError:
                pass
        return value

    payload = {"dataset_id": "portfolio_fixture_1",
               "request": transform(request.model_dump(mode="json")),
               "constraints": transform(spec.model_dump(mode="json"))}
    for candidate in payload["request"]["candidates"]:
        name = candidate["order_request_id"]
        terms, received_at, version = bound[name]
        candidate["request_version"] = version
        candidate["terms_hash"] = terms.terms_hash
        candidate["deadline"] = terms.window_end.isoformat()
        candidate["received_at"] = received_at
        candidate["source_identity"] = f"synthetic://source_{name}"
        candidate["financial"]["request_version"] = version
        candidate["financial"]["terms_hash"] = terms.terms_hash
        candidate["financial"]["revenue"] = str(terms.total)
    for binding in payload["constraints"]["candidate_bindings"]:
        candidate = next(item for item in payload["request"]["candidates"]
                         if item["order_request_id"] == binding["order_request_id"])
        for key in ("request_version", "terms_hash", "source_identity"):
            binding[key] = candidate[key]
    payload["request"]["evaluated_at"] = datetime.now(UTC).isoformat()
    return payload


def test_mock_optimization_registered_solver_and_persistence(client, session, monkeypatch):
    isolated(monkeypatch)
    source = dataset(seed_reviewed_orders(client))
    seeded = client.post(BASE, headers=HEADERS, json=source)
    assert seeded.status_code == 201, seeded.text
    assert seeded.json()["operational_action_authorized"] is False
    assert client.get(BASE, headers=HEADERS).json()[0]["dataset_id"] == "portfolio_fixture_1"
    assert client.get(BASE + "/portfolio_fixture_1", headers=HEADERS).status_code == 200
    assert client.post(BASE, headers=HEADERS, json=source).status_code == 201
    compared = client.get(BASE + "/portfolio_fixture_1/comparison", headers=HEADERS)
    assert compared.status_code == 200, compared.text
    result = compared.json()["result"]
    if ORTOOLS_VERSION == "UNAVAILABLE":
        assert result["trigger"] == "SOURCE_UNAVAILABLE"
        assert result["scenarios"] == []
    else:
        assert result["trigger"] == "JOINT_CONTENTION"
        fcfs, profit, expiry = result["scenarios"]
        assert fcfs["selected_order_ids"] == ["A"]
        assert profit["selected_order_ids"] == ["B"]
        assert expiry["selected_order_ids"] == ["B"]
        assert all(s["validation_status"] == "FIXTURE_VALIDATED" for s in result["scenarios"])
        assert all(s["recommendation_only"] is True for s in result["scenarios"])
    assert compared.json()["evidence_tier"] == "DEMO-ONLY"
    assert compared.json()["operational_action_authorized"] is False
    session.expire_all()
    assert session.scalar(select(func.count()).select_from(MockOptimizationDatasetRecord)) == 1
    assert session.scalar(select(func.count()).select_from(MockOptimizationAuditRecord)) == 1
    assert session.scalar(select(func.count()).select_from(OutboxEventRecord)) == 7


def test_mock_optimization_rejects_foreign_source_and_bad_binding(client, monkeypatch):
    isolated(monkeypatch)
    bound = seed_reviewed_orders(client)
    source = dataset(bound)
    source["request"]["evidence_refs"] = ["https://live.test/stock"]
    assert client.post(BASE, headers=HEADERS, json=source).status_code == 422
    source = dataset(bound)
    source["constraints"]["candidate_bindings"][0]["terms_hash"] = "tampered"
    assert client.post(BASE, headers=HEADERS, json=source).status_code == 422
    source = dataset(bound)
    source["request"]["snapshot_version"] = True
    assert client.post(BASE, headers=HEADERS, json=source).status_code == 422
    assert client.get(BASE + "/missing/comparison", headers=HEADERS).status_code == 404


def test_mock_optimization_revalidates_order_state_at_read(client, session, monkeypatch):
    isolated(monkeypatch)
    assert client.post(BASE, headers=HEADERS,
                       json=dataset(seed_reviewed_orders(client))).status_code == 201
    row = session.get(OrderRequestRecord, ("tenant_001", "B"))
    row.decision_status = "ACCEPTED"
    session.commit()
    response = client.get(BASE + "/portfolio_fixture_1/comparison", headers=HEADERS)
    assert response.status_code == 409
    assert response.json()["code"] == "MOCK_OPTIMIZATION_ORDER_BINDING_MISMATCH"


def test_mock_optimization_identity_and_openapi(client, monkeypatch):
    isolated(monkeypatch)
    assert client.get(BASE, headers=HEADERS | {"X-Tenant-ID": "other"}).status_code == 403
    assert client.get(BASE, headers=HEADERS | {"X-Actor-ID": "staff_01"}).status_code == 403
    assert "post" in client.get("/openapi.json").json()["paths"][BASE]
    assert "get" in client.get("/openapi.json").json()["paths"][BASE + "/{dataset_id}/comparison"]
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert client.get(BASE, headers=HEADERS).status_code == 503
