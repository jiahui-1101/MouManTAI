"""Tests for Batch 2: Identity & Order Association models, rules, and database persistence."""

from datetime import datetime, timezone
import pytest

from app.context.association_schemas import (
    AssociationDecisionRequest,
    IdentityLinkStatus,
    MatchType,
)
from app.context.association_service import AssociationService, StaleAssociationVersion
from app.context.customer_directory import SyntheticCustomerDirectory
from app.context.postgres_repository import PostgresMessageRepository
from app.context.repository import AssociationNotFound, MessageNotFound
from app.context.tests.test_postgres_repository import NOW, envelope


@pytest.fixture
def directory():
    return SyntheticCustomerDirectory()


@pytest.fixture
def service(directory):
    return AssociationService(directory)


def test_directory_lookups_and_tenant_isolation(directory):
    # Verified sender in tenant A
    cust_a = directory.find_by_sender("synthetic_tenant_a", "WHATSAPP", "+60123456789")
    assert cust_a is not None
    assert cust_a.customer_id == "cust_bk"

    # Same sender in tenant B is not found (tenant isolation)
    assert directory.find_by_sender("synthetic_tenant_b", "WHATSAPP", "+60123456789") is None

    # Unknown sender
    assert directory.find_by_sender("synthetic_tenant_a", "WHATSAPP", "+60199999999") is None

    # Orders lookup
    order_a = directory.get_order("synthetic_tenant_a", "ORD-1001")
    assert order_a is not None
    assert order_a.customer_id == "cust_bk"

    # Cross tenant order
    assert directory.get_order("synthetic_tenant_b", "ORD-1001") is None

    # Typed contact lookup (P4 outbound support)
    wa_contact = directory.get_contact_for_channel("synthetic_tenant_a", "cust_bk", "MOCK_WHATSAPP")
    assert wa_contact is not None
    assert wa_contact.sender_identity_id == "+60123456789"

    tg_contact = directory.get_contact_for_channel("synthetic_tenant_a", "cust_bk", "MOCK_TELEGRAM")
    assert tg_contact is not None
    assert tg_contact.sender_identity_id == "tg_bk_ops"

    # Cross tenant contact lookup
    assert directory.get_contact_for_channel("synthetic_tenant_b", "cust_bk", "MOCK_WHATSAPP") is None


def test_verified_sender_with_explicit_matching_order(service):
    # Sender +60123456789 is cust_bk who owns ORD-1001
    env = envelope(
        tenant_id="synthetic_tenant_a",
        sender_identity_id="+60123456789",
        text="Please send items for ORD-1001",
    )
    repo = PostgresMessageRepository(None)  # message mock
    msg = repo.ingest.__annotations__  # check type
    from app.context.ingestion_schemas import StoredMessage

    stored_msg = StoredMessage(
        message_id="msg-1",
        raw=env,
        synthetic_provider="SYNTHETIC_WHATSAPP",
        content_sha256="abc",
        processing_status="PROCESSED",
        ingested_at=NOW,
        updated_at=NOW,
    )

    extracted_fields = [{"field_name": "order_id", "value": "ORD-1001"}]
    record = service.evaluate_association(stored_msg, extracted_fields)

    assert record.status == IdentityLinkStatus.LINK_VERIFIED
    assert record.verified_customer is not None
    assert record.verified_customer.customer_id == "cust_bk"
    assert record.verified_order is not None
    assert record.verified_order.order_id == "ORD-1001"
    assert len(record.conflicts) == 0


def test_verified_sender_referencing_another_customers_order_causes_conflict(service):
    # Sender +60123456789 is cust_bk, but references ORD-2001 (owned by cust_mcd)
    env = envelope(
        tenant_id="synthetic_tenant_a",
        sender_identity_id="+60123456789",
        text="Update ORD-2001 please",
    )
    from app.context.ingestion_schemas import StoredMessage

    stored_msg = StoredMessage(
        message_id="msg-2",
        raw=env,
        synthetic_provider="SYNTHETIC_WHATSAPP",
        content_sha256="abc",
        processing_status="PROCESSED",
        ingested_at=NOW,
        updated_at=NOW,
    )

    extracted_fields = [{"field_name": "order_id", "value": "ORD-2001"}]
    record = service.evaluate_association(stored_msg, extracted_fields)

    assert record.status == IdentityLinkStatus.CONFLICT
    assert record.verified_order is None
    assert any("Security Conflict" in c for c in record.conflicts)


def test_verified_sender_with_multiple_orders_requires_manual_selection(service):
    # cust_bk owns ORD-1001 and ORD-1002; no specific order mentioned in message
    env = envelope(
        tenant_id="synthetic_tenant_a",
        sender_identity_id="+60123456789",
        text="Need more burgers",
    )
    from app.context.ingestion_schemas import StoredMessage

    stored_msg = StoredMessage(
        message_id="msg-3",
        raw=env,
        synthetic_provider="SYNTHETIC_WHATSAPP",
        content_sha256="abc",
        processing_status="PROCESSED",
        ingested_at=NOW,
        updated_at=NOW,
    )

    record = service.evaluate_association(stored_msg, extracted_fields=[])

    assert record.status == IdentityLinkStatus.LINK_VERIFIED
    assert record.verified_order is None  # Never arbitrarily choose!
    assert len(record.candidates) == 2
    order_ids = {c.order_id for c in record.candidates}
    assert order_ids == {"ORD-1001", "ORD-1002"}


