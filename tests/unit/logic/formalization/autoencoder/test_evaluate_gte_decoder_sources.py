"""Saved source-only regression evaluation and strict immutable-parent admission."""
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
WORKSPACE = REPOSITORY.parents[1]
PATH = REPOSITORY / "scripts/ops/autoencoder/evaluate_gte_decoder_sources.py"
CONFIG = REPOSITORY / "configs/autoencoders/gte_decoder_source_evaluation_v1.json"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


subject = _load("gte_source_evaluation_cli_subject", PATH)
parent_tests = _load("gte_source_evaluation_cli_parent_fixture",
    Path(__file__).with_name("test_gte_source_evaluation_parent.py"))
torch = pytest.importorskip("torch")


def _read(path):
    return json.loads(path.read_bytes())


def _pin(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n")
    return _pin(path)


def _reference(path):
    return {"path": str(path.resolve().relative_to("/")), "sha256": _pin(path)}


@pytest.fixture(scope="module", autouse=True)
def bounded_threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


@pytest.fixture(scope="module")
def actual():
    if not CONFIG.is_file():
        pytest.skip("actual source evaluation configuration is outside this checkout")
    config = _read(CONFIG)
    root = Path(config["workspace_root"])
    paths = {name: root / config[name]["path"] for name in subject.REFERENCES}
    if not all(path.is_file() for path in paths.values()):
        pytest.skip("actual cached donor artifacts are outside this checkout")
    admitted = parent_tests._admit(paths["training_parent_manifest"], root=root)
    assert admitted["status"] == "unavailable"
    original = {path: path.read_bytes() for path in paths.values()}
    yield SimpleNamespace(config=config, paths=paths, admitted=admitted, original=original)
    assert all(path.read_bytes() == raw for path, raw in original.items())


@pytest.fixture(scope="module")
def synthetic_publications(tmp_path_factory):
    generator = parent_tests.publications.__wrapped__(tmp_path_factory)
    publications = next(generator)
    yield publications
    with pytest.raises(StopIteration):
        next(generator)


@pytest.fixture
def pipeline(tmp_path, monkeypatch, actual):
    training = subject._training_cli()
    native = training._native_cli()
    reader = native._helper("gte_worker_contract")
    previous_helper = native._helper
    budget_calls = []

    def configure(resources):
        resources = reader._resources(resources)
        budget_calls.append(deepcopy(resources))
        return {"schema": "gte-worker-cpu-budget-receipt/v1",
            "scope": "synthetic_test_no_process_limits_applied", **resources}

    monkeypatch.setattr(reader, "configure_cpu_process", configure)
    monkeypatch.setattr(native, "_helper", lambda name:
        reader if name == "gte_worker_contract" else previous_helper(name))
    monkeypatch.setattr(training, "_native_cli", lambda: native)
    monkeypatch.setattr(subject, "_training_cli", lambda: training)
    config = {"schema": subject.SCHEMA, "workspace_root": "/", "mode": "prepare",
        "max_primary_rows": 1, "max_auxiliary_rows": 1,
        **{name: _reference(path) for name, path in actual.paths.items()}}
    value = SimpleNamespace(config=config, path=tmp_path / "inputs/config.json", output=tmp_path / "output",
        native=native, reader=reader, training=training, budget_calls=budget_calls, actual=actual)
    _repin(value)
    yield value
    assert all(path.read_bytes() == raw for path, raw in actual.original.items())


def _repin(pipeline):
    pipeline.pin = _write(pipeline.path, pipeline.config)


def _run(pipeline, **changes):
    return subject.run_source_evaluation(pipeline.path, expected_config_sha256=pipeline.pin,
        output_directory=pipeline.output, **changes)


def _publication(pipeline, result, *, evaluated):
    manifest_path = pipeline.output / "manifest.json"
    manifest = _read(manifest_path)
    assert manifest["schema"] == "gte-decoder-source-evaluation-manifest/v1"
    assert manifest["completed"] is True and manifest["status"] == result["status"]
    assert _pin(manifest_path) == result["manifest_sha256"]
    names = {"source-evaluation-plan.json", "plan-inspection.json", "summary.json"}
    if evaluated:
        names |= {"resources.json", "source-comparison.json", "comparison-inspection.json", "numerical-replay.json"}
    assert {ref["path"] for ref in manifest["outputs"]} == names
    for key in ("inputs", "parent_closure", "implementation_files", "outputs"):
        for ref in manifest[key]:
            path = Path(ref["path"])
            raw = (path if path.is_absolute() else pipeline.output / path).read_bytes()
            assert len(raw) == ref["bytes"] and hashlib.sha256(raw).hexdigest() == ref["sha256"]
    assert manifest["decoder_inference_executed"] is evaluated
    assert manifest["saved_source_comparison_authenticated_and_replayed"] is evaluated
    assert manifest["optimizer_steps"] == 0 and result["optimizer_created"] is False
    for flag in subject.FALSE_FLAGS:
        assert manifest[flag] is False and result[flag] is False
    assert result["old_embeddings_regenerated"] is result["source_vectors_relabelled"] is False
    return manifest


def _forbid(monkeypatch):
    parent_tests.old.native_tests._forbid_numerical_imports(monkeypatch)


def test_cli_import_stays_dependency_free():
    code = """import importlib.util,sys
spec=importlib.util.spec_from_file_location('isolated_eval',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
assert not any(name in sys.modules for name in ('torch','numpy','transformers','sentence_transformers','ipfs_datasets_py'))
"""
    subprocess.run([sys.executable, "-I", "-c", code, str(PATH)], check=True)


def test_actual_preparation_in_guarded_fresh_subprocess_uses_no_models(pipeline):
    code = """import builtins,importlib.util,json,sys
original=builtins.__import__
def guarded(name,*args,**kwargs):
 if name.split('.')[0] in ('torch','numpy','transformers','sentence_transformers','ipfs_datasets_py'):
  raise AssertionError('unexpected numerical or package import: '+name)
 return original(name,*args,**kwargs)
builtins.__import__=guarded
spec=importlib.util.spec_from_file_location('isolated_evaluation',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
result=module.run_source_evaluation(sys.argv[2],expected_config_sha256=sys.argv[3],output_directory=sys.argv[4])
assert result['status']=='prepared_unqualified'
assert result['selected_row_count']==result['donor_ready_row_count']==2
assert result['native_ready_row_count']==0 and result['native_missing_row_count']==2
assert result['decoder_inference_executed'] is False
assert not any(name in sys.modules for name in ('torch','numpy','transformers','sentence_transformers','ipfs_datasets_py'))
print(json.dumps(result,sort_keys=True))
"""
    process = subprocess.run([sys.executable, "-I", "-c", code, str(PATH), str(pipeline.path), pipeline.pin,
        str(pipeline.output)], capture_output=True, text=True)
    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout)
    _publication(pipeline, result, evaluated=False)
    assert pipeline.budget_calls == []


