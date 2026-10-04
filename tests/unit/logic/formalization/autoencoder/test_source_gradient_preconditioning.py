"""Synthetic8D preconditioner boundaries; no corpus fidelity or proof evidence."""
from copy import deepcopy
import sys
import time
from types import ModuleType,SimpleNamespace
import pytest

torch=pytest.importorskip('torch')
from ipfs_datasets_py.logic.formalization import autoencoder as package
from ipfs_datasets_py.logic.formalization.autoencoder import source_gradient_preconditioning as subject
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core
from . import test_source_modality_training_integration as fixtures

@pytest.fixture(autouse=True)
def cpu():
 old=torch.get_num_threads();torch.set_num_threads(1)
 yield
 torch.set_num_threads(old)

def cache(monkeypatch,policy='train_covariance_inverse'):
 model,_,train,tune,options,contexts=fixtures.real_fixture(monkeypatch)
 sources=[dict(id=r['id'],source_text=r['source_text']) for r in train]
 c=subject.prepare(torch,model,sources,contexts['train'],input_transform=options['input_transform'],policy=policy,deadline=time.monotonic()+30)
 return model,c,train,tune,options,contexts

@pytest.mark.parametrize('kind',['random','rank_one','constant','extreme'])
@pytest.mark.parametrize('policy',subject.POLICIES)
def test_matrix_is_fixed_finite_bounded_spd_trace8(kind,policy):
 generator=torch.Generator().manual_seed(42);x=torch.randn((113,8),generator=generator)
 if kind=='rank_one':x[:,1:]=0.
 if kind=='constant':x.fill_(3.)
 if kind=='extreme':x[:,0]*=1e8;x[:,7]*=1e-8
 before=x.clone();rng=torch.get_rng_state().clone();p,r=subject.matrix_from_features(torch,x,policy=policy)
 assert torch.equal(x,before) and torch.equal(torch.get_rng_state(),rng)
 assert torch.equal(p,p.T) and r['matrix_condition']<=32.00064 and abs(r['matrix_trace']-8)<.00016
 assert min(r['matrix_eigenvalues'])>0 and not r['reference_labels_used_for_fitting']
 if policy=='identity':assert torch.equal(p,torch.eye(8))

@pytest.mark.parametrize('bad',[None,True,'validation',''])
def test_unknown_policy_fails(bad):
 with pytest.raises(ValueError):subject.matrix_from_features(torch,torch.ones((2,8)),policy=bad)

@pytest.mark.parametrize('x',[torch.zeros((1,8)),torch.zeros((2,384)),torch.zeros((2,8),dtype=torch.float64),torch.full((2,8),float('nan')),torch.ones((2,8),requires_grad=True)])
def test_invalid_feature_inputs_fail(x):
 with pytest.raises(ValueError):subject.matrix_from_features(torch,x,policy='identity')


def test_prepare_uses_actual_source_path_and_preserves_all_state(monkeypatch):
 model,c,train,_,options,contexts=cache(monkeypatch);before=core.tensor_digest(model);rng=torch.get_rng_state().clone()
 r=c.receipt;assert r['validation_vectors_used']==0 and not r['validation_labels_used']
 expected=[];seen=set()
 for row in train:
  packet=core._source_context_kwargs(torch,[row],contexts['train'],options['input_transform'])['source_context']
  with torch.no_grad():features,_=model.clause_features(torch.zeros((1,8)),source_context=packet)
  for n,s in enumerate(contexts['train'][row['id']]['segments']):
   if s['source_sha256'] not in seen:seen.add(s['source_sha256']);expected.append(features[0,n].tolist())
 assert r['actual_train_features']==expected
 assert core.tensor_digest(model)==before and torch.equal(torch.get_rng_state(),rng)
 r['matrix'][0][0]+=10
 assert c.receipt['matrix']!=r['matrix']


def test_targets_or_evaluation_context_cannot_enter_fit(monkeypatch):
 model,_,train,tune,options,contexts=fixtures.real_fixture(monkeypatch)
 with pytest.raises(ValueError,match='no target fields'):
  subject.prepare(torch,model,train,contexts['train'],input_transform=options['input_transform'],policy='identity',deadline=time.monotonic()+30)
 with pytest.raises(ValueError):
  subject.prepare(torch,model,[dict(id=r['id'],source_text=r['source_text']) for r in tune],contexts['validation'],input_transform=options['input_transform'],policy='identity',deadline=time.monotonic()+30)

