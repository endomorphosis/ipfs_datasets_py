"""Synthetic action factorization invariants; no encoder or trained checkpoint."""
from copy import deepcopy

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import action_factorized_clause_decoder_experiment as subject
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core
from .test_clause_source_decoder_experiment import bound, trained
from .test_projected_source_decoder_experiment import encode, inputs


@pytest.fixture(autouse=True)
def one_cpu():
    old = torch.get_num_threads(); torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


def fixture(dimension=8, fitted=False):
    original, _, codec, packet, _ = bound(dimension)
    if fitted: trained(original)
    model = subject.bind_action_factorized_clause_model(original, codec=codec)
    return model, original, codec, packet


def greedy(model, source, context, limit=48):
    with torch.no_grad():
        state = model.start(model.project(source), source_context=context)
        token = torch.ones((1, 1), dtype=torch.long); result=[]
        for _ in range(limit):
            logits, state = model.next_logits(token, state)
            token = logits[:, -1].argmax(-1, keepdim=True)
            result.append(int(token.item()))
            if result[-1] == 2: break
        return result


@pytest.mark.parametrize("dimension", [8,384,768])
def test_fresh_full_prefix_and_greedy_exact_initial_parity(dimension):
    model, old, codec, context = fixture(dimension)
    x=inputs(dimension,1);prefix=torch.tensor([encode(codec)])
    a=model(x,prefix,source_context=context);b=old(x,prefix,source_context=context)
    assert all(torch.equal(left,right) for left,right in zip(a,b))
    assert greedy(model,x,context)==greedy(old,x,context)
    spec=subject.checked_specification(model,codec)
    assert spec["paired_fresh_initial_logits_exact"] and spec["initial_decoder_logits_unchanged"]
    assert spec["additional_trainable_parameters"]==64*(dimension+1)
    assert sum(p.numel() for p in model.parameters())-sum(p.numel() for p in old.parameters())==64*(dimension+1)


@pytest.mark.parametrize("dimension", [8,384,768])
def test_exact_copied_projection_readout_rows_no_dead_action_parameters(dimension):
    model,old,codec,_=fixture(dimension,fitted=True);size=len(codec["target_vocabulary"])
    expected=torch.tensor([i*size+j for i in (0,2,3) for j in range(size)])
    for head in (model.action_head,model.non_action_head):
        for name in ("weight","bias"):
            value=getattr(head.source_projection,name);original=getattr(old.clause_head.source_projection,name)
            assert torch.equal(value,original) and value.data_ptr()!=original.data_ptr()
    assert model.action_head.source_projection.weight.data_ptr()!=model.non_action_head.source_projection.weight.data_ptr()
    for name in ("weight","bias"):
        original=getattr(old.clause_head.field_readout,name)
        assert torch.equal(getattr(model.action_head.field_readout,name),original[size:2*size])
        assert torch.equal(getattr(model.non_action_head.field_readout,name),original.index_select(0,expected))
    assert not hasattr(model,"clause_head")
    assert not dict(model.body.source_value_head.named_parameters())
    assert core.tensor_digest(model.body)==core.tensor_digest(old.body)
    assert subject.checked_specification(model,codec)["fitted_donor_affine_rounding_possible"]


@pytest.mark.parametrize("dimension", [8,384,768])
def test_fitted_donor_logits_preserved_to_float_rounding(dimension):
    model,old,codec,packet=fixture(dimension,fitted=True);x=inputs(dimension,1)
    assert torch.allclose(model.source_value_logits(model.project(x),source_context=packet),
        old.source_value_logits(old.project(x),source_context=packet),atol=2e-6,rtol=2e-6)
    prefix=torch.tensor([encode(codec)])
    assert torch.allclose(model(x,prefix,source_context=packet)[1],old(x,prefix,source_context=packet)[1],atol=2e-6,rtol=2e-6)


def test_binding_preserves_caller_rng_modes_flags_gradients_and_storage():
    old,_,codec,_,_=bound(8);old.eval();old.clause_head.source_projection.train()
    for p in old.parameters():
        if p.requires_grad:p.grad=torch.ones_like(p)
    before=core.tensor_digest(old);rng=torch.random.get_rng_state().clone()
    modes={k:m.training for k,m in old.named_modules()};flags={k:p.requires_grad for k,p in old.named_parameters()}
    grads={k:None if p.grad is None else p.grad.clone() for k,p in old.named_parameters()}
    model=subject.bind_action_factorized_clause_model(old,codec=codec)
    assert torch.equal(rng,torch.random.get_rng_state()) and core.tensor_digest(old)==before
    assert {k:m.training for k,m in old.named_modules()}==modes
    assert {k:p.requires_grad for k,p in old.named_parameters()}==flags
    for name,p in old.named_parameters():
        assert p.grad is None if grads[name] is None else torch.equal(p.grad,grads[name])
    assert model.training==old.training and model.non_action_head.source_projection.training
    assert all(p.grad is None for p in model.parameters())
    assert all(p.data_ptr()!=q.data_ptr() for p in model.parameters() for q in old.parameters())


