"""Model-free contracts for the three executable, one blocked width comparison."""
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import time
from types import SimpleNamespace

import pytest

PATH=Path(__file__).resolve().parents[5]/'scripts/ops/autoencoder/benchmark_multidimension_modality_training.py'
SPEC=importlib.util.spec_from_file_location('_multidimension_modality_runner_tests',PATH)
subject=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(subject)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def test_six_registered_jobs_leave4096_closed_and_teacher_separate():
    assert [(d,s,a['name']) for d,s,a in subject.jobs()]==[(d,1729,a['name']) for d in (8,384,768) for a in subject.ARMS]
    assert subject.jobs()[0][2] is not subject.ARMS[0]
    ready=subject.readiness()
    assert ready['requested_dimensions']==[8,384,768,4096] and ready['executable_dimensions']==[8,384,768]
    assert ready['blocked_dimensions']['4096']['reason']=='trusted_native_owner_integration_required'
    assert ready['blocked_dimensions']['4096']['training_executed'] is False
    assert ready['historical8_teacher_distinct_from_native8_formula_sidecar']
    assert all(ready[k] is False for k in subject.FALSE)


@pytest.mark.parametrize('key,value',[('dimensions',[8,384,768,4096]),('seed_order',[1729,2718]),('fit_count',8),
    ('requested_dimensions',[8,384,768]),('fixed_encoder_context_tokens',1024),('fixed_decoder_output_limit',1024),
    ('temperature',1),('auxiliary_sampler','content_matched_cycles'),('generated_boundary_weight',0.),
    ('auxiliary_batch_size',12),('auxiliary_full_vocabulary_size',3),('non_action_learning_rate_multiplier',1.),
    ('selection_unchanged',False),('production_promotion_allowed',True),('teacher_distillation_used',True),
    ('encoder_executed_during_training',True),('baseline_replay_required',False)])
def test_recipe_cannot_drift(key,value):
    plan=deepcopy(subject.FIXED);subject.validate_plan(plan);plan[key]=value
    with pytest.raises(ValueError,match='fixed multidimension'):subject.validate_plan(plan)


@pytest.mark.parametrize('dimension',[8,384,768])
@pytest.mark.parametrize('positive',[False,True])
def test_only_auxiliary_arm_changes_objective_and_retry(dimension,positive):
    calls=[];ctx=dict(dimension=dimension,owners={'long_span_source_value_training':SimpleNamespace(train=lambda *a,**k:calls.append((a,k)))},
        rows={'train':['training'],'validation':['development']},references={'train':['train labels'],'validation':['dev labels']},
        donor={'codec':{},'input_transform':{}},lineage={},validate_rule='validator',validator_id='id',stages=[],source_contexts={},
        modality_banks={'used113':{'dimension':dimension}})
    subject.train_candidate(ctx,'model',1729,subject.ARMS[int(positive)]);args,kw=calls[0]
    assert args==('model',['training'],['development'])
    assert 'auxiliary_source_modality_sampler' not in kw
    assert kw['config']['max_seconds']==180 and kw['config']['max_target_tokens']==512 and kw['config']['seed']==1729
    assert kw['generated_boundary_weight']==kw['action_contrastive_weight']==.05
    assert kw['source_value_weight']==kw['cardinality_weight']==.25 and kw['non_action_learning_rate_multiplier']==10.
    if positive:
        assert kw['auxiliary_source_modality_bank'] is ctx['modality_banks']['used113']
        assert kw['auxiliary_source_modality_weight']==.05 and kw['generated_boundary_retry_on_mismatch'] is True
    else:
        assert not any(k.startswith('auxiliary_source_modality') or k.startswith('generated_boundary_retry') for k in kw)


def vector(index,width):
    values=[0.]*width;values[0]=math.cos(index/1000);values[1]=math.sin(index/1000)
    return values


