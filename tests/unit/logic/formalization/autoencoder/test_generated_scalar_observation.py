"""Actual same-pass scalar observations and posthoc labels, never qualification."""
from copy import deepcopy
import math
import random
import time

import pytest

torch = pytest.importorskip('torch')
from ipfs_datasets_py.logic.formalization.autoencoder import generated_scalar_observation as subject
from ipfs_datasets_py.logic.formalization.autoencoder import generated_field_training as fields
from ipfs_datasets_py.logic.formalization.autoencoder import ordered_clause_recurrent_decoder_experiment as recurrent
from .test_contextual_generated_boundary_training import scripted
from .test_generated_field_training import labelled
from .test_clause_source_context import transform
from .test_long_span_cardinality_training import validate_rule


@pytest.fixture(autouse=True)
def one_cpu():
    previous=torch.get_num_threads();torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def collect(model,codec,rows,contexts,**options):
    return subject.collect_source_scalar_trace(model,rows,codec=codec,input_transform=options.pop('input_transform',transform(model.dimension)),
        source_contexts=contexts,deadline=options.pop('deadline',time.monotonic()+30),**options)


def score(trace,codec,rows,contexts,**options):
    train,refs=labelled(rows,contexts,codec,wrong=options.pop('wrong',False))
    return subject.score_scalar_trace(trace,train,refs,split=options.pop('split','training'),codec=codec,
        input_transform=options.pop('input_transform',transform(trace['dimension'])),source_contexts=contexts,
        validate_rule=validate_rule,deadline=options.pop('deadline',time.monotonic()+30),**options)


def resign(trace):
    trace['trace_sha256']=subject.core.digest({k:v for k,v in trace.items() if k!='trace_sha256'})
    return trace


@pytest.mark.parametrize('kind',['clause','action','recurrent'])
@pytest.mark.parametrize('dimension',[8,384,768])
def test_trace_preserves_exact_existing_generated_predictions_and_call_count(kind,dimension):
    model,codec,rows,contexts=scripted(kind,dimension=dimension)
    old=fields.collect_source_generated_sites(model,rows,codec=codec,input_transform=transform(dimension),
        source_contexts=contexts,deadline=time.monotonic()+30)
    trace=collect(model,codec,rows,contexts)
    assert trace['predictions']==old['predictions']
    assert trace['greedy_batch_steps']==trace['recurrent_readout_calls']==old['greedy_batch_steps']
    assert trace['scalar_site_count']==old['available_field_sites']==8
    assert trace['extra_model_passes']==trace['source_head_extra_evaluations']==0
    for site in trace['rows'][0]['scalar_sites']:
        raw=torch.tensor(site['raw_recurrent_logits']);source=torch.tensor(site['applied_source_logits'])
        assert torch.equal(raw+source,torch.tensor(site['combined_logits']))
        assert len(raw)==len(codec['target_vocabulary'])
    result=score(trace,codec,rows,contexts)
    assert result['scored_sites']==8 and not result['unscored_sites'] and not result['unvisited_reference_sites']
    assert all(x['combined_correct']==x['scored']==2 for x in result['per_field'].values())
    assert not result['qualified'] and not result['admitted'] and not result['lake_executed']


def test_model_modes_existing_gradients_rng_sources_and_unrelated_hooks_preserved():
    model,codec,rows,contexts=scripted()
    model.train();model.body.eval();next(model.parameters()).grad=torch.ones_like(next(model.parameters()))
    snapshot=subject.boundary._snapshot(model,torch)
    original=(deepcopy(rows),deepcopy(contexts));observed=[]
    handle=model.body.body.body.target_embedding.register_forward_hook(lambda *args: observed.append(1))
    try:
        trace=collect(model,codec,rows,contexts)
        subject.boundary._preserved(model,torch,snapshot)
        assert original==(rows,contexts) and observed
        assert handle.id in model.body.body.body.target_embedding._forward_hooks
        assert not model.body.body.body.output._forward_hooks
        assert trace['caller_exclusive_model_access_required'] is True
    finally:handle.remove()


def test_actual_cached_source_overriding_or_overridden_margin_is_scored_full_vocabulary():
    model,codec,rows,contexts=scripted()
    trace=collect(model,codec,rows,contexts)
    result=score(trace,codec,rows,contexts,wrong=True)
    assert result['scored_sites']==8
    for event in result['events']:
        original=next(s for r in trace['rows'] if r['id']==event['id'] for s in r['scalar_sites'] if s['position']==event['position'])
        y=event['target_token_id'];chosen=event['actual_next_token_id']
        for name,key in [('source','applied_source_logits'),('recurrent','raw_recurrent_logits'),('combined','combined_logits')]:
            values=original[key];expected=torch.nn.functional.cross_entropy(torch.tensor([values],dtype=torch.float64),torch.tensor([y])).item()
            assert event[name]['full_vocabulary_cross_entropy']==pytest.approx(expected,abs=1e-12)
            assert event[name]['target_minus_best_other']==values[y]-max(v for i,v in enumerate(values) if i!=y)
            assert event[name]['target_minus_emitted']==values[y]-values[chosen]
        assert event['combined']['target_minus_emitted']==pytest.approx(event['source']['target_minus_emitted']+event['recurrent']['target_minus_emitted'],abs=1e-5)


