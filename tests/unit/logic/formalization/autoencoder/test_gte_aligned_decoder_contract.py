"""Fitted-boundary handoff admission using synthetic, independently split rows."""
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
PATH = ROOT / "ipfs_datasets_py/logic/formalization/autoencoder/gte_aligned_decoder_contract.py"


def read_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


subject = read_module("gte_aligned_contract_test_subject", PATH)


def handoff_fixture(tmp_path_factory, *, validation=True, candidates=None, initialization=None):
    """Build strict synthetic donor/plan/fit objects for this and CLI tests."""
    torch = pytest.importorskip("torch")
    old_threads = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        if initialization is None:
            fixture = read_module("gte_aligned_contract_reuse_fixture",
                                  Path(__file__).with_name("test_gte_decoder_reuse.py"))
            donors = fixture.donors.__wrapped__(tmp_path_factory)
            _, initialization = fixture.initialized.__wrapped__(donors)
        else:
            initialization = deepcopy(initialization)
        cli = read_module("gte_aligned_contract_fit_cli", ROOT / "scripts/ops/autoencoder/prepare_gte_alignment.py")
        corpus = cli._helper("gte_multilingual_corpus")
        rows = []
        splits = ("train", "train", "validation") if validation else ("train", "train")
        for index, split in enumerate(splits):
            vector = [0.] * 384
            vector[index] = 1.
            rows.append({"id": "aligned-row" + str(index), "domain_id": "legal_ir",
                "document_id": "aligned-document" + str(index), "group_id": "aligned-group" + str(index),
                "split": split, "source_text": "Independent synthetic original " + str(index),
                "embedding": vector, "reference_target": {"synthetic": index}, "target_origin": "authored",
                "source_language": "en", "evaluation_role": "development"})
        audit = corpus._AUDIT.audit_transfer_rows(rows, dimension=384,
            vector_space_id=subject._BRIDGE.SOURCE_REPRESENTATION_ID)
        tasks = corpus.prepare_embedding_tasks(rows, audit)
        receipts = []
        for index, task in enumerate(tasks["tasks"]):
            vector = [0.] * 768
            vector[index] = 1.
            receipts.append({"schema": corpus.RECEIPT_SCHEMA, "id": task["id"],
                "source_sha256": task["source_sha256"], "profile_id": corpus.PROFILE_ID,
                "dimension": 768, "embedding": vector, "token_count_including_special_tokens": 4,
                "token_input_sha256": "a" * 64, "truncated": False, "normalized": True,
                "asset_manifest_sha256": "b" * 64})
        pairs = cli._helper("gte_bridge_pairs").prepare_bridge_pairs(rows, audit, tasks, receipts)
        candidates = candidates if candidates is not None else [.001, .01, .1] if validation else [.01]
        plan = subject._ALIGNMENT.prepare_alignment_plan(pairs, regularization_candidates=candidates)
        selection, state = cli._fit_candidates(plan)
        pins = initialization["donor_pins"]
        bridge = cli._pack_bridge(state, config={"seed": 113, "domain_id": "legal_ir"}, teacher={
            "teacher_runtime_id": "legal_ir:source_training_v2",
            "source_representation_id": subject._BRIDGE.SOURCE_REPRESENTATION_ID,
            "checkpoint_sha256": pins["teacher384_checkpoint_sha256"],
            "input_transform": initialization["primary"]["input_transform"]})
        # Original checkpoint bytes deliberately use a different admissible
        # JSON serialization from CLI output; object inspection cannot infer it.
        initialization_raw = json.dumps(initialization, indent=1, ensure_ascii=False).encode()
        file_pins = {"initialization_sha256": hashlib.sha256(initialization_raw).hexdigest(),
            "bridge_checkpoint_sha256": hashlib.sha256(cli._raw(bridge)).hexdigest(),
            "plan_sha256": hashlib.sha256(cli._raw(plan)).hexdigest()}
        identity = {"initialization_sha256": file_pins["initialization_sha256"],
            "plan_sha256": file_pins["plan_sha256"], "bridge_weights_sha256": bridge["weights_sha256"]}
        report = {"schema": "gte-affine-alignment-fit/v1", **identity,
            "bridge_checkpoint_sha256": file_pins["bridge_checkpoint_sha256"],
            "initialization_representation_id": initialization["representation_id"],
            "aligned_representation_id": "legal_ir:aligned_dual_decoder_768:" + cli._digest(identity),
            "donor_pins": deepcopy(pins), "source_profile_id": pairs["student_profile_id"],
            "train_rows_sha256": plan["train_rows_sha256"], "validation_rows_sha256": plan["validation_rows_sha256"],
            "plan_content_sha256": plan["plan_sha256"], "pair_coverage_status": pairs["status"],
            "missing_eligible_pair_receipts": pairs["counts"]["missing_eligible_pair_receipts"],
            "selection": selection, **{name: True for name in subject._TRUE_REPORT},
            **{name: False for name in subject._FALSE_REPORT}, "optimizer_steps": 0}
        file_pins["fit_report_sha256"] = hashlib.sha256(cli._raw(report)).hexdigest()
        return SimpleNamespace(initialization=initialization, bridge=bridge, plan=plan, fit_report=report,
            file_pins=file_pins, donor_pins=deepcopy(pins), initialization_raw=initialization_raw)
    finally:
        torch.set_num_threads(old_threads)


