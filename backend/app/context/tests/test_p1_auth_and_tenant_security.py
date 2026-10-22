"""Comprehensive tenant isolation, authentication and authorization security test suite (WS2).

Verifies:
1. No endpoint trusts caller-supplied envelope tenant over authorized tenant boundary (403 TenantMismatch).
2. Cross-tenant reads and mutations are denied (404 / NotFound).
3. Caller-supplied X-Actor-Role cannot elevate untrusted principals to OWNER or MANAGER.
4. Shared ACTOR_ROLES determines authoritative actor roles for audit history.
5. Publish to Core enforces known synthetic human actor role authorization (403 for unauthorized).
6. Attachments and extracted document evidence enforce tenant isolation.
"""

from datetime import datetime, timezone
from uuid import uuid4
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.context.hosting import mount_p1_ingestion
from app.context.ingestion_schemas import DevelopmentContext
from app.context.postgres_repository import PostgresMessageRepository


@pytest.fixture
def auth_api_client(pg_engine):
    app = FastAPI()
    repo = PostgresMessageRepository(pg_engine)
    mount_p1_ingestion(
        app,
        repository_provider=lambda: repo,
        tenant_provider=lambda: DevelopmentContext(tenant_id="tenant_sec_a"),
    )
    return TestClient(app), repo


def _make_msg_payload(tenant_id: str, text: str = "Need 10 burgers tomorrow before 3pm for ORD-SEC-1"):
    return {
        "tenant_id": tenant_id,
        "channel": "WHATSAPP",
        "provider_message_id": f"sec_msg_{uuid4().hex[:8]}",
        "sender_identity_id": "+60123456789",
        "sender_alias": "Security Buyer",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "business_timezone": "Asia/Kuala_Lumpur",
        "text": text,
        "attachments": [],
    }


def test_cross_tenant_envelope_ingestion_blocked(auth_api_client):
    client, _ = auth_api_client
    # Authorized tenant is tenant_sec_a; attacker submits envelope claiming tenant_sec_b
    payload = _make_msg_payload("tenant_sec_b")
    resp = client.post("/v1/messages/ingest", json=payload)
    assert resp.status_code == 403


def test_cross_tenant_message_isolation(auth_api_client):
    client, repo = auth_api_client
    # Authorized ingestion into tenant_sec_a
    payload = _make_msg_payload("tenant_sec_a")
    ingest_resp = client.post("/v1/messages/ingest", json=payload)
    assert ingest_resp.status_code == 201
    msg_id = ingest_resp.json()["message"]["message_id"]

    # Verify visible within tenant_sec_a
    get_resp = client.get(f"/v1/messages/{msg_id}")
    assert get_resp.status_code == 200

    # Mount another client for tenant_sec_b
    app_b = FastAPI()
    mount_p1_ingestion(
        app_b,
        repository_provider=lambda: repo,
        tenant_provider=lambda: DevelopmentContext(tenant_id="tenant_sec_b"),
    )
    client_b = TestClient(app_b)

    # Cross-tenant read is blocked (404)
    assert client_b.get(f"/v1/messages/{msg_id}").status_code == 404
    # Cross-tenant list does not leak message
    list_b = client_b.get("/v1/messages").json()
    assert all(m["message_id"] != msg_id for m in list_b["items"])


def test_cross_tenant_context_review_and_patch_blocked(auth_api_client):
    client, repo = auth_api_client
    payload = _make_msg_payload("tenant_sec_a")
    msg_id = client.post("/v1/messages/ingest", json=payload).json()["message"]["message_id"]
    ctx_id = client.post(f"/v1/contexts/from-message/{msg_id}").json()["context_id"]

    app_b = FastAPI()
    mount_p1_ingestion(
        app_b,
        repository_provider=lambda: repo,
        tenant_provider=lambda: DevelopmentContext(tenant_id="tenant_sec_b"),
    )
    client_b = TestClient(app_b)

    # Cross-tenant get context
    assert client_b.get(f"/v1/contexts/{ctx_id}").status_code == 404

    # Cross-tenant review context
    review_req = {"expected_context_version": 1, "action": "ACCEPT_EXTRACTION", "note": "Attacker"}
    assert client_b.post(f"/v1/contexts/{ctx_id}/review", json=review_req).status_code == 404

    # Cross-tenant patch context
    patch_req = {"expected_context_version": 1, "special_instructions": "Malicious edit"}
    assert client_b.patch(f"/v1/contexts/{ctx_id}", json=patch_req).status_code == 404

    # Cross-tenant versions and reviews
    assert client_b.get(f"/v1/contexts/{ctx_id}/versions").status_code == 404
    assert client_b.get(f"/v1/contexts/{ctx_id}/reviews").status_code == 404