@pytest.mark.parametrize('policy',subject.POLICIES)
def test_only_registered_gradient_changes_exactly_once(monkeypatch,policy):
 model,c,*_=cache(monkeypatch,policy);gen=torch.Generator().manual_seed(99)
 for p in model.parameters():
  if p.requires_grad:p.grad=torch.randn(p.shape,generator=gen)
 before={n:p.grad.clone() for n,p in model.named_parameters() if p.grad is not None};weights=core.tensor_digest(model)
 r=subject.apply(torch,model,c,committed_step=0,deadline=time.monotonic()+30)
 for n,p in model.named_parameters():
  if n not in before:continue
  if n==subject.PARAMETER and policy!='identity':assert torch.equal(p.grad,before[n]@c._matrix)
  else:assert torch.equal(p.grad,before[n])
 assert r['gradient_inner_product']>=0 and core.tensor_digest(model)==weights
 with pytest.raises(ValueError,match='ordered application'):subject.apply(torch,model,c,committed_step=0,deadline=time.monotonic()+30)

@pytest.mark.parametrize('mutation',['matrix','fixed_buffer','wrong_model','nonfinite_gradient','missing_gradient','parameter'])
def test_cache_and_gradient_tampering_fails(monkeypatch,mutation):
 model,c,*_=cache(monkeypatch);c._parameter.grad=torch.ones_like(c._parameter)
 if mutation=='matrix':c._matrix[0,0]+=1
 elif mutation=='fixed_buffer':next(model.buffers()).add_(1)
 elif mutation=='wrong_model':model=deepcopy(model)
 elif mutation=='nonfinite_gradient':c._parameter.grad[0,0]=float('nan')
 elif mutation=='missing_gradient':c._parameter.grad=None
 else:model.non_action_head.source_projection.weight=torch.nn.Parameter(c._parameter.clone())
 with pytest.raises(ValueError):subject.apply(torch,model,c,committed_step=0,deadline=time.monotonic()+30)


def test_expired_apply_preserves_gradient(monkeypatch):
 model,c,*_=cache(monkeypatch);c._parameter.grad=torch.ones_like(c._parameter);before=c._parameter.grad.clone()
 with pytest.raises(TimeoutError):subject.apply(torch,model,c,committed_step=0,deadline=time.monotonic()-1)
 assert torch.equal(before,c._parameter.grad) and c._next_step==0


def test_default_none_does_not_import_or_prepare(monkeypatch):
 model,_,train,tune,options,contexts=fixtures.real_fixture(monkeypatch);fixtures.fake_context_boundary(monkeypatch)
 monkeypatch.setitem(sys.modules,package.__name__+'.source_gradient_preconditioning',None)
 a=fixtures.fit(model,train,tune,options,contexts);b=fixtures.fit(model,train,tune,options,contexts,source_gradient_preconditioning=None)
 fixtures.same(a,b);assert not any(k.startswith('source_gradient_preconditioning') for k in b['report'])


def test_identity_exactly_replays_default_and_candidate_records_once_before_clip(monkeypatch):
 model,_,train,tune,options,contexts=fixtures.real_fixture(monkeypatch);fixtures.fake_context_boundary(monkeypatch)
 a=fixtures.fit(model,train,tune,options,contexts)
 b=fixtures.fit(model,train,tune,options,contexts,source_gradient_preconditioning='identity')
 for role in ('state_dict','last_complete_attempt_state_dict'):
  assert all(torch.equal(v,b[role][n]) for n,v in a[role].items())
 assert a['predictions']==b['predictions'] and a['last_complete_attempt_predictions']==b['last_complete_attempt_predictions']
 for key in ('selected_epoch','selection','gradient_norms','committed_decoder_batch_ids_sha256'):
  assert a['report'][key]==b['report'][key]
 assert b['report']['source_gradient_preconditioning_committed_updates']==2
 for u in b['report']['committed_updates']:
  assert u['source_gradient_preconditioning']['before']==u['source_gradient_preconditioning']['after']
 seen=[];original=torch.nn.utils.clip_grad_norm_
 def clipping(parameters,*a,**k):
  parameters=list(parameters);seen.append(1);return original(parameters,*a,**k)
 monkeypatch.setattr(torch.nn.utils,'clip_grad_norm_',clipping)
 c=fixtures.fit(model,train,tune,options,contexts,source_gradient_preconditioning='train_covariance_inverse')
 assert len(seen)==c['report']['optimizer_steps']==c['report']['source_gradient_preconditioning_committed_updates']==2
 assert c['report']['selection']==a['report']['selection']

@pytest.mark.parametrize('phase',['prepare','apply'])
def test_preconditioning_deadline_never_commits_expired_work(monkeypatch,phase):
 model,_,train,tune,options,contexts=fixtures.real_fixture(monkeypatch);fixtures.fake_context_boundary(monkeypatch)
 monkeypatch.setattr(subject,phase,lambda *a,**k:(_ for _ in ()).throw(TimeoutError('test')))
 monkeypatch.setattr(torch.optim.AdamW,'step',lambda *a,**k:pytest.fail('expired update committed'))
 report=fixtures.fit(model,train,tune,options,contexts,source_gradient_preconditioning='identity')['report']
 assert report['optimizer_steps']==report['source_gradient_preconditioning_committed_updates']==0
 assert report['stopped_reason']=='deadline_during_source_gradient_'+('preparation' if phase=='prepare' else 'preconditioning')
