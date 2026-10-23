from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.context.order_context_schemas import OrderContextRecord, OrderContextVersionRecord
from app.context.postgres_repository import (
    ContextReview,
    MessageAssociation,
    OrderContext,
    OrderContextVersion,
    PostgresMessageRepository,
)
from app.context.schemas import RawMessageEnvelope


def test_source_snapshot_is_read_only_and_tenant_scoped(pg_engine):
    now = datetime(2026, 10, 24, 8, tzinfo=UTC)
    repository = PostgresMessageRepository(pg_engine)
    message = repository.ingest(
        RawMessageEnvelope(
            tenant_id="tenant_snapshot_a",
            channel="WHATSAPP",
            provider_message_id="snapshot_provider_1",
            sender_identity_id="sender_1",
            sender_alias="Buyer",
            received_at=now,
            text="Please prepare the order.",
            adapter_mode="SYNTHETIC",
        ),
        now,
    ).message
    context = OrderContextRecord(
        context_id="context_snapshot_1",
        tenant_id="tenant_snapshot_a",
        customer_id="customer_snapshot_1",
        customer_identity_status="UNVERIFIED",
        status="UNRESOLVED",
        context_version=1,
        source_message_ids=[message.message_id],
        created_at=now,
        updated_at=now,
    )
    version = OrderContextVersionRecord(
        version_id="context_snapshot_version_1",
        context_id=context.context_id,
        tenant_id=context.tenant_id,
        context_version=1,
        snapshot=context.model_dump(mode="json"),
        change_type="INITIAL_CREATION",
        created_at=now,
    )
    with Session(pg_engine) as session, session.begin():
        session.add(
            OrderContext(
                context_id=context.context_id,
                tenant_id=context.tenant_id,
                order_id=None,
                customer_id=context.customer_id,
                customer_identity_status=context.customer_identity_status,
                status=context.status,
                context_version=context.context_version,
                requested_items=[],
                requested_delivery_at=None,
                delivery_qualifier=None,
                special_instructions=None,
                source_message_ids=context.source_message_ids,
                field_evidence={},
                missing_fields=[],
                conflicts=[],
                last_reviewed_by=None,
                last_reviewed_role=None,
                last_reviewed_at=None,
                core_commitment_id=None,
                published_to_core_at=None,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            OrderContextVersion(
                version_id=version.version_id,
                context_id=version.context_id,
                tenant_id=version.tenant_id,
                context_version=version.context_version,
                snapshot=version.snapshot,
                change_type=version.change_type,
                actor_id=None,
                actor_role=None,
                reason=None,
                created_at=now,
            )
        )
        session.add(
            MessageAssociation(
                association_id="association_snapshot_1",
                tenant_id=context.tenant_id,
                message_id=message.message_id,
                status="UNVERIFIED",
                verified_customer=None,
                verified_order=None,
                candidates=[],
                conflicts=[],
                last_decision=None,
                version=1,
                updated_at=now,
            )
        )

    snapshot = repository.read_order_context_source(context.tenant_id, context.context_id)

    assert snapshot is not None
    assert snapshot.context == context
    assert tuple(row.version_id for row in snapshot.context_versions) == (version.version_id,)
    assert snapshot.source_messages == (message,)
    assert len(snapshot.associations) == 1
    assert snapshot.context_reviews == ()
    assert snapshot.extraction_attempts == ()
    assert repository.read_order_context_source("tenant_snapshot_b", context.context_id) is None
    assert repository.get_order_context(context.tenant_id, context.context_id) == context
