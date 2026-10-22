"""Audit current operational proposal service; never writes business records.

Scores exact (field, normalized value) pairs of VALID L0 fields. Provisional
model observations are counted separately, never credited as accepted fields.
Fixtures are frozen separately and their answers never enter model requests.
"""
import argparse
import asyncio
from collections import Counter
from dataclasses import replace
from datetime import datetime
import hashlib
import json
from pathlib import Path
import time

from app.context.ai.endpoint import EndpointAdapter, EndpointConfig
from app.context.ai.service import ModelProposalService
from app.context.deterministic_extraction import PROVISIONAL_PRODUCTS
from app.context.ingestion_schemas import StoredMessage
from app.context.schemas import RawMessageEnvelope

FIXTURES = Path(__file__).with_name('pipeline_audit_fixtures.json')


class Recorder:
    def __init__(self, adapter):
        self.adapter, self.records = adapter, []

    async def infer(self, request):
        before = time.perf_counter()
        record = {'request': request.model_dump(mode='json')}
        try:
            answer = await self.adapter.infer(request)
            record['response'] = answer.model_dump(mode='json')
            return answer
        except Exception as exc:
            record['failure'] = str(exc)
            if self.adapter.last_output:
                record['rejected_response'] = self.adapter.last_output.model_dump(mode='json')
            raise
        finally:
            record['wall_seconds'] = time.perf_counter() - before
            self.records.append(record)


def score(predicted, gold):
    p, g = set(predicted), set(gold)
    tp, fp, fn = len(p & g), len(p - g), len(g - p)
    return {'tp': tp, 'fp': fp, 'fn': fn}


def rates(counts):
    tp, fp, fn = counts['tp'], counts['fp'], counts['fn']
    return {**counts, 'precision': tp / (tp + fp) if tp + fp else None,
            'recall': tp / (tp + fn) if tp + fn else None,
            'f1': 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None}


async def evaluate(split, endpoint=None, stages=('qwen',)):
    fixture_bytes = FIXTURES.read_bytes()
    fixtures = json.loads(fixture_bytes)
    now = datetime.fromisoformat(fixtures['message_timestamp'])
    rows, totals, per_field, dispositions = [], Counter(), {}, Counter()
    for case in fixtures['cases']:
        if case['split'] != split:
            continue
        raw = RawMessageEnvelope(tenant_id='synthetic_tenant_a', channel='WHATSAPP',
            provider_message_id=case['id'], sender_identity_id='synthetic_unverified', sender_alias='Audit synthetic',
            text=case['text'], received_at=now, message_at=now, business_timezone=case.get('timezone'))
        message = StoredMessage(message_id=case['id'], raw=raw, synthetic_provider='SYNTHETIC_WHATSAPP',
            content_sha256=hashlib.sha256(raw.text.encode()).hexdigest(), processing_status='RECEIVED',
            ingested_at=now, updated_at=now)
        result = await ModelProposalService(endpoint, enabled=endpoint is not None, stages=stages).extract_stored(
            message, catalog=PROVISIONAL_PRODUCTS)
        accepted = [(f.field_name, f.value) for f in result.rules.fields if f.validation_status == 'VALID']
        gold = [tuple(v) for v in case['accepted_fields']]
        counts = score(accepted, gold)
        totals.update(counts)
        for name in ('sku', 'quantity', 'unit', 'requested_delivery_at'):
            per_field.setdefault(name, Counter()).update(score([p for p in accepted if p[0] == name], [g for g in gold if g[0] == name]))
        dispositions.update(c.metadata.get('disposition', 'unknown') for c in result.candidates)
        rows.append({'id': case['id'], 'language': case['language'], 'score': counts,
            'expected': gold, 'accepted': accepted, 'rules': result.rules.model_dump(mode='json'),
            'model_outcomes': result.outcomes, 'model_candidates': [c.model_dump(mode='json') for c in result.candidates],
            'runtime_reported': result.telemetry})
    return {'fixture_sha256': hashlib.sha256(fixture_bytes).hexdigest(), 'split': split, 'samples': len(rows),
        'scoring': 'exact field/normalized-value pairs; only VALID fields accepted; model proposals never counted as accepted',
        'rules': rates(totals), 'combined_accepted': rates(totals),
        'per_field': {k: rates(v) for k, v in per_field.items()},
        'model_dispositions': dict(dispositions), 'accepted_model_fields': 0, 'cases': rows,
        'calls': endpoint.records if endpoint else [],
        'limitations': 'Small synthetic sample; semantic correctness scope is declared in fixtures. Remote telemetry is reported, not hardware attestation.'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--split', choices=('development', 'evaluation'), default='evaluation')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--live-existing-endpoint', action='store_true')
    parser.add_argument('--stages', default='qwen')
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('Refusing to overwrite audit evidence')
    stages = tuple(args.stages.split(','))
    endpoint = None
    if args.live_existing_endpoint:
        cfg = EndpointConfig.from_env_or_none()
        if not cfg:
            raise SystemExit('No existing endpoint configured; no resource was created')
        endpoint = Recorder(EndpointAdapter(replace(cfg, timeout_seconds=12)))
    report = asyncio.run(evaluate(args.split, endpoint, stages))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('samples', 'fixture_sha256', 'rules', 'accepted_model_fields', 'model_dispositions')}))


if __name__ == '__main__':
    main()
