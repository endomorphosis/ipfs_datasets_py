from copy import deepcopy
import pytest
from scripts.ops.legal_ir import prepare_legal_native768_contexts as subject


def sources():
    result={}
    for split in subject.SPLITS:
        text=split+' source'
        result[split]=[{'id':split,'source_text':text,'source_sha256':subject.hashlib.sha256(text.encode()).hexdigest()}]
    return result


def receipt(source):
    return {'schema':'gte-multilingual-embedding-receipt/v1','id':'cached-id','source_sha256':source['source_sha256'],
        'profile_id':'profile','dimension':768,'embedding':[1.]+[0.]*767,'token_count_including_special_tokens':5,
        'token_input_sha256':'a'*64,'truncated':False,'normalized':True,'asset_manifest_sha256':'b'*64}


def test_source_only_splits_preserve_order_and_reject_targets():
    rows=sources()
    assert subject.source_splits(rows) == rows
    rows['train'][0]['canonical_ir']={}
    with pytest.raises(ValueError,match='must not contain targets'):
        subject.source_splits(rows)


@pytest.mark.parametrize('case',['hash','duplicate','missing_split'])
def test_identity_errors_fail_closed(case):
    rows=sources()
    if case=='hash':rows['train'][0]['source_sha256']='0'*64
    if case=='duplicate':rows['tuning'][0]['id']='train'
    if case=='missing_split':rows.pop('oov')
    with pytest.raises(ValueError):subject.source_splits(rows)


def test_duplicate_texts_with_distinct_ids_are_not_synthetic_vectors():
    rows=sources();rows['oov'].append({**rows['oov'][0],'id':'second-observation'})
    checked=subject.source_splits(rows)
    assert len(checked['oov']) == 2
    assert checked['oov'][0]['source_sha256'] == checked['oov'][1]['source_sha256']


def test_native_receipt_accepts_exact_bound_profile():
    native=receipt(sources()['train'][0])
    subject.valid_native_receipt(native,profile_id='profile',asset_sha256='b'*64)


@pytest.mark.parametrize('field,value',[('dimension',384),('truncated',True),('normalized',False),
    ('profile_id','substitute'),('embedding',[0.]*768),('token_count_including_special_tokens',8193)])
def test_synthetic_or_wrong_profile_receipts_rejected(field,value):
    native=receipt(sources()['train'][0]);native[field]=value
    with pytest.raises(ValueError):subject.valid_native_receipt(native,profile_id='profile',asset_sha256='b'*64)


def test_context_preserves_upstream_receipt_identity_and_binds_new_id():
    source=sources()['train'][0];native=receipt(source);before=deepcopy(native)
    upstream={'receipt':native,'producer_report':{'path':'/report','bytes':1,'sha256':'c'*64}}
    row=subject.make_context(source,upstream,source_artifact={'path':'/sources','bytes':1,'sha256':'d'*64},producer_sha256='e'*64,reused=True)
    stage=row['native_stage_receipt']
    assert row['id']=='train' and stage['upstream_receipt_id']=='cached-id'
    assert stage['source_sha256']==native['source_sha256']
    assert stage['vector_sha256']==row['context_sha256']==subject.digest(native['embedding'])
    assert stage['receipt_sha256']==subject.digest({k:v for k,v in stage.items() if k!='receipt_sha256'})
    assert stage['target_access'] is False and stage['proof_authority'] is False
    assert native==before


def test_context_rejects_source_receipt_mismatch():
    source=sources()['train'][0];native=receipt(sources()['tuning'][0])
    with pytest.raises(ValueError,match='source differ'):
        subject.make_context(source,{'receipt':native,'producer_report':{}},source_artifact={},producer_sha256='x',reused=True)


def test_pinned_artifact_mutation_rejected(tmp_path):
    reference=subject.write(tmp_path/'artifact.json',{'ok':True})
    assert subject.read(reference)=={'ok':True}
    (tmp_path/'artifact.json').write_text('{"ok":false}')
    with pytest.raises(ValueError,match='changed'):subject.read(reference)