def test_unverified_sender_with_extracted_order_proposes_candidate_only(service):
    # Stranger (+60199999999) says ORD-1001. Extracted reference alone is NEVER authorization!
    env = envelope(
        tenant_id="synthetic_tenant_a",
        sender_identity_id="+60199999999",
        text="I am paying for ORD-1001",
    )
    from app.context.ingestion_schemas import StoredMessage

    stored_msg = StoredMessage(
        message_id="msg-4",
        raw=env,
        synthetic_provider="SYNTHETIC_WHATSAPP",
        content_sha256="abc",
        processing_status="PROCESSED",
        ingested_at=NOW,
        updated_at=NOW,
    )

    extracted_fields = [{"field_name": "order_id", "value": "ORD-1001"}]
    record = service.evaluate_association(stored_msg, extracted_fields)

    assert record.status == IdentityLinkStatus.LINK_CANDIDATE
    assert record.verified_customer is None
    assert record.verified_order is None
    assert len(record.candidates) == 1
    assert record.candidates[0].order_id == "ORD-1001"
    assert record.candidates[0].customer_id == "cust_bk"
    assert "Manual authorization required" in record.candidates[0].reasons[0]


def test_postgres_association_persistence_and_optimistic_locking(pg_engine):
    repo = PostgresMessageRepository(pg_engine)
    ingested = repo.ingest(
        envelope(tenant_id="synthetic_tenant_a", sender_identity_id="+60123456789", text="ORD-1001"),
        NOW,
    ).message

    svc = AssociationService()
    evaluated = svc.evaluate_association(ingested, [{"field_name": "order_id", "value": "ORD-1001"}])

    # Save to PostgreSQL
    saved = repo.save_association(evaluated)
    assert saved.status == IdentityLinkStatus.LINK_VERIFIED
    assert saved.version == 1

    # Retrieve from PostgreSQL
    retrieved = repo.get_association("synthetic_tenant_a", ingested.message_id)
    assert retrieved is not None
    assert retrieved.association_id == saved.association_id
    assert retrieved.verified_order.order_id == "ORD-1001"

    # Apply manual decision: reject order association
    decision_req = AssociationDecisionRequest(
        decision="REJECTED",
        reason="Customer called in and cancelled association",
        expected_version=1,
    )
    updated = repo.decide_association(
        "synthetic_tenant_a",
        ingested.message_id,
        decision_req,
        actor_id="user_staff_01",
        actor_role="STAFF",
    )
    assert updated.version == 2
    assert updated.status == IdentityLinkStatus.UNVERIFIED
    assert updated.last_decision is not None
    assert updated.last_decision.decision == "REJECTED"
    assert updated.last_decision.actor_id == "user_staff_01"

    # Stale update with version 1 is rejected (optimistic concurrency protection)
    with pytest.raises(StaleAssociationVersion):
        repo.decide_association(
            "synthetic_tenant_a",
            ingested.message_id,
            decision_req,
            actor_id="user_staff_01",
            actor_role="STAFF",
        )

    # Cross-tenant query protection
    with pytest.raises(MessageNotFound):
        repo.get_association("synthetic_tenant_b", ingested.message_id)


def test_api_association_workflow(pg_engine):
    from fastapi.testclient import TestClient
    from app.context.dependencies import development_context, local_repository
    from app.context.dev_app import app
    from app.context.ingestion_schemas import DevelopmentContext

    repo = PostgresMessageRepository(pg_engine)
    app.dependency_overrides[local_repository] = lambda: repo
    app.dependency_overrides[development_context] = lambda: DevelopmentContext(tenant_id="synthetic_tenant_a")

    try:
        with TestClient(app) as client:
            # 1. Ingest message with verified sender
            ingest_payload = envelope(
                tenant_id="synthetic_tenant_a",
                sender_identity_id="+60123456789",
                text="Please ship ORD-1001 today",
            ).model_dump(mode="json")
            ing_res = client.post("/v1/messages/ingest", json=ingest_payload)
            assert ing_res.status_code == 201
            msg_id = ing_res.json()["message"]["message_id"]

            # Process extraction so order_id is extracted
            proc_res = client.post(f"/v1/messages/{msg_id}/process")
            assert proc_res.status_code == 200

            # 2. GET association
            assoc_res = client.get(f"/v1/messages/{msg_id}/association")
            assert assoc_res.status_code == 200
            data = assoc_res.json()
            assert data["status"] == "LINK_VERIFIED"
            assert data["verified_customer"]["customer_id"] == "cust_bk"
            assert data["verified_order"]["order_id"] == "ORD-1001"
            assert data["version"] == 1

            # 3. Apply decision
            dec_payload = {
                "decision": "CONFIRMED",
                "target_customer_id": "cust_bk",
                "target_order_id": "ORD-1001",
                "reason": "Staff confirmed phone number match and invoice",
                "expected_version": 1,
            }
            dec_res = client.post(
                f"/v1/messages/{msg_id}/association",
                json=dec_payload,
                headers={"X-Actor-ID": "staff_01", "X-Actor-Role": "STAFF"},
            )
            assert dec_res.status_code == 200
            dec_data = dec_res.json()
            assert dec_data["version"] == 2
            assert dec_data["last_decision"]["decision"] == "CONFIRMED"
            assert dec_data["last_decision"]["actor_id"] == "staff_01"

            # 4. Stale update is rejected with 409
            stale_res = client.post(
                f"/v1/messages/{msg_id}/association",
                json=dec_payload,  # expected_version is still 1
                headers={"X-Actor-ID": "staff_01", "X-Actor-Role": "STAFF"},
            )
            assert stale_res.status_code == 409

            # 5. Non-existent message returns 404
            missing_res = client.get("/v1/messages/nonexistent-msg/association")
            assert missing_res.status_code == 404
    finally:
        app.dependency_overrides.clear()

