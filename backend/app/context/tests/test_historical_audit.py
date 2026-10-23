from app.context.experiments.audit_historical import audit
from app.context.postgres_repository import PostgresMessageRepository
from app.context.tests.test_deterministic_extraction import stored


def test_read_only_audit_is_tenant_scoped_and_does_not_process_messages(pg_engine):
    repo = PostgresMessageRepository(pg_engine)
    raw = stored('Need 40 pcs burgers tomorrow').raw
    original = repo.ingest(raw, raw.received_at).message
    other = raw.model_copy(deep=True)
    other.tenant_id = 'other_tenant'
    repo.ingest(other, other.received_at)
    result = audit(pg_engine, raw.tenant_id)
    assert result['read_only_transaction'] and result['accessible_messages'] == 1
    assert result['model_calls'] == 0
    assert result['messages'][0]['historical_attempts'] == []
    assert repo.get(raw.tenant_id, original.message_id) == original
