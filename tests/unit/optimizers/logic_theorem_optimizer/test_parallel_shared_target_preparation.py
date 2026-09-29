"""Shared target handoff retains native timeout objectives across worker jobs.

Bridge generation and optimizer execution are fixtures; real sample building,
bundle serialization, artifact validation and target-payload evaluation run.
This is not native-training speed or qualification evidence.
"""
from dataclasses import asdict, replace
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.logic.bridge.multiview import LegalIRTrainingTarget
from ipfs_datasets_py.logic.bridge.types import LegalIRDocument
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_target_preparation as prep
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as modal
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_bundle import load_target_artifact
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_snapshot import TargetSnapshotConfig
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    records = [
        worker.SampleRecord("5", "training", "The agency shall not disclose records.",
                            embedding_model="fixture-provided", embedding_vector=(0.25, 0.75)),
        worker.SampleRecord("5", "tuning", "The officer shall retain the file for at least 20 days.",
                            embedding_model="fixture-provided", embedding_vector=(0.75, 0.25)),
    ]
    config = TargetSnapshotConfig(worker.BRIDGE_NAMES, False, 1, {"fixture": "0" * 64},
                                  {"target_timeout_enforcement": "fixture"})
    monkeypatch.setattr(prep, "target_snapshot_config", lambda _: config)
    original_targets = {}
    calls = []

    def generate(callback, **kwargs):
        calls.append(kwargs)
        assert kwargs["cache"] is kwargs["evaluate_provers"] is False
        assert kwargs["bridge_names"] == worker.BRIDGE_NAMES
        if kwargs["text"] == records[0].text:
            raise modal._LegalIRTargetTimeout("fixture native timeout, no report")
        target = LegalIRTrainingTarget(
            worker.BRIDGE_NAMES,
            LegalIRDocument(kwargs["document_id"], kwargs["text"], kwargs["text"],
                            source=kwargs["source"], citation=kwargs["citation"]),
            {"legal_ir_multiview_total_loss": .75}, {}, {"deontic.ir": 1.0}, False)
        original_targets[kwargs["document_id"]] = target
        return SimpleNamespace(training_target=lambda: target, bridge_names=worker.BRIDGE_NAMES,
                               reports={}, failures={}, accepted=False)

    monkeypatch.setattr(modal, "_evaluate_legal_ir_multiview_with_timeout", generate)
    receipt = prep.prepare_training_targets(records[:1], tmp_path / "targets.bundle",
        validation_records=records[1:], artifact_format="bundle")
    samples = [build_us_code_sample(**asdict(row)) for row in records]
    timeout_sample = samples[0]
    original_targets[timeout_sample.sample_id] = modal._legal_ir_timeout_training_target(
        timeout_sample, bridge_names=worker.BRIDGE_NAMES,
        cache_key=modal._legal_ir_target_cache_key(timeout_sample, bridge_names=worker.BRIDGE_NAMES,
                                                  evaluate_provers=False),
        timeout_seconds=config.target_timeout_seconds)
    assert len(calls) == 2
    monkeypatch.setattr(modal, "_evaluate_legal_ir_multiview_with_timeout",
                        lambda *args, **kwargs: pytest.fail("target regenerated after shared preparation"))
    return records, samples, original_targets, receipt, config


def test_bundle_preserves_timeout_and_full_target_payloads(prepared):
    records, samples, originals, receipt, config = prepared
    assert receipt["model_independent_targets"] is True
    assert receipt["timeout_fallback_count"] == receipt["returned_report_count"] == 1
    assert receipt["bridge_failure_sample_count"] == 0
    assert receipt["split_target_status_counts"] == {"training": {"timeout": 1}, "validation": {"ready": 1}}
    assert receipt["training_executed"] is receipt["admitted"] is False
    with load_target_artifact(receipt["artifact"]["path"],
                              expected_sha256=receipt["artifact"]["sha256"], config=config) as snapshot:
        targets = snapshot.targets_for(samples, config=config)
        assert targets == originals
        assert modal._legal_ir_target_payload(samples, legal_ir_targets=targets) == \
               modal._legal_ir_target_payload(samples, legal_ir_targets=originals)
        assert targets[samples[0].sample_id].accepted is False
        assert targets[samples[0].sample_id].document.canonical_hash().startswith("timeout-fallback:")


