from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.dependencies import RequestContext
from app.core.events import CoreEventType, OutboxStatus
from app.core.models import CommitmentRecord, OutboxEventRecord, ProcessedEventRecord
from app.core.outbox import OutboxDispatcher
from app.core.schemas import AgreementState, FeasibilityState
from app.db.base import Base
from app.context.core_publisher import CoreContextPublisher
from app.context.order_context_schemas import OrderContextRecord, RequestedItem
from app.context.p2_consumer import (
    P2FeasibilityConsumer,
    register_p2_subscribers,
    resolve_snapshot_for_commitment,
)
from app.context.postgres_repository import PostgresMessageRepository


def make_valid_context(tenant_id: str, context_id: str, order_id: str = "ORD-P2-001") -> OrderContextRecord:
    now = datetime.now(timezone.utc)
    return OrderContextRecord(
        context_id=context_id,
        tenant_id=tenant_id,
        order_id=order_id,
        customer_id="cust_retail_001",
        customer_identity_status="LINK_VERIFIED",
        status="INFORMATION_READY",
        context_version=1,
        requested_items=[RequestedItem(sku="BURGER", quantity="100", unit="pcs")],
        requested_delivery_at=now,
        delivery_qualifier="DEADLINE",
        special_instructions="Deliver on time",
        source_message_ids=["msg_001"],
        field_evidence={"sku": [{"evidence_id": "ev_synthetic_terms_fixture", "quote": "BURGER", "start": 0, "end": 6, "method": "RULE"}]},
        missing_fields=[],
        conflicts=[],
        created_at=now,
        updated_at=now,
    )


def test_register_p2_subscribers():
    dispatcher = OutboxDispatcher()
    register_p2_subscribers(dispatcher)
    subscribers_ready = dispatcher.get_subscribers(CoreEventType.COMMITMENT_CONTEXT_READY.value)
    assert any(name == "p2_feasibility_evaluator" for name, _ in subscribers_ready)
    subscribers_prop = dispatcher.get_subscribers(CoreEventType.COMMITMENT_PROPOSAL_OFFERED.value)
    assert any(name == "p2_proposal_evaluator" for name, _ in subscribers_prop)


def test_p2_consumer_evaluates_published_context(pg_engine):
    """P1 publishes context -> Outbox event emitted -> Dispatcher runs P2 consumer -> Feasibility assessed."""
    with pg_engine.begin() as conn:
        Base.metadata.create_all(conn)

    repo = PostgresMessageRepository(pg_engine)
    tenant_id = "tenant_test_p2_e2e"
    ctx_id = f"ctx_{uuid4().hex[:12]}"
    order_id = f"ord_{uuid4().hex[:8]}"

    ctx = make_valid_context(tenant_id, ctx_id, order_id)
    saved = repo.save_order_context(ctx, change_type="INITIAL_CREATION", actor_id="usr_01", actor_role="OPERATOR")

    publisher = CoreContextPublisher()
    req_context = RequestContext(
        tenant_id=tenant_id,
        actor_id="usr_01",
        actor_role="OPERATOR",
        correlation_id=f"corr_{uuid4().hex[:8]}",
        causation_id=ctx_id,
    )

    # 1. Publish context to Core (initially REQUESTED, feasibility NOT_ASSESSED)
    with Session(pg_engine) as session:
        commitment = publisher.publish_to_core(session, req_context, saved)
        assert commitment.commitment_id.startswith("com_")
        assert commitment.feasibility_state == FeasibilityState.NOT_ASSESSED

        # Advance to CONFIRMED to authorize operational P2 feasibility evaluation (Invariant 1)
        row = session.get(CommitmentRecord, (tenant_id, commitment.commitment_id))
        assert row is not None
        row.agreement_state = AgreementState.CONFIRMED.value
        session.commit()

    # 2. Check pending outbox events
    with Session(pg_engine) as session:
        events = session.scalars(
            select(OutboxEventRecord).where(
                OutboxEventRecord.tenant_id == tenant_id,
                OutboxEventRecord.commitment_id == commitment.commitment_id,
                OutboxEventRecord.event_type == CoreEventType.COMMITMENT_CONTEXT_READY.value,
            )
        ).all()
        assert len(events) >= 1
        assert events[0].status == OutboxStatus.PENDING.value

    # 3. Setup dispatcher and run outbox batch
    dispatcher = OutboxDispatcher()
    register_p2_subscribers(dispatcher)

    target_event_id = events[0].event_id
    with Session(pg_engine) as session:
        result = dispatcher.process_outbox_batch(session, batch_size=200)
        assert result.processed_count >= 1
        ev = session.get(OutboxEventRecord, target_event_id)
        assert ev is not None
        assert ev.status == OutboxStatus.PUBLISHED.value

    # 4. Verify P2 feasibility assessment was written back to Core commitment
    with Session(pg_engine) as session:
        record = session.get(CommitmentRecord, (tenant_id, commitment.commitment_id))
        assert record is not None
        assert record.feasibility_state in (
            FeasibilityState.FEASIBLE.value,
            FeasibilityState.INFEASIBLE.value,
            FeasibilityState.CONDITIONAL.value,
            FeasibilityState.UNKNOWN.value,
        )
        assert record.feasibility_state != FeasibilityState.NOT_ASSESSED.value

        # Verify idempotency entry was created in processed_events
        processed = session.scalars(
            select(ProcessedEventRecord).where(
                ProcessedEventRecord.tenant_id == tenant_id,
                ProcessedEventRecord.consumer_name == "p2_feasibility_evaluator",
            )
        ).all()
        assert len(processed) >= 1


def test_p2_consumer_idempotency_prevents_duplicate_evaluation(pg_engine):
    """Re-processing the same outbox event skips execution without redundant state transition."""
    with pg_engine.begin() as conn:
        Base.metadata.create_all(conn)

    repo = PostgresMessageRepository(pg_engine)
    tenant_id = "tenant_test_p2_idem"
    ctx_id = f"ctx_{uuid4().hex[:12]}"
    order_id = f"ord_{uuid4().hex[:8]}"

    ctx = make_valid_context(tenant_id, ctx_id, order_id)
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

    dispatcher = OutboxDispatcher()
    register_p2_subscribers(dispatcher)

    with Session(pg_engine) as session:
        first_run = dispatcher.process_outbox_batch(session, batch_size=500)
        assert first_run.processed_count >= 1

    # Second check: event is marked PUBLISHED, and re-invoking consumer on this event is skipped via idempotency table
    with Session(pg_engine) as session:
        ev = session.scalar(
            select(OutboxEventRecord).where(
                OutboxEventRecord.tenant_id == tenant_id,
                OutboxEventRecord.commitment_id == commitment.commitment_id,
                OutboxEventRecord.event_type == CoreEventType.COMMITMENT_CONTEXT_READY.value,
            )
        )
        assert ev is not None
        assert ev.status == OutboxStatus.PUBLISHED.value

        from app.core.outbox import to_domain_event
        domain_evt = to_domain_event(ev)
        consumer = P2FeasibilityConsumer()
        executed = dispatcher.execute_consumer(
            session, domain_evt, "p2_feasibility_evaluator", consumer.handle_context_ready
        )
        assert executed is False  # Idempotently skipped!
