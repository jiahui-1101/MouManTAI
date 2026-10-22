import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.context.hosting import mount_p1_ingestion
from app.context.ingestion_schemas import DevelopmentContext
from app.context.postgres_repository import PostgresMessageRepository


@pytest.fixture
def api_client(pg_engine):
    app = FastAPI()
    repo = PostgresMessageRepository(pg_engine)
    tenant = DevelopmentContext(tenant_id="synthetic_tenant_a")

    mount_p1_ingestion(
        app,
        repository_provider=lambda: repo,
        tenant_provider=lambda: tenant,
    )
    return TestClient(app)


def test_context_end_to_end_lifecycle(api_client):
    # 1. Ingest initial message from trusted phone (+60123456789 -> cust_bk, ORD-1001)
    envelope = {
        "tenant_id": "synthetic_tenant_a",
        "channel": "WHATSAPP",
        "provider_message_id": f"msg_ctx_{uuid4().hex[:8]}",
        "sender_identity_id": "+60123456789",
        "sender_alias": "Burger King Procurement",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "business_timezone": "Asia/Kuala_Lumpur",
        "text": "Please send 50 pcs burgers tomorrow before 3pm for ORD-1001",
        "attachments": [],
    }
    resp = api_client.post("/v1/messages/ingest", json=envelope)
    assert resp.status_code == 201
    msg_1_id = resp.json()["message"]["message_id"]

    # 2. Create context from message
    resp = api_client.post(f"/v1/contexts/from-message/{msg_1_id}")
    assert resp.status_code == 201
    ctx = resp.json()
    ctx_id = ctx["context_id"]
    assert ctx["order_id"] == "ORD-1001"
    assert ctx["customer_id"] == "cust_bk"
    assert ctx["customer_identity_status"] == "LINK_VERIFIED"
    assert ctx["context_version"] == 1
    assert len(ctx["requested_items"]) == 1
    assert ctx["requested_items"][0]["sku"] == "BURGER"
    assert ctx["requested_items"][0]["quantity"] == "50"
    assert ctx["source_message_ids"] == [msg_1_id]

    # 3. Retrieve context by context_id and by order_id
    resp = api_client.get(f"/v1/contexts/{ctx_id}")
    assert resp.status_code == 200
    assert resp.json()["context_id"] == ctx_id

    resp = api_client.get("/v1/contexts/by-order/ORD-1001")
    assert resp.status_code == 200
    assert resp.json()["context_id"] == ctx_id

    # 4. Ingest follow-up message with contradictory quantity (100 instead of 50)
    envelope_2 = {
        "tenant_id": "synthetic_tenant_a",
        "channel": "WHATSAPP",
        "provider_message_id": f"msg_ctx_{uuid4().hex[:8]}",
        "sender_identity_id": "+60123456789",
        "sender_alias": "Burger King Procurement",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "business_timezone": "Asia/Kuala_Lumpur",
        "text": "Please change ORD-1001 to 100 pcs burgers",
        "attachments": [],
    }
    resp = api_client.post("/v1/messages/ingest", json=envelope_2)
    assert resp.status_code == 201
    msg_2_id = resp.json()["message"]["message_id"]

    # 5. Merge follow-up into context
    resp = api_client.post(f"/v1/contexts/from-message/{msg_2_id}")
    assert resp.status_code == 201
    ctx_2 = resp.json()
    assert ctx_2["context_id"] == ctx_id
    assert ctx_2["context_version"] == 2
    assert ctx_2["status"] == "CONFLICT"
    assert len(ctx_2["conflicts"]) > 0
    assert "Quantity conflict: existing 50" in ctx_2["conflicts"][0]
    # Original validated quantity NOT silently overwritten!
    assert ctx_2["requested_items"][0]["quantity"] == "50"
    assert msg_2_id in ctx_2["source_message_ids"]

    # 6. Human Review: Staff clarifies and updates to 100 pcs
    review_req = {
        "expected_context_version": 2,
        "action": "EDIT_FIELD",
        "field_edits": {
            "requested_items": [{"sku": "BURGER", "quantity": "100", "unit": "pcs"}],
            "conflicts": [],  # Resolved
        },
        "note": "Verified phone call with buyer: 100 pcs confirmed",
    }
    resp = api_client.post(
        f"/v1/contexts/{ctx_id}/review",
        json=review_req,
        headers={"X-Actor-ID": "staff_jane", "X-Actor-Role": "DISPATCHER"},
    )
    assert resp.status_code == 200
    reviewed = resp.json()
    assert reviewed["context_version"] == 3
    assert reviewed["status"] == "INFORMATION_READY"
    assert reviewed["requested_items"][0]["quantity"] == "100"
    assert reviewed["conflicts"] == []
    assert reviewed["last_reviewed_by"] == "staff_jane"
    assert reviewed["last_reviewed_role"] == "DISPATCHER"

    # 7. Check versions and review history endpoints
    resp = api_client.get(f"/v1/contexts/{ctx_id}/versions")
    assert resp.status_code == 200
    versions = resp.json()
    assert len(versions) == 3
    assert versions[0]["context_version"] == 3
    assert versions[1]["context_version"] == 2
    assert versions[2]["context_version"] == 1

    resp = api_client.get(f"/v1/contexts/{ctx_id}/reviews")
    assert resp.status_code == 200
    reviews = resp.json()
    assert len(reviews) == 1
    assert reviews[0]["action"] == "EDIT_FIELD"
    assert reviews[0]["actor_id"] == "staff_jane"
    assert reviews[0]["note"] == "Verified phone call with buyer: 100 pcs confirmed"

    # 8. Stale update check: trying to review with version 2 again returns 409
    resp = api_client.post(
        f"/v1/contexts/{ctx_id}/review",
        json=review_req,  # expected_context_version still 2
    )
    assert resp.status_code == 409

    # 9. 404 boundaries
    resp = api_client.get("/v1/contexts/nonexistent_ctx_999")
    assert resp.status_code == 404

    resp = api_client.get("/v1/contexts/by-order/nonexistent_ord_999")
    assert resp.status_code == 404


