"""Synthetic bank/gradient/sampler controls; no native encoder or saved fit."""
from collections import Counter
from copy import deepcopy
import math
import random
import time

import pytest
torch=pytest.importorskip('torch')
from ipfs_datasets_py.logic.formalization.autoencoder import paraphrase_modality_auxiliary_training as subject
from .test_contextual_training_mixture import fixture as corpus_fixture,seal
from . import test_contextual_training_mixture_integration as tiny


@pytest.fixture(autouse=True)
def cpu():
    old=torch.get_num_threads();torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


def bank_fixture(monkeypatch,dimension=384):
    train,dev,kw,calls=corpus_fixture(monkeypatch,dimension)
    inventory=kw.pop('mixture');inventory['policy']='original_only';seal(inventory)
    kw['source_inventory']=inventory
    return train,dev,kw,calls


def prepare(args):
    train,dev,kw,*_=args
    return subject.prepare_bank(train,dev,**kw,deadline=time.monotonic()+30)


def cache_fixture(monkeypatch):
    args=bank_fixture(monkeypatch);bank=prepare(args)
    model,train,dev,options,contexts,*_=tiny.fixture(monkeypatch)
    cache=subject.prepare_tensor_cache(torch,model,bank,codec=options['codec'],
        input_transform=options['input_transform'],seed=1729,deadline=time.monotonic()+30,max_optimizer_steps=170)
    return model,bank,cache,options


@pytest.mark.parametrize('dimension',[384,768])
def test_authenticated180_bank_and_six_strata_without_mutation(monkeypatch,dimension):
    args=bank_fixture(monkeypatch,dimension);before=deepcopy(args[:3]);rng=random.getstate()
    bank=prepare(args)
    assert args[:3]==before and args[3]==[1] and random.getstate()==rng
    assert bank['dimension']==dimension and len(bank['rows'])==180
    assert [r['id'] for r in bank['rows']]==sorted({r['id'] for r in bank['rows']})
    assert Counter((r['modality'],r['template']) for r in bank['rows'])==Counter({s:30 for s in subject.STRATA})
    assert not bank['decoder_rows_replaced'] and not bank['normalization_fitted']
    assert set(bank['source_derivation_receipt']['evaluation_coverage'])==set(subject.mixture.EVALUATION_DATASETS)
    assert bank['bank_sha256']==subject.digest({k:v for k,v in bank.items() if k!='bank_sha256'})


@pytest.mark.parametrize('mutation',['policy','source','target','vector','missing_split','producer','digest'])
def test_resealed_bad_source_provenance_refused(monkeypatch,mutation):
    args=bank_fixture(monkeypatch);inv=args[2]['source_inventory']
    if mutation=='policy':inv['policy']='half_paraphrases'
    elif mutation=='source':inv['corpus']['source_rows'][0]['source_text']='fabricated clause'
    elif mutation=='target':inv['corpus']['references'][0]['target']['rules'][0]['modality']='unknown'
    elif mutation=='vector':inv['source_inputs']['clause_cache'][0]['input'][0]=3.
    elif mutation=='missing_split':inv['prior_sources_by_dataset'].pop('exposed_v3')
    elif mutation=='producer':
        monkeypatch.setattr(subject.mixture.producer,'validate_report',
            lambda *a:(_ for _ in ()).throw(ValueError('native producer refused')))
    else:inv['payload_sha256']='0'*64
    if mutation!='digest':seal(inv)
    with pytest.raises((ValueError,AssertionError)):prepare(args)


def test_schedule_is_balanced_committed_step_indexed_and_rng_free(monkeypatch):
    model,bank,cache,options=cache_fixture(monkeypatch);rng=torch.random.get_rng_state().clone();py=random.getstate()
    exposures=Counter();strata=Counter()
    for step in range(170):
        indices=subject.select_indices(cache,step)
        assert indices==subject.select_indices(cache,step) and len(set(indices))==6
        assert [(bank['rows'][i]['modality'],bank['rows'][i]['template']) for i in indices]==list(subject.STRATA)
        for i in indices:exposures[i]+=1;strata[bank['rows'][i]['modality'],bank['rows'][i]['template']]+=1
    assert set(exposures)==set(range(180)) and set(exposures.values())=={5,6}
    assert set(strata.values())=={170} and sum(exposures.values())==1020
    assert torch.equal(rng,torch.random.get_rng_state()) and random.getstate()==py
    for i in (True,-1,170):
        with pytest.raises(ValueError):subject.select_indices(cache,i)


