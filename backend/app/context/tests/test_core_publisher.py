from datetime import datetime, timezone, time
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.schemas import AgreementState, ContextStatus, CustomerIdentityStatus
from app.context.core_publisher import CoreContextPublisher, IneligibleContextError
from app.context.order_context_schemas import OrderContextRecord, RequestedItem
from app.context.postgres_repository import PostgresMessageRepository


def make_valid_context(tenant_id: str, context_id: str, order_id: str = "ORD-TEST-001") -> OrderContextRecord:
    now = datetime.now(timezone.utc)
    return OrderContextRecord(
        context_id=context_id,
        tenant_id=tenant_id,
        order_id=order_id,
        customer_id="cust_retail_001",
        customer_identity_status="LINK_VERIFIED",
        status="INFORMATION_READY",
        context_version=1,
        requested_items=[RequestedItem(sku="SKU_BREAD_01", quantity="100", unit="pcs")],
        requested_delivery_at=now,
        delivery_qualifier="EXACT",
        special_instructions="Deliver to front door",
        source_message_ids=["msg_001"],
        field_evidence={"sku": [{"quote": "SKU_BREAD_01", "start": 0, "end": 12, "method": "RULE"}]},
        missing_fields=[],
        conflicts=[],
        created_at=now,
        updated_at=now,
    )


def test_check_eligibility_success():
    publisher = CoreContextPublisher()
    ctx = make_valid_context("tenant_01", "ctx_01")
    is_eligible, reasons = publisher.check_eligibility(ctx)
    assert is_eligible is True
    assert reasons == []


def test_check_eligibility_ineligible_status():
    publisher = CoreContextPublisher()
    ctx = make_valid_context("tenant_01", "ctx_01")
    ctx.status = "INFORMATION_PARTIAL"
    ctx.missing_fields = ["delivery_address"]
    is_eligible, reasons = publisher.check_eligibility(ctx)
    assert is_eligible is False
    assert any("INFORMATION_PARTIAL" in r for r in reasons)
    assert any("Missing mandatory fields" in r for r in reasons)


def test_check_eligibility_ineligible_identity():
    publisher = CoreContextPublisher()
    ctx = make_valid_context("tenant_01", "ctx_01")
    ctx.customer_identity_status = "LINK_CANDIDATE"
    is_eligible, reasons = publisher.check_eligibility(ctx)
    assert is_eligible is False
    assert any("LINK_CANDIDATE" in r for r in reasons)


def test_check_eligibility_ineligible_conflicts():
    publisher = CoreContextPublisher()
    ctx = make_valid_context("tenant_01", "ctx_01")
    ctx.conflicts = ["Quantity discrepancy between message 1 and 2"]
    is_eligible, reasons = publisher.check_eligibility(ctx)
    assert is_eligible is False
    assert any("Unresolved conflicts" in r for r in reasons)


def test_to_business_context_date_only_normalization():
    publisher = CoreContextPublisher()
    ctx = make_valid_context("tenant_01", "ctx_01")
    # Date-only delivery date at midnight UTC
    ctx.requested_delivery_at = datetime(2026, 10, 25, 0, 0, 0, tzinfo=timezone.utc)
    ctx.delivery_qualifier = "DATE_ONLY"
    ctx.special_instructions = "Handle with care"

    b_ctx = publisher.to_business_context(ctx)
    assert b_ctx.requested_delivery_at is not None
    # Hour normalized to 17:00 operating cutoff
    assert b_ctx.requested_delivery_at.hour == 17
    assert "[DATE_ONLY]" in (b_ctx.special_instructions or "")
    assert "Handle with care" in (b_ctx.special_instructions or "")
    assert b_ctx.customer_identity_status == CustomerIdentityStatus.LINK_VERIFIED
    assert b_ctx.status == ContextStatus.INFORMATION_READY


def test_publish_to_core_ineligible_raises_error():
    publisher = CoreContextPublisher()
    ctx = make_valid_context("tenant_01", "ctx_01")
    ctx.status = "INFORMATION_PARTIAL"
    req_context = RequestContext(
        tenant_id="tenant_01",
        actor_id="usr_01",
        actor_role="OPERATOR",
        correlation_id="corr_test_01",
        causation_id="ctx_01",
    )
    with pytest.raises(IneligibleContextError) as exc_info:
        publisher.publish_to_core(None, req_context, ctx, enforce_eligibility=True)  # type: ignore
    assert "ineligible for Core publication" in str(exc_info.value)


def test_publish_to_core_success_with_db(pg_engine):
    from app.db.base import Base
    with pg_engine.begin() as conn:
        Base.metadata.create_all(conn)

    repo = PostgresMessageRepository(pg_engine)
    tenant_id = "tenant_test_pub"
    ctx_id = f"ctx_{uuid4().hex[:12]}"
    ctx = make_valid_context(tenant_id, ctx_id, "ORD-PUB-001")
    saved = repo.save_order_context(ctx, change_type="INITIAL_CREATION", actor_id="usr_01", actor_role="OPERATOR")

    publisher = CoreContextPublisher()
    req_context = RequestContext(
        tenant_id=tenant_id,
        actor_id="usr_01",
        actor_role="OPERATOR",
        correlation_id=f"corr_{uuid4().hex[:8]}",
        causation_id=ctx_id,
    )

    with Session(pg_engine) as session:
        commitment = publisher.publish_to_core(session, req_context, saved)

    assert commitment.commitment_id.startswith("com_")
    assert commitment.tenant_id == tenant_id
    assert commitment.order_id == "ORD-PUB-001"
    assert commitment.agreement_state == AgreementState.REQUESTED
    assert commitment.terms.sku == "SKU_BREAD_01"
    assert commitment.terms.quantity == Decimal("100")

    # Verify P1 record was updated with core_commitment_id and published_to_core_at
    refetched = repo.get_order_context(tenant_id, ctx_id)
    assert refetched is not None
    assert refetched.core_commitment_id == commitment.commitment_id
    assert refetched.published_to_core_at is not None
