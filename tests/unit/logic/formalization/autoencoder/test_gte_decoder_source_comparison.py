"""Source-only comparison on real private models and synthetic cached inputs."""
from copy import deepcopy
import builtins
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[5]
PATH = ROOT / "ipfs_datasets_py/logic/formalization/autoencoder/gte_decoder_source_comparison.py"


def read_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


subject = read_module("gte_source_comparison_subject", PATH)
aligned_tests = read_module("gte_source_comparison_aligned_fixture", Path(__file__).with_name("test_gte_aligned_interface_training.py"))
torch = pytest.importorskip("torch")


@pytest.fixture(scope="module", autouse=True)
def single_thread():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


@pytest.fixture(scope="module")
def fixture(tmp_path_factory):
    value = aligned_tests.aligned_training_fixture(tmp_path_factory)
    source = subject._helper("gte_decoder_source_evaluation")
    value.evaluations = {
        "empty": source.prepare_source_evaluation(value.initialization, value.empty_plan,
            value.batch, value.replay, expected_donor_pins=value.donor_pins,
            max_primary_rows=1, max_auxiliary_rows=1),
        "partial": source.prepare_source_evaluation(value.initialization, value.plan,
            value.batch, value.replay, expected_donor_pins=value.donor_pins,
            max_primary_rows=1, max_auxiliary_rows=1)}
    trainer = subject._helper("gte_aligned_interface_training")
    arguments = {"initialization": value.initialization, "batch": value.batch, "replay": value.replay,
        "expected_donor_pins": value.donor_pins, "aligned_checkpoint": value.aligned_checkpoint,
        "expected_alignment_file_pins": value.alignment_file_pins, "steps": 1}
    value.trained = trainer.train_decoder_interfaces(value.plan, **arguments)["checkpoint"]
    selected_validation_id = value.evaluations["partial"]["heads"]["primary384"]["rows"][0]["embedding_task_id"]
    task = next(task for task in value.empty_plan["task_manifest"]["tasks"]
                if task["id"] == selected_validation_id)
    receipts = value.receipts_768 + [aligned_tests.native_fixture.receipt(task, index=180)]
    value.full_native_plan = aligned_tests.native_fixture.prepare(value, receipts_768=receipts)
    value.full_trained = trainer.train_decoder_interfaces(value.full_native_plan, **arguments)["checkpoint"]
    value.evaluations["full"] = source.prepare_source_evaluation(value.initialization,
        value.full_native_plan, value.batch, value.replay, expected_donor_pins=value.donor_pins,
        max_primary_rows=1, max_auxiliary_rows=1)
    assert value.evaluations["empty"]["native_ready_row_count"] == 0
    assert value.evaluations["partial"]["native_ready_row_count"] == 1
    assert value.evaluations["full"]["native_ready_row_count"] == 2
    return value


def kwargs(fixture, kind="empty", *, include_models=True):
    arguments = {"initialization": fixture.initialization,
        "native_plan": fixture.empty_plan if kind == "empty" else fixture.full_native_plan if kind == "full" else fixture.plan,
        "batch": fixture.batch, "replay": fixture.replay, "expected_donor_pins": fixture.donor_pins,
        "primary_checkpoint": fixture.primary_checkpoint, "legacy8_checkpoint": fixture.legacy8_checkpoint}
    if include_models and kind != "empty":
        arguments.update(aligned_checkpoint=fixture.aligned_checkpoint,
            expected_alignment_file_pins=fixture.alignment_file_pins,
            trained_checkpoint=fixture.full_trained if kind == "full" else fixture.trained)
    return arguments


def compare(fixture, kind="empty", **changes):
    return subject.compare_source_decoders(fixture.evaluations[kind], **{**kwargs(fixture, kind), **changes})


def inspect(fixture, report, kind="empty", **changes):
    return subject.inspect_source_comparison(report, fixture.evaluations[kind],
        **{**kwargs(fixture, kind), **changes})


@pytest.fixture(scope="module")
def reports(fixture):
    return {kind: compare(fixture, kind) for kind in ("empty", "partial", "full")}


def test_import_is_dependency_free():
    code = """import importlib.util,sys
spec=importlib.util.spec_from_file_location('source_comparison',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
assert not any(name in sys.modules for name in ('torch','numpy','transformers','ipfs_datasets_py'))
"""
    subprocess.run([sys.executable, "-I", "-c", code, str(PATH)], check=True)


