"""Synthetic shared-slot invariants; these are not source-fidelity evidence."""
from copy import deepcopy
import random

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import shared_slot_source_decoder_experiment as subject
from ipfs_datasets_py.logic.formalization.autoencoder import source_value_decoder_experiment as values
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_cardinality_experiment as cardinality
from .test_projected_source_decoder_experiment import bound, inputs, encode, rule


@pytest.fixture(autouse=True)
def one_cpu():
    old = torch.get_num_threads(); torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


def make(dimension=8, kind="center_rms", seed=1729, guided=True):
    base, codec, _ = bound(dimension=dimension, kind=kind, guided=guided)
    model = subject.bind_shared_slot_source_model(base, head_seed=seed)
    return model, base, codec


def perturb(model):
    head = model.body.source_value_head
    generator = torch.Generator().manual_seed(63)
    with torch.no_grad():
        head.field_readout.weight.copy_(torch.randn(head.field_readout.weight.shape, generator=generator)*.3)
        head.field_readout.bias.copy_(torch.randn(head.field_readout.bias.shape, generator=generator)*.1)


@pytest.mark.parametrize("dimension", [8, 384, 768])
@pytest.mark.parametrize("kind", ["none", "center_rms"])
def test_zero_readout_preserves_complete_initial_logits_and_inherited_state(dimension, kind):
    model, base, codec = make(dimension, kind)
    old = subject.core.tensor_digest(base)
    data = inputs(dimension); prefix = torch.tensor([encode(codec)[:-1]]*2)
    with torch.no_grad():
        original_projected, expected = base(data, prefix)
        projected, actual = model(data, prefix)
    assert torch.equal(projected, original_projected) and torch.equal(actual, expected)
    assert torch.equal(model.count_logits(projected), base.count_logits(projected))
    assert torch.count_nonzero(model.source_value_logits(projected)) == 0
    assert subject.core.tensor_digest(base) == old
    for name, tensor in base.state_dict().items():
        if not name.startswith("source_value_head."):
            assert torch.equal(model.body.state_dict()[name], tensor)
    description = subject.checked_specification(model, codec)
    assert description["base_architecture_is_pre_replacement_donor"] is True
    assert description["source_value_parameter_count"] == (dimension+1)*64+8*64+65*4*len(codec["target_vocabulary"])
    assert description["source_value_parameter_count"] < description["replaced_source_value_parameter_count"] or dimension == 8
    assert not any(name in model.state_dict() for name in ("body.source_value_head.weight", "body.source_value_head.bias"))


def test_private_seed_determinism_ambient_rng_and_caller_modes_are_preserved():
    base, codec, _ = bound(dimension=8, kind="center_rms", guided=True)
    base.eval(); base.body.train()
    modes = {name: module.training for name, module in base.named_modules()}
    before = subject.core.tensor_digest(base); python_rng = random.getstate(); torch_rng = torch.get_rng_state().clone()
    a = subject.bind_shared_slot_source_model(base, head_seed=91)
    assert torch.equal(torch.get_rng_state(), torch_rng) and random.getstate() == python_rng
    torch.manual_seed(90001); changed_rng = torch.get_rng_state().clone()
    b = subject.bind_shared_slot_source_model(base, head_seed=91)
    assert torch.equal(torch.get_rng_state(), changed_rng)
    assert subject.core.tensor_digest(a) == subject.core.tensor_digest(b)
    c = subject.bind_shared_slot_source_model(base, head_seed=92)
    assert subject.core.tensor_digest(c) != subject.core.tensor_digest(a)
    assert subject.core.tensor_digest(base) == before
    assert {name: module.training for name, module in base.named_modules()} == modes
    assert all(a.data_ptr() != b.data_ptr() for a, b in zip(a.parameters(), base.parameters()))
    torch.set_rng_state(torch_rng)


@pytest.mark.parametrize("seed", [True, -1, 2**31, 1.5, None])
def test_invalid_seed_refused(seed):
    base, _, _ = bound(dimension=8)
    with pytest.raises(ValueError, match="seed"):
        subject.bind_shared_slot_source_model(base, head_seed=seed)


@pytest.mark.parametrize("width", [True, 0, 63, 128, 64.])
def test_unreviewed_hidden_width_refused(width):
    base, _, _ = bound(dimension=8)
    with pytest.raises(ValueError, match="width"):
        subject.bind_shared_slot_source_model(base, head_seed=1, hidden_width=width)