@pytest.mark.parametrize("dimension", [8,384,768])
def test_action_features_are_source_only_masked_and_independent_gradient_route(dimension):
    model,_,_,packet=fixture(dimension);x=model.project(inputs(dimension,1))
    result=model.source_action_features(x,source_context=packet)
    assert result.shape==(1,8,64) and not result[:,2:].any()
    assert torch.equal(result,model.action_features(x,source_context=packet))
    assert bool((result.abs()<=1).all())
    result.square().sum().backward()
    assert all(p.grad is not None and p.grad.abs().sum()>0 for p in model.action_head.source_projection.parameters())
    assert all(p.grad is None for p in model.action_head.field_readout.parameters())
    assert all(p.grad is None for p in model.non_action_head.parameters())
    assert all(p.grad is None for p in model.body.parameters())


@pytest.mark.parametrize("field", [0,1,2,3])
def test_full_vocabulary_scalar_gradient_is_owned_by_correct_branch(field):
    model,_,_,packet=fixture(fitted=True);x=model.project(inputs(8,1))
    logits=model.source_value_logits(x,source_context=packet)
    torch.nn.functional.cross_entropy(logits[0,:2,field],torch.tensor([3,4])).backward()
    active=model.action_head if field==1 else model.non_action_head
    inactive=model.non_action_head if field==1 else model.action_head
    assert all(p.grad is not None and p.grad.abs().sum()>0 for p in active.parameters())
    assert all(p.grad is None or not p.grad.any() for p in inactive.parameters())
    assert logits.shape[-1]>4 and logits[0,:2].count_nonzero()==2*4*logits.shape[-1]


def test_action_only_change_affects_only_causal_action_colons_not_other_fields():
    model,_,codec,packet=fixture();other=deepcopy(model)
    with torch.no_grad(): other.action_head.field_readout.bias.copy_(torch.arange(len(codec["target_vocabulary"]),dtype=torch.float32))
    tokens=encode(codec);prefix=torch.tensor([tokens]);x=inputs(8,1)
    old=model(x,prefix,source_context=packet)[1];new=other(x,prefix,source_context=packet)[1]
    action=codec["target_vocabulary"].index('"action"');colon=codec["target_vocabulary"].index(":")
    expected={i for i in range(1,len(tokens)) if tokens[i]==colon and tokens[i-1]==action}
    changed={i for i in range(len(tokens)) if not torch.equal(old[0,i],new[0,i])}
    assert expected and changed==expected
    assert torch.equal(old[:,0],new[:,0])


def test_clause_permutation_is_shared_head_equivariance_not_forced_output_order():
    model,_,_,packet=fixture(fitted=True);x=model.project(inputs(8,1))
    swapped={k:v.clone() for k,v in packet.items()};swapped["vectors"][:,[0,1]]=swapped["vectors"][:,[1,0]]
    expected=model.source_value_logits(x,source_context=packet);actual=model.source_value_logits(x,source_context=swapped)
    assert torch.equal(actual[:,0],expected[:,1]) and torch.equal(actual[:,1],expected[:,0])
    old=model.start(x,source_context=packet);new=model.start(x,source_context=swapped)
    assert all(torch.equal(a,b) for a,b in zip(old[:-1],new[:-1]))


def test_incremental_prefix_matches_full_prefix_after_nonzero_factorized_guidance():
    model,_,codec,packet=fixture(fitted=True);x=model.project(inputs(8,1));tokens=torch.tensor([encode(codec)])
    whole=model.next_logits(tokens,model.start(x,source_context=packet))[0]
    state=model.start(x,source_context=packet);parts=[]
    for offset in range(tokens.shape[1]):
        logits,state=model.next_logits(tokens[:,offset:offset+1],state);parts.append(logits)
    assert torch.allclose(torch.cat(parts,dim=1),whole,atol=2e-6,rtol=2e-6)


