"""Cache reuse admission and publication with explicitly synthetic vectors."""
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
PATH = REPOSITORY / "scripts/ops/autoencoder/prepare_gte_embedding_reuse.py"
SPEC = importlib.util.spec_from_file_location("gte_embedding_reuse_cli_test_subject", PATH)
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)


def _raw(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False) + "\n").encode()


def _write(path, value):
    raw = _raw(value)
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def inputs(tmp_path):
    input_directory = tmp_path / "inputs"
    input_directory.mkdir()
    corpus = subject._helper("gte_multilingual_corpus")
    source_id = ("thenlper/gte-small@17e1f347d17fe144873b1201da91788898c639cd:"
        "d384:pool=mean:norm=l2:precision=float32:input_policy=exact_source_no_truncation")
    rows = []
    for index, split in enumerate(("train", "train", "validation")):
        vector = [0.] * 384
        vector[index] = 1.
        rows.append({"id": "synthetic-source" + str(index), "domain_id": "legal_ir",
            "document_id": "synthetic-document" + str(index), "group_id": "synthetic-group" + str(index),
            "split": split, "source_text": "authored cache diagnostic source " + str(index),
            "embedding": vector, "reference_target": {"reference": index},
            "target_origin": "authored", "source_language": "en", "evaluation_role": "development"})
    audit = corpus._AUDIT.audit_transfer_rows(rows, dimension=384, vector_space_id=source_id)
    tasks = corpus.prepare_embedding_tasks(rows, audit)
    config = {"schema": subject.SCHEMA, "workspace_root": str(tmp_path), "mode": "reuse",
        "expected_asset_manifest_sha256": "b" * 64}
    payloads = {"rows_384": rows, "corpus_audit": audit, "tasks": tasks, "receipts_768": []}
    for name, value in payloads.items():
        path = input_directory / (name + ".json")
        config[name] = {"path": str(path.relative_to(tmp_path)), "sha256": _write(path, value)}
    config_path = input_directory / "reuse-config.json"
    return SimpleNamespace(root=tmp_path, path=config_path, pin=_write(config_path, config),
        config=config, payloads=payloads, corpus=corpus, source_id=source_id, output=tmp_path / "reuse-output")


def _repin(inputs):
    inputs.pin = _write(inputs.path, inputs.config)


def _run(inputs, **overrides):
    kwargs = {"expected_config_sha256": inputs.pin, "output_directory": inputs.output}
    kwargs.update(overrides)
    return subject.prepare_embedding_reuse(inputs.path, **kwargs)


def _cache(inputs, count):
    receipts = []
    for index, task in enumerate(inputs.payloads["tasks"]["tasks"][:count]):
        vector = [0] * 768
        vector[index] = 1.
        receipts.append({"schema": inputs.corpus.RECEIPT_SCHEMA, "id": task["id"],
            "source_sha256": task["source_sha256"], "profile_id": inputs.corpus.PROFILE_ID,
            "dimension": 768, "embedding": vector, "token_count_including_special_tokens": 3,
            "token_input_sha256": "a" * 64, "truncated": False, "normalized": True,
            "asset_manifest_sha256": inputs.config["expected_asset_manifest_sha256"]})
    inputs.payloads["receipts_768"] = receipts
    inputs.config["receipts_768"]["sha256"] = _write(inputs.root / inputs.config["receipts_768"]["path"], receipts)
    _repin(inputs)
    return receipts


def _guard_imports(monkeypatch):
    import builtins
    original = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name.split(".")[0] in ("torch", "numpy", "transformers", "sentence_transformers"):
            pytest.fail("reuse must not load model dependencies")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded)


def test_import_loads_no_model_dependencies():
    code = """import importlib.util,sys
spec=importlib.util.spec_from_file_location('isolated_reuse_cli',sys.argv[1])
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
assert not any(name in sys.modules for name in ('torch','numpy','transformers','sentence_transformers'))
"""
    subprocess.run([sys.executable, "-I", "-c", code, str(PATH)], check=True)


