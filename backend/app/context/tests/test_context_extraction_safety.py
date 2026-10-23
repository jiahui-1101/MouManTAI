from datetime import datetime, timezone

import pytest

from app.context.context_service import ContextService
from app.context.core_publisher import CoreContextPublisher, IneligibleContextError
from app.context.postgres_repository import PostgresMessageRepository
from app.context.tests.test_ai_pipeline_integration import make_envelope, NOW
from app.context.tests.test_core_publisher import make_valid_context
from app.context.order_context_schemas import ContextReviewRequest


def test_date_only_is_preserved_in_evidence_without_inventing_midnight(pg_engine):
    repo = PostgresMessageRepository(pg_engine)
    m = repo.ingest(make_envelope('40 pcs burgers tomorrow'), NOW).message
    ctx = ContextService(repo).create_or_update_from_message(m.raw.tenant_id, m.message_id)
    assert ctx.requested_delivery_at is None
    assert ctx.delivery_qualifier == 'DATE_ONLY'
    assert 'requested_delivery_at' in ctx.missing_fields
    assert ctx.field_evidence['requested_delivery_at'][0]['normalized_value'] == '2026-10-23'
    assert ctx.field_evidence['requested_delivery_at'][0]['quote'] == 'tomorrow'


def test_missing_unit_stays_missing_in_context(pg_engine):
    repo = PostgresMessageRepository(pg_engine)
    m = repo.ingest(make_envelope('40 burgers tomorrow before 3pm'), NOW).message
    ctx = ContextService(repo).create_or_update_from_message(m.raw.tenant_id, m.message_id)
    assert not ctx.requested_items
    assert 'requested_items' in ctx.missing_fields


def test_single_unverified_order_candidate_cannot_merge_existing_context(pg_engine):
    repo = PostgresMessageRepository(pg_engine)
    existing = make_valid_context('synthetic_tenant_a', 'ctx-reviewed', 'ORD-1001')
    repo.save_order_context(existing)
    env = make_envelope('40 pcs burgers tomorrow before 3pm for ORD-1001')
    env.sender_identity_id = 'unverified-synthetic-sender'
    m = repo.ingest(env, NOW).message
    ctx = ContextService(repo).create_or_update_from_message(m.raw.tenant_id, m.message_id)
    assert ctx.context_id != existing.context_id
    assert ctx.order_id is None
    assert repo.get_order_context(existing.tenant_id, existing.context_id).context_version == 1


@pytest.mark.parametrize('qualifier', ['EXACT', 'DATE_ONLY', None])
def test_unsupported_shared_delivery_mapping_blocks_without_reinterpretation(qualifier):
    ctx = make_valid_context('synthetic_tenant_a', 'ctx-guard')
    ctx.delivery_qualifier = qualifier
    original = ctx.model_dump()
    with pytest.raises(IneligibleContextError):
        CoreContextPublisher().to_business_context(ctx)
    assert ctx.model_dump() == original


def test_missing_evidence_never_gets_fabricated_core_refs():
    ctx = make_valid_context('synthetic_tenant_a', 'ctx-guard')
    ctx.field_evidence = {}
    assert not CoreContextPublisher().check_eligibility(ctx)[0]


def test_reopening_unlinked_message_preserves_review_and_context_version(pg_engine):
    repo = PostgresMessageRepository(pg_engine)
    m = repo.ingest(make_envelope('40 pcs burgers tomorrow before 3pm'), NOW).message
    service = ContextService(repo)
    original = service.create_or_update_from_message(m.raw.tenant_id, m.message_id)
    reviewed = repo.apply_context_review(m.raw.tenant_id, original.context_id,
        ContextReviewRequest(expected_context_version=1, action='EDIT_FIELD',
            field_edits={'requested_items': [{'sku':'BURGER','quantity':'45','unit':'pcs'}]}, note='Explicit synthetic correction'),
        'user_staff_01', 'STAFF')
    repo.process(m.raw.tenant_id, m.message_id, reprocess=True)
    reopened = service.create_or_update_from_message(m.raw.tenant_id, m.message_id)
    assert reopened.context_id == reviewed.context_id
    assert reopened.context_version == 2
    assert reopened.requested_items[0].quantity == '45'
    assert len(repo.list_context_versions(m.raw.tenant_id, original.context_id)) == 2


