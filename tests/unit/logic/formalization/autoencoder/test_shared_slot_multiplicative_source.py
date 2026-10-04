"""Synthetic multiplicative-source invariants; no fidelity or admission claim."""
from copy import deepcopy
import random
import time

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import shared_slot_source_decoder_experiment as subject
from ipfs_datasets_py.logic.formalization.autoencoder import source_value_decoder_experiment as values
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_cardinality_experiment as cardinality
from .test_projected_source_decoder_experiment import bound, inputs, encode, rule
from .test_shared_slot_source_decoder_experiment import perturb


@pytest.fixture(autouse=True)
def one_cpu():
    old = torch.get_num_threads(); torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


def make(dimension=8, kind="center_rms", seed=1729, guided=True):
    base, codec, _ = bound(dimension=dimension, kind=kind, guided=guided)
    model = subject.bind_shared_slot_source_model(base, head_seed=seed,
        slot_interaction="additive_multiplicative")
    return model, base, codec


@pytest.mark.parametrize("dimension", [8, 384, 768])
@pytest.mark.parametrize("kind", ["none", "center_rms"])
def test_identical_initial_float_parameters_full_logits_and_greedy(dimension, kind):
    model, base, codec = make(dimension, kind)
    default = subject.bind_shared_slot_source_model(base, head_seed=1729)
    explicit = subject.bind_shared_slot_source_model(base, head_seed=1729, slot_interaction="additive")
    assert default.describe() == explicit.describe()
    assert subject.core.tensor_digest(default) == subject.core.tensor_digest(explicit)
    assert not any(k in default.describe() for k in subject.INTERACTION_FIELDS)
    assert "slot_interaction_version" not in default.state_dict()
    assert set(model.state_dict()) == set(default.state_dict()) | {"slot_interaction_version"}
    for name, tensor in default.state_dict().items():
        assert torch.equal(model.state_dict()[name], tensor)
    assert model.slot_interaction_version.dtype == torch.long and int(model.slot_interaction_version) == 1
    assert sum(p.numel() for p in model.parameters()) == sum(p.numel() for p in default.parameters())
    data = inputs(dimension); prefix = torch.tensor([encode(codec)[:-1]]*2)
    with torch.no_grad():
        z, actual = model(data, prefix); zd, expected = default(data, prefix)
        assert torch.equal(z, zd) and torch.equal(actual, expected)
        assert torch.count_nonzero(model.source_value_logits(z)) == 0
        assert torch.equal(model.count_logits(z), default.count_logits(z))
        a = subject.core._greedy(torch, model, data, 32, len(codec["target_vocabulary"]), time.monotonic()+5)
        b = subject.core._greedy(torch, default, data, 32, len(codec["target_vocabulary"]), time.monotonic()+5)
        assert torch.equal(a[0], b[0]) and a[1:] == b[1:]
    description = subject.checked_specification(model, codec)
    assert description["source_value_parameter_count"] == default.describe()["source_value_parameter_count"]
    assert description["additional_trainable_parameters"] == 0
    assert description["slot_modulation_and_offset_parameters_tied"] is True


def test_binding_preserves_ambient_rng_caller_modes_and_storage():
    base, codec, _ = bound(dimension=8, kind="center_rms", guided=True)
    base.eval(); base.body.train()
    modes = {n:m.training for n,m in base.named_modules()}
    before = subject.core.tensor_digest(base); state = torch.get_rng_state().clone(); py = random.getstate()
    model = subject.bind_shared_slot_source_model(base, head_seed=1729, slot_interaction="additive_multiplicative")
    assert torch.equal(state, torch.get_rng_state()) and py == random.getstate()
    assert before == subject.core.tensor_digest(base)
    assert modes == {n:m.training for n,m in base.named_modules()}
    again = subject.bind_shared_slot_source_model(base, head_seed=1729, slot_interaction="additive_multiplicative")
    assert subject.core.tensor_digest(model) == subject.core.tensor_digest(again)
    assert all(a.data_ptr()!=b.data_ptr() for a,b in zip(model.parameters(), again.parameters()))
    assert not model.describe()["source_context_cached_on_module"]