@pytest.mark.parametrize("key,value", [
    ("schema", "forged"), ("mode", "train"), ("max_primary_rows", True), ("max_primary_rows", 0),
    ("max_primary_rows", 61), ("max_auxiliary_rows", True), ("max_auxiliary_rows", 0),
    ("max_auxiliary_rows", 3), ("workspace_root", "."), ("extra_field", False)])
def test_closed_configuration_rejects_invalid_controls_before_torch(pipeline, monkeypatch, key, value):
    pipeline.config[key] = value
    _repin(pipeline)
    _forbid(monkeypatch)
    with pytest.raises(ValueError):
        _run(pipeline)
    assert not pipeline.output.exists() and pipeline.budget_calls == []


@pytest.mark.parametrize("reference", subject.REFERENCES)
def test_each_external_input_hash_is_admitted_before_torch(pipeline, monkeypatch, reference):
    pipeline.config[reference]["sha256"] = "0" * 64
    _repin(pipeline)
    _forbid(monkeypatch)
    with pytest.raises(ValueError):
        _run(pipeline)
    assert not pipeline.output.exists() and pipeline.budget_calls == []


def test_configuration_byte_hash_is_required_before_model_imports(pipeline, monkeypatch):
    pipeline.pin = "0" * 64
    _forbid(monkeypatch)
    with pytest.raises(ValueError):
        _run(pipeline)
    assert not pipeline.output.exists()


@pytest.mark.parametrize("reference", ("primary_checkpoint", "legacy8_checkpoint"))
def test_missing_raw_donor_is_not_replaced_or_reconstructed(pipeline, monkeypatch, reference):
    pipeline.config[reference]["path"] = str((pipeline.path.parent / "missing-checkpoint.json").relative_to("/"))
    _repin(pipeline)
    _forbid(monkeypatch)
    with pytest.raises(OSError):
        _run(pipeline)
    assert not pipeline.output.exists() and pipeline.budget_calls == []