def test_ambiguous_followup_cannot_silently_leave_context_ready(pg_engine):
    repo = PostgresMessageRepository(pg_engine)
    service = ContextService(repo)
    env = make_envelope('40 pcs burgers tomorrow before 3pm for ORD-1001')
    env.sender_identity_id = '+60123456789'
    first = repo.ingest(env, NOW).message
    ctx = service.create_or_update_from_message(first.raw.tenant_id, first.message_id)
    env2 = make_envelope('40 or 50 burgers for ORD-1001')
    env2.sender_identity_id = '+60123456789'
    second = repo.ingest(env2, NOW).message
    updated = service.create_or_update_from_message(second.raw.tenant_id, second.message_id)
    assert updated.context_id == ctx.context_id
    assert updated.status == 'CONFLICT'
    assert updated.requested_items[0].quantity == '40'
    assert any('requires review' in c for c in updated.conflicts)


def test_conversational_followup_merges_missing_unit_without_creating_second_order(pg_engine):
    repo = PostgresMessageRepository(pg_engine)
    service = ContextService(repo)

    # Message 1: Product and quantity provided, unit is missing
    env1 = make_envelope('Can I get 50 burgers tomorrow before 3pm?')
    env1.sender_identity_id = '+60123456789'
    msg1 = repo.ingest(env1, NOW).message
    ctx1 = service.create_or_update_from_message(msg1.raw.tenant_id, msg1.message_id)

    assert ctx1.status == 'INFORMATION_PARTIAL'
    assert not ctx1.requested_items
    assert 'unit' in ctx1.missing_fields or 'requested_items' in ctx1.missing_fields
    assert ctx1.field_evidence['sku'][0]['normalized_value'] == 'BURGER'
    assert ctx1.field_evidence['quantity'][0]['normalized_value'] == '50'
    assert ctx1.context_version == 1

    # Message 2: Follow-up clarifies unit and repeats quantity without repeating SKU
    env2 = make_envelope('50 pcs please')
    env2.sender_identity_id = '+60123456789'
    msg2 = repo.ingest(env2, NOW).message
    ctx2 = service.create_or_update_from_message(msg2.raw.tenant_id, msg2.message_id)

    # Context continuity: Must update the existing context, never create a separate second OrderContext
    assert ctx2.context_id == ctx1.context_id
    assert ctx2.context_version == 2
    assert len(ctx2.requested_items) == 1
    assert ctx2.requested_items[0].sku == 'BURGER'
    assert ctx2.requested_items[0].quantity == '50'
    assert ctx2.requested_items[0].unit == 'pcs'
    assert 'unit' not in ctx2.missing_fields
    assert 'requested_items' not in ctx2.missing_fields
    assert ctx2.status == 'INFORMATION_READY'
    assert ctx2.source_message_ids == [msg1.message_id, msg2.message_id]

    # Verify Core eligibility gate: ctx1 is blocked, ctx2 is eligible
    publisher = CoreContextPublisher()
    eligible1, reasons1 = publisher.check_eligibility(ctx1)
    assert not eligible1
    assert any("not INFORMATION_READY" in r for r in reasons1)

    eligible2, reasons2 = publisher.check_eligibility(ctx2)
    assert eligible2
    assert reasons2 == []

    # Verify database persistence: exactly 1 OrderContext exists, zero duplicate orders created
    by_msg1 = repo.get_order_context_by_message(msg1.raw.tenant_id, msg1.message_id)
    by_msg2 = repo.get_order_context_by_message(msg2.raw.tenant_id, msg2.message_id)
    assert by_msg1 is not None and by_msg2 is not None
    assert by_msg1.context_id == by_msg2.context_id == ctx1.context_id
    assert by_msg2.context_version == 2
    versions = repo.list_context_versions(msg1.raw.tenant_id, ctx1.context_id)
    assert len(versions) == 2


def test_conversational_followup_unit_only_recovers_sku_and_quantity(pg_engine):
    repo = PostgresMessageRepository(pg_engine)
    service = ContextService(repo)

    # Message 1: 50 burgers tomorrow 3pm
    env1 = make_envelope('Can I get 50 burgers tomorrow before 3pm?')
    env1.sender_identity_id = '+60123456789'
    msg1 = repo.ingest(env1, NOW).message
    ctx1 = service.create_or_update_from_message(msg1.raw.tenant_id, msg1.message_id)
    assert not ctx1.requested_items

    # Message 2: Customer responds with unit only ("pcs please")
    env2 = make_envelope('pcs please')
    env2.sender_identity_id = '+60123456789'
    msg2 = repo.ingest(env2, NOW).message
    ctx2 = service.create_or_update_from_message(msg2.raw.tenant_id, msg2.message_id)

    # Verifies cross-message item assembly recovers SKU and Quantity from Message 1
    assert ctx2.context_id == ctx1.context_id
    assert ctx2.context_version == 2
    assert len(ctx2.requested_items) == 1
    assert ctx2.requested_items[0].sku == 'BURGER'
    assert ctx2.requested_items[0].quantity == '50'
    assert ctx2.requested_items[0].unit == 'pcs'
    assert ctx2.status == 'INFORMATION_READY'
