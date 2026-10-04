"""Synthetic causal recurrent-route contracts; no encoder or trained checkpoint."""
from copy import deepcopy
import pytest

torch=pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import ordered_clause_recurrent_decoder_experiment as subject
from ipfs_datasets_py.logic.formalization.autoencoder import action_factorized_clause_decoder_experiment as action
from ipfs_datasets_py.logic.formalization.autoencoder import clause_source_decoder_experiment as clauses
from ipfs_datasets_py.logic.formalization.autoencoder import clause_source_context as contexts_owner
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment_v2 as conditioning_owner
from ipfs_datasets_py.logic.formalization.autoencoder import projected_source_decoder_experiment as projected
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_cardinality_experiment as cardinality
from ipfs_datasets_py.logic.formalization.autoencoder import source_value_decoder_experiment as scalar
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as numerical
from .test_projected_source_decoder_experiment import setup,receipts,encode,inputs,rule
from .test_clause_source_context import fixtures,transform
from .test_action_factorized_clause_decoder_experiment import greedy


@pytest.fixture(autouse=True)
def one_cpu():
 old=torch.get_num_threads();torch.set_num_threads(1)
 yield
 torch.set_num_threads(old)


def fixture(dimension=8,seed=1729,fitted=False,conditioning="every_step"):
 _,codec=setup(dimension)
 raw=numerical._model(dict(dimension=dimension),codec,
     dict(seed=132,hidden_size=8,token_embedding_dim=16,projection_width=2))
 persistent=conditioning_owner.bind_persistent_model(raw,dimension=dimension,conditioning=conditioning)
 normalization,prior=receipts(dimension,"center_rms")
 base=projected.bind_projected_source_model(persistent,codec=codec,normalization_receipt=normalization,
     count_prior_receipt=prior,guide_boundary=True)
 train,validation,_,contexts=fixtures(dimension)
 unique=contexts_owner.unique_training_clauses(train,validation,contexts)
 with torch.no_grad():features=base.project(torch.tensor([r['input'] for r in unique])).tolist()
 rows=[dict(id=r['id'],source_sha256=r['source_sha256'],features=x) for r,x in zip(unique,features)]
 norm=projected.fit_source_normalization(rows,kind="center_rms",expected_training_ids=[r['id'] for r in rows],
     forbidden_validation_ids=[r['id'] for r in contexts_owner.validate_training_contexts(train,validation,contexts)['validation_clause_inventory']],training_rows_sha256='a'*64)
 norm['training_contexts_sha256']=core.digest(contexts['train'])
 norm['receipt_sha256']=core.digest({k:v for k,v in norm.items() if k!='receipt_sha256'})
 clause=clauses.bind_clause_source_model(base,head_seed=seed,clause_normalization_receipt=norm)
 donor=action.bind_action_factorized_clause_model(clause,codec=codec)
 if fitted:
  with torch.no_grad():
   gen=torch.Generator().manual_seed(777)
   for name,p in donor.named_parameters():
    if p.requires_grad:p.uniform_(-.2,.2,generator=gen)
 packet=contexts_owner.batch_source_context(torch,train,contexts['train'],transform(dimension))
 return subject.bind_ordered_clause_recurrent_model(donor,codec=codec),donor,codec,packet


@pytest.mark.parametrize('dimension',[8,384,768])
@pytest.mark.parametrize('seed',[1729,2718])
def test_initial_full_prefix_greedy_and_all_inherited_tensors_exact(dimension,seed):
 model,old,codec,packet=fixture(dimension,seed)
 x=inputs(dimension,1);prefix=torch.tensor([encode(codec)])
 actual=model(x,prefix,source_context=packet);expected=old(x,prefix,source_context=packet)
 assert all(torch.equal(a,b) for a,b in zip(actual,expected))
 assert greedy(model,x,packet)==greedy(old,x,packet)
 assert all(torch.equal(t,model.state_dict()[n]) for n,t in old.state_dict().items())
 assert set(model.state_dict())-set(old.state_dict())=={'clause_to_embedding.weight','ordered_clause_recurrent_version'}
 assert sum(p.numel() for p in model.parameters())-sum(p.numel() for p in old.parameters())==2048
 spec=subject.checked_specification(model,codec)
 assert spec['recurrent_parameter_count']==2048 and spec['source_clause_availability_used_for_recurrence']
 assert not spec['source_clause_count_forces_stopping'] and not spec['qualified']