@pytest.fixture(scope="module")
def handoff(tmp_path_factory):
    return handoff_fixture(tmp_path_factory)


def inspect(fixture, **changes):
    args = {"initialization": fixture.initialization, "bridge": fixture.bridge,
        "plan": fixture.plan, "fit_report": fixture.fit_report,
        "expected_file_pins": fixture.file_pins, "expected_donor_pins": fixture.donor_pins}
    args.update(changes)
    return subject.inspect_alignment_handoff(**args)


def test_import_is_standard_library_only():
    code = """import importlib.util,sys
spec=importlib.util.spec_from_file_location('isolated_contract',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
assert not any(name in sys.modules for name in ('torch','numpy','transformers','ipfs_datasets_py'))
"""
    subprocess.run([sys.executable, "-I", "-c", code, str(PATH)], check=True)


def test_complete_handoff_inspection_is_standard_library_only(handoff, tmp_path):
    payload = {"initialization": handoff.initialization, "bridge": handoff.bridge,
        "plan": handoff.plan, "fit_report": handoff.fit_report,
        "expected_file_pins": handoff.file_pins, "expected_donor_pins": handoff.donor_pins}
    path = tmp_path / "handoff.json"
    path.write_text(json.dumps(payload))
    code = """import importlib.util,json,sys
spec=importlib.util.spec_from_file_location('isolated_handoff',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
report=module.inspect_alignment_handoff(**json.load(open(sys.argv[2])))
assert report['primary_input_boundary_fitted'] is True
assert report['teacher_qualified'] is False
assert not any(name in sys.modules for name in ('torch','numpy','transformers','ipfs_datasets_py'))
"""
    subprocess.run([sys.executable, "-I", "-c", code, str(PATH), str(path)], check=True)


def test_ready_handoff_retains_external_bytes_and_remaining_alignment_scope(handoff):
    report = inspect(handoff)
    assert report["schema"] == subject.SCHEMA
    assert report["status"] == "fitted_unqualified"
    assert report["file_pins"] == handoff.file_pins
    assert handoff.file_pins["initialization_sha256"] != subject._file_digest_binding(handoff.initialization)
    assert report["initialization_representation_id"] != report["aligned_representation_id"]
    assert report["primary_input_boundary_fitted"] is True
    assert report["boundary_alignment_required"] is True
    assert report["auxiliary_connector_fitted"] is False
    assert report["train_pair_count"] == 2 and report["validation_pair_count"] == 1
    assert report["candidate_count"] == 3
    assert report["pair_coverage_authenticated"] is False
    for name in ("teacher_qualified", "source_fidelity_qualified", "proof_authority", "distillation_executed",
                 "encoder_numerics_verified", "student_decoder_gradient_training_executed"):
        assert report[name] is False


def test_inspection_and_receipt_leave_all_inputs_private(handoff):
    before = deepcopy(handoff.__dict__)
    result = inspect(handoff)
    result["file_pins"]["initialization_sha256"] = "0" * 64
    result["donor_pins"]["teacher384_checkpoint_sha256"] = "0" * 64
    assert handoff.__dict__ == before


@pytest.mark.parametrize("field", sorted(subject.FILE_PIN_FIELDS))
def test_external_file_pins_are_closed_full_sha256(handoff, field):
    pins = deepcopy(handoff.file_pins)
    pins[field] = "not a full digest"
    with pytest.raises(ValueError, match="SHA256"):
        inspect(handoff, expected_file_pins=pins)
    pins = deepcopy(handoff.file_pins)
    pins.pop(field)
    with pytest.raises(ValueError, match="closed"):
        inspect(handoff, expected_file_pins=pins)