def test_empty_native_cache_executes_actual_original_donors_only(fixture, reports):
    report = reports["empty"]
    assert report["schema"] == subject.SCHEMA
    assert report["status"] == "donor_baseline_only_unqualified"
    assert report["native768_inputs_used"] is False
    for head in subject.HEADS:
        original = report["variants"]["original_donor"]["heads"][head]
        assert original["summary"]["evaluated_row_count"] == original["summary"]["selected_row_count"] == 1
        row = original["rows"][0]
        assert row["status"] == "evaluated"
        assert row["generation"]["input_dimension"] == (384 if head == "primary384" else 8)
        selected = fixture.evaluations["empty"]["heads"][head]
        assert row["generation"]["max_new_tokens"] == selected["max_new_tokens"] == (511 if head == "primary384" else 63)
        assert row["input_sha256"] == selected["rows"][0]["generation_input"]["input_sha256"]
        initial = report["variants"]["original_initialization"]["heads"][head]
        assert initial["rows"][0]["status"] == "missing_native"
        assert initial["rows"][0]["generation"] is None
        assert initial["summary"]["missing_native_row_count"] == 1
        for label in ("aligned_initialization", "trained_interfaces"):
            assert report["variants"][label]["available"] is False
            assert report["variants"][label]["heads"][head]["rows"][0]["status"] == "model_unavailable"
    assert inspect(fixture, report)["numerical_execution_authenticated"] is False


def test_partial_native_cache_runs_three_genuine_student_generations_only_where_ready(fixture, reports):
    report = reports["partial"]
    assert report["status"] == "partial_comparison_unqualified"
    assert report["native768_inputs_used"] is True
    for label in subject.VARIANTS[1:]:
        value = report["variants"][label]
        assert value["available"] is True
        missing = value["heads"]["primary384"]
        assert missing["rows"][0]["status"] == "missing_native"
        assert missing["summary"]["coverage_fraction"] == 0
        assert missing["summary"]["exact_match_rate_on_evaluated_rows"] is None
        ready = value["heads"]["legacy8"]
        assert ready["summary"]["coverage_fraction"] == 1
        assert ready["summary"]["complete_cohort_evaluated"] is True
        assert ready["rows"][0]["generation"]["variant"] == "student768"
        assert ready["rows"][0]["generation"]["input_dimension"] == 768
    identities = report["model_identities"]
    assert len({identities[label]["legacy8"] for label in subject.VARIANTS[1:]}) == 3
    assert identities["trained_interfaces"]["legacy8"] == fixture.trained["representation_id"]
    assert fixture.trained["optimizer_steps"] == 1
    assert inspect(fixture, report, "partial")["scoring_reconstructed"] is True


def test_validation_receipt_makes_complete_comparison_without_quality_or_authority(fixture, reports):
    report = reports["full"]
    assert report["status"] == "complete_comparison_unqualified"
    for label in subject.VARIANTS:
        assert report["variants"][label]["available"] is True
        for head in subject.HEADS:
            summary = report["variants"][label]["heads"][head]["summary"]
            assert summary["selected_row_count"] == summary["evaluated_row_count"] == 1
            assert summary["coverage_fraction"] == 1
            assert summary["complete_cohort_evaluated"] is True
    assert all(report[key] is False for key in subject.FALSE_FLAGS)
    assert all(report[key] is True for key in subject.TRUE_FLAGS)
    assert report["optimizer_created"] is False and report["optimizer_steps"] == 0
    assert inspect(fixture, report, "full")["status"] == "complete_comparison_unqualified"
    for head in subject.HEADS:
        assert report["variants"]["original_donor"]["heads"][head] == reports["empty"]["variants"]["original_donor"]["heads"][head]


def test_original_donors_match_independent_private_autoregressive_runs(fixture, reports):
    preserved = subject._helper("gte_decoder_transfer_replay")
    generation = subject._helper("gte_decoder_source_generation")
    primary = preserved._original_primary_model(torch, fixture.primary_checkpoint)
    legacy = subject._helper("gte_legacy8_decoder_donor").load_private_legacy8_decoder_snapshot(
        fixture.initialization["legacy8"], expected_source_checkpoint_sha256=fixture.donor_pins["legacy8_checkpoint_sha256"],
        expected_source_model_state_sha256=fixture.donor_pins["legacy8_weights_sha256"])["model"]
    for head, model in (("primary384", primary), ("legacy8", legacy)):
        selected = fixture.evaluations["empty"]["heads"][head]
        actual = generation.generate_source_only(model, variant="donor384" if head == "primary384" else "legacy8",
            head=head, input_vector=selected["rows"][0]["generation_input"]["input_vector"],
            max_new_tokens=selected["max_new_tokens"], inherited_max_target_tokens=selected["inherited_max_target_tokens"])
        assert actual == reports["empty"]["variants"]["original_donor"]["heads"][head]["rows"][0]["generation"]


