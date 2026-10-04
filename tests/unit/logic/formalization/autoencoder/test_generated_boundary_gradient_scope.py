"""Synthetic opt-in gradient routing; no real checkpoint or optimizer run."""
from copy import deepcopy
import random
import time

import pytest

torch=pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import generated_boundary_training as subject
from ipfs_datasets_py.logic.formalization.autoencoder import shared_slot_source_decoder_experiment as shared
from .test_boundary_source_diagnostic import scripted,plain
from .test_generated_boundary_training import collect,loss
from .test_projected_source_decoder_experiment import bound

COUNT={"body.count_head.weight","body.count_head.bias"}


@pytest.fixture(autouse=True)
def one_cpu():
    old=torch.get_num_threads();torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


def gradients(model):
    return {n:None if p.grad is None else p.grad.detach().clone() for n,p in model.named_parameters()}


def flags(model):
    return {n:p.requires_grad for n,p in model.named_parameters()}


def main_loss(model,codec,rows,collection):
    """Build the ordinary decoder graph before auxiliary flag isolation."""
    outputs=[p['token_ids']+[2] for p in collection['predictions']]
    width=max(map(len,outputs));labels=torch.tensor([[1]+x+[0]*(width-len(x)) for x in outputs])
    _,logits=subject.core._logits(torch,model,torch.tensor([r['input'] for r in rows]),
        labels[:,:-1],len(codec['target_vocabulary']))
    return torch.nn.functional.cross_entropy(logits.flatten(0,1),labels[:,1:].flatten(),ignore_index=0)


def test_default_and_explicit_default_have_original_logits_and_receipt_shape():
    model,codec,rows,_=scripted('shared');col=collect(model,codec,rows)
    default=loss(model,codec,col,{'0':1,'1':2})
    explicit=loss(model,codec,col,{'0':1,'1':2},gradient_scope='all_trainable')
    assert torch.equal(default['loss'],explicit['loss'])
    a,b=deepcopy(default['receipt']),deepcopy(explicit['receipt'])
    a.pop('elapsed_seconds');b.pop('elapsed_seconds')
    assert a==b and 'gradient_scope' not in a and 'gradient_parameter_names' not in a


def test_count_only_keeps_full_vocabulary_forward_values_and_count_gradient():
    model,codec,rows,_=scripted('shared',count_bias=.3);col=collect(model,codec,rows)
    all_loss=loss(model,codec,col,{'0':1,'1':3})
    all_loss['loss'].backward();full=gradients(model);model.zero_grad(set_to_none=True)
    isolated=loss(model,codec,col,{'0':1,'1':3},gradient_scope='count_head_only')
    assert torch.equal(all_loss['loss'].detach(),isolated['loss'].detach())
    assert all_loss['receipt']['events']==isolated['receipt']['events']
    isolated['loss'].backward();routed=gradients(model)
    for name in routed:
        if name in COUNT:
            assert full[name] is not None and torch.equal(routed[name],full[name])
        else:assert routed[name] is None
    assert all(torch.count_nonzero(routed[name])>0 for name in COUNT)
    receipt=isolated['receipt']
    assert receipt['gradient_scope']=='count_head_only'
    assert set(receipt['gradient_parameter_names'])==COUNT
    assert receipt['gradient_parameter_count']==(model.dimension+1)*32
    assert receipt['full_vocabulary_cross_entropy'] and receipt['vocabulary_size']==len(codec['target_vocabulary'])
    assert receipt['gradient_isolation_scope']=='this_auxiliary_loss_only_before_global_clipping'


def test_preexisting_main_graph_retains_identical_non_count_gradients_before_clipping():
    model,codec,rows,_=scripted('shared',count_bias=.3);col=collect(model,codec,rows)
    main_loss(model,codec,rows,col).backward();base=gradients(model);model.zero_grad(set_to_none=True)
    aux=loss(model,codec,col,{'0':1,'1':3},gradient_scope='count_head_only')
    aux['loss'].backward();extra=gradients(model);model.zero_grad(set_to_none=True)
    ordinary=main_loss(model,codec,rows,col)  # This graph exists when flags change.
    before=flags(model)
    aux=loss(model,codec,col,{'0':1,'1':3},gradient_scope='count_head_only')
    assert flags(model)==before
    (ordinary+.25*aux['loss']).backward();combined=gradients(model)
    assert any(base[n] is not None and torch.count_nonzero(base[n]) for n in base if n not in COUNT)
    for name in combined:
        if name in COUNT:
            assert torch.allclose(combined[name],base[name]+.25*extra[name],rtol=1e-6,atol=1e-7)
        elif base[name] is None:assert combined[name] is None
        else:assert torch.equal(combined[name],base[name])