def fixture(dimension=8):
    vocabulary=['<pad>','<bos>','<eos>','"O"','"P"','"F"']+['unused'+str(i) for i in range(26)]
    rules={};rows=[];cache=[]
    for index in range(113):
        text=f'The actor{index} must act the record.'
        rule=dict(actor='actor'+str(index),action='act',modality='O',object='record',conditions=[],exceptions=[],temporal=[])
        rules[text]=rule;original=vector(index+1,384)
        rows.append(dict(id='original-'+str(index),source_text=text,wording_style=0,input=original,
            source_sha256=hashlib.sha256(text.encode()).hexdigest(),input_sha256=digest(original),
            target_sha256=digest({'rules':[rule]}),modality='O',modality_token_id=3))
        cache.append(dict(id='clause:'+rows[-1]['source_sha256'],source_text=text,input=vector(index+1,dimension)))
    bank=dict(dimension=384,bank_kind='used113',selected_rows=113,rows=rows,input_sha256={'source_rows':'original384-vector-envelope'})
    bank['bank_sha256']=digest(bank)
    def checked_vector(v):
        assert type(v) is list and len(v) in (8,384,768) and all(type(x) in (int,float) and math.isfinite(x) for x in v)
        assert abs(sum(x*x for x in v)-1)<1e-4
    def binding(bank,train,validation,*,source_contexts,codec,deadline):
        expected=source_contexts['expected']
        assert all(row['input']==expected[row['source_text']] for row in bank['rows'])
        return dict(actual_training_unique_clauses=113,dimension=bank['dimension'])
    owner=SimpleNamespace(_vector=checked_vector,_normal=lambda x:' '.join(x.casefold().split()),
        _source=lambda text,style:rules[text] if style==0 else {},validate_training_binding=binding)
    ctx=dict(owners={'source_modality_auxiliary_training':owner},core=SimpleNamespace(digest=digest))
    lane=dict(dimension=dimension,clause_cache={'train':cache},donor={'codec':{'target_vocabulary':vocabulary}},
        rows={'train':['original train'],'validation':['original dev']},
        source_contexts={'expected':{r['source_text']:deepcopy(r['input']) for r in cache}})
    blocked=[dict(id='forbidden',source_text='The forbidden actor must act the record.',input=vector(800,dimension))]
    return ctx,bank,lane,blocked


@pytest.mark.parametrize('dimension',[8,384,768])
def test_cached113_derivation_preserves_original_and_does_not_invent_unused_vectors(dimension):
    ctx,base,lane,blocked=fixture(dimension);before=deepcopy(base)
    bank,receipt=subject.derive_used_bank(ctx,base,lane,blocked,time.monotonic()+10)
    assert base==before and bank['dimension']==dimension and len(bank['rows'])==113
    assert bank['bank_sha256']==digest({k:v for k,v in bank.items() if k!='bank_sha256'})
    assert bank['input_sha256']==base['input_sha256']
    assert bank['cached_used113_derivation']['full180_native_vectors_authenticated'] is False
    assert bank['cached_used113_derivation']['unused67_vectors_materialized'] is False
    assert [r['input'] for r in bank['rows']]==[r['input'] for r in lane['clause_cache']['train']]
    assert receipt['actual_binding']['dimension']==dimension and receipt['complete']
    assert all(receipt[k] is False for k in subject.FALSE)


@pytest.mark.parametrize('mutation',[lambda b,l,f:b.update(bank_sha256='stale'),
    lambda b,l,f:l['clause_cache']['train'].pop(),lambda b,l,f:l['clause_cache']['train'].append(deepcopy(l['clause_cache']['train'][0])),
    lambda b,l,f:l['clause_cache']['train'][0].update(source_text='A changed literal.'),
    lambda b,l,f:l['clause_cache']['train'][0].update(input=vector(999,8)),
    lambda b,l,f:f.append(dict(id='original-0',source_text='different',input=vector(888,8))),
    lambda b,l,f:f.append(dict(id='new',source_text=l['clause_cache']['train'][0]['source_text'].upper(),input=vector(888,8))),
    lambda b,l,f:f.append(dict(id='new',source_text='different',input=l['clause_cache']['train'][0]['input']))])