def test_fitted_affine_donor_is_not_silently_discarded():
    base, _, _ = bound(dimension=8)
    with torch.no_grad(): base.source_value_head.bias[0] = 1.
    old = subject.core.tensor_digest(base)
    with pytest.raises(ValueError, match="fitted heads"):
        subject.bind_shared_slot_source_model(base, head_seed=1)
    assert subject.core.tensor_digest(base) == old


@pytest.mark.parametrize("field", ["source_mean", "source_scale", "count_prior_logits"])
def test_binding_rejects_unrecorded_frozen_buffer_changes(field):
    base, _, _ = bound(dimension=8)
    with torch.no_grad(): getattr(base,field).add_(1)
    before=subject.core.tensor_digest(base)
    with pytest.raises(ValueError,match="buffer"):
        subject.bind_shared_slot_source_model(base,head_seed=1)
    assert subject.core.tensor_digest(base)==before


def test_binding_rejects_changed_count_head_geometry():
    base, _, _ = bound(dimension=8)
    base.count_head=torch.nn.Linear(8,31)
    with pytest.raises(ValueError,match="count head"):
        subject.bind_shared_slot_source_model(base,head_seed=1)


def test_explicit_shared_formula_matches_all_slots_fields_and_vocabulary():
    model, _, codec = make(); perturb(model)
    projected = model.project(inputs(8)); features = model.body._features(projected)
    head = model.body.source_value_head
    hidden = torch.tanh(torch.nn.functional.linear(features, head.source_projection.weight,
        head.source_projection.bias)[:, None, :]+head.slot_embeddings[None, :, :])
    expected = torch.nn.functional.linear(hidden, head.field_readout.weight, head.field_readout.bias).reshape(2,8,4,-1)
    assert torch.equal(model.source_value_logits(projected), expected)
    assert torch.equal(model.source_value_guidance_logits(projected), expected)
    assert expected.shape == (2,8,4,len(codec["target_vocabulary"]))
    assert torch.isfinite(expected).all()


def test_nonlinearity_creates_real_source_position_interaction():
    model, _, _ = make(); head = model.body.source_value_head
    with torch.no_grad():
        for parameter in head.parameters(): parameter.zero_()
        head.source_projection.weight[0,0] = 1.
        head.slot_embeddings[1,0] = 1.
        head.field_readout.weight[0,0] = 1.
    x = torch.zeros(2,8); x[1,0] = 1.
    score = head(x).reshape(2,8,4,-1)
    # Slot differences depend on source x; this is not just a position bias.
    assert not torch.isclose(score[0,1,0,0]-score[0,0,0,0], score[1,1,0,0]-score[1,0,0,0])


def test_readout_is_shared_across_slots_and_gradient_reaches_other_slot_behavior():
    model, _, _ = make(); head = model.body.source_value_head
    x = torch.ones(1,8); before = head(x).reshape(1,8,4,-1).detach().clone()
    score = head(x).reshape(1,8,4,-1)
    gradient = torch.autograd.grad(-score[0,0,0,3], head.field_readout.weight)[0]
    with torch.no_grad(): head.field_readout.weight.sub_(.1*gradient)
    after = head(x).reshape(1,8,4,-1)
    assert after[0,0,0,3] != before[0,0,0,3]
    assert after[0,7,0,3] != before[0,7,0,3]
    assert torch.equal(after[:,:,1:], before[:,:,1:])


def test_zero_init_gradient_then_source_slot_and_auxiliary_gradients():
    model, _, _ = make(); head = model.body.source_value_head
    projected = model.project(inputs(8)); score = model.source_value_logits(projected)
    targets = torch.full((2*8*4,), 3, dtype=torch.long)
    loss = torch.nn.functional.cross_entropy(score.flatten(0,2), targets); loss.backward()
    assert torch.count_nonzero(head.field_readout.weight.grad) > 0
    assert torch.count_nonzero(head.field_readout.bias.grad) > 0
    assert torch.count_nonzero(head.source_projection.weight.grad) == 0
    assert torch.count_nonzero(head.slot_embeddings.grad) == 0
    model.zero_grad(); perturb(model)
    score = model.source_value_logits(model.project(inputs(8)))
    torch.nn.functional.cross_entropy(score.flatten(0,2), targets).backward()
    for parameter in head.parameters():
        assert parameter.grad is not None and torch.isfinite(parameter.grad).all()
        assert torch.count_nonzero(parameter.grad) > 0
    for name, parameter in model.named_parameters():
        if "projection_down." in name or "projection_up." in name:
            assert not parameter.requires_grad and parameter.grad is None


