from datetime import UTC, datetime

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError
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
from app.context.tests.test_p1_alembic_migration import migrated_database as migrated_database


def _migrated_context(engine):
    now = datetime(2026, 10, 24, 8, tzinfo=UTC)
    repository = PostgresMessageRepository(engine)
    context = repository.save_order_context(
        OrderContextRecord(
            context_id="migrated_snapshot",
            tenant_id="tenant_snapshot_a",
            status="UNRESOLVED",
            context_version=1,
            created_at=now,
            updated_at=now,
        )
    )
    return repository, context


def test_migrated_source_transaction_rejects_writes(migrated_database):
    engine, _ = migrated_database
    repository, context = _migrated_context(engine)
    observed = []
    statements = []

    def probe(connection, cursor, statement, parameters, execution_context, executemany):
        statements.append(statement)
        if statement == "SET TRANSACTION READ ONLY":
            observed.append(
                (
                    connection.exec_driver_sql("SHOW transaction_isolation").scalar_one(),
                    connection.exec_driver_sql("SHOW transaction_read_only").scalar_one(),
                )
            )
            # A savepoint lets the actual repository read continue after PG rejects DML.
            with connection.begin_nested() as savepoint:
                with pytest.raises(DBAPIError) as rejected:
                    connection.execute(text("DELETE FROM p1_dev.order_contexts WHERE false"))
                assert rejected.value.orig.sqlstate == "25006"
                savepoint.rollback()

    event.listen(engine, "after_cursor_execute", probe)
    try:
        snapshot = repository.read_order_context_source(context.tenant_id, context.context_id)
    finally:
        event.remove(engine, "after_cursor_execute", probe)

    assert observed == [("repeatable read", "on")]
    assert snapshot.context == context
    assert repository.get_order_context(context.tenant_id, context.context_id) == context
    # The failed deliberate probe never reaches after_cursor_execute; all successful
    # statements from the reader are transaction controls or queries, never DML.
    assert not any(
        s.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"} for s in statements
    )
    assert repository.read_order_context_source("tenant_snapshot_b", context.context_id) is None


def test_migrated_source_snapshot_survives_concurrent_review(migrated_database):
    from app.context.order_context_schemas import ContextReviewRequest
    from app.orders.p1_source_reader import P1OrderContextSourceReader

    engine, _ = migrated_database
    repository, context = _migrated_context(engine)
    advanced = []

    def advance_after_context_read(
        connection, cursor, statement, parameters, execution_context, executemany
    ):
        if not advanced and statement.lstrip().startswith("SELECT p1_dev.order_contexts."):
            advanced.append(True)
            # A separate connection commits while the reader's snapshot remains open.
            repository.apply_context_review(
                context.tenant_id,
                context.context_id,
                ContextReviewRequest(
                    expected_context_version=1,
                    action="EDIT_FIELD",
                    field_edits={"special_instructions": "Concurrent reviewed update"},
                ),
                "reviewer_snapshot",
                "STAFF",
            )

    event.listen(engine, "after_cursor_execute", advance_after_context_read)
    try:
        before = repository.read_order_context_source(context.tenant_id, context.context_id)
    finally:
        event.remove(engine, "after_cursor_execute", advance_after_context_read)

    assert advanced == [True]
    assert before.context.context_version == 1
    assert [row.context_version for row in before.context_versions] == [1]
    assert before.context_reviews == ()
    after = repository.read_order_context_source(context.tenant_id, context.context_id)
    assert after.context.context_version == 2
    assert [row.context_version for row in after.context_versions] == [2, 1]
    assert after.context_reviews[0].context_version_after == 2

    class TenantScope:
        def current_verified_tenant_id(self):
            return context.tenant_id

    reader = P1OrderContextSourceReader(repository, tenant_scope=TenantScope())
    assert (
        reader.read_candidate(context.context_id, expected_context_version=1).status
        == "STALE_SOURCE"
    )


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
