from datetime import datetime, UTC

import pytest
from sqlalchemy import func, select

from app.core.models import AuditEventRecord, CommitmentRecord, OutboxEventRecord
from test_terms import terms_data


KEY = "synthetic-test-key-" + "z" * 32
HEADERS = {"X-Tenant-ID": "a", "X-Actor-ID": "manager_v22", "X-Isolated-E2E-Key": KEY}


@pytest.fixture
def isolated(monkeypatch):
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E", "1")
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E_KEY", KEY)
    monkeypatch.setenv("MOUMANTAI_ISOLATED_E2E_MANAGER_ID", "manager_v22")


def payload():
    from app.orders.terms import OrderTerms
    original = terms_data() | {"tenant_id": "a"}
    return dict(original=original, proposed=original, expected_revision=1,
                expected_terms_hash=OrderTerms.model_validate(original).terms_hash)


def seed_commitment(session, **changes):
    row = CommitmentRecord(**(dict(
        tenant_id="a", commitment_id="com_v22", order_id="ord_v22", customer_id="cust_v22",
        terms={"sku": "CUP", "quantity": "100", "unit": "pcs"},
        agreement_state="CONFIRMED", feasibility_state="FEASIBLE", risk_state="NORMAL",
        recovery_state="NONE", fulfilment_state="NOT_STARTED", commitment_version=3,
        evidence_refs=["ev_order"], updated_at=datetime.now(UTC),
    ) | changes))
    session.add(row)
    session.commit()
    return row


def test_validation_value_errors_are_safe_json(client):
    response = client.post("/v1/commitments", headers={"X-Tenant-ID": "a", "X-Actor-ID": "user_owner_01"}, json={
        "order_id": "o", "customer_id": "c", "terms": {"sku": "A", "quantity": "1", "unit": "pcs",
        "deadline": "2026-10-25T10:00:00"}, "evidence_refs": ["e1"],
    })
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert "input" not in response.json()["details"]["errors"][0]
    assert "ctx" not in response.json()["details"]["errors"][0]


def test_v22_api_is_disabled_by_default_even_with_development_actor_headers(client, monkeypatch):
    monkeypatch.delenv("MOUMANTAI_ISOLATED_E2E", raising=False)
    response = client.post("/v1/backend-v2/terms/check", headers=HEADERS, json=payload())
    assert response.status_code == 503


@pytest.mark.parametrize("overrides", [
    {"X-Isolated-E2E-Key": "wrong"}, {"X-Actor-ID": "user_owner_01"},
])
def test_isolated_key_and_server_configured_actor_both_required(client, isolated, overrides):
    response = client.post("/v1/backend-v2/terms/check", headers=HEADERS | overrides, json=payload())
    assert response.status_code == 403