def test_rehashed_donor_body_cannot_override_original_donor_identity(pipeline, monkeypatch):
    donor = _read(pipeline.actual.paths["primary_checkpoint"])
    values = donor["model_state"][next(iter(donor["model_state"]))]
    while type(values[0]) is list:
        values = values[0]
    values[0] += .01
    copied = pipeline.path.parent / "changed-donor.json"
    _write(copied, donor)
    pipeline.config["primary_checkpoint"] = _reference(copied)
    _repin(pipeline)
    _forbid(monkeypatch)
    with pytest.raises(ValueError, match="raw donor"):
        _run(pipeline)
    assert not pipeline.output.exists()


def test_missing_parent_dependency_cannot_be_hidden_by_rehashing_manifest(pipeline, monkeypatch):
    manifest = _read(pipeline.actual.paths["training_parent_manifest"])
    manifest["implementation_files"].pop()
    copied = pipeline.path.parent / "incomplete-parent.json"
    _write(copied, manifest)
    pipeline.config["training_parent_manifest"] = _reference(copied)
    _repin(pipeline)
    _forbid(monkeypatch)
    with pytest.raises(ValueError, match="implementation inventory"):
        _run(pipeline)
    assert not pipeline.output.exists()


@pytest.mark.parametrize("namespace", ("repository", "original_source", "donor_inputs"))
def test_output_cannot_alias_preserved_source_or_input_namespace(pipeline, monkeypatch, namespace):
    protected = {"repository": REPOSITORY,
        "original_source": pipeline.actual.admitted["source_roots"][0],
        "donor_inputs": pipeline.actual.paths["primary_checkpoint"].parent}[namespace]
    pipeline.output = protected / "forbidden-source-evaluation-test"
    assert not pipeline.output.exists()
    _forbid(monkeypatch)
    with pytest.raises(ValueError, match="aliases"):
        _run(pipeline)
    assert not pipeline.output.exists()


def test_existing_output_is_never_overwritten(pipeline, monkeypatch):
    pipeline.output.mkdir()
    sentinel = pipeline.output / "sentinel.bin"
    sentinel.write_bytes(b"preserved existing output")
    _forbid(monkeypatch)
    with pytest.raises(ValueError, match="fresh output"):
        _run(pipeline)
    assert sentinel.read_bytes() == b"preserved existing output"
    assert not (pipeline.output / "manifest.json").exists()


def test_small_actual_donor_only_evaluation_saves_exact_replay_with_zero_native(pipeline):
    pipeline.config["mode"] = "evaluate"
    _repin(pipeline)
    result = _run(pipeline)
    assert result["status"] == "donor_baseline_only_unqualified"
    assert result["training_parent_status"] == "unavailable"
    assert result["selected_row_count"] == result["donor_ready_row_count"] == 2
    assert result["native_ready_row_count"] == 0 and result["native_missing_row_count"] == 2
    assert result["decoder_inference_executed"] is True and result["native768_inputs_used"] is False
    assert len(pipeline.budget_calls) == 1
    assert pipeline.budget_calls[0]["threads"] == 1 and pipeline.budget_calls[0]["max_rows"] == 62
    _publication(pipeline, result, evaluated=True)
    comparison = _read(pipeline.output / "source-comparison.json")
    for name in ("primary384", "legacy8"):
        donor = comparison["variants"]["original_donor"]["heads"][name]
        assert donor["summary"]["selected_row_count"] == donor["summary"]["evaluated_row_count"] == 1
        assert donor["rows"][0]["generation"]["steps"][0]["prefix_length"] == 1
        assert donor["rows"][0]["generation"]["generated_ids"][0] == 1
        assert donor["rows"][0]["score"]["reference_prefix_used"] is False
        initial = comparison["variants"]["original_initialization"]["heads"][name]
        assert initial["summary"]["evaluated_row_count"] == 0 and initial["summary"]["missing_native_row_count"] == 1
        assert initial["rows"][0]["generation"] is None
    verification = _read(pipeline.output / "numerical-replay.json")
    assert verification["all_generated_tokens_and_logits_replayed_exactly"] is True
    assert verification["fresh_private_models_loaded"] is True
    assert verification["all_selected_rows_retained"] is True
    assert verification["optimizer_steps"] == 0


