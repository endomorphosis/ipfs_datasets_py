"""Reporter fixtures test binding and redaction, not native training success."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def reporter():
    script = Path(__file__).resolve().parents[3] / "scripts/ops/legal_ir/summarize_autoformal_cycle.py"
    spec = importlib.util.spec_from_file_location("autoformal_cycle_summary_under_test", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def evidence(tmp_path, reporter):
    directory = tmp_path / "cycle-one"
    (directory / "training").mkdir(parents=True)
    (tmp_path / "artifacts").mkdir()
    base, candidate = tmp_path / "artifacts/base", directory / "training/candidate.json"
    for path in (base, candidate):
        path.write_bytes(b"unchanged")
    def descriptor(path):
        return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}
    evaluation = {**{key: 1.0 for key in reporter.METRICS}, "decoded_embeddings": {"PRIVATE_CANARY": [1, 2, 3]}}
    report = {"accepted_epochs": 0, "sample_memory_used": False, "epoch_reports": [],
              "rejection_summary": {"attempted_count": 1}, "before": evaluation, "after": evaluation,
              "projection_profile": {"by_stage": {"training_cache_prime": {"seconds": 4.0}}}}
    worker = {"job_id": "one", "job_spec": {"job_id": "one", "code_identity": "code"},
              "execution_mode": "native_training", "admitted": False, "promotion_performed": False,
              "training_report": report, "optimizer_accepted_epochs": 0, "sample_count": 43,
              "validation_sample_count": 3, "base_checkpoint": descriptor(base), "candidate": descriptor(candidate),
              "base_state_identity": {"digest": "same"}, "candidate_state_identity": {"digest": "same"}}
    cycle = {"cycle_id": "one", "code_identity": "code", "stage": "native_training_and_repair_queue",
             "training_report": report, "optimizer_accepted_epochs": 0,
             "model_identity": "sha256:" + worker["candidate"]["sha256"], "candidate_version_id": "private-one",
             "agreement": [{"rows": [{"text": "PRIVATE_SOURCE", "agrees": False}]}],
             "queue_receipts": [{"task_count": 0}], "wall_seconds": 5.0,
             "admitted": False, "formalized": False, "production_promotion": False}
    def save():
        (directory / "cycle.json").write_text(json.dumps(cycle))
        (directory / "training/receipt.json").write_text(json.dumps(worker))
    save()
    return directory, cycle, worker, save


def test_summary_does_not_expose_sources_vectors_or_turn_rejection_into_learning(evidence, reporter):
    result = reporter.summarize(evidence[0])
    assert result["attempted_updates"] == 1 and result["accepted_epochs"] == 0
    assert result["artifact_bytes_changed"] is False and result["reported_model_state_changed"] is False
    assert result["compiler_discrepancies"] == 1 and result["diagnostic_only"] is True
    assert "PRIVATE" not in json.dumps(result)
    assert result["profile_durations_overlap"] is True


@pytest.mark.parametrize("change", ["job", "training", "promotion", "accepted", "memory"])
def test_mismatched_or_untrusted_receipt_is_rejected(evidence, reporter, change):
    directory, cycle, worker, save = evidence
    if change == "job":
        worker["job_id"] = "different"
    elif change == "training":
        worker["execution_mode"] = "injected_test"
    elif change == "promotion":
        cycle["production_promotion"] = True
    elif change == "accepted":
        worker["optimizer_accepted_epochs"] = True
    else:
        worker["training_report"]["sample_memory_used"] = True
    save()
    with pytest.raises(ValueError):
        reporter.summarize(directory)


def test_checkpoint_bytes_are_verified(evidence, reporter):
    directory, _, worker, _ = evidence
    Path(worker["candidate"]["path"]).write_bytes(b"tampered!")
    with pytest.raises(ValueError, match="checkpoint bytes"):
        reporter.summarize(directory)


def test_changed_artifact_is_not_itself_an_optimizer_update(evidence, reporter):
    directory, cycle, worker, save = evidence
    path = Path(worker["candidate"]["path"])
    path.write_bytes(b"different serialization")
    worker["candidate"].update(bytes=path.stat().st_size,
                                sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    cycle["model_identity"] = "sha256:" + worker["candidate"]["sha256"]
    save()
    result = reporter.summarize(directory)
    assert result["artifact_bytes_changed"] is True
    assert result["accepted_epochs"] == 0 and result["reported_model_state_changed"] is False
    assert result["production_promotion"] is False


def test_existing_report_is_never_overwritten(evidence, reporter):
    directory = evidence[0]
    output = directory / "summary.json"
    reporter.main([str(directory), "--output", str(output)])
    original = output.read_bytes()
    with pytest.raises(FileExistsError):
        reporter.main([str(directory), "--output", str(output)])
    assert output.read_bytes() == original
