"""Synthetic self-prefix supervision invariants; no real checkpoint training."""
from copy import deepcopy
import math
import random
import time

import pytest

torch=pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import generated_boundary_training as subject
from .test_boundary_source_diagnostic import scripted,plain
from .test_projected_source_decoder_experiment import encode,rule


@pytest.fixture(autouse=True)
def one_cpu():
    old=torch.get_num_threads();torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


def collect(model,codec,rows,**options):
    return subject.collect_source_boundary_prefixes(model,rows,codec=codec,
        input_transform=dict(mean=[0.]*8,scale=1.),max_target_tokens=options.pop('max_target_tokens',128),
        batch_size=2,deadline=options.pop('deadline',time.monotonic()+30),**options)


def loss(model,codec,collection,counts,**options):
    return subject.generated_boundary_loss(torch,model,collection,counts,codec=codec,
        input_transform=dict(mean=[0.]*8,scale=1.),deadline=options.pop('deadline',time.monotonic()+30),**options)


def test_actual_greedy_parity_and_separate_training_count_labels():
    model,codec,rows,_=scripted('shared',count_bias=1.)
    expected=plain(model,codec,rows);col=collect(model,codec,rows)
    assert [r['token_ids'] for r in col['predictions']]==expected[1]
    assert [r['generation_status'] for r in col['predictions']]==expected[2]
    a=loss(model,codec,col,{'0':1,'1':2});b=loss(model,codec,col,{'0':3,'1':3})
    assert [e['action'] for e in a['receipt']['events']]==['stop','stop','continue','stop']
    assert [e['action'] for e in b['receipt']['events']]==['continue']*4
    # Varying loss supervision never alters collection or generation inputs.
    assert [r['token_ids'] for r in col['predictions']]==expected[1]
    assert col['reference_count_access'] is False and col['reference_prefix_access'] is False
    assert a['receipt']['target_prefixes_used'] is False


def test_full_vocabulary_ce_and_equal_row_reduction_are_exact():
    model,codec,rows,_=scripted('shared');col=collect(model,codec,rows)
    result=loss(model,codec,col,{'0':1,'1':2});expected=0.
    for event in result['receipt']['events']:
        logits=event['replay_logits'];maximum=max(logits)
        ce=maximum+math.log(sum(math.exp(v-maximum) for v in logits))-logits[event['target_token_id']]
        assert len(logits)==len(codec['target_vocabulary'])
        assert event['cross_entropy']==pytest.approx(ce,abs=2e-6)
        row=next(r for r in result['receipt']['generation']['rows'] if r['id']==event['id'])
        assert event['consumed_prefix_length']==event['position']+1
        assert event['consumed_prefix_sha256']==subject.core.digest(row['consumed_prefix'][:event['position']+1])
        expected+=ce*event['mean_loss_coefficient']
    assert float(result['loss'].detach())==pytest.approx(expected,abs=2e-6)
    assert result['receipt']['rows_replayed_once'] is True
    assert result['receipt']['selected_sites']==4


def test_replay_backpropagates_into_actual_recurrent_and_count_parameters():
    model,codec,rows,_=scripted('shared');col=collect(model,codec,rows)
    before=subject.core.tensor_digest(model);result=loss(model,codec,col,{'0':1,'1':1})
    assert result['loss'].requires_grad
    result['loss'].backward()
    assert model.body.body.body.output.weight.grad is not None
    assert torch.count_nonzero(model.body.body.body.output.weight.grad)>0
    assert model.body.count_head.bias.grad is not None and torch.count_nonzero(model.body.count_head.bias.grad)>0
    assert subject.core.tensor_digest(model)==before  # No optimizer step belongs to the helper.
    assert all(p.grad is None for n,p in model.named_parameters() if 'projection_down.' in n or 'projection_up.' in n)


def test_first_last_policy_keeps_overrun_boundary_and_reports_all_dropped_sites():
    model,codec,rows,_=scripted('shared');body=model.body.body.body
    sequence=encode(codec,{'rules':[rule()]*9})[1:]
    class Positions(torch.nn.Module):
        def forward(self,values,hidden):
            pos=hidden[0,:,0].long();out=torch.zeros(len(values),values.shape[1],len(sequence))
            for offset in range(values.shape[1]):out[:,offset].scatter_(1,(pos+offset).clamp(max=len(sequence)-1).unsqueeze(1),1.)
            updated=hidden.clone();updated[0,:,0]+=values.shape[1]
            return out,updated
    body.decoder=Positions();body.output=torch.nn.Linear(len(sequence),len(codec['target_vocabulary']))
    with torch.no_grad():
        body.output.weight.fill_(-20.);body.output.bias.zero_()
        for step,token in enumerate(sequence):body.output.weight[token,step]=20.
    col=collect(model,codec,rows,max_target_tokens=512)
    assert col['available_sites']==18 and col['selected_sites']==4 and col['ignored_sites']==14
    for row in col['rows']:
        assert [s['completed_rules'] for s in row['selected_sites']]==[1,9]
        assert len(row['available_sites'])==9 and row['replay_prefix_tokens']==row['selected_sites'][-1]['position']+1
    receipt=loss(model,codec,col,{'0':8,'1':8})['receipt']
    assert [e['action'] for e in receipt['events']]==['continue','stop']*2
    assert all('input' not in row and 'input_sha256' in row for row in receipt['generation']['rows'])