@pytest.mark.parametrize("count,status", [(0, "unavailable"), (1, "partial"), (3, "ready")])
def test_reuses_cache_without_assets_inference_or_regenerated_source_vectors(inputs, monkeypatch, count, status):
    cached = _cache(inputs, count)
    retained = {(inputs.root / ref["path"]): (inputs.root / ref["path"]).read_bytes()
        for name, ref in inputs.config.items() if type(ref) is dict}
    _guard_imports(monkeypatch)
    result = _run(inputs)
    assert result["status"] == status
    assert result["archive_384_row_count"] == 3
    assert result["cached_receipt_count"] == count
    assert result["missing_task_count"] == 3 - count
    for flag in ("archive_384_embeddings_regenerated", "embeddings_generated",
                 "encoder_inference_executed", "training_executed"):
        assert result[flag] is False
    assert json.loads((inputs.output / "receipts.json").read_bytes()) == cached
    reused = json.loads((inputs.output / "receipts.json").read_bytes())
    if reused:
        assert type(reused[0]["embedding"][1]) is int
        assert reused[0]["source_sha256"] == cached[0]["source_sha256"]
    missing = json.loads((inputs.output / "missing-tasks.json").read_bytes())
    assert len(missing) == 3 - count
    assert {task["id"] for task in missing}.isdisjoint({row["id"] for row in cached})
    manifest = json.loads((inputs.output / "manifest.json").read_bytes())
    assert manifest["completed"] is True and manifest["status"] == status
    assert {entry["path"] for entry in manifest["outputs"]} == {
        "receipts.json", "missing-tasks.json", "binding.json", "reuse.json", "summary.json"}
    assert hashlib.sha256((inputs.output / "manifest.json").read_bytes()).hexdigest() == result["manifest_sha256"]
    for ref in manifest["outputs"]:
        raw = (inputs.output / ref["path"]).read_bytes()
        assert len(raw) == ref["bytes"] and hashlib.sha256(raw).hexdigest() == ref["sha256"]
    for path, raw in retained.items():
        assert path.read_bytes() == raw


@pytest.mark.parametrize("change", ["extra", "mode", "asset_missing", "asset_short", "asset_uppercase",
    "root_relative", "ref_extra", "ref_absolute", "ref_traversal"])
def test_closed_reuse_configuration_is_required(inputs, change):
    config = inputs.config
    if change == "extra": config["generate_missing"] = True
    if change == "mode": config["mode"] = "embed"
    if change == "asset_missing": del config["expected_asset_manifest_sha256"]
    if change == "asset_short": config["expected_asset_manifest_sha256"] = "b" * 63
    if change == "asset_uppercase": config["expected_asset_manifest_sha256"] = "B" * 64
    if change == "root_relative": config["workspace_root"] = "."
    if change == "ref_extra": config["tasks"]["dimension"] = 768
    if change == "ref_absolute": config["tasks"]["path"] = str(inputs.root / config["tasks"]["path"])
    if change == "ref_traversal": config["tasks"]["path"] = "../tasks.json"
    _repin(inputs)
    with pytest.raises(ValueError):
        _run(inputs)
    assert not inputs.output.exists()


@pytest.mark.parametrize("reference", [None, "rows_384", "corpus_audit", "tasks", "receipts_768"])
def test_every_external_file_pin_is_required(inputs, reference):
    if reference is None:
        kwargs = {"expected_config_sha256": "0" * 64}
    else:
        inputs.config[reference]["sha256"] = "0" * 64
        _repin(inputs)
        kwargs = {}
    with pytest.raises(ValueError, match="SHA256"):
        _run(inputs, **kwargs)
    assert not inputs.output.exists()


def test_repinned_tasks_must_reproduce_from_unchanged_archive(inputs):
    tasks = deepcopy(inputs.payloads["tasks"])
    tasks["tasks"].pop()
    tasks["task_count"] = len(tasks["tasks"])
    tasks["tasks_sha256"] = inputs.corpus._digest(tasks["tasks"])
    inputs.config["tasks"]["sha256"] = _write(inputs.root / inputs.config["tasks"]["path"], tasks)
    _repin(inputs)
    with pytest.raises(ValueError):
        _run(inputs)
    assert not inputs.output.exists()