@pytest.mark.parametrize("field", ("initialization_sha256", "bridge_checkpoint_sha256", "plan_sha256"))
def test_report_cannot_change_external_file_bindings(handoff, field):
    pins = {**handoff.file_pins, field: "0" * 64}
    with pytest.raises(ValueError, match="external file binding"):
        inspect(handoff, expected_file_pins=pins)


def test_fit_report_file_pin_is_explicit_external_admission(handoff):
    # The object-level inspector cannot authenticate arbitrary original bytes.
    pin = {**handoff.file_pins, "fit_report_sha256": "f" * 64}
    assert inspect(handoff, expected_file_pins=pin)["file_pins"] == pin


@pytest.mark.parametrize("field", sorted(subject._TRUE_REPORT | subject._FALSE_REPORT))
def test_fit_report_claims_must_be_exact_booleans(handoff, field):
    report = deepcopy(handoff.fit_report)
    report[field] = int(report[field])
    with pytest.raises(ValueError):
        inspect(handoff, fit_report=report)


@pytest.mark.parametrize("change", ["extra", "schema", "identity", "donor", "source_profile", "train_rows",
    "validation_rows", "plan_content", "weights", "missing_count", "negative_missing", "missing_bool",
    "coverage", "optimizer_bool", "optimizer_step"])
def test_fit_report_binding_and_policy_tampering_rejected(handoff, change):
    report = deepcopy(handoff.fit_report)
    if change == "extra": report["student_qualified"] = True
    if change == "schema": report["schema"] = "unrecognized"
    if change == "identity": report["aligned_representation_id"] = handoff.initialization["representation_id"]
    if change == "donor": report["donor_pins"]["legacy8_checkpoint_sha256"] = "0" * 64
    if change == "source_profile": report["source_profile_id"] = "different-encoder"
    if change == "train_rows": report["train_rows_sha256"] = "0" * 64
    if change == "validation_rows": report["validation_rows_sha256"] = "0" * 64
    if change == "plan_content": report["plan_content_sha256"] = "0" * 64
    if change == "weights": report["bridge_weights_sha256"] = "0" * 64
    if change == "missing_count": report["missing_eligible_pair_receipts"] += 1
    if change == "negative_missing": report["missing_eligible_pair_receipts"] = -1
    if change == "missing_bool": report["missing_eligible_pair_receipts"] = False
    if change == "coverage": report["pair_coverage_status"] = "unavailable"
    if change == "optimizer_bool": report["optimizer_steps"] = False
    if change == "optimizer_step": report["optimizer_steps"] = 1
    with pytest.raises(ValueError):
        inspect(handoff, fit_report=report)


@pytest.mark.parametrize("change", ["extra", "architecture", "input_dimension", "output_bool", "seed_bool",
    "domain", "teacher", "source", "student", "transform", "derived_identity", "weight_digest",
    "shape", "missing_bias", "rounding", "nan", "overflow", "bool", "authority"])
def test_fitted_bridge_tampering_is_rejected_without_torch(handoff, change):
    bridge = deepcopy(handoff.bridge)
    if change == "extra": bridge["training_complete"] = True
    if change == "architecture": bridge["architecture"] = "native-768"
    if change == "input_dimension": bridge["input_dimension"] = 384
    if change == "output_bool": bridge["output_dimension"] = True
    if change == "seed_bool": bridge["seed"] = False
    if change == "domain": bridge["domain_id"] = "intent_ir"
    if change == "teacher": bridge["teacher_checkpoint_sha256"] = "0" * 64
    if change == "source": bridge["source_representation_id"] = "first-384-coordinates"
    if change == "student": bridge["student_representation_id"] = "unsupported"
    if change == "transform": bridge["input_transform"]["scale"] *= 2.
    if change == "derived_identity": bridge["adapted_representation_id"] = bridge["source_representation_id"]
    if change == "weight_digest": bridge["weights_sha256"] = "0" * 64
    if change == "shape": bridge["model_state"]["weight"][0].pop()
    if change == "missing_bias": bridge["model_state"].pop("bias")
    if change == "rounding": bridge["model_state"]["weight"][0][0] = 1. / 3.
    if change == "nan": bridge["model_state"]["weight"][0][0] = float("nan")
    if change == "overflow": bridge["model_state"]["weight"][0][0] = 1e100
    if change == "bool": bridge["model_state"]["weight"][0][0] = False
    if change == "authority": bridge["proof_authority"] = True
    with pytest.raises(ValueError):
        inspect(handoff, bridge=bridge)


