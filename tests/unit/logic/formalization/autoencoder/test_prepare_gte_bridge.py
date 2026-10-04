"""Bridge CLI checks use synthetic archive data and never fit a model."""
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

REPOSITORY = Path(__file__).resolve().parents[5]
PATH = REPOSITORY / "scripts/ops/autoencoder/prepare_gte_bridge.py"
SPEC = importlib.util.spec_from_file_location("bridge_preparation_cli_under_test", PATH)
subject = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(subject)
corpus = subject._helper("gte_multilingual_corpus")
SOURCE_ID = ("thenlper/gte-small@17e1f347d17fe144873b1201da91788898c639cd:"
             "d384:pool=mean:norm=l2:precision=float32:input_policy=exact_source_no_truncation")


def write(path, value):
    raw = subject._raw(value)
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    rows = []
    for index, split in enumerate(("train", "validation")):
        embedding = [0.] * 384
        embedding[index] = 1.
        rows.append({"id": "row" + str(index), "domain_id": "legal_ir",
            "document_id": "doc" + str(index), "group_id": "group" + str(index),
            "split": split, "source_text": "distinct exact source " + str(index),
            "embedding": embedding, "reference_target": {"reference": index},
            "target_origin": "authored", "source_language": "en", "evaluation_role": "development"})
    audit = corpus._AUDIT.audit_transfer_rows(rows, dimension=384, vector_space_id=SOURCE_ID)
    tasks = corpus.prepare_embedding_tasks(rows, audit)
    checkpoint = {"schema": "synthetic-checkpoint-for-cli-stub/v1"}
    payloads = {"rows_384": rows, "corpus_audit": audit, "tasks": tasks,
                "receipts_768": [], "teacher_checkpoint": checkpoint}
    config = {"schema": subject.CONFIG_SCHEMA, "workspace_root": str(tmp_path),
              "domain_id": "legal_ir", "max_rows": 4096, "mode": "prepare", "seed": 1729}
    for name, value in payloads.items():
        path = tmp_path / (name + ".json")
        config[name] = {"path": path.name, "sha256": write(path, value)}
    config_path = tmp_path / "config.json"
    pin = write(config_path, config)
    real_helper = subject._helper
    binding = {"schema": "gte-bridge-teacher-binding/v1", "teacher_runtime_id": "legal_ir:source_training_v2",
               "source_representation_id": SOURCE_ID, "teacher_qualified": False}
    monkeypatch.setattr(subject, "_helper", lambda name:
        SimpleNamespace(inspect_teacher=lambda *a, **k: dict(binding))
        if name == "gte_bridge_teacher" else real_helper(name))
    return config_path, pin, config, payloads, binding


def run(inputs, tmp_path):
    path, pin, *_ = inputs
    return subject.prepare_bridge(path, expected_config_sha256=pin, output_directory=tmp_path / "output")


def test_missing_embeddings_publishes_unavailable_with_zero_pairs(inputs, tmp_path):
    result = run(inputs, tmp_path)
    assert result["status"] == "unavailable" and result["pair_count"] == 0
    assert result["teacher_qualified"] is False
    assert result["teacher_model_loaded"] is False and result["training_executed"] is False
    manifest = json.loads((tmp_path / "output/manifest.json").read_text())
    assert manifest["completed"] is True
    assert manifest["status"] == "unavailable"
    assert manifest["captured_at_utc"].endswith("+00:00")
    pairs = json.loads((tmp_path / "output/pairs.json").read_text())
    assert pairs["pairs"] == [] and len(pairs["missing_eligible_pair_receipt_ids"]) == 2
    for entry in manifest["outputs"]:
        raw = (tmp_path / "output" / entry["path"]).read_bytes()
        assert len(raw) == entry["bytes"] and hashlib.sha256(raw).hexdigest() == entry["sha256"]