def test_sequence_loss_also_trains_shared_scalar_readout_at_actual_prefix_sites():
    model, _, codec = make(); data = inputs(8)
    ids = torch.tensor([encode(codec)]*2)
    _, logits = model(data, ids[:,:-1])
    torch.nn.functional.cross_entropy(logits.flatten(0,1), ids[:,1:].flatten()).backward()
    head = model.body.source_value_head
    assert torch.count_nonzero(head.field_readout.weight.grad) > 0
    assert torch.count_nonzero(head.field_readout.bias.grad) > 0


def test_causal_integration_incremental_prefix_and_request_isolation():
    model, _, codec = make(); perturb(model)
    projected = model.project(inputs(8)); prefix = torch.tensor([encode(codec)[:-1]]*2)
    state = model.start(projected); saved = [value.clone() for value in state]
    full, _ = model.next_logits(prefix, state)
    recurrent_logits, _ = model.body.body.next_logits(prefix, state[:3])
    without = model.body.next_logits(prefix, (*state[:-1], torch.zeros_like(state[-1])))[0]
    tables = cardinality._tables(codec, len(codec["target_vocabulary"]), torch)
    _, sites = values._scan_value_prefix(prefix.tolist(), state[4].tolist(), tables, 8)
    expected = torch.zeros_like(full)
    for row, offset, slot, field in sites: expected[row,offset] += state[-1][row,slot,field]
    assert torch.allclose(full-without, expected, atol=2e-7)
    incremental = model.start(projected); parts = []
    for offset in range(prefix.shape[1]):
        logits, incremental = model.next_logits(prefix[:,offset:offset+1], incremental); parts.append(logits)
    assert torch.allclose(full, torch.cat(parts,1), atol=1e-6, rtol=1e-6)
    assert all(torch.equal(a,b) for a,b in zip(state,saved))
    model.start(projected+1)
    assert torch.equal(model.next_logits(prefix,state)[0],full)
    assert not model.describe()["source_context_cached_on_module"]


def test_no_vocabulary_mask_or_forced_semantics_and_invalid_prefix_disables_guidance():
    model, _, codec = make(); head = model.body.source_value_head
    with torch.no_grad():
        head.field_readout.bias.reshape(4,-1)[:,0] = 100.
    projected = model.project(inputs(8)); state = model.start(projected)
    prefix = torch.tensor([encode(codec)[:-1]]*2)
    _, sites = values._scan_value_prefix(prefix.tolist(), state[4].tolist(),
        cardinality._tables(codec,len(codec["target_vocabulary"]),torch),8)
    logits, _ = model.next_logits(prefix,state)
    for row,offset,_,_ in sites: assert int(logits[row,offset].argmax()) == 0
    invalid = torch.cat((torch.tensor([[1,0],[1,0]]),prefix[:,1:]),dim=1)
    actual, _ = model.next_logits(invalid,model.start(projected))
    without, _ = model.next_logits(invalid,(*model.start(projected)[:-1],torch.zeros_like(state[-1])))
    assert torch.equal(actual,without)


def test_slot_cap_does_not_mask_or_close_ninth_rule():
    model, _, codec = make(guided=False); perturb(model)
    prefix = torch.tensor([encode(codec,{"rules":[rule() for _ in range(9)]})[:-1]])
    projected = model.project(inputs(8,1)); state = model.start(projected)
    actual, _ = model.next_logits(prefix,state)
    original, _ = model.body.body.next_logits(prefix,state[:3])
    tables = cardinality._tables(codec,len(codec["target_vocabulary"]),torch)
    _, all_sites = values._scan_value_prefix(prefix.tolist(),state[4].tolist(),tables,9)
    ninth = [offset for row,offset,slot,field in all_sites if slot==8]
    assert len(ninth)==4
    for offset in ninth: assert torch.equal(actual[0,offset],original[0,offset])