@pytest.mark.parametrize("mode", [None, True, 1, [], "multiply", "", "ADDITIVE"])
def test_unknown_or_implicit_modes_are_rejected(mode):
    base, _, _ = bound(dimension=8)
    before = subject.core.tensor_digest(base)
    with pytest.raises(ValueError, match="interaction"):
        subject.bind_shared_slot_source_model(base, head_seed=1729, slot_interaction=mode)
    assert subject.core.tensor_digest(base) == before


def test_exact_fixed_formula_for_every_slot_field_and_token():
    model, _, codec = make(); perturb(model)
    projected = model.project(inputs(8)); x = model.body._features(projected)
    head = model.body.source_value_head
    u = torch.nn.functional.linear(x, head.source_projection.weight, head.source_projection.bias)[:,None,:]
    e = head.slot_embeddings[None,:,:]
    hidden = torch.tanh(u*(1+e)+e)
    expected = torch.nn.functional.linear(hidden, head.field_readout.weight, head.field_readout.bias).reshape(2,8,4,-1)
    assert torch.equal(model.source_value_logits(projected), expected)
    assert torch.equal(model.source_value_guidance_logits(projected), expected)
    old = torch.nn.functional.linear(torch.tanh(u+e), head.field_readout.weight, head.field_readout.bias).reshape_as(expected)
    assert not torch.equal(expected, old)
    assert expected.shape == (2,8,4,len(codec["target_vocabulary"]))
    assert torch.isfinite(expected).all()


def test_slot_derivative_contains_real_source_modulation_and_shared_readout():
    model, _, _ = make(); head=model.body.source_value_head
    with torch.no_grad():
        for p in head.parameters():p.zero_()
        head.source_projection.weight[0,0]=1
        head.slot_embeddings[1,0]=.3
        head.field_readout.weight[0,0]=1
    x=torch.zeros(1,8);x[0,0]=.7
    score=head(x).reshape(1,8,4,-1)
    gradient=torch.autograd.grad(score[0,1,0,0],head.slot_embeddings)[0]
    expected=(1+.7)*(1-torch.tanh(torch.tensor(.7*1.3+.3)).square())
    assert torch.allclose(gradient[1,0],expected,atol=1e-7)
    assert torch.count_nonzero(gradient)==1
    # One readout parameter affects every slot; slots have no independent head.
    before=score.detach().clone()
    with torch.no_grad():head.field_readout.weight[0,0]+=.2
    after=head(x).reshape_as(before)
    assert after[0,0,0,0]!=before[0,0,0,0] and after[0,7,0,0]!=before[0,7,0,0]
    assert torch.equal(after[:,:,1:],before[:,:,1:])


def test_auxiliary_and_sequence_gradients_reach_readout_then_all_shared_parameters():
    model, _, codec=make();data=inputs(8);ids=torch.tensor([encode(codec)]*2)
    _,logits=model(data,ids[:,:-1])
    torch.nn.functional.cross_entropy(logits.flatten(0,1),ids[:,1:].flatten()).backward()
    head=model.body.source_value_head
    assert torch.count_nonzero(head.field_readout.weight.grad)>0
    assert torch.count_nonzero(head.source_projection.weight.grad)==0
    assert torch.count_nonzero(head.slot_embeddings.grad)==0
    model.zero_grad();perturb(model)
    scalar=model.source_value_logits(model.project(data))
    targets=torch.full((2*8*4,),3,dtype=torch.long)
    torch.nn.functional.cross_entropy(scalar.flatten(0,2),targets).backward()
    for p in head.parameters():
        assert p.grad is not None and torch.isfinite(p.grad).all() and torch.count_nonzero(p.grad)>0
    for name,p in model.named_parameters():
        if "projection_down." in name or "projection_up." in name:
            assert not p.requires_grad and p.grad is None


