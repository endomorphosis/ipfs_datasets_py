"""Source-shape and native evidence contracts, with explicitly mocked producers."""
from copy import deepcopy
from pathlib import Path
import time

import pytest
from ipfs_datasets_py.logic.formalization.autoencoder import prospective_wording_source_inputs as owner
from ipfs_datasets_py.logic.formalization.autoencoder import source_embeddings_768_complete as complete
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_embedding_runtime as runtime


def plan():
    rows = [dict(id=f'fixture:{i}', source_text=f'Fixture sentence {i}.') for i in range(60)]
    return owner.source_plan(rows, expected_source_rows_sha256=owner.digest(rows), sealed_recipe_sha256='a'*64)


def assets(d):
    return {'snapshot_path':'/fixture/snapshot'} if d == 384 else dict(manifest_path='/fixture/manifest',
        expected_manifest_sha256='b'*64, model_directory='/fixture/model', code_directory='/fixture/code')


def payload(p, d):
    representation = dict(dimension=d, semantic_embedding=True, device='cpu', dtype='float32',
        experiment_token_limit=512, actual_forward_tokens_verified=True)
    if d == 384:
        representation.update(kind='native_gte_small_semantic_embedding', model_id='thenlper/gte-small', revision=runtime.PINNED_REVISION)
    else:
        representation.update(kind='native_gte_multilingual_semantic_embedding', profile_id=complete.PROFILE_ID,
            historical_profile_token_limit=8192, cached_profile_relabelled=False)
    native = {'explicit_test_double':True}
    if d == 384: native['execution'] = dict(batch_size=4)
    else: native['execution_profile'] = dict(batch_size=4, device='cpu', dtype='float32', pooling='cls',
        normalization='l2', max_tokens_including_special_tokens=512, attention_implementation='eager')
    return dict(vectors=[dict(id=r['id'], source_sha256=owner.native.authored.text_sha(r['source_text']),
        vector=[1.]+[0.]*(d-1), token_count=2, token_input_sha256='b'*64) for r in p['source_inputs']],
        native_production=native, producer_files=owner.native._pins(), source_artifact=None,
        representation=representation)


def report(monkeypatch, d):
    p = plan()
    monkeypatch.setattr(owner.native, '_produce'+str(d), lambda shape,*args:payload(shape,d))
    monkeypatch.setattr(owner.native, '_validate_native_binding', lambda *args:None)
    value = owner.produce_width(p, dimension=d, asset_config=assets(d),
        source_artifact_directory=Path('/fixture/sources') if d == 384 else None)
    return p, value


def resign(value):
    value['production_sha256'] = owner.digest({k:v for k,v in value.items() if k != 'production_sha256'})


def test_closed_sixty_single_sources_have_complete_aliases_and_preserve_input():
    p = plan(); rows = deepcopy(p['shape_plan']['source_rows'])
    assert len(p['shape_plan']['source_inputs']) == 60 and len(p['shape_plan']['source_aliases']) == 120
    assert owner._plan(p) == p and rows == p['shape_plan']['source_rows']
    assert p['role'] == 'prospective_development' and all(p[k] is False for k in owner.FALSE)


@pytest.mark.parametrize('mutation',['missing','target','duplicate_id','duplicate_normalized','paragraph','hash'])
def test_invalid_or_labelled_sources_refuse_before_native_work(mutation, monkeypatch):
    p = plan(); rows = deepcopy(p['shape_plan']['source_rows']); sha = owner.digest(rows)
    if mutation == 'missing': rows.pop()
    elif mutation == 'target': rows[0]['target'] = {}
    elif mutation == 'duplicate_id': rows[1]['id'] = rows[0]['id']
    elif mutation == 'duplicate_normalized': rows[1]['source_text'] = rows[0]['source_text'].upper().replace(' ','  ')
    elif mutation == 'paragraph': rows[0]['source_text'] += '\n\nSecond clause.'
    if mutation != 'hash': sha = owner.digest(rows)
    else: sha = '0'*64
    with pytest.raises(ValueError): owner.source_plan(rows, expected_source_rows_sha256=sha, sealed_recipe_sha256='a'*64)


