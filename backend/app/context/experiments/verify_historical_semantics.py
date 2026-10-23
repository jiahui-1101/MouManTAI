"""Offline snapshot verification; no DB, model, reprocessing or publication.

Annotations are retrospective source review, not independent human intent gold.
Verified verdicts concern reproducible literal facts; missing review/lineage
prevents calling a complete BusinessContext correct.
"""
import argparse
from collections import Counter
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

LABELS = Path(__file__).with_name('historical_semantic_labels.json')
STATUSES = ('VERIFIED_CORRECT','VERIFIED_INCORRECT','AMBIGUOUS','INSUFFICIENT_EVIDENCE','NOT_REVIEWED')


def verify_record(row, label):
    if label is None:
        return {'status':'NOT_REVIEWED','defects':[], 'limitations':['No source annotation']}
    message = row['message']
    raw = message['raw']
    text = raw['text']
    fields = row['latest_stored_fields']
    defects, limitations = [], []
    for field in fields:
        if field['validation_status']=='VALID' and any(e.get('method')=='MODEL' for e in field.get('evidence',[])):
            defects.append('provisional_model_marked_valid')
        if field['validation_status']=='VALID' and not field.get('evidence'):
            limitations.append('Valid field lacks source evidence')
        for evidence in field.get('evidence', []):
            start, end = evidence.get('start'), evidence.get('end')
            if not isinstance(start,int) or not isinstance(end,int) or not 0 <= start < end <= len(text) or text[start:end] != evidence.get('quote') or evidence.get('message_id') != message['message_id']:
                defects.append('original_evidence_mismatch')
        if any(e.get('method') == 'HUMAN' for e in field.get('evidence', [])):
            limitations.append('Human field requires its actual review event')
    rule_fields = [f for f in fields if f.get('evidence') and all(e.get('method')=='RULE' for e in f['evidence'])]
    valid = lambda name: [f for f in rule_fields if f['field_name']==name and f['validation_status']=='VALID']
    for name in ('sku','quantity','unit'):
        expected = label.get(name)
        for field in valid(name):
            if field.get('value') != (str(expected) if expected is not None else None):
                defects.append(f'unsupported_or_wrong_{name}')
    human_quantity = any(f['field_name']=='quantity' and any(e.get('method')=='HUMAN' for e in f.get('evidence',[])) for f in fields)
    if fields and label.get('quantity_required') and not human_quantity and not any(f.get('value')==str(label['quantity']) for f in valid('quantity')):
        defects.append('explicit_quantity_rejected_or_missing')
    for field in fields:
        if field['field_name']=='sku' and field['validation_status']=='CONFLICT' and label.get('sku') and field.get('value') in {label['sku'],f"{label['quantity']} burgers"} and valid('sku'):
            defects.append('equivalent_model_sku_false_conflict')

    delivery = label.get('delivery')
    actual = valid('requested_delivery_at')
    if delivery is None and actual:
        defects.append('delivery_not_stated')
    elif delivery and delivery.get('unresolved') and actual:
        defects.append('vague_delivery_marked_valid')
    elif delivery and not delivery.get('unresolved'):
        zone = raw.get('business_timezone')
        if not zone:
            if actual:
                defects.append('relative_date_without_trusted_timezone')
        else:
            source = datetime.fromisoformat(raw.get('message_at') or raw['received_at'])
            received = datetime.fromisoformat(raw['received_at'])
            persisted = datetime.fromisoformat(message['ingested_at'])
            expected_date = source.astimezone(ZoneInfo(zone)).date() + timedelta(days=delivery['days'])
            clock_problem = source > received or received > persisted
            hour = delivery.get('hour')
            expected = datetime.combine(expected_date, datetime.min.time(), ZoneInfo(zone)) + timedelta(hours=hour or 0,minutes=delivery.get('minute',0))
            past = expected < received if hour is not None else expected_date < received.astimezone(ZoneInfo(zone)).date()
            if clock_problem or past:
                if actual:
                    defects.append('valid_delivery_despite_source_clock_or_past_request')
                limitations.append('Source clock/delayed receipt requires review')
            elif fields and not actual:
                defects.append('literal_delivery_not_normalized')
            for field in actual:
                value = field.get('value') or ''
                if field.get('qualifier')=='DATE_ONLY':
                    if value != expected_date.isoformat() or hour is not None:
                        defects.append('date_only_dropped_stated_clock_or_wrong_date')
                else:
                    try:
                        parsed = datetime.fromisoformat(value)
                        if hour is None or parsed.tzinfo is None or parsed != expected:
                            defects.append('unsupported_or_wrong_delivery_instant')
                        if field.get('qualifier') != delivery.get('qualifier'):
                            defects.append('unsupported_delivery_qualifier')
                    except ValueError:
                        defects.append('invalid_delivery_value')
    if row.get('contexts'):
        limitations.append('Context snapshot lacks delivery/evidence/review-event/thread lineage; manual changes cannot be verified')
    if not fields:
        limitations.append('No saved extraction to verify')
    if defects:
        status = 'VERIFIED_INCORRECT'
    elif limitations:
        status = 'INSUFFICIENT_EVIDENCE'
    elif label.get('ambiguity'):
        status = 'AMBIGUOUS'
    else:
        status = 'VERIFIED_CORRECT'
    return {'status':status,'defects':sorted(set(defects)),'limitations':sorted(set(limitations)),
            'source_ambiguity':label.get('ambiguity'), 'reviewed_text_group':label['group'],
            'scope':'Saved literal extraction and available context only; no identity/agreement confirmation'}


def evaluate(snapshot_path, labels_path=LABELS):
    data = snapshot_path.read_bytes()
    labels = json.loads(labels_path.read_text(encoding='utf-8'))
    if hashlib.sha256(data).hexdigest() != labels['snapshot_sha256']:
        raise ValueError('Snapshot differs from reviewed evidence; refusing to transfer verdicts')
    snapshot = json.loads(data)
    if len(snapshot['messages']) != labels['expected_records']:
        raise ValueError('Historical coverage changed')
    by_hash = {l['text_sha256']:l for l in labels['labels']}
    rows, categories = [], Counter()
    for row in snapshot['messages']:
        label = by_hash.get(hashlib.sha256(row['message']['raw']['text'].encode()).hexdigest())
        verdict = verify_record(row,label)
        categories.update(verdict['defects'])
        rows.append({'message_id':row['message']['message_id'],'text':row['message']['raw']['text'],
                     'literal_source_annotation':label, 'context_ids':[c['context_id'] for c in row.get('contexts',[])],
                     'stored_accepted_fields':[{k:f.get(k) for k in ('field_name','value','qualifier','evidence')}
                                              for f in row['latest_stored_fields'] if f['validation_status']=='VALID'], **verdict})
    counts = Counter(r['status'] for r in rows)
    return {'snapshot_sha256':labels['snapshot_sha256'], 'total':len(rows),
        'semantically_reviewed':sum(r['status']!='NOT_REVIEWED' for r in rows),
        'counts':{s:counts[s] for s in STATUSES}, 'defect_categories':dict(categories),
        'review_method':labels['review_method'], 'data_writes':0, 'model_calls':0, 'records':rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('Refusing to overwrite reviewed evidence')
    report = evaluate(args.snapshot)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='records'}))


if __name__=='__main__':
    main()
