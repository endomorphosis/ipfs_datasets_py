"""Synthetic object-projection parity and gradient contracts; no native assets."""
from copy import deepcopy

import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import isolated_object_clause_decoder_experiment as subject
from ipfs_datasets_py.logic.formalization.autoencoder import ordered_clause_recurrent_decoder_experiment as ordered
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core
from .test_ordered_clause_recurrent_decoder_experiment import fixture, inputs, encode
from .test_action_factorized_clause_decoder_experiment import greedy


@pytest.fixture(autouse=True)
def one_cpu():
    old = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


def bound(*, fitted=True):
    old, _, codec, packet = fixture(fitted=fitted)
    return subject.bind_isolated_object_model(old, codec=codec), old, codec, packet


@pytest.mark.parametrize("fitted", [False, True])
@pytest.mark.parametrize("conditioning", ["first_step", "every_step"])
def test_initial_full_logits_cached_features_and_greedy_are_exact(fitted, conditioning):
    old, _, codec, packet = fixture(fitted=fitted, conditioning=conditioning)
    with torch.no_grad():
        old.clause_to_embedding.weight.fill_(.03)
    new = subject.bind_isolated_object_model(old, codec=codec)
    x = inputs(8, 1); prefix = torch.tensor([encode(codec)])
    assert all(torch.equal(a, b) for a, b in zip(old(x, prefix, source_context=packet), new(x, prefix, source_context=packet)))
    projected = old.project(x)
    assert torch.equal(old.source_value_logits(projected, source_context=packet), new.source_value_logits(projected, source_context=packet))
    assert torch.equal(old.source_recurrent_features(projected, source_context=packet), new.source_recurrent_features(projected, source_context=packet))
    assert torch.equal(old.count_logits(projected), new.count_logits(projected))
    assert greedy(old, x, packet) == greedy(new, x, packet)
    assert all(torch.equal(tensor, new.state_dict()[name]) for name, tensor in old.state_dict().items())
    assert set(new.state_dict()) - set(old.state_dict()) == set(subject.EXTRA_NAMES)
    assert sum(p.numel() for p in new.parameters()) - sum(p.numel() for p in old.parameters()) == 576


def test_constructor_preserves_caller_rng_modes_flags_gradients_and_no_storage_sharing():
    old, _, codec, _ = fixture(fitted=True)
    old.eval(); old.non_action_head.source_projection.train()
    for p in old.parameters():
        if p.requires_grad: p.grad = torch.ones_like(p)
    identity = core.tensor_digest(old); rng = torch.get_rng_state().clone()
    modes = {name: m.training for name, m in old.named_modules()}
    flags = {name: p.requires_grad for name, p in old.named_parameters()}
    new = subject.bind_isolated_object_model(old, codec=codec)
    assert core.tensor_digest(old) == identity and torch.equal(rng, torch.get_rng_state())
    assert modes == {name: m.training for name, m in old.named_modules()}
    assert flags == {name: p.requires_grad for name, p in old.named_parameters()}
    assert all(p.grad is not None and torch.equal(p.grad, torch.ones_like(p)) for p in old.parameters() if p.requires_grad)
    assert all(p.grad is None for p in new.parameters())
    assert not new.training and new.non_action_head.source_projection.training and new.non_action_head.object_projection.training
    assert all(new.state_dict()[name].data_ptr() != tensor.data_ptr() for name, tensor in old.state_dict().items())
    pointers = [p.untyped_storage().data_ptr() for p in new.parameters()]
    assert len(pointers) == len(set(pointers))
    subject.checked_specification(new, codec)
    assert torch.equal(rng, torch.get_rng_state()) and core.tensor_digest(old) == identity


@pytest.mark.parametrize("field", ["actor", "modality", "object"])
def test_field_only_loss_reaches_only_its_source_projection(field):
    model, _, _, _ = bound()
    values = torch.linspace(-.3, .4, 2 * 8 * 8).reshape(2, 8, 8)
    logits = model.non_action_head(values).reshape(2, 8, 3, -1)
    index = {"actor": 0, "modality": 1, "object": 2}[field]
    torch.nn.functional.cross_entropy(logits[:, :, index].reshape(-1, logits.shape[-1]), torch.zeros(16, dtype=torch.long)).backward()
    shared = model.non_action_head.source_projection.weight.grad
    private = model.non_action_head.object_projection.weight.grad
    assert bool((private if field == "object" else shared).abs().sum() > 0)
    assert torch.count_nonzero(shared if field == "object" else private) == 0
    readout = model.non_action_head.field_readout.weight.grad.reshape(3, logits.shape[-1], 64)
    assert bool(readout[index].abs().sum() > 0)
    assert all(torch.count_nonzero(readout[i]) == 0 for i in range(3) if i != index)
    assert all(p.grad is None for p in model.action_head.parameters())


def test_complete_source_ce_is_identical_and_shared_gradient_splits_without_discard():
    model, old, codec, _ = bound()
    values = torch.linspace(-.4, .3, 128).reshape(2, 8, 8)
    a, b = old._values(values), model._values(values)
    assert torch.equal(a, b)
    targets = torch.arange(64) % len(codec['target_vocabulary'])
    old_loss = torch.nn.functional.cross_entropy(a.reshape(-1, a.shape[-1]), targets)
    new_loss = torch.nn.functional.cross_entropy(b.reshape(-1, b.shape[-1]), targets)
    assert torch.equal(old_loss, new_loss)
    old_loss.backward(); new_loss.backward()
    for name in ('weight', 'bias'):
        shared = getattr(model.non_action_head.source_projection, name).grad
        private = getattr(model.non_action_head.object_projection, name).grad
        original = getattr(old.non_action_head.source_projection, name).grad
        assert torch.allclose(shared + private, original, atol=1e-7, rtol=2e-6)
        assert torch.equal(getattr(model.non_action_head.field_readout, name).grad,
                           getattr(old.non_action_head.field_readout, name).grad)


