"""Synthetic policy tests; no corpus or qualification evidence."""
from copy import deepcopy
import pytest

torch = pytest.importorskip("torch")
from ipfs_datasets_py.logic.formalization.autoencoder import decoder_distillation_experiment as core
from ipfs_datasets_py.logic.formalization.autoencoder import source_value_freeze_experiment as subject
from ipfs_datasets_py.logic.formalization.autoencoder import long_span_source_value_training as training
from .test_long_span_source_value_training import prepared


@pytest.fixture(autouse=True)
def one_cpu():
    old = torch.get_num_threads(); torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


@pytest.mark.parametrize("kind", ["projected_source", "inherited_conditioning"])
def test_freeze_preserves_numeric_protocol_and_caller_state(kind):
    model, _, rows, _, options = prepared(kind)
    model.train(); model.body.eval()
    for index, parameter in enumerate(model.parameters()):
        if index % 2:
            parameter.grad = torch.full_like(parameter, .125)
    before = core.tensor_digest(model)
    modes = {name: module.training for name, module in model.named_modules()}
    inventory = {name:(parameter.requires_grad,None if parameter.grad is None else parameter.grad.clone())
        for name, parameter in model.named_parameters()}
    rng = torch.get_rng_state().clone()
    result = subject.bind_head_only_model(model); private = result['model']
    assert core.tensor_digest(private) == core.tensor_digest(model) == before
    assert torch.equal(rng, torch.get_rng_state())
    assert {name: module.training for name,module in model.named_modules()} == modes
    assert [name for name,parameter in private.named_parameters() if parameter.requires_grad] == list(subject.HEAD_NAMES)
    assert all(parameter.grad is None for parameter in private.parameters())
    for name,parameter in model.named_parameters():
        flag, gradient = inventory[name]
        assert parameter.requires_grad == flag
        assert parameter.grad is None if gradient is None else torch.equal(parameter.grad,gradient)
    data, labels = core._batch(torch, rows, options['input_transform'])
    with torch.inference_mode():
        old = core._logits(torch, model, data, labels[:,:-1], len(options['codec']['target_vocabulary']))
        new = core._logits(torch, private, data, labels[:,:-1], len(options['codec']['target_vocabulary']))
    assert all(torch.equal(a,b) for a,b in zip(old,new))
    assert subject.verify_frozen_body(private,result['report'])['verified']
    assert all(result['report'][key] is False for key in subject.FALSE)


@pytest.mark.parametrize("kind", ["projected_source", "inherited_conditioning"])
def test_reused_trainer_updates_only_head_and_keeps_real_generation_gate(kind):
    model, _, train, tune, options = prepared(kind)
    bound = subject.bind_head_only_model(model)
    result = training.train(bound['model'],train,tune,source_value_weight=.25,cardinality_weight=.25,
        count_exposure='balanced_all',**options)
    replay = deepcopy(bound['model'])
    for name in ('state_dict','last_complete_attempt_state_dict'):
        replay.load_state_dict(result[name],strict=True)
        assert subject.verify_frozen_body(replay,bound['report'])['verified']
    assert result['report']['selection'] == 'per_length_nonregression_then_fidelity_progress_then_reference_ce'
    assert result['report']['frozen_parameter_names'] == bound['report']['frozen_parameter_names']
    assert result['report']['frozen_parameters_verified']
    assert result['report']['source_value_presentations'] == 16
    assert result['report']['count_training_row_presentations'] == 3
    assert torch.count_nonzero(result['last_complete_attempt_state_dict']['source_value_head.weight']) > 0
    assert all(not parameter.requires_grad for parameter in bound['model'].body.parameters())


@pytest.mark.parametrize('change', ['body_weight','body_trainable','head_frozen','receipt','untracked_parameter'])
def test_frozen_policy_refuses_drift(change):
    model, _, _, _, _ = prepared()
    bound = subject.bind_head_only_model(model); private, receipt = bound['model'],bound['report']
    first = next(private.body.parameters())
    if change == 'body_weight':
        with torch.no_grad():first.add_(.01)
    elif change == 'body_trainable':first.requires_grad_(True)
    elif change == 'head_frozen':private.source_value_head.weight.requires_grad_(False)
    elif change == 'receipt':receipt['architecture_sha256']='0'*64
    else:private.register_parameter('extra',torch.nn.Parameter(torch.ones(1)))
    with pytest.raises(ValueError):subject.verify_frozen_body(private,receipt)


def test_guidance_off_is_not_this_controlled_experiment():
    model, _, _, _, _ = prepared(guidance=False)
    with pytest.raises(ValueError,match='unchanged guided'):subject.bind_head_only_model(model)
