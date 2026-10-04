"""Real fitted-start AdamW updates, with explicitly synthetic native receipts.

Original donor checkpoints, cached 384D/8D assets and native plan are shared
unchanged with the synthetic analytic-fit generation used by this module.
"""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[5]
PATH = ROOT / "ipfs_datasets_py/logic/formalization/autoencoder/gte_aligned_interface_training.py"


def read_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


subject = read_module("gte_aligned_interface_training_test_subject", PATH)
native_fixture = read_module("gte_aligned_interface_training_native_fixture", Path(__file__).with_name("test_gte_decoder_native_batch.py"))
alignment_cli = read_module("gte_aligned_interface_training_alignment_cli",
                            ROOT / "scripts/ops/autoencoder/prepare_gte_alignment.py")
torch = pytest.importorskip("torch")


@pytest.fixture(scope="module", autouse=True)
def single_thread():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def aligned_training_fixture(tmp_path_factory):
    """Fit a separate generation from exactly the native fixture's originals."""
    fixture = native_fixture.decoder_native_fixture(tmp_path_factory)
    aligned = subject._helper("gte_aligned_decoder")
    contract = aligned._helper("gte_alignment_contract")
    bridge_helper = aligned._helper("gte_affine_bridge")
    originals = fixture.primary_archive["rows"][:2] + fixture.primary_validation_archive["rows"][:1]
    rows = [{"id": row["id"], "domain_id": "legal_ir", "document_id": row["id"],
        "group_id": row["group_id"], "split": row["split"], "source_text": row["source_text"],
        "embedding": deepcopy(row["embedding"]), "reference_target": deepcopy(row["target"]),
        "target_origin": "authored", "source_language": "en", "evaluation_role": "development"}
        for row in originals]
    audit = contract._AUDIT.audit_transfer_rows(rows, dimension=384,
        vector_space_id=bridge_helper.SOURCE_REPRESENTATION_ID)
    tasks = contract._BRIDGE._CORPUS.prepare_embedding_tasks(rows, audit)
    selected_by_source = {row["source_sha256"]: row for row in fixture.receipts_768}
    receipts = []
    for task in tasks["tasks"]:
        if task["source_sha256"] in selected_by_source:
            receipt = deepcopy(selected_by_source[task["source_sha256"]])
            receipt["id"] = task["id"]
        else:
            receipt = native_fixture.receipt(task, index=180)
        receipts.append(receipt)
    pairs = contract._BRIDGE.prepare_bridge_pairs(rows, audit, tasks, receipts)
    plan = contract.prepare_alignment_plan(pairs, regularization_candidates=(.01,))
    selection, state = alignment_cli._fit_candidates(plan)
    initialization = fixture.initialization
    teacher = {"teacher_runtime_id": initialization["primary"]["donor"]["runtime_id"],
        "source_representation_id": bridge_helper.SOURCE_REPRESENTATION_ID,
        "checkpoint_sha256": fixture.donor_pins["teacher384_checkpoint_sha256"],
        "input_transform": deepcopy(initialization["primary"]["input_transform"])}
    bridge = alignment_cli._pack_bridge(state,
        config={"seed": initialization["seed"], "domain_id": "legal_ir"}, teacher=teacher)
    identity = {"initialization_sha256": alignment_cli._digest(initialization),
        "plan_sha256": alignment_cli._digest(plan), "bridge_weights_sha256": bridge["weights_sha256"]}
    report = {"schema": "gte-affine-alignment-fit/v1", **identity,
        "bridge_checkpoint_sha256": alignment_cli._digest(bridge),
        "initialization_representation_id": initialization["representation_id"],
        "aligned_representation_id": "legal_ir:aligned_dual_decoder_768:" + alignment_cli._digest(identity),
        "donor_pins": deepcopy(fixture.donor_pins), "source_profile_id": pairs["student_profile_id"],
        "train_rows_sha256": plan["train_rows_sha256"], "validation_rows_sha256": plan["validation_rows_sha256"],
        "plan_content_sha256": plan["plan_sha256"], "pair_coverage_status": pairs["status"],
        "missing_eligible_pair_receipts": pairs["counts"]["missing_eligible_pair_receipts"],
        "selection": selection, "analytic_alignment_fit_executed": True,
        "primary_input_boundary_fitted": True, "auxiliary_connector_fitted": False,
        "validation_used_for_fit": False, "original_initialization_unchanged": True,
        "inherited_decoder_weights_unchanged": True, "fitted_bridge_reloaded_exactly": True,
        "adapter_outputs_normalized": False, "donor_transform_applied_by_decoder_only": True,
        "encoder_numerics_verified": False, "source_vectors_producer_verified": False,
        "student_vectors_producer_verified": False, "source_fidelity_qualified": False,
        "teacher_qualified": False, "optimizer_steps": 0, "distillation_executed": False,
        "student_decoder_gradient_training_executed": False, "proof_authority": False}
    pins = {"initialization_sha256": identity["initialization_sha256"],
        "bridge_checkpoint_sha256": report["bridge_checkpoint_sha256"], "plan_sha256": identity["plan_sha256"],
        "fit_report_sha256": alignment_cli._digest(report)}
    fixture.aligned_model, fixture.aligned_checkpoint = aligned.create_aligned_decoder(
        initialization, bridge, plan, report, expected_file_pins=pins,
        expected_donor_pins=fixture.donor_pins)
    fixture.alignment_file_pins = pins
    return fixture


