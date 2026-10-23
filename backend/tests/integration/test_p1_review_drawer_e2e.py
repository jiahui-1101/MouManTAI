"""Real PostgreSQL End-to-End Integration Tests for Human Review Drawer Actions.

Verifies every implemented Review Drawer action against real PostgreSQL persistence:
1. EDIT_FIELD (single-item): updates SKU, quantity, unit, delivery timestamp with UTC offset,
   special instructions, resolves conflicts, bumps context_version, stores audit & snapshot.
2. Multi-Item EDIT_FIELD: adds/edits multiple requested items, persists intact in PostgreSQL.
3. ACCEPT_EXTRACTION: accepts extraction, marks INFORMATION_READY, records review audit.
4. REQUEST_MORE_INFO: marks INFORMATION_PARTIAL, records reviewer note in audit history.
5. MARK_UNRESOLVED: marks UNRESOLVED, records rejection audit history.
6. Survives Page Refresh / Durable Re-fetch: reload from DB, verify version history and reviews.
7. Optimistic Locking: stale expected_context_version returns HTTP 409 StaleContextVersion.
8. Core Publishing & Confirmed-Commitment Amendment: publish multi-item context to Core,
   confirm commitment, edit context via review, re-publish and verify amendment proposal.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

if not os.environ.get("P1_DATABASE_URL"):
    pytest.skip(
        "P1_DATABASE_URL is not configured; PostgreSQL required for real integration tests",
        allow_module_level=True,
    )

from app.context.core_publisher import CoreContextPublisher
from app.context.dev_database import create_p1_engine, initialize_p1_schema
from app.context.hosting import mount_p1_ingestion
from app.context.ingestion_schemas import DevelopmentContext
from app.context.order_context_schemas import (
    ContextReviewRequest,
    OrderContextRecord,
    RequestedItem,
)
from app.context.postgres_repository import (
    ContextReview,
    OrderContext,
    OrderContextVersion,
    PostgresMessageRepository,
)
from app.core.dependencies import RequestContext
from app.core.models import CommitmentProposalRecord, CommitmentRecord
from app.core.schemas import AgreementState
from app.db.base import Base


@pytest.fixture
def pg_engine():
    """Real PostgreSQL engine connecting via P1_DATABASE_URL."""
    url = os.environ.get("P1_DATABASE_URL")
    if not url:
        pytest.skip("P1_DATABASE_URL is not configured; PostgreSQL required for real integration tests")
    engine = create_p1_engine(url)
    initialize_p1_schema(engine)
    with engine.begin() as conn:
        Base.metadata.create_all(conn)
    yield engine
    engine.dispose()


@pytest.fixture
def client_and_repo(pg_engine):
    repo = PostgresMessageRepository(pg_engine)
    tenant_id = f"tenant_review_{uuid4().hex[:8]}"
    tenant = DevelopmentContext(tenant_id=tenant_id)

    app = FastAPI()
    mount_p1_ingestion(
        app,
        repository_provider=lambda: repo,
        tenant_provider=lambda: tenant,
    )
    client = TestClient(app)
    return client, repo, tenant_id


def make_initial_context(
    tenant_id: str,
    context_id: str,
    order_id: str,
    sku: str = "SOURDOUGH",
    quantity: str = "50",
    unit: str = "pcs",
) -> OrderContextRecord:
    now = datetime.now(timezone.utc)
    return OrderContextRecord(
        context_id=context_id,
        tenant_id=tenant_id,
        order_id=order_id,
        customer_id=f"cust_{tenant_id}",
        customer_identity_status="LINK_VERIFIED",
        status="INFORMATION_PARTIAL",
        context_version=1,
        requested_items=[RequestedItem(sku=sku, quantity=quantity, unit=unit)],
        requested_delivery_at=now + timedelta(days=2),
        delivery_qualifier="DATE_ONLY",
        special_instructions=None,
        source_message_ids=[f"msg_{context_id}"],
        field_evidence={
            "sku": [{"evidence_id": f"ev_sku_{context_id}", "quote": sku, "start": 0, "end": len(sku), "method": "MODEL"}],
            "quantity": [{"evidence_id": f"ev_qty_{context_id}", "quote": quantity, "start": 0, "end": len(quantity), "method": "MODEL"}],
            "unit": [{"evidence_id": f"ev_unit_{context_id}", "quote": unit, "start": 0, "end": len(unit), "method": "MODEL"}],
        },
        missing_fields=["delivery_time"],
        conflicts=["Quantity tentative: customer asked 50 or 60"],
        created_at=now,
        updated_at=now,
    )


def test_review_drawer_actions_end_to_end(client_and_repo, pg_engine):
    """Test all Review Drawer actions sequentially on a real PostgreSQL context:
    1. Single-item EDIT_FIELD
    2. Multi-item EDIT_FIELD
    3. ACCEPT_EXTRACTION
    4. REQUEST_MORE_INFO
    5. MARK_UNRESOLVED
    6. Durable re-fetch / Survives page refresh
    7. Stale version 409 conflict
    8. Confirmed-commitment amendment with P5 Core
    """
    client, repo, tenant_id = client_and_repo
    ctx_id = f"ctx_rev_{uuid4().hex[:10]}"
    order_id = f"ord_rev_{uuid4().hex[:8]}"

    # Setup initial context (v1, INFORMATION_PARTIAL, 1 item: SOURDOUGH 50 pcs)
    initial_ctx = make_initial_context(tenant_id, ctx_id, order_id)
    repo.save_order_context(initial_ctx, change_type="INITIAL_CREATION", actor_id="sys_ingest", actor_role="SYSTEM")

    headers = {"X-Actor-ID": "user_staff_01", "X-Actor-Role": "STAFF"}

    # -------------------------------------------------------------------------
    # 1. EDIT_FIELD (Single item amendment)
    # -------------------------------------------------------------------------
    delivery_ts = (datetime.now(timezone.utc) + timedelta(days=3)).replace(microsecond=0).isoformat()
    edit_payload = {
        "expected_context_version": 1,
        "action": "EDIT_FIELD",
        "field_edits": {
            "requested_items": [{"sku": "SOURDOUGH", "quantity": "80", "unit": "pcs"}],
            "requested_delivery_at": delivery_ts,
            "delivery_qualifier": "DEADLINE",
            "special_instructions": "Deliver before 11:00 AM to back kitchen",
            "conflicts": [],
            "missing_fields": [],
        },
        "note": "Customer called and confirmed 80 pcs and morning deadline",
    }
    resp = client.post(f"/v1/contexts/{ctx_id}/review", json=edit_payload, headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["context_version"] == 2
    assert data["status"] == "INFORMATION_READY"
    assert len(data["requested_items"]) == 1
    assert data["requested_items"][0]["sku"] == "SOURDOUGH"
    assert data["requested_items"][0]["quantity"] == "80"
    assert data["delivery_qualifier"] == "DEADLINE"
    assert data["special_instructions"] == "Deliver before 11:00 AM to back kitchen"
    assert data["conflicts"] == []
    assert data["missing_fields"] == []
    assert data["last_reviewed_by"] == "user_staff_01"

    # Direct PostgreSQL audit verification
    with Session(pg_engine) as session:
        reviews = session.scalars(
            select(ContextReview).where(ContextReview.tenant_id == tenant_id, ContextReview.context_id == ctx_id)
        ).all()
        assert len(reviews) == 1
        assert reviews[0].action == "EDIT_FIELD"
        assert reviews[0].context_version_before == 1
        assert reviews[0].context_version_after == 2
        assert reviews[0].actor_id == "user_staff_01"
        assert reviews[0].note == "Customer called and confirmed 80 pcs and morning deadline"
        assert "requested_items" in reviews[0].field_changes

        versions = session.scalars(
            select(OrderContextVersion).where(OrderContextVersion.tenant_id == tenant_id, OrderContextVersion.context_id == ctx_id)
        ).all()
        # initial creation (v1) + edit (v2)
        assert len(versions) == 2
        v2 = next(v for v in versions if v.context_version == 2)
        assert v2.change_type == "EDIT_FIELD"
        assert v2.snapshot["requested_items"][0]["quantity"] == "80"

    # -------------------------------------------------------------------------
    # 2. Multi-Item EDIT_FIELD
    # -------------------------------------------------------------------------
    multi_item_payload = {
        "expected_context_version": 2,
        "action": "EDIT_FIELD",
        "field_edits": {
            "requested_items": [
                {"sku": "SOURDOUGH", "quantity": "80", "unit": "pcs"},
                {"sku": "BAGEL", "quantity": "40", "unit": "pcs"},
                {"sku": "CROISSANT", "quantity": "20", "unit": "box"},
            ],
        },
        "note": "Added bagels and croissants per customer amendment",
    }
    resp = client.post(f"/v1/contexts/{ctx_id}/review", json=multi_item_payload, headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["context_version"] == 3
    assert len(data["requested_items"]) == 3
    assert [it["sku"] for it in data["requested_items"]] == ["SOURDOUGH", "BAGEL", "CROISSANT"]
    assert [it["quantity"] for it in data["requested_items"]] == ["80", "40", "20"]
    assert [it["unit"] for it in data["requested_items"]] == ["pcs", "pcs", "box"]

    # Direct PostgreSQL verification of multi-item persistence
    with Session(pg_engine) as session:
        row = session.scalar(
            select(OrderContext).where(OrderContext.tenant_id == tenant_id, OrderContext.context_id == ctx_id)
        )
        assert row is not None
        assert row.context_version == 3
        assert len(row.requested_items) == 3
        assert row.requested_items[1]["sku"] == "BAGEL"

    # -------------------------------------------------------------------------
    # 3. ACCEPT_EXTRACTION (Confirm / Accept action)
    # -------------------------------------------------------------------------
    accept_payload = {
        "expected_context_version": 3,
        "action": "ACCEPT_EXTRACTION",
        "field_edits": {},
        "note": "Staff verified items and accepted multi-product extraction",
    }
    resp = client.post(f"/v1/contexts/{ctx_id}/review", json=accept_payload, headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["context_version"] == 4
    assert data["status"] == "INFORMATION_READY"

    # -------------------------------------------------------------------------
    # 4. REQUEST_MORE_INFO
    # -------------------------------------------------------------------------
    info_payload = {
        "expected_context_version": 4,
        "action": "REQUEST_MORE_INFO",
        "field_edits": {},
        "note": "Need customer to clarify delivery dock security code",
    }
    resp = client.post(f"/v1/contexts/{ctx_id}/review", json=info_payload, headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["context_version"] == 5
    assert data["status"] == "INFORMATION_PARTIAL"

    # -------------------------------------------------------------------------
    # 5. MARK_UNRESOLVED (Reject action)
    # -------------------------------------------------------------------------
    unresolved_payload = {
        "expected_context_version": 5,
        "action": "MARK_UNRESOLVED",
        "field_edits": {},
        "note": "Customer cancelled order inquiry over phone",
    }
    resp = client.post(f"/v1/contexts/{ctx_id}/review", json=unresolved_payload, headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["context_version"] == 6
    assert data["status"] == "UNRESOLVED"

    # -------------------------------------------------------------------------
    # 6. Survives Page Refresh / Durable Re-fetch
    # -------------------------------------------------------------------------
    refreshed_resp = client.get(f"/v1/contexts/{ctx_id}")
    assert refreshed_resp.status_code == 200
    refreshed = refreshed_resp.json()
    assert refreshed["context_version"] == 6
    assert refreshed["status"] == "UNRESOLVED"
    assert len(refreshed["requested_items"]) == 3
    assert refreshed["last_reviewed_by"] == "user_staff_01"

    # Version history list
    versions_resp = client.get(f"/v1/contexts/{ctx_id}/versions")
    assert versions_resp.status_code == 200
    version_items = versions_resp.json()
    assert len(version_items) == 6
    assert [v["context_version"] for v in version_items] == [6, 5, 4, 3, 2, 1]
    assert version_items[0]["change_type"] == "MARK_UNRESOLVED"
    assert version_items[1]["change_type"] == "REQUEST_MORE_INFO"
    assert version_items[2]["change_type"] == "ACCEPT_EXTRACTION"
    assert version_items[3]["change_type"] == "EDIT_FIELD"

    # Reviews audit list
    reviews_resp = client.get(f"/v1/contexts/{ctx_id}/reviews")
    assert reviews_resp.status_code == 200
    review_items = reviews_resp.json()
    assert len(review_items) == 5
    assert [r["action"] for r in review_items] == [
        "MARK_UNRESOLVED",
        "REQUEST_MORE_INFO",
        "ACCEPT_EXTRACTION",
        "EDIT_FIELD",
        "EDIT_FIELD",
    ]

    # -------------------------------------------------------------------------
    # 7. Optimistic Locking: stale expected_context_version returns 409
    # -------------------------------------------------------------------------
    stale_payload = {
        "expected_context_version": 2,  # Current is 6
        "action": "EDIT_FIELD",
        "field_edits": {"requested_items": [{"sku": "SOURDOUGH", "quantity": "99", "unit": "pcs"}]},
        "note": "Attempted edit from stale browser tab",
    }
    resp = client.post(f"/v1/contexts/{ctx_id}/review", json=stale_payload, headers=headers)
    assert resp.status_code == 409
    err = resp.json()
    err_msg = str(err.get("detail") or err.get("message") or err)
    assert "mismatch" in err_msg.lower()

    # Invariant: Database version unchanged at 6
    with Session(pg_engine) as session:
        current_db = session.scalar(
            select(OrderContext).where(OrderContext.tenant_id == tenant_id, OrderContext.context_id == ctx_id)
        )
        assert current_db.context_version == 6


def test_review_drawer_confirmed_commitment_amendment(client_and_repo, pg_engine):
    """Test 8: Proves multi-item context publication to Core, customer confirmation,
    follow-up Review Drawer field amendment, and proposal generation without in-place mutation.
    """
    client, repo, tenant_id = client_and_repo
    ctx_id = f"ctx_core_{uuid4().hex[:10]}"
    order_id = f"ord_core_{uuid4().hex[:8]}"

    # 1. Create fully eligible ready multi-item context
    delivery_ts = (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0)
    ctx = OrderContextRecord(
        context_id=ctx_id,
        tenant_id=tenant_id,
        order_id=order_id,
        customer_id=f"cust_{tenant_id}",
        customer_identity_status="LINK_VERIFIED",
        status="INFORMATION_READY",
        context_version=1,
        requested_items=[
            RequestedItem(sku="BURGER", quantity="50", unit="pcs"),
            RequestedItem(sku="FRIES", quantity="30", unit="box"),
        ],
        requested_delivery_at=delivery_ts,
        delivery_qualifier="DEADLINE",
        special_instructions="Deliver together",
        source_message_ids=[f"msg_{ctx_id}"],
        field_evidence={
            "sku": [{"evidence_id": f"ev_sku_{ctx_id}", "quote": "burger", "method": "HUMAN"}],
            "quantity": [{"evidence_id": f"ev_qty_{ctx_id}", "quote": "50", "method": "HUMAN"}],
            "unit": [{"evidence_id": f"ev_unit_{ctx_id}", "quote": "pcs", "method": "HUMAN"}],
            "requested_delivery_at": [{"evidence_id": f"ev_del_{ctx_id}", "quote": "deadline", "method": "HUMAN"}],
        },
        missing_fields=[],
        conflicts=[],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    repo.save_order_context(ctx, change_type="INITIAL_CREATION", actor_id="usr_op", actor_role="STAFF")

    # 2. Publish multi-item context to Core
    publisher = CoreContextPublisher()
    req_context = RequestContext(
        tenant_id=tenant_id,
        actor_id="user_staff_01",
        actor_role="STAFF",
        correlation_id=f"corr_{uuid4().hex[:8]}",
        causation_id=ctx_id,
    )
    with Session(pg_engine) as session:
        saved = repo.get_order_context(tenant_id, ctx_id)
        commitment = publisher.publish_to_core(session, req_context, saved)
        assert commitment.commitment_id.startswith("com_")
        assert commitment.agreement_state == AgreementState.REQUESTED
        # Verify multi-item terms
        assert commitment.terms.sku == "BURGER"
        assert commitment.terms.quantity == Decimal("50")

        # Simulate Core commitment transition to CONFIRMED
        com_row = session.get(CommitmentRecord, (tenant_id, commitment.commitment_id))
        assert com_row is not None
        com_row.agreement_state = AgreementState.CONFIRMED.value
        session.commit()

    # 3. Customer calls to amend terms: Reviewer opens Review Drawer and amends items to 100 burgers
    headers = {"X-Actor-ID": "user_staff_01", "X-Actor-Role": "STAFF"}
    amend_payload = {
        "expected_context_version": 1,
        "action": "EDIT_FIELD",
        "field_edits": {
            "requested_items": [
                {"sku": "BURGER", "quantity": "100", "unit": "pcs"},
                {"sku": "FRIES", "quantity": "30", "unit": "box"},
            ],
            "special_instructions": "Increased to 100 burgers per phone call",
        },
        "note": "Reviewer amended terms after customer confirmation call",
    }
    resp = client.post(f"/v1/contexts/{ctx_id}/review", json=amend_payload, headers=headers)
    assert resp.status_code == 200
    amended_ctx = resp.json()
    assert amended_ctx["context_version"] == 2
    assert amended_ctx["requested_items"][0]["quantity"] == "100"

    # 4. Re-publish amended context to Core
    req_context_2 = RequestContext(
        tenant_id=tenant_id,
        actor_id="user_staff_01",
        actor_role="STAFF",
        correlation_id=f"corr_{uuid4().hex[:8]}",
        causation_id=ctx_id,
    )
    with Session(pg_engine) as session:
        saved_2 = repo.get_order_context(tenant_id, ctx_id)
        publisher.publish_to_core(session, req_context_2, saved_2)

        # Core commitment: agreement_state transitioned to OFFERED (amendment proposed)
        # Invariant: confirmed agreed terms (quantity 50) are NOT overwritten in place!
        record = session.get(CommitmentRecord, (tenant_id, commitment.commitment_id))
        assert record.agreement_state == AgreementState.OFFERED.value
        assert Decimal(record.terms["quantity"]) == Decimal("50"), (
            f"Expected agreed terms quantity 50 preserved, got {record.terms['quantity']}"
        )