@pytest.mark.parametrize('conditioning',['every_step','first_step'])
def test_even_fitted_donor_exact_logits_when_new_residual_zero(conditioning):
 model,old,codec,packet=fixture(fitted=True,conditioning=conditioning)
 x=inputs(8,1);prefix=torch.tensor([encode(codec)])
 assert torch.equal(model(x,prefix,source_context=packet)[1],old(x,prefix,source_context=packet)[1])
 assert greedy(model,x,packet)==greedy(old,x,packet)
 assert subject.checked_specification(model,codec)['initial_decoder_logits_unchanged']


def test_constructor_preserves_caller_rng_modes_gradients_flags_and_storage():
 _,old,codec,_=fixture();old.eval();old.action_head.source_projection.train()
 for p in old.parameters():
  if p.requires_grad:p.grad=torch.ones_like(p)
 digest=core.tensor_digest(old);rng=torch.get_rng_state().clone()
 modes={n:m.training for n,m in old.named_modules()};flags={n:p.requires_grad for n,p in old.named_parameters()}
 new=subject.bind_ordered_clause_recurrent_model(old,codec=codec)
 assert torch.equal(rng,torch.get_rng_state()) and core.tensor_digest(old)==digest
 assert {n:m.training for n,m in old.named_modules()}==modes
 assert {n:p.requires_grad for n,p in old.named_parameters()}==flags
 assert all(p.grad is not None and torch.equal(p.grad,torch.ones_like(p)) for p in old.parameters() if p.requires_grad)
 assert all(p.grad is None for p in new.parameters()) and not new.training and new.action_head.source_projection.training
 assert all(new.state_dict()[n].data_ptr()!=t.data_ptr() for n,t in old.state_dict().items())
 # Specification's read-only aliased view must not mutate any mode/state.
 subject.checked_specification(new,codec)
 assert {n:m.training for n,m in old.named_modules()}==modes and core.tensor_digest(old)==digest


def scan(codec,tokens,initial=None):
 tables=cardinality._tables(codec,len(codec['target_vocabulary']),torch)
 return subject._scan_routes([tokens],[initial or [0]*6],tables),tables


@pytest.mark.parametrize('count',[1,2,4,8,9])
def test_routes_switch_after_complete_rule_and_never_clamp_exhausted_to_last(count):
 _,_,codec,_=fixture();tokens=encode(codec,{'rules':[rule() for _ in range(count)]})
 (routes,final,boundaries,sites),tables=scan(codec,tokens)
 assert (final,boundaries)==cardinality._scan_prefix([tokens],[[0]*6],tables)
 assert (final,sites)==scalar._scan_value_prefix([tokens],[[0]*6],tables,8)
 assert routes[0][0]==0
 for _,offset,completed in boundaries:
  assert routes[0][offset]==(completed if completed<8 else -1)
 assert routes[0][-3:]==[-1,-1,-1]
 assert all(route<8 for route in routes[0])
 if count==9:
  eighth=next(i for _,i,k in boundaries if k==8)
  assert set(routes[0][eighth:])=={-1}


def test_scan_matches_existing_recognizers_for_invalid_and_quoted_field_values():
 _,_,codec,_=fixture();valid=encode(codec,{'rules':[rule()|{'action':'actor'},rule()]})
 size=len(codec['target_vocabulary'])
 inputs_to_scan=[valid,valid[:7]+[0]+valid[8:]]
 gen=torch.Generator().manual_seed(76)
 inputs_to_scan.extend(torch.randint(size,(20,40),generator=gen).tolist())
 for tokens in inputs_to_scan:
  (routes,final,boundaries,sites),tables=scan(codec,tokens)
  assert (final,boundaries)==cardinality._scan_prefix([tokens],[[0]*6],tables)
  assert (final,sites)==scalar._scan_value_prefix([tokens],[[0]*6],tables,8)
  if final[0][0]==cardinality._INVALID:assert routes[0][-1]==-1
 # Changing a suffix cannot alter earlier routing or sites.
 cut=len(valid)//2;mutated=valid[:cut]+[0]*len(valid[cut:])
 assert scan(codec,valid)[0][0][0][:cut]==scan(codec,mutated)[0][0][0][:cut]