def test_references_do_not_enter_generation_and_private_state_stays_unchanged(fixture, monkeypatch):
    calls = []
    helper = subject._helper
    originals = deepcopy((fixture.evaluations["partial"], kwargs(fixture, "partial")))
    models = []

    def dependencies(name):
        module = helper(name)
        if name == "gte_decoder_source_generation":
            operation = module.generate_source_only

            def observed(model, **arguments):
                assert set(arguments) == {"variant", "head", "input_vector", "max_new_tokens", "inherited_max_target_tokens"}
                assert type(arguments["input_vector"]) is list
                assert not any("reference" in key or "source_text" in key or "target" in key and key != "inherited_max_target_tokens"
                               for key in arguments)
                before = {name: value.detach().clone() for name, value in model.state_dict().items()}
                pointers = {name: value.untyped_storage().data_ptr() for name, value in model.named_parameters()}
                result = operation(model, **arguments)
                assert all(torch.equal(value, model.state_dict()[name]) for name, value in before.items())
                assert pointers == {name: value.untyped_storage().data_ptr() for name, value in model.named_parameters()}
                assert all(parameter.grad is None for parameter in model.parameters())
                calls.append(deepcopy(arguments))
                models.append(model)
                return result

            module.generate_source_only = observed
        return module

    def forbidden_optimizer(*args, **kwargs):
        raise AssertionError("source comparison created an optimizer")

    monkeypatch.setattr(subject, "_helper", dependencies)
    monkeypatch.setattr(torch.optim, "AdamW", forbidden_optimizer)
    rng, previous_threads = torch.get_rng_state().clone(), torch.get_num_threads()
    try:
        torch.set_num_threads(2)
        report = compare(fixture, "partial")
        assert torch.get_num_threads() == 2
    finally:
        torch.set_num_threads(previous_threads)
    assert torch.equal(rng, torch.get_rng_state())
    assert originals == (fixture.evaluations["partial"], kwargs(fixture, "partial"))
    assert len(calls) == 5
    assert [call["variant"] for call in calls].count("student768") == 3
    assert all(call["input_vector"] == fixture.evaluations["partial"]["heads"][call["head"]]["rows"][0][
        "native_generation_input" if call["variant"] == "student768" else "generation_input"]["input_vector"] for call in calls)
    pointers = [parameter.untyped_storage().data_ptr() for model in models for parameter in model.parameters()]
    assert len(set(pointers)) == len(pointers)
    assert report["private_storage_disjoint"] is True


def test_exact_numerical_rerun_reproduces_saved_report(fixture, reports, tmp_path):
    path = tmp_path / "comparison.json"
    path.write_text(json.dumps(reports["partial"]))
    saved = json.loads(path.read_text())
    rerun = compare(fixture, "partial")
    assert rerun == saved
    assert subject.digest(rerun) == subject.digest(saved)


def test_invalid_generations_remain_in_every_evaluated_denominator(fixture, reports):
    for report in reports.values():
        for variant in report["variants"].values():
            for head in variant["heads"].values():
                summary = head["summary"]
                rows = [row for row in head["rows"] if row["status"] == "evaluated"]
                assert summary["evaluated_row_count"] == len(rows)
                assert summary["syntax_valid_count"] + summary["invalid_generation_count"] == len(rows)
                assert summary["terminated_count"] + summary["truncated_count"] == len(rows)
                assert summary["exact_match_rate_on_selected_rows"] == summary["exact_target_match_count"] / summary["selected_row_count"]
                for row in rows:
                    assert row["score"]["invalid_generation"] is (not row["score"]["syntax_valid"])
                    if row["score"]["invalid_generation"]:
                        assert row["score"]["exact_target_match"] is False


@pytest.mark.parametrize("mutation", ["plan", "donor", "primary", "legacy", "alignment", "trained_without_start"])
def test_bad_model_and_plan_admission_fails_before_numerical_import(fixture, monkeypatch, mutation):
    evaluation = deepcopy(fixture.evaluations["partial"])
    arguments = deepcopy(kwargs(fixture, "partial"))
    if mutation == "plan": evaluation["plan_sha256"] = "a" * 64
    elif mutation == "donor": arguments["expected_donor_pins"]["teacher384_checkpoint_sha256"] = "a" * 64
    elif mutation == "primary": arguments["primary_checkpoint"]["model_state"]["output.bias"][0] += 1.
    elif mutation == "legacy": arguments["legacy8_checkpoint"]["model_state"]["output.bias"][0] += 1.
    elif mutation == "alignment": arguments["expected_alignment_file_pins"]["fit_report_sha256"] = "a" * 64
    else:
        arguments["aligned_checkpoint"] = None
        arguments["expected_alignment_file_pins"] = None
    original = builtins.__import__

    def admitted(name, *args, **kwargs):
        assert name.split(".")[0] not in ("torch", "numpy", "transformers"), name
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", admitted)
    with pytest.raises(ValueError):
        subject.compare_source_decoders(evaluation, **arguments)