@pytest.mark.parametrize("kind", ["none", "center_rms"])
def test_zero_control_retains_source_independent_slot_and_bias_priors(kind):
    model, _, codec = make(kind=kind); perturb(model)
    with torch.no_grad(): model.body.count_head.bias[0]=.5
    control = subject.bind_zero_condition_model(model)
    projected = model.project(inputs(8)); state = control.start(projected)
    expected = model.body.source_value_head(torch.zeros_like(projected)).reshape(2,8,4,-1)
    assert torch.equal(control.source_value_logits(projected),expected)
    assert torch.equal(control.source_value_guidance_logits(projected),expected)
    assert torch.count_nonzero(state[0]) == torch.count_nonzero(state[1]) == 0
    assert torch.equal(state[-1],expected) and torch.count_nonzero(expected)>0
    assert torch.equal(control.count_logits(projected),
        (model.body.count_head.bias+model.body.count_prior_logits)[None,:].expand(2,-1))
    prefix=torch.tensor([encode(codec)[:-1]]*2)
    assert torch.equal(control.next_logits(prefix,control.start(projected))[0],
        control.next_logits(prefix,control.start(projected+3))[0])


@pytest.mark.parametrize("key", ["body.source_mean", "body.source_scale", "body.count_prior_logits", "head_initialization_seed"])
def test_frozen_buffers_reject_changed_checkpoint_before_parameter_mutation(key):
    model, _, _ = make(); state=deepcopy(model.state_dict()); before=subject.core.tensor_digest(model)
    state[key]=state[key]+1
    state["body.source_value_head.field_readout.weight"]+=1
    with pytest.raises(ValueError,match="restored frozen"):
        model.load_state_dict(state)
    assert subject.core.tensor_digest(model)==before


def test_fitted_same_architecture_state_roundtrips_and_different_seed_refused():
    model, _, codec=make(seed=1); perturb(model)
    other, _, _=make(seed=1); other.load_state_dict(deepcopy(model.state_dict()))
    assert subject.core.tensor_digest(other)==subject.core.tensor_digest(model)
    subject.checked_specification(other,codec)
    different, _, _=make(seed=2)
    with pytest.raises(ValueError,match="frozen"):
        different.load_state_dict(model.state_dict())


@pytest.mark.parametrize("mutation", ["dtype", "shape", "missing"])
def test_seed_buffer_checkpoint_guard_rejects_nonexact_representation(mutation):
    model, _, _=make(); state=deepcopy(model.state_dict()); before=subject.core.tensor_digest(model)
    if mutation=="dtype":state["head_initialization_seed"]=state["head_initialization_seed"].float()
    elif mutation=="shape":state["head_initialization_seed"]=state["head_initialization_seed"].reshape(1)
    else:del state["head_initialization_seed"]
    with pytest.raises(ValueError,match="frozen"):
        model.load_state_dict(state,strict=False)
    assert subject.core.tensor_digest(model)==before


@pytest.mark.parametrize("mutation", ["nan", "frozen_head", "shape", "codec", "projection", "receipt", "mode"])
def test_closed_specification_refuses_changed_geometry_policy_and_provenance(mutation):
    model, _, codec=make(); codec=deepcopy(codec); head=model.body.source_value_head
    if mutation=="nan":
        with torch.no_grad():head.field_readout.bias[0]=float("nan")
    elif mutation=="frozen_head":head.slot_embeddings.requires_grad_(False)
    elif mutation=="shape":head.slot_embeddings=torch.nn.Parameter(torch.zeros(7,64))
    elif mutation=="codec":codec["target_vocabulary"][-1]="changed"
    elif mutation=="projection":
        for name, parameter in model.named_parameters():
            if "projection_down." in name:parameter.requires_grad_(True)
    else:
        original=model.describe
        def changed():
            result=original()
            if mutation=="receipt":result["normalization"]["mean"][0]+=1
            else:result["scalar_mode"]="off"
            return result
        model.describe=changed
    with pytest.raises(ValueError):subject.checked_specification(model,codec)


def test_description_copy_cannot_change_architecture_receipts():
    model, _, codec=make(); description=model.describe()
    description["normalization"]["mean"][0]+=100
    description["source_fields"].clear();description["base_architecture"]["count_prior"]["log_prior"][0]=0
    checked=subject.checked_specification(model,codec)
    assert len(checked["source_fields"])==4
    assert not checked["admitted"] and not checked["qualified"]
