import json

from app.context.ai.service import ModelProposalService
from app.context.postgres_repository import PostgresMessageRepository
from app.context.tests.test_ai_pipeline_integration import FakeEndpoint, make_envelope, NOW
from app.context.tests.test_persisted_extraction import api
from app.context.tests.test_postgres_repository import envelope


def test_telemetry_records_only_actual_calls_and_completion_time(pg_engine):
    endpoint = FakeEndpoint()
    repo = PostgresMessageRepository(pg_engine, proposal_service=ModelProposalService(endpoint, enabled=True, stages=('qwen',)))
    m = repo.ingest(make_envelope('Need burgers serving 40 guests'), NOW).message
    attempt = repo.process(m.raw.tenant_id, m.message_id).attempt
    d = json.loads(attempt.diagnostic)
    assert d['configured'] and d['accepted_model_fields'] == 0
    assert d['runtime_reported']['qwen']['attempted']
    assert d['runtime_reported']['qwen']['succeeded']
    assert d['runtime_reported']['qwen']['device'] is None
    assert attempt.completed_at >= attempt.started_at


def test_reprocess_operation_id_replays_but_fresh_operation_preserves_history(pg_engine):
    repo = PostgresMessageRepository(pg_engine)
    m = repo.ingest(make_envelope('20 pcs burgers tomorrow before 3pm'), NOW).message
    a = repo.process(m.raw.tenant_id, m.message_id, reprocess=True, operation_id='op-1').attempt
    b = repo.process(m.raw.tenant_id, m.message_id, reprocess=True, operation_id='op-1').attempt
    c = repo.process(m.raw.tenant_id, m.message_id, reprocess=True, operation_id='op-2').attempt
    assert a.attempt_id == b.attempt_id != c.attempt_id
    assert len(repo.list_extraction_attempts(m.raw.tenant_id, m.message_id)) == 2
    assert json.loads(c.diagnostic)['trigger'] == 'explicit_reprocess'


def test_rules_only_skipped_model_has_no_runtime_success(pg_engine):
    endpoint = FakeEndpoint()
    repo = PostgresMessageRepository(pg_engine, proposal_service=ModelProposalService(endpoint, enabled=True, stages=('gliner', 'qwen')))
    env = make_envelope('Need 15 burgers tomorrow')
    env.business_timezone = None
    m = repo.ingest(env, NOW).message
    d = json.loads(repo.process(m.raw.tenant_id, m.message_id).attempt.diagnostic)
    assert d['model_outcomes'] == {'gliner': 'not_needed', 'qwen': 'not_needed'}
    assert not d['runtime_reported'] and not endpoint.requests


def test_api_reprocess_reuses_operation_header_without_losing_explicit_history(api):
    client, repo = api
    m = repo.ingest(envelope(), NOW).message
    path = f'/v1/messages/{m.message_id}/process?reprocess=true'
    a = client.post(path, headers={'X-P1-Operation-ID': 'audit-operation-1'})
    b = client.post(path, headers={'X-P1-Operation-ID': 'audit-operation-1'})
    c = client.post(path, headers={'X-P1-Operation-ID': 'audit-operation-2'})
    assert a.status_code == b.status_code == c.status_code == 200
    assert a.json()['attempt']['attempt_id'] == b.json()['attempt']['attempt_id'] != c.json()['attempt']['attempt_id']
    assert client.post(path, headers={'X-P1-Operation-ID': 'bad key'}).status_code == 422