def test_source_features_have_exact_branch_order_and_ignore_padding_vectors():
 model,_,_,packet=fixture(fitted=True);x=model.project(inputs(8,1))
 features,mask=model.clause_features(x,source_context=packet)
 expected=torch.cat((model.non_action_head.features(features),model.action_head.features(features)),dim=-1)*mask[:,:,None]
 actual=model.source_recurrent_features(x,source_context=packet)
 assert torch.equal(actual,expected) and actual.shape==(1,8,128) and not actual[:,2:].any()


@pytest.mark.parametrize('conditioning',['every_step','first_step'])
def test_batched_chunk_and_incremental_recurrence_matches_full_prefix(conditioning):
 model,_,codec,packet=fixture(fitted=True,conditioning=conditioning)
 with torch.no_grad():model.clause_to_embedding.weight.uniform_(-.1,.1,generator=torch.Generator().manual_seed(5))
 seqs=[encode(codec,{'rules':[rule()]}),encode(codec,{'rules':[rule(),rule()]})]
 tokens=torch.zeros((2,max(map(len,seqs))),dtype=torch.long)
 for i,row in enumerate(seqs):tokens[i,:len(row)]=torch.tensor(row)
 context={k:v.expand(2,*v.shape[1:]).clone() for k,v in packet.items()}
 context['mask'][0,1:]=False;context['vectors'][0,1:]=0
 x=model.project(inputs(8,2));initial=model.start(x,source_context=context)
 whole,last=model.next_logits(tokens,initial)
 for chunks in ([1]*tokens.shape[1],[4,17,tokens.shape[1]-21]):
  state=initial;parts=[];offset=0
  for length in chunks:
   y,state=model.next_logits(tokens[:,offset:offset+length],state);parts.append(y);offset+=length
  assert torch.allclose(torch.cat(parts,1),whole,atol=2e-6,rtol=2e-6)
  assert torch.allclose(state[0],last[0],atol=2e-6,rtol=2e-6)
  assert all(torch.equal(a,b) for a,b in zip(state[1:],last[1:]))
 assert torch.equal(initial[2],torch.zeros(2,dtype=torch.long))


def test_real_ce_first_updates_new_matrix_then_both_source_branches_and_gru():
 model,old,codec,packet=fixture();before=core.tensor_digest(old);x=inputs(8,1);tokens=torch.tensor([encode(codec)])
 def loss():return torch.nn.functional.cross_entropy(model(x,tokens[:,:-1],source_context=packet)[1].flatten(0,1),tokens[:,1:].flatten())
 loss().backward()
 assert model.clause_to_embedding.weight.grad.abs().sum()>0
 assert all(p.grad is None or not p.grad.any() for h in (model.action_head,model.non_action_head) for p in h.source_projection.parameters())
 with torch.no_grad():model.clause_to_embedding.weight.add_(-.1*model.clause_to_embedding.weight.grad)
 model.zero_grad(set_to_none=True);loss().backward()
 for h in (model.action_head,model.non_action_head):
  assert h.source_projection.weight.grad.abs().sum()>0
 assert model.body.body.body.decoder.weight_ih_l0.grad.abs().sum()>0
 assert core.tensor_digest(old)==before and all(p.grad is None for p in old.parameters())
 assert all(p.grad is None and not p.requires_grad for n,p in model.named_parameters() if 'projection_down.' in n or 'projection_up.' in n)


def test_residual_off_retains_other_source_paths_and_matches_weight_zeroing():
 model,old,codec,packet=fixture(fitted=True)
 with torch.no_grad():model.clause_to_embedding.weight.fill_(.2)
 before=core.tensor_digest(model);control=subject.bind_residual_off_model(model);other=deepcopy(model)
 with torch.no_grad():other.clause_to_embedding.weight.zero_()
 x=inputs(8,1);tokens=torch.tensor([encode(codec)])
 assert torch.equal(control(x,tokens,source_context=packet)[1],other(x,tokens,source_context=packet)[1])
 assert not torch.equal(model(x,tokens,source_context=packet)[1],control(x,tokens,source_context=packet)[1])
 assert torch.equal(control.source_value_logits(x,source_context=packet),model.source_value_logits(x,source_context=packet))
 assert torch.equal(control.count_logits(x),model.count_logits(x))
 assert core.tensor_digest(model)==before


