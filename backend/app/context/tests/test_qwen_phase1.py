"""Offline Phase 1 only: no model imports, downloads or real endpoint calls."""
import asyncio

import httpx
import pytest
from pydantic import ValidationError

from app.context.ai.endpoint import EndpointAdapter, EndpointConfig
from app.context.ai.protocol import MODEL_CONFIG, InferenceOutput, Observation
from app.context.ai.protocol import InferenceFailure
from app.context.ai.service import ModelProposalService
from app.context.ai.worker import ground_raw_answer
from app.context.deterministic_extraction import PROVISIONAL_PRODUCTS, extract_explicit_fields
from app.context.schemas import ExtractedField, FieldEvidence
from app.context.tests.test_deterministic_extraction import stored


class FakeEndpoint:
    def __init__(self, fields=None):
        self.calls = []
        self.fields = fields or {}

    async def infer(self, request):
        self.calls.append(request.engine)
        return InferenceOutput(engine=request.engine, model_id=MODEL_CONFIG[request.engine][0],
            revision=MODEL_CONFIG[request.engine][1], status='ok', finish_reason='stop',
            load_seconds=0.0, inference_seconds=0.1, fields=self.fields.get(request.engine, []))


def run(service, text, **kwargs):
    return asyncio.run(service.extract_stored(stored(text), catalog=PROVISIONAL_PRODUCTS, **kwargs))


def test_default_has_no_l2_and_stages_cannot_duplicate_or_reverse():
    assert ModelProposalService().stages == ('gliner',)
    assert not ModelProposalService().enabled
    for stages in (('qwen','gliner'), ('qwen','qwen')):
        with pytest.raises(ValueError):
            ModelProposalService(stages=stages)


@pytest.mark.parametrize('text', ['Need 40 pcs burgers tomorrow', 'Need burgers', 'Need 40 burgers tomorrow after 3pm'])
def test_no_l2_for_sufficient_terms_absent_facts_or_lower_bound_metadata(text):
    endpoint = FakeEndpoint()
    result = run(ModelProposalService(endpoint, enabled=True, stages=('gliner','qwen')), text)
    assert 'qwen' not in endpoint.calls
    assert not any(f.validation_status == 'VALID' for f in result.candidates)


def test_unknown_request_escalates_once_after_l1_and_cache_is_per_engine():
    endpoint = FakeEndpoint()
    service = ModelProposalService(endpoint, enabled=True, stages=('gliner','qwen'))
    text = 'Please prepare 20 mystery_items tomorrow'
    result = run(service, text)
    assert endpoint.calls == ['gliner','qwen']
    assert result.worker_request_count == 2
    assert run(service, text).worker_request_count == 0
    assert endpoint.calls == ['gliner','qwen']


def test_l1_multi_item_proposals_escalate_without_collapsing_items():
    from app.context.deterministic_extraction import ProductAlias
    text = 'Need burgers and bread tomorrow'
    fields = [Observation(field='product', message_id='m1', quote=quote,
        start=text.index(quote), end=text.index(quote)+len(quote), group_id=quote)
        for quote in ('burgers','bread')]
    endpoint = FakeEndpoint({'gliner':fields})
    catalog = (*PROVISIONAL_PRODUCTS, ProductAlias('synthetic_tenant_a','BREAD',('bread',),'pcs'))
    result = asyncio.run(ModelProposalService(endpoint, enabled=True, stages=('gliner','qwen')).extract_stored(
        stored(text), catalog=catalog))
    assert endpoint.calls == ['gliner','qwen']
    assert {c.value for c in result.candidates if c.field_name == 'sku'} == {'BURGER','BREAD'}
    assert all(c.validation_status != 'VALID' for c in result.candidates)


def test_single_supported_l1_proposal_does_not_require_a_second_model():
    from app.context.ai.service import ProposalResult
    from app.context.extraction import ExtractionResult
    result = ProposalResult(rules=ExtractionResult(status='AVAILABLE', fields=[]), reviewed_fields=[],
        outcomes={}, conflicts=[], candidates=[ExtractedField(field_name=name, value=value,
        validation_status='UNRESOLVED', evidence=[], metadata={'domain_supported':'true', 'disposition':'proposal'})
        for name,value in (('sku','BURGER'),('quantity','40'))])
    assert ModelProposalService._l2_escalation_reason(stored('Please prepare burgers for 40 people'),result) is None


