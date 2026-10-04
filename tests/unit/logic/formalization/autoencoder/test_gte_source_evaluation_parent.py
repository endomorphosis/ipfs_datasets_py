"""Pure admission of actual cached donors and saved synthetic trained parents."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


REPOSITORY = Path(__file__).resolve().parents[5]
PATH = REPOSITORY / "scripts/ops/autoencoder/gte_source_evaluation_parent.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


subject = _load("gte_source_evaluation_parent_subject", PATH)
old = _load("gte_source_evaluation_aligned_fixture",
    Path(__file__).with_name("test_run_gte_aligned_interface_training.py"))
torch = pytest.importorskip("torch")


def _read(path):
    return json.loads(path.read_bytes())


def _receipt(path):
    raw = path.read_bytes()
    return {"path": str(path.resolve()), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _write(path, value):
    old.native_tests._write(path, value)
    return _receipt(path)


def _admit(path, *, root=Path("/")):
    native = old.subject._native_cli()
    return subject.admit_training_parent(_read(path), _receipt(path), root=root,
        reader=native._helper("gte_worker_contract"), training_cli=old.subject)


@pytest.fixture(scope="module", autouse=True)
def bounded_threads():
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


@pytest.fixture(scope="module")
def publications(tmp_path_factory):
    parents = old.parents.__wrapped__(tmp_path_factory)
    published = {}
    for status, kind, mode, aligned_kind in (
        ("unavailable", "empty", "prepare", "unavailable"),
        ("prepared", "selected", "prepare", "constructed"),
        ("trained_unqualified", "selected", "train", "constructed")):
        directory = tmp_path_factory.mktemp("source_eval_parent_" + status)
        with pytest.MonkeyPatch.context() as patch:
            generator = old.pipeline.__wrapped__(directory, patch, parents)
            pipeline = next(generator)
            try:
                def configure(resources):
                    resources = pipeline.reader._resources(resources)
                    pipeline.budget_calls.append(deepcopy(resources))
                    return {"schema": "gte-worker-cpu-budget-receipt/v1",
                        "scope": "synthetic_test_no_process_limits_applied", **resources}
                patch.setattr(pipeline.reader, "configure_cpu_process", configure)
                old._configure(pipeline, kind, mode, aligned_kind)
                result = old._run(pipeline)
                assert result["status"] == status
            finally:
                with pytest.raises(StopIteration):
                    next(generator)
        manifest = pipeline.output / "manifest.json"
        published[status] = manifest
    originals = {path: path.read_bytes() for manifest in published.values()
        for path in [manifest, *(manifest.parent / ref["path"] for ref in _read(manifest)["outputs"])]}
    yield published
    assert all(path.read_bytes() == raw for path, raw in originals.items())


def _copy_parent(publications, tmp_path, *, status="trained_unqualified"):
    original = publications[status]
    copied = tmp_path / "copied-parent"
    shutil.copytree(original.parent, copied)
    return copied / "manifest.json"


def _replace_output(path, name, changes):
    manifest = _read(path)
    value = _read(path.parent / name)
    value.update(changes)
    ref = _write(path.parent / name, value)
    index = next(index for index, old_ref in enumerate(manifest["outputs"]) if old_ref["path"] == name)
    manifest["outputs"][index] = {**ref, "path": name}
    _write(path, manifest)


def test_parent_reader_import_has_no_numerical_dependencies():
    code = """import importlib.util,sys