def test_private_projection_changes_only_object_readouts_not_recurrent_features():
    model, old, _, packet = bound()
    values = model.project(inputs(8, 1))
    before = model.source_value_logits(values, source_context=packet)
    recurrence = model.source_recurrent_features(values, source_context=packet)
    with torch.no_grad(): model.non_action_head.object_projection.weight.add_(.2)
    after = model.source_value_logits(values, source_context=packet)
    assert torch.equal(before[:, :, :3], after[:, :, :3])
    assert not torch.equal(before[:, :, 3], after[:, :, 3])
    assert torch.equal(recurrence, model.source_recurrent_features(values, source_context=packet))
    assert torch.equal(old.source_action_features(values, source_context=packet), model.source_action_features(values, source_context=packet))


@pytest.mark.parametrize('dimension', [384, 768])
def test_other_widths_are_explicitly_rejected(dimension):
    old, _, codec, _ = fixture(dimension=dimension)
    with pytest.raises(ValueError, match='actual8D'):
        subject.bind_isolated_object_model(old, codec=codec)


def test_old_validator_stays_strict_and_new_spec_has_no_authority():
    model, _, codec, _ = bound()
    with pytest.raises(ValueError, match='explicit ordered'):
        ordered.checked_specification(model, codec)
    spec = subject.checked_specification(model, codec)
    assert spec['source_value_parameter_count'] == spec['inherited_ordered_architecture']['source_value_parameter_count'] + 576
    assert spec['existing_targets_changed'] is spec['historical_linguistic_teacher_modified'] is False
    assert all(spec[k] is False for k in subject.ordered.FALSE)


@pytest.mark.parametrize('kind', ['missing', 'extra', 'shape', 'dtype', 'nan', 'frozen', 'version'])
def test_invalid_restore_is_rejected_before_any_tensor_is_copied(kind):
    model, _, _, _ = bound()
    before = core.tensor_digest(model); state = deepcopy(model.state_dict())
    state['action_head.field_readout.bias'].add_(1)
    if kind == 'missing': state.pop(subject.EXTRA_NAMES[0])
    elif kind == 'extra': state['unregistered'] = torch.zeros(1)
    elif kind == 'shape': state[subject.EXTRA_NAMES[0]] = torch.zeros(1)
    elif kind == 'dtype': state[subject.EXTRA_NAMES[0]] = state[subject.EXTRA_NAMES[0]].double()
    elif kind == 'nan': state[subject.EXTRA_NAMES[0]][0, 0] = float('nan')
    elif kind == 'frozen': state['clause_source_mean'].add_(1)
    elif kind == 'version': state['ordered_clause_recurrent_version'].add_(1)
    with pytest.raises(ValueError): model.load_state_dict(state)
    assert core.tensor_digest(model) == before


@pytest.mark.parametrize('kwargs', [{'strict': False}, {'assign': True}])
def test_restore_rejects_non_strict_or_assigning_modes(kwargs):
    model, _, _, _ = bound()
    with pytest.raises(ValueError, match='strict nonassigning'):
        model.load_state_dict(model.state_dict(), **kwargs)


def test_roundtrip_state_restores_private_projection_and_all_other_weights():
    model, old, codec, _ = bound()
    with torch.no_grad(): model.non_action_head.object_projection.bias.add_(.07)
    clone = subject.bind_isolated_object_model(old, codec=codec)
    clone.load_state_dict(deepcopy(model.state_dict()))
    assert core.tensor_digest(clone) == core.tensor_digest(model)
    subject.checked_specification(clone, codec)


@pytest.mark.parametrize('alias', ['shared_weight', 'shared_bias', 'action_weight'])
def test_parameter_cross_aliases_are_rejected(alias):
    model, _, codec, _ = bound()
    if alias == 'shared_weight': model.non_action_head.object_projection.weight = model.non_action_head.source_projection.weight
    elif alias == 'shared_bias': model.non_action_head.object_projection.bias = model.non_action_head.source_projection.bias
    else: model.non_action_head.object_projection.weight = model.action_head.source_projection.weight
    with pytest.raises(ValueError, match='alias|unexpected'):
        subject.checked_specification(model, codec)


@pytest.mark.parametrize('field,value', [('object_projection_shares_storage', True), ('existing_targets_changed', True),
                                      ('source_value_parameter_count', 0), ('qualified', True), ('unexpected', False)])
def test_forged_specification_fails_closed(field, value):
    model, _, codec, _ = bound(); original = model.describe
    model.describe = lambda: {**original(), field: value}
    with pytest.raises(ValueError): subject.checked_specification(model, codec)


@pytest.mark.parametrize('zero', [False, True])
def test_inference_controls_match_inherited_control_before_private_learning(zero):
    model, old, codec, packet = bound()
    control = subject.bind_inference_control(model, codec=codec, zero_condition=zero)
    inherited = (ordered.bind_zero_condition_model if zero else ordered.bind_residual_off_model)(old)
    x = inputs(8, 1); prefix = torch.tensor([encode(codec)])
    assert all(torch.equal(a, b) for a, b in zip(control(x, prefix, source_context=packet), inherited(x, prefix, source_context=packet)))
    assert greedy(control, x, packet) == greedy(inherited, x, packet)
    before = core.tensor_digest(model)
    with torch.no_grad(): control.body.non_action_head.object_projection.bias.add_(1)
    assert core.tensor_digest(model) == before
