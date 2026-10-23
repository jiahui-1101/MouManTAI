from zoneinfo import ZoneInfo
"""Judge-facing invariants; deterministic and mocked failures, never GPU accuracy."""
import asyncio
import json
from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.context.ai.protocol import InferenceFailure
from app.context.ai.protocol import InferenceOutput, MODEL_CONFIG, Observation
from app.context.ai.service import ModelProposalService
from app.context.context_service import ContextService
from app.context.deterministic_extraction import PROVISIONAL_PRODUCTS, extract_explicit_fields
from app.context.postgres_repository import PostgresMessageRepository
from app.context.schemas import RawMessageEnvelope
from app.context.tests.test_deterministic_extraction import stored
from app.context.tests.test_review_catalog_boundary import client_for
from app.core.models import CommitmentRecord

NOW = datetime.fromisoformat('2026-10-23T09:00:00+08:00')


class OfflineEndpoint:
    def __init__(self):
        self.calls = []

    async def infer(self, request):
        self.calls.append(request.engine)
        raise InferenceFailure('transport_or_schema_error')


def message(text, tz='Asia/Kuala_Lumpur'):
    return stored(text, received_at=NOW, tz=tz)


@pytest.mark.parametrize('text,product,quantity,unit', [
    ('Please prepare 25 boxes of cookies for delivery on 28 October 2026.', 'cookies', '25', 'box'),
    ('Nak 25 kotak cookies, hantar esok sebelum pukul 4 petang.', 'cookies', '25', 'box'),
    ('Please prepare 25 cookies for delivery on 28 October 2026.', 'cookies', '25', None),
    ('Please deliver 25 boxes of potato puffs tomorrow before 4pm', 'potato puffs', '25', 'box'),
    ('Nak 30 bungkus nasi lemak esok 9am.', 'nasi lemak', '30', 'pack'),
    ('Tolong hantar 40 biji karipap esok pukul 10 pagi.', 'karipap', '40', 'pcs'),
    ('明天早上要20杯咖啡送到办公室。', '咖啡', '20', 'cup'),
    ('Please deliver 50 egg tarts tomorrow before 2pm.', 'egg tarts', '50', None),
    ('Curry puffs, quantity is 35 boxes tomorrow 3pm.', 'Curry puffs', '35', 'box'),
    ('Nasi lemak: 20 sets tomorrow 12pm.', 'Nasi lemak', '20', 'set'),
    ('曲奇要25盒明天下午送到。', '曲奇', '25', 'box'),
    ('Please prepare 25 boxes of matcha roll cakes tomorrow 3pm.', 'matcha roll cakes', '25', 'box'),
    ('Please deliver 40 trays of blueberry scones before 2pm.', 'blueberry scones', '40', 'tray'),
    ('明天下午两点前要30盒榴莲酥送达。', '榴莲酥', '30', 'box'),
    ('明天早上要15碗牛肉面送达。', '牛肉面', '15', 'bowl'),
    ('Tolong hantar 20 bungkus pulut panggang esok sebelum 12pm.', 'pulut panggang', '20', 'pack'),
    ('Nak 35 kotak kuih lapis esok 4pm.', 'kuih lapis', '35', 'box'),
])
def test_unknown_product_keeps_literal_fields_with_exact_source_evidence(text, product, quantity, unit):
    msg = message(text)
    result = extract_explicit_fields(msg, catalog=PROVISIONAL_PRODUCTS)
    fields = [f for f in result.fields if f.metadata.get('disposition') == 'unverified_product']
    assert [(f.field_name, f.value) for f in fields] == [('sku', product), ('quantity', quantity), ('unit', unit)]
    assert all(f.validation_status != 'VALID' for f in fields)
    assert fields[-1].validation_status == ('UNRESOLVED' if unit else 'MISSING')
    for f in fields:
        for ev in f.evidence:
            assert text[ev.start:ev.end] == ev.quote