@pytest.mark.parametrize('d',[384,768])
def test_same_native_evidence_validator_runs_and_source_contexts_are_complete(d,monkeypatch):
    p, value = report(monkeypatch,d); calls=[]
    monkeypatch.setattr(owner.native,'_validate_native_binding',lambda shape,v:calls.append((shape,v)))
    result=owner.assemble(p,value,dimension=d)
    assert len(calls)==1 and calls[0][0]==p['shape_plan'] and calls[0][1] is value
    assert len(result['rows'])==len(result['clause_cache'])==len(result['source_contexts'])==60
    assert all(set(r)=={'id','source_text','input'} for r in result['rows'])
    assert all(len(c['segments'])==1 for c in result['source_contexts'].values())
    assert result['targets_attached'] is False and result['qualified'] is result['admitted'] is False


@pytest.mark.parametrize('field,value',[('dimension',8),('dimension',True),('batch_size',2),
    ('max_seconds',True),('max_seconds',float('nan')),('max_seconds',601)])
def test_runtime_policy_fails_before_any_producer(field,value,monkeypatch):
    args=dict(dimension=768,asset_config=assets(768)); args[field]=value
    monkeypatch.setattr(owner.native,'_produce768',lambda *args:pytest.fail('native work started'))
    with pytest.raises(ValueError): owner.produce_width(plan(),**args)


@pytest.mark.parametrize('field,value',[('admitted',True),('batch_size',2),('max_seconds',601),
    ('receipt_count',59),('role','train_augmentation'),('encoder_executed',False)])
def test_rehashed_forged_report_still_refuses(field,value,monkeypatch):
    p,r=report(monkeypatch,768); r[field]=value; resign(r)
    with pytest.raises(ValueError): owner.validate_report(p,r)


def test_deadline_after_forward_refuses_complete_receipt(monkeypatch):
    clock=[0.]; monkeypatch.setattr(owner.time,'monotonic',lambda:clock[0])
    def overdue(shape,*args):
        result=payload(shape,768);clock[0]=10.;return result
    monkeypatch.setattr(owner.native,'_produce768',overdue)
    with pytest.raises(TimeoutError): owner.produce_width(plan(),dimension=768,asset_config=assets(768),max_seconds=1)


def test_native_binding_failure_cannot_be_skipped(monkeypatch):
    p,r=report(monkeypatch,768)
    def reject(*args):raise ValueError('native receipt mismatch')
    monkeypatch.setattr(owner.native,'_validate_native_binding',reject)
    with pytest.raises(ValueError,match='native receipt mismatch'):owner.assemble(p,r,dimension=768)


@pytest.mark.parametrize('d,field,value',[(384,'model_id','other/model'),(384,'revision','foreign'),
    (384,'kind','unverified'),(768,'profile_id','foreign'),(768,'historical_profile_token_limit',512),
    (768,'cached_profile_relabelled',True),(768,'kind','unverified')])
def test_rehashed_representation_cannot_relabel_actual_producer(d,field,value,monkeypatch):
    p,r=report(monkeypatch,d);r['representation'][field]=value;resign(r)
    with pytest.raises(ValueError,match='profile'):owner.validate_report(p,r)


@pytest.mark.parametrize('d,field,value',[(384,'batch_size',8),(768,'batch_size',16),
    (768,'device','cuda'),(768,'pooling','mean'),(768,'max_tokens_including_special_tokens',8192)])
def test_outer_policy_cannot_disagree_with_native_execution(d,field,value,monkeypatch):
    p,r=report(monkeypatch,d)
    key='execution' if d==384 else 'execution_profile'
    r['native_production'][key][field]=value;resign(r)
    with pytest.raises(ValueError,match='native'):owner.validate_report(p,r)
