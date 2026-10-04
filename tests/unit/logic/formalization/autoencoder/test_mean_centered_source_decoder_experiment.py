"""Synthetic centering/gate invariants; no real-corpus fidelity claims."""
from copy import deepcopy

import pytest

torch=pytest.importorskip('torch')
from ipfs_datasets_py.logic.formalization.autoencoder import mean_centered_source_decoder_experiment as subject
from ipfs_datasets_py.logic.formalization.autoencoder import long_span_source_value_training as trainer
from .test_projected_source_decoder_experiment import bound, receipts, inputs, encode
from .test_benchmark_projected_source_reconstruction import synthetic_training_model


@pytest.fixture(autouse=True)
def one_cpu():
    old=torch.get_num_threads();torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


def make(kind='center_rms',mode='mean_centered',*,dimension=8,guided=True):
    base,codec,_=bound(dimension=dimension,kind=kind,guided=guided)
    reference,_=receipts(dimension,'center_rms')
    model=subject.bind_mean_centered_source_model(base,scalar_mode=mode,
        training_feature_mean_receipt=reference)
    return model,base,codec


def perturb(model):
    with torch.no_grad():
        for head in (model.body.source_value_head,model.body.count_head):
            head.weight.copy_(torch.randn(head.weight.shape,generator=torch.Generator().manual_seed(8))*.1)
            head.bias.copy_(torch.randn(head.bias.shape,generator=torch.Generator().manual_seed(12))*.1)


@pytest.mark.parametrize('mode',['raw','off','mean_centered'])
@pytest.mark.parametrize('kind',['none','center_rms'])
def test_zero_heads_preserve_base_logits_source_counts_and_caller(kind,mode):
    model,base,codec=make(kind,mode)
    before=subject.core.tensor_digest(base);rng=torch.get_rng_state().clone()
    data=inputs(8);prefix=torch.tensor([encode(codec)[:-1]]*2)
    with torch.no_grad():
        projected,expected=base(data,prefix);actual_projected,actual=model(data,prefix)
    assert torch.equal(actual,expected) and torch.equal(projected,actual_projected)
    assert torch.equal(model.source_value_logits(projected),base.source_value_logits(projected))
    assert torch.equal(model.count_logits(projected),base.count_logits(projected))
    assert subject.core.tensor_digest(base)==before and torch.equal(torch.get_rng_state(),rng)
    assert len(list(model.parameters()))==len(list(base.parameters()))
    assert model.describe()['added_trainable_parameters']==0


@pytest.mark.parametrize('mode',['raw','off','mean_centered'])
@pytest.mark.parametrize('kind',['none','center_rms'])
def test_applied_logits_equal_explicit_affine_centering_with_unchanged_auxiliary(kind,mode):
    model,_,_=make(kind,mode);perturb(model)
    projected=model.project(inputs(8));raw=model.body.source_value_logits(projected)
    reference=model.body.source_value_logits(model.source_reference_mean[None,:].expand(len(projected),-1))
    expected={'raw':raw,'off':torch.zeros_like(raw),'mean_centered':raw-reference}[mode]
    assert torch.equal(model.source_value_logits(projected),raw)
    assert torch.equal(model.source_value_guidance_logits(projected),expected)
    assert torch.equal(model.start(projected)[-1],expected)
    if kind=='center_rms':
        assert torch.equal(model.source_reference_mean,model.body.source_mean)
        assert torch.count_nonzero(model.body._features(model.source_reference_mean[None,:]))==0
    assert not model.describe()['calibrated_posterior_claim']