def test_reviewed_quantity_prevents_unnecessary_l2_and_is_immutable():
    message = stored('Need burgers serving 40 guests')
    start = message.raw.text.index('40')
    human = ExtractedField(field_name='quantity', value='40', validation_status='VALID',
        evidence=[FieldEvidence(evidence_id='review', message_id=message.message_id, quote='40',
            start=start, end=start+2, method='HUMAN', method_version='review-1')])
    endpoint = FakeEndpoint()
    result = asyncio.run(ModelProposalService(endpoint, enabled=True, stages=('qwen',)).extract_stored(
        message, catalog=PROVISIONAL_PRODUCTS, reviewed_fields=[human]))
    assert not endpoint.calls
    assert result.reviewed_fields == [human]


@pytest.mark.parametrize('field,quote,text', [
    ('quantity','40/50','Need burgers for 40/50 guests'),
    ('quantity','40 guests','Need burgers for 40 guests'),
    ('product','burger sauce','Need 40 burger sauce'),
    ('unit','kg','Need 40 burgers, weight 2 kg'),
])
def test_qwen_cannot_pick_first_number_invent_sku_or_ignore_unit_compatibility(field, quote, text):
    message = stored(text)
    start = text.index(quote)
    observation = Observation(field=field, message_id='m1', quote=quote, start=start, end=start+len(quote))
    candidate = ModelProposalService._candidate(observation, message, PROVISIONAL_PRODUCTS, *MODEL_CONFIG['qwen'])
    assert candidate.metadata['domain_supported'] == 'false'
    assert candidate.validation_status != 'VALID'
    assert candidate.evidence[0].quote == text[start:start+len(quote)]


@pytest.mark.parametrize('raw', ['not json', '{"fields":[],"confirm":true}',
    '{"fields":[{"field":"quantity","message_id":"m1","quote":"999"}]}'])
def test_strict_worker_json_and_evidence_gates(raw):
    from app.context.ai.protocol import InferenceInput
    with pytest.raises((ValueError, ValidationError)):
        ground_raw_answer(raw, InferenceInput(engine='qwen', messages=[{'id':'m1','text':'Need 40 burgers'}]))


def test_custom_adapter_timeout_is_bounded_counted_and_preserves_rules():
    class HangingEndpoint(FakeEndpoint):
        async def infer(self, request):
            self.calls.append(request.engine)
            await asyncio.Future()
    endpoint = HangingEndpoint()
    service = ModelProposalService(endpoint, enabled=True, stages=('qwen',))
    service.request_timeout_seconds = 0.01
    text = 'Please prepare 20 mystery_items tomorrow'
    result = run(service, text)
    assert result.outcomes['qwen'] == 'timeout'
    assert result.worker_request_count == 1 and endpoint.calls == ['qwen']
    assert not service._inference_cache
    assert result.rules == extract_explicit_fields(stored(text), catalog=PROVISIONAL_PRODUCTS)


@pytest.mark.parametrize('response', [httpx.Response(503), httpx.Response(200, json={'confirm':True})])
def test_http_failure_or_malformed_output_has_no_retry_or_authoritative_fields(response):
    calls = []
    def handler(request):
        calls.append(request)
        return response
    endpoint = EndpointAdapter(EndpointConfig('https://mock.invalid/infer', 'mock-key', mode='direct'),
        transport=httpx.MockTransport(handler))
    result = run(ModelProposalService(endpoint, enabled=True, stages=('qwen',)),
                 'Please prepare 20 mystery_items tomorrow')
    assert len(calls) == result.worker_request_count == 1
    assert result.outcomes['qwen'] in {'endpoint_http_error','transport_or_schema_error'}
    assert not result.candidates


def test_injected_adapter_cannot_bypass_output_schema():
    class MalformedEndpoint(FakeEndpoint):
        async def infer(self, request):
            return {'engine':'qwen','fields':[], 'execute_tool':'confirm_order'}
    result = run(ModelProposalService(MalformedEndpoint(), enabled=True, stages=('qwen',)),
                 'Please prepare 20 mystery_items tomorrow')
    assert result.outcomes['qwen'] == 'invalid_structured_output'
    assert not result.candidates


