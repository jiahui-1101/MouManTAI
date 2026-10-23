import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.context.order_context_schemas import (
    ContextReviewRequest,
    OrderContextRecord,
    RequestedItem,
)
from app.context.postgres_repository import PostgresMessageRepository
from app.context.repository import (
    ContextNotFound,
    StaleContextVersion,
)


def make_context(tenant_id: str, context_id: str, order_id: str = "ORD-1001") -> OrderContextRecord:
    now = datetime.now(timezone.utc)
    return OrderContextRecord(
        context_id=context_id,
        tenant_id=tenant_id,
        order_id=order_id,
        customer_id="cust_bk",
        customer_identity_status="LINK_VERIFIED",
        status="INFORMATION_PARTIAL",
        context_version=1,
        requested_items=[RequestedItem(sku="BURGER", quantity="50", unit="pcs")],
        requested_delivery_at=now,
        delivery_qualifier="BEFORE",
        special_instructions="Extra sauce",
        source_message_ids=["msg_001"],
        field_evidence={"sku": [{"start": 0, "end": 6, "quote": "BURGER", "method": "RULE"}]},
        missing_fields=["delivery_address"],
        conflicts=[],
        created_at=now,
        updated_at=now,
    )


def test_order_context_crud(pg_engine):
    repo = PostgresMessageRepository(pg_engine)
    tenant_id = "test_tenant_p1"
    ctx_id = str(uuid4())

    ctx = make_context(tenant_id, ctx_id, "ORD-2001")
    saved = repo.save_order_context(ctx, change_type="INITIAL_CREATION", actor_id="sys", actor_role="SYSTEM")
    assert saved.context_id == ctx_id
    assert saved.context_version == 1
    assert saved.status == "INFORMATION_PARTIAL"
    assert len(saved.requested_items) == 1
    assert saved.requested_items[0].sku == "BURGER"

    # Fetch by context_id
    fetched = repo.get_order_context(tenant_id, ctx_id)
    assert fetched is not None
    assert fetched.order_id == "ORD-2001"
    assert fetched.customer_id == "cust_bk"

    # Fetch by order_id
    by_order = repo.get_order_context_by_order(tenant_id, "ORD-2001")
    assert by_order is not None
    assert by_order.context_id == ctx_id

    # Check version history
    versions = repo.list_context_versions(tenant_id, ctx_id)
    assert len(versions) == 1
    assert versions[0].context_version == 1
    assert versions[0].change_type == "INITIAL_CREATION"
    assert versions[0].actor_id == "sys"


def test_order_context_optimistic_concurrency(pg_engine):
    repo = PostgresMessageRepository(pg_engine)
    tenant_id = "test_tenant_p1"
    ctx_id = str(uuid4())

    ctx = make_context(tenant_id, ctx_id, "ORD-3001")
    repo.save_order_context(ctx)

    # Wrong expected_version should raise StaleContextVersion
    with pytest.raises(StaleContextVersion):
        repo.update_order_context(
            tenant_id=tenant_id,
            context_id=ctx_id,
            expected_version=999,
            updates={"special_instructions": "No pickles"},
        )

    # Correct expected_version should succeed and increment version to 2
    updated = repo.update_order_context(
        tenant_id=tenant_id,
        context_id=ctx_id,
        expected_version=1,
        updates={"special_instructions": "No pickles"},
        actor_id="user_staff_01",
        actor_role="STAFF",
        reason="Customer requested change",
    )
    assert updated.context_version == 2
    assert updated.special_instructions == "No pickles"

    # Verify history now contains 2 versions
    versions = repo.list_context_versions(tenant_id, ctx_id)
    assert len(versions) == 2
    assert versions[0].context_version == 2
    assert versions[0].change_type == "HUMAN_EDIT"
    assert versions[0].snapshot["special_instructions"] == "No pickles"
    assert versions[1].context_version == 1


def test_context_review_workflow(pg_engine):
    from app.context.deterministic_extraction import ProductAlias
    repo = PostgresMessageRepository(pg_engine, catalog=(
        ProductAlias('test_tenant_p1', 'BURGER', ('burger',), 'pcs'),))
    tenant_id = "test_tenant_p1"
    ctx_id = str(uuid4())

    ctx = make_context(tenant_id, ctx_id, "ORD-4001")
    repo.save_order_context(ctx)

    # Apply EDIT_FIELD review
    review_req = ContextReviewRequest(
        expected_context_version=1,
        action="EDIT_FIELD",
        field_edits={
            "requested_items": [{"sku": "BURGER", "quantity": "100", "unit": "pcs"}],
            "special_instructions": "Rush order",
            "missing_fields": [],  # Clear missing fields
        },
        note="Customer increased quantity to 100 and removed missing field block",
    )
    reviewed = repo.apply_context_review(
        tenant_id=tenant_id,
        context_id=ctx_id,
        request=review_req,
        actor_id="supervisor_01",
        actor_role="SUPERVISOR",
    )
    assert reviewed.context_version == 2
    assert reviewed.requested_items[0].quantity == "100"
    assert reviewed.special_instructions == "Rush order"
    assert reviewed.status == "INFORMATION_READY"
    assert reviewed.last_reviewed_by == "supervisor_01"
    assert reviewed.last_reviewed_role == "SUPERVISOR"

    # Verify review audit
    reviews = repo.list_context_reviews(tenant_id, ctx_id)
    assert len(reviews) == 1
    assert reviews[0].action == "EDIT_FIELD"
    assert reviews[0].context_version_before == 1
    assert reviews[0].context_version_after == 2
    assert reviews[0].actor_id == "supervisor_01"
    assert "requested_items" in reviews[0].field_changes
    assert reviews[0].note == "Customer increased quantity to 100 and removed missing field block"

    # Trying to review again with stale version 1 fails
    with pytest.raises(StaleContextVersion):
        repo.apply_context_review(
            tenant_id=tenant_id,
            context_id=ctx_id,
            request=review_req,
            actor_id="supervisor_01",
            actor_role="SUPERVISOR",
        )


def test_order_context_tenant_isolation(pg_engine):
    repo = PostgresMessageRepository(pg_engine)
    ctx_id = str(uuid4())

    ctx = make_context("tenant_alpha", ctx_id, "ORD-5001")
    repo.save_order_context(ctx)

    # In tenant_alpha it exists
    assert repo.get_order_context("tenant_alpha", ctx_id) is not None
    assert repo.get_order_context_by_order("tenant_alpha", "ORD-5001") is not None

    # In tenant_beta it cannot be found
    assert repo.get_order_context("tenant_beta", ctx_id) is None
    assert repo.get_order_context_by_order("tenant_beta", "ORD-5001") is None

    # Reviewing across tenant raises ContextNotFound
    with pytest.raises(ContextNotFound):
        repo.apply_context_review(
            tenant_id="tenant_beta",
            context_id=ctx_id,
            request=ContextReviewRequest(expected_context_version=1, action="ACCEPT_EXTRACTION"),
            actor_id="intruder",
            actor_role="STAFF",
        )
