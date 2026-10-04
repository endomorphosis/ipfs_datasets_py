"""Versioned trained-interface admission; all native receipts are test fixtures."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[5]
PATH = ROOT / "ipfs_datasets_py/logic/formalization/autoencoder/gte_decoder_interface_checkpoint.py"


def read_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


subject = read_module("gte_interface_checkpoint_test_subject", PATH)


def trained_interface_fixture(tmp_path_factory):
    native = read_module("gte_interface_native_fixture", Path(__file__).with_name("test_gte_decoder_native_batch.py"))
    fixture = native.decoder_native_fixture(tmp_path_factory)
    trainer = subject._helper("gte_decoder_interface_training")
    result = trainer.train_decoder_interfaces(fixture.plan, initialization=fixture.initialization,
        batch=fixture.batch, replay=fixture.replay, expected_donor_pins=fixture.donor_pins, steps=1)
    fixture.checkpoint, fixture.training_report = result["checkpoint"], result["report"]
    return fixture


@pytest.fixture(scope="module")
def fixture(tmp_path_factory):
    return trained_interface_fixture(tmp_path_factory)


def kwargs(fixture):
    return {"initialization": fixture.initialization, "plan": fixture.plan, "batch": fixture.batch,
            "replay": fixture.replay, "expected_donor_pins": fixture.donor_pins}


def inspect(fixture, checkpoint=None):
    return subject.inspect_interface_checkpoint(checkpoint if checkpoint is not None else fixture.checkpoint,
                                                **kwargs(fixture))


def make(fixture, interfaces=None, report=None):
    return subject.create_interface_checkpoint(fixture.initialization, fixture.plan,
        expected_donor_pins=fixture.donor_pins,
        interfaces=interfaces if interfaces is not None else fixture.checkpoint["interfaces"],
        training_report=report if report is not None else fixture.training_report)


def resign_outer(checkpoint):
    checkpoint["training_report_sha256"] = subject.digest(checkpoint["training_report"])
    checkpoint["interface_state_sha256"] = subject.digest(checkpoint["interfaces"])
    checkpoint["representation_id"] = subject._identity(checkpoint)


def test_actual_optimizer_generation_has_distinct_identity_and_only_four_weights(fixture):
    checkpoint = fixture.checkpoint
    receipt = inspect(fixture)
    assert receipt["status"] == "consistent_trained_unqualified"
    assert receipt["optimizer_steps"] == 1
    assert checkpoint["representation_id"] != fixture.initialization["representation_id"]
    assert checkpoint["representation_id"].startswith("gte-768-dual-reference-interfaces:sha256:")
    assert set(checkpoint["interfaces"]) == set(subject.INTERFACES)
    assert checkpoint["initialization_content_sha256"] == subject.digest(fixture.initialization)
    assert checkpoint["primary_start"] == "original_initialization"
    assert checkpoint["training_report"] == fixture.training_report
    assert make(fixture) == checkpoint
    assert checkpoint["optimizer"] == {"mode": "fresh", "state": None, "resume": False, "donor_moments_imported": False}
    assert receipt["training_execution_authenticated"] is False
    assert checkpoint["training_executed"] is True and checkpoint["distillation_executed"] is False
    assert checkpoint["encoder_inference_executed"] is False and checkpoint["teacher_qualified"] is False


def test_full_inventory_keeps_twenty_six_exact_frozen_decoder_tensors(fixture):
    inventory = fixture.checkpoint["tensor_inventory"]
    initial = subject._state(fixture.initialization)
    assert len(inventory) == 30
    inherited = [row for row in inventory if not row["requires_grad"]]
    assert len(inherited) == 26
    for row in inherited:
        assert row["sha256"] == subject.digest(initial[row["name"]])
        assert row["origin"].startswith("unchanged_copied_")
    trained = [row for row in inventory if row["requires_grad"]]
    assert {row["name"] for row in trained} == set(subject.INTERFACES)
    for row in trained:
        assert row["sha256"] != subject.digest(initial[row["name"]])
        assert row["origin"] == "reference_optimizer_trained_interface"
    assert fixture.checkpoint["inherited_state_sha256"] == subject.digest(
        {name: value for name, value in initial.items() if name not in subject.INTERFACES})


def test_report_preserves_separate_reference_counts_and_actual_reload_outputs(fixture):
    report = fixture.training_report
    assert report["before"]["heads"]["primary384"]["reference_token_count"] == 16 * 39
    assert report["before"]["heads"]["legacy8"]["reference_token_count"] == 2 * 15
    assert len(report["history"]) == 1
    assert report["optimizer"]["parameters"] == list(subject.INTERFACES)
    assert report["optimizer"]["donor_state_imported"] is False
    assert report["all_selected_reference_outputs_preserved_on_reload"] is True
    for name in subject.HEADS:
        outputs = report["trained_reference_outputs"][name]
        assert len(outputs) == fixture.plan["heads"][name]["ready_row_count"]
        assert [row["id"] for row in outputs] == [row["id"] for row in fixture.plan["heads"][name]["rows"]]
    assert report["trained_reference_outputs_sha256"] == subject.digest(report["trained_reference_outputs"])


def test_two_private_reloads_are_equal_disjoint_and_keep_initialization_immutable(fixture):
    torch = pytest.importorskip("torch")
    original = deepcopy((fixture.initialization, fixture.plan, fixture.batch, fixture.replay, fixture.checkpoint))
    rng = torch.random.get_rng_state().clone()
    threads = torch.get_num_threads()
    first = subject.load_interface_checkpoint(fixture.checkpoint, **kwargs(fixture))
    second = subject.load_interface_checkpoint(fixture.checkpoint, **kwargs(fixture))
    assert torch.equal(rng, torch.random.get_rng_state()) and torch.get_num_threads() == threads
    initial = subject._state(fixture.initialization)
    for (name, left), (_, right) in zip(first.named_parameters(), second.named_parameters()):
        assert torch.equal(left, right)
        assert left.untyped_storage().data_ptr() != right.untyped_storage().data_ptr()
        assert left.requires_grad is (name in subject.INTERFACES)
        assert left.grad is None and right.grad is None
        if name not in subject.INTERFACES:
            assert left.tolist() == initial[name]
    with torch.no_grad():
        for name in subject.HEADS:
            for row in fixture.plan["heads"][name]["rows"]:
                vectors = torch.tensor([row["native_receipt"]["embedding"]], dtype=torch.float32)
                prefix = torch.tensor([row["prefix_ids"]], dtype=torch.int64)
                bos = torch.tensor([[1]], dtype=torch.int64)
                args = (vectors, prefix, bos) if name == "primary384" else (vectors, bos, prefix)
                left, right = first(*args), second(*args)
                for key in ("primary_logits", "auxiliary_logits", "shared_condition", "auxiliary_latent"):
                    assert torch.equal(left[key], right[key])
    assert original == (fixture.initialization, fixture.plan, fixture.batch, fixture.replay, fixture.checkpoint)


@pytest.mark.parametrize("mutation", ["integer", "boolean", "wider_than_float32", "overflow", "nan", "wrong_width",
    "missing_tensor", "extra_inherited_tensor", "one_unchanged", "all_unchanged"])
def test_strict_interface_tensor_admission_before_any_loading(fixture, mutation):
    interfaces = deepcopy(fixture.checkpoint["interfaces"])
    report = deepcopy(fixture.training_report)
    name = "primary.input_adapter.weight"
    if mutation == "integer": interfaces[name][0][0] = 0
    elif mutation == "boolean": interfaces[name][0][0] = True
    elif mutation == "wider_than_float32": interfaces[name][0][0] = .1
    elif mutation == "overflow": interfaces[name][0][0] = 1e100
    elif mutation == "nan": interfaces[name][0][0] = float("nan")
    elif mutation == "wrong_width": interfaces[name][0].pop()
    elif mutation == "missing_tensor": interfaces.pop("auxiliary_connector.bias")
    elif mutation == "extra_inherited_tensor": interfaces["primary.condition.weight"] = [[0.]]
    elif mutation in ("one_unchanged", "all_unchanged"):
        original = subject._state(fixture.initialization)
        names = [name] if mutation == "one_unchanged" else subject.INTERFACES
        for key in names:
            interfaces[key] = deepcopy(original[key])
        report["interface_state_sha256_after"] = subject.digest(interfaces)
        report["model_state_sha256_after"] = subject.digest(subject._state(fixture.initialization, interfaces))
    with pytest.raises(ValueError):
        make(fixture, interfaces=interfaces, report=report)


@pytest.mark.parametrize("mutation", ["schema", "identity", "dimension_bool", "initialization_digest", "plan_digest",
    "batch_digest", "replay_digest", "donor_pin", "codec_pin", "asset_pin", "profile", "primary_start", "interface_digest",
    "inherited_digest", "fullstate_digest", "inventory_origin", "inventory_trainable", "optimizer_state", "optimizer_resume",
    "training_flag", "kd_flag", "encoder_flag", "quality_flag", "reload_flag", "steps_bool", "extra_field"])
def test_outer_generation_rejects_retaging_state_and_authority_tampering(fixture, mutation):
    checkpoint = deepcopy(fixture.checkpoint)
    if mutation == "schema": checkpoint["schema"] = "old-initialization/v1"
    elif mutation == "identity": checkpoint["representation_id"] = fixture.initialization["representation_id"]
    elif mutation == "dimension_bool": checkpoint["dimension"] = True
    elif mutation == "initialization_digest": checkpoint["initialization_content_sha256"] = "c" * 64
    elif mutation == "plan_digest": checkpoint["plan_sha256"] = "c" * 64
    elif mutation == "batch_digest": checkpoint["batch_sha256"] = "c" * 64
    elif mutation == "replay_digest": checkpoint["replay_sha256"] = "c" * 64
    elif mutation == "donor_pin": checkpoint["donor_pins"]["teacher384_weights_sha256"] = "c" * 64
    elif mutation == "codec_pin": checkpoint["codec_sha256"]["legacy8"] = "c" * 64
    elif mutation == "asset_pin": checkpoint["asset_manifest_sha256"] = "c" * 64
    elif mutation == "profile": checkpoint["profile_id"] = "random-native768"
    elif mutation == "primary_start": checkpoint["primary_start"] = "affine_aligned"
    elif mutation == "interface_digest": checkpoint["interface_state_sha256"] = "c" * 64
    elif mutation == "inherited_digest": checkpoint["inherited_state_sha256"] = "c" * 64
    elif mutation == "fullstate_digest": checkpoint["model_state_sha256"] = "c" * 64
    elif mutation == "inventory_origin": checkpoint["tensor_inventory"][0]["origin"] = "learned_decoder_retrained"
    elif mutation == "inventory_trainable": checkpoint["tensor_inventory"][-1]["requires_grad"] = True
    elif mutation == "optimizer_state": checkpoint["optimizer"]["state"] = {"moments": "donor"}
    elif mutation == "optimizer_resume": checkpoint["optimizer"]["resume"] = True
    elif mutation == "training_flag": checkpoint["training_executed"] = False
    elif mutation == "kd_flag": checkpoint["production_kd_enabled"] = True
    elif mutation == "encoder_flag": checkpoint["encoder_inference_executed"] = True
    elif mutation == "quality_flag": checkpoint["teacher_qualified"] = True
    elif mutation == "reload_flag": checkpoint["exact_trained_reload_passed"] = False
    elif mutation == "steps_bool": checkpoint["optimizer_steps"] = True
    elif mutation == "extra_field": checkpoint["new_unknown_training_mode"] = False
    if mutation != "identity":
        checkpoint["representation_id"] = subject._identity(checkpoint)
    with pytest.raises(ValueError):
        inspect(fixture, checkpoint)


@pytest.mark.parametrize("mutation", ["step_zero", "step_overflow", "step_bool", "wrong_start", "optimizer_name", "fresh_bool",
    "learning_rate", "betas", "eps", "decay", "frozen_parameter", "resume", "head_weight", "head_count", "head_codec",
    "head_loss_bool", "combined_loss", "history_length", "history_step", "history_before", "clip_bound", "gradient_bool",
    "gradient_shape", "gradient_zero", "gradient_norm", "before_tensor_digest", "after_tensor_digest", "inherited_count",
    "output_id", "output_source", "output_prefix", "output_native", "output_digest", "output_hash_uppercase", "output_count",
    "implementation", "dtype", "training_bool", "kd_flag", "reload_flag", "extra_field"])
def test_closed_actual_training_report_cannot_be_rebound_by_resigning_outer_checkpoint(fixture, mutation):
    report = deepcopy(fixture.training_report)
    step, head = report["history"][0], report["after"]["heads"]["primary384"]
    if mutation == "step_zero": report["steps"] = report["optimizer_steps"] = 0
    elif mutation == "step_overflow": report["steps"] = report["optimizer_steps"] = 65
    elif mutation == "step_bool": report["steps"] = True
    elif mutation == "wrong_start": report["primary_start"] = "random_decoder"
    elif mutation == "optimizer_name": report["optimizer"]["name"] = "imported-donor-Adam"
    elif mutation == "fresh_bool": report["optimizer"]["fresh"] = 1
    elif mutation == "learning_rate": report["optimizer"]["learning_rate"] = .1
    elif mutation == "betas": report["optimizer"]["betas"][1] = .99
    elif mutation == "eps": report["optimizer"]["eps"] = 0.
    elif mutation == "decay": report["optimizer"]["weight_decay"] = .01
    elif mutation == "frozen_parameter": report["optimizer"]["parameters"].append("primary.condition.weight")
    elif mutation == "resume": report["optimizer"]["resume"] = True
    elif mutation == "head_weight": report["head_weights"]["legacy8"] = 0.
    elif mutation == "head_count": head["reference_token_count"] = 625
    elif mutation == "head_codec": head["codec_sha256"] = "c" * 64
    elif mutation == "head_loss_bool": head["loss"] = True
    elif mutation == "combined_loss": report["after"]["loss"] += 1.
    elif mutation == "history_length": report["history"] = []
    elif mutation == "history_step": step["step"] = True
    elif mutation == "history_before": step["head_losses_before"]["primary384"] += 1.
    elif mutation == "clip_bound": step["gradient_global_norm_after_clipping"] = report["max_grad_norm"] + 1.
    elif mutation == "gradient_bool": step["interface_gradients"][subject.INTERFACES[0]]["finite"] = 1
    elif mutation == "gradient_shape": step["interface_gradients"][subject.INTERFACES[0]]["shape"] = [True, 768]
    elif mutation == "gradient_zero": step["interface_gradients"][subject.INTERFACES[0]]["max_abs"] = 0.
    elif mutation == "gradient_norm": step["gradient_global_norm_before_clipping"] += 1.
    elif mutation == "before_tensor_digest": report["interface_state_sha256_before"] = "c" * 64
    elif mutation == "after_tensor_digest": report["model_state_sha256_after"] = "c" * 64
    elif mutation == "inherited_count": report["inherited_tensor_count"] = 25
    elif mutation.startswith("output_"):
        outputs = report["trained_reference_outputs"]["primary384"]
        if mutation == "output_id": outputs[0]["id"] = "unselected-native-source"
        elif mutation == "output_source": outputs[0]["source_sha256"] = "c" * 64
        elif mutation == "output_prefix": outputs[0]["reference_prefix_sha256"] = "c" * 64
        elif mutation == "output_native": outputs[0]["native_row_sha256"] = "c" * 64
        elif mutation == "output_digest": report["trained_reference_outputs_sha256"] = "c" * 64
        elif mutation == "output_hash_uppercase": outputs[0]["primary_logits_sha256"] = "A" * 64
        elif mutation == "output_count": outputs.pop()
        if mutation != "output_digest": report["trained_reference_outputs_sha256"] = subject.digest(report["trained_reference_outputs"])
    elif mutation == "implementation": report["implementation"]["gte_decoder_interface_training.py"] = "c" * 64
    elif mutation == "dtype": report["numerical_profile"]["dtype"] = "float64"
    elif mutation == "training_bool": report["training_executed"] = 1
    elif mutation == "kd_flag": report["production_kd_eligible"] = True
    elif mutation == "reload_flag": report["all_selected_reference_outputs_preserved_on_reload"] = False
    elif mutation == "extra_field": report["resumed_optimizer"] = False
    checkpoint = deepcopy(fixture.checkpoint)
    checkpoint["training_report"] = report
    resign_outer(checkpoint)
    with pytest.raises(ValueError):
        inspect(fixture, checkpoint)


def test_constructor_and_inspector_do_not_mutate_or_alias_saved_parent_inputs(fixture):
    old = deepcopy((fixture.initialization, fixture.plan, fixture.training_report, fixture.checkpoint))
    checkpoint = make(fixture)
    inspect(fixture, checkpoint)
    checkpoint["interfaces"][subject.INTERFACES[0]][0][0] += 1.
    checkpoint["training_report"]["before"]["loss"] += 1.
    assert old == (fixture.initialization, fixture.plan, fixture.training_report, fixture.checkpoint)


def test_partial_native_plan_cannot_create_or_admit_trained_generation(fixture):
    plan = deepcopy(fixture.empty_plan)
    with pytest.raises(ValueError):
        subject.create_interface_checkpoint(fixture.initialization, plan, expected_donor_pins=fixture.donor_pins,
            interfaces=fixture.checkpoint["interfaces"], training_report=fixture.training_report)
    with pytest.raises(ValueError):
        subject.inspect_interface_checkpoint(fixture.checkpoint, **{**kwargs(fixture), "plan": plan})


def test_invalid_tensor_checkpoint_is_rejected_before_torch_import(fixture, tmp_path):
    payload = {**kwargs(fixture), "checkpoint": fixture.checkpoint}
    path = tmp_path / "interface-input.json"
    path.write_text(json.dumps(payload))
    code = """import importlib.util,json,sys
spec=importlib.util.spec_from_file_location('isolated_checkpoint',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
payload=json.load(open(sys.argv[2]))
module.inspect_interface_checkpoint(**payload)
assert not any(name in sys.modules for name in ('torch','numpy','transformers','ipfs_datasets_py'))
payload['checkpoint']['interfaces']['primary.input_adapter.weight'][0][0]=0.1
try:module.load_interface_checkpoint(**payload)
except ValueError:pass
else:raise AssertionError('invalid serializedtensor accepted')
assert not any(name in sys.modules for name in ('torch','numpy','transformers','ipfs_datasets_py'))
"""
    subprocess.run([sys.executable, "-I", "-c", code, str(PATH), str(path)], check=True)


def test_exact_float32_payload_survives_json_save_and_pure_reload(fixture, tmp_path):
    path = tmp_path / "trained-interfaces.json"
    path.write_bytes(subject._raw(fixture.checkpoint) + b"\n")
    saved = json.loads(path.read_bytes())
    assert inspect(fixture, saved)["model_state_sha256"] == fixture.checkpoint["model_state_sha256"]
    value = saved["interfaces"][subject.INTERFACES[0]][0][0]
    assert value == struct.unpack("!f", struct.pack("!f", value))[0]