def test_posthoc_development_is_labeled_and_never_training_loss(monkeypatch):
    model,codec,rows,contexts=scripted()
    trace=collect(model,codec,rows,contexts)
    monkeypatch.setattr(subject.core,'_greedy',lambda *a,**k:pytest.fail('scoring executed a model'))
    result=score(trace,codec,rows,contexts,split='exposed_development')
    assert result['split']=='exposed_development' and result['split_is_caller_declared']
    assert not result['models_executed'] and not result['training_loss_returned']
    assert result['reference_labels_used_only_after_rollout']


@pytest.mark.parametrize('key',['target_ids','reference','expected_count','desired_prefix'])
def test_collector_rejects_labels_before_generation(monkeypatch,key):
    model,codec,rows,contexts=scripted();rows[0][key]=[1,2]
    monkeypatch.setattr(subject.core,'_greedy',lambda *a,**k:pytest.fail('poisoned generation'))
    with pytest.raises(ValueError,match='source.only'):collect(model,codec,rows,contexts)
    assert not model.body.body.body.output._forward_hooks


@pytest.mark.parametrize('invalid',[False,True])
def test_unavailable_unvisited_and_malformed_sites_receive_no_fabricated_labels(invalid):
    model,codec,rows,contexts=scripted(count=9,invalid=invalid)
    trace=collect(model,codec,rows,contexts)
    result=score(trace,codec,rows,contexts)
    if invalid:
        assert trace['scalar_site_count']==0 and result['scored_sites']==0
        assert len(result['unvisited_reference_sites'])==8
    else:
        assert trace['scalar_site_count']==36 and result['scored_sites']==8
        assert len(result['unscored_sites'])==28 and not result['unvisited_reference_sites']
        for site in trace['rows'][0]['scalar_sites'][8:]:
            assert site['source_clause_sha256'] is None and not site['source_slot_available']
            assert not any(site['applied_source_logits'])
        assert not trace['rows'][0]['scalar_sites'][-1]['source_guidance_active']


@pytest.mark.parametrize('bad', [True,False,0,-1,None,float('nan')])
def test_memory_budget_types_and_bounds_fail_before_rollout(monkeypatch,bad):
    model,codec,rows,contexts=scripted()
    monkeypatch.setattr(subject.core,'_greedy',lambda *a,**k:pytest.fail('bad budget generation'))
    with pytest.raises(ValueError):collect(model,codec,rows,contexts,max_memory_bytes=bad)


def test_small_budget_fails_before_hook_or_model_pass(monkeypatch):
    model,codec,rows,contexts=scripted()
    monkeypatch.setattr(subject.core,'_greedy',lambda *a,**k:pytest.fail('budget exceeded generation'))
    with pytest.raises(ValueError,match='memory estimate'):collect(model,codec,rows,contexts,max_memory_bytes=1)
    assert not model.body.body.body.output._forward_hooks


@pytest.mark.parametrize('failure',['exception','deadline','invalid_decomposition'])
def test_error_removes_hooks_preserves_state_and_releases_exclusive_guard(monkeypatch,failure):
    model,codec,rows,contexts=scripted();snapshot=subject.boundary._snapshot(model,torch)
    original=model.next_logits
    def changed(tokens,state):
        logits,updated=original(tokens,state)
        if failure=='exception':raise RuntimeError('synthetic failure')
        if failure=='deadline':raise TimeoutError('synthetic deadline')
        return logits+1,updated
    monkeypatch.setattr(model,'next_logits',changed)
    with pytest.raises((ValueError,RuntimeError,TimeoutError)):collect(model,codec,rows,contexts)
    assert not model.body.body.body.output._forward_hooks and id(model) not in subject._ACTIVE_MODELS
    subject.boundary._preserved(model,torch,snapshot)
    monkeypatch.setattr(model,'next_logits',original)
    assert collect(model,codec,rows,contexts)['complete']


def test_concurrent_same_instance_refused_and_existing_readout_hooks_not_removed():
    model,codec,rows,contexts=scripted()
    with subject._exclusive(model):
        with pytest.raises(ValueError,match='concurrent'):collect(model,codec,rows,contexts)
    handle=model.body.body.body.output.register_forward_hook(lambda *args:None)
    try:
        with pytest.raises(ValueError,match='unhooked'):collect(model,codec,rows,contexts)
        assert handle.id in model.body.body.body.output._forward_hooks
    finally:handle.remove()