@pytest.fixture(scope="module")
def fixture(tmp_path_factory):
    return aligned_training_fixture(tmp_path_factory)


def kwargs(fixture):
    return {"initialization": fixture.initialization, "batch": fixture.batch,
            "replay": fixture.replay, "expected_donor_pins": fixture.donor_pins,
            "aligned_checkpoint": fixture.aligned_checkpoint,
            "expected_alignment_file_pins": fixture.alignment_file_pins}


def admission(fixture):
    return {"plan": fixture.plan, **kwargs(fixture)}


@pytest.fixture(scope="module")
def trained(fixture):
    """Capture real optimizer steps and the live post-update model for verification."""
    models, optimizers = [], []
    helper, adamw = subject._helper, torch.optim.AdamW
    def dependencies(name):
        module = helper(name)
        if name == "gte_aligned_decoder":
            original = module.load_aligned_decoder
            def capture(*args, **kwargs):
                model = original(*args, **kwargs)
                models.append(model)
                return model
            module.load_aligned_decoder = capture
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
    before = subject.digest([fixture.initialization, fixture.plan, fixture.batch, fixture.replay, fixture.donor_pins,
                            fixture.aligned_checkpoint, fixture.alignment_file_pins])
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
    assert before == subject.digest([fixture.initialization, fixture.plan, fixture.batch, fixture.replay, fixture.donor_pins,
                            fixture.aligned_checkpoint, fixture.alignment_file_pins])
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


