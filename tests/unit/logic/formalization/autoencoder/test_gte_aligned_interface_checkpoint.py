"""Aligned-start generations using real updates on explicitly synthetic inputs."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[5]
PATH = ROOT / "ipfs_datasets_py/logic/formalization/autoencoder/gte_aligned_interface_checkpoint.py"


def read_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


subject = read_module("gte_aligned_interface_checkpoint_test_subject", PATH)


@pytest.fixture(scope="module")
def fixture(tmp_path_factory):
    numeric_tests = read_module("gte_aligned_checkpoint_numeric_fixture",
                               Path(__file__).with_name("test_gte_aligned_interface_training.py"))
    value = numeric_tests.aligned_training_fixture(tmp_path_factory)
    trainer = subject._helper("gte_aligned_interface_training")
    result = trainer.train_decoder_interfaces(value.plan, initialization=value.initialization,
        batch=value.batch, replay=value.replay, aligned_checkpoint=value.aligned_checkpoint,
        expected_alignment_file_pins=value.alignment_file_pins,
        expected_donor_pins=value.donor_pins, steps=1)
    value.checkpoint, value.training_report = result["checkpoint"], result["report"]
    return value


def kwargs(fixture):
    return {"initialization": fixture.initialization, "plan": fixture.plan, "batch": fixture.batch,
        "replay": fixture.replay, "aligned_checkpoint": fixture.aligned_checkpoint,
        "expected_alignment_file_pins": fixture.alignment_file_pins, "expected_donor_pins": fixture.donor_pins}


def inspect(fixture, checkpoint=None, **changes):
    return subject.inspect_interface_checkpoint(checkpoint if checkpoint is not None else fixture.checkpoint,
                                                **{**kwargs(fixture), **changes})


def make(fixture, interfaces=None, report=None, **changes):
    values = {"aligned_checkpoint": fixture.aligned_checkpoint,
        "expected_alignment_file_pins": fixture.alignment_file_pins, "expected_donor_pins": fixture.donor_pins,
        "interfaces": interfaces if interfaces is not None else fixture.checkpoint["interfaces"],
        "training_report": report if report is not None else fixture.training_report}
    return subject.create_interface_checkpoint(fixture.initialization, fixture.plan, **{**values, **changes})


def resign(checkpoint):
    checkpoint["training_report_sha256"] = subject.digest(checkpoint["training_report"])
    checkpoint["interface_state_sha256"] = subject.digest(checkpoint["interfaces"])
    checkpoint["representation_id"] = subject._identity(checkpoint)


def aligned_state(fixture):
    return subject._helper("gte_aligned_decoder")._state(fixture.initialization,
                                                        fixture.aligned_checkpoint["bridge"])


def test_actual_generation_keeps_original_aligned_and_trained_identities_distinct(fixture):
    checkpoint = fixture.checkpoint
    assert checkpoint["schema"] == subject.SCHEMA
    assert checkpoint["representation_id"].startswith("gte-768-aligned-reference-interfaces:sha256:")
    assert len({checkpoint["representation_id"], checkpoint["aligned_representation_id"],
                checkpoint["initialization_representation_id"]}) == 3
    assert checkpoint["initialization_representation_id"] == fixture.initialization["representation_id"]
    assert checkpoint["initialization_content_sha256"] == subject.digest(fixture.initialization)
    assert checkpoint["aligned_representation_id"] == fixture.aligned_checkpoint["representation_id"]
    assert checkpoint["aligned_checkpoint_content_sha256"] == subject.digest(fixture.aligned_checkpoint)
    assert checkpoint["aligned_start_model_state_sha256"] == fixture.aligned_checkpoint["model_state_sha256"]
    assert checkpoint["aligned_handoff_sha256"] == fixture.aligned_checkpoint["handoff_sha256"]
    assert checkpoint["aligned_parent_file_pins"] == checkpoint["alignment_file_pins"] == fixture.alignment_file_pins
    assert checkpoint["primary_start"] == subject.PRIMARY_START
    assert make(fixture) == checkpoint
    receipt = inspect(fixture)
    assert receipt["optimizer_steps"] == 1 and receipt["training_execution_authenticated"] is False
    assert receipt["frozen_inherited_tensor_count"] == 26 and receipt["trainable_tensor_count"] == 4


def test_before_state_comes_from_fitted_boundary_and_never_original_seeded_adapter(fixture):
    original, aligned = subject._state(fixture.initialization), aligned_state(fixture)
    report = fixture.training_report
    assert report["schema"] == subject.REPORT_SCHEMA
    assert report["primary_start"] == subject.PRIMARY_START
    assert report["start_model_state_sha256"] == subject.digest(aligned)
    assert report["start_checkpoint_content_sha256"] == subject.digest(fixture.aligned_checkpoint)
    assert report["start_representation_id"] == fixture.aligned_checkpoint["representation_id"]
    assert report["model_state_sha256_before"] == subject.digest(aligned) != subject.digest(original)
    assert report["interface_state_sha256_before"] == subject.digest({name: aligned[name] for name in subject.INTERFACES})
    assert report["interface_state_sha256_before"] != subject.digest({name: original[name] for name in subject.INTERFACES})
    for name in subject.INTERFACES:
        assert fixture.checkpoint["interfaces"][name] != aligned[name]


def test_only_four_interfaces_saved_and_all_twenty_six_learned_tensors_frozen(fixture):
    checkpoint = fixture.checkpoint
    assert set(checkpoint["interfaces"]) == set(subject.INTERFACES)
    assert "initialization" not in checkpoint and "bridge" not in checkpoint
    original = subject._state(fixture.initialization)
    inventory = checkpoint["tensor_inventory"]
    assert len(inventory) == 30
    frozen = [row for row in inventory if not row["requires_grad"]]
    assert len(frozen) == 26
    for row in frozen:
        assert row["sha256"] == subject.digest(original[row["name"]])
        assert row["origin"].startswith("unchanged_copied_")
    assert checkpoint["inherited_state_sha256"] == subject.digest(
        {name: value for name, value in original.items() if name not in subject.INTERFACES})
    assert checkpoint["optimizer"] == {"mode": "fresh", "state": None, "resume": False,
                                      "donor_moments_imported": False}
    assert len(checkpoint["implementation"]) == 10
    assert checkpoint["implementation"] == subject._implementation()
    assert checkpoint["training_report"]["optimizer"]["parameters"] == list(subject.INTERFACES)
    for key in ("production_kd_enabled", "production_kd_eligible", "teacher_qualified", "distillation_executed",
                "encoder_inference_executed", "proof_authority", "optimizer_resume_supported"):
        assert checkpoint[key] is False


def test_reload_has_exact_private_tensors_and_outputs_without_mutating_start(fixture):
    torch = pytest.importorskip("torch")
    before = deepcopy((fixture.initialization, fixture.plan, fixture.batch, fixture.replay,
                       fixture.aligned_checkpoint, fixture.alignment_file_pins, fixture.checkpoint))
    rng, threads = torch.random.get_rng_state().clone(), torch.get_num_threads()
    first = subject.load_interface_checkpoint(fixture.checkpoint, **kwargs(fixture))
    second = subject.load_interface_checkpoint(fixture.checkpoint, **kwargs(fixture))
    assert torch.equal(rng, torch.random.get_rng_state()) and torch.get_num_threads() == threads
    assert first.representation_id == second.representation_id == fixture.checkpoint["representation_id"]
    assert first.aligned_start_representation_id == fixture.aligned_checkpoint["representation_id"]
    original = subject._state(fixture.initialization)
    for (name, left), (_, right) in zip(first.named_parameters(), second.named_parameters()):
        assert torch.equal(left, right) and left.untyped_storage().data_ptr() != right.untyped_storage().data_ptr()
        assert left.requires_grad is (name in subject.INTERFACES)
        assert left.grad is None and right.grad is None
        if name not in subject.INTERFACES:
            assert left.tolist() == original[name]
    with torch.no_grad():
        for head in subject.HEADS:
            for row in fixture.plan["heads"][head]["rows"]:
                vector = torch.tensor([row["native_receipt"]["embedding"]], dtype=torch.float32)
                prefix, bos = torch.tensor([row["prefix_ids"]]), torch.tensor([[1]])
                args = (vector, prefix, bos) if head == "primary384" else (vector, bos, prefix)
                left, right = first(*args), second(*args)
                for name in ("primary_logits", "auxiliary_logits", "shared_condition", "auxiliary_latent"):
                    assert torch.equal(left[name], right[name])
    assert before == (fixture.initialization, fixture.plan, fixture.batch, fixture.replay,
                       fixture.aligned_checkpoint, fixture.alignment_file_pins, fixture.checkpoint)


def test_inspection_and_invalid_loading_stay_dependency_free(fixture, tmp_path):
    path = tmp_path / "aligned-inputs.json"
    path.write_bytes(subject._raw({"checkpoint": fixture.checkpoint, **kwargs(fixture)}))
    code = """import importlib.util,json,sys