def test_scope_does_not_change_actual_greedy_predictions_or_caller_state():
    model,codec,rows,_=scripted('shared');model.train();model.body.eval()
    for p in model.parameters():p.grad=torch.ones_like(p)
    modes={n:m.training for n,m in model.named_modules()};before_flags=flags(model)
    versions=subject._state_versions(model);weight=subject.core.tensor_digest(model)
    rng=torch.get_rng_state().clone();python_rng=random.getstate();expected=plain(model,codec,rows)
    col=collect(model,codec,rows)
    loss(model,codec,col,{'0':1,'1':2},gradient_scope='count_head_only')
    observed=plain(model,codec,rows)
    assert expected[1:]==observed[1:]
    assert subject.core.tensor_digest(model)==weight and subject._state_versions(model)==versions
    assert flags(model)==before_flags and modes=={n:m.training for n,m in model.named_modules()}
    assert torch.equal(rng,torch.get_rng_state()) and random.getstate()==python_rng


@pytest.mark.parametrize('error',[TimeoutError('deadline'),RuntimeError('forward failure')])
def test_forward_failure_restores_flags_and_preexisting_graph(monkeypatch,error):
    model,codec,rows,_=scripted('shared');col=collect(model,codec,rows)
    ordinary=main_loss(model,codec,rows,col);original=flags(model)
    modes={n:m.training for n,m in model.named_modules()};before=subject.core.tensor_digest(model)
    def fail(*args,**kwargs):
        assert {n for n,p in model.named_parameters() if p.requires_grad}==COUNT
        raise error
    monkeypatch.setattr(subject.core,'_logits',fail)
    with pytest.raises(type(error),match=str(error)):
        loss(model,codec,col,{'0':1,'1':2},gradient_scope='count_head_only')
    assert flags(model)==original and modes=={n:m.training for n,m in model.named_modules()}
    assert subject.core.tensor_digest(model)==before and all(p.grad is None for p in model.parameters())
    ordinary.backward()
    assert model.body.body.body.output.weight.grad is not None


def test_no_sites_keeps_none_and_no_gradient_graph():
    model,codec,rows,_=scripted('shared',invalid=True);col=collect(model,codec,rows)
    before=flags(model);result=loss(model,codec,col,{'0':1,'1':2},gradient_scope='count_head_only')
    assert result['loss'] is None and result['receipt']['events']==[]
    assert result['receipt']['gradient_scope']=='count_head_only' and flags(model)==before
    assert all(p.grad is None for p in model.parameters())


@pytest.mark.parametrize('value',['none','recurrent',True,None,1])
def test_unknown_or_untyped_scope_is_refused(value):
    model,codec,rows,_=scripted('shared');col=collect(model,codec,rows)
    with pytest.raises(ValueError,match='gradient scope'):
        loss(model,codec,col,{'0':1,'1':2},gradient_scope=value)


def test_opt_in_requires_active_count_guidance():
    base,codec,_=bound(dimension=8,kind='center_rms',guided=False)
    model=shared.bind_shared_slot_source_model(base,head_seed=1729)
    with pytest.raises(ValueError,match='active count guidance'):
        subject.generated_boundary_loss(torch,model,{}, {},codec=codec,
            input_transform={'mean':[0.]*8,'scale':1.},deadline=time.monotonic()+30,
            gradient_scope='count_head_only')


@pytest.mark.parametrize('name',['weight','bias'])
def test_opt_in_requires_both_actual_count_parameters_trainable(name):
    model,codec,rows,_=scripted('shared');col=collect(model,codec,rows)
    getattr(model.body.count_head,name).requires_grad_(False);before=flags(model)
    with pytest.raises(ValueError,match='trainable count-head'):
        loss(model,codec,col,{'0':1,'1':2},gradient_scope='count_head_only')
    assert flags(model)==before
