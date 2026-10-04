"""Offline CLI integrity, source-only preparation and unavailable-path tests."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[5]
SCRIPT = ROOT / "scripts/ops/autoencoder/prepare_gte_multilingual.py"
spec = importlib.util.spec_from_file_location("gte_multilingual_cli_test_subject", SCRIPT)
subject = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = subject
spec.loader.exec_module(subject)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, allow_nan=False) + "\n")
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    helpers = tmp_path / "helpers"
    helpers.mkdir()
    for name in ("gte_worker_contract", "gte_transfer_corpus", "gte_multilingual_corpus",
                 "gte_multilingual_profile", "source_embeddings_768"):
        (helpers / (name + ".py")).write_bytes((subject.HELPERS / (name + ".py")).read_bytes())
    tool = tmp_path / "prepare.py"
    tool.write_bytes(SCRIPT.read_bytes())
    monkeypatch.setattr(subject, "HELPERS", helpers)
    monkeypatch.setattr(subject, "__file__", str(tool))
    rows = []
    for index, split in enumerate(("train", "validation")):
        rows.append({"id": "source-" + str(index), "domain_id": "legal_ir",
                     "document_id": "document-" + str(index), "group_id": "group-" + str(index),
                     "split": split, "source_text": "The office must retain record " + str(index) + ".",
                     "embedding": None, "reference_target": {"secret_target_payload": index},
                     "target_origin": "authored", "source_language": "en",
                     "evaluation_role": "development"})
    audit = subject._helper("gte_transfer_corpus").audit_transfer_rows(
        rows, dimension=384, vector_space_id="synthetic-gte-small-not-producer-authenticated")
    row_path, audit_path = tmp_path / "rows.json", tmp_path / "audit.json"
    row_sha, audit_sha = write_json(row_path, rows), write_json(audit_path, audit)
    return SimpleNamespace(root=tmp_path, rows=rows, row_path=row_path, row_sha=row_sha,
                           audit=audit, audit_path=audit_path, audit_sha=audit_sha, helpers=helpers)


def prepare(inputs, output=None):
    return subject.prepare_tasks(inputs.row_path, expected_rows_sha256=inputs.row_sha,
                                 corpus_audit_path=inputs.audit_path,
                                 expected_audit_sha256=inputs.audit_sha,
                                 output_directory=output or inputs.root / "prepared")


def embed(inputs, tasks_path, tasks_sha, output=None, **overrides):
    options = {"manifest_path": inputs.root / "missing-assets.json", "expected_manifest_sha256": None,
               "model_directory": inputs.root / "missing-model", "code_directory": inputs.root / "missing-code",
               "output_directory": output or inputs.root / "embedded"}
    options.update(overrides)
    return subject.embed_tasks(tasks_path, expected_tasks_sha256=tasks_sha, **options)


def test_prepare_preserves_source_identity_and_hashed_supervision(inputs):
    result = prepare(inputs)
    output = inputs.root / "prepared"
    assert result["status"] == "prepared"
    assert result["model_execution_attempted"] is False
    assert result["task_count"] == 2
    tasks = json.loads((output / "tasks.json").read_bytes())
    by_id = {task["metadata"]["source_id"]: task for task in tasks["tasks"]}
    for row in inputs.rows:
        task = by_id[row["id"]]
        assert task["source_text"] == row["source_text"]
        assert task["metadata"]["split"] == row["split"]
        assert task["metadata"]["reference_target_sha256"]
    for path in output.glob("*.json"):
        assert b"secret_target_payload" not in path.read_bytes()
    binding = json.loads((output / "binding.json").read_bytes())
    assert binding["status"] == "incomplete"
    assert binding["accepted_count"] == 0
    manifest = json.loads((output / "manifest.json").read_bytes())
    assert manifest["completed"] is True
    assert manifest["captured_at_utc"].endswith("+00:00")
    assert len(manifest["inputs"]) == 2
    assert len(manifest["implementation_files"]) == 4
    for receipt in manifest["outputs"]:
        assert hashlib.sha256((output / receipt["path"]).read_bytes()).hexdigest() == receipt["sha256"]
    assert hashlib.sha256((output / "manifest.json").read_bytes()).hexdigest() == result["manifest_sha256"]


@pytest.mark.parametrize("which", ["rows", "audit"])
def test_prepare_rejects_wrong_input_pins_before_output(inputs, which):
    setattr(inputs, "row_sha" if which == "rows" else "audit_sha", "0" * 64)
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        prepare(inputs)
    assert not (inputs.root / "prepared").exists()


def test_prepare_recomputes_audit_instead_of_trusting_matching_file_pin(inputs):
    inputs.rows[0]["reference_target"] = {"changed": True}
    inputs.row_sha = write_json(inputs.row_path, inputs.rows)
    with pytest.raises(ValueError, match="does not exactly match"):
        prepare(inputs)
    assert not (inputs.root / "prepared").exists()


def test_no_output_overwrite(inputs):
    prepare(inputs)
    before = (inputs.root / "prepared/manifest.json").read_bytes()
    with pytest.raises(ValueError, match="must be fresh"):
        prepare(inputs)
    assert (inputs.root / "prepared/manifest.json").read_bytes() == before


def test_output_cannot_write_under_implementation_namespace(inputs):
    with pytest.raises(ValueError, match="implementation or asset namespace"):
        prepare(inputs, inputs.helpers / "new-run")
    assert not (inputs.helpers / "new-run").exists()


def test_prepare_does_not_select_a_subset_above_row_limit(inputs):
    inputs.row_sha = write_json(inputs.row_path, inputs.rows * 2049)
    with pytest.raises(ValueError, match="at most 4096"):
        prepare(inputs)
    assert not (inputs.root / "prepared").exists()


def test_prepare_source_byte_budget_is_explicit(inputs, monkeypatch):
    monkeypatch.setattr(subject, "MAX_SOURCE_BYTES", 1)
    with pytest.raises(ValueError, match="UTF8 limit"):
        prepare(inputs)
    assert not (inputs.root / "prepared").exists()


@pytest.mark.parametrize("source", ["x" * 65537, "Text with\0a NUL"])
def test_prepare_rejects_sources_outside_producer_bounds(inputs, source):
    inputs.rows[0]["source_text"] = source
    inputs.row_sha = write_json(inputs.row_path, inputs.rows)
    inputs.audit = subject._helper("gte_transfer_corpus").audit_transfer_rows(
        inputs.rows, dimension=384, vector_space_id=inputs.audit["profile"]["vector_space_id"])
    inputs.audit_sha = write_json(inputs.audit_path, inputs.audit)
    with pytest.raises(ValueError, match="65536 characters"):
        prepare(inputs)
    assert not (inputs.root / "prepared").exists()


@pytest.mark.parametrize("changed", ["input", "implementation"])
def test_input_and_tool_drift_prevent_completion_manifest(inputs, monkeypatch, changed):
    original = subject._helper

    def altered(name):
        helper = original(name)
        if name == "gte_multilingual_corpus":
            real_prepare = helper.prepare_embedding_tasks

            def mutate(*args, **kwargs):
                result = real_prepare(*args, **kwargs)
                path = inputs.row_path if changed == "input" else inputs.helpers / "gte_transfer_corpus.py"
                with path.open("ab") as stream:
                    stream.write(b"\n")
                return result

            helper.prepare_embedding_tasks = mutate
        return helper

    monkeypatch.setattr(subject, "_helper", altered)
    with pytest.raises(ValueError, match="SHA256"):
        prepare(inputs)
    assert not (inputs.root / "prepared/manifest.json").exists()


def test_missing_assets_write_incomplete_embed_receipts(inputs):
    prepare(inputs)
    path = inputs.root / "prepared/tasks.json"
    pin = hashlib.sha256(path.read_bytes()).hexdigest()
    result = embed(inputs, path, pin)
    assert result["status"] == "unavailable"
    assert result["model_execution_attempted"] is False
    assert result["accepted_count"] == 0
    assert json.loads((inputs.root / "embedded/receipts.json").read_bytes()) == []
    binding = json.loads((inputs.root / "embedded/binding.json").read_bytes())
    assert binding["status"] == "incomplete" and len(binding["missing_receipt_ids"]) == 2


def test_embed_validates_full_tasks_before_model_work(inputs):
    prepare(inputs)
    path = inputs.root / "prepared/tasks.json"
    tasks = json.loads(path.read_bytes())
    tasks["tasks"][0]["metadata"]["split"] = "test"
    pin = write_json(path, tasks)
    with pytest.raises(ValueError, match="tasks_sha256"):
        embed(inputs, path, pin)
    assert not (inputs.root / "embedded").exists()


def test_embed_does_not_write_inside_missing_asset_roots(inputs):
    prepare(inputs)
    path = inputs.root / "prepared/tasks.json"
    pin = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="asset namespace"):
        embed(inputs, path, pin, inputs.root / "missing-model/run")
    assert not (inputs.root / "missing-model").exists()


def test_inspector_preserves_asset_symlinks_for_rejection(inputs):
    actual = inputs.root / "actual-model"
    actual.mkdir()
    alias = inputs.root / "model-link"
    alias.symlink_to(actual, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink|ordinary"):
        subject.inspect_assets(manifest_path=inputs.root / "missing-manifest",
                               expected_manifest_sha256=None, model_directory=alias,
                               code_directory=inputs.root / "code", report_file=inputs.root / "report.json")
    assert not (inputs.root / "report.json").exists()


def test_report_cannot_materialize_a_missing_asset_manifest(inputs):
    missing = inputs.root / "missing-manifest.json"
    with pytest.raises(ValueError, match="aliases the asset manifest"):
        subject.inspect_assets(manifest_path=missing, expected_manifest_sha256=None,
                               model_directory=inputs.root / "model", code_directory=inputs.root / "code",
                               report_file=missing)
    assert not missing.exists()


def test_synthetic_producer_receives_only_id_and_source_text(inputs, monkeypatch):
    prepare(inputs)
    path = inputs.root / "prepared/tasks.json"
    pin = hashlib.sha256(path.read_bytes()).hexdigest()
    asset_path = inputs.root / "synthetic-assets.json"
    asset_pin = write_json(asset_path, {"test_only": True})
    corpus = subject._helper("gte_multilingual_corpus")
    seen = []
    original = subject._helper

    def produce(rows, **kwargs):
        seen.extend(rows)
        receipts = [{"schema": corpus.RECEIPT_SCHEMA, "id": row["id"],
                     "source_sha256": hashlib.sha256(row["source_text"].encode()).hexdigest(),
                     "profile_id": corpus.PROFILE_ID, "dimension": 768,
                     "embedding": [1.0] + [0.0] * 767,
                     "token_count_including_special_tokens": 7, "token_input_sha256": "d" * 64,
                     "truncated": False, "normalized": True,
                     "asset_manifest_sha256": asset_pin} for row in rows]
        return {"status": "completed", "receipts": receipts, "model_inference_executed": True,
                "assets": {"status": "available", "manifest_sha256": asset_pin},
                "synthetic_test_backend": True}

    def helpers(name):
        if name == "source_embeddings_768":
            return SimpleNamespace(embed_rows=produce)
        if name == "gte_multilingual_profile":
            return SimpleNamespace(inspect_local_assets=lambda *a, **k:
                                   {"status": "available", "manifest_sha256": asset_pin})
        return original(name)

    monkeypatch.setattr(subject, "_helper", helpers)
    result = embed(inputs, path, pin, manifest_path=asset_path, expected_manifest_sha256=asset_pin)
    assert result["status"] == "complete"
    assert len(seen) == 2 and all(set(row) == {"id", "source_text"} for row in seen)
    binding = json.loads((inputs.root / "embedded/binding.json").read_bytes())
    assert binding["accepted_count"] == 2
    assert binding["vectors_producer_verified"] is False
    assert binding["reference_targets_exported"] is False


@pytest.mark.parametrize("command", ["prepare", "inspect-assets", "embed"])
def test_offline_commands_do_not_import_tensor_libraries_when_assets_missing(inputs, command):
    if command == "prepare":
        arguments = [command, "--rows-file", str(inputs.row_path), "--expected-rows-sha256", inputs.row_sha,
                     "--corpus-audit-file", str(inputs.audit_path), "--expected-audit-sha256", inputs.audit_sha,
                     "--output-directory", str(inputs.root / "guard-prepared")]
        expected_exit = 0
    else:
        arguments = [command, "--asset-manifest", str(inputs.root / "missing-assets.json"),
                     "--model-directory", str(inputs.root / "missing-model"),
                     "--code-directory", str(inputs.root / "missing-code")]
        if command == "inspect-assets":
            arguments += ["--report-file", str(inputs.root / "guard-report.json")]
        else:
            prepare(inputs)
            path = inputs.root / "prepared/tasks.json"
            arguments += ["--tasks-file", str(path), "--expected-tasks-sha256",
                          hashlib.sha256(path.read_bytes()).hexdigest(),
                          "--output-directory", str(inputs.root / "guard-embedded")]
        expected_exit = 1
    code = """import builtins, runpy, sys
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split('.')[0] in {'torch', 'transformers', 'sentence_transformers', 'tokenizers', 'numpy'}:
        raise AssertionError('unexpected model import: ' + name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
sys.argv = [sys.argv[1], *sys.argv[2:]]
runpy.run_path(sys.argv[0], run_name='__main__')
"""
    result = subprocess.run([sys.executable, "-c", code, str(SCRIPT), *arguments],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == expected_exit, result.stderr
    assert "unexpected model import" not in result.stderr


def test_cli_pin_error_exit_is_distinct_from_unavailable(inputs, capsys):
    code = subject.main(["prepare", "--rows-file", str(inputs.row_path), "--expected-rows-sha256", "0" * 64,
                         "--corpus-audit-file", str(inputs.audit_path), "--expected-audit-sha256", inputs.audit_sha,
                         "--output-directory", str(inputs.root / "bad-run")])
    assert code == 2
    assert "SHA256 mismatch" in capsys.readouterr().err
    assert not (inputs.root / "bad-run").exists()
