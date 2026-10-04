"""Private analytic-boundary handoff on synthetic, independently scoped rows.

These checks do not produce qualified teachers, real multilingual embeddings,
or decoder-training evidence. They exercise exact reuse and the trainable path.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[5]
PATH = ROOT / "ipfs_datasets_py/logic/formalization/autoencoder/gte_aligned_decoder.py"


def read_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


subject = read_module("gte_aligned_decoder_subject", PATH)
reuse_fixture = read_module("gte_aligned_reuse_fixture", Path(__file__).with_name("test_gte_decoder_reuse.py"))
alignment_cli = read_module("gte_aligned_alignment_cli", ROOT / "scripts/ops/autoencoder/prepare_gte_alignment.py")
torch = pytest.importorskip("torch")


@pytest.fixture(scope="module", autouse=True)
def single_thread():
    original = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(original)


@pytest.fixture(scope="module")
def parents(tmp_path_factory):
    donors = reuse_fixture.donors.__wrapped__(tmp_path_factory)
    original_model, initialization = reuse_fixture.create(donors)
    contract = subject._helper("gte_alignment_contract")
    bridge_helper = subject._helper("gte_affine_bridge")
    rows = []
    for index, split in enumerate(("train", "train", "validation")):
        source = [0.] * 384
        source[index] = 1.
        rows.append({"id": "synthetic-aligned-" + str(index), "domain_id": "legal_ir",
            "document_id": "document-" + str(index), "group_id": "group-" + str(index),
            "split": split, "source_text": "Separate source " + str(index),
            "embedding": source, "reference_target": {"authored": index},
            "target_origin": "authored", "source_language": "en", "evaluation_role": "development"})
    audit = contract._AUDIT.audit_transfer_rows(rows, dimension=384,
        vector_space_id=bridge_helper.SOURCE_REPRESENTATION_ID)
    tasks = contract._BRIDGE._CORPUS.prepare_embedding_tasks(rows, audit)
    receipts = []
    row_index = {row["id"]: index for index, row in enumerate(rows)}
    for task in tasks["tasks"]:
        vector = [0.] * 768
        vector[row_index[task["metadata"]["source_id"]]] = 1.
        receipts.append({"schema": contract._BRIDGE._CORPUS.RECEIPT_SCHEMA,
            "id": task["id"], "source_sha256": task["source_sha256"],
            "profile_id": bridge_helper.STUDENT_REPRESENTATION_ID, "dimension": 768,
            "embedding": vector, "token_count_including_special_tokens": 5,
            "token_input_sha256": "a" * 64, "truncated": False, "normalized": True,
            "asset_manifest_sha256": "b" * 64})
    pairs = contract._BRIDGE.prepare_bridge_pairs(rows, audit, tasks, receipts)
    plan = contract.prepare_alignment_plan(pairs, regularization_candidates=(.01,))
    selection, state = alignment_cli._fit_candidates(plan)
    teacher = {"teacher_runtime_id": initialization["primary"]["donor"]["runtime_id"],
        "source_representation_id": bridge_helper.SOURCE_REPRESENTATION_ID,
        "checkpoint_sha256": initialization["donor_pins"]["teacher384_checkpoint_sha256"],
        "input_transform": initialization["primary"]["input_transform"]}
    bridge = alignment_cli._pack_bridge(state,
        config={"seed": initialization["seed"], "domain_id": "legal_ir"}, teacher=teacher)
    identity = {"initialization_sha256": alignment_cli._digest(initialization),
        "plan_sha256": alignment_cli._digest(plan), "bridge_weights_sha256": bridge["weights_sha256"]}
    report = {"schema": "gte-affine-alignment-fit/v1", **identity,
        "bridge_checkpoint_sha256": alignment_cli._digest(bridge),
        "initialization_representation_id": initialization["representation_id"],
        "aligned_representation_id": "legal_ir:aligned_dual_decoder_768:" + alignment_cli._digest(identity),
        "donor_pins": initialization["donor_pins"], "source_profile_id": pairs["student_profile_id"],
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
    return {"initialization": initialization, "bridge": bridge, "plan": plan, "fit_report": report,
        "file_pins": pins, "donor_pins": initialization["donor_pins"], "donors": donors,
        "original_model": original_model}


def create(parents):
    return subject.create_aligned_decoder(*[parents[key] for key in ("initialization", "bridge", "plan", "fit_report")],
        expected_file_pins=parents["file_pins"], expected_donor_pins=parents["donor_pins"])


def inspect(checkpoint, parents):
    return subject.inspect_aligned_decoder(checkpoint,
        expected_file_pins=parents["file_pins"], expected_donor_pins=parents["donor_pins"])


def reload(checkpoint, parents):
    return subject.load_aligned_decoder(checkpoint,
        expected_file_pins=parents["file_pins"], expected_donor_pins=parents["donor_pins"])


@pytest.fixture(scope="module")
def aligned(parents):
    return create(parents)


def inputs():
    vectors = torch.zeros((2, 768), dtype=torch.float32)
    vectors[0, 0], vectors[1, 1] = 1., 1.
    return vectors, torch.tensor([[1, 3], [1, 4]]), torch.tensor([[1, 3, 4], [1, 4, 5]])


def test_module_import_is_dependency_free():
    program = """import importlib.util,sys