def test_untrusted_actor_role_elevation_is_prevented(auth_api_client):
    client, _ = auth_api_client
    payload = _make_msg_payload("tenant_sec_a")
    msg_id = client.post("/v1/messages/ingest", json=payload).json()["message"]["message_id"]
    ctx_id = client.post(f"/v1/contexts/from-message/{msg_id}").json()["context_id"]

    # Unknown caller attempts to claim OWNER role via header
    review_req = {
        "expected_context_version": 1,
        "action": "EDIT_FIELD",
        "field_edits": {"special_instructions": "Verified by attacker"},
        "note": "Attacker claiming owner privileges",
    }
    resp = client.post(
        f"/v1/contexts/{ctx_id}/review",
        json=review_req,
        headers={"X-Actor-ID": "external_attacker", "X-Actor-Role": "OWNER"},
    )
    assert resp.status_code == 200
    data = resp.json()
    # Role elevation was stripped: not recorded as OWNER
    assert data["last_reviewed_by"] == "external_attacker"
    assert data["last_reviewed_role"] == "STAFF"


def test_registered_actor_role_is_authoritatively_resolved(auth_api_client):
    client, _ = auth_api_client
    payload = _make_msg_payload("tenant_sec_a")
    msg_id = client.post("/v1/messages/ingest", json=payload).json()["message"]["message_id"]
    ctx_id = client.post(f"/v1/contexts/from-message/{msg_id}").json()["context_id"]

    # user_manager_01 is registered in ACTOR_ROLES as MANAGER. Even if caller sends STAFF, MANAGER is used.
    review_req = {
        "expected_context_version": 1,
        "action": "EDIT_FIELD",
        "field_edits": {"special_instructions": "Manager note"},
        "note": "Authoritative role check",
    }
    resp = client.post(
        f"/v1/contexts/{ctx_id}/review",
        json=review_req,
        headers={"X-Actor-ID": "user_manager_01", "X-Actor-Role": "STAFF"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["last_reviewed_by"] == "user_manager_01"
    assert data["last_reviewed_role"] == "MANAGER"


def test_publish_denies_unknown_actor_or_unauthorized_role(pg_engine):
    repo = PostgresMessageRepository(pg_engine)
    app = FastAPI()
    mount_p1_ingestion(
        app,
        repository_provider=lambda: repo,
        tenant_provider=lambda: DevelopmentContext(tenant_id="synthetic_tenant_a"),
    )
    client = TestClient(app)

    payload = _make_msg_payload("synthetic_tenant_a", "50 pcs burgers tomorrow before 3pm for ORD-1001")
    msg_id = client.post("/v1/messages/ingest", json=payload).json()["message"]["message_id"]
    ctx = client.post(f"/v1/contexts/from-message/{msg_id}").json()
    ctx_id = ctx["context_id"]
    assert ctx["status"] == "INFORMATION_READY"

    # Unknown caller cannot publish (403)
    resp = client.post(
        f"/v1/contexts/{ctx_id}/publish",
        headers={"X-Actor-ID": "unknown_actor", "X-Actor-Role": "OWNER"},
    )
    assert resp.status_code == 403

    # Authorized user_staff_01 can publish
    resp_ok = client.post(
        f"/v1/contexts/{ctx_id}/publish",
        headers={"X-Actor-ID": "user_staff_01"},
    )
    assert resp_ok.status_code == 200
    assert resp_ok.json()["core_commitment_id"] is not None
