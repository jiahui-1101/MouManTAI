"""Synthetic supplier facts through registered API, comparison and durable choice."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.core.models import OutboxEventRecord
from app.suppliers.models import MockSupplierAuditRecord, MockSupplierSelectionRecord

KEY = "synthetic-test-key-" + "a" * 32
HEADERS = {"X-Tenant-ID": "tenant_001", "X-Actor-ID": "manager_v22",
           "X-Isolated-E2E-Key": KEY}
BASE = "/v1/backend-v2/mock-suppliers/datasets"


def dataset(*, dataset_id="supplier_batch_1", valid=True):
    now = datetime.now(UTC)
    valid_until = now + timedelta(hours=2) if valid else now - timedelta(minutes=1)
    prop = lambda value, ref: {"name": "material", "value": value,
                               "evidence_refs": [f"synthetic://{ref}"]}
    common = {
        "tenant_id": "tenant_001", "supplier_id": "supplier_a", "quote_id": "quote_a",
        "quote_version": 1, "category_id": "container", "spec_version": 1,
        "properties": [prop("PP", "material_a")],
        "evidence_refs": ["synthetic://quote_a"],
        "price_per_pack": "20", "units_per_pack": "10", "unit": "pcs",
        "moq": "10", "currency": "MYR", "pack_evidence_refs": ["synthetic://pack_a"],
        "availability": "VERIFIED", "available_quantity": "300",
        "availability_evidence_refs": ["synthetic://stock_a"],
        "verified_property_names": ["material"],
        "verification_evidence_refs": ["synthetic://verified_a"],
        "quoted_arrival": (now + timedelta(hours=8)).isoformat(),
        "arrival_evidence_refs": ["synthetic://arrival_a"],
        "valid_until": (now + timedelta(hours=1)).isoformat(),
    }
    incompatible = common | {
        "supplier_id": "supplier_b", "quote_id": "quote_b",
        "properties": [prop("PET", "material_b")],
        "evidence_refs": ["synthetic://quote_b"],
    }
    return {
        "dataset_id": dataset_id, "dataset_version": 1,
        "spec": {"tenant_id": "tenant_001", "category_id": "container", "version": 1,
                 "authority": "SME_CONFIG", "approval_ref": "synthetic://sme_spec",
                 "evidence_refs": ["synthetic://spec"],
                 "hard_fields": [{"name": "material", "kind": "TEXT"}]},
        "requirement": {"tenant_id": "tenant_001", "category_id": "container",
                        "spec_version": 1, "properties": [prop("PP", "requirement")],
                        "quantity": "100", "unit": "pcs",
                        "needed_by": (now + timedelta(days=1)).isoformat(), "currency": "MYR"},
        "offers": [common, incompatible],
        "observed_at": (now - timedelta(minutes=1)).isoformat(),
        "valid_through": valid_until.isoformat(),
    }


def isolated(monkeypatch):
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E", "1")
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E_KEY", KEY)
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E_MANAGER_ID", "manager_v22")
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E_TENANT_ID", "tenant_001")


def choose(client, quote="quote_a", **changes):
    return client.post(BASE + "/supplier_batch_1/selection", headers=HEADERS, json={
        "expected_dataset_version": 1, "quote_id": quote, "quote_version": 1,
        "request_key": "selection_001", "reason": "SME reviewed synthetic quote and spec",
    } | changes)


def test_registered_comparison_choice_rfq_and_evidence(client, session, monkeypatch):
    isolated(monkeypatch)
    source = dataset()
    created = client.post(BASE, headers=HEADERS, json=source)
    assert created.status_code == 201, created.text
    assert created.json()["evidence_tier"] == "DEMO-ONLY"
    assert client.get(BASE, headers=HEADERS).json()[0]["dataset_id"] == "supplier_batch_1"
    assert client.get(BASE + "/supplier_batch_1", headers=HEADERS).status_code == 200
    compared = client.get(BASE + "/supplier_batch_1/comparison", headers=HEADERS)
    assert compared.status_code == 200, compared.text
    results = {item["quote_id"]: item for item in compared.json()["results"]}
    assert results["quote_a"]["status"] == "MATCHES"
    assert results["quote_a"]["normalized_unit_cost"] == "2.000000"
    assert results["quote_b"]["status"] == "INCOMPATIBLE"
    assert "HARD_SPEC_MISMATCH" in results["quote_b"]["reason_codes"]
    assert choose(client, "quote_b").status_code == 409
    chosen = choose(client)
    assert chosen.status_code == 201, chosen.text
    assert chosen.json()["supplier_id"] == "supplier_a"
    assert chosen.json()["purchasing_authorized"] is False
    assert chosen.json()["evidence_tier"] == "DEMO-ONLY"
    assert client.get(BASE + "/supplier_batch_1/selection", headers=HEADERS).json() == chosen.json()
    assert choose(client).json()["selection_id"] == chosen.json()["selection_id"]
    assert choose(client, request_key="selection_002").status_code == 409
    assert choose(client, quote="quote_b").status_code == 409
    draft = client.get(BASE + "/supplier_batch_1/rfq-draft", headers=HEADERS)
    assert draft.status_code == 200, draft.text
    assert draft.json()["send_authorized"] is False
    assert draft.json()["status"] == "DRAFT_ONLY"
    session.expire_all()
    assert session.scalar(select(func.count()).select_from(MockSupplierSelectionRecord)) == 1
    assert session.scalar(select(func.count()).select_from(MockSupplierAuditRecord)) == 2
    assert session.scalar(select(func.count()).select_from(OutboxEventRecord)) == 2


def test_supplier_boundaries_and_freshness(client, monkeypatch):
    isolated(monkeypatch)
    source = dataset()
    assert client.post(BASE, headers=HEADERS, json=source).status_code == 201
    assert client.post(BASE, headers=HEADERS, json=source).status_code == 201
    conflict = source | {"dataset_version": 2}
    assert client.post(BASE, headers=HEADERS, json=conflict).status_code == 409
    assert choose(client, expected_dataset_version=2).status_code == 409
    assert choose(client, quote="missing").status_code == 404
    assert client.get(BASE + "/supplier_batch_1/selection", headers=HEADERS).status_code == 404


def test_supplier_identity_source_validation_and_expiry(client, monkeypatch):
    isolated(monkeypatch)
    assert client.get(BASE, headers=HEADERS | {"X-Actor-ID": "staff_01"}).status_code == 403
    assert client.get(BASE, headers=HEADERS | {"X-Tenant-ID": "tenant_002"}).status_code == 403
    foreign = dataset()
    foreign["offers"][0]["evidence_refs"] = ["https://real-provider.test/quote"]
    assert client.post(BASE, headers=HEADERS, json=foreign).status_code == 422
    expired = dataset(dataset_id="expired_batch", valid=False)
    assert client.post(BASE, headers=HEADERS, json=expired).status_code == 422
    assert client.get(BASE + "/unknown", headers=HEADERS).status_code == 404
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert client.get(BASE, headers=HEADERS).status_code == 503


def test_supplier_registered_contract(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert "post" in paths[BASE]
    assert "get" in paths[BASE + "/{dataset_id}/comparison"]
    assert "post" in paths[BASE + "/{dataset_id}/selection"]
