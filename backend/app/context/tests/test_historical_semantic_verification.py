import pytest

from app.context.experiments.verify_historical_semantics import verify_record
from app.context.tests.test_deterministic_extraction import stored


def fixture():
    message=stored('Need 12 burgers tomorrow').model_dump(mode='json')
    text=message['raw']['text']
    fields=[]
    for name,value,quote in [('sku','BURGER','burgers'),('quantity','12','12')]:
        start=text.index(quote)
        fields.append({'field_name':name,'value':value,'validation_status':'VALID','evidence':[
            {'method':'RULE','quote':quote,'start':start,'end':start+len(quote),'message_id':message['message_id']} ]})
    row={'message':message,'latest_stored_fields':fields,'contexts':[]}
    label={'group':0,'sku':'BURGER','quantity':12,'quantity_required':True,'unit':None,'delivery':None}
    return row,label


def test_correct_literal_extraction_does_not_imply_context_or_human_confirmation():
    row,label=fixture()
    assert verify_record(row,label)['status']=='VERIFIED_CORRECT'
    row['contexts']=[{'items':[{'sku':'BURGER','quantity':'99','unit':'pcs'}]}]
    assert verify_record(row,label)['status']=='INSUFFICIENT_EVIDENCE'


def test_wrong_normalization_and_false_sku_are_deterministic_defects():
    row,label=fixture()
    row['latest_stored_fields'][1]['value']='99'
    assert 'unsupported_or_wrong_quantity' in verify_record(row,label)['defects']
    row,label=fixture()
    label['sku']=None
    assert 'unsupported_or_wrong_sku' in verify_record(row,label)['defects']


def test_original_span_mismatch_is_not_hidden_by_schema_validity():
    row,label=fixture()
    row['latest_stored_fields'][0]['evidence'][0]['start']=0
    assert 'original_evidence_mismatch' in verify_record(row,label)['defects']


def test_unavailable_human_review_is_not_misclassified_as_false_original_quantity():
    row,label=fixture()
    quantity=row['latest_stored_fields'][1]
    quantity['value']='99'
    quantity['evidence'][0]['method']='HUMAN'
    assert verify_record(row,label)['status']=='INSUFFICIENT_EVIDENCE'


def test_missing_results_unknown_annotation_and_ambiguity_are_separate():
    row,label=fixture()
    label['ambiguity']='Quantity association needs clarification'
    assert verify_record(row,label)['status']=='AMBIGUOUS'
    row['latest_stored_fields']=[]
    assert verify_record(row,label)['status']=='INSUFFICIENT_EVIDENCE'
    assert verify_record(row,None)['status']=='NOT_REVIEWED'


def test_stated_clock_cannot_be_verified_as_date_only():
    row,label=fixture()
    source=row['message']['raw']['received_at']
    from datetime import datetime,timedelta
    from zoneinfo import ZoneInfo
    date=datetime.fromisoformat(source).astimezone(ZoneInfo('Asia/Kuala_Lumpur')).date()+timedelta(days=1)
    text=row['message']['raw']['text']; start=text.index('tomorrow')
    row['latest_stored_fields'].append({'field_name':'requested_delivery_at','value':date.isoformat(),
        'validation_status':'VALID','qualifier':'DATE_ONLY','evidence':[{'method':'RULE','quote':'tomorrow',
        'start':start,'end':start+8,'message_id':row['message']['message_id']}]})
    label['delivery']={'days':1,'hour':15,'qualifier':'EXACT'}
    assert 'date_only_dropped_stated_clock_or_wrong_date' in verify_record(row,label)['defects']


def test_snapshot_hash_prevents_reusing_verdicts_on_new_or_modified_messages(tmp_path):
    from app.context.experiments.verify_historical_semantics import evaluate
    snapshot=tmp_path/'snapshot.json';snapshot.write_text('{}',encoding='utf-8')
    labels=tmp_path/'labels.json';labels.write_text('{"snapshot_sha256":"wrong"}',encoding='utf-8')
    with pytest.raises(ValueError,match='Snapshot differs'):
        evaluate(snapshot,labels)