def test_zero_control_removes_all_source_routes_mask_but_retains_scalar_bias_priors():
 model,_,codec,packet=fixture(fitted=True)
 with torch.no_grad():model.clause_to_embedding.weight.fill_(.2)
 zero=subject.bind_zero_condition_model(model)
 other={'vectors':torch.randn(packet['vectors'].shape,generator=torch.Generator().manual_seed(5)),
     'mask':torch.ones_like(packet['mask'])}
 a=zero.start(zero.project(inputs(8,1)),source_context=packet)
 b=zero.start(zero.project(inputs(8,1)+100),source_context=other)
 assert all(torch.equal(x,y) for x,y in zip(a,b))
 assert not a[0].any() and not a[1].any() and not a[6].any()
 assert a[5].any() and torch.equal(a[5][:,0],a[5][:,7])
 prefix=torch.tensor([encode(codec)])
 assert torch.equal(zero.next_logits(prefix,a)[0],zero.next_logits(prefix,b)[0])


@pytest.mark.parametrize('name',['ordered_clause_recurrent_version','head_initialization_seed','clause_source_mean',
 'clause_source_scale','body.source_mean','body.source_scale','body.count_prior_logits','body.body.body.projection_up.weight'])
def test_frozen_and_version_tamper_rejected_atomically(name):
 model,_,_,_=fixture();old=core.tensor_digest(model);state=deepcopy(model.state_dict())
 state['clause_to_embedding.weight'].fill_(.1);state[name]=state[name]+1
 with pytest.raises(ValueError,match='frozen'):model.load_state_dict(state)
 assert core.tensor_digest(model)==old


@pytest.mark.parametrize('mutation',['missing','extra','shape','dtype','nan','version_float','strict','assign'])
def test_complete_typed_restore_fails_before_mutating_any_tensor(mutation):
 model,_,_,_=fixture();old=core.tensor_digest(model);state=deepcopy(model.state_dict());kwargs={}
 state['action_head.field_readout.bias'].add_(1)
 if mutation=='missing':state.pop('clause_to_embedding.weight')
 elif mutation=='extra':state['dead.weight']=torch.zeros(1)
 elif mutation=='shape':state['clause_to_embedding.weight']=torch.zeros(1)
 elif mutation=='dtype':state['clause_to_embedding.weight']=state['clause_to_embedding.weight'].double()
 elif mutation=='nan':state['clause_to_embedding.weight'][0,0]=float('nan')
 elif mutation=='version_float':state['ordered_clause_recurrent_version']=state['ordered_clause_recurrent_version'].float()
 elif mutation=='strict':kwargs['strict']=False
 else:kwargs['assign']=True
 with pytest.raises(ValueError):model.load_state_dict(state,**kwargs)
 assert core.tensor_digest(model)==old


def test_trained_state_roundtrip_and_no_dead_extra_modules():
 model,_,codec,packet=fixture(fitted=True);other,_,_,_=fixture()
 with torch.no_grad():model.clause_to_embedding.weight.fill_(.2)
 other.load_state_dict(model.state_dict())
 assert core.tensor_digest(model)==core.tensor_digest(other)
 assert subject.checked_specification(other,codec)['schema']==subject.SCHEMA
 x=inputs(8,1);tokens=torch.tensor([encode(codec)])
 assert torch.equal(model(x,tokens,source_context=packet)[1],other(x,tokens,source_context=packet)[1])
 other.register_parameter('dead',torch.nn.Parameter(torch.zeros(1)))
 with pytest.raises(ValueError):subject.checked_specification(other,codec)


@pytest.mark.parametrize('mutation',['missing','target','dimension','mask','nan'])
def test_context_required_closed_and_source_only(mutation):
 model,_,_,packet=fixture();packet=deepcopy(packet);x=inputs(8,1)
 if mutation=='missing':
  with pytest.raises(TypeError):model.start(x)
  return
 if mutation=='target':packet['target_ids']=[1,2]
 elif mutation=='dimension':packet['vectors']=packet['vectors'][:,:,:7]
 elif mutation=='mask':packet['mask'][0,0]=False
 else:packet['vectors'][0,0,0]=float('nan')
 with pytest.raises(ValueError):model.start(x,source_context=packet)


def test_wrong_embedding_geometry_is_explicitly_rejected():
 from .test_action_factorized_clause_decoder_experiment import fixture as old_fixture
 old,_,codec,_=old_fixture()
 with pytest.raises(ValueError,match='16-wide'):subject.bind_ordered_clause_recurrent_model(old,codec=codec)