def test_valid_native_plan_with_different_asset_manifest_cannot_use_aligned_boundary(fixture, monkeypatch):
    receipts = deepcopy(fixture.receipts_768)
    for receipt in receipts:
        receipt["asset_manifest_sha256"] = "c" * 64
    native = aligned_tests.native_fixture.prepare(fixture, receipts_768=receipts,
        expected_asset_manifest_sha256="c" * 64)
    source = subject._helper("gte_decoder_source_evaluation")
    evaluation = source.prepare_source_evaluation(fixture.initialization, native, fixture.batch,
        fixture.replay, expected_donor_pins=fixture.donor_pins, max_primary_rows=1, max_auxiliary_rows=1)
    source.inspect_source_evaluation(evaluation, fixture.initialization, native, fixture.batch,
        fixture.replay, expected_donor_pins=fixture.donor_pins)
    assert native["asset_manifest_sha256"] == "c" * 64
    assert fixture.aligned_checkpoint["plan"]["asset_manifest_sha256"] == "b" * 64
    arguments = {**kwargs(fixture, "partial"), "native_plan": native, "trained_checkpoint": None}
    original = builtins.__import__

    def admitted(name, *args, **kwargs):
        assert name.split(".")[0] not in ("torch", "numpy", "transformers"), name
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", admitted)
    with pytest.raises(ValueError, match="asset"):
        subject.compare_source_decoders(evaluation, **arguments)


@pytest.mark.parametrize("mutation", ["extra", "authority", "qualification", "optimizer", "variants",
    "rows", "summary", "row_id", "reference", "score", "availability", "input", "native_status",
    "numerical_input", "model_state"])
def test_saved_report_inspection_rejects_accounting_scoring_and_binding_tampering(fixture, reports, monkeypatch, mutation):
    changed = deepcopy(reports["partial"])
    head = changed["variants"]["original_donor"]["heads"]["primary384"]
    row = head["rows"][0]
    if mutation == "extra": changed["unknown"] = True
    elif mutation == "authority": changed["proof_authority"] = True
    elif mutation == "qualification": changed["teacher_qualified"] = True
    elif mutation == "optimizer": changed["optimizer_steps"] = True
    elif mutation == "variants": del changed["variants"]["trained_interfaces"]
    elif mutation == "rows": head["rows"] = []
    elif mutation == "summary": head["summary"]["evaluated_row_count"] = 0
    elif mutation == "row_id": row["id"] = "foreign-source"
    elif mutation == "reference": row["reference_sha256"] = "a" * 64
    elif mutation == "score": row["score"]["token_edit_distance"] += 1
    elif mutation == "availability": changed["variants"]["original_initialization"]["available"] = False
    elif mutation == "input":
        row["generation"]["input_vector_sha256"] = "a" * 64
        for step in row["generation"]["steps"]: step["input_vector_sha256"] = "a" * 64
    elif mutation == "native_status": changed["variants"]["original_initialization"]["heads"]["primary384"]["rows"][0]["status"] = "model_unavailable"
    elif mutation == "numerical_input": row["generation"]["numerical_input_sha256"] = "a" * 64
    else:
        row["generation"]["model_state_sha256_before"] = "a" * 64
        row["generation"]["model_state_sha256_after"] = "a" * 64
    original = builtins.__import__

    def admitted(name, *args, **kwargs):
        assert name.split(".")[0] not in ("torch", "numpy", "transformers"), name
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", admitted)
    with pytest.raises(ValueError):
        inspect(fixture, changed, "partial")


def test_structural_inspection_does_not_authenticate_forged_logit_digest(fixture, reports):
    changed = deepcopy(reports["empty"])
    changed["variants"]["original_donor"]["heads"]["primary384"]["rows"][0]["generation"]["steps"][0]["raw_logits_sha256"] = "a" * 64
    assert inspect(fixture, changed)["numerical_execution_authenticated"] is False
    assert changed != compare(fixture)


def test_saved_inspection_stays_dependency_free(fixture, reports, tmp_path):
    path = tmp_path / "payload.json"
    path.write_text(json.dumps({"report": reports["empty"], "evaluation": fixture.evaluations["empty"], **kwargs(fixture)}))
    code = """import builtins,importlib.util,json,sys
spec=importlib.util.spec_from_file_location('source_comparison',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
original=builtins.__import__
def admitted(name,*args,**kwargs):
    assert name.split('.')[0] not in ('torch','numpy','transformers'), name
    return original(name,*args,**kwargs)
builtins.__import__=admitted
receipt=module.inspect_source_comparison(**json.load(open(sys.argv[2])))
assert receipt['scoring_reconstructed'] is True
assert receipt['numerical_execution_authenticated'] is False
assert not any(name in sys.modules for name in ('torch','numpy','transformers','ipfs_datasets_py'))
"""
    subprocess.run([sys.executable, "-I", "-c", code, str(PATH), str(path)], check=True)