spec=importlib.util.spec_from_file_location('isolated_aligned',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
assert not any(name in sys.modules for name in ('torch','transformers','numpy','ipfs_datasets_py'))
"""
    subprocess.run([sys.executable, "-I", "-c", program, str(PATH)], check=True)


def test_checkpoint_inspection_is_dependency_free(aligned, parents, tmp_path):
    checkpoint_path, pins_path, donor_pins_path = [tmp_path / name for name in ("student.json", "pins.json", "donor-pins.json")]
    checkpoint_path.write_text(json.dumps(aligned[1]))
    pins_path.write_text(json.dumps(parents["file_pins"]))
    donor_pins_path.write_text(json.dumps(parents["donor_pins"]))
    program = """import importlib.util,json,sys
spec=importlib.util.spec_from_file_location('isolated_aligned_inspection',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
payloads=[json.loads(open(path).read()) for path in sys.argv[2:]]
report=module.inspect_aligned_decoder(payloads[0],expected_file_pins=payloads[1],expected_donor_pins=payloads[2])
assert report['copied_tensor_count']==26 and report['fitted_tensor_count']==2
assert not any(name in sys.modules for name in ('torch','transformers','numpy','ipfs_datasets_py'))
"""
    subprocess.run([sys.executable, "-I", "-c", program, str(PATH), str(checkpoint_path), str(pins_path), str(donor_pins_path)], check=True)


def test_only_primary_affine_tensors_change_and_all_26_body_tensors_are_exact(aligned, parents):
    model, checkpoint = aligned
    original = parents["original_model"]
    for name, value in model.state_dict().items():
        assert value.data_ptr() != original.state_dict()[name].data_ptr()
        if name in subject._PRIMARY_BOUNDARY:
            assert not torch.equal(value, original.state_dict()[name])
            assert torch.equal(value, torch.tensor(parents["bridge"]["model_state"][name.rsplit(".", 1)[1]]))
        else:
            assert torch.equal(value, original.state_dict()[name])
    receipt = inspect(checkpoint, parents)
    assert receipt["tensor_count"] == 30 and receipt["copied_tensor_count"] == 26
    assert receipt["fitted_tensor_count"] == receipt["unfitted_connector_tensor_count"] == 2
    assert receipt["trainable_tensor_count"] == 4
    assert receipt["fitted_boundary_parameter_count"] == 768 * 384 + 384
    assert receipt["unfitted_connector_parameter_count"] == 8 * model.primary.decoder.hidden_size + 8


def test_parent_snapshot_flags_remain_historical_and_current_identity_is_distinct(aligned, parents):
    model, checkpoint = aligned
    for key in ("initialization", "bridge", "plan", "fit_report"):
        assert checkpoint[key] == parents[key]
    assert checkpoint["initialization"]["training_executed"] is False
    assert checkpoint["initialization"]["boundary_alignment_required"] is True
    assert checkpoint["analytic_alignment_fit_executed"] is True
    assert checkpoint["primary_input_boundary_fitted"] is True
    assert checkpoint["auxiliary_connector_fitted"] is False
    assert checkpoint["boundary_alignment_required"] is True
    assert checkpoint["representation_id"] == parents["fit_report"]["aligned_representation_id"]
    assert checkpoint["representation_id"] != parents["initialization"]["representation_id"]
    assert model.representation_id == checkpoint["representation_id"]
    assert model.initialization_representation_id == parents["initialization"]["representation_id"]
    assert model.aligned_identity == checkpoint["handoff"]
    assert checkpoint["optimizer"] == {"mode": "fresh", "state": None, "resume": False}
    for key in ("teacher_qualified", "source_fidelity_qualified", "encoder_numerics_verified",
                "student_decoder_gradient_training_executed", "distillation_executed", "proof_authority"):
        assert checkpoint[key] is False


def test_fitted_boundary_remains_raw_and_donor_center_rms_transform_is_applied_once(aligned, parents):
    model, _ = aligned
    vectors, primary_prefix, auxiliary_prefix = inputs()
    adapted = torch.nn.functional.linear(vectors,
        torch.tensor(parents["bridge"]["model_state"]["weight"]),
        torch.tensor(parents["bridge"]["model_state"]["bias"]))
    assert torch.equal(model.primary.input_adapter(vectors), adapted)
    assert not torch.allclose(adapted.norm(dim=1), torch.ones(2))
    transform = parents["initialization"]["primary"]["input_transform"]
    normalized = (adapted - torch.tensor(transform["mean"])) / transform["scale"]
    projected = normalized + model.primary.projection_up(torch.tanh(model.primary.projection_down(normalized)))
    assert torch.equal(model.primary.project_input(vectors), projected)
    condition = torch.tanh(model.primary.condition(projected))
    result = model(vectors, primary_prefix, auxiliary_prefix)
    assert torch.equal(result["shared_condition"], condition)
    assert torch.equal(result["primary_logits"], model.primary.decode_from_condition(condition, primary_prefix))
    assert torch.equal(result["auxiliary_logits"], model.legacy8(model.auxiliary_connector(condition), auxiliary_prefix)[1])
    assert result["primary_logits"].shape[-1] != result["auxiliary_logits"].shape[-1]


def test_auxiliary_gradient_reaches_all_four_shared_interfaces_and_no_inherited_weights(aligned, parents):
    model = reload(aligned[1], parents)
    before = {name: value.clone() for name, value in model.state_dict().items()}
    auxiliary = model(*inputs())["auxiliary_logits"]
    coefficients = torch.linspace(.5, 1.5, auxiliary.numel()).reshape(auxiliary.shape)
    (auxiliary * coefficients).sum().backward()
    for name, parameter in model.named_parameters():
        if name in subject._PRIMARY_BOUNDARY | subject._AUXILIARY_CONNECTOR:
            assert parameter.requires_grad and parameter.grad is not None
            assert bool(torch.isfinite(parameter.grad).all()) and bool((parameter.grad != 0.).any())
        else:
            assert not parameter.requires_grad and parameter.grad is None
    assert all(torch.equal(value, before[name]) for name, value in model.state_dict().items())


def test_primary_gradient_reaches_fitted_adapter_without_changing_auxiliary_connector(aligned, parents):
    model = reload(aligned[1], parents)
    primary = model(*inputs())["primary_logits"]
    primary.square().mean().backward()
    for parameter in model.primary.input_adapter.parameters():
        assert parameter.grad is not None and torch.isfinite(parameter.grad).all()
        assert (parameter.grad != 0.).any()
    assert all(parameter.grad is None for parameter in model.auxiliary_connector.parameters())


def test_exact_reload_preserves_values_predictions_rng_threads_and_evaluation_mode(aligned, parents):
    model, checkpoint = aligned
    before_rng = torch.get_rng_state().clone()
    before_threads = torch.get_num_threads()
    restored = reload(checkpoint, parents)
    assert torch.equal(before_rng, torch.get_rng_state()) and torch.get_num_threads() == before_threads
    assert all(not module.training for module in restored.modules())
    for name, value in model.state_dict().items():
        assert torch.equal(value, restored.state_dict()[name])
        assert value.data_ptr() != restored.state_dict()[name].data_ptr()
    expected, actual = model(*inputs()), restored(*inputs())
    assert all(torch.equal(expected[key], actual[key]) for key in expected)
    receipt = inspect(checkpoint, parents)
    assert subject.digest({name: value.tolist() for name, value in restored.state_dict().items()}) == receipt["model_state_sha256"]


def test_construction_restores_threads_rng_and_autograd_context(parents):
    prior_threads = torch.get_num_threads()
    torch.set_num_threads(2)
    try:
        before_rng = torch.get_rng_state().clone()
        before = deepcopy(tuple(parents[key] for key in ("initialization", "bridge", "plan", "fit_report")))
        with torch.no_grad():
            model, checkpoint = create(parents)
            assert not torch.is_grad_enabled()
        assert torch.is_grad_enabled() and torch.get_num_threads() == 2
        assert torch.equal(before_rng, torch.get_rng_state())
        assert tuple(parents[key] for key in ("initialization", "bridge", "plan", "fit_report")) == before
        assert all(parameter.grad is None for parameter in model.parameters())
    finally:
        torch.set_num_threads(prior_threads)


def test_private_generations_and_nested_payloads_do_not_alias_callers_or_other_students(parents, aligned):
    arguments = deepcopy(parents)
    first, checkpoint = create(arguments)
    second = reload(checkpoint, parents)
    pointers = [value.untyped_storage().data_ptr() for value in second.state_dict().values()]
    assert len(pointers) == len(set(pointers))
    arguments["bridge"]["model_state"]["bias"][0] += 123.
    arguments["initialization"]["connector"]["bias"][0] += 123.
    assert checkpoint["bridge"] == parents["bridge"]
    assert checkpoint["initialization"] == parents["initialization"]
    with torch.no_grad():
        second.primary.input_adapter.bias.add_(1.)
        second.legacy8.output.bias.add_(2.)
    assert not torch.equal(first.primary.input_adapter.bias, second.primary.input_adapter.bias)
    assert not torch.equal(first.legacy8.output.bias, second.legacy8.output.bias)
    checkpoint["bridge"]["model_state"]["bias"][0] += 99.
    assert torch.equal(first.primary.input_adapter.bias, aligned[0].primary.input_adapter.bias)


def test_create_and_reload_leave_both_donor_files_and_original_student_unchanged(parents, aligned):
    donors = parents["donors"]
    paths = (donors["primary"]["path"], donors["legacy_path"])
    before = [path.read_bytes() for path in paths]
    original = {name: value.clone() for name, value in parents["original_model"].state_dict().items()}
    create(parents)
    reload(aligned[1], parents)
    assert [path.read_bytes() for path in paths] == before
    assert all(torch.equal(value, original[name]) for name, value in parents["original_model"].state_dict().items())


def test_private_construction_failure_restores_process_state(aligned, parents, monkeypatch):
    real_helper = subject._helper
    reuse = real_helper("gte_decoder_reuse")
    def fail_load(*args, **kwargs):
        assert torch.get_num_threads() == 1
        torch.rand(7)
        raise RuntimeError("synthetic private-load failure")
    replacement = SimpleNamespace(_PRIMARY=reuse._PRIMARY, _LEGACY=reuse._LEGACY,
                                  load_dual_decoder=fail_load)
    monkeypatch.setattr(subject, "_helper", lambda name:
        replacement if name == "gte_decoder_reuse" else real_helper(name))
    before_threads = torch.get_num_threads()
    torch.set_num_threads(2)
    try:
        before_rng = torch.get_rng_state().clone()
        with torch.no_grad():
            with pytest.raises(RuntimeError, match="synthetic private-load failure"):
                reload(aligned[1], parents)
            assert not torch.is_grad_enabled()
        assert torch.get_num_threads() == 2 and torch.equal(before_rng, torch.get_rng_state())
    finally:
        torch.set_num_threads(before_threads)


def test_invalid_parent_admission_rejects_before_numerical_import(aligned, parents, monkeypatch):
    import builtins
    original_import = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name.split(".")[0] in ("torch", "numpy", "transformers"):
            pytest.fail("invalid handoff must not import numerical dependencies")
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded)
    pins = deepcopy(parents["file_pins"])
    pins["initialization_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        subject.load_aligned_decoder(aligned[1], expected_file_pins=pins,
                                     expected_donor_pins=parents["donor_pins"])


@pytest.mark.parametrize("field", sorted(subject.FLAGS))
def test_current_flags_cannot_be_forged(aligned, parents, field):
    checkpoint = deepcopy(aligned[1])
    checkpoint[field] = not checkpoint[field]
    with pytest.raises(ValueError):
        inspect(checkpoint, parents)


@pytest.mark.parametrize("field", ("model_state_sha256", "tensor_inventory_sha256", "handoff_sha256",
                                   "representation_id", "source_profile_id", "architecture", "schema"))
def test_generation_identities_and_digests_are_checked(aligned, parents, field):
    checkpoint = deepcopy(aligned[1])
    checkpoint[field] = "0" * 64
    with pytest.raises(ValueError):
        inspect(checkpoint, parents)


@pytest.mark.parametrize("field", ("initialization_sha256", "bridge_checkpoint_sha256", "plan_sha256", "fit_report_sha256"))
def test_every_external_parent_pin_is_required(aligned, parents, field):
    pins = deepcopy(parents["file_pins"])
    pins[field] = "0" * 64
    with pytest.raises(ValueError):
        subject.load_aligned_decoder(aligned[1], expected_file_pins=pins, expected_donor_pins=parents["donor_pins"])


@pytest.mark.parametrize("field", sorted(reuse_fixture.subject.PIN_FIELDS))
def test_every_external_donor_pin_is_required(aligned, parents, field):
    pins = deepcopy(parents["donor_pins"])
    pins[field] = "0" * 64
    with pytest.raises(ValueError):
        subject.load_aligned_decoder(aligned[1], expected_file_pins=parents["file_pins"], expected_donor_pins=pins)


@pytest.mark.parametrize("mutation", ("extra_field", "optimizer_state", "optimizer_steps_bool", "optimizer_steps",
                                      "mode_policy", "inventory_origin", "inventory_mode", "handoff_count"))
def test_closed_metadata_and_training_modes_are_checked(aligned, parents, mutation):
    checkpoint = deepcopy(aligned[1])
    if mutation == "extra_field":
        checkpoint["unknown"] = True
    elif mutation == "optimizer_state":
        checkpoint["optimizer"]["state"] = {"moments": [1.]}
    elif mutation == "optimizer_steps_bool":
        checkpoint["optimizer_steps"] = False
    elif mutation == "optimizer_steps":
        checkpoint["optimizer_steps"] = 1
    elif mutation == "mode_policy":
        checkpoint["mode_policy"]["inherited_primary_decoder_frozen"] = False
    elif mutation == "inventory_origin":
        checkpoint["tensor_inventory"][0]["origin"] = "qualified_teacher"
        checkpoint["tensor_inventory_sha256"] = subject.digest(checkpoint["tensor_inventory"])
    elif mutation == "inventory_mode":
        checkpoint["tensor_inventory"][0]["requires_grad"] = False
        checkpoint["tensor_inventory_sha256"] = subject.digest(checkpoint["tensor_inventory"])
    else:
        checkpoint["handoff"]["train_pair_count"] += 1
        checkpoint["handoff_sha256"] = subject.digest(checkpoint["handoff"])
    with pytest.raises(ValueError):
        inspect(checkpoint, parents)


def test_runtime_keeps_independent_output_budgets(aligned, parents):
    model = reload(aligned[1], parents)
    vectors, primary, auxiliary = inputs()
    assert inspect(aligned[1], parents)["primary_max_target_tokens"] == 512
    assert inspect(aligned[1], parents)["auxiliary_max_target_tokens"] == 64
    with pytest.raises(ValueError):
        model(vectors, torch.ones((2, 513), dtype=torch.long), auxiliary)
    with pytest.raises(ValueError):
        model(vectors, primary, torch.ones((2, 65), dtype=torch.long))
