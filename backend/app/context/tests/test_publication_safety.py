from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.context.core_publisher import CoreContextPublisher
from app.context.core_publisher import IneligibleContextError
from app.context.deterministic_extraction import ProductAlias
from app.context.order_context_schemas import ContextReviewRequest
from app.context.postgres_repository import PostgresMessageRepository
from app.context.tests.test_core_publisher import make_valid_context
from app.core.dependencies import RequestContext
from app.core.models import CommitmentRecord, AuditEventRecord, CommitmentProposalRecord
from app.core.schemas import AgreementState


def test_identical_published_version_replays_without_core_version_or_audit_bump(pg_engine):
    repo = PostgresMessageRepository(pg_engine)
    ctx = repo.save_order_context(make_valid_context('audit-tenant', 'audit-context'))
    request = RequestContext('audit-tenant', 'user_staff_01', 'STAFF', 'audit-correlation')
    publisher = CoreContextPublisher()
    with Session(pg_engine) as session:
        first = publisher.publish_to_core(session, request, ctx)
    with Session(pg_engine) as session:
        before = session.scalar(select(func.count()).select_from(AuditEventRecord))
        again = publisher.publish_to_core(session, request, repo.get_order_context('audit-tenant','audit-context'))
        after = session.scalar(select(func.count()).select_from(AuditEventRecord))
        assert again.commitment_id == first.commitment_id
        assert again.commitment_version == first.commitment_version
        assert before == after


def test_failure_after_core_flush_rolls_back_core_and_p1_pointer(pg_engine, monkeypatch):
    repo = PostgresMessageRepository(pg_engine)
    ctx = repo.save_order_context(make_valid_context('rollback-tenant', 'rollback-context'))
    publisher = CoreContextPublisher()
    original = publisher.facade.handle_context_updated
    def fail(*args, **kwargs):
        assert kwargs['commit'] is False
        original(*args, **kwargs)
        raise RuntimeError('injected after flush')
    monkeypatch.setattr(publisher.facade, 'handle_context_updated', fail)
    with pytest.raises(RuntimeError), Session(pg_engine) as session:
        publisher.publish_to_core(session, RequestContext('rollback-tenant','user_staff_01','STAFF','rollback'), ctx)
    assert repo.get_order_context('rollback-tenant','rollback-context').core_commitment_id is None
    with Session(pg_engine) as session:
        assert session.scalar(select(func.count()).select_from(CommitmentRecord)) == 0


def test_generated_order_reference_cannot_bypass_confirmed_terms_guard(pg_engine):
    repo = PostgresMessageRepository(pg_engine, catalog=(ProductAlias('generated-order-tenant', 'SKU_BREAD_01', ('bread',), 'pcs'), ProductAlias('generated-order-tenant', 'BURGER', ('burger',), 'pcs')))
    ctx = make_valid_context('generated-order-tenant', 'generated-order-context')
    ctx.order_id = None
    saved = repo.save_order_context(ctx)
    request = RequestContext(ctx.tenant_id, 'user_staff_01', 'STAFF', 'generated-order')
    publisher = CoreContextPublisher()
    with Session(pg_engine) as session:
        first = publisher.publish_to_core(session, request, saved)
        row = session.get(CommitmentRecord, (ctx.tenant_id, first.commitment_id))
        row.agreement_state = AgreementState.CONFIRMED.value
        session.commit()
    reviewed = repo.apply_context_review(ctx.tenant_id, ctx.context_id,
        ContextReviewRequest(expected_context_version=1, action='EDIT_FIELD',
            field_edits={'requested_items':[{'sku':'BURGER','quantity':'150','unit':'pcs'}]}), 'user_staff_01','STAFF')
    with Session(pg_engine) as session:
        publisher.publish_to_core(session, request, reviewed)
        row = session.get(CommitmentRecord, (ctx.tenant_id, first.commitment_id))
        assert str(row.terms['quantity']) == '100'
        proposals = session.scalars(select(CommitmentProposalRecord).where(
            CommitmentProposalRecord.tenant_id == ctx.tenant_id,
            CommitmentProposalRecord.commitment_id == first.commitment_id)).all()
        assert len(proposals) == 1
        assert str(proposals[0].revised_terms['quantity']) == '150'
        publisher.publish_to_core(session, request, repo.get_order_context(ctx.tenant_id, ctx.context_id))
        assert session.scalar(select(func.count()).select_from(CommitmentProposalRecord)) == 1


def test_publisher_rejects_cross_tenant_before_any_io():
    context = make_valid_context('tenant-a', 'context-a')
    with pytest.raises(IneligibleContextError, match='Tenant mismatch'):
        CoreContextPublisher().publish_to_core(None, RequestContext('tenant-b','user_staff_01','STAFF','cross'), context)