def test_bad_aligned_closure_and_valid_foreign_initialization_fail_before_torch(fixture, tmp_path):
    """A valid fit for another initialization must not retag native evidence."""
    cases = []
    for mutation in ("external_pin", "embedded_weights", "state_hash", "qualification", "profile"):
        case = deepcopy(admission(fixture))
        if mutation == "external_pin":
            case["expected_alignment_file_pins"]["initialization_sha256"] = "0" * 64
        elif mutation == "embedded_weights":
            case["aligned_checkpoint"]["initialization"]["primary"]["model_state"]["target_embedding.weight"][0][0] += .1
        elif mutation == "state_hash":
            case["aligned_checkpoint"]["model_state_sha256"] = "0" * 64
        elif mutation == "qualification":
            case["aligned_checkpoint"]["teacher_qualified"] = True
        else:
            case["aligned_checkpoint"]["source_profile_id"] = "wrong-native-profile"
        cases.append(case)
    reuse = subject._helper("gte_decoder_reuse")
    _, foreign_initialization = reuse.create_dual_decoder(fixture.primary_path, fixture.legacy8_path,
        expected_teacher384_sha256=fixture.donor_pins["teacher384_checkpoint_sha256"],
        expected_legacy8_sha256=fixture.donor_pins["legacy8_checkpoint_sha256"],
        repository_root=ROOT, legacy_implementation_root=ROOT, seed=1730)
    previous = fixture.aligned_checkpoint
    foreign_report = deepcopy(previous["fit_report"])
    foreign_report["initialization_sha256"] = alignment_cli._digest(foreign_initialization)
    foreign_report["initialization_representation_id"] = foreign_initialization["representation_id"]
    identity = {key: foreign_report[key] for key in
                ("initialization_sha256", "plan_sha256", "bridge_weights_sha256")}
    foreign_report["aligned_representation_id"] = "legal_ir:aligned_dual_decoder_768:" + alignment_cli._digest(identity)
    foreign_pins = {**fixture.alignment_file_pins,
        "initialization_sha256": foreign_report["initialization_sha256"],
        "fit_report_sha256": alignment_cli._digest(foreign_report)}
    aligned = subject._helper("gte_aligned_decoder")
    _, foreign_checkpoint = aligned.create_aligned_decoder(foreign_initialization,
        previous["bridge"], previous["plan"], foreign_report,
        expected_file_pins=foreign_pins, expected_donor_pins=fixture.donor_pins)
    foreign = deepcopy(admission(fixture))
    foreign["aligned_checkpoint"] = foreign_checkpoint
    foreign["expected_alignment_file_pins"] = foreign_pins
    cases.append(foreign)
    path = tmp_path / "bad-aligned-starts.json"
    path.write_text(json.dumps(cases))
    code = """import builtins,importlib.util,json,sys
spec=importlib.util.spec_from_file_location('isolated_bad_aligned_training',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
cases=json.load(open(sys.argv[2]));original=builtins.__import__
def admitted_import(name,*args,**kwargs):
    assert name.split('.')[0] not in ('torch','numpy','transformers'),name
    return original(name,*args,**kwargs)
builtins.__import__=admitted_import
for index,payload in enumerate(cases):
    plan=payload.pop('plan')
    try:module.train_decoder_interfaces(plan,**payload)
    except ValueError as error:
        if index==len(cases)-1:assert 'embedded initialization differs' in str(error),error
    else:raise AssertionError('invalid aligned start admitted')
assert 'torch' not in sys.modules
"""
    subprocess.run([sys.executable, "-I", "-c", code, str(PATH), str(path)], check=True)


def test_real_optimizer_changes_only_four_interfaces_and_improves_fixture_ce(fixture, trained):
    report, optimizer = trained.report, trained.optimizer
    assert report["optimizer_steps"] == report["steps"] == optimizer.recorded_steps == 3
    assert report["training_executed"] is report["reference_supervised_training_executed"] is True
    assert report["primary_start"] == "authenticated_aligned_generation"
    assert report["start_representation_id"] == fixture.aligned_checkpoint["representation_id"]
    assert report["start_checkpoint_content_sha256"] == subject.digest(fixture.aligned_checkpoint)
    assert report["start_model_state_sha256"] == report["model_state_sha256_before"] == fixture.aligned_checkpoint["model_state_sha256"]
    assert report["alignment_file_pins"] == fixture.alignment_file_pins
    assert report["after"]["loss"] < report["before"]["loss"]
    assert report["interface_state_sha256_before"] != report["interface_state_sha256_after"]
    assert report["model_state_sha256_before"] != report["model_state_sha256_after"]
    parameters = dict(trained.model.named_parameters())
    expected = subject._helper("gte_aligned_decoder")._state(fixture.initialization, fixture.aligned_checkpoint["bridge"])
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
    original_admission = {key: value for key, value in kwargs(fixture).items()
                          if key not in ("aligned_checkpoint", "expected_alignment_file_pins")}
    result = objective.compute_native_reference_objective(trained.model, fixture.plan, **original_admission)
    assert float(result["loss"].detach()) == trained.report["after"]["loss"]
    for name in subject.HEADS:
        assert float(result["heads"][name]["loss"].detach()) == trained.report["after"]["heads"][name]["loss"]


