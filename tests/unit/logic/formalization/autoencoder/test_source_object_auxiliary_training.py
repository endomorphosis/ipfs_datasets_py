"""Full-vocabulary object supervision with exactly matched source exposure."""
from copy import deepcopy
import sys
import time
from types import ModuleType,SimpleNamespace
import pytest

torch=pytest.importorskip('torch')
from ipfs_datasets_py.logic.formalization import autoencoder as package
from ipfs_datasets_py.logic.formalization.autoencoder import source_object_auxiliary_training as subject
from ipfs_datasets_py.logic.formalization.autoencoder import source_modality_auxiliary_training as modality
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core
from . import test_source_modality_auxiliary_training as fixtures
from . import test_source_modality_training_integration as integration

@pytest.fixture(autouse=True)
def cpu():
    old=torch.get_num_threads();torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)

def cache(monkeypatch,dimension=8):
    bank,data=fixtures.bank(dimension=dimension);model,codec=fixtures.model_for(monkeypatch,dimension,fitted=True)
    result=subject.prepare_tensor_cache(torch,model,bank,codec=codec,input_transform=fixtures.transform(dimension),
        seed=1729,deadline=time.monotonic()+30,max_optimizer_steps=170)
    return model,result,bank,codec

@pytest.mark.parametrize('dimension',[8,384,768])
def test_exact_same170_six_source_batches_and_full_vocabulary_ce(monkeypatch,dimension):
    model,c,bank,codec=cache(monkeypatch,dimension)
    control=modality.prepare_tensor_cache(torch,model,bank,codec=codec,input_transform=fixtures.transform(dimension),seed=1729,
        deadline=time.monotonic()+30,max_optimizer_steps=170)
    for step in range(170):assert subject.select_indices(c,step)==modality.select_indices(control,step)
    before=core.tensor_digest(model);rng=torch.get_rng_state().clone()
    for p in model.parameters():
        if p.requires_grad:p.grad=torch.ones_like(p)
    gradients={n:p.grad.clone() for n,p in model.named_parameters() if p.grad is not None}
    result=subject.object_loss(torch,model,c,committed_step=0,deadline=time.monotonic()+30);r=result['receipt']
    expected=torch.nn.functional.cross_entropy(torch.tensor(r['full_vocabulary_logits']),torch.tensor(r['target_token_ids']))
    assert result['loss'].item()==pytest.approx(expected.item()) and len(r['full_vocabulary_logits'])==6
    assert all(len(row)==32 for row in r['full_vocabulary_logits'])
    assert r['loss_field']=='object' and r['source_indices_identical_to_modality_control']
    assert r['row_ids']==[bank['rows'][i]['id'] for i in r['indices']]
    for label,target in zip(r['object_labels'],r['target_token_ids']):assert codec['target_vocabulary'][target]=='"'+label+'"'
    assert core.tensor_digest(model)==before and torch.equal(torch.get_rng_state(),rng)
    assert all(torch.equal(p.grad,gradients[n]) for n,p in model.named_parameters() if n in gradients)
    assert all(r[k] is False for k in subject.FALSE)
    model.zero_grad(set_to_none=True);result['loss'].backward()
    g=model.non_action_head.field_readout.weight.grad
    assert g[:64].count_nonzero()==0 and g[64:].count_nonzero()>0
    assert model.non_action_head.source_projection.weight.grad.count_nonzero()>0

@pytest.mark.parametrize('kind',['target','source','style','vector'])
def test_authentication_rejects_tampered_complete_targets(monkeypatch,kind):
    bank,_=fixtures.bank();model,codec=fixtures.model_for(monkeypatch,fitted=True)
    if kind=='target':bank['rows'][0]['target_sha256']='0'*64
    elif kind=='source':bank['rows'][0]['source_text']+=' '
    elif kind=='style':bank['rows'][0]['wording_style']=1-bank['rows'][0]['wording_style']
    else:bank['rows'][0]['input'][0]+=.1
    bank['bank_sha256']=modality.digest({k:v for k,v in bank.items() if k!='bank_sha256'})
    with pytest.raises(ValueError):subject.prepare_tensor_cache(torch,model,bank,codec=codec,input_transform=fixtures.transform(8),seed=1729,deadline=time.monotonic()+30)

@pytest.mark.parametrize('step',[True,-1,170,0.5])
def test_selector_is_bounded_no_cursor(monkeypatch,step):
    model,c,_,_=cache(monkeypatch);before=subject.select_indices(c,0)
    with pytest.raises(ValueError):subject.object_loss(torch,model,c,committed_step=step,deadline=time.monotonic()+30)
    assert subject.select_indices(c,0)==before