@pytest.mark.parametrize("change", ["asset", "profile", "width", "source"])
def test_repinned_cache_cannot_relabel_another_producer_or_source(inputs, change):
    receipts = _cache(inputs, 1)
    if change == "asset": receipts[0]["asset_manifest_sha256"] = "c" * 64
    if change == "profile": receipts[0]["profile_id"] = "thenlper/gte-small:384:relabelled"
    if change == "width": receipts[0]["embedding"] = receipts[0]["embedding"][:384]
    if change == "source": receipts[0]["source_sha256"] = "0" * 64
    inputs.config["receipts_768"]["sha256"] = _write(inputs.root / inputs.config["receipts_768"]["path"], receipts)
    _repin(inputs)
    with pytest.raises(ValueError):
        _run(inputs)
    assert not inputs.output.exists()


def test_existing_output_namespace_is_preserved(inputs):
    inputs.output.mkdir()
    marker = inputs.output / "retained.txt"
    marker.write_bytes(b"retained")
    with pytest.raises(ValueError, match="fresh"):
        _run(inputs)
    assert marker.read_bytes() == b"retained"


def test_output_parent_symlink_is_rejected(inputs):
    link = inputs.root / "alias"
    link.symlink_to(inputs.root, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        _run(inputs, output_directory=link / "new-output")
    assert not (inputs.root / "new-output").exists()


def test_output_inside_repository_is_rejected(inputs):
    with pytest.raises(ValueError):
        _run(inputs, output_directory=REPOSITORY / "workspace" / "forbidden-reuse-output")
    assert not (REPOSITORY / "workspace" / "forbidden-reuse-output").exists()


def test_output_inside_archived_input_namespace_is_rejected(inputs):
    output = inputs.root / "inputs" / "forbidden-output"
    with pytest.raises(ValueError, match="namespace"):
        _run(inputs, output_directory=output)
    assert not output.exists()


def test_malformed_quarantined_row_preserves_reusable_archive_and_tasks(inputs, monkeypatch):
    rows = deepcopy(inputs.payloads["rows_384"])
    rows.append(None)
    audit = inputs.corpus._AUDIT.audit_transfer_rows(rows, dimension=384, vector_space_id=inputs.source_id)
    tasks = inputs.corpus.prepare_embedding_tasks(rows, audit)
    assert tasks["task_count"] == 3 and tasks["rejected_row_count"] == 1
    for name, payload in (("rows_384", rows), ("corpus_audit", audit), ("tasks", tasks)):
        inputs.config[name]["sha256"] = _write(inputs.root / inputs.config[name]["path"], payload)
    _repin(inputs)
    retained = (inputs.root / inputs.config["rows_384"]["path"]).read_bytes()
    _guard_imports(monkeypatch)
    result = _run(inputs)
    assert result["archive_384_row_count"] == 4 and result["archive_384_vector_count"] == 3
    assert result["task_count"] == 3 and result["missing_task_count"] == 3
    assert result["archive_384_embeddings_regenerated"] is False
    assert (inputs.root / inputs.config["rows_384"]["path"]).read_bytes() == retained


@pytest.mark.parametrize("late", [False, True])
def test_input_drift_prevents_completion_manifest(inputs, monkeypatch, late):
    original = subject._recheck
    calls = []
    def drift(reader, refs):
        calls.append(1)
        if len(calls) == (2 if late else 1):
            (inputs.root / inputs.config["receipts_768"]["path"]).write_bytes(b"[] \n")
        return original(reader, refs)
    monkeypatch.setattr(subject, "_recheck", drift)
    with pytest.raises(ValueError, match="changed"):
        _run(inputs)
    assert inputs.output.exists() is late
    assert not (inputs.output / "manifest.json").exists()


def test_corrupted_reused_receipts_never_get_completion_manifest(inputs, monkeypatch):
    _cache(inputs, 3)
    original = subject._write
    def corrupt(directory, name, value):
        receipt = original(directory, name, value)
        if name == "receipts.json":
            with (directory / name).open("ab") as stream:
                stream.write(b" ")
        return receipt
    monkeypatch.setattr(subject, "_write", corrupt)
    with pytest.raises(ValueError, match="changed"):
        _run(inputs)
    assert (inputs.output / "receipts.json").exists()
    assert not (inputs.output / "manifest.json").exists()
