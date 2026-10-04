"""Real bounded AdamW updates using explicitly synthetic native-input receipts."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[5]
PATH = ROOT / "ipfs_datasets_py/logic/formalization/autoencoder/gte_decoder_interface_training.py"


def read_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


subject = read_module("gte_interface_training_test_subject", PATH)
native_fixture = read_module("gte_interface_training_fixture", Path(__file__).with_name("test_gte_decoder_native_batch.py"))
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


def admission(fixture):
    return {"plan": fixture.plan, **kwargs(fixture)}


@pytest.fixture(scope="module")
def trained(fixture):
    """Capture real optimizer steps and the live post-update model for verification."""
    models, optimizers = [], []
    helper, adamw = subject._helper, torch.optim.AdamW
    def dependencies(name):
        module = helper(name)
        if name == "gte_decoder_reuse":
            original = module.load_dual_decoder
            def capture(*args, **kwargs):
                model = original(*args, **kwargs)
                models.append(model)
                return model
            module.load_dual_decoder = capture
        return module
    class RecordingAdamW(adamw):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.recorded_steps = 0
            assert not self.state
            optimizers.append(self)
        def step(self, *args, **kwargs):
            result = super().step(*args, **kwargs)
            self.recorded_steps += 1
            return result
    patch = pytest.MonkeyPatch()
    patch.setattr(subject, "_helper", dependencies)
    patch.setattr(torch.optim, "AdamW", RecordingAdamW)
    before = subject.digest([fixture.initialization, fixture.plan, fixture.batch, fixture.replay, fixture.donor_pins])
    rng = torch.random.get_rng_state().clone()
    previous = torch.get_num_threads()
    try:
        torch.set_num_threads(2)
        result = subject.train_decoder_interfaces(fixture.plan, **kwargs(fixture),
            steps=3, learning_rate=1e-2, max_grad_norm=1e-6)
        assert torch.get_num_threads() == 2
        assert torch.equal(torch.random.get_rng_state(), rng)
    finally:
        torch.set_num_threads(previous)
        patch.undo()
    assert before == subject.digest([fixture.initialization, fixture.plan, fixture.batch, fixture.replay, fixture.donor_pins])
    assert len(models) == len(optimizers) == 1
    return SimpleNamespace(**result, model=models[0], optimizer=optimizers[0])


def test_import_is_dependency_free():
    code = """import importlib.util,sys