@pytest.mark.parametrize('key,value',[('scalar_site_count',True),('sample_count',True),('optimizer_steps',False),('greedy_batch_steps',1),('recurrent_readout_calls',1)])
def test_rehashed_counter_tampering_rejected(key,value):
    model,codec,rows,contexts=scripted();trace=collect(model,codec,rows,contexts)
    trace[key]=value
    if key=='greedy_batch_steps':trace['recurrent_readout_calls']=value
    resign(trace)
    with pytest.raises(ValueError):score(trace,codec,rows,contexts)


@pytest.mark.parametrize('key,value',[('slot',1),('position',0),('source_slot_available',False),('actual_next_token_id',0),('source_clause_sha256','0'*64)])
def test_rehashed_site_tampering_rejected(key,value):
    model,codec,rows,contexts=scripted();trace=collect(model,codec,rows,contexts)
    trace['rows'][0]['scalar_sites'][0][key]=value;resign(trace)
    with pytest.raises(ValueError):score(trace,codec,rows,contexts)


def test_stale_context_input_transform_and_reference_tokens_rejected():
    model,codec,rows,contexts=scripted();trace=collect(model,codec,rows,contexts)
    stale=deepcopy(rows);stale[0]['input'][0]+=.01
    with pytest.raises(ValueError):score(trace,codec,stale,contexts)
    changed=transform(8);changed['scale']=2
    with pytest.raises(ValueError):score(trace,codec,rows,contexts,input_transform=changed)
    train,refs=labelled(rows,contexts,codec);train[0]['target_ids'][1]=2
    with pytest.raises(ValueError):subject.score_scalar_trace(trace,train,refs,split='training',codec=codec,input_transform=transform(8),source_contexts=contexts,validate_rule=validate_rule,deadline=time.monotonic()+30)


@pytest.mark.parametrize('scoring',[False,True])
def test_deadline_after_final_digest_is_enforced(monkeypatch,scoring):
    model,codec,rows,contexts=scripted();trace=collect(model,codec,rows,contexts)
    digest=subject.core.digest;finished=False
    def observe(value):
        nonlocal finished
        schema=subject.SCORE_SCHEMA if scoring else subject.SCHEMA
        seal='score_sha256' if scoring else 'trace_sha256'
        if isinstance(value,dict) and value.get('schema')==schema and seal not in value:
            finished=True
        return digest(value)
    def deadline(value):
        if finished:raise TimeoutError('after final digest')
    monkeypatch.setattr(subject.core,'digest',observe);monkeypatch.setattr(subject,'_deadline',deadline)
    with pytest.raises(TimeoutError,match='final digest'):
        score(trace,codec,rows,contexts) if scoring else collect(model,codec,rows,contexts)
    assert not model.body.body.body.output._forward_hooks and id(model) not in subject._ACTIVE_MODELS


def test_controls_are_rejected_without_copying_or_running():
    model,codec,rows,contexts=scripted()
    control=recurrent.bind_residual_off_model(model)
    with pytest.raises(ValueError,match='architecture'):collect(control,codec,rows,contexts)


@pytest.mark.parametrize('key,value',[('model_schema','unknown/v1'),('model_tensor_sha256',None),
    ('model_tensor_sha256','F'*64),('generation_temperature',False),('vocabulary_size',True)])
def test_rehashed_architecture_provenance_and_exact_counter_types_rejected(key,value):
    model,codec,rows,contexts=scripted();trace=collect(model,codec,rows,contexts)
    trace[key]=value;resign(trace)
    with pytest.raises(ValueError):score(trace,codec,rows,contexts)


@pytest.mark.parametrize('kind',['boolean_grammar','float_overflow','fake_eos'])
def test_rehashed_scalar_or_prediction_metadata_malformed_values_rejected(kind):
    model,codec,rows,contexts=scripted();trace=collect(model,codec,rows,contexts)
    site=trace['rows'][0]['scalar_sites'][0]
    if kind=='boolean_grammar':site['grammar_before'][4]=False
    elif kind=='float_overflow':site['raw_recurrent_logits'][0]=1e300
    else:trace['predictions'][0]['eos_reached']=1
    resign(trace)
    with pytest.raises(ValueError):score(trace,codec,rows,contexts)


@pytest.mark.parametrize('key,value',[('deadline',True),('deadline',float('nan')),('deadline',0),
    ('max_target_tokens',True),('max_target_tokens',513),('batch_size',False),('batch_size',129)])
def test_bad_generation_bounds_never_leave_a_hook(key,value):
    model,codec,rows,contexts=scripted()
    with pytest.raises((ValueError,TimeoutError)):collect(model,codec,rows,contexts,**{key:value})
    assert not model.body.body.body.output._forward_hooks and id(model) not in subject._ACTIVE_MODELS