def test_deadline_and_cache_mutation_fail_without_model_change(monkeypatch):
    model,c,_,_=cache(monkeypatch);before=core.tensor_digest(model)
    with pytest.raises(TimeoutError):subject.object_loss(torch,model,c,committed_step=0,deadline=time.monotonic()-1)
    c._targets[0]=1
    with pytest.raises(ValueError,match='cached object'):subject.object_loss(torch,model,c,committed_step=0,deadline=time.monotonic()+30)
    assert core.tensor_digest(model)==before

def fake_object(monkeypatch,expire=None,clock=None):
    owner=ModuleType(package.__name__+'.source_object_auxiliary_training');observed=[]
    owner.validate_training_binding=lambda *a,**k:{'synthetic':True}
    owner.estimate_training_work_bytes=lambda *a,**k:10000
    def prepare(torch,model,bank,**kw):
        if expire=='preparation':raise TimeoutError()
        return SimpleNamespace(model=model,receipt={'synthetic':True})
    def loss(torch,model,c,*,committed_step,deadline):
        observed.append(committed_step)
        if expire=='loss':raise TimeoutError()
        value=(model.non_action_head.field_readout.weight[64:]+1.).square().mean()
        if expire=='backward':value.register_hook(lambda g:(clock.__setitem__(0,1e9) or g))
        return dict(loss=value,receipt=dict(mean_cross_entropy=float(value.detach()),object_labels=['record']*3+['request']*3))
    owner.prepare_tensor_cache=prepare;owner.object_loss=loss
    monkeypatch.setitem(sys.modules,owner.__name__,owner);monkeypatch.setattr(package,'source_object_auxiliary_training',owner)
    return observed

def test_disabled_default_exact_and_no_import(monkeypatch):
    model,_,train,tune,options,contexts=integration.real_fixture(monkeypatch);integration.fake_context_boundary(monkeypatch)
    monkeypatch.setitem(sys.modules,package.__name__+'.source_object_auxiliary_training',None)
    a=integration.fit(model,train,tune,options,contexts)
    b=integration.fit(model,train,tune,options,contexts,auxiliary_source_object_weight=0.,auxiliary_source_object_bank=None)
    integration.same(a,b);assert not any(k.startswith('auxiliary_source_object') for k in b['report'])

def test_object_loss_participates_once_and_selection_unchanged(monkeypatch):
    model,_,train,tune,options,contexts=integration.real_fixture(monkeypatch);integration.fake_context_boundary(monkeypatch)
    seen=fake_object(monkeypatch);before=core.tensor_digest(model)
    result=integration.fit(model,train,tune,options,contexts,auxiliary_source_object_weight=.05,auxiliary_source_object_bank={})
    r=result['report'];assert seen==[0,1] and r['auxiliary_source_object_presentations']==12
    assert r['auxiliary_source_object_presentations_per_class']=={'record':6,'request':6}
    assert r['selection']=='per_length_nonregression_then_fidelity_progress_then_reference_ce'
    for update in r['committed_updates']:
        extra=update['auxiliary_source_object'];assert extra['weighted_loss']==pytest.approx(.05*extra['receipt']['mean_cross_entropy'])
        assert update['objective']==pytest.approx(extra['base_objective']+extra['weighted_loss'])
    assert core.tensor_digest(model)==before and r['auxiliary_source_object_used_for_selection'] is False

@pytest.mark.parametrize('phase',['preparation','loss','backward'])
def test_deadline_before_commit_retains_parent_and_zero_exposure(monkeypatch,phase):
    model,_,train,tune,options,contexts=integration.real_fixture(monkeypatch);integration.fake_context_boundary(monkeypatch)
    clock=[0.];monkeypatch.setattr(integration.subject.time,'monotonic',lambda:clock[0]);fake_object(monkeypatch,phase,clock)
    before=core.tensor_digest(model);monkeypatch.setattr(torch.optim.AdamW,'step',lambda *a,**k:pytest.fail('committed expired update'))
    r=integration.fit(model,train,tune,options,contexts,auxiliary_source_object_weight=.05,auxiliary_source_object_bank={})['report']
    assert r['optimizer_steps']==r['auxiliary_source_object_presentations']==0 and core.tensor_digest(model)==before

@pytest.mark.parametrize('extra',[dict(auxiliary_source_object_weight=True),dict(auxiliary_source_object_weight=float('nan')),
    dict(auxiliary_source_object_weight=.05),dict(auxiliary_source_object_bank={}),
    dict(auxiliary_source_object_weight=.05,auxiliary_source_object_bank={},auxiliary_source_modality_weight=.05,auxiliary_source_modality_bank={})])
def test_invalid_weight_or_combination_rejected_before_copy(monkeypatch,extra):
    model,_,train,tune,options,contexts=integration.real_fixture(monkeypatch)
    monkeypatch.setattr(integration.subject,'deepcopy',lambda *a:pytest.fail('private copy'))
    with pytest.raises(ValueError):integration.fit(model,train,tune,options,contexts,**extra)
