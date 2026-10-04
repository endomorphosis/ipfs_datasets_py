"""Configuration, readiness metadata and pre-inference orchestration guards."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import (
    alignment_checkpoint_experiment as subject,
)

ROOT = Path(__file__).resolve().parents[5]


def config():
    return {"schema": subject.CONFIG_SCHEMA, "study_id": "autoformalization-checkpoint-development-v1",
        **{name: {"path": name + ".json", "sha256": "a" * 64} for name in (
            "context_report", "source384_checkpoint", "spacy_manifest", "spacy_core", "parallel_lineages")},
        "preserved_repository_root": "/test-only/preserved-sources", "max_seconds": 30}


@pytest.mark.parametrize("field,value", [("schema", "unknown"), ("study_id", "other"),
    ("max_seconds", True), ("max_seconds", 0), ("max_seconds", 601), ("max_seconds", 10**500),
    ("max_seconds", float("inf")), ("preserved_repository_root", "relative"),
    ("context_report", {"path": "x", "sha256": "a" * 63}),
    ("context_report", {"path": "x\x00y", "sha256": "a" * 64}),
    ("context_report", {"path": "x", "sha256": "a" * 64, "extra": 1})])
def test_closed_configuration_rejects_drift(tmp_path, field, value):
    settings = config()
    settings[field] = value
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(settings))
    with pytest.raises(ValueError):
        subject._config(path)


def test_configuration_binding_preserves_real_path_and_unknown_fields_fail(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(config()))
    parsed, binding = subject._config(path)
    assert parsed == config() and binding["path"] == str(path.absolute())
    settings = config()
    settings["extra"] = False
    path.write_text(json.dumps(settings))
    with pytest.raises(ValueError, match="closed"):
        subject._config(path)


def test_duplicate_json_configuration_fields_are_rejected(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"schema":"a","schema":"b"}')
    with pytest.raises(ValueError):
        subject._config(path)


def test_changed_predecessor_binding_fails_before_output_or_models(tmp_path):
    settings = config()
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(settings))
    (tmp_path / "context_report.json").write_text("{}")
    output = tmp_path / "new-output"
    with pytest.raises(ValueError, match="digest mismatch"):
        subject.run_checkpoint_experiment(path, ROOT, tmp_path, output)
    assert not output.exists()


def test_existing_output_and_wrong_repository_are_rejected(tmp_path):
    output = tmp_path / "output"
    output.mkdir()
    with pytest.raises(ValueError, match="fresh"):
        subject.run_checkpoint_experiment(tmp_path / "unused", ROOT, tmp_path, output)
    with pytest.raises(ValueError, match="canonical"):
        subject.run_checkpoint_experiment(tmp_path / "unused", tmp_path, tmp_path, tmp_path / "unused-output")


def test_source_scope_cannot_be_granted_by_metadata():
    for key in ("qualified", "proof_authority", "source_fidelity_established"):
        value = dict.fromkeys(("qualified", "proof_authority", "source_fidelity_established"), False)
        value[key] = True
        with pytest.raises(ValueError, match="authority"):
            subject._scope(value)


def test_cli_success_and_failure_are_self_contained(tmp_path, monkeypatch, capsys):
    path = ROOT / "scripts/ops/legal_ir/run_alignment_checkpoint_experiment.py"
    spec = importlib.util.spec_from_file_location("checkpoint_cli", path)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    monkeypatch.setattr(subject, "run_checkpoint_experiment", lambda *args: {
        "status": "completed", "representation_status": "diagnostic_fixture", "checkpoint_inference_rows": 34,
        "retrieval_summaries": {}, "report_sha256": "a" * 64})
    assert cli.main(["--output-directory", str(tmp_path / "output")]) == 0
    value = json.loads(capsys.readouterr().out)
    assert value["representation_status"] == "diagnostic_fixture" and value["qualified"] is False
    def fail(*args):
        raise ValueError("fixture admission failed")
    monkeypatch.setattr(subject, "run_checkpoint_experiment", fail)
    assert cli.main(["--output-directory", str(tmp_path / "output")]) == 2
    assert json.loads(capsys.readouterr().err)["reason"] == "fixture admission failed"
