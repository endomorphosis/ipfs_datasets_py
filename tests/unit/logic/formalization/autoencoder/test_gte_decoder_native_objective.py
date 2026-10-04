"""Reference objectives on explicitly synthetic cached native-input fixtures."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[5]
PATH = ROOT / "ipfs_datasets_py/logic/formalization/autoencoder/gte_decoder_native_objective.py"


def read_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


subject = read_module("gte_native_reference_objective_subject", PATH)
native_fixture = read_module("gte_native_objective_fixture", Path(__file__).with_name("test_gte_decoder_native_batch.py"))
torch = pytest.importorskip("torch")


@pytest.fixture(scope="module", autouse=True)
def single_thread():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


@pytest.fixture(scope="module")
def fixture(tmp_path_factory):
    return native_fixture.decoder_native_fixture(tmp_path_factory)


def kwargs(fixture):
    return {"initialization": fixture.initialization, "batch": fixture.batch,
            "replay": fixture.replay, "expected_donor_pins": fixture.donor_pins}


def private_model(fixture):
    return subject._helper("gte_decoder_reuse").load_dual_decoder(fixture.initialization,
        expected_donor_pins=fixture.donor_pins)


def objective(fixture, model=None, **changes):
    return subject.compute_native_reference_objective(private_model(fixture) if model is None else model,
        fixture.plan, **kwargs(fixture), **changes)


@pytest.fixture(scope="module")
def probe(fixture):
    return subject.probe_native_reference_gradients(fixture.plan, **kwargs(fixture))


def inspect_probe(fixture, receipt):
    return subject.inspect_native_reference_probe(receipt, fixture.plan, **kwargs(fixture))


def test_import_is_dependency_free():
    code = """import importlib.util,sys