@pytest.mark.parametrize('kind',['none','center_rms'])
def test_sequence_bias_gradient_cancels_without_detach_but_auxiliary_trains_bias(kind):
    model,_,codec=make(kind);perturb(model)
    projected=model.project(inputs(8))
    score=model.source_value_guidance_logits(projected)
    # Asymmetric weights avoid a vacuous all-vocabulary shift-invariant loss.
    weighting=torch.arange(score.numel(),dtype=torch.float32).reshape_as(score)/score.numel()
    weight_grad,bias_grad=torch.autograd.grad((score*weighting).sum(),
        (model.body.source_value_head.weight,model.body.source_value_head.bias),retain_graph=True)
    assert torch.count_nonzero(weight_grad)>0
    assert torch.equal(bias_grad,torch.zeros_like(bias_grad))
    raw=model.source_value_logits(projected)
    auxiliary=torch.nn.functional.cross_entropy(raw.flatten(0,2),torch.full((raw.numel()//raw.shape[-1],),3,dtype=torch.long))
    auxiliary_bias=torch.autograd.grad(auxiliary,model.body.source_value_head.bias)[0]
    assert torch.count_nonzero(auxiliary_bias)>0


@pytest.mark.parametrize('mode',['raw','off','mean_centered'])
def test_full_prefix_incremental_and_request_isolation(mode):
    model,_,codec=make(mode=mode);perturb(model)
    data=inputs(8);prefix=torch.tensor([encode(codec)[:-1]]*2);projected=model.project(data)
    initial=model.start(projected);saved=[x.clone() for x in initial]
    full,_=model.next_logits(prefix,initial)
    state=model.start(projected);parts=[]
    for index in range(prefix.shape[1]):
        logits,state=model.next_logits(prefix[:,index:index+1],state);parts.append(logits)
    assert torch.allclose(full,torch.cat(parts,dim=1),atol=1e-6,rtol=1e-6)
    assert all(torch.equal(a,b) for a,b in zip(initial,saved))
    another=model.start(projected+1)
    assert torch.equal(model.next_logits(prefix,initial)[0],full)
    assert not hasattr(model,'source_context') and not model.describe()['source_context_cached_on_module']
    assert all(a.data_ptr()!=b.data_ptr() for a,b in zip(initial,another) if a.numel())


@pytest.mark.parametrize('kind',['none','center_rms'])
@pytest.mark.parametrize('mode',['raw','off','mean_centered'])
def test_zero_control_removes_source_and_preserves_raw_bias_and_count_prior(kind,mode):
    model,_,_=make(kind,mode);perturb(model);control=subject.bind_zero_condition_model(model)
    projected=model.project(inputs(8));state=control.start(projected)
    assert torch.count_nonzero(state[0])==torch.count_nonzero(state[1])==0
    expected_scalar=model.body.source_value_head.bias.reshape(1,8,4,-1).expand(len(projected),-1,-1,-1)
    assert torch.equal(control.source_value_logits(projected),expected_scalar)
    assert torch.equal(control.count_logits(projected),
        (model.body.count_head.bias+model.body.count_prior_logits)[None,:].expand(len(projected),-1))
    if mode!='raw':assert torch.count_nonzero(state[-1])==0
    else:assert torch.equal(state[-1],expected_scalar)
    assert torch.equal(state[-1],control.source_value_guidance_logits(projected))
    assert torch.equal(control.project(inputs(8)),projected)


@pytest.mark.parametrize('mode',['',None,True,1,[],{},'calibrated','mean-centered'])
def test_invalid_modes_refused(mode):
    base,_,_=bound(dimension=8)
    with pytest.raises(ValueError,match='scalar guidance mode'):
        subject.bind_mean_centered_source_model(base,scalar_mode=mode)


def test_identity_features_require_explicit_training_reference():
    base,_,_=bound(dimension=8,kind='none')
    with pytest.raises(ValueError,match='requires authenticated centered'):
        subject.bind_mean_centered_source_model(base)


@pytest.mark.parametrize('key',['training_feature_rows_sha256','fitted_training_mean','training_rows_sha256','forbidden_validation_ids'])
def test_self_consistent_foreign_mean_receipt_refused(key):
    base,_,_=bound(dimension=8,kind='none');receipt,prior=receipts(8,'center_rms')
    if key=='fitted_training_mean':
        receipt[key][0]+=1;receipt['mean']=deepcopy(receipt[key])
    elif key=='forbidden_validation_ids':receipt[key]=['other-validation']
    else:receipt[key]='f'*64
    receipt['receipt_sha256']=subject.core.digest({k:v for k,v in receipt.items() if k!='receipt_sha256'})
    with pytest.raises(ValueError):
        subject.bind_mean_centered_source_model(base,training_feature_mean_receipt=receipt)


@pytest.mark.parametrize('key',['source_reference_mean','body.source_mean','body.source_scale','body.count_prior_logits'])
def test_restore_rejects_changed_frozen_reference_or_inherited_buffers_before_mutation(key):
    model,_,_=make();before=subject.core.tensor_digest(model);state=deepcopy(model.state_dict())
    state[key].add_(1)
    with pytest.raises(ValueError,match='restored frozen'):
        model.load_state_dict(state,strict=True)
    assert subject.core.tensor_digest(model)==before


def test_roundtrip_restore_accepts_trainable_parameters_and_preserves_guidance():
    model,_,codec=make();perturb(model);state=deepcopy(model.state_dict())
    fresh,_,_=make();fresh.load_state_dict(state,strict=True)
    data=inputs(8);prefix=torch.tensor([encode(codec)[:-1]]*2)
    assert torch.equal(model(data,prefix)[1],fresh(data,prefix)[1])


def test_mean_centering_preserves_full_output_support_and_never_forces_closure():
    model,_,codec=make();data=inputs(8);prefix=torch.tensor([encode(codec)[:-1]]*2)
    with torch.no_grad():
        model.body.source_value_head.weight.fill_(0)
        # Non-scalar punctuation remains in the vocabulary; no hard support mask.
        token=codec['target_vocabulary'].index('}')
        model.body.source_value_head.weight[token,0]=100
    projected=model.project(data);applied=model.source_value_guidance_logits(projected)
    assert bool(torch.isfinite(applied).all()) and applied.shape[-1]==len(codec['target_vocabulary'])
    assert torch.count_nonzero(applied[...,token])>0
    assert not model.describe()['syntax_forced'] and not model.describe()['closure_forced']


def test_raw_wrapper_training_is_exact_old_path_numerical_parity():
    _,owner,_,base,train,tune,options=synthetic_training_model(kind='center_rms',guided=True)
    wrapped=subject.bind_mean_centered_source_model(base,scalar_mode='raw')
    old=trainer.train(base,train,tune,source_value_weight=.25,cardinality_weight=.25,
        count_exposure='balanced_all',strategy='semantic_fields',**options)
    new=trainer.train(wrapped,train,tune,source_value_weight=.25,cardinality_weight=.25,
        count_exposure='balanced_all',strategy='semantic_fields',**options)
    for role in ('state_dict','last_complete_attempt_state_dict'):
        stripped={key[5:]:value for key,value in new[role].items() if key.startswith('body.')}
        assert stripped.keys()==old[role].keys()
        assert all(torch.equal(stripped[key],old[role][key]) for key in stripped)
    assert old['predictions']==new['predictions'] and old['last_complete_attempt_predictions']==new['last_complete_attempt_predictions']
    for key in ('committed_updates','gradient_norms','optimizer_steps','selected_epoch','stopped_reason',
        'row_presentations','source_value_presentations','valid_target_token_presentations'):
        assert old['report'][key]==new['report'][key],key
    for a,b in zip(old['report']['history'],new['report']['history']):
        for key in ('numerical','source_count','source_values','source_fidelity','accepted','rejection_reasons'):
            assert a[key]==b[key],key


def test_centered_wrapper_trains_with_unchanged_gate_and_cohort_guard(monkeypatch):
    _,owner,_,base,train,tune,options=synthetic_training_model(kind='center_rms',guided=True)
    model=subject.bind_mean_centered_source_model(base)
    result=trainer.train(model,train,tune,source_value_weight=.25,cardinality_weight=.25,
        count_exposure='balanced_all',strategy='semantic_fields',**options)
    assert result['report']['optimizer_steps']==2 and result['report']['source_value_presentations']==16
    assert result['report']['selection']=='per_length_nonregression_then_fidelity_progress_then_reference_ce'
    assert torch.count_nonzero(result['last_complete_attempt_state_dict']['body.source_value_head.weight'])>0
    changed=deepcopy(train);changed[0]['input'][0]+=.01
    with pytest.raises(ValueError,match='cohort differs'):
        trainer.train(model,changed,tune,source_value_weight=.25,cardinality_weight=.25,
            count_exposure='balanced_all',strategy='semantic_fields',**options)
    description=model.describe();description['scalar_mode']='oracle'
    monkeypatch.setattr(model,'describe',lambda:description)
    with pytest.raises(ValueError,match='base and mode'):
        trainer._head_specification(model,options['codec'],.25)


@pytest.mark.parametrize('name',['source_mean','source_scale','count_prior_logits'])
def test_binding_rejects_in_place_corrupted_projected_preprocessing(name):
    base,_,_=bound(dimension=8,kind='center_rms')
    with torch.no_grad():getattr(base,name).add_(1)
    with pytest.raises(ValueError,match='base buffer differs'):
        subject.bind_mean_centered_source_model(base)


def test_invalid_prefix_does_not_reenable_scalar_guidance():
    model,_,codec=make();perturb(model)
    projected=model.project(inputs(8));state=model.start(projected)
    invalid=torch.tensor([[1,codec['target_vocabulary'].index(']')]]*2)
    _,state=model.next_logits(invalid,state)
    later=torch.tensor([[codec['target_vocabulary'].index('"actor"'),codec['target_vocabulary'].index(':')]]*2)
    actual,_=model.next_logits(later,state)
    no_scalar=(*state[:-1],torch.zeros_like(state[-1]))
    expected,_=model.next_logits(later,no_scalar)
    assert torch.equal(actual,expected)


def test_later_prefix_cannot_change_earlier_scalar_logits():
    model,_,codec=make();perturb(model)
    data=inputs(8);prefix=torch.tensor([encode(codec)[:-1]]*2)
    changed=prefix.clone();changed[:,-4:]=codec['target_vocabulary'].index('}')
    original=model(data,prefix)[1];altered=model(data,changed)[1]
    assert torch.equal(original[:,:-4],altered[:,:-4])
