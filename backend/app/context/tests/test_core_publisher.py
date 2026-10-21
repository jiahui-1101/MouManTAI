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


def test_publish_confirmed_commitment_amendment_becomes_proposal(pg_engine):
    """When a commitment is already CONFIRMED, publishing an amended context creates a proposal."""
    from app.core.models import CommitmentProposalRecord, CommitmentRecord, OutboxEventRecord
    from app.core.events import CoreEventType
    from app.db.base import Base
    from sqlalchemy import select

    with pg_engine.begin() as conn:
        Base.metadata.create_all(conn)

    repo = PostgresMessageRepository(pg_engine)
    tenant_id = "tenant_test_amend"
    order_id = "ORD-CONFIRMED-001"
    ctx_id_1 = f"ctx_{uuid4().hex[:12]}"

    # 1. First context: 100 pcs
    ctx_1 = make_valid_context(tenant_id, ctx_id_1, order_id)
    saved_1 = repo.save_order_context(ctx_1, change_type="INITIAL_CREATION", actor_id="usr_01", actor_role="OPERATOR")

    publisher = CoreContextPublisher()
    req_context = RequestContext(
        tenant_id=tenant_id,
        actor_id="usr_01",
        actor_role="MANAGER",
        correlation_id=f"corr_{uuid4().hex[:8]}",
        causation_id=ctx_id_1,
    )

    with Session(pg_engine) as session:
        com_1 = publisher.publish_to_core(session, req_context, saved_1)
        # Advance commitment to CONFIRMED
        row = session.get(CommitmentRecord, (tenant_id, com_1.commitment_id))
        assert row is not None
        row.agreement_state = AgreementState.CONFIRMED.value
        session.commit()

    # 2. Follow-up context: customer requests amendment to 150 pcs
    ctx_id_2 = f"ctx_{uuid4().hex[:12]}"
    ctx_2 = make_valid_context(tenant_id, ctx_id_2, order_id)
    ctx_2.requested_items = [RequestedItem(sku="SKU_BREAD_01", quantity="150", unit="pcs")]
    saved_2 = repo.save_order_context(ctx_2, change_type="INITIAL_CREATION", actor_id="usr_01", actor_role="OPERATOR")

    req_context_2 = RequestContext(
        tenant_id=tenant_id,
        actor_id="usr_01",
        actor_role="OPERATOR",
        correlation_id=f"corr_{uuid4().hex[:8]}",
        causation_id=ctx_id_2,
    )

    with Session(pg_engine) as session:
        updated_com = publisher.publish_to_core(session, req_context_2, saved_2)

        # Invariant: Agreement state is OFFERED (proposal created)
        assert updated_com.agreement_state == AgreementState.OFFERED

        # Verify proposal record created in DB
        proposals = session.scalars(
            select(CommitmentProposalRecord).where(
                CommitmentProposalRecord.tenant_id == tenant_id,
                CommitmentProposalRecord.commitment_id == com_1.commitment_id,
            )
        ).all()
        assert len(proposals) >= 1
        active_prop = next(p for p in proposals if p.status == "ACTIVE")
        assert active_prop.revised_terms is not None
        assert str(active_prop.revised_terms["quantity"]) == "150"

        # Verify outbox event emitted for proposal
        outbox_events = session.scalars(
            select(OutboxEventRecord).where(
                OutboxEventRecord.tenant_id == tenant_id,
                OutboxEventRecord.commitment_id == com_1.commitment_id,
                OutboxEventRecord.event_type == CoreEventType.COMMITMENT_PROPOSAL_OFFERED.value,
            )
        ).all()
        assert len(outbox_events) >= 1