def test_production_environment_cannot_enable_preview_routes(client, isolated, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    assert client.post("/v1/backend-v2/terms/check", headers=HEADERS, json=payload()).status_code == 503


def test_terms_check_returns_consistency_only_and_never_mutates_core(client, session, isolated):
    before = session.scalar(select(func.count()).select_from(CommitmentRecord))
    response = client.post("/v1/backend-v2/terms/check", headers=HEADERS, json=payload())
    assert response.status_code == 200
    result = response.json()
    assert result["comparison"]["matches"]
    assert result["acceptance_enabled"] is False
    assert result["source_verified"] is False
    assert result["integration_mode"] == "SYNTHETIC"
    assert session.scalar(select(func.count()).select_from(CommitmentRecord)) == before
    assert session.scalar(select(func.count()).select_from(OutboxEventRecord)) == 0


def test_changed_terms_return_409_without_reservation_or_auto_proposal(client, session, isolated):
    data = payload()
    data["proposed"] = data["original"] | {"location_ref": "new_address"}
    response = client.post("/v1/backend-v2/terms/check", headers=HEADERS, json=data)
    assert response.status_code == 409
    assert response.json()["code"] == "TERMS_MISMATCH"
    assert response.json()["details"]["required_action"] == "PROPOSAL_REQUIRED"
    assert session.scalar(select(func.count()).select_from(CommitmentRecord)) == 0


def test_terms_tenant_scope_and_validation_422(client, isolated):
    data = payload()
    data["original"]["tenant_id"] = "b"
    assert client.post("/v1/backend-v2/terms/check", headers=HEADERS, json=data).status_code == 404
    data = payload()
    data["original"]["total"] = "1"
    response = client.post("/v1/backend-v2/terms/check", headers=HEADERS, json=data)
    assert response.status_code == 422
    assert "price_source" not in str(response.json())  # no original input echoed


def test_persisted_legacy_confirmation_is_not_order_acceptance_receipt(client, session, isolated):
    seed_commitment(session)
    response = client.get("/v1/backend-v2/commitments/com_v22/status-preview", headers=HEADERS)
    assert response.status_code == 200
    data = response.json()
    assert data["commitment_version"] == 3
    assert data["agreement_state"] == "CONFIRMED"
    assert data["customer_status"] == "ORDER_ACCEPTANCE_UNVERIFIED"
    assert data["acceptance_verified"] is False
    assert data["integration_mode"] == "SYNTHETIC"
    assert "cust_v22" not in str(data)
    assert client.get("/v1/backend-v2/commitments/com_v22/status-preview",
                      headers=HEADERS | {"X-Tenant-ID": "b"}).status_code == 404


def test_fulfilled_without_matching_audit_never_projects_completed(client, session, isolated):
    seed_commitment(session, fulfilment_state="FULFILLED")
    result = client.get("/v1/backend-v2/commitments/com_v22/status-preview", headers=HEADERS).json()
    assert result["customer_status"] == "COMPLETION_VERIFICATION_PENDING"
    assert result["fulfilment_verified"] is False


def test_core_fulfilment_audit_projects_completed_and_does_not_write(client, session, isolated):
    seed_commitment(session, fulfilment_state="FULFILLED", evidence_refs=["ev_order", "ev_pod_22"])
    session.add(AuditEventRecord(
        audit_id="aud_v22", tenant_id="a", commitment_id="com_v22",
        event_type="commitment.fulfilment_verified", actor_id="manager_v22", actor_role="MANAGER",
        dimension="fulfilment", previous_state={},
        new_state={"fulfilment_state": "FULFILLED", "commitment_version": 3},
        evidence_refs=["ev_pod_22"], reason="Synthetic delivery receipt",
        correlation_id="corr_v22", occurred_at=datetime.now(UTC),
    ))
    session.commit()
    result = client.get("/v1/backend-v2/commitments/com_v22/status-preview", headers=HEADERS).json()
    assert result["customer_status"] == "COMPLETED"
    assert result["fulfilment_verified"]
    assert result["evidence_refs"] == ["ev_pod_22"]
    assert session.scalar(select(func.count()).select_from(AuditEventRecord)) == 1
    assert session.scalar(select(func.count()).select_from(OutboxEventRecord)) == 0


def test_real_core_http_lifecycle_readback_uses_persisted_fulfilment_audit(client, isolated):
    """Existing Core commands, real test DB and fresh HTTP reads; no optimistic status."""
    core_headers = HEADERS | {"X-Actor-ID": "user_manager_01"}
    created = client.post("/v1/commitments", headers=core_headers, json={
        "order_id": "http_order", "customer_id": "http_customer",
        "terms": {"sku": "CUP", "quantity": "10", "unit": "pcs"}, "evidence_refs": ["ev_request"],
    })
    assert created.status_code == 201
    cid = created.json()["commitment_id"]
    path = f"/v1/backend-v2/commitments/{cid}/status-preview"
    assert client.get(path, headers=HEADERS).json()["customer_status"] == "REQUEST_RECEIVED"
    offered = client.post(f"/v1/commitments/{cid}/proposals", headers=core_headers, json={
        "proposal_id": "prop_http", "expected_commitment_version": 1,
        "reason": "Synthetic terms offer", "evidence_refs": ["ev_offer"],
    })
    assert offered.status_code == 200, offered.text
    assert client.get(path, headers=HEADERS).json()["customer_status"] == "CHANGE_PROPOSED"
    confirmed = client.post(f"/v1/commitments/{cid}/confirm-proposal", headers=core_headers, json={
        "proposal_id": "prop_http", "expected_commitment_version": 2, "decision": "ACCEPT",
        "reason": "Synthetic signed customer response", "evidence_refs": ["ev_signed_confirm_http"],
    })
    assert confirmed.status_code == 200, confirmed.text
    assert client.get(path, headers=HEADERS).json()["customer_status"] == "ORDER_ACCEPTANCE_UNVERIFIED"
    fulfilled = client.post(f"/v1/commitments/{cid}/record-fulfilment", headers=core_headers, json={
        "expected_commitment_version": 3, "fulfilment_state": "FULFILLED",
        "reason": "Synthetic operational delivery proof", "evidence_refs": ["ev_pod_http"],
    })
    assert fulfilled.status_code == 200, fulfilled.text
    status = client.get(path, headers=HEADERS).json()
    assert status["customer_status"] == "COMPLETED"
    assert status["commitment_version"] == 4
    assert status["evidence_refs"] == ["ev_pod_http"]
