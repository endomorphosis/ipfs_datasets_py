"""Exercise publication with real updates and explicitly synthetic native inputs."""
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
PATH = REPOSITORY / "scripts/ops/autoencoder/run_gte_decoder_interface_training.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


subject = _load("gte_interface_cli_subject", PATH)
native_tests = _load("gte_interface_cli_native_fixture",
    Path(__file__).with_name("test_prepare_gte_decoder_native.py"))
torch = pytest.importorskip("torch")


@pytest.fixture(scope="module", autouse=True)
def bounded_threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


@pytest.fixture(scope="module")
def parents(tmp_path_factory):
    transfer = native_tests.parent.__wrapped__(tmp_path_factory)
    published = {}
    for kind in ("empty", "selected"):
        directory = tmp_path_factory.mktemp("interface_native_" + kind)
        patch = pytest.MonkeyPatch()
        generator = native_tests.pipeline.__wrapped__(directory, patch, transfer)
        pipeline = next(generator)
        try:
            if kind == "selected":
                native_tests._cache(pipeline, "selected")
            result = native_tests._run(pipeline)
            manifest = json.loads((pipeline.output / "manifest.json").read_bytes())
            paths = [Path(ref["path"]) for key in ("inputs", "parent_closure", "implementation_files")
                for ref in manifest[key]]
            paths += [pipeline.output / ref["path"] for ref in manifest["outputs"]]
            paths.append(pipeline.output / "manifest.json")
            published[kind] = SimpleNamespace(pipeline=pipeline, result=result,
                original={path: path.read_bytes() for path in paths})
        finally:
            try:
                next(generator)
            except StopIteration:
                pass
            patch.undo()
    return SimpleNamespace(transfer=transfer, published=published)