spec=importlib.util.spec_from_file_location('isolated_aligned_interfaces',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
payload=json.load(open(sys.argv[2]));module.inspect_interface_checkpoint(**payload)
assert not any(name in sys.modules for name in ('torch','numpy','transformers','ipfs_datasets_py'))
payload['checkpoint']['interfaces']['primary.input_adapter.weight'][0][0]=.1
try:module.load_interface_checkpoint(**payload)
except ValueError:pass
else:raise AssertionError('invalid float32 interface was admitted')
assert not any(name in sys.modules for name in ('torch','numpy','transformers','ipfs_datasets_py'))
"""
    subprocess.run([sys.executable, "-I", "-c", code, str(PATH), str(path)], check=True)


@pytest.mark.parametrize("mutation", ["aligned_content", "aligned_identity", "aligned_state", "alignment_pins",
    "handoff", "parent_pins", "original_identity", "original_content", "original_start", "old_schema",
    "optimizer_moments", "kd", "inherited_inventory", "extra_field"])
def test_resigning_outer_identity_cannot_retag_or_rebind_authenticated_start(fixture, mutation):
    checkpoint = deepcopy(fixture.checkpoint)
    if mutation == "aligned_content": checkpoint["aligned_checkpoint_content_sha256"] = "c" * 64
    elif mutation == "aligned_identity": checkpoint["aligned_representation_id"] = fixture.initialization["representation_id"]
    elif mutation == "aligned_state": checkpoint["aligned_start_model_state_sha256"] = subject.digest(subject._state(fixture.initialization))
    elif mutation == "alignment_pins": checkpoint["alignment_file_pins"]["fit_report_sha256"] = "c" * 64
    elif mutation == "handoff": checkpoint["aligned_handoff_sha256"] = "c" * 64
    elif mutation == "parent_pins": checkpoint["aligned_parent_file_pins"]["plan_sha256"] = "c" * 64
    elif mutation == "original_identity": checkpoint["initialization_representation_id"] = checkpoint["aligned_representation_id"]
    elif mutation == "original_content": checkpoint["initialization_content_sha256"] = "c" * 64
    elif mutation == "original_start": checkpoint["primary_start"] = "original_initialization"
    elif mutation == "old_schema": checkpoint["schema"] = subject._BASE.SCHEMA
    elif mutation == "optimizer_moments": checkpoint["optimizer"]["state"] = {"old": "moments"}
    elif mutation == "kd": checkpoint["production_kd_enabled"] = True
    elif mutation == "inherited_inventory":
        next(row for row in checkpoint["tensor_inventory"] if not row["requires_grad"])["requires_grad"] = True
    elif mutation == "extra_field": checkpoint["start_override"] = False
    resign(checkpoint)
    with pytest.raises(ValueError):
        inspect(fixture, checkpoint)


@pytest.mark.parametrize("mutation", ["schema", "start", "start_identity", "start_content", "start_state",
    "pins", "before_interface", "before_model", "implementation", "head_count", "optimizer_parameter",
    "resume", "gradient_norm", "output_source", "output_digest", "quality", "extra_field"])
def test_report_cannot_claim_original_seed_or_fake_aligned_training_by_resigning(fixture, mutation):
    report = deepcopy(fixture.training_report)
    original = subject._state(fixture.initialization)
    if mutation == "schema": report["schema"] = subject._BASE.REPORT_SCHEMA
    elif mutation == "start": report["primary_start"] = "original_initialization"
    elif mutation == "start_identity": report["start_representation_id"] = fixture.initialization["representation_id"]
    elif mutation == "start_content": report["start_checkpoint_content_sha256"] = subject.digest(fixture.initialization)
    elif mutation == "start_state": report["start_model_state_sha256"] = subject.digest(original)
    elif mutation == "pins": report["alignment_file_pins"]["initialization_sha256"] = "c" * 64
    elif mutation == "before_interface": report["interface_state_sha256_before"] = subject.digest({name: original[name] for name in subject.INTERFACES})
    elif mutation == "before_model": report["model_state_sha256_before"] = subject.digest(original)
    elif mutation == "implementation": report["implementation"].pop("gte_aligned_interface_training.py")
    elif mutation == "head_count": report["after"]["heads"]["primary384"]["reference_token_count"] += 1
    elif mutation == "optimizer_parameter": report["optimizer"]["parameters"].append("primary.condition.weight")
    elif mutation == "resume": report["optimizer"]["resume"] = True
    elif mutation == "gradient_norm": report["history"][0]["gradient_global_norm_before_clipping"] += 1.
    elif mutation == "output_source":
        report["trained_reference_outputs"]["primary384"][0]["source_sha256"] = "c" * 64
        report["trained_reference_outputs_sha256"] = subject.digest(report["trained_reference_outputs"])
    elif mutation == "output_digest": report["trained_reference_outputs_sha256"] = "c" * 64
    elif mutation == "quality": report["teacher_qualified"] = True
    elif mutation == "extra_field": report["qualified_from_alignment"] = True
    checkpoint = deepcopy(fixture.checkpoint)
    checkpoint["training_report"] = report
    resign(checkpoint)
    with pytest.raises(ValueError):
        inspect(fixture, checkpoint)


@pytest.mark.parametrize("mutation", ["integer", "float64", "nan", "wrong_shape", "missing", "inherited",
                                      "unchanged_aligned_boundary", "unchanged_aligned_connector"])
def test_only_exact_changed_float32_interfaces_are_admitted(fixture, mutation):
    interfaces, report = deepcopy(fixture.checkpoint["interfaces"]), deepcopy(fixture.training_report)
    name = "primary.input_adapter.weight"
    if mutation == "integer": interfaces[name][0][0] = 0
    elif mutation == "float64": interfaces[name][0][0] = .1
    elif mutation == "nan": interfaces[name][0][0] = float("nan")
    elif mutation == "wrong_shape": interfaces[name][0].pop()
    elif mutation == "missing": interfaces.pop("auxiliary_connector.bias")
    elif mutation == "inherited": interfaces["primary.condition.weight"] = [[0.]]
    else:
        key = name if mutation == "unchanged_aligned_boundary" else "auxiliary_connector.bias"
        interfaces[key] = deepcopy(aligned_state(fixture)[key])
        report["interface_state_sha256_after"] = subject.digest(interfaces)
        report["model_state_sha256_after"] = subject.digest(subject._state(fixture.initialization, interfaces))
    with pytest.raises(ValueError):
        make(fixture, interfaces=interfaces, report=report)


def test_external_aligned_parent_pins_and_embedded_original_are_independently_admitted(fixture):
    pins = deepcopy(fixture.alignment_file_pins)
    pins["bridge_checkpoint_sha256"] = "c" * 64
    with pytest.raises(ValueError):
        inspect(fixture, expected_alignment_file_pins=pins)
    aligned = deepcopy(fixture.aligned_checkpoint)
    aligned["initialization"]["seed"] += 1
    with pytest.raises(ValueError):
        inspect(fixture, aligned_checkpoint=aligned)


def test_valid_aligned_generation_for_different_encoder_assets_is_rejected_before_torch(fixture, tmp_path):
    """A consistent foreign asset binding cannot be used with this native plan."""
    aligned = subject._helper("gte_aligned_decoder")
    handoff_contract = aligned._helper("gte_aligned_decoder_contract")
    foreign = deepcopy(fixture.aligned_checkpoint)
    plan, report = foreign["plan"], foreign["fit_report"]
    plan["asset_manifest_sha256"] = "c" * 64
    for row in plan["train_rows"] + plan["validation_rows"]:
        row["asset_manifest_sha256"] = "c" * 64
    plan["train_rows_sha256"] = subject.digest(plan["train_rows"])
    plan["validation_rows_sha256"] = subject.digest(plan["validation_rows"])
    plan["pairs_sha256"] = subject.digest(sorted(plan["train_rows"] + plan["validation_rows"],
                                                key=lambda row: row["task_id"]))
    plan["plan_sha256"] = subject.digest({key: value for key, value in plan.items() if key != "plan_sha256"})
    report["plan_sha256"] = handoff_contract._file_digest_binding(plan)
    report["plan_content_sha256"] = plan["plan_sha256"]
    report["train_rows_sha256"] = plan["train_rows_sha256"]
    report["validation_rows_sha256"] = plan["validation_rows_sha256"]
    identity = {"initialization_sha256": report["initialization_sha256"],
                "plan_sha256": report["plan_sha256"], "bridge_weights_sha256": report["bridge_weights_sha256"]}
    report["aligned_representation_id"] = "legal_ir:aligned_dual_decoder_768:" + handoff_contract._file_digest_binding(identity)
    pins = deepcopy(fixture.alignment_file_pins)
    pins["plan_sha256"] = report["plan_sha256"]
    pins["fit_report_sha256"] = handoff_contract._file_digest_binding(report)
    foreign["parent_file_pins"] = pins
    foreign["representation_id"] = report["aligned_representation_id"]
    foreign["handoff"] = aligned._handoff(fixture.initialization, foreign["bridge"], plan, report,
                                         pins, fixture.donor_pins)
    foreign["handoff_sha256"] = subject.digest(foreign["handoff"])
    assert aligned.inspect_aligned_decoder(foreign, expected_file_pins=pins,
        expected_donor_pins=fixture.donor_pins)["status"] == "fitted_unqualified"
    payload = {"checkpoint": fixture.checkpoint, **kwargs(fixture), "aligned_checkpoint": foreign,
               "expected_alignment_file_pins": pins}
    path = tmp_path / "foreign-asset-start.json"
    path.write_bytes(subject._raw(payload))
    code = """import importlib.util,json,sys
spec=importlib.util.spec_from_file_location('foreign_asset_start',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
payload=json.load(open(sys.argv[2]))
try:module.load_interface_checkpoint(**payload)
except ValueError as error:assert 'producer profile' in str(error)
else:raise AssertionError('foreign asset start admitted')
assert not any(name in sys.modules for name in ('torch','numpy','transformers','ipfs_datasets_py'))
"""
    subprocess.run([sys.executable, "-I", "-c", code, str(PATH), str(path)], check=True)


def test_incomplete_native_plan_cannot_publish_aligned_trained_generation(fixture):
    with pytest.raises(ValueError):
        inspect(fixture, plan=fixture.empty_plan)
    with pytest.raises(ValueError):
        subject.create_interface_checkpoint(fixture.initialization, fixture.empty_plan,
            aligned_checkpoint=fixture.aligned_checkpoint, expected_alignment_file_pins=fixture.alignment_file_pins,
            expected_donor_pins=fixture.donor_pins, interfaces=fixture.checkpoint["interfaces"],
            training_report=fixture.training_report)


def test_saved_float32_payload_and_constructor_do_not_alias_immutable_inputs(fixture, tmp_path):
    before = deepcopy((fixture.initialization, fixture.aligned_checkpoint, fixture.plan, fixture.training_report))
    checkpoint = make(fixture)
    path = tmp_path / "aligned-trained.json"
    path.write_bytes(subject._raw(checkpoint) + b"\n")
    saved = json.loads(path.read_bytes())
    assert inspect(fixture, saved)["model_state_sha256"] == checkpoint["model_state_sha256"]
    value = saved["interfaces"][subject.INTERFACES[0]][0][0]
    assert value == struct.unpack("!f", struct.pack("!f", value))[0]
    checkpoint["interfaces"][subject.INTERFACES[0]][0][0] += 1.
    checkpoint["training_report"]["alignment_file_pins"]["plan_sha256"] = "c" * 64
    assert before == (fixture.initialization, fixture.aligned_checkpoint, fixture.plan, fixture.training_report)
