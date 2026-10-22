from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.context.core_publisher import CoreContextPublisher
from app.context.postgres_repository import PostgresMessageRepository
from app.context.tests.test_core_publisher import make_valid_context
from app.core.dependencies import RequestContext
from app.core.models import CommitmentRecord, AuditEventRecord


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