def test_context_patch_and_review_actions(api_client):
    # Ingest message for ORD-1002
    envelope = {
        "tenant_id": "synthetic_tenant_a",
        "channel": "WHATSAPP",
        "provider_message_id": f"msg_ctx_patch_{uuid4().hex[:8]}",
        "sender_identity_id": "+60123456789",
        "sender_alias": "Burger King Procurement",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "business_timezone": "Asia/Kuala_Lumpur",
        "text": "Please send 30 pcs burgers tomorrow before 3pm for ORD-1002",
        "attachments": [],
    }
    resp = api_client.post("/v1/messages/ingest", json=envelope)
    msg_id = resp.json()["message"]["message_id"]

    resp = api_client.post(f"/v1/contexts/from-message/{msg_id}")
    assert resp.status_code == 201
    ctx = resp.json()
    ctx_id = ctx["context_id"]
    assert ctx["context_version"] == 1

    # 1. PATCH with valid expected_context_version
    patch_req = {
        "expected_context_version": 1,
        "special_instructions": "Handle with care",
        "delivery_qualifier": "DEADLINE",
        "reason": "Customer added delivery instructions",
    }
    resp = api_client.patch(
        f"/v1/contexts/{ctx_id}",
        json=patch_req,
        headers={"X-Actor-ID": "operator_01", "X-Actor-Role": "STAFF"},
    )
    assert resp.status_code == 200
    patched = resp.json()
    assert patched["context_version"] == 2
    assert patched["special_instructions"] == "Handle with care"
    assert patched["delivery_qualifier"] == "DEADLINE"

    # Stale PATCH returns 409
    resp = api_client.patch(f"/v1/contexts/{ctx_id}", json=patch_req)
    assert resp.status_code == 409

    # 2. Review action: MARK_UNRESOLVED
    resp = api_client.post(
        f"/v1/contexts/{ctx_id}/review",
        json={"expected_context_version": 2, "action": "MARK_UNRESOLVED", "note": "Address needs manual check"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "UNRESOLVED"
    assert resp.json()["context_version"] == 3

    # 3. Review action: REQUEST_MORE_INFO
    resp = api_client.post(
        f"/v1/contexts/{ctx_id}/review",
        json={"expected_context_version": 3, "action": "REQUEST_MORE_INFO", "note": "Awaiting customer WhatsApp response"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "INFORMATION_PARTIAL"
    assert resp.json()["context_version"] == 4

    # 4. Review action: ACCEPT_EXTRACTION
    resp = api_client.post(
        f"/v1/contexts/{ctx_id}/review",
        json={"expected_context_version": 4, "action": "ACCEPT_EXTRACTION", "note": "Staff verified details"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "INFORMATION_READY"
    assert resp.json()["context_version"] == 5


def test_context_api_tenant_isolation(pg_engine):
    repo = PostgresMessageRepository(pg_engine)
    app_a = FastAPI()
    mount_p1_ingestion(app_a, repository_provider=lambda: repo, tenant_provider=lambda: DevelopmentContext(tenant_id="synthetic_tenant_a"))
    client_a = TestClient(app_a)

    app_b = FastAPI()
    mount_p1_ingestion(app_b, repository_provider=lambda: repo, tenant_provider=lambda: DevelopmentContext(tenant_id="synthetic_tenant_b"))
    client_b = TestClient(app_b)

    # Ingest message in tenant A
    envelope = {
        "tenant_id": "synthetic_tenant_a",
        "channel": "WHATSAPP",
        "provider_message_id": f"msg_iso_{uuid4().hex[:8]}",
        "sender_identity_id": "+60123456789",
        "sender_alias": "Burger King Procurement",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "business_timezone": "Asia/Kuala_Lumpur",
        "text": "Please send 40 burgers for ORD-1001",
        "attachments": [],
    }
    resp = client_a.post("/v1/messages/ingest", json=envelope)
    msg_id = resp.json()["message"]["message_id"]
    ctx = client_a.post(f"/v1/contexts/from-message/{msg_id}").json()
    ctx_id = ctx["context_id"]

    # In client A, context exists
    assert client_a.get(f"/v1/contexts/{ctx_id}").status_code == 200

    # In client B, context returns 404 (does not exist in tenant B)
    assert client_b.get(f"/v1/contexts/{ctx_id}").status_code == 404
    assert client_b.get("/v1/contexts/by-order/ORD-1001").status_code == 404

    # In client B, cannot review tenant A's context
    resp = client_b.post(
        f"/v1/contexts/{ctx_id}/review",
        json={"expected_context_version": 1, "action": "ACCEPT_EXTRACTION"},
    )
    assert resp.status_code == 404


def test_publish_context_to_core_ineligible(api_client):
    envelope = {
        "tenant_id": "synthetic_tenant_a",
        "channel": "WHATSAPP",
        "provider_message_id": f"msg_pub_inelig_{uuid4().hex[:8]}",
        "sender_identity_id": "+60199999999",  # unverified sender
        "sender_alias": "Unknown Sender",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "business_timezone": "Asia/Kuala_Lumpur",
        "text": "Hello I might want some items later",
        "attachments": [],
    }
    resp = api_client.post("/v1/messages/ingest", json=envelope)
    assert resp.status_code == 201
    msg_id = resp.json()["message"]["message_id"]

    ctx = api_client.post(f"/v1/contexts/from-message/{msg_id}").json()
    ctx_id = ctx["context_id"]

    # Calling publish on unverified / incomplete context returns 422
    pub_resp = api_client.post(f"/v1/contexts/{ctx_id}/publish")
    assert pub_resp.status_code == 422
    detail = pub_resp.json()["detail"]
    assert "ineligible for Core publication" in detail["message"]
    assert len(detail["reasons"]) > 0


def test_publish_context_to_core_success(api_client):
    envelope = {
        "tenant_id": "synthetic_tenant_a",
        "channel": "WHATSAPP",
        "provider_message_id": f"msg_pub_succ_{uuid4().hex[:8]}",
        "sender_identity_id": "+60123456789",  # cust_bk verified
        "sender_alias": "Burger King Procurement",
        "received_at": datetime.now(timezone.utc).isoformat(),
        "business_timezone": "Asia/Kuala_Lumpur",
        "text": "Please send 50 pcs burgers tomorrow before 3pm for ORD-1001",
        "attachments": [],
    }
    resp = api_client.post("/v1/messages/ingest", json=envelope)
    assert resp.status_code == 201
    msg_id = resp.json()["message"]["message_id"]

    ctx = api_client.post(f"/v1/contexts/from-message/{msg_id}").json()
    ctx_id = ctx["context_id"]
    assert ctx["status"] == "INFORMATION_READY"
    assert ctx["customer_identity_status"] == "LINK_VERIFIED"

    # Publish to Core
    pub_resp = api_client.post(
        f"/v1/contexts/{ctx_id}/publish",
        headers={"X-Actor-ID": "usr_mgr", "X-Actor-Role": "MANAGER"},
    )
    assert pub_resp.status_code == 200
    published_ctx = pub_resp.json()
    assert published_ctx["core_commitment_id"] is not None
    assert published_ctx["core_commitment_id"].startswith("com_")
    assert published_ctx["published_to_core_at"] is not None