def test_complete_synthetic_pairs_preserve_splits_without_targets(inputs, tmp_path):
    path, _, config, payloads, _ = inputs
    receipts = []
    for index, task in enumerate(payloads["tasks"]["tasks"]):
        vector = [0.] * 768
        vector[index] = 1.
        receipts.append({"schema": corpus.RECEIPT_SCHEMA, "id": task["id"],
            "source_sha256": task["source_sha256"], "profile_id": corpus.PROFILE_ID,
            "dimension": 768, "embedding": vector, "token_count_including_special_tokens": 3,
            "token_input_sha256": "a" * 64, "truncated": False, "normalized": True,
            "asset_manifest_sha256": "b" * 64})
    config["receipts_768"]["sha256"] = write(tmp_path / "receipts_768.json", receipts)
    pin = write(path, config)
    result = subject.prepare_bridge(path, expected_config_sha256=pin, output_directory=tmp_path / "output")
    assert result["status"] == "ready" and result["pair_count"] == 2
    assert result["pair_split_counts"] == {"train": 1, "validation": 1}
    pairs = json.loads((tmp_path / "output/pairs.json").read_text())
    assert all("reference_target" not in pair and "target" not in pair for pair in pairs["pairs"])
    assert result["native_768d_inference_executed"] is False
    assert result["teacher_qualified"] is False


@pytest.mark.parametrize("change", ["extra", "mode", "domain", "max_rows", "seed", "absolute", "traversal", "reference_extra"])
def test_closed_configuration_rejects_unsupported_changes(inputs, tmp_path, change):
    path, _, config, *_ = inputs
    if change == "extra": config["fit_now"] = True
    if change == "mode": config["mode"] = "train"
    if change == "domain": config["domain_id"] = "unknown_ir"
    if change == "max_rows": config["max_rows"] = True
    if change == "seed": config["seed"] = -1
    if change == "absolute": config["rows_384"]["path"] = str(tmp_path / "rows_384.json")
    if change == "traversal": config["rows_384"]["path"] = "../rows_384.json"
    if change == "reference_extra": config["rows_384"]["targets_are_neural_input"] = True
    pin = write(path, config)
    with pytest.raises(ValueError):
        subject.prepare_bridge(path, expected_config_sha256=pin, output_directory=tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_configuration_pin_and_input_pin_fail_before_publication(inputs, tmp_path):
    path, pin, *_ = inputs
    with pytest.raises(ValueError, match="SHA256"):
        subject.prepare_bridge(path, expected_config_sha256="0" * 64, output_directory=tmp_path / "output")
    (tmp_path / "tasks.json").write_text("{}\n")
    with pytest.raises(ValueError, match="SHA256"):
        run(inputs, tmp_path)
    assert not (tmp_path / "output").exists()


def test_existing_output_is_never_overwritten(inputs, tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    original = output / "existing.json"
    original.write_bytes(b"retained")
    with pytest.raises(ValueError, match="fresh"):
        run(inputs, tmp_path)
    assert original.read_bytes() == b"retained"


def test_teacher_alignment_coordinates_must_match(inputs, tmp_path):
    inputs[-1]["source_representation_id"] = "different-vector-space"
    with pytest.raises(ValueError, match="source coordinates"):
        run(inputs, tmp_path)
    assert not (tmp_path / "output").exists()


def test_helper_drift_rejects_completion_manifest(inputs, tmp_path, monkeypatch):
    original = subject._file
    calls = {}
    def drift(path):
        receipt = original(path)
        calls[receipt["path"]] = calls.get(receipt["path"], 0) + 1
        if receipt["path"] == str(PATH) and calls[receipt["path"]] > 1:
            receipt["sha256"] = "0" * 64
        return receipt
    monkeypatch.setattr(subject, "_file", drift)
    with pytest.raises(ValueError, match="implementation changed"):
        run(inputs, tmp_path)
    assert not (tmp_path / "output/manifest.json").exists()


def test_prepare_does_not_import_numerical_packages(inputs, tmp_path, monkeypatch):
    import builtins
    real_import = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name.split(".")[0] in ("torch", "transformers", "numpy", "sentence_transformers"):
            pytest.fail("preparation must use standard library only")
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded)
    result = run(inputs, tmp_path)
    assert result["status"] == "unavailable"


def test_cli_unavailable_and_invalid_exit_codes(inputs, tmp_path, capsys):
    path, pin, *_ = inputs
    assert subject.main(["prepare", "--config", str(path), "--expected-config-sha256", pin,
                         "--output-directory", str(tmp_path / "output")]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["pair_count"] == 0
    assert subject.main(["prepare", "--config", str(path), "--expected-config-sha256", "0" * 64,
                         "--output-directory", str(tmp_path / "second")]) == 2
    assert json.loads(capsys.readouterr().err)["status"] == "invalid"