@pytest.mark.parametrize('text,product,quantity,unit', [
    ('Cookies, quantity is 25 boxes. Deliver tomorrow before 4pm.', 'Cookies', '25', 'box'),
    ('曲奇要25盒，明天下午四点前送到。', '曲奇', '25', 'box'),
    ('Karipap jumlah 12 bungkus, hantar esok.', 'Karipap', '12', 'pack'),
    ('Kopi x20 cups, hantar esok.', 'Kopi', '20', 'cup'),
    ('Croissants: 15 pcs. Delivery tomorrow.', 'Croissants', '15', 'pcs'),
])
def test_more_product_names_and_postfix_quantities_are_unverified_not_new_skus(text, product, quantity, unit):
    fields = extract_explicit_fields(message(text), catalog=PROVISIONAL_PRODUCTS).fields
    raw = [f for f in fields if f.metadata.get('disposition') == 'unverified_product']
    assert any(f.field_name == 'sku' and f.value == product for f in raw)
    group = next(f.metadata['group_id'] for f in raw if f.field_name == 'sku' and f.value == product)
    assert any(f.field_name == 'quantity' and f.value == quantity and f.metadata.get('group_id') == group for f in raw)
    assert any(f.field_name == 'unit' and f.value == unit and f.metadata.get('group_id') == group for f in raw)
    assert not any(f.validation_status == 'VALID' for f in raw)


def test_known_clear_request_skips_models():
    endpoint = OfflineEndpoint()
    result = asyncio.run(ModelProposalService(endpoint, enabled=True, stages=('gliner', 'qwen')).extract_stored(
        message('Please prepare 12 pcs burgers for delivery on 28 October 2026 before 3pm.'), catalog=PROVISIONAL_PRODUCTS))
    assert endpoint.calls == []
    assert result.outcomes == {'gliner': 'not_needed', 'qwen': 'not_needed'}
    assert any(f.field_name == 'quantity' and f.value == '12' and f.validation_status == 'VALID' for f in result.rules.fields)


def test_mixed_items_keep_separate_quantity_unit_evidence_without_creating_cookie_sku():
    result = extract_explicit_fields(message('Prepare 12 pcs burgers and 25 boxes of cookies tomorrow before 4pm.'), catalog=PROVISIONAL_PRODUCTS)
    groups = {}
    for f in result.fields:
        if f.value and f.metadata.get('group_id'):
            groups.setdefault(f.metadata['group_id'], {})[f.field_name] = f.value
    assert any(g.get('sku') == 'BURGER' and g.get('quantity') == '12' and g.get('unit') == 'pcs' for g in groups.values())
    assert any(g.get('sku') == 'cookies' and g.get('quantity') == '25' and g.get('unit') == 'box' for g in groups.values())
    assert not any(f.value == 'cookies' and f.validation_status == 'VALID' for f in result.fields)


def test_missing_timezone_does_not_suppress_unknown_item_models():
    endpoint = OfflineEndpoint()
    result = asyncio.run(ModelProposalService(endpoint, enabled=True, stages=('gliner', 'qwen')).extract_stored(
        message('Prepare 12 pcs burgers and 25 boxes of cookies tomorrow before 4pm.', tz=None), catalog=PROVISIONAL_PRODUCTS))
    assert endpoint.calls == ['gliner', 'qwen']
    assert result.rules.fields


@pytest.mark.parametrize('quote,is_duplicate', [('burgers', False), ('28 October 2026 before 3pm', True)])
def test_model_delivery_is_duplicate_only_when_its_source_is_the_parsed_delivery(quote, is_duplicate):
    msg = message('Please prepare burgers, quantity is 12 pcs, for 28 October 2026 before 3pm.')
    class Endpoint:
        async def infer(self, request):
            return InferenceOutput(engine=request.engine, model_id=MODEL_CONFIG[request.engine][0],
                revision=MODEL_CONFIG[request.engine][1], status='ok', finish_reason='stop',
                load_seconds=0, inference_seconds=0, fields=[Observation(field='delivery', message_id='m1',
                    quote=quote, start=msg.raw.text.index(quote), end=msg.raw.text.index(quote)+len(quote))])
    result = asyncio.run(ModelProposalService(Endpoint(), enabled=True).extract_stored(msg, catalog=PROVISIONAL_PRODUCTS))
    assert bool(result.candidates[0].metadata['disposition'] == 'duplicate') == is_duplicate