spec=importlib.util.spec_from_file_location('isolated_training',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
assert not any(name in sys.modules for name in ('torch','numpy','transformers','ipfs_datasets_py'))
"""
    subprocess.run([sys.executable, "-I", "-c", code, str(PATH)], check=True)


def test_empty_and_partial_native_plans_fail_before_torch_or_optimizer(fixture, tmp_path):
    partial = native_fixture.prepare(fixture, receipts_768=fixture.receipts_768[:1])
    path = tmp_path / "unready.json"
    path.write_text(json.dumps({"plans": [fixture.empty_plan, partial], **kwargs(fixture)}))
    code = """import builtins,importlib.util,json,sys
spec=importlib.util.spec_from_file_location('isolated_unready_training',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
payload=json.load(open(sys.argv[2]));plans=payload.pop('plans');original=builtins.__import__
def admitted_import(name,*args,**kwargs):
    assert name.split('.')[0] not in ('torch','numpy','transformers'),name
    return original(name,*args,**kwargs)
builtins.__import__=admitted_import
for plan in plans:
    try:module.train_decoder_interfaces(plan,**payload)
    except ValueError as error:assert 'complete ready' in str(error)
    else:raise AssertionError('unready training admitted')
assert 'torch' not in sys.modules
"""
    subprocess.run([sys.executable, "-I", "-c", code, str(PATH), str(path)], check=True)


def test_real_optimizer_changes_only_four_interfaces_and_improves_fixture_ce(fixture, trained):
    report, optimizer = trained.report, trained.optimizer
    assert report["optimizer_steps"] == report["steps"] == optimizer.recorded_steps == 3
    assert report["training_executed"] is report["reference_supervised_training_executed"] is True
    assert report["primary_start"] == "original_initialization"
    assert report["after"]["loss"] < report["before"]["loss"]
    assert report["interface_state_sha256_before"] != report["interface_state_sha256_after"]
    assert report["model_state_sha256_before"] != report["model_state_sha256_after"]
    parameters = dict(trained.model.named_parameters())
    expected = subject._helper("gte_decoder_native_objective")._expected_state(fixture.initialization)
    assert len(optimizer.state) == 4
    assert {id(parameter) for parameter in optimizer.param_groups[0]["params"]} == {id(parameters[name]) for name in subject.INTERFACES}
    for name, parameter in parameters.items():
        initial = torch.tensor(expected[name], dtype=torch.float32)
        if name in subject.INTERFACES:
            assert parameter.requires_grad and parameter.grad is not None
            assert not torch.equal(parameter.detach(), initial)
            assert optimizer.state[parameter]["step"].item() == 3
        else:
            assert not parameter.requires_grad and parameter.grad is None
            assert torch.equal(parameter.detach(), initial)
    assert optimizer.param_groups[0]["weight_decay"] == 0.
    assert optimizer.param_groups[0]["betas"] == (.9, .999)
    assert optimizer.param_groups[0]["eps"] == 1e-8
    assert report["all_26_inherited_tensors_unchanged"] is report["inherited_gradients_absent"] is True


def test_step_history_records_real_reference_ce_gradients_and_clipping(trained):
    report = trained.report
    assert len(report["history"]) == 3
    assert report["history"][0]["loss_before"] == report["before"]["loss"]
    assert report["history"][-1]["loss_after"] == report["after"]["loss"]
    for index, row in enumerate(report["history"]):
        assert row["step"] == index + 1
        if index:
            assert row["loss_before"] == report["history"][index - 1]["loss_after"]
        assert row["gradient_global_norm_before_clipping"] > report["max_grad_norm"]
        assert 0 < row["gradient_global_norm_after_clipping"] <= report["max_grad_norm"] * (1 + 2e-6)
        for gradient in row["interface_gradients"].values():
            assert gradient["finite"] is gradient["nonzero"] is True
            assert gradient["l2_norm"] >= gradient["max_abs"] > 0
    for name in subject.HEADS:
        before, after = report["before"]["heads"][name], report["after"]["heads"][name]
        assert before["codec_sha256"] == after["codec_sha256"]
        assert before["reference_token_count"] == after["reference_token_count"] > 0
    assert report["before"]["heads"]["primary384"]["reference_token_count"] != report["before"]["heads"]["legacy8"]["reference_token_count"]


def test_report_matches_public_reference_objective_on_trained_model(fixture, trained):
    objective = subject._helper("gte_decoder_native_objective")
    result = objective.compute_native_reference_objective(trained.model, fixture.plan, **kwargs(fixture))
    assert float(result["loss"].detach()) == trained.report["after"]["loss"]
    for name in subject.HEADS:
        assert float(result["heads"][name]["loss"].detach()) == trained.report["after"]["heads"][name]["loss"]


def test_exact_saved_reload_matches_live_postoptimizer_outputs_and_private_storage(fixture, trained, tmp_path, monkeypatch):
    path = tmp_path / "trained.json"
    path.write_text(json.dumps(trained.checkpoint, sort_keys=True))
    saved = json.loads(path.read_text())
    contract = subject._helper("gte_decoder_interface_checkpoint")
    restored = contract.load_interface_checkpoint(saved, **admission(fixture))
    for name, tensor in trained.model.state_dict().items():
        assert torch.equal(tensor, restored.state_dict()[name])
    original_pointers = {parameter.untyped_storage().data_ptr() for parameter in trained.model.parameters()}
    restored_pointers = {parameter.untyped_storage().data_ptr() for parameter in restored.parameters()}
    assert len(original_pointers) == len(restored_pointers) == 30
    assert original_pointers.isdisjoint(restored_pointers)
    live = subject._reference_outputs(torch, trained.model, fixture.plan)
    assert live == trained.report["trained_reference_outputs"]
    assert subject._reference_outputs(torch, restored, fixture.plan) == live
    def forbidden(*args, **kwargs):
        raise AssertionError("saved trained reload verifier must not create an optimizer")
    monkeypatch.setattr(torch.optim, "AdamW", forbidden)
    rng = torch.random.get_rng_state().clone()
    before = subject.digest([saved, fixture.initialization, fixture.plan, fixture.batch, fixture.replay])
    verification = subject.verify_trained_interface_reload(saved, **admission(fixture))
    assert torch.equal(torch.random.get_rng_state(), rng)
    assert before == subject.digest([saved, fixture.initialization, fixture.plan, fixture.batch, fixture.replay])
    assert verification["trained_reference_outputs_sha256"] == subject.digest(live)
    assert verification["model_state_sha256"] == trained.report["model_state_sha256_after"]
    assert verification["optimizer_created"] is verification["training_executed"] is False
    assert verification["optimizer_steps"] == 0
    assert verification["private_storage_disjoint"] is verification["trained_reference_outputs_match"] is True
    assert saved["representation_id"] != fixture.initialization["representation_id"]
    assert saved["optimizer"] == {"mode": "fresh", "state": None, "resume": False, "donor_moments_imported": False}


def test_saved_verifier_rejects_forged_output_inventory_even_with_consistent_contract_hashes(fixture, trained):
    contract = subject._helper("gte_decoder_interface_checkpoint")
    report = deepcopy(trained.report)
    report["trained_reference_outputs"]["legacy8"][0]["auxiliary_logits_sha256"] = "a" * 64
    report["trained_reference_outputs_sha256"] = subject.digest(report["trained_reference_outputs"])
    forged = contract.create_interface_checkpoint(fixture.initialization, fixture.plan,
        expected_donor_pins=fixture.donor_pins, interfaces=trained.checkpoint["interfaces"], training_report=report)
    contract.inspect_interface_checkpoint(forged, **admission(fixture))
    with pytest.raises(ValueError, match="actual post-optimizer export"):
        subject.verify_trained_interface_reload(forged, **admission(fixture))


def test_trained_scope_preserves_unqualified_teacher_and_native_receipt_limitations(trained):
    for key, value in subject.FLAGS.items():
        assert trained.report[key] is value
    for key in ("distillation_executed", "encoder_inference_executed", "teacher_qualified",
                "production_kd_eligible", "source_fidelity_qualified", "proof_authority",
                "producer_execution_authenticated", "optimizer_resume_supported"):
        assert trained.checkpoint[key] is False
    assert "optimizer_state" not in trained.report and "optimizer_state" not in trained.checkpoint
    assert set(trained.checkpoint["interfaces"]) == set(subject.INTERFACES)


@pytest.mark.parametrize("controls", [{"steps": True}, {"steps": 0}, {"steps": 65},
    {"learning_rate": 1e-7}, {"learning_rate": float("nan")}, {"max_grad_norm": 0.},
    {"head_weights": {"primary384": 1., "legacy8": 0.}}])
def test_unsafe_or_incomplete_training_controls_reject_before_model(controls):
    with pytest.raises(ValueError):
        subject.train_decoder_interfaces(None, initialization=None, batch=None, replay=None,
            expected_donor_pins=None, **controls)


def test_failed_optimizer_step_restores_threads_rng_and_all_input_artifacts(fixture, monkeypatch):
    optimizer = torch.optim.AdamW
    class FailedAdamW(optimizer):
        def step(self, *args, **kwargs):
            torch.rand(4)
            raise RuntimeError("deliberate optimizer failure")
    monkeypatch.setattr(torch.optim, "AdamW", FailedAdamW)
    before = subject.digest([fixture.initialization, fixture.plan, fixture.batch, fixture.replay])
    rng = torch.random.get_rng_state().clone()
    previous = torch.get_num_threads()
    try:
        torch.set_num_threads(2)
        with pytest.raises(RuntimeError, match="deliberate optimizer failure"):
            subject.train_decoder_interfaces(fixture.plan, **kwargs(fixture), steps=1)
        assert torch.get_num_threads() == 2
        assert torch.equal(rng, torch.random.get_rng_state())
        assert before == subject.digest([fixture.initialization, fixture.plan, fixture.batch, fixture.replay])
    finally:
        torch.set_num_threads(previous)
