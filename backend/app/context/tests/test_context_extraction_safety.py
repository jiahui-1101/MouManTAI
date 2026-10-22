from datetime import datetime, timezone

import pytest

from app.context.context_service import ContextService
from app.context.core_publisher import CoreContextPublisher, IneligibleContextError
from app.context.postgres_repository import PostgresMessageRepository
from app.context.tests.test_ai_pipeline_integration import make_envelope, NOW
from app.context.tests.test_core_publisher import make_valid_context


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