@pytest.mark.parametrize("change", ["extra", "schema", "grid_order", "missing_candidate", "duplicate_candidate",
    "selected_weights", "selected_lambda", "train_count", "validation_count", "candidate_count_bool",
    "refit", "validation_fit", "test_used", "steps", "policy", "tie_policy", "mean_objective",
    "bad_train_metrics", "bad_validation_metrics", "bad_diagnostics", "objective"])
def test_candidate_selection_and_reporting_tampering_rejected(handoff, change):
    report = deepcopy(handoff.fit_report)
    selection = report["selection"]
    candidate = selection["candidates"][0]
    if change == "extra": selection["teacher_qualified"] = True
    if change == "schema": selection["schema"] = "unrecognized"
    if change == "grid_order": selection["candidates"].reverse()
    if change == "missing_candidate": selection["candidates"].pop()
    if change == "duplicate_candidate": selection["candidates"][1] = deepcopy(candidate)
    if change == "selected_weights": selection["selected_weights_sha256"] = "0" * 64
    if change == "selected_lambda": selection["selected_regularization"] = 100.
    if change == "train_count": selection["train_rows"] += 1
    if change == "validation_count": selection["validation_rows"] += 1
    if change == "candidate_count_bool": selection["candidate_count"] = True
    if change == "refit": selection["refit_with_validation"] = True
    if change == "validation_fit": selection["validation_used_for_fit"] = True
    if change == "test_used": selection["test_or_canary_used"] = True
    if change == "steps": selection["optimizer_steps"] = 1
    if change == "policy": selection["selection_policy"] = "training_mse"
    if change == "tie_policy": selection["tie_break_policy"] = "larger_regularization"
    if change == "mean_objective": candidate["objective_residual_reduction"] = "mean"
    if change == "bad_train_metrics": candidate["train_metrics"]["rows"] = 1
    if change == "bad_validation_metrics": candidate["validation_metrics"]["mean_squared_l2"] = float("nan")
    if change == "bad_diagnostics": candidate["diagnostics"]["solver_numerics_passed"] = False
    if change == "objective":
        selected = next(row for row in selection["candidates"] if row["regularization"] == selection["selected_regularization"])
        selected["exported_training_objective"] += 1.
    with pytest.raises(ValueError):
        inspect(handoff, fit_report=report)


def test_report_cannot_select_a_larger_validation_error(handoff):
    report = deepcopy(handoff.fit_report)
    candidates = report["selection"]["candidates"]
    # Make a nonselected candidate win while retaining internally consistent
    # metric summaries. The weights report still selects the old bridge.
    altered = next(row for row in candidates if row["regularization"] != report["selection"]["selected_regularization"])
    metrics = altered["validation_metrics"]
    metrics.update({"coordinate_mse": 0., "mean_squared_l2": 0., "min_squared_l2": 0., "max_squared_l2": 0.})
    with pytest.raises(ValueError, match="validation winner"):
        inspect(handoff, fit_report=report)


def test_single_train_only_candidate_is_a_valid_explicit_policy(handoff, tmp_path_factory):
    fixture = handoff_fixture(tmp_path_factory, validation=False, initialization=handoff.initialization)
    result = inspect(fixture)
    assert result["candidate_count"] == 1 and result["validation_pair_count"] == 0
    assert fixture.fit_report["selection"]["selection_policy"] == "fixed_candidate_no_validation"
    assert fixture.fit_report["selection"]["candidates"][0]["validation_metrics"]["status"] == "unavailable"


def test_unavailable_plan_is_not_a_fitted_handoff(handoff):
    plan = deepcopy(handoff.plan)
    plan["fit_ready"] = False
    with pytest.raises(ValueError):
        inspect(handoff, plan=plan)
    with pytest.raises(ValueError):
        inspect(handoff, bridge=None)
    with pytest.raises(ValueError):
        inspect(handoff, fit_report=None)


def test_original_nested_decoder_and_external_donor_admission_remain_required(handoff):
    changed = deepcopy(handoff.initialization)
    changed["primary"]["model_state"]["output.bias"][0] += 1.
    with pytest.raises(ValueError):
        inspect(handoff, initialization=changed)
    pins = {**handoff.donor_pins, "legacy8_codec_sha256": "0" * 64}
    with pytest.raises(ValueError):
        inspect(handoff, expected_donor_pins=pins)


def test_partial_coverage_is_retained_without_inventing_complete_geometry(handoff):
    report = deepcopy(handoff.fit_report)
    report["pair_coverage_status"] = "partial"
    result = inspect(handoff, fit_report=report)
    assert result["pair_coverage_status"] == "partial"
    assert result["pair_coverage_authenticated"] is False
