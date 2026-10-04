"""Preparation integrity and exposure checks without optional model imports."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[5]
SCRIPT = ROOT / "scripts/ops/autoencoder/prepare_gte_migration.py"
spec = importlib.util.spec_from_file_location("gte_preparation_test_subject", SCRIPT)
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
    for name in ("gte_migration_inventory", "gte_transfer_corpus"):
        (helpers / (name + ".py")).write_bytes((subject.HELPERS / (name + ".py")).read_bytes())
    tool = tmp_path / "prepare.py"
    tool.write_bytes(SCRIPT.read_bytes())
    monkeypatch.setattr(subject, "HELPERS", helpers)
    monkeypatch.setattr(subject, "__file__", str(tool))
    checkpoint_sha = write_json(tmp_path / "checkpoint.json", {"schema": "unknown-local-head/v1"})
    data_sha = write_json(tmp_path / "rows.json", {"rows": [{"id": "one", "group_id": "g-one",
        "split": "train", "source_text": "The operator must save the report.",
        "embedding": [1.0, 0.0], "target": {"action": "save"}}]})
    config = {"schema": subject.CONFIG_SCHEMA, "dimension": 2,
        "vector_space_id": "explicit-test-fixture:d2:not-a-real-producer", "max_rows": 10,
        "checkpoints": [{"id": "unknown-head", "path": "checkpoint.json", "sha256": checkpoint_sha}],
        "datasets": [{"id": "diagnostic-train", "path": "rows.json", "sha256": data_sha,
            "domain_id": "legal_ir", "split": "train", "rows_key": "rows",
            "group_field": "group_id", "document_field": "group_id", "source_language": "en",
            "target_origin": "authored", "evaluation_role": "development",
            "source_exposure": "archived_diagnostic_exposed",
            "document_identity_policy": "synthetic_group_is_document_unit"}], "source_files": []}
    path = tmp_path / "config.json"
    write_json(path, config)
    return tmp_path, path, config


def test_run_and_verify_capture_inputs_and_never_claim_qualification(inputs):
    root, path, _ = inputs
    output = root / "run"
    result = subject.run_preparation(path, output, workspace_root=root)
    assert result["input_rows"] == 1
    assert result["teacher_qualified"] is False
    assert result["teacher_replay_executed"] is False
    assert result["sealed_evaluation_rows_declared"] == 0
    checked = subject.verify_preparation(output, expected_manifest_sha256=result["manifest_sha256"],
                                         workspace_root=root)
    assert checked["verified"] is True
    assert checked["input_files"] == 2
    assert checked["source_files"] == 3
    saved = json.loads((output / "corpus-audit.json").read_bytes())
    assert "source_text" not in saved["rows"][0]


@pytest.mark.parametrize("changed", ["rows.json", "checkpoint.json", "helpers/gte_transfer_corpus.py", "run/summary.json", "run/manifest.json"])
def test_verification_rejects_input_implementation_or_report_drift(inputs, changed):
    root, path, _ = inputs
    result = subject.run_preparation(path, root / "run", workspace_root=root)
    with (root / changed).open("ab") as stream:
        stream.write(b" ")
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        subject.verify_preparation(root / "run", expected_manifest_sha256=result["manifest_sha256"],
                                   workspace_root=root)


def test_exposed_canary_cannot_be_relabeled_sealed(inputs):
    root, path, config = inputs
    config["datasets"][0].update(split="canary", evaluation_role="sealed")
    write_json(path, config)
    with pytest.raises(ValueError, match="exposed artifacts"):
        subject.run_preparation(path, root / "run", workspace_root=root)
    assert not (root / "run").exists()


def test_archived_embedding_metadata_is_hashed_without_exporting_payloads(inputs):
    root, path, config = inputs
    data = json.loads((root / "rows.json").read_bytes())
    data["source_embeddings"] = {"source_text": "secret_source_payload",
                                 "embedding": [0.12, 0.34], "target": "secret_target_payload"}
    config["datasets"][0]["sha256"] = write_json(root / "rows.json", data)
    write_json(path, config)
    subject.run_preparation(path, root / "run", workspace_root=root)
    saved = json.loads((root / "run/dataset-inventory.json").read_bytes())
    assert len(saved[0]["archived_embedding_metadata_sha256"]) == 64
    for report in (root / "run").glob("*.json"):
        assert b"secret_source_payload" not in report.read_bytes()
        assert b"secret_target_payload" not in report.read_bytes()


def test_fresh_sealed_declaration_never_claims_verified_sealing(inputs):
    root, path, config = inputs
    data = json.loads((root / "rows.json").read_bytes())
    data["rows"][0]["split"] = "test"
    config["datasets"][0].update(split="test", evaluation_role="sealed", source_exposure="fresh_sealed")
    config["datasets"][0]["sha256"] = write_json(root / "rows.json", data)
    write_json(path, config)
    result = subject.run_preparation(path, root / "run", workspace_root=root)
    assert result["sealed_evaluation_rows_declared"] == 1
    assert result["evaluation_seals_verified"] is False
    saved = json.loads((root / "run/corpus-audit.json").read_bytes())
    assert saved["usable_counts"]["fitting_reference_rows"] == 0
    assert saved["usable_counts"]["selection_reference_rows"] == 0


def test_split_and_pinned_hash_mismatches_stop_before_output(inputs):
    root, path, config = inputs
    config["datasets"][0]["split"] = "validation"
    write_json(path, config)
    with pytest.raises(ValueError, match="declared split"):
        subject.run_preparation(path, root / "run", workspace_root=root)
    config["datasets"][0]["split"] = "train"
    config["datasets"][0]["sha256"] = "0" * 64
    write_json(path, config)
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        subject.run_preparation(path, root / "run", workspace_root=root)
    assert not (root / "run").exists()


def test_workspace_escape_and_existing_output_are_rejected(inputs):
    root, path, config = inputs
    config["checkpoints"][0]["path"] = "../checkpoint.json"
    write_json(path, config)
    with pytest.raises(ValueError, match="traversal"):
        subject.run_preparation(path, root / "run", workspace_root=root)
    (root / "run").mkdir()
    with pytest.raises(ValueError, match="fresh output"):
        subject.run_preparation(path, root / "run", workspace_root=root)


def test_incomplete_run_cannot_verify(inputs):
    root, _, _ = inputs
    (root / "run").mkdir()
    with pytest.raises(FileNotFoundError):
        subject.verify_preparation(root / "run", expected_manifest_sha256="0" * 64,
                                   workspace_root=root)