spec=importlib.util.spec_from_file_location('isolated_parent',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
assert not any(name in sys.modules for name in ('torch','numpy','transformers','sentence_transformers','ipfs_datasets_py'))
"""
    subprocess.run([sys.executable, "-I", "-c", code, str(PATH)], check=True)


def test_actual_unavailable_parent_exposes_original_caches_without_numerical_imports(monkeypatch):
    path = REPOSITORY.parents[1] / "artifacts/gte-aligned-interface-training-preparation-20261002/run-01/manifest.json"
    if not path.is_file():
        pytest.skip("actual production artifact is outside this checkout")
    old.native_tests._forbid_numerical_imports(monkeypatch)
    result = _admit(path, root=REPOSITORY.parents[1])
    assert result["status"] == "unavailable" and result["trained_checkpoint"] is None
    assert result["training_report"] is result["checkpoint_inspection"] is result["reload_verification"] is None
    plan = result["payloads"]["native_batch"]
    assert len(plan["audit_rows"]) == 242 and plan["ready_row_count"] == 0
    assert len(plan["audit_rows"][180:240]) == 60
    assert all(row["split"] == "validation" for row in plan["audit_rows"][180:240])
    assert len(result["inputs"]) == 8 and len(result["closure"]) == 94


@pytest.mark.parametrize("status", ["unavailable", "prepared", "trained_unqualified"])
def test_saved_parent_is_reconstructed_without_model_imports(publications, monkeypatch, status):
    old.native_tests._forbid_numerical_imports(monkeypatch)
    result = _admit(publications[status])
    assert set(result) == {"payloads", "inputs", "closure", "source_roots", "aligned",
        "trained_checkpoint", "training_report", "checkpoint_inspection", "reload_verification", "status"}
    assert result["status"] == status
    assert len({ref["path"] for ref in result["closure"]}) == len(result["closure"])
    assert all(_receipt(Path(ref["path"])) == ref for ref in result["closure"])
    if status == "trained_unqualified":
        checkpoint, report, verification = (result[key] for key in
            ("trained_checkpoint", "training_report", "reload_verification"))
        assert checkpoint["training_report"] == report and checkpoint["optimizer_steps"] == 3
        assert len(checkpoint["interfaces"]) == 4 and report["all_26_inherited_tensors_unchanged"] is True
        assert checkpoint["representation_id"] != result["aligned"]["checkpoint"]["representation_id"]
        assert verification["model_state_sha256"] == report["model_state_sha256_after"]
        assert verification["trained_reference_outputs_sha256"] == report["trained_reference_outputs_sha256"]
        assert verification["optimizer_created"] is False and verification["optimizer_steps"] == 0
        assert result["checkpoint_inspection"]["training_execution_authenticated"] is False
    else:
        assert result["trained_checkpoint"] is result["training_report"] is None


def test_admitted_parent_payloads_are_private_copies(publications):
    path = publications["trained_unqualified"]
    original = {p: p.read_bytes() for p in path.parent.iterdir() if p.is_file()}
    first = _admit(path)
    first["trained_checkpoint"]["interfaces"].clear()
    first["payloads"]["initialization"].clear()
    first["aligned"]["file_pins"].clear()
    second = _admit(path)
    assert len(second["trained_checkpoint"]["interfaces"]) == 4
    assert len(second["aligned"]["file_pins"]) == 4
    assert second["payloads"]["initialization"]["dimension"] == 768
    assert all(p.read_bytes() == raw for p, raw in original.items())


@pytest.mark.parametrize("key,value", [
    ("completed", False), ("status", "prepared"), ("mode", "prepare"),
    ("training_executed", False), ("optimizer_steps", True), ("trained_checkpoint_count", 0),
    ("saved_trained_checkpoint_authenticated_and_replayed", False),
    ("aligned_start_admitted", False), ("start_representation_id", "forged"),
    ("teacher_qualified", True), ("teacher_qualified", 0), ("outputs", [])])
def test_forged_parent_accounting_fails_before_model_imports(publications, tmp_path, monkeypatch, key, value):
    path = _copy_parent(publications, tmp_path)
    manifest = _read(path)
    manifest[key] = value
    _write(path, manifest)
    old.native_tests._forbid_numerical_imports(monkeypatch)
    with pytest.raises(ValueError):
        _admit(path)


@pytest.mark.parametrize("key,value", [
    ("training_executed", False), ("optimizer_steps", 1), ("native768_inputs_used", False),
    ("inherited_decoder_tensor_count", 25), ("start_representation_id", "forged"),
    ("unavailable_reasons", ["forged"])])
def test_rehashed_summary_tamper_fails_before_model_imports(publications, tmp_path, monkeypatch, key, value):
    path = _copy_parent(publications, tmp_path)
    _replace_output(path, "summary.json", {key: value})
    old.native_tests._forbid_numerical_imports(monkeypatch)
    with pytest.raises(ValueError):
        _admit(path)


@pytest.mark.parametrize("change", ["missing", "reordered", "duplicate", "source_hash", "closure"])
def test_exact_source_and_implementation_closure_is_required(publications, tmp_path, monkeypatch, change):
    path = _copy_parent(publications, tmp_path)
    manifest = _read(path)
    if change == "missing":
        manifest["implementation_files"].pop()
    elif change == "reordered":
        manifest["implementation_files"].reverse()
    elif change == "duplicate":
        manifest["implementation_files"].append(deepcopy(manifest["implementation_files"][0]))
    elif change == "source_hash":
        manifest["parent_closure"][0]["sha256"] = "0" * 64
    else:
        manifest["parent_closure"].append(deepcopy(manifest["inputs"][0]))
    _write(path, manifest)
    old.native_tests._forbid_numerical_imports(monkeypatch)
    with pytest.raises(ValueError):
        _admit(path)


@pytest.mark.parametrize("name,key,value", [
    ("trained-interfaces.json", "teacher_qualified", True),
    ("training-report.json", "optimizer_steps", 2),
    ("checkpoint-inspection.json", "model_state_sha256", "a" * 64),
    ("reload-verification.json", "trained_reference_outputs_sha256", "a" * 64),
    ("reload-verification.json", "optimizer_steps", False),
    ("resources.json", "device", "cuda")])
def test_rehashed_trained_artifacts_are_revalidated(publications, tmp_path, monkeypatch, name, key, value):
    path = _copy_parent(publications, tmp_path)
    _replace_output(path, name, {key: value})
    old.native_tests._forbid_numerical_imports(monkeypatch)
    with pytest.raises(ValueError):
        _admit(path)


def test_unavailable_parent_cannot_add_a_trained_output(publications, tmp_path, monkeypatch):
    path = _copy_parent(publications, tmp_path, status="unavailable")
    manifest = _read(path)
    manifest["outputs"].append(deepcopy(manifest["outputs"][0]))
    _write(path, manifest)
    old.native_tests._forbid_numerical_imports(monkeypatch)
    with pytest.raises(ValueError):
        _admit(path)


def test_evaluation_workspace_cannot_hide_outside_parent_sources(publications, monkeypatch):
    path = publications["unavailable"]
    old.native_tests._forbid_numerical_imports(monkeypatch)
    with pytest.raises(ValueError):
        _admit(path, root=path.parent)