def test_before_objective_uses_fitted_boundary_and_original_auxiliary_connector(fixture, trained):
    objective = subject._helper("gte_decoder_native_objective")
    original_admission = {key: value for key, value in kwargs(fixture).items()
                          if key not in ("aligned_checkpoint", "expected_alignment_file_pins")}
    aligned = subject._helper("gte_aligned_decoder")
    fitted = aligned.load_aligned_decoder(fixture.aligned_checkpoint,
        expected_file_pins=fixture.alignment_file_pins, expected_donor_pins=fixture.donor_pins)
    seeded = subject._helper("gte_decoder_reuse").load_dual_decoder(
        fixture.initialization, expected_donor_pins=fixture.donor_pins)
    fitted_result = objective.compute_native_reference_objective(fitted, fixture.plan, **original_admission)
    seeded_result = objective.compute_native_reference_objective(seeded, fixture.plan, **original_admission)
    assert float(fitted_result["loss"].detach()) == trained.report["before"]["loss"]
    assert float(fitted_result["loss"].detach()) != float(seeded_result["loss"].detach())
    assert trained.report["model_state_sha256_before"] == objective._state_digest(fitted)
    assert trained.report["model_state_sha256_before"] != objective._state_digest(seeded)
    fitted_interfaces = subject._interface_state(fitted)
    assert trained.report["interface_state_sha256_before"] == subject.digest(fitted_interfaces)
    assert fitted_interfaces["primary.input_adapter.weight"] == fixture.aligned_checkpoint["bridge"]["model_state"]["weight"]
    assert fitted_interfaces["primary.input_adapter.bias"] == fixture.aligned_checkpoint["bridge"]["model_state"]["bias"]
    for name in ("weight", "bias"):
        assert fitted_interfaces["auxiliary_connector." + name] == fixture.initialization["connector"][name]


def test_exact_saved_reload_matches_live_postoptimizer_outputs_and_private_storage(fixture, trained, tmp_path, monkeypatch):
    path = tmp_path / "trained.json"
    path.write_text(json.dumps(trained.checkpoint, sort_keys=True))
    saved = json.loads(path.read_text())
    contract = subject._helper("gte_aligned_interface_checkpoint")
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
    assert saved["representation_id"] != fixture.aligned_checkpoint["representation_id"]
    assert saved["representation_id"].startswith("gte-768-aligned-reference-interfaces:sha256:")
    assert verification["schema"] == "gte-aligned-interface-reload-verification/v1"
    assert verification["status"] == "exact_trained_aligned_reload_verified_unqualified"
    assert verification["start_representation_id"] == fixture.aligned_checkpoint["representation_id"]
    assert saved["optimizer"] == {"mode": "fresh", "state": None, "resume": False, "donor_moments_imported": False}


def test_saved_verifier_rejects_forged_output_inventory_even_with_consistent_contract_hashes(fixture, trained):
    contract = subject._helper("gte_aligned_interface_checkpoint")
    report = deepcopy(trained.report)
    report["trained_reference_outputs"]["legacy8"][0]["auxiliary_logits_sha256"] = "a" * 64
    report["trained_reference_outputs_sha256"] = subject.digest(report["trained_reference_outputs"])
    forged = contract.create_interface_checkpoint(fixture.initialization, fixture.plan,
        expected_donor_pins=fixture.donor_pins, aligned_checkpoint=fixture.aligned_checkpoint,
        expected_alignment_file_pins=fixture.alignment_file_pins,
        interfaces=trained.checkpoint["interfaces"], training_report=report)
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
            expected_donor_pins=None, aligned_checkpoint=None, expected_alignment_file_pins=None, **controls)


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
