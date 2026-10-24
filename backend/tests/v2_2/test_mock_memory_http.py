"""Persisted DEMO history through registered decision-memory insights API."""

from sqlalchemy import func, select

from app.core.models import OutboxEventRecord
from app.decision_memory.mock_models import MockMemoryAuditRecord, MockMemoryDatasetRecord
from app.decision_memory.tests.test_decision_memory import current, fixture, manifest, policy

KEY = "synthetic-test-key-" + "a" * 32
HEADERS = {"X-Tenant-ID": "tenant_001", "X-Actor-ID": "manager_v22",
           "X-Isolated-E2E-Key": KEY}
BASE = "/v1/backend-v2/mock-memory/datasets"


def isolated(monkeypatch):
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E", "1")
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E_KEY", KEY)
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E_MANAGER_ID", "manager_v22")
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E_TENANT_ID", "tenant_001")


def synthetic(value, key=""):
    if isinstance(value, dict):
        return {name: synthetic(item, name) for name, item in value.items()}
    if isinstance(value, list):
        return [synthetic(item, key) for item in value]
    if key == "tenant_id":
        return "tenant_001"
    if key == "source_reader_id":
        return "MOCK_HISTORY"
    if key in {"ref", "selected_ref", "actor_ref", "evidence_id", "evidence_ids",
               "business_context_ref", "provenance_refs", "evidence_refs",
               "approval_ref", "retention_ref", "privacy_ref"} and value is not None:
        return f"synthetic://{value}"
    return value


def dataset():
    return {"dataset_id": "recovery_history_1",
            "manifest": synthetic(manifest().model_dump(mode="json")),
            "cases": [synthetic(fixture(name, proof=name != "B").model_dump(mode="json"))
                      for name in ("A", "B", "C")],
            "policy": synthetic(policy().model_dump(mode="json"))}


def situation():
    return synthetic(current().model_dump(mode="json"))


def test_mock_memory_retrieval_outcomes_and_no_policy_action(client, session, monkeypatch):
    isolated(monkeypatch)
    source = dataset()
    seeded = client.post(BASE, headers=HEADERS, json=source)
    assert seeded.status_code == 201, seeded.text
    assert seeded.json()["evidence_tier"] == "DEMO-ONLY"
    assert client.post(BASE, headers=HEADERS, json=source).status_code == 201
    assert client.get(BASE, headers=HEADERS).json()[0]["dataset_id"] == "recovery_history_1"
    assert client.get(BASE + "/recovery_history_1", headers=HEADERS).status_code == 200
    result = client.post(BASE + "/recovery_history_1/insights", headers=HEADERS,
                         json=situation())
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["retrieval"]["status"] == "ADVISORY_ONLY"
    assert body["retrieval"]["eligible_count"] == 1
    assert body["retrieval"]["matches"][0]["memory_case_id"] == "memory-A"
    assert body["outcomes"]["verified_count"] == 1
    assert body["outcomes"]["unknown_count"] == 2
    assert "DEMO_ONLY_NO_BUSINESS_PERFORMANCE_CLAIM" in body["outcomes"]["limitations"]
    assert body["review_proposal"]["human_review_required"] is True
    assert body["review_proposal"]["execution_authorized"] is False
    assert body["policy_update_authorized"] is False
    assert body["operational_action_authorized"] is False
    session.expire_all()
    assert session.scalar(select(func.count()).select_from(MockMemoryDatasetRecord)) == 1
    assert session.scalar(select(func.count()).select_from(MockMemoryAuditRecord)) == 1
    assert session.scalar(select(func.count()).select_from(OutboxEventRecord)) == 1


def test_mock_memory_source_and_context_fail_closed(client, monkeypatch):
    isolated(monkeypatch)
    source = dataset()
    source["manifest"]["integration_mode"] = "LIVE"
    assert client.post(BASE, headers=HEADERS, json=source).status_code == 422
    source = dataset()
    source["cases"][0]["events"][0]["tenant_id"] = "other"
    assert client.post(BASE, headers=HEADERS, json=source).status_code == 422
    assert client.post(BASE, headers=HEADERS, json=dataset()).status_code == 201
    unverified = situation()
    unverified["evidence_refs"] = ["https://real-source.test"]
    result = client.post(BASE + "/recovery_history_1/insights", headers=HEADERS,
                         json=unverified)
    assert result.status_code == 200
    assert result.json()["retrieval"]["status"] == "CONTEXT_UNVERIFIED"
    assert result.json()["outcomes"] is None
    assert client.post(BASE + "/missing/insights", headers=HEADERS,
                       json=situation()).status_code == 404


def test_mock_memory_identity_and_openapi(client, monkeypatch):
    isolated(monkeypatch)
    assert client.get(BASE, headers=HEADERS | {"X-Actor-ID": "staff_01"}).status_code == 403
    assert client.get(BASE, headers=HEADERS | {"X-Tenant-ID": "other"}).status_code == 403
    paths = client.get("/openapi.json").json()["paths"]
    assert "post" in paths[BASE]
    assert "post" in paths[BASE + "/{dataset_id}/insights"]
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert client.get(BASE, headers=HEADERS).status_code == 503