def test_full32v_ce_zero_graph_and_positive_gradient_scope(monkeypatch):
    model,bank,cache,options=cache_fixture(monkeypatch);before={n:t.clone() for n,t in model.state_dict().items()}
    zero=subject.modality_loss(torch,model,cache,committed_step=0,deadline=time.monotonic()+30,requires_grad=False)
    positive=subject.modality_loss(torch,model,cache,committed_step=0,deadline=time.monotonic()+30,requires_grad=True)
    assert not zero['loss'].requires_grad and positive['loss'].requires_grad
    assert zero['receipt']['full_vocabulary_logits']==positive['receipt']['full_vocabulary_logits']
    values=positive['receipt'];manual=[]
    for vector,target in zip(values['full_vocabulary_logits'],values['target_token_ids']):
        peak=max(vector);manual.append(peak+math.log(sum(math.exp(v-peak) for v in vector))-vector[target])
    assert values['mean_cross_entropy']==pytest.approx(sum(manual)/6,abs=5e-7)
    positive['loss'].backward();gradients={n:p.grad for n,p in model.named_parameters() if p.grad is not None}
    assert gradients and any(bool(g.any()) for g in gradients.values())
    # The complete four-field source forward can materialize zero derivatives
    # for unselected rows/branches; only non-action tensors receive nonzero CE.
    assert all(n.startswith('non_action_head.') or not bool(g.any()) for n,g in gradients.items())
    assert all(torch.equal(t,before[n]) for n,t in model.state_dict().items())
    assert all(len(v)==32 for v in values['full_vocabulary_logits'])


def test_full_bank_readout_is_detached_and_preserves_model_rng_modes_gradients(monkeypatch):
    model,bank,cache,options=cache_fixture(monkeypatch)
    parameter=next(model.parameters());parameter.grad=torch.ones_like(parameter)
    before={n:t.clone() for n,t in model.state_dict().items()};rng=torch.random.get_rng_state().clone()
    modes={n:m.training for n,m in model.named_modules()};gradient=parameter.grad.clone()
    result=subject.evaluate_bank(torch,model,cache,deadline=time.monotonic()+30)
    assert result['groups']['all']['rows']==180 and result['source_head_forward_calls']==30
    assert all(result['groups']['modality:'+m]['rows']==60 for m in ('O','P','F'))
    assert all(result['groups']['template:'+t]['rows']==90 for t in subject.mixture.authored.TEMPLATES)
    assert result['groups']['all']['cross_entropy']==pytest.approx(sum(r['cross_entropy'] for r in result['rows'])/180)
    assert all(torch.equal(t,before[n]) for n,t in model.state_dict().items())
    assert torch.equal(rng,torch.random.get_rng_state()) and modes=={n:m.training for n,m in model.named_modules()}
    assert torch.equal(parameter.grad,gradient) and result['optimizer_steps']==0


@pytest.mark.parametrize('mutation',['buffer','cache','foreign_model'])
def test_cache_and_preprocessing_mutations_refused(monkeypatch,mutation):
    model,bank,cache,options=cache_fixture(monkeypatch)
    if mutation=='buffer':
        with torch.no_grad():next(model.buffers()).add_(1)
    elif mutation=='cache':cache._data.add_(1)
    else:model=deepcopy(model)
    with pytest.raises(ValueError):subject.modality_loss(torch,model,cache,committed_step=0,deadline=time.monotonic()+30,requires_grad=False)


def test_expired_prepare_and_forward_never_execute_model(monkeypatch):
    args=bank_fixture(monkeypatch)
    with pytest.raises(TimeoutError):subject.prepare_bank(args[0],args[1],**args[2],deadline=time.monotonic()-1)
    model,bank,cache,options=cache_fixture(monkeypatch)
    monkeypatch.setattr(model,'source_value_logits',lambda *a,**kw:pytest.fail('expired model forward'))
    with pytest.raises(TimeoutError):subject.modality_loss(torch,model,cache,committed_step=0,deadline=time.monotonic()-1,requires_grad=False)