def test_saved_rehashed_logit_forgery_cannot_complete_publication(pipeline, monkeypatch):
    pipeline.config["mode"] = "evaluate"
    _repin(pipeline)
    writer = pipeline.native._write

    def corrupt(directory, name, value):
        if name == "source-comparison.json":
            value = deepcopy(value)
            receipt = value["variants"]["original_donor"]["heads"]["primary384"]["rows"][0]["generation"]
            receipt["steps"][0]["raw_logits_sha256"] = "a" * 64
        return writer(directory, name, value)

    monkeypatch.setattr(pipeline.native, "_write", corrupt)
    with pytest.raises(ValueError, match="saved source evaluation output differs from actual execution"):
        _run(pipeline)
    assert not (pipeline.output / "manifest.json").exists()


@pytest.mark.parametrize("filename,key,value", [
    ("source-evaluation-plan.json", "reference_prefix_used", True),
    ("plan-inspection.json", "donor_ready_row_count", 0),
    ("summary.json", "teacher_qualified", True),
    ("resources.json", "device", "cuda"),
    ("comparison-inspection.json", "scoring_reconstructed", False),
    ("numerical-replay.json", "all_generated_tokens_and_logits_replayed_exactly", False)])
def test_rehashed_saved_metadata_cannot_complete_publication(pipeline, monkeypatch, filename, key, value):
    if filename in ("resources.json", "comparison-inspection.json", "numerical-replay.json"):
        pipeline.config["mode"] = "evaluate"
        _repin(pipeline)
    else:
        _forbid(monkeypatch)
    writer = pipeline.native._write

    def corrupt(directory, name, original):
        if name == filename:
            original = deepcopy(original)
            original[key] = value
            if name == "source-evaluation-plan.json":
                helper = pipeline.native._helper("gte_decoder_source_evaluation")
                original["plan_sha256"] = helper.digest({key: child for key, child in original.items()
                                                         if key != "plan_sha256"})
        return writer(directory, name, original)

    monkeypatch.setattr(pipeline.native, "_write", corrupt)
    with pytest.raises(ValueError):
        _run(pipeline)
    assert not (pipeline.output / "manifest.json").exists()


def test_real_synthetic_trained_parent_retains_missing_validation_and_compares_two_auxiliary_rows(pipeline, synthetic_publications):
    parent = synthetic_publications["trained_unqualified"]
    admitted = parent_tests._admit(parent)
    pins = admitted["payloads"]["donor_pins"]
    raw_paths = {}
    for name, key in (("primary_checkpoint", "teacher384_checkpoint_sha256"),
                      ("legacy8_checkpoint", "legacy8_checkpoint_sha256")):
        matches = [Path(ref["path"]) for ref in admitted["closure"] if ref["sha256"] == pins[key]]
        assert matches
        raw_paths[name] = matches[0]
    pipeline.config.update(mode="evaluate", max_primary_rows=1, max_auxiliary_rows=2,
        training_parent_manifest=_reference(parent), **{name: _reference(path) for name, path in raw_paths.items()})
    _repin(pipeline)
    result = _run(pipeline)
    assert result["status"] == "partial_comparison_unqualified"
    assert result["training_parent_status"] == "trained_unqualified"
    assert result["native_ready_row_count"] == 2 and result["native_missing_row_count"] == 1
    assert result["aligned_generation_available"] is result["trained_generation_available"] is True
    assert result["native768_inputs_used"] is True and result["optimizer_steps"] == 0
    _publication(pipeline, result, evaluated=True)
    comparison = _read(pipeline.output / "source-comparison.json")
    for label in ("original_initialization", "aligned_initialization", "trained_interfaces"):
        variant = comparison["variants"][label]
        assert variant["available"] is True
        primary = variant["heads"]["primary384"]
        assert primary["summary"]["selected_row_count"] == primary["summary"]["missing_native_row_count"] == 1
        assert primary["summary"]["evaluated_row_count"] == 0
        auxiliary = variant["heads"]["legacy8"]
        assert auxiliary["summary"]["selected_row_count"] == auxiliary["summary"]["evaluated_row_count"] == 2
        assert auxiliary["summary"]["complete_cohort_evaluated"] is True
        assert all(row["evaluation_role"] == "legacy_training_diagnostic_only" for row in auxiliary["rows"])
    assert comparison["variants"]["trained_interfaces"]["heads"]["legacy8"]["rows"][0]["generation"]["model_state_sha256_before"] == admitted["trained_checkpoint"]["model_state_sha256"]