def test_cache_source_or_forbidden_binding_drift_is_rejected(mutation):
    ctx,bank,lane,blocked=fixture();mutation(bank,lane,blocked)
    with pytest.raises((ValueError,AssertionError)):
        subject.derive_used_bank(ctx,bank,lane,blocked,time.monotonic()+10)


@pytest.mark.parametrize('key,value',[('target_sha256','wrong'),('modality','P'),('modality_token_id',4),('wording_style',1)])
def test_resealed_original_target_metadata_still_checked(key,value):
    ctx,bank,lane,blocked=fixture();bank['rows'][0][key]=value
    bank['bank_sha256']=digest({k:v for k,v in bank.items() if k!='bank_sha256'})
    with pytest.raises((ValueError,KeyError)):
        subject.derive_used_bank(ctx,bank,lane,blocked,time.monotonic()+10)


def test_bank_deadline_aborts_without_mutation():
    ctx,bank,lane,blocked=fixture();original=deepcopy(bank)
    with pytest.raises(ValueError,match='deadline'):
        subject.derive_used_bank(ctx,bank,lane,blocked,time.monotonic()-1)
    assert bank==original


@pytest.mark.parametrize('single',[False,True])
def test_forbidden_container_supports_actual_saved_single_and_multi_schemas(tmp_path,single):
    row=dict(id='source',source_text='Literal source only.',input=vector(20,384))
    value=dict(schema='fresh-scalar-source-inputs-single/v1' if single else 'fresh-scalar-source-inputs/v1',complete=True)
    if single:value.update(dimension=384,rows=[row],clause_cache=[])
    else:value['dimensions']={'384':dict(rows=[row],clause_cache=[])}
    value['inputs_sha256']=digest(value);path=tmp_path/'inputs.json';path.write_text(json.dumps(value))
    ctx=dict(comparison_manifest={'additional_forbidden_source_inputs':[str(path)],'inputs':{str(path):subject.sha(path)}},
        manifest={'exposed_source_inputs':str(path)},core=SimpleNamespace(digest=digest,_vector=lambda v,d:None))
    assert subject.forbidden_inputs(ctx)==[row]
    value['inputs_sha256']='forged';path.write_text(json.dumps(value));ctx['comparison_manifest']['inputs'][str(path)]=subject.sha(path)
    with pytest.raises(ValueError,match='authenticated source-only'):subject.forbidden_inputs(ctx)


def test_preflight_branch_validates_all_widths_without_training(tmp_path,monkeypatch):
    saved=[];bound=[]
    def save(path,value):saved.append((str(path),value));return dict(path=str(path),sha256='receipt')
    ctx=dict(comparison_owner=SimpleNamespace(source_inventory=lambda *a:{}),comparison_parent_args='prior',
        helpers=SimpleNamespace(save=save),comparison_plan={},comparison_manifest={'inputs':{},'extensions':{},'plan_sha256':'plan'},tree={})
    monkeypatch.setattr(subject,'load_context',lambda _:ctx)
    monkeypatch.setattr(subject,'prepare_original_bank',lambda *a:('384',{'banks':{'used113':'bank'}},[]))
    def lane(*args,**kwargs):
        dimension=args[1];return dict(dimension=dimension,preparation={},source_contexts={},rows={},modality_banks={'used113':{}},
            bank_derivation={},prior_margin=SimpleNamespace(ARMS=[{}],validate_initial=lambda *a:{'complete':True}))
    monkeypatch.setattr(subject,'prepare_lane',lane)
    monkeypatch.setattr(subject,'bind_candidate',lambda c,*a:bound.append(c['dimension']) or 'model')
    monkeypatch.setattr(subject,'fit_and_record',lambda *a:pytest.fail('preflight performed optimizer work'))
    monkeypatch.setattr(subject,'sha',lambda _: 'plan')
    args=SimpleNamespace(phase='preflight',output=tmp_path/'new',plan=tmp_path/'plan',extension_root=tmp_path)
    result=subject.execute(args)
    assert bound==[8,384,768] and result['complete'] and result['training_executed'] is False
    assert result['dimensions_actually_trained']==[] and len(result['preflights'])==3
