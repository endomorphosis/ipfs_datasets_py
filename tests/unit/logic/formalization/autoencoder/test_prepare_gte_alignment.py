"""Alignment CLI admission and publication checks, with synthetic vector rows.

The numerical helper has separate mathematical tests. These checks exercise
closed inputs, train/validation isolation, lazy imports and immutable evidence.
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


REPOSITORY = Path(__file__).resolve().parents[5]
PATH = REPOSITORY / "scripts/ops/autoencoder/prepare_gte_alignment.py"
SPEC = importlib.util.spec_from_file_location("gte_alignment_preparation_cli_test", PATH)
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)


def _write(path, value):
    raw = subject._raw(value)
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def test_cli_import_does_not_load_numerical_libraries():
    code = """import importlib.util,sys
spec=importlib.util.spec_from_file_location('isolated_cli',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
assert not any(name in sys.modules for name in ('torch','transformers','numpy'))
"""
    subprocess.run([sys.executable, "-I", "-c", code, str(PATH)], check=True)


def _guard_numerical_imports(monkeypatch):
    import builtins
    real_import = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name.split(".")[0] in ("torch", "transformers", "numpy", "sentence_transformers"):
            pytest.fail("preparation and unavailable fits must stay dependency-free")
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded)


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    """Keep corpus admission real; donor admission is independently tested."""
    real_helper = subject._helper
    reader = real_helper("gte_worker_contract")
    corpus = real_helper("gte_multilingual_corpus")
    source_id = ("thenlper/gte-small@17e1f347d17fe144873b1201da91788898c639cd:"
                 "d384:pool=mean:norm=l2:precision=float32:input_policy=exact_source_no_truncation")
    rows = []
    for index, split in enumerate(("train", "train", "validation")):
        vector = [0.] * 384
        vector[index] = 1.
        rows.append({"id": "row" + str(index), "domain_id": "legal_ir",
            "document_id": "document" + str(index), "group_id": "group" + str(index),
            "split": split, "source_text": "separate original source " + str(index),
            "embedding": vector, "reference_target": {"reference": index},
            "target_origin": "authored", "source_language": "en",
            "evaluation_role": "development"})
    audit = corpus._AUDIT.audit_transfer_rows(rows, dimension=384, vector_space_id=source_id)
    tasks = corpus.prepare_embedding_tasks(rows, audit)
    teacher_path = tmp_path / "teacher_checkpoint.json"
    teacher_sha = _write(teacher_path, {"schema": "synthetic-donor-admission-stub/v1"})
    pins = {"teacher384_checkpoint_sha256": teacher_sha,
            "teacher384_weights_sha256": "1" * 64, "teacher384_codec_sha256": "2" * 64,
            "legacy8_checkpoint_sha256": "3" * 64, "legacy8_weights_sha256": "4" * 64,
            "legacy8_codec_sha256": "5" * 64}
    transform = {"mode": "none", "mean": [0.] * 384, "scale": 1., "origin": "training_only"}
    digest = lambda value: hashlib.sha256(json.dumps(value, sort_keys=True,
        separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    teacher = {"schema": "synthetic-teacher-binding/v1",
        "teacher_runtime_id": "legal_ir:source_training_v2", "source_representation_id": source_id,
        "teacher_checkpoint_sha256": teacher_sha, "checkpoint_sha256": teacher_sha,
        "weights_sha256": pins["teacher384_weights_sha256"],
        "codec_sha256": pins["teacher384_codec_sha256"], "input_transform": transform,
        "input_transform_sha256": digest(transform), "sources": [], "teacher_qualified": False}
    initial = {"schema": "synthetic-initialization-admission-stub/v1", "donor_pins": pins,
        "representation_id": "synthetic_initialized_unaligned",
        "primary": {"donor": {"checkpoint_sha256": teacher_sha,
             "weights_sha256": pins["teacher384_weights_sha256"],
             "codec_sha256": pins["teacher384_codec_sha256"]},
             "input_transform": transform, "input_transform_sha256": digest(transform),
             "codec_sha256": pins["teacher384_codec_sha256"], "model_state": {},
             "freeze_inherited": True, "weights_sha256": "6" * 64},
        "legacy8": {"schema": "synthetic-legacy-port"}, "connector": {},
        "decoder_parameters_random": False, "boundary_alignment_required": True}
    payloads = {"rows_384": rows, "corpus_audit": audit, "tasks": tasks,
                "receipts_768": [], "teacher_checkpoint": {"schema": "synthetic-donor-admission-stub/v1"},
                "initialization": initial, "donor_pins": pins}
    source_root = tmp_path / "donor-source"
    source_root.mkdir()
    config = {"schema": subject.CONFIG_SCHEMA, "workspace_root": str(tmp_path),
              "domain_id": "legal_ir", "max_rows": 4096, "mode": "prepare", "seed": 1729,
              "regularization_candidates": [.001, .01, .1], "max_train_pairs": 4096,
              "max_validation_pairs": 4096, "teacher_repository_root": source_root.name}
    for name, value in payloads.items():
        path = tmp_path / (name + ".json")
        config[name] = {"path": path.name, "sha256": _write(path, value)}
    path = tmp_path / "config.json"
    pin = _write(path, config)
    inspected = {"schema": "synthetic-initialization-inspection/v1",
        "representation_id": initial["representation_id"], "primary_copied_tensor_count": 13,
        "legacy8_copied_tensor_count": 13, "copied_parameter_count": 27142}
    def inspect_initial(bundle, *, expected_donor_pins):
        if expected_donor_pins != pins or bundle != initial:
            raise ValueError("external donor pins differ")
        return deepcopy(inspected)
    reuse = SimpleNamespace(inspect_dual_decoder=inspect_initial, digest=digest)
    teacher_helper = SimpleNamespace(inspect_teacher=lambda *args, **kwargs: deepcopy(teacher))
    monkeypatch.setattr(subject, "_helper", lambda name:
        reuse if name == "gte_decoder_reuse" else teacher_helper if name == "gte_bridge_teacher"
        else reader if name == "gte_worker_contract"
        else real_helper(name))
    return SimpleNamespace(path=path, pin=pin, config=config, payloads=payloads, corpus=corpus,
        teacher=teacher, initial=initial, pins=pins, reuse=reuse, reader=reader,
        output=tmp_path / "output")


def _run(fixture, **overrides):
    kwargs = {"expected_config_sha256": fixture.pin, "output_directory": fixture.output}
    kwargs.update(overrides)
    return subject.run_alignment(fixture.path, **kwargs)


def _repin(fixture):
    fixture.pin = _write(fixture.path, fixture.config)


def _add_receipts(fixture):
    receipts = []
    for index, task in enumerate(fixture.payloads["tasks"]["tasks"]):
        vector = [0.] * 768
        vector[index] = 1.
        receipts.append({"schema": fixture.corpus.RECEIPT_SCHEMA, "id": task["id"],
            "source_sha256": task["source_sha256"], "profile_id": fixture.corpus.PROFILE_ID,
            "dimension": 768, "embedding": vector, "token_count_including_special_tokens": 3,
            "token_input_sha256": "a" * 64, "truncated": False, "normalized": True,
            "asset_manifest_sha256": "b" * 64})
    fixture.payloads["receipts_768"] = receipts
    fixture.config["receipts_768"]["sha256"] = _write(
        fixture.path.parent / "receipts_768.json", receipts)
    _repin(fixture)


@pytest.mark.parametrize("mode", ["prepare", "fit"])
def test_missing_real_receipts_publish_unavailable_without_numerical_imports(inputs, monkeypatch, mode):
    inputs.config["mode"] = mode
    _repin(inputs)
    _guard_numerical_imports(monkeypatch)
    def forbidden_resources(*args, **kwargs):
        pytest.fail("preparation and unavailable fits must not change process resources")
    monkeypatch.setattr(inputs.reader, "configure_cpu_process", forbidden_resources)
    result = _run(inputs)
    assert result["status"] == "unavailable"
    assert result["candidate_fits_executed"] == 0
    assert result["analytic_alignment_fit_executed"] is False
    assert result["training_executed"] is False
    assert result["distillation_executed"] is False
    assert not (inputs.output / "fitted-bridge.json").exists()
    assert not (inputs.output / "fit-report.json").exists()
    manifest = json.loads((inputs.output / "manifest.json").read_text())
    assert manifest["completed"] is True
    assert manifest["status"] == "unavailable"
    plan = json.loads((inputs.output / "plan.json").read_text())
    assert plan["fit_ready"] is False
    assert plan["train_rows"] == plan["validation_rows"] == []
    assert plan["counts"]["missing_eligible_pair_receipts"] == 3
    for entry in manifest["outputs"]:
        raw = (inputs.output / entry["path"]).read_bytes()
        assert len(raw) == entry["bytes"]
        assert hashlib.sha256(raw).hexdigest() == entry["sha256"]


def test_prepare_ready_plan_preserves_splits_and_never_fits(inputs, monkeypatch):
    _add_receipts(inputs)
    _guard_numerical_imports(monkeypatch)
    original = {name: (inputs.path.parent / ref["path"]).read_bytes()
                for name, ref in inputs.config.items() if type(ref) is dict}
    result = _run(inputs)
    assert result["status"] in ("ready", "prepared")
    plan = json.loads((inputs.output / "plan.json").read_text())
    assert plan["fit_ready"] is True
    assert [row["split"] for row in plan["train_rows"]] == ["train", "train"]
    assert [row["split"] for row in plan["validation_rows"]] == ["validation"]
    assert plan["teacher_qualification_required"] is False
    assert plan["training_performed"] is False
    assert not (inputs.output / "fitted-bridge.json").exists()
    for name, raw in original.items():
        assert (inputs.path.parent / inputs.config[name]["path"]).read_bytes() == raw


@pytest.mark.parametrize("change", [
    "extra", "mode", "domain", "max_rows_bool", "seed_bool", "seed_negative",
    "train_limit_bool", "validation_limit_bool", "train_limit_zero", "candidate_bool",
    "candidate_empty", "candidate_duplicate", "candidate_unsorted", "candidate_zero",
    "candidate_tiny", "candidate_huge", "reference_extra", "absolute", "traversal",
    "teacher_absolute", "teacher_traversal",
])
def test_closed_configuration_rejects_unsupported_changes_before_publication(inputs, change):
    config = inputs.config
    if change == "extra": config["allow_semantic_claims"] = True
    if change == "mode": config["mode"] = "distill"
    if change == "domain": config["domain_id"] = "unknown_ir"
    if change == "max_rows_bool": config["max_rows"] = True
    if change == "seed_bool": config["seed"] = True
    if change == "seed_negative": config["seed"] = -1
    if change == "train_limit_bool": config["max_train_pairs"] = True
    if change == "validation_limit_bool": config["max_validation_pairs"] = False
    if change == "train_limit_zero": config["max_train_pairs"] = 0
    if change == "candidate_bool": config["regularization_candidates"] = [True]
    if change == "candidate_empty": config["regularization_candidates"] = []
    if change == "candidate_duplicate": config["regularization_candidates"] = [.01, .01]
    if change == "candidate_unsorted": config["regularization_candidates"] = [.1, .01]
    if change == "candidate_zero": config["regularization_candidates"] = [0]
    if change == "candidate_tiny": config["regularization_candidates"] = [1e-9]
    if change == "candidate_huge": config["regularization_candidates"] = [1e7]
    if change == "reference_extra": config["rows_384"]["schema"] = "extra"
    if change == "absolute": config["rows_384"]["path"] = str(inputs.path.parent / "rows_384.json")
    if change == "traversal": config["rows_384"]["path"] = "../rows_384.json"
    if change == "teacher_absolute": config["teacher_repository_root"] = str(inputs.path.parent / "donor-source")
    if change == "teacher_traversal": config["teacher_repository_root"] = "../donor-source"
    _repin(inputs)
    with pytest.raises(ValueError):
        _run(inputs)
    assert not inputs.output.exists()


def test_config_and_input_content_pins_are_externally_required(inputs):
    with pytest.raises(ValueError, match="SHA256"):
        _run(inputs, expected_config_sha256="0" * 64)
    (inputs.path.parent / "tasks.json").write_bytes(b"{}\n")
    with pytest.raises(ValueError, match="SHA256"):
        _run(inputs)
    assert not inputs.output.exists()


def test_existing_output_is_never_overwritten(inputs):
    inputs.output.mkdir()
    sentinel = inputs.output / "existing-evidence"
    sentinel.write_bytes(b"preserve original evidence")
    with pytest.raises(ValueError, match="fresh"):
        _run(inputs)
    assert sentinel.read_bytes() == b"preserve original evidence"


def test_input_namespace_cannot_be_reused_as_output(inputs):
    with pytest.raises(ValueError):
        _run(inputs, output_directory=inputs.path.parent)
    assert inputs.path.exists()


def test_recomputed_tasks_reject_target_or_source_drift(inputs):
    tasks = deepcopy(inputs.payloads["tasks"])
    tasks["tasks"][0]["source_sha256"] = "f" * 64
    inputs.config["tasks"]["sha256"] = _write(inputs.path.parent / "tasks.json", tasks)
    _repin(inputs)
    with pytest.raises(ValueError, match="tasks_manifest"):
        _run(inputs)
    assert not inputs.output.exists()


def test_external_donor_pins_must_match_initialization(inputs):
    changed = {**inputs.pins, "legacy8_checkpoint_sha256": "e" * 64}
    inputs.config["donor_pins"]["sha256"] = _write(inputs.path.parent / "donor_pins.json", changed)
    _repin(inputs)
    with pytest.raises(ValueError, match="donor"):
        _run(inputs)
    assert not inputs.output.exists()


def test_teacher_transform_must_match_inherited_primary_input(inputs):
    inputs.teacher["input_transform"] = {"mode": "center_rms", "mean": [.1] * 384,
                                          "scale": 2., "origin": "training_only"}
    with pytest.raises(ValueError, match="bindings"):
        _run(inputs)
    assert not inputs.output.exists()


def test_helper_drift_prevents_completion_manifest(inputs, monkeypatch):
    original = subject._file
    calls = {}
    def drifting(reader, path):
        receipt = original(reader, path)
        calls[receipt["path"]] = calls.get(receipt["path"], 0) + 1
        if receipt["path"] == str(PATH) and calls[receipt["path"]] > 1:
            return {**receipt, "sha256": "0" * 64}
        return receipt
    monkeypatch.setattr(subject, "_file", drifting)
    with pytest.raises(ValueError, match="changed during operation"):
        _run(inputs)
    assert not (inputs.output / "manifest.json").exists()


def test_published_output_drift_prevents_completion_manifest(inputs, monkeypatch):
    original = subject._file
    def drifting(reader, path):
        receipt = original(reader, path)
        if Path(receipt["path"]) == inputs.output / "plan.json":
            return {**receipt, "sha256": "0" * 64}
        return receipt
    monkeypatch.setattr(subject, "_file", drifting)
    with pytest.raises(ValueError, match="output changed"):
        _run(inputs)
    assert (inputs.output / "plan.json").is_file()
    assert not (inputs.output / "manifest.json").exists()


def test_input_drift_between_publication_checks_prevents_completion(inputs, monkeypatch):
    original = subject._recheck
    calls = []
    def drifting(reader, references):
        original(reader, references)
        calls.append(True)
        if len(calls) == 1:
            (inputs.path.parent / "tasks.json").write_bytes(b"changed after first stability check")
    monkeypatch.setattr(subject, "_recheck", drifting)
    with pytest.raises(ValueError, match="changed during operation"):
        _run(inputs)
    assert not (inputs.output / "manifest.json").exists()


def test_cli_reports_unavailable_and_invalid_pins(inputs, capsys):
    arguments = ["--config", str(inputs.path), "--expected-config-sha256", inputs.pin,
                 "--output-directory", str(inputs.output)]
    assert subject.main(arguments) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "unavailable"
    arguments[3] = "0" * 64
    assert subject.main(arguments) == 2
    assert json.loads(capsys.readouterr().err)["status"] == "invalid"


def _ready_plan(fixture):
    _add_receipts(fixture)
    pairs = subject._helper("gte_bridge_pairs").prepare_bridge_pairs(
        fixture.payloads["rows_384"], fixture.payloads["corpus_audit"],
        fixture.payloads["tasks"], fixture.payloads["receipts_768"])
    return subject._helper("gte_alignment_contract").prepare_alignment_plan(
        pairs, regularization_candidates=fixture.config["regularization_candidates"])


def _fake_numerics(scores):
    calls = {"fit": [], "score": []}
    def fit(inputs, targets, *, regularization):
        calls["fit"].append((deepcopy(inputs), deepcopy(targets), regularization))
        state = {"regularization_test_marker": regularization}
        return {"regularization": regularization, "model_state": state,
            "weights_sha256": hashlib.sha256(subject._raw(state)).hexdigest(),
            "train_metrics": {"status": "available", "rows": len(inputs),
                              "mean_squared_l2": 1e-4 / regularization},
            "diagnostics": {"scope": "synthetic_selection_unit_test", "training_rows": len(inputs)},
            "objective": "sum_squared_l2_residual_plus_lambda_frobenius_weight_squared",
            "objective_residual_reduction": "sum", "exported_training_objective": 0.1,
            "validation_used_for_fit": False}
    def score(state, inputs, targets):
        calls["score"].append((deepcopy(inputs), deepcopy(targets)))
        return {"status": "available" if inputs else "unavailable", "rows": len(inputs),
                "mean_squared_l2": scores[state["regularization_test_marker"]] if inputs else None}
    return SimpleNamespace(fit_affine_ridge=fit, score_affine_ridge=score), calls


def test_candidates_fit_training_only_validation_selects_without_refit(inputs):
    plan = _ready_plan(inputs)
    original = deepcopy(plan)
    numeric, calls = _fake_numerics({.001: .6, .01: .2, .1: .4})
    report, state = subject._fit_candidates(plan, numeric=numeric)
    assert report["selected_regularization"] == .01
    assert report["candidate_count"] == 3
    assert state == {"regularization_test_marker": .01}
    assert report["validation_used_for_fit"] is False
    assert report["refit_with_validation"] is False
    assert report["test_or_canary_used"] is False
    assert len(calls["fit"]) == 3
    train_x = [row["student_embedding_768"] for row in plan["train_rows"]]
    train_y = [row["source_embedding_384"] for row in plan["train_rows"]]
    val_x = [row["student_embedding_768"] for row in plan["validation_rows"]]
    val_y = [row["source_embedding_384"] for row in plan["validation_rows"]]
    assert all(left == train_x and right == train_y for left, right, _ in calls["fit"])
    assert all(left == val_x and right == val_y for left, right in calls["score"])
    assert plan == original


def test_validation_tie_selects_smaller_regularization(inputs):
    numeric, _ = _fake_numerics({.001: .2, .01: .2, .1: .2})
    report, state = subject._fit_candidates(_ready_plan(inputs), numeric=numeric)
    assert report["selected_regularization"] == .001
    assert state == {"regularization_test_marker": .001}
    assert report["tie_break_policy"] == "smaller_regularization"


@pytest.mark.parametrize("invalid_score", [float("nan"), float("inf"), -0.01, None, True])
def test_invalid_validation_metric_cannot_select_candidate(inputs, invalid_score):
    numeric, _ = _fake_numerics({.001: invalid_score, .01: .2, .1: .2})
    with pytest.raises(ValueError, match="validation selection metric"):
        subject._fit_candidates(_ready_plan(inputs), numeric=numeric)


def test_numerical_candidate_cannot_claim_validation_was_fitted(inputs):
    numeric, _ = _fake_numerics({.001: .2, .01: .1, .1: .3})
    original = numeric.fit_affine_ridge
    numeric.fit_affine_ridge = lambda *args, **kwargs: {
        **original(*args, **kwargs), "validation_used_for_fit": True}
    with pytest.raises(ValueError, match="fitting policy"):
        subject._fit_candidates(_ready_plan(inputs), numeric=numeric)


@pytest.mark.parametrize("change", ["training_count", "training_metric_count", "validation_metric_count", "mean_objective"])
def test_numerical_report_must_preserve_row_counts_and_ridge_convention(inputs, change):
    numeric, _ = _fake_numerics({.001: .2, .01: .1, .1: .3})
    original_fit, original_score = numeric.fit_affine_ridge, numeric.score_affine_ridge
    def fitting(*args, **kwargs):
        value = original_fit(*args, **kwargs)
        if change == "training_count": value["diagnostics"]["training_rows"] += 1
        if change == "training_metric_count": value["train_metrics"]["rows"] += 1
        if change == "mean_objective": value["objective_residual_reduction"] = "mean"
        return value
    def scoring(*args, **kwargs):
        value = original_score(*args, **kwargs)
        if change == "validation_metric_count": value["rows"] += 1
        return value
    numeric.fit_affine_ridge, numeric.score_affine_ridge = fitting, scoring
    with pytest.raises(ValueError, match="accounting|summed-residual"):
        subject._fit_candidates(_ready_plan(inputs), numeric=numeric)


def test_one_fixed_candidate_can_fit_without_validation_or_selection(inputs):
    inputs.config["regularization_candidates"] = [.01]
    rows = [row for row in inputs.payloads["rows_384"] if row["split"] == "train"]
    audit = inputs.corpus._AUDIT.audit_transfer_rows(rows, dimension=384,
        vector_space_id=inputs.teacher["source_representation_id"])
    inputs.payloads.update(rows_384=rows, corpus_audit=audit,
        tasks=inputs.corpus.prepare_embedding_tasks(rows, audit))
    plan = _ready_plan(inputs)
    assert plan["validation_rows"] == []
    assert plan["fit_ready"] is True
    numeric, calls = _fake_numerics({.01: .2})
    report, state = subject._fit_candidates(plan, numeric=numeric)
    assert report["selection_policy"] == "fixed_candidate_no_validation"
    assert report["validation_rows"] == 0
    assert report["candidate_count"] == 1
    assert report["selected_regularization"] == .01
    assert state == {"regularization_test_marker": .01}
    assert len(calls["fit"]) == 1
    assert calls["score"] == [([], [])]


def test_new_alignment_must_not_claim_donor_coordinates_changed(inputs):
    inputs.teacher["source_representation_id"] = "unsupported-384-vector-space"
    with pytest.raises(ValueError, match="coordinates differ"):
        _run(inputs)
    assert not inputs.output.exists()


def test_fit_requested_on_unready_plan_never_calls_numeric_helper(inputs):
    pairs = subject._helper("gte_bridge_pairs").prepare_bridge_pairs(
        inputs.payloads["rows_384"], inputs.payloads["corpus_audit"],
        inputs.payloads["tasks"], inputs.payloads["receipts_768"])
    plan = subject._helper("gte_alignment_contract").prepare_alignment_plan(pairs)
    def forbidden(*args, **kwargs):
        pytest.fail("unready plan must not call the numerical fitter")
    with pytest.raises(ValueError, match="ready paired alignment plan"):
        subject._fit_candidates(plan, numeric=SimpleNamespace(fit_affine_ridge=forbidden))


def test_pack_bridge_preserves_exact_float32_state_and_external_bindings(inputs):
    torch = pytest.importorskip("torch")
    state = {"weight": torch.zeros(384, 768, dtype=torch.float32).tolist(),
             "bias": torch.full((384,), .125, dtype=torch.float32).tolist()}
    state["weight"][0][0] = 1.
    original = deepcopy(state)
    packed = subject._pack_bridge(state, config=inputs.config, teacher=inputs.teacher)
    assert packed["model_state"] == state == original
    assert packed["teacher_checkpoint_sha256"] == inputs.pins["teacher384_checkpoint_sha256"]
    assert packed["input_transform"] == inputs.teacher["input_transform"]
    assert packed["source_representation_id"] == inputs.teacher["source_representation_id"]
    assert packed["adapted_outputs_are_gte_small"] is False
    helper = subject._helper("gte_affine_bridge")
    restored = helper.load_bridge_checkpoint(packed,
        expected_domain_id="legal_ir", expected_teacher_runtime_id=inputs.teacher["teacher_runtime_id"],
        expected_source_representation_id=inputs.teacher["source_representation_id"],
        expected_student_representation_id=helper.STUDENT_REPRESENTATION_ID,
        expected_teacher_checkpoint_sha256=inputs.pins["teacher384_checkpoint_sha256"],
        input_transform=inputs.teacher["input_transform"])
    assert restored.weight.tolist() == state["weight"]
    assert restored.bias.tolist() == state["bias"]


def test_pack_bridge_rejects_rounding_or_misbinding(inputs):
    torch = pytest.importorskip("torch")
    state = {"weight": torch.zeros(384, 768, dtype=torch.float32).tolist(),
             "bias": torch.zeros(384, dtype=torch.float32).tolist()}
    state["weight"][0][0] = 1. / 3.
    with pytest.raises(ValueError, match="rounded fitted state"):
        subject._pack_bridge(state, config=inputs.config, teacher=inputs.teacher)
    state["weight"][0][0] = 1.
    wrong_teacher = {**inputs.teacher, "source_representation_id": "unsupported-coordinates"}
    with pytest.raises(ValueError, match="vector-space"):
        subject._pack_bridge(state, config=inputs.config, teacher=wrong_teacher)


def test_ready_fit_publishes_new_bound_bridge_and_preserves_all_inputs(inputs, monkeypatch):
    pytest.importorskip("torch")
    _add_receipts(inputs)
    inputs.config["mode"] = "fit"
    _repin(inputs)
    budget_calls = []
    def configure(resources):
        budget_calls.append(deepcopy(resources))
        return {"schema": "synthetic-unit-resource-admission/v1", "scope": "no_process_limits_applied"}
    monkeypatch.setattr(inputs.reader, "configure_cpu_process", configure)
    originals = {name: (inputs.path.parent / inputs.config[name]["path"]).read_bytes()
                 for name in subject.REFERENCES}
    result = _run(inputs)
    assert result["status"] == "fitted_unqualified"
    assert result["candidate_fits_executed"] == 3
    assert result["analytic_alignment_fit_executed"] is True
    assert result["training_executed"] is True
    assert result["distillation_executed"] is False
    assert result["encoder_inference_executed"] is False
    assert result["auxiliary_connector_fitted"] is False
    assert len(budget_calls) == 1
    manifest_path = inputs.output / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    assert manifest["completed"] is True
    assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == result["manifest_sha256"]
    bridge_raw = (inputs.output / "fitted-bridge.json").read_bytes()
    bridge = json.loads(bridge_raw)
    report = json.loads((inputs.output / "fit-report.json").read_bytes())
    plan_raw = (inputs.output / "plan.json").read_bytes()
    plan = json.loads(plan_raw)
    assert report["initialization_sha256"] == hashlib.sha256(originals["initialization"]).hexdigest()
    assert report["plan_sha256"] == hashlib.sha256(plan_raw).hexdigest()
    assert report["bridge_checkpoint_sha256"] == hashlib.sha256(bridge_raw).hexdigest()
    assert report["bridge_weights_sha256"] == bridge["weights_sha256"]
    assert report["selection"]["selected_weights_sha256"] == bridge["weights_sha256"]
    assert report["train_rows_sha256"] == plan["train_rows_sha256"]
    assert report["validation_rows_sha256"] == plan["validation_rows_sha256"]
    assert report["donor_pins"] == inputs.pins
    assert report["aligned_representation_id"] != inputs.initial["representation_id"]
    assert report["primary_input_boundary_fitted"] is True
    assert report["auxiliary_connector_fitted"] is False
    assert report["original_initialization_unchanged"] is True
    assert report["inherited_decoder_weights_unchanged"] is True
    assert report["source_fidelity_qualified"] is False
    assert report["validation_used_for_fit"] is False
    assert report["selection"]["refit_with_validation"] is False
    for name, raw in originals.items():
        assert (inputs.path.parent / inputs.config[name]["path"]).read_bytes() == raw
    for receipt in manifest["outputs"]:
        raw = (inputs.output / receipt["path"]).read_bytes()
        assert len(raw) == receipt["bytes"]
        assert hashlib.sha256(raw).hexdigest() == receipt["sha256"]