def test_causal_full_prefix_equals_incremental_with_immutable_request_state():
    model, _, codec=make();perturb(model)
    projected=model.project(inputs(8));prefix=torch.tensor([encode(codec)[:-1]]*2)
    state=model.start(projected);saved=[v.clone() for v in state]
    full,_=model.next_logits(prefix,state)
    reduced,_=model.next_logits(prefix,(*state[:-1],torch.zeros_like(state[-1])))
    _,sites=values._scan_value_prefix(prefix.tolist(),state[4].tolist(),
        cardinality._tables(codec,len(codec["target_vocabulary"]),torch),8)
    expected=torch.zeros_like(full)
    for row,offset,slot,field in sites:expected[row,offset]+=state[-1][row,slot,field]
    assert torch.allclose(full-reduced,expected,atol=2e-7)
    pieces=[];running=model.start(projected)
    for j in range(prefix.shape[1]):
        part,running=model.next_logits(prefix[:,j:j+1],running);pieces.append(part)
    assert torch.allclose(full,torch.cat(pieces,1),atol=1e-6,rtol=1e-6)
    assert all(torch.equal(a,b) for a,b in zip(state,saved))
    model.start(projected+2)
    assert torch.equal(full,model.next_logits(prefix,state)[0])


def test_full_vocabulary_and_invalid_prefix_and_ninth_rule_keep_inherited_policy():
    model, _, codec=make(guided=False);head=model.body.source_value_head
    with torch.no_grad():head.field_readout.bias.reshape(4,-1)[:,0]=100
    projected=model.project(inputs(8,1));prefix=torch.tensor([encode(codec,{"rules":[rule() for _ in range(9)]})[:-1]])
    state=model.start(projected);actual,_=model.next_logits(prefix,state)
    inherited,_=model.body.body.next_logits(prefix,state[:3])
    _,sites=values._scan_value_prefix(prefix.tolist(),state[4].tolist(),
        cardinality._tables(codec,len(codec["target_vocabulary"]),torch),9)
    for row,offset,slot,_ in sites:
        if slot<8:assert int(actual[row,offset].argmax())==0
        else:assert torch.equal(actual[row,offset],inherited[row,offset])
    invalid=torch.cat((torch.tensor([[1,0]]),prefix[:,1:]),dim=1)
    a,_=model.next_logits(invalid,state)
    b,_=model.next_logits(invalid,(*state[:-1],torch.zeros_like(state[-1])))
    assert torch.equal(a,b)


@pytest.mark.parametrize("kind", ["none", "center_rms"])
def test_zero_source_control_preserves_learned_bias_and_tied_slot_priors(kind):
    model, _, codec=make(kind=kind);perturb(model)
    with torch.no_grad():
        model.body.source_value_head.source_projection.bias.add_(.4)
        model.body.count_head.bias[0]=.5
    zero=subject.bind_zero_condition_model(model);projected=model.project(inputs(8))
    expected=model.body.source_value_head(torch.zeros_like(projected)).reshape(2,8,4,-1)
    state=zero.start(projected)
    assert torch.equal(state[-1],expected) and torch.count_nonzero(expected)>0
    assert torch.equal(zero.source_value_logits(projected),expected)
    assert torch.count_nonzero(state[0])==torch.count_nonzero(state[1])==0
    assert torch.equal(zero.count_logits(projected),
        (model.body.count_head.bias+model.body.count_prior_logits)[None,:].expand(2,-1))
    prefix=torch.tensor([encode(codec)[:-1]]*2)
    assert torch.equal(zero.next_logits(prefix,state)[0],zero.next_logits(prefix,zero.start(projected+2))[0])
    assert zero.describe()["slot_interaction"]=="additive_multiplicative"