def test_shared_native_and_timeout_targets_are_reused_across_candidate_jobs(prepared, tmp_path):
    records, samples, originals, preparation, config = prepared
    checkpoint = tmp_path / "seed.json"
    raw = (modal.ModalAutoencoderTrainingState().to_json() + "\n").encode()
    checkpoint.write_bytes(raw)
    artifact_before = Path(preparation["artifact"]["path"]).read_bytes()
    consumed = []

    def trainer(model, training, *, validation_samples, **kwargs):
        targets = kwargs["legal_ir_targets"]
        assert targets == originals
        consumed.append(modal._legal_ir_target_payload(
            [*training, *validation_samples], legal_ir_targets=targets))
        return {"accepted_epochs": 0, "stopped_reason": "fixture_no_optimizer_execution"}

    receipts = []
    for index, learning_rate in enumerate((.175, .7)):
        spec = worker.TrainingJobSpec.from_dict({
            "job_id": f"job-{index}", "run_id": "fixture", "base_version_id": "seed",
            "base_checkpoint": {"path": str(checkpoint), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)},
            "output_directory": str(tmp_path / f"job-{index}"),
            "code_identity": "fixture", "dataset_snapshot_id": "fixture", "split_snapshot_id": "fixture",
            "samples": [asdict(records[0])], "validation_samples": [asdict(records[1])],
            "autoencoder_config": {"compute_device": "python"},
            "training_config": {"learning_rate": learning_rate},
            "target_snapshot_id": preparation["target_snapshot_id"],
            "target_snapshot_artifact": preparation["artifact"],
        })
        receipts.append(worker.execute_training_job(spec, trainer=trainer))
    assert consumed[0] == consumed[1]
    for receipt in receipts:
        assert receipt["shared_targets_verified"] is True
        assert receipt["shared_target_count"] == 2
        assert receipt["shared_timeout_fallback_count"] == 1
        assert receipt["shared_target_split_status_counts"] == preparation["split_target_status_counts"]
        assert receipt["shared_target_reuse"]["target_source"] == "verified_shared_artifact"
        assert receipt["shared_target_reuse"]["preparation_included_in_training_seconds"] is False
        assert receipt["pretraining_seconds"] >= receipt["target_load_seconds"]
        assert receipt["sample_build_seconds"] >= 0
        assert receipt["admitted"] is receipt["promotion_performed"] is False
    assert Path(preparation["artifact"]["path"]).read_bytes() == artifact_before
    assert checkpoint.read_bytes() == raw


@pytest.mark.parametrize("change", ["embedding", "source", "bridges", "timeout", "bytes"])
def test_prepared_bundle_rejects_stale_input_or_configuration(prepared, change):
    records, samples, originals, preparation, config = prepared
    if change == "embedding":
        samples[0] = build_us_code_sample(**asdict(replace(records[0], embedding_vector=(.2, .8))))
    elif change == "source":
        config = replace(config, code_sha256={"fixture": "1" * 64})
    elif change == "bridges":
        config = replace(config, bridge_names=config.bridge_names[:-1])
    elif change == "timeout":
        config = replace(config, target_timeout_seconds=config.target_timeout_seconds + 1)
    else:
        path = Path(preparation["artifact"]["path"])
        path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError):
        with load_target_artifact(preparation["artifact"]["path"],
                                  expected_sha256=preparation["artifact"]["sha256"], config=config) as snapshot:
            snapshot.targets_for(samples, config=config)
