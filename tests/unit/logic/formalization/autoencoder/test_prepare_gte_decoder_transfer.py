"""Pinned publication and real copied-head replay on synthetic cached inputs.

These tests exercise learned-distribution preservation, never encoder execution
or semantic qualification. Only process-wide operating system budgets are
replaced so the numerical replay remains real inside the pytest process.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest


REPOSITORY = Path(__file__).resolve().parents[5]
PATH = REPOSITORY / "scripts/ops/autoencoder/prepare_gte_decoder_transfer.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


subject = _load("gte_decoder_transfer_cli_test_subject", PATH)
torch = pytest.importorskip("torch")


def _raw(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False) + "\n").encode()


def _write(path, value):
    raw = _raw(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture(scope="module", autouse=True)
def bounded_threads():
    old = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(old)


def test_cli_import_is_dependency_free():
    code = """import importlib.util,sys
spec=importlib.util.spec_from_file_location('isolated_transfer_cli',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
assert not any(name in sys.modules for name in ('torch','numpy','transformers','sentence_transformers','ipfs_datasets_py'))
"""
    subprocess.run([sys.executable, "-I", "-c", code, str(PATH)], check=True)


@pytest.fixture(scope="module")
def retained(tmp_path_factory):
    builder = _load("gte_transfer_cli_fixture",
        Path(__file__).with_name("test_gte_decoder_transfer_batch.py"))
    return builder, builder.decoder_transfer_fixture(tmp_path_factory)


@pytest.fixture
def pipeline(tmp_path, monkeypatch, retained):
    builder, donor = retained
    incoming = tmp_path / "inputs"
    incoming.mkdir()
    roots = {"teacher384_repository_root": tmp_path / "source384",
             "legacy8_implementation_root": tmp_path / "source8"}
    inspector = builder.subject._TEACHER
    primary_paths = {*inspector._NATIVE_MODULE_PATHS.values(),
        *inspector._NUMERICAL_PATHS.values(),
        "ipfs_datasets_py/logic/formalization/autoencoder/source_training_v2.py",
        "ipfs_datasets_py/optimizers/logic_theorem_optimizer/domain_384_autoencoder.py"}
    legacy_paths = set(builder.subject._LEGACY._SOURCE_PATHS.values())
    source_files = []
    for name, paths in (("teacher384_repository_root", primary_paths),
                        ("legacy8_implementation_root", legacy_paths)):
        for relative in paths:
            destination = roots[name] / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPOSITORY / relative, destination)
            source_files.append(destination)
    values = {"initialization": deepcopy(donor.initialization),
        "donor_pins": deepcopy(donor.donor_pins),
        "primary_checkpoint": deepcopy(donor.primary_checkpoint),
        "legacy8_checkpoint": deepcopy(donor.legacy8_checkpoint),
        "primary_training_archive": deepcopy(donor.primary_archive),
        "legacy8_inputs": deepcopy(donor.legacy8_inputs),
        "legacy8_inference": deepcopy(donor.legacy8_inference)}
    config = {"schema": subject.SCHEMA, "workspace_root": str(tmp_path),
        "mode": "prepare", "max_rows_per_head": 16,
        **{name: root.name for name, root in roots.items()}}
    paths = {}
    for name, value in values.items():
        path = incoming / (name + ".json")
        if name in ("primary_checkpoint", "legacy8_checkpoint"):
            original = donor.primary_path if name == "primary_checkpoint" else donor.legacy8_path
            path.write_bytes(original.read_bytes())
            pin = hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            pin = _write(path, value)
        paths[name] = path
        config[name] = {"path": str(path.relative_to(tmp_path)), "sha256": pin}
    path = incoming / "config.json"
    pin = _write(path, config)
    reader = subject._helper("gte_worker_contract")
    original_helper = subject._helper
    budget_calls = []
    def configure(resources):
        checked = reader._resources(resources)
        budget_calls.append(deepcopy(checked))
        return {"schema": "synthetic-unit-test-resource-receipt/v1",
            "scope": "unit_test_no_process_limits_applied", **checked}
    monkeypatch.setattr(reader, "configure_cpu_process", configure)
    monkeypatch.setattr(subject, "_helper", lambda name:
        reader if name == "gte_worker_contract" else original_helper(name))
    return SimpleNamespace(root=tmp_path, roots=roots, paths=paths, config=config,
        path=path, pin=pin, values=values, output=tmp_path / "output",
        source_files=source_files, reader=reader, budget_calls=budget_calls,
        original_helper=original_helper, builder=builder)


def _run(pipeline, **changes):
    args = {"expected_config_sha256": pipeline.pin, "output_directory": pipeline.output}
    args.update(changes)
    return subject.prepare_decoder_transfer(pipeline.path, **args)


def _repin(pipeline):
    pipeline.pin = _write(pipeline.path, pipeline.config)


def _replace(pipeline, name, value):
    pipeline.config[name]["sha256"] = _write(pipeline.paths[name], value)
    _repin(pipeline)


def test_real_replay_publishes_authenticated_separate_head_distributions(pipeline):
    preserved = {path: path.read_bytes() for path in
        (*pipeline.paths.values(), pipeline.path, *pipeline.source_files)}
    rng = torch.get_rng_state().clone()
    result = _run(pipeline)
    assert result["status"] == "behavior_preserved_unqualified"
    assert result["primary384_rows"] == 16 and result["legacy8_rows"] == 2
    assert result["copied_decoder_tensor_count"] == 26
    assert result["decoder_parameters_random"] is False
    assert result["original_decoder_initialization_unchanged"] is True
    assert result["all_26_inherited_tensors_unchanged"] is True
    assert result["raw_8d_latents_reconstructed_from_original_cache"] is True
    for flag in ("input_adapter_exercised", "auxiliary_connector_exercised",
        "native768_inputs_used", "encoder_inference_executed", "training_executed",
        "distillation_executed", "teacher_qualified", "production_kd_eligible",
        "download_executed", "source_fidelity_qualified", "proof_authority"):
        assert result[flag] is False
    assert result["optimizer_steps"] == 0
    assert torch.equal(rng, torch.get_rng_state())
    assert all(path.read_bytes() == raw for path, raw in preserved.items())
    assert pipeline.budget_calls == [{"device": "cpu", "threads": 1, "max_rows": 128,
        "memory_limit_mib": 16384, "cpu_time_limit_seconds": 120}]
    manifest_path = pipeline.output / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    assert manifest["completed"] is True and manifest["status"] == result["status"]
    assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == result["manifest_sha256"]
    assert {ref["path"] for ref in manifest["outputs"]} == {
        "batch.json", "teacher384-binding.json", "legacy8-binding.json", "replay.json",
        "resources.json", "summary.json"}
    assert {ref["path"] for ref in manifest["inputs"]} == {str(path.resolve()) for path in preserved}
    for ref in [*manifest["inputs"], *manifest["implementation_files"], *manifest["outputs"]]:
        path = Path(ref["path"])
        raw = (path if path.is_absolute() else pipeline.output / path).read_bytes()
        assert len(raw) == ref["bytes"] and hashlib.sha256(raw).hexdigest() == ref["sha256"]
    batch = json.loads((pipeline.output / "batch.json").read_bytes())
    replay = json.loads((pipeline.output / "replay.json").read_bytes())
    numeric = pipeline.original_helper("gte_decoder_transfer_replay")
    inspection = numeric.inspect_decoder_transfer_replay(replay, batch,
        initialization=pipeline.values["initialization"], expected_donor_pins=pipeline.values["donor_pins"])
    assert inspection["row_counts"] == {"primary384": 16, "legacy8": 2}
    assert replay["heads"]["primary384"]["vocabulary_size"] != replay["heads"]["legacy8"]["vocabulary_size"]
    for name, head in replay["heads"].items():
        assert head["input_dimension"] == (384 if name == "primary384" else 8)
        assert head["prefix_policy"] == "reference_prefix" and head["distribution"] == "raw"
        assert head["diagnostic_kl_t2"] == 0. and head["max_logit_error"] == 0.
        assert head["logits_detached"] is True and head["exact_logits"] is True
        for row, original in zip(head["rows"], batch["heads"][name]["rows"]):
            logits = torch.tensor(row["teacher_logits"], dtype=torch.float32)
            assert bool(torch.isfinite(logits).all())
            assert logits.shape == (len(row["prefix_ids"]), head["vocabulary_size"])
            assert row["teacher_logits"] == logits.tolist()
            assert row["prefix_ids"] == original["token_ids"][:-1]
            assert row["next_token_ids"] == original["token_ids"][1:]
            assert all(row["reference_token_mask"]) and not any(row["kd_token_mask"])
    assert not (pipeline.output / "student-initialization.json").exists()


def test_row_selection_is_bounded_independently_for_both_heads(pipeline):
    pipeline.config["max_rows_per_head"] = 1
    _repin(pipeline)
    result = _run(pipeline)
    assert result["primary384_rows"] == result["legacy8_rows"] == 1
    batch = json.loads((pipeline.output / "batch.json").read_bytes())
    assert batch["heads"]["primary384"]["available_row_count"] == 180
    assert batch["heads"]["legacy8"]["available_row_count"] == 2


@pytest.mark.parametrize("change", ["extra", "mode", "root_relative", "missing_root",
    "root_absolute", "source_traversal", "ref_extra", "ref_absolute", "ref_traversal",
    "limit_bool", "limit_zero", "limit_65"])
def test_closed_configuration_and_workspace_identity_are_required(pipeline, change):
    config = pipeline.config
    if change == "extra": config["allow_unqualified_kd"] = True
    if change == "mode": config["mode"] = "train"
    if change == "root_relative": config["workspace_root"] = "."
    if change == "missing_root": config["workspace_root"] = str(pipeline.root / "absent")
    if change == "root_absolute": config["teacher384_repository_root"] = str(pipeline.roots["teacher384_repository_root"])
    if change == "source_traversal": config["legacy8_implementation_root"] = "../source8"
    if change == "ref_extra": config["legacy8_inputs"]["trusted"] = True
    if change == "ref_absolute": config["primary_training_archive"]["path"] = str(pipeline.paths["primary_training_archive"])
    if change == "ref_traversal": config["primary_training_archive"]["path"] = "../inputs/archive.json"
    if change == "limit_bool": config["max_rows_per_head"] = True
    if change == "limit_zero": config["max_rows_per_head"] = 0
    if change == "limit_65": config["max_rows_per_head"] = 65
    _repin(pipeline)
    with pytest.raises(ValueError): _run(pipeline)
    assert not pipeline.output.exists() and pipeline.budget_calls == []


@pytest.mark.parametrize("name", subject.REFERENCES)
def test_every_input_requires_an_external_file_pin_before_numerical_loading(pipeline, name):
    pipeline.config[name]["sha256"] = "0" * 64
    _repin(pipeline)
    with pytest.raises(ValueError, match="SHA256"):
        _run(pipeline)
    assert not pipeline.output.exists() and pipeline.budget_calls == []


def test_configuration_pin_is_external_and_required(pipeline):
    with pytest.raises(ValueError, match="SHA256"):
        _run(pipeline, expected_config_sha256="0" * 64)
    assert not pipeline.output.exists() and pipeline.budget_calls == []


@pytest.mark.parametrize("kwargs", [{"threads": True}, {"threads": 2},
    {"memory_limit_mib": True}, {"memory_limit_mib": 255},
    {"cpu_time_limit_seconds": 0}, {"cpu_time_limit_seconds": True}])
def test_cpu_resources_require_strict_bounded_integers(pipeline, kwargs):
    with pytest.raises(ValueError): _run(pipeline, **kwargs)
    assert not pipeline.output.exists() and pipeline.budget_calls == []


@pytest.mark.parametrize("change", ["unselected_source", "unselected_vector", "provenance",
    "legacy_input", "legacy_prefix", "legacy_teacher_forcing"])
def test_repinned_cache_changes_cannot_replace_the_original_training_inputs(pipeline, change):
    name = "primary_training_archive" if change in ("unselected_source", "unselected_vector", "provenance") else (
        "legacy8_inputs" if change == "legacy_input" else "legacy8_inference")
    value = deepcopy(pipeline.values[name])
    if change == "unselected_source":
        row = value["rows"][-1]
        row["source_text"] += " changed"
        row["source_sha256"] = hashlib.sha256(row["source_text"].encode()).hexdigest()
    if change == "unselected_vector":
        row = value["rows"][-1]
        row["embedding"] = [0.] * 384
        row["embedding"][383] = 1.
        row["embedding_sha256"] = pipeline.builder.subject.digest(row["embedding"])
    if change == "provenance": value["source_embeddings"]["revision"] = "0" * 40
    if change == "legacy_input": value[0]["embedding_vector"][0] += .01
    if change == "legacy_prefix": value["rows"][0]["generated_token_ids"][1] = 2
    if change == "legacy_teacher_forcing": value["teacher_forcing"] = True
    _replace(pipeline, name, value)
    with pytest.raises(ValueError): _run(pipeline)
    assert not pipeline.output.exists() and pipeline.budget_calls == []


@pytest.mark.parametrize("which", ["primary", "legacy"])
def test_donor_implementation_source_drift_prevents_replay(pipeline, which):
    root = pipeline.roots["teacher384_repository_root" if which == "primary" else "legacy8_implementation_root"]
    path = next(path for path in pipeline.source_files if path.is_relative_to(root))
    path.write_bytes(path.read_bytes() + b"\n# changed synthetic source\n")
    with pytest.raises(ValueError): _run(pipeline)
    assert not pipeline.output.exists() and pipeline.budget_calls == []


@pytest.mark.parametrize("namespace", ["inputs", "primary_source", "legacy_source", "repository"])
def test_output_cannot_alias_input_or_implementation_namespaces(pipeline, namespace):
    roots = {"inputs": pipeline.path.parent,
        "primary_source": pipeline.roots["teacher384_repository_root"],
        "legacy_source": pipeline.roots["legacy8_implementation_root"], "repository": REPOSITORY}
    output = roots[namespace] / "synthetic-transfer-output-never-created"
    with pytest.raises(ValueError, match="namespace"):
        _run(pipeline, output_directory=output)
    assert not output.exists() and pipeline.budget_calls == []


def test_existing_output_and_symlink_output_namespace_are_preserved(pipeline):
    pipeline.output.mkdir()
    sentinel = pipeline.output / "retained.txt"
    sentinel.write_bytes(b"retained")
    with pytest.raises(ValueError, match="fresh"): _run(pipeline)
    assert sentinel.read_bytes() == b"retained" and pipeline.budget_calls == []
    alias = pipeline.root / "alias"
    alias.symlink_to(pipeline.output, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        _run(pipeline, output_directory=alias / "child")
    assert not (pipeline.output / "child").exists() and pipeline.budget_calls == []


@pytest.mark.parametrize("filename,change", [("batch.json", "prefix"),
    ("replay.json", "logits"), ("replay.json", "qualification"), ("replay.json", "optimizer_bool")])
def test_saved_artifacts_are_inspected_after_their_bytes_are_authenticated(pipeline, monkeypatch, filename, change):
    original = subject._write
    def corrupt(directory, name, value):
        if name == filename:
            value = deepcopy(value)
            if change == "prefix": value["heads"]["primary384"]["rows"][0]["prefix_ids"][0] = 0
            if change == "logits": value["heads"]["legacy8"]["rows"][0]["exact_logits"] = False
            if change == "qualification": value["teacher_qualified"] = True
            if change == "optimizer_bool": value["optimizer_steps"] = False
        return original(directory, name, value)
    monkeypatch.setattr(subject, "_write", corrupt)
    with pytest.raises(ValueError): _run(pipeline)
    assert (pipeline.output / filename).exists()
    assert not (pipeline.output / "manifest.json").exists()


def test_written_output_corruption_prevents_a_completion_manifest(pipeline, monkeypatch):
    original = subject._write
    def corrupt(directory, name, value):
        receipt = original(directory, name, value)
        if name == "replay.json":
            with (Path(directory) / name).open("ab") as stream: stream.write(b" ")
        return receipt
    monkeypatch.setattr(subject, "_write", corrupt)
    with pytest.raises(ValueError, match="changed"):
        _run(pipeline)
    assert not (pipeline.output / "manifest.json").exists()


def test_input_drift_during_publication_prevents_completion(pipeline, monkeypatch):
    original = subject._write
    def drift(directory, name, value):
        receipt = original(directory, name, value)
        if name == "batch.json":
            with pipeline.paths["legacy8_inputs"].open("ab") as stream: stream.write(b" ")
        return receipt
    monkeypatch.setattr(subject, "_write", drift)
    with pytest.raises(ValueError, match="changed"):
        _run(pipeline)
    assert (pipeline.output / "batch.json").exists()
    assert not (pipeline.output / "manifest.json").exists()