def test_l1_failure_can_escalate_once_without_retry_or_loss_of_rules():
    class FailedL1(FakeEndpoint):
        async def infer(self, request):
            if request.engine == 'gliner':
                self.calls.append(request.engine)
                raise InferenceFailure('unavailable')
            return await super().infer(request)
    endpoint = FailedL1()
    result = run(ModelProposalService(endpoint, enabled=True, stages=('gliner','qwen')),
                 'Please prepare 20 mystery_items tomorrow')
    assert endpoint.calls == ['gliner','qwen']
    assert result.worker_request_count == 2
    assert result.outcomes == {'gliner':'unavailable', 'qwen':'proposals_only'}


def test_l2_candidates_never_accept_or_overwrite_human_corrections():
    text = 'Need 40 or 50 burgers'
    message = stored(text)
    start = text.index('burgers')
    human = ExtractedField(field_name='sku', value='HUMAN_CORRECTED', validation_status='VALID',
        evidence=[FieldEvidence(evidence_id='review', message_id=message.message_id,
            quote='burgers', start=start, end=start+7, method='HUMAN', method_version='review-2')])
    endpoint = FakeEndpoint({'qwen':[Observation(field='product', message_id='m1',
        quote='burgers', start=start, end=start+7)]})
    result = asyncio.run(ModelProposalService(endpoint, enabled=True, stages=('qwen',)).extract_stored(
        message, catalog=PROVISIONAL_PRODUCTS, reviewed_fields=[human]))
    assert endpoint.calls == ['qwen']
    assert result.reviewed_fields == [human]
    assert result.candidates[0].validation_status == 'CONFLICT'
    assert result.manual_review_required
    assert all(f.validation_status != 'VALID' for f in result.candidates)


def test_qwen_worker_refuses_cpu_before_model_loader_import(monkeypatch):
    import sys
    from types import SimpleNamespace
    from app.context.ai.worker import ModelRuntime
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'transformers', None)
    with pytest.raises(RuntimeError, match='CPU inference is disabled'):
        ModelRuntime(device='cpu')._load('qwen')


def test_mock_qwen_persistence_and_reprocess_cannot_overwrite_review_or_publish(pg_engine):
    from sqlalchemy import select, func
    from sqlalchemy.orm import Session
    from app.context.postgres_repository import PostgresMessageRepository
    from app.context.context_service import ContextService
    from app.context.core_publisher import CoreContextPublisher
    from app.context.order_context_schemas import ContextReviewRequest
    from app.core.models import CommitmentRecord, OutboxEventRecord
    text = 'Need 40 or 50 burgers'
    message = stored(text)
    start = text.index('burgers')
    endpoint = FakeEndpoint({'qwen':[Observation(field='product', message_id='m1',
        quote='burgers', start=start, end=start+7)]})
    service = ModelProposalService(endpoint, enabled=True, stages=('qwen',))
    repo = PostgresMessageRepository(pg_engine, proposal_service=service)
    saved = repo.ingest(message.raw, message.raw.received_at).message
    attempt = repo.process(saved.raw.tenant_id, saved.message_id)
    assert attempt.attempt.extractor_version == 'p1-ai-pipeline-v2'
    context_service = ContextService(repo)
    context = context_service.create_or_update_from_message(saved.raw.tenant_id, saved.message_id)
    assert not CoreContextPublisher().check_eligibility(context)[0]
    reviewed = repo.apply_context_review(context.tenant_id, context.context_id,
        ContextReviewRequest(expected_context_version=context.context_version, action='EDIT_FIELD',
            field_edits={'requested_items':[{'sku':'BURGER','quantity':'50','unit':'pcs'}]}),
        'user_staff_01','STAFF')
    repo.process(saved.raw.tenant_id, saved.message_id, reprocess=True, operation_id='qwen-review-preserved')
    restored = context_service.create_or_update_from_message(context.tenant_id, saved.message_id)
    assert restored.context_version == reviewed.context_version
    assert restored.requested_items[0].quantity == '50'
    assert repo.get_order_context(context.tenant_id, context.context_id) == restored
    assert endpoint.calls == ['qwen']  # reprocess reused grounded observations, not human fields
    with Session(pg_engine) as session:
        assert session.scalar(select(func.count()).select_from(CommitmentRecord)) == 0
        assert session.scalar(select(func.count()).select_from(OutboxEventRecord)) == 0