def test_zero_control_discards_original_source_mask_retains_all_eight_branch_biases():
    model,_,codec,packet=fixture(fitted=True);zero=subject.bind_zero_condition_model(model)
    different={"vectors":torch.randn(packet["vectors"].shape,generator=torch.Generator().manual_seed(7)),
        "mask":torch.ones_like(packet["mask"])}
    a=zero.start(zero.project(inputs(8,1)),source_context=packet)
    b=zero.start(zero.project(inputs(8,1)+40),source_context=different)
    assert all(torch.equal(left,right) for left,right in zip(a,b))
    assert not a[0].any() and not a[1].any() and a[-1].any()
    assert torch.equal(a[-1][:,0],a[-1][:,7])
    feat=zero.source_action_features(inputs(8,1),source_context=packet)
    assert torch.equal(feat[:,0],feat[:,7]) and feat.any()
    tokens=torch.tensor([encode(codec)])
    assert torch.equal(zero.next_logits(tokens,a)[0],zero.next_logits(tokens,b)[0])


@pytest.mark.parametrize("name", ["clause_source_mean","clause_source_scale","head_initialization_seed",
    "body.source_mean","body.source_scale","body.count_prior_logits","body.body.body.projection_down.weight",
    "body.body.body.projection_up.bias"])
def test_frozen_state_tamper_rejected_before_any_mutation(name):
    model,_,_,_=fixture();before=core.tensor_digest(model);state=deepcopy(model.state_dict())
    state["action_head.field_readout.bias"].add_(.3)
    state[name]=state[name]+1
    with pytest.raises(ValueError,match="frozen"):model.load_state_dict(state)
    assert core.tensor_digest(model)==before


@pytest.mark.parametrize("mutation", ["missing","extra","shape","dtype","nan","seed_float","strict","assign"])
def test_strict_restore_is_complete_typed_and_atomic(mutation):
    model,_,_,_=fixture();before=core.tensor_digest(model);state=deepcopy(model.state_dict());kwargs={}
    state["non_action_head.field_readout.bias"].add_(.2)
    if mutation=="missing":state.pop("action_head.field_readout.bias")
    elif mutation=="extra":state["clause_head.field_readout.bias"]=torch.zeros(1)
    elif mutation=="shape":state["action_head.field_readout.weight"]=torch.zeros(1)
    elif mutation=="dtype":state["action_head.source_projection.weight"]=state["action_head.source_projection.weight"].double()
    elif mutation=="nan":state["action_head.source_projection.bias"][0]=float("nan")
    elif mutation=="seed_float":state["head_initialization_seed"]=state["head_initialization_seed"].float()
    elif mutation=="strict":kwargs["strict"]=False
    else:kwargs["assign"]=True
    with pytest.raises(ValueError):model.load_state_dict(state,**kwargs)
    assert core.tensor_digest(model)==before


def test_trained_state_roundtrip_remains_compatible_and_does_not_freeze_action_learning():
    model,_,codec,packet=fixture();other,_,_,_=fixture()
    with torch.no_grad():
        model.action_head.source_projection.weight.add_(.01)
        model.action_head.field_readout.weight.add_(.1)
        model.non_action_head.field_readout.bias.add_(.2)
    other.load_state_dict(model.state_dict())
    assert core.tensor_digest(other)==core.tensor_digest(model)
    assert subject.checked_specification(other,codec)["schema"]==subject.SCHEMA
    x=inputs(8,1);prefix=torch.tensor([encode(codec)])
    assert torch.equal(model(x,prefix,source_context=packet)[1],other(x,prefix,source_context=packet)[1])


@pytest.mark.parametrize("mutation", ["codec","dead","frozen_head","shared_storage","normalization"])
def test_specification_rejects_mutated_architecture_and_semantics(mutation):
    model,_,codec,_=fixture();codec=deepcopy(codec)
    if mutation=="codec":codec["target_vocabulary"]=codec["target_vocabulary"][::-1]
    elif mutation=="dead":model.register_parameter("unused_action",torch.nn.Parameter(torch.zeros(1)))
    elif mutation=="frozen_head":model.action_head.source_projection.weight.requires_grad_(False)
    elif mutation=="shared_storage":model.action_head.source_projection.weight=model.non_action_head.source_projection.weight
    else:model.clause_source_scale.add_(1.)
    with pytest.raises(ValueError):subject.checked_specification(model,codec)


@pytest.mark.parametrize("mutation", ["missing","target","wrong_dimension","noncontiguous_mask","nan"])
def test_explicit_context_is_required_closed_source_only_and_validated(mutation):
    model,_,_,packet=fixture();x=model.project(inputs(8,1));packet=deepcopy(packet)
    if mutation=="missing":
        with pytest.raises(TypeError):model.source_action_features(x)
        return
    if mutation=="target":packet["target_ids"]=[1,2]
    elif mutation=="wrong_dimension":packet["vectors"]=packet["vectors"][:,:,:7]
    elif mutation=="noncontiguous_mask":packet["mask"][0,0]=False
    else:packet["vectors"][0,0,0]=float("nan")
    with pytest.raises(ValueError):model.source_action_features(x,source_context=packet)