def test_offline_unknown_product_survives_postgres_context_refresh_and_cannot_publish(pg_engine):
    endpoint = OfflineEndpoint()
    repo = PostgresMessageRepository(pg_engine, proposal_service=ModelProposalService(
        endpoint, enabled=True, stages=('gliner', 'qwen')))
    text = 'Prepare 12 pcs burgers and 25 boxes of cookies for delivery on 28 October 2026 before 4pm.'
    envelope = RawMessageEnvelope(tenant_id='synthetic_tenant_a', channel='WHATSAPP',
        provider_message_id=f'judge-{uuid4().hex}', sender_identity_id='+60123456789', sender_alias='Synthetic buyer',
        received_at=NOW, message_at=NOW, business_timezone='Asia/Kuala_Lumpur', text=text)
    msg = repo.ingest(envelope, NOW).message
    processed = repo.process(envelope.tenant_id, msg.message_id)
    assert processed.attempt.status == 'PROCESSED'
    assert json.loads(processed.attempt.diagnostic)['fallback'] == 'rules_only'
    ctx = ContextService(repo).create_or_update_from_message(envelope.tenant_id, msg.message_id)
    assert ctx.status != 'INFORMATION_READY'
    assert 'sku_mapping' in ctx.missing_fields
    client = client_for(repo, 'synthetic_tenant_a')
    refreshed = client.get(f'/v1/contexts/{ctx.context_id}').json()
    for name, value in [('sku', 'cookies'), ('quantity', '25'), ('unit', 'box')]:
        assert any(ev.get('normalized_value') == value and ev['validation_status'] == 'UNRESOLVED'
                   for ev in refreshed['field_evidence'][name])
    assert client.post(f'/v1/contexts/{ctx.context_id}/publish').status_code == 422
    assert client.post(f'/v1/contexts/{ctx.context_id}/review', json={
        'expected_context_version': ctx.context_version, 'action': 'MARK_UNRESOLVED'}).status_code == 200
    assert client.get(f'/v1/contexts/{ctx.context_id}').json()['status'] == 'UNRESOLVED'
    with Session(pg_engine) as session:
        assert session.scalar(select(func.count()).select_from(CommitmentRecord)) == 0


def test_catalog_grounded_unit_inference_and_packaging_safety(pg_engine):
    repo = PostgresMessageRepository(pg_engine)
    svc = ContextService(repo)
    now = datetime(2026, 10, 23, 9, 0, 0, tzinfo=ZoneInfo("Asia/Kuala_Lumpur"))

    # Case 1: "50 burgers" (unambiguous known product with piece count -> quantity is VALID, unit stays MISSING without inventing packaging)
    res1 = extract_explicit_fields(message("Please deliver 50 burgers tomorrow before 3pm."), catalog=PROVISIONAL_PRODUCTS)
    sku1 = next(f for f in res1.fields if f.field_name == "sku")
    qty1 = next(f for f in res1.fields if f.field_name == "quantity")
    unit1 = next(f for f in res1.fields if f.field_name == "unit")
    assert sku1.value == "BURGER" and sku1.validation_status == "VALID"
    assert qty1.value == "50" and qty1.validation_status == "VALID"
    assert unit1.value is None and unit1.validation_status == "MISSING"

    # Context lifecycle: requires review before canonical publication
    raw1 = RawMessageEnvelope(
        tenant_id="synthetic_tenant_a", channel="WHATSAPP", adapter_mode="SYNTHETIC",
        provider_message_id=f"test_u1_{uuid4().hex[:6]}", sender_identity_id="+60123456789",
        sender_alias="Buyer 1", received_at=now, message_at=now,
        text="Please deliver 50 burgers tomorrow before 3pm.", business_timezone="Asia/Kuala_Lumpur", attachments=[]
    )
    ing1 = repo.ingest(raw1, now)
    ctx1 = svc.create_or_update_from_message("synthetic_tenant_a", ing1.message.message_id)
    assert ctx1.status == "INFORMATION_PARTIAL"
    assert ctx1.requested_items == []
    assert "requested_items" in ctx1.missing_fields

    # Case 2: "50 boxes of burgers" (ambiguous packaging unit -> MUST NOT convert to pcs)
    res2 = extract_explicit_fields(message("Please deliver 50 boxes of burgers tomorrow before 3pm."), catalog=PROVISIONAL_PRODUCTS)
    box_unit = next(f for f in res2.fields if f.field_name == "unit")
    assert box_unit.value == "box"
    assert box_unit.validation_status != "VALID"
    assert box_unit.metadata.get("domain_supported") == "false"