@pytest.mark.parametrize("target_mode,source_mode", [("additive","additive_multiplicative"),("additive_multiplicative","additive")])
@pytest.mark.parametrize("strict", [True,False])
def test_cross_mode_checkpoint_rejected_before_any_mutation(target_mode,source_mode,strict):
    base,_,_=bound(dimension=8)
    target=subject.bind_shared_slot_source_model(base,head_seed=1,slot_interaction=target_mode)
    source=subject.bind_shared_slot_source_model(base,head_seed=1,slot_interaction=source_mode)
    perturb(source);before=subject.core.tensor_digest(target)
    with pytest.raises(ValueError,match="interaction|frozen"):
        target.load_state_dict(source.state_dict(),strict=strict)
    assert subject.core.tensor_digest(target)==before


@pytest.mark.parametrize("key", ["slot_interaction_version","head_initialization_seed"])
@pytest.mark.parametrize("mutation", ["missing","dtype","shape","value"])
def test_frozen_mode_and_seed_cannot_be_rewritten_during_restore(key,mutation):
    model,_,_=make();state=deepcopy(model.state_dict());before=subject.core.tensor_digest(model)
    state["body.source_value_head.field_readout.weight"]+=1
    if mutation=="missing":del state[key]
    elif mutation=="dtype":state[key]=state[key].float()
    elif mutation=="shape":state[key]=state[key].reshape(1)
    else:state[key]+=1
    with pytest.raises(ValueError,match="frozen"):
        model.load_state_dict(state,strict=False)
    assert subject.core.tensor_digest(model)==before


def test_same_mode_fitted_state_copy_roundtrips_without_aliasing():
    model,_,codec=make(seed=11);perturb(model)
    other,_,_=make(seed=11);other.load_state_dict(deepcopy(model.state_dict()))
    assert subject.core.tensor_digest(other)==subject.core.tensor_digest(model)
    subject.checked_specification(other,codec)
    assert all(a.data_ptr()!=b.data_ptr() for a,b in zip(model.parameters(),other.parameters()))
    assert torch.equal(model.source_value_logits(model.project(inputs(8))),
        other.source_value_logits(other.project(inputs(8))))


@pytest.mark.parametrize("mutation", ["mode","formula","version","dtype","new_parameters","tied","modulation","missing_mode","false_additive"])
def test_forged_or_inconsistent_architecture_refused(mutation):
    model,_,codec=make();old=model.describe
    if mutation=="dtype":model.slot_interaction_version=model.slot_interaction_version.float()
    else:
        def forged():
            d=old()
            if mutation=="mode":d["slot_interaction"]="unknown"
            elif mutation=="formula":d["source_formula"]=subject.ADDITIVE_FORMULA
            elif mutation=="version":d["slot_interaction_version"]=True
            elif mutation=="new_parameters":d["additional_trainable_parameters"]=512
            elif mutation=="tied":d["slot_modulation_and_offset_parameters_tied"]=False
            elif mutation=="modulation":d["slot_modulation_formula"]="sigmoid(slot)"
            elif mutation=="missing_mode":del d["slot_interaction"]
            else:
                for key in subject.INTERACTION_FIELDS:d.pop(key,None)
                d["source_formula"]=subject.ADDITIVE_FORMULA
            return d
        model.describe=forged
    with pytest.raises(ValueError,match="architecture|mode"):
        subject.checked_specification(model,codec)


def test_additive_cannot_claim_multiplicative_formula_or_mode():
    base,codec,_=bound(dimension=8);model=subject.bind_shared_slot_source_model(base,head_seed=1);old=model.describe
    def forged():
        d=old();d["slot_interaction"]="additive_multiplicative";d["source_formula"]=subject.MULTIPLICATIVE_FORMULA;return d
    model.describe=forged
    with pytest.raises(ValueError,match="additive"):
        subject.checked_specification(model,codec)