spec=importlib.util.spec_from_file_location('isolated_native_objective',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
assert not any(name in sys.modules for name in ('torch','numpy','transformers','ipfs_datasets_py'))
"""
    subprocess.run([sys.executable, "-I", "-c", code, str(PATH)], check=True)


def test_unavailable_and_partial_plans_fail_before_torch(fixture, tmp_path):
    partial = native_fixture.prepare(fixture, receipts_768=fixture.receipts_768[:1])
    path = tmp_path / "unready.json"
    path.write_text(json.dumps({"plans": [fixture.empty_plan, partial], **kwargs(fixture)}))
    code = """import builtins,importlib.util,json,sys
spec=importlib.util.spec_from_file_location('isolated_native_unready',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
payload=json.load(open(sys.argv[2]));plans=payload.pop('plans');original=builtins.__import__
def admitted_import(name,*args,**kwargs):
    assert name.split('.')[0] not in ('torch','numpy','transformers'), name
    return original(name,*args,**kwargs)
builtins.__import__=admitted_import
for plan in plans:
    for operation in (lambda:module.compute_native_reference_objective(None,plan,**payload),
                      lambda:module.probe_native_reference_gradients(plan,**payload)):
        try:operation()
        except ValueError as error:assert 'complete ready' in str(error)
        else:raise AssertionError('unready numerical plan admitted')
assert 'torch' not in sys.modules
"""
    subprocess.run([sys.executable, "-I", "-c", code, str(PATH), str(path)], check=True)


def test_saved_probe_inspection_is_dependency_free(fixture, probe, tmp_path):
    path = tmp_path / "probe.json"
    path.write_text(json.dumps({"receipt": probe, "plan": fixture.plan, **kwargs(fixture)}))
    code = """import builtins,importlib.util,json,sys
spec=importlib.util.spec_from_file_location('isolated_native_inspect',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
payload=json.load(open(sys.argv[2]));original=builtins.__import__
def admitted_import(name,*args,**kwargs):
    assert name.split('.')[0] not in ('torch','numpy','transformers'), name
    return original(name,*args,**kwargs)
builtins.__import__=admitted_import
report=module.inspect_native_reference_probe(**payload)
assert report['interface_tensor_count']==4 and report['execution_authenticated'] is False
assert not any(name in sys.modules for name in ('torch','numpy','transformers','ipfs_datasets_py'))
"""
    subprocess.run([sys.executable, "-I", "-c", code, str(PATH), str(path)], check=True)


def manual_head(model, plan, name):
    """Independent reference CE arithmetic with each archived vocabulary."""
    losses = []
    tokens = 0
    for row in plan["heads"][name]["rows"]:
        vector = torch.tensor([row["native_receipt"]["embedding"]], dtype=torch.float32)
        prefix = torch.tensor([row["prefix_ids"]], dtype=torch.int64)
        adapted = (model.primary.input_adapter(vector) - model.primary.input_mean) / model.primary.input_scale
        projected = adapted + model.primary.projection_up(torch.tanh(model.primary.projection_down(adapted)))
        shared = torch.tanh(model.primary.condition(projected))
        if name == "primary384":
            head, condition = model.primary, shared
        else:
            head = model.legacy8
            raw8 = model.auxiliary_connector(shared)
            projected8 = raw8 + head.projection_up(torch.tanh(head.projection_down(raw8)))
            condition = torch.tanh(head.condition(projected8))
        outputs, _ = head.decoder(head.target_embedding(prefix), condition.unsqueeze(0))
        logits = head.output(outputs)[0]
        mask = torch.tensor(row["reference_token_mask"], dtype=torch.bool)
        labels = torch.tensor(row["next_token_ids"], dtype=torch.int64)
        losses.append(-torch.log_softmax(logits[mask], dim=-1).gather(1, labels[mask, None]).sum())
        tokens += int(mask.sum())
    return sum(losses) / tokens, tokens


def test_ce_matches_archived_transform_and_each_independent_reference_codec(fixture):
    model = private_model(fixture)
    result = objective(fixture, model, head_weights={"primary384": .25, "legacy8": 1.5})
    expected = []
    for name in subject.HEADS:
        loss, tokens = manual_head(model, fixture.plan, name)
        assert torch.allclose(result["heads"][name]["loss"], loss, atol=3e-7, rtol=1e-7)
        assert result["heads"][name]["reference_token_count"] == tokens
        assert result["heads"][name]["excluded_token_count"] == 0
        assert result["heads"][name]["row_count"] == fixture.plan["heads"][name]["ready_row_count"]
        assert result["heads"][name]["codec_sha256"] == fixture.plan["heads"][name]["codec_sha256"]
        expected.append(loss * result["heads"][name]["head_weight"])
    assert result["heads"]["primary384"]["reference_token_count"] != result["heads"]["legacy8"]["reference_token_count"]
    assert fixture.plan["heads"]["primary384"]["target_vocabulary"] != fixture.plan["heads"]["legacy8"]["target_vocabulary"]
    assert torch.allclose(result["loss"], sum(expected), atol=1e-6, rtol=1e-7)
    assert result["loss"].requires_grad
    assert result["head_normalization"] == "eligible_reference_tokens_within_each_head"
    assert result["logits_combined"] is False
    assert all(result[key] is value for key, value in subject.FLAGS.items())
    assert result["optimizer_steps"] == 0
    assert all(parameter.grad is None for parameter in model.parameters())


def test_each_head_exercises_its_native_interface_and_reference_prefix(fixture):
    model = private_model(fixture)
    original = model.forward
    calls = []
    def record(vectors, primary, auxiliary):
        calls.append((vectors.detach().tolist(), primary.tolist(), auxiliary.tolist()))
        return original(vectors, primary, auxiliary)
    model.forward = record
    objective(fixture, model)
    expected = []
    for name in subject.HEADS:
        for row in fixture.plan["heads"][name]["rows"]:
            expected.append(([row["native_receipt"]["embedding"]],
                [row["prefix_ids"]] if name == "primary384" else [[1]],
                [[1]] if name == "primary384" else [row["prefix_ids"]]))
    assert calls == expected
    assert all(len(vectors[0]) == 768 for vectors, _, _ in calls)


@pytest.mark.parametrize("head", subject.HEADS)
def test_each_separate_ce_reaches_shared_primary_adapter(fixture, head):
    model = private_model(fixture)
    result = objective(fixture, model, head_weights={name: float(name == head) for name in subject.HEADS})
    result["heads"][head]["loss"].backward()
    for name, parameter in model.named_parameters():
        if name.startswith("primary.input_adapter.") or (head == "legacy8" and name.startswith("auxiliary_connector.")):
            assert parameter.grad is not None and bool(torch.isfinite(parameter.grad).all())
            assert bool(torch.count_nonzero(parameter.grad))
        else:
            assert parameter.grad is None


def test_objective_preserves_modes_rng_threads_state_and_existing_gradients(fixture):
    model = private_model(fixture)
    parameters = dict(model.named_parameters())
    parameters[subject.INTERFACES[0]].grad = torch.ones_like(parameters[subject.INTERFACES[0]])
    existing = parameters[subject.INTERFACES[0]].grad
    state = subject._state_digest(model)
    modes = [module.training for module in model.modules()]
    rng = torch.random.get_rng_state().clone()
    original_threads = torch.get_num_threads()
    try:
        torch.set_num_threads(2)
        result = objective(fixture, model)
        assert torch.get_num_threads() == 2
        assert torch.equal(torch.random.get_rng_state(), rng)
        assert [module.training for module in model.modules()] == modes
        assert subject._state_digest(model) == state
        assert parameters[subject.INTERFACES[0]].grad is existing
        assert bool((existing == 1).all())
        assert all(parameter.grad is None for name, parameter in parameters.items() if name != subject.INTERFACES[0])
        assert result["loss"].requires_grad
    finally:
        torch.set_num_threads(original_threads)


def test_failure_restores_caller_rng_threads_and_modes(fixture):
    model = private_model(fixture)
    state = subject._state_digest(model)
    modes = [module.training for module in model.modules()]
    rng = torch.random.get_rng_state().clone()
    def failed_forward(*args):
        torch.rand(3)
        raise RuntimeError("deliberate forward failure")
    model.forward = failed_forward
    previous = torch.get_num_threads()
    try:
        torch.set_num_threads(2)
        with pytest.raises(RuntimeError, match="deliberate forward failure"):
            objective(fixture, model)
        assert torch.get_num_threads() == 2
        assert torch.equal(torch.random.get_rng_state(), rng)
        assert [module.training for module in model.modules()] == modes
        assert subject._state_digest(model) == state
        assert all(parameter.grad is None for parameter in model.parameters())
    finally:
        torch.set_num_threads(previous)


def test_fitted_interfaces_are_allowed_without_changing_inherited_bodies(fixture):
    model = private_model(fixture)
    with torch.no_grad():
        model.primary.input_adapter.bias.add_(.02)
        model.auxiliary_connector.bias.add_(.01)
    result = objective(fixture, model)
    result["loss"].backward()
    assert all(parameter.grad is not None for name, parameter in model.named_parameters() if name in subject.INTERFACES)


def test_probe_is_private_and_has_nonzero_finite_gradients_without_updates(fixture, probe):
    report = inspect_probe(fixture, probe)
    assert report["status"] == "consistent_unqualified"
    assert report["execution_authenticated"] is False
    assert probe["inherited_tensor_count"] == 26
    assert probe["inherited_gradients_absent"] is True
    assert probe["all_26_inherited_tensors_unchanged"] is True
    assert probe["whole_model_state_unchanged"] is True
    assert probe["original_decoder_initialization_unchanged"] is True
    assert probe["model_state_sha256_before"] == probe["model_state_sha256_after"] == subject.digest(subject._expected_state(fixture.initialization))
    assert set(probe["interface_gradients"]) == set(subject.INTERFACES)
    for gradient in probe["interface_gradients"].values():
        assert gradient["finite"] is gradient["nonzero"] is True
        assert 0 < gradient["max_abs"] <= gradient["l2_norm"]
    assert all(probe[key] is value for key, value in subject.FLAGS.items())
    assert type(probe["optimizer_steps"]) is int and probe["optimizer_steps"] == 0
    assert "model_state" not in probe and "optimizer_state" not in probe


def test_private_probe_preserves_caller_assets_rng_threads_and_no_optimizer(fixture, monkeypatch):
    captured = []
    helper = subject._helper
    def dependencies(name):
        module = helper(name)
        if name == "gte_decoder_reuse":
            original = module.load_dual_decoder
            def capture(*args, **kwargs):
                model = original(*args, **kwargs)
                captured.append(model)
                return model
            module.load_dual_decoder = capture
        return module
    monkeypatch.setattr(subject, "_helper", dependencies)
    def forbidden(*args, **kwargs):
        raise AssertionError("optimizer creation is forbidden in reference probe")
    monkeypatch.setattr(torch.optim, "Adam", forbidden)
    monkeypatch.setattr(torch.optim, "AdamW", forbidden)
    monkeypatch.setattr(torch.optim, "SGD", forbidden)
    payload_digest = subject.digest([fixture.initialization, fixture.plan, fixture.batch, fixture.replay])
    rng = torch.random.get_rng_state().clone()
    previous = torch.get_num_threads()
    try:
        torch.set_num_threads(2)
        receipt = subject.probe_native_reference_gradients(fixture.plan, **kwargs(fixture))
        assert torch.get_num_threads() == 2
        assert torch.equal(rng, torch.random.get_rng_state())
    finally:
        torch.set_num_threads(previous)
    assert len(captured) == 1
    assert subject.digest([fixture.initialization, fixture.plan, fixture.batch, fixture.replay]) == payload_digest
    assert subject._state_digest(captured[0]) == receipt["model_state_sha256_after"]
    assert all(parameter.grad is None for name, parameter in captured[0].named_parameters() if name not in subject.INTERFACES)
    assert len({parameter.untyped_storage().data_ptr() for parameter in captured[0].parameters()}) == 30


@pytest.mark.parametrize("weights", [False, {}, {"primary384": 1.},
    {"primary384": True, "legacy8": 1.}, {"primary384": float("nan"), "legacy8": 1.},
    {"primary384": float("inf"), "legacy8": 1.}, {"primary384": -1., "legacy8": 1.},
    {"primary384": 101., "legacy8": 1.}, {"primary384": 10**1000, "legacy8": 1.},
    {"primary384": 0., "legacy8": 0.}])
def test_invalid_head_weights_rejected_without_model(fixture, weights):
    with pytest.raises(ValueError):
        subject.compute_native_reference_objective(None, fixture.plan, **kwargs(fixture), head_weights=weights)


def test_probe_requires_both_positive_head_weights(fixture):
    with pytest.raises(ValueError, match="both head weights"):
        subject.probe_native_reference_gradients(fixture.plan, **kwargs(fixture),
            head_weights={"primary384": 1., "legacy8": 0.})


@pytest.mark.parametrize("mutation", ["inherited_weight", "inherited_trainable", "interface_frozen",
    "float64", "mean", "scale", "max_tokens", "training_mode", "parameter_alias"])
def test_model_identity_and_freeze_admission_rejects_drift(fixture, mutation):
    model = private_model(fixture)
    with torch.no_grad():
        if mutation == "inherited_weight":
            model.primary.output.bias[0].add_(.01)
        elif mutation == "inherited_trainable":
            model.primary.output.bias.requires_grad_(True)
        elif mutation == "interface_frozen":
            model.auxiliary_connector.bias.requires_grad_(False)
        elif mutation == "float64":
            model.primary.input_adapter.to(torch.float64)
        elif mutation == "mean":
            model.primary.input_mean[0].add_(.01)
        elif mutation == "scale":
            model.primary.input_scale *= 2
        elif mutation == "max_tokens":
            model.primary.max_target_tokens += 1
        elif mutation == "training_mode":
            model.train()
        else:
            model.primary.condition.bias = model.primary.output.bias
    with pytest.raises(ValueError):
        objective(fixture, model)


def test_no_grad_context_rejected(fixture):
    model = private_model(fixture)
    with torch.no_grad(), pytest.raises(ValueError, match="gradient-enabled"):
        objective(fixture, model)


@pytest.mark.parametrize("mutation", ["training", "kd", "proof", "optimizer_bool", "inherited_bool",
    "zero_gradient", "nonfinite_gradient", "wrong_shape", "wrong_count", "loss", "head_codec", "state", "extra"])
def test_saved_probe_diagnostics_and_scope_reject_tampering(fixture, probe, mutation):
    receipt = deepcopy(probe)
    gradient = receipt["interface_gradients"][subject.INTERFACES[0]]
    if mutation == "training":
        receipt["training_executed"] = True
    elif mutation == "kd":
        receipt["production_kd_enabled"] = True
    elif mutation == "proof":
        receipt["proof_authority"] = True
    elif mutation == "optimizer_bool":
        receipt["optimizer_steps"] = False
    elif mutation == "inherited_bool":
        receipt["inherited_tensor_count"] = True
    elif mutation == "zero_gradient":
        gradient["max_abs"] = 0.
    elif mutation == "nonfinite_gradient":
        gradient["l2_norm"] = float("inf")
    elif mutation == "wrong_shape":
        gradient["shape"][0] += 1
    elif mutation == "wrong_count":
        receipt["heads"]["legacy8"]["reference_token_count"] += 1
    elif mutation == "loss":
        receipt["loss"] += 1.
    elif mutation == "head_codec":
        receipt["heads"]["legacy8"]["codec_sha256"] = receipt["heads"]["primary384"]["codec_sha256"]
    elif mutation == "state":
        receipt["model_state_sha256_after"] = "a" * 64
    else:
        receipt["extra"] = None
    with pytest.raises(ValueError):
        inspect_probe(fixture, receipt)


def test_native_receipt_and_prefix_bindings_are_admitted_before_model(fixture):
    plan = deepcopy(fixture.plan)
    plan["heads"]["primary384"]["rows"][0]["native_receipt"]["embedding"] = [0.] * 384
    with pytest.raises(ValueError):
        subject.compute_native_reference_objective(None, plan, **kwargs(fixture))
    plan = deepcopy(fixture.plan)
    plan["heads"]["legacy8"]["rows"][0]["prefix_ids"][0] = True
    with pytest.raises(ValueError):
        subject.compute_native_reference_objective(None, plan, **kwargs(fixture))