def test_no_sites_returns_none_without_creating_gradients():
    model,codec,rows,_=scripted('shared',invalid=True);col=collect(model,codec,rows)
    result=loss(model,codec,col,{'0':1,'1':2})
    assert result['loss'] is None and result['receipt']['active_rows']==0
    assert result['receipt']['selected_sites']==0 and result['receipt']['events']==[]
    assert all(p.grad is None for p in model.parameters())
    assert all(r['first_invalid_prefix_position'] is not None for r in col['rows'])


def test_output_limit_preserves_actual_truncated_rollout_without_fabricated_sites():
    model,codec,rows,_=scripted('shared');col=collect(model,codec,rows,max_target_tokens=4)
    assert all(p['generation_status']=='output_limit' and len(p['token_ids'])==3 for p in col['predictions'])
    assert all(len(r['consumed_prefix'])==3 and r['available_sites']==[] for r in col['rows'])
    result=loss(model,codec,col,{'0':1,'1':2})
    assert result['loss'] is None and result['receipt']['active_rows']==0
    assert result['receipt']['generation']['max_target_tokens']==4


def test_preserves_caller_modes_rng_existing_gradients_and_input_objects():
    model,codec,rows,_=scripted('shared');model.train();model.body.eval()
    for p in model.parameters():p.grad=torch.ones_like(p)
    versions=subject._state_versions(model);modes={n:m.training for n,m in model.named_modules()}
    rng=torch.get_rng_state().clone();prng=random.getstate();original=deepcopy(rows)
    col=collect(model,codec,rows);loss(model,codec,col,{'0':1,'1':2})
    assert versions==subject._state_versions(model) and rows==original
    assert modes=={n:m.training for n,m in model.named_modules()}
    assert torch.equal(rng,torch.get_rng_state()) and random.getstate()==prng
    assert col['model_copied'] is False


@pytest.mark.parametrize('field',['target_ids','target','reference_count','prefix','source_text'])
def test_collection_rejects_reference_inputs(field):
    model,codec,rows,_=scripted('shared');rows[0][field]=2
    with pytest.raises(ValueError,match='source-only'):collect(model,codec,rows)


@pytest.mark.parametrize('value',[True,0,33,1.5])
def test_loss_requires_actual_integer_training_counts(value):
    model,codec,rows,_=scripted('shared');col=collect(model,codec,rows)
    with pytest.raises(ValueError,match='counts1..32'):loss(model,codec,col,{'0':value,'1':2})


def test_stale_model_or_forged_sites_are_refused():
    model,codec,rows,_=scripted('shared');col=collect(model,codec,rows)
    bad=deepcopy(col);bad['rows'][0]['selected_sites'][0]['position']+=1
    with pytest.raises(ValueError,match='digest'):loss(model,codec,bad,{'0':1,'1':2})
    bad['collection_sha256']=subject.core.digest({k:v for k,v in bad.items() if k!='collection_sha256'})
    with pytest.raises(ValueError,match='selected sites'):loss(model,codec,bad,{'0':1,'1':2})
    with torch.no_grad():model.body.count_head.bias[0].add_(.01)
    with pytest.raises(ValueError,match='stale'):loss(model,codec,col,{'0':1,'1':2})


def test_deadline_is_timeout_and_caller_not_mutated(monkeypatch):
    model,codec,rows,_=scripted('shared');col=collect(model,codec,rows)
    before=subject.core.tensor_digest(model);modes={n:m.training for n,m in model.named_modules()}
    with pytest.raises(TimeoutError):collect(model,codec,rows,deadline=time.monotonic()-1)
    with pytest.raises(TimeoutError):loss(model,codec,col,{'0':1,'1':2},deadline=time.monotonic()-1)
    tick=[0.]
    def clock():tick[0]+=1.;return tick[0]
    monkeypatch.setattr(subject.time,'monotonic',clock)
    with pytest.raises(TimeoutError):collect(model,codec,rows,deadline=5.)
    assert subject.core.tensor_digest(model)==before and modes=={n:m.training for n,m in model.named_modules()}


@pytest.mark.parametrize('options',[{'max_target_tokens':513},{'max_sites_per_row':1},{'max_sites_per_row':8}])
def test_unreviewed_caps_and_site_policies_rejected(options):
    model,codec,rows,_=scripted('shared')
    with pytest.raises(ValueError):collect(model,codec,rows,**options)


def test_non_shared_model_refused():
    model,codec,rows,_=scripted('projected')
    with pytest.raises(ValueError,match='shared-slot'):collect(model,codec,rows)