def _configure(pipeline, kind="empty", mode="prepare"):
    parent = pipeline.parents.published[kind].pipeline
    paths = {"native_parent_manifest": parent.output / "manifest.json",
        **{name: parent.paths[name] for name in ("initialization", "donor_pins", "batch", "replay")},
        "native_batch": parent.output / "native-batch.json"}
    pipeline.config = {"schema": subject.SCHEMA, "workspace_root": "/", "mode": mode,
        "steps": 3, "learning_rate": .01, "max_grad_norm": 1.,
        "head_weights": {"primary384": 1., "legacy8": 1.},
        **{name: {"path": str(path.relative_to("/")),
                  "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
           for name, path in paths.items()}}
    pipeline.paths = paths
    _repin(pipeline)


def _repin(pipeline):
    pipeline.pin = native_tests._write(pipeline.path, pipeline.config)


@pytest.fixture
def pipeline(tmp_path, monkeypatch, parents):
    incoming = tmp_path / "inputs"
    incoming.mkdir()
    native = subject._native_cli()
    reader = native._helper("gte_worker_contract")
    original_helper = native._helper
    budget_calls = []

    def configure(resources):
        resources = reader._resources(resources)
        budget_calls.append(deepcopy(resources))
        return {"schema": "synthetic-test-resource-receipt/v1",
            "scope": "unit_test_no_process_limits_applied", **resources}

    monkeypatch.setattr(reader, "configure_cpu_process", configure)
    monkeypatch.setattr(native, "_helper", lambda name:
        reader if name == "gte_worker_contract" else original_helper(name))
    monkeypatch.setattr(subject, "_native_cli", lambda: native)
    value = SimpleNamespace(root=tmp_path, incoming=incoming, path=incoming / "config.json",
        output=tmp_path / "output", native=native, reader=reader, parents=parents,
        budget_calls=budget_calls)
    _configure(value)
    yield value
    for parent in parents.published.values():
        assert all(path.read_bytes() == raw for path, raw in parent.original.items())


def _run(pipeline, **changes):
    return subject.run_decoder_interface_training(pipeline.path,
        expected_config_sha256=pipeline.pin, output_directory=pipeline.output, **changes)


def _publication(pipeline, result, *, trained=False):
    manifest_path = pipeline.output / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    assert manifest["completed"] is True and manifest["status"] == result["status"]
    assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == result["manifest_sha256"]
    names = {"native-inspection.json", "summary.json"}
    if trained:
        names |= {"resources.json", "trained-interfaces.json", "training-report.json",
                  "checkpoint-inspection.json", "reload-verification.json"}
    assert {ref["path"] for ref in manifest["outputs"]} == names
    for key in ("inputs", "parent_closure", "implementation_files", "outputs"):
        for ref in manifest[key]:
            path = Path(ref["path"])
            raw = (path if path.is_absolute() else pipeline.output / path).read_bytes()
            assert len(raw) == ref["bytes"] and hashlib.sha256(raw).hexdigest() == ref["sha256"]
    assert manifest["training_executed"] is trained
    assert manifest["saved_trained_checkpoint_authenticated_and_replayed"] is trained
    assert manifest["optimizer_steps"] == (3 if trained else 0)
    assert manifest["trained_checkpoint_count"] == int(trained)
    assert result["old_embeddings_regenerated"] is False
    assert result["source_vectors_relabelled"] is False
    assert result["original_decoder_initialization_unchanged"] is True
    for flag in subject.FALSE_FLAGS:
        assert result[flag] is False and manifest[flag] is False


def test_cli_import_has_no_model_dependencies():
    code = """import importlib.util,sys
spec=importlib.util.spec_from_file_location('isolated_interface_cli',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
assert not any(name in sys.modules for name in ('torch','numpy','transformers','sentence_transformers','ipfs_datasets_py'))
"""
    subprocess.run([sys.executable, "-I", "-c", code, str(PATH)], check=True)


@pytest.mark.parametrize("mode", ["prepare", "train"])
def test_missing_native_inputs_create_no_optimizer_or_checkpoint(pipeline, monkeypatch, mode):
    pipeline.config["mode"] = mode
    _repin(pipeline)
    native_tests._forbid_numerical_imports(monkeypatch)
    result = _run(pipeline)
    assert result["status"] == "unavailable"
    assert result["selected_rows"] == result["missing_rows"] == 18 and result["ready_rows"] == 0
    assert result["optimizer_steps"] == result["trained_checkpoint_count"] == 0
    assert result["native768_inputs_used"] is False and result["training_executed"] is False
    assert pipeline.budget_calls == []
    _publication(pipeline, result)


def test_ready_prepare_executes_no_numerical_model(pipeline, monkeypatch):
    _configure(pipeline, "selected")
    native_tests._forbid_numerical_imports(monkeypatch)
    result = _run(pipeline)
    assert result["status"] == "prepared" and result["ready_rows"] == 18
    assert result["optimizer_steps"] == 0 and pipeline.budget_calls == []
    _publication(pipeline, result)


def test_ready_train_performs_real_updates_and_authenticates_saved_outputs(pipeline):
    _configure(pipeline, "selected", "train")
    result = _run(pipeline)
    assert result["status"] == "trained_unqualified"
    assert result["optimizer_steps"] == 3 and result["trained_checkpoint_count"] == 1
    assert result["trained_representation_id"] != result["initialization_representation_id"]
    assert result["inherited_decoder_tensor_count"] == 26 and result["trainable_interface_tensor_count"] == 4
    assert result["primary_start"] == "original_initialization"
    assert len(pipeline.budget_calls) == 1
    checkpoint = json.loads((pipeline.output / "trained-interfaces.json").read_bytes())
    report = json.loads((pipeline.output / "training-report.json").read_bytes())
    verified = json.loads((pipeline.output / "reload-verification.json").read_bytes())
    assert checkpoint["training_report"] == report
    assert report["after"]["loss"] < report["before"]["loss"]
    assert report["all_26_inherited_tensors_unchanged"] is True
    assert report["interfaces_changed"] is True
    assert verified["model_state_sha256"] == report["model_state_sha256_after"]
    assert verified["trained_reference_outputs_sha256"] == report["trained_reference_outputs_sha256"]
    for flag in ("trained_reference_outputs_match", "all_30_reloaded_tensors_bitwise_equal", "private_storage_disjoint"):
        assert verified[flag] is True
    assert verified["optimizer_steps"] == 0 and verified["optimizer_created"] is False
    _publication(pipeline, result, trained=True)


@pytest.mark.parametrize("key,value", [
    ("steps", True), ("steps", 0), ("steps", 65), ("learning_rate", 0),
    ("learning_rate", .1), ("max_grad_norm", 0),
    ("head_weights", {"primary384": 1., "legacy8": 0}), ("mode", "resume")])
def test_invalid_controls_fail_before_publication(pipeline, key, value):
    pipeline.config[key] = value
    _repin(pipeline)
    with pytest.raises(ValueError):
        _run(pipeline)
    assert not pipeline.output.exists() and pipeline.budget_calls == []


@pytest.mark.parametrize("name", subject.REFERENCES)
def test_external_input_hashes_are_required(pipeline, name):
    pipeline.config[name]["sha256"] = "0" * 64
    _repin(pipeline)
    with pytest.raises(ValueError):
        _run(pipeline)
    assert not pipeline.output.exists()


@pytest.mark.parametrize("namespace", ["repository", "primary_source", "legacy_source"])
def test_source_namespaces_cannot_receive_outputs(pipeline, namespace):
    transfer = pipeline.parents.transfer.pipeline
    if namespace == "repository":
        root = REPOSITORY
    else:
        name = "teacher384_repository_root" if namespace == "primary_source" else "legacy8_implementation_root"
        root = Path(transfer.config["workspace_root"]) / transfer.config[name]
    pipeline.output = root / "forbidden-interface-test-output"
    assert not pipeline.output.exists()
    with pytest.raises(ValueError):
        _run(pipeline)
    assert not pipeline.output.exists()


@pytest.mark.parametrize("corruption", ["checkpoint_quality", "report_mismatch", "live_output_forgery"])
def test_altered_saved_artifacts_never_receive_a_completion_manifest(pipeline, monkeypatch, corruption):
    _configure(pipeline, "selected", "train")
    original_write = pipeline.native._write

    def altered_write(output, name, value):
        value = deepcopy(value)
        if corruption == "checkpoint_quality" and name == "trained-interfaces.json":
            value["teacher_qualified"] = True
        elif corruption == "report_mismatch" and name == "training-report.json":
            value["optimizer_steps"] = 2
        elif corruption == "live_output_forgery" and name in ("trained-interfaces.json", "training-report.json"):
            contract = pipeline.native._helper("gte_decoder_interface_checkpoint")
            report = value["training_report"] if name == "trained-interfaces.json" else value
            report["trained_reference_outputs"]["legacy8"][0]["auxiliary_logits_sha256"] = "a" * 64
            report["trained_reference_outputs_sha256"] = contract.digest(report["trained_reference_outputs"])
            if name == "trained-interfaces.json":
                load = lambda key: json.loads(pipeline.paths[key].read_bytes())
                value = contract.create_interface_checkpoint(load("initialization"), load("native_batch"),
                    expected_donor_pins=load("donor_pins"), interfaces=value["interfaces"], training_report=report)
        return original_write(output, name, value)

    monkeypatch.setattr(pipeline.native, "_write", altered_write)
    with pytest.raises(ValueError):
        _run(pipeline)
    assert not (pipeline.output / "manifest.json").exists()
