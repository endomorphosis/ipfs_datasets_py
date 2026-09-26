"""Combined v8 targets, sparse replay and Arrow features using injected updates.

Synthetic producer declarations and complete hand-built targets exercise the
real worker/owner artifact path. No model evaluation, optimizer execution,
embedding inference, native qualification, publication or Lean admission occurs.
"""
from dataclasses import dataclass, replace
from functools import wraps
import hashlib
import json
from pathlib import Path
import struct

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry, RegistryError
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_target_preparation as preparation
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_coordinator as coordinator
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_ir_target_bundle as bundles
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as modal
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_snapshot import build_target_snapshot
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_arrow_weights import (
    MappedFeatureEmbeddingWeights, build_feature_embedding_weights_ipc,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_sparse_checkpoint import resolve_checkpoint
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_campaign_training_coordinator import _campaign_inputs
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_training_coordinator import ImmediateExecutor, _prepare
from tests.unit.optimizers.logic_theorem_optimizer.test_legal_ir_target_snapshot import target_for


def _forbid_native(monkeypatch):
    for name in ("evaluate", "train_generalizable_projection"):
        original = getattr(modal.AdaptiveModalAutoencoder, name)
        @wraps(original)
        def forbidden(*args, **kwargs):
            pytest.fail("combined artifact fixture must not run model evaluation or optimization")
        monkeypatch.setattr(modal.AdaptiveModalAutoencoder, name, forbidden)


def _stage(registry, path):
    ref = registry.stage_artifact(path)
    return {**ref, "path": str(registry.artifact_path(ref))}


def _register_job(registry, root, payload, suffix):
    spec = worker.TrainingJobSpec.from_dict({**payload, "job_id": f"job-{suffix}", "run_id": f"run-{suffix}",
        "output_directory": str(root / f"attempt-{suffix}")})
    path = root / f"job-{suffix}.json"
    path.write_text(json.dumps(spec.to_dict()))
    registry.create_run(f"create-{suffix}", spec.run_id, "english-0", spec.base_version_id,
        {"job_spec_sha256": spec.canonical_sha256, "job_spec_artifact": registry.stage_artifact(path)})
    return spec


def _target_artifact(root, samples, config, artifact_format, targets):
    path = root / ("complete-targets.bundle" if artifact_format == "bundle" else "complete-targets.json")
    if artifact_format == "bundle":
        return bundles.write_target_bundle(path,
            iter((sample, targets[sample.sample_id], "ready") for sample in samples), config=config)
    return build_target_snapshot(samples, targets, config=config).save(path)


@dataclass
class Combined:
    specs: tuple
    targets: dict
    config: object
    base_raw: bytes
    shared_files: dict
    target_count: int


def _combined(registry, root, monkeypatch, *, arrow=False, artifact_format="bundle", problem=None):
    _forbid_native(monkeypatch)
    inputs, binding, fixture = _campaign_inputs(registry, root)
    second_inputs, second_binding, _ = _campaign_inputs(registry, root, fixture=fixture, batch_number=1)
    assert second_binding == binding
    samples = [build_us_code_sample(**row) for batch in (inputs, second_inputs)
               for row in (*batch["samples"], *batch["validation_samples"])]
    assert len({sample.sample_id for sample in samples}) == len(samples) == 8
    # The complete target objects contain document views, triples, metadata,
    # timestamps, exact floats, all loss dictionaries and explicit acceptance.
    targets = {sample.sample_id: replace(target_for(sample), bridge_names=worker.BRIDGE_NAMES)
               for sample in samples}
    # Use the actual package/configuration provenance checker. Only target
    # values and the trainer are injected; producer guards stay active.
    config = preparation.target_snapshot_config(worker.TrainingConfig())
    target_samples = samples
    if problem == "missing_validation":
        removed = samples[2].sample_id  # First batch's first validation member.
        target_samples = [sample for sample in samples if sample.sample_id != removed]
        stored_targets = {key: value for key, value in targets.items() if key != removed}
    else:
        stored_targets = targets
    saved = _target_artifact(root, target_samples, config, artifact_format, stored_targets)
    target_ref = _stage(registry, saved["path"])
    # About 14KB of synthetic padding keeps the accepted patch below the
    # owner's normal compaction fraction without using an archived checkpoint.
    state = modal.ModalAutoencoderTrainingState(feature_embedding_weights={
        "shared": [0.25, -0.0], "padding": [index / 1000 for index in range(2000)]})
    base_raw = (state.to_json() + "\n").encode()
    base_path = root / "base.json"
    base_path.write_bytes(base_raw)
    updates = {"target_snapshot_id": saved["snapshot_id"], "target_snapshot_artifact": target_ref,
               "capture_sparse_patches": True, "candidate_storage": "sparse"}
    if problem == "snapshot_id":
        updates["target_snapshot_id"] = "sha256:" + "0" * 64
    if arrow:
        arrow_path = root / "features.arrow"
        # JSON serialization sorts keys. Bind Arrow to the exact checkpoint
        # reload order, rather than this fixture's original insertion order.
        checkpoint_state = modal.ModalAutoencoderTrainingState.from_dict(json.loads(base_raw))
        build_feature_embedding_weights_ipc(checkpoint_state, arrow_path,
            base_checkpoint_sha256="b" * 64 if problem == "arrow_base" else hashlib.sha256(base_raw).hexdigest())
        updates["arrow_feature_weights_artifact"] = _stage(registry, arrow_path)
    first = _prepare(registry, root, job_updates={**inputs, **updates},
                     variant_updates={"source_campaign_binding": binding})
    second = _register_job(registry, root, {**first.to_dict(), **second_inputs}, "independent")
    paths = [first.base_checkpoint.path, target_ref["path"]]
    if arrow:
        paths.append(updates["arrow_feature_weights_artifact"]["path"])
    shared_files = {path: Path(path).read_bytes() for path in paths}
    return Combined((first, second), targets, config, base_raw, shared_files, len(samples))


def _injected_worker(combined, observations, *, arrow):
    def execute(spec):
        def trainer(model, samples, *, validation_samples, **kwargs):
            ids = [sample.sample_id for sample in (*samples, *validation_samples)]
            supplied = kwargs["legal_ir_targets"]
            assert set(supplied) == set(ids)
            assert len(supplied) == 4 < combined.target_count
            for sample_id in ids:
                target = supplied[sample_id]
                expected = combined.targets[sample_id]
                assert type(target) is type(expected)
                assert target == expected
                assert target.document.to_json() == expected.document.to_json()
                assert target.document.canonical_hash() == expected.document.canonical_hash()
                assert struct.pack("!d", target.document.views["deontic.ir"].payload["rules"][0]["amount"]) == struct.pack("!d", -0.0)
            weights = model.state.feature_embedding_weights
            if arrow:
                assert type(weights) is MappedFeatureEmbeddingWeights
                assert weights.statistics["overlay_rows"] == 0
            else:
                assert type(weights) is not MappedFeatureEmbeddingWeights
            branch = "branch:" + samples[0].sample_id
            previous = weights.get(branch, [0.0])[0]
            before = model.state.state_identity()
            with model.state.transaction(label="synthetic-combined-update") as transaction:
                model.state.feature_embedding_weights["shared"][0] += 0.125
                model.state.feature_embedding_weights[branch] = [previous + 0.5, -0.0]
            kwargs["accepted_patch_sink"](transaction.patch, {
                "base_state_identity": before, "result_state_identity": model.state.state_identity(),
                "base_revision": transaction.patch.base_revision, "result_revision": transaction.patch.result_revision,
                "label": "synthetic-combined-update"})
            observations[spec.run_id] = {"raw": (model.state.to_json() + "\n").encode(),
                "identity": model.state.state_identity_record().to_dict(),
                "branch": branch, "weight_object": weights, "selected_ids": tuple(ids)}
            return {"accepted_epochs": 1, "after": {"legal_ir_target_count": len(supplied)},
                "stopped_reason": "synthetic_complete_target_sparse_transport_fixture"}
        return worker.execute_training_job(spec, trainer=trainer)
    return execute


def _resolved(registry, completed, *, reset_revision=True):
    return resolve_checkpoint(completed["candidate"], resolver=lambda ref: registry.artifact_path(ref),
                              reset_revision=reset_revision)


def _receipt(registry, completed):
    return json.loads(registry.artifact_path(completed["worker_receipt_artifact"]).read_bytes())


def _assert_transport_result(registry, completed, spec, observed, combined, *, arrow, artifact_format):
    receipt = _receipt(registry, completed)
    summary = completed["result"]
    assert summary["execution_mode"] == receipt["execution_mode"] == "injected_test"
    assert summary["sparse_replay_verified"] is True
    assert summary["checkpoint_storage"] == "sparse_manifest"
    assert summary["sparse_compaction_performed"] is False
    assert summary["source_campaign_verified"] is summary["produced_record_projection_verified"] is True
    assert summary["shared_targets_verified"] is True
    assert summary["shared_target_count"] == 4
    assert receipt["target_snapshot_sample_count"] == combined.target_count
    assert receipt["target_snapshot_status_counts"] == {"ready": combined.target_count}
    assert receipt["shared_target_status_counts"] == {"ready": 4}
    assert receipt["target_artifact_format"] == artifact_format
    assert receipt["weight_storage"] == ("arrow_cow_feature_embeddings" if arrow else "private_json")
    if artifact_format == "bundle":
        assert receipt["target_storage_statistics"]["unique_decompressed_shards"] == 4
    if arrow:
        assert receipt["arrow_feature_statistics_before_training"]["overlay_rows"] == 0
        assert receipt["arrow_feature_statistics_after_training"]["overlay_rows"] == 2
        assert observed["weight_object"].statistics["closed"] is True
    assert len(receipt["sparse_patch_segments"]) == receipt["optimizer_accepted_epochs"] == 1
    assert not (Path(spec.output_directory) / "candidate.state.json").exists()
    resolved = _resolved(registry, completed)
    assert (resolved.state.to_json() + "\n").encode() == observed["raw"]
    assert resolved.materialized_checkpoint == receipt["candidate_materialized_checkpoint"]
    assert resolved.materialized_checkpoint == {"sha256": hashlib.sha256(observed["raw"]).hexdigest(), "bytes": len(observed["raw"])}
    assert receipt["candidate_state_identity"] == observed["identity"]
    # Normal checkpoint reload starts a new process-local revision counter;
    # terminal replay must also reproduce the trainer's full identity record.
    assert resolved.state.state_revision == 0
    assert resolved.replayed_revision == receipt["candidate_state_identity"]["revision"]
    assert resolved.state.state_identity_record().to_dict() == {**receipt["candidate_state_identity"], "revision": 0}
    terminal = _resolved(registry, completed, reset_revision=False)
    assert terminal.state.state_identity_record().to_dict() == receipt["candidate_state_identity"]
    assert terminal.state.state_revision == terminal.replayed_revision == resolved.replayed_revision
    assert (terminal.state.to_json() + "\n").encode() == observed["raw"]
    assert receipt["admitted"] is receipt["promotion_performed"] is receipt["heldout_canary_qualified"] is False
    assert summary["admitted"] is summary["promotion_performed"] is summary["heldout_canary_qualified"] is False
    assert "roundtrip_ok" not in json.dumps(receipt)
    return resolved


@pytest.mark.parametrize("artifact_format", ["json", "bundle"])
@pytest.mark.parametrize("arrow", [False, True])
def test_v8_complete_targets_sparse_branches_arrow_and_restart(tmp_path, monkeypatch, artifact_format, arrow):
    database, artifacts = tmp_path / "registry.duckdb", tmp_path / "artifacts"
    observations, target_handles = {}, []
    load = bundles.load_target_artifact
    def capture(*args, **kwargs):
        result = load(*args, **kwargs)
        target_handles.append(result)
        return result
    monkeypatch.setattr(bundles, "load_target_artifact", capture)
    with AutoencoderRegistry(database, artifacts) as registry:
        combined = _combined(registry, tmp_path, monkeypatch, arrow=arrow, artifact_format=artifact_format)
        first, second = combined.specs
        execute = _injected_worker(combined, observations, arrow=arrow)
        result = coordinator.run_training_jobs(registry, combined.specs, max_workers=2,
            executor_factory=ImmediateExecutor, worker_function=execute)
        assert result["failed"] == [], json.dumps(result["failed"], sort_keys=True)
        assert result["execution_mode"] == "injected_test"
        completed = {item["run_id"]: item for item in result["completed"]}
        assert len(completed) == 2
        assert completed[first.run_id]["version_id"] != completed[second.run_id]["version_id"]
        assert first.base_version_id == second.base_version_id
        assert observations[first.run_id]["branch"] != observations[second.run_id]["branch"]
        for spec, other in ((first, second), (second, first)):
            resolved = _assert_transport_result(registry, completed[spec.run_id], spec, observations[spec.run_id],
                combined, arrow=arrow, artifact_format=artifact_format)
            assert resolved.state.feature_embedding_weights["shared"] == [0.375, -0.0]
            assert observations[spec.run_id]["branch"] in resolved.state.feature_embedding_weights
            assert observations[other.run_id]["branch"] not in resolved.state.feature_embedding_weights
        assert registry.resolve_head("english-0", "best")["version_id"] == first.base_version_id
        saved_results = {spec.run_id: registry.get_run(spec.run_id)["result"] for spec in combined.specs}
    if artifact_format == "bundle":
        assert all(handle.statistics["closed"] for handle in target_handles)
    with AutoencoderRegistry(database, artifacts) as registry:
        for spec in combined.specs:
            assert registry.get_run(spec.run_id)["result"] == saved_results[spec.run_id]
            restored = coordinator.registered_corpus_job_inputs(registry, spec.run_id)
            assert restored["spec"].canonical_sha256 == spec.canonical_sha256
            _assert_transport_result(registry, completed[spec.run_id], spec, observations[spec.run_id],
                combined, arrow=arrow, artifact_format=artifact_format)
        # Resume one sparse branch through the actual registered dependency
        # closure. The other branch remains an independent version.
        parent = completed[first.run_id]
        checkpoint = coordinator.registered_checkpoint_inputs(registry, parent["version_id"])
        assert checkpoint["base_checkpoint_dependencies"]
        payload = {**first.to_dict(), **checkpoint, "base_version_id": parent["version_id"]}
        if arrow:
            path = tmp_path / "resumed-features.arrow"
            resolved = _resolved(registry, parent)
            build_feature_embedding_weights_ipc(resolved.state, path,
                base_checkpoint_sha256=resolved.materialized_checkpoint["sha256"])
            payload["arrow_feature_weights_artifact"] = _stage(registry, path)
        resumed = _register_job(registry, tmp_path, payload, "resumed")
        resumed_result = coordinator.run_training_jobs(registry, [resumed], executor_factory=ImmediateExecutor,
            worker_function=execute)
        assert resumed_result["failed"] == [], json.dumps(resumed_result["failed"], sort_keys=True)
        child = resumed_result["completed"][0]
        resolved = _assert_transport_result(registry, child, resumed, observations[resumed.run_id], combined,
            arrow=arrow, artifact_format=artifact_format)
        assert resolved.depth == 2
        assert resolved.state.feature_embedding_weights["shared"] == [0.5, -0.0]
        assert resolved.state.feature_embedding_weights[observations[first.run_id]["branch"]] == [1.0, -0.0]
        assert observations[second.run_id]["branch"] not in resolved.state.feature_embedding_weights
        assert registry.resolve_head("english-0", "best")["version_id"] == first.base_version_id
    assert all(Path(path).read_bytes() == raw for path, raw in combined.shared_files.items())
    if artifact_format == "bundle":
        assert len(target_handles) == 3 and all(handle.statistics["closed"] for handle in target_handles)


@pytest.mark.parametrize("kind", ["target", "arrow"])
def test_corrupted_shared_cas_artifact_rejected_before_any_claim(tmp_path, monkeypatch, kind):
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        combined = _combined(registry, tmp_path, monkeypatch, arrow=True)
        spec = combined.specs[0]
        ref = spec.target_snapshot_artifact if kind == "target" else spec.arrow_feature_weights_artifact
        Path(ref.path).write_bytes(b"corrupted shared artifact")
        def forbidden(*args, **kwargs):
            pytest.fail("corrupt shared artifact must not reach worker dispatch")
        with pytest.raises((RegistryError, coordinator.TrainingCoordinationError), match="artifact|digest|hash"):
            coordinator.run_training_jobs(registry, combined.specs, executor_factory=ImmediateExecutor, worker_function=forbidden)
        assert all(registry.get_run(job.run_id)["status"] == "queued" for job in combined.specs)
        assert not Path(spec.output_directory).exists()


@pytest.mark.parametrize("problem", ["snapshot_id", "missing_validation", "arrow_base"])
def test_valid_cas_with_wrong_target_or_arrow_binding_fails_before_injected_update(tmp_path, monkeypatch, problem):
    with AutoencoderRegistry(tmp_path / "registry.duckdb", tmp_path / "artifacts") as registry:
        combined = _combined(registry, tmp_path, monkeypatch, arrow=True, problem=problem)
        spec = combined.specs[0]
        def execute(job):
            def forbidden(*args, **kwargs):
                pytest.fail("wrong shared binding reached injected updater")
            return worker.execute_training_job(job, trainer=forbidden)
        result = coordinator.run_training_jobs(registry, [spec], executor_factory=ImmediateExecutor, worker_function=execute)
        assert result["completed"] == []
        assert len(result["failed"]) == 1 and result["failed"][0]["failure_recorded"] is True
        assert registry.get_run(spec.run_id)["status"] == "failed"
        assert not Path(spec.output_directory).exists()
        assert registry.resolve_head("english-0", "best")["version_id"] == spec.base_version_id


@pytest.mark.parametrize("problem", ["segment_bytes", "candidate_identity"])
def test_owner_rejects_corrupt_sparse_result_and_completes_independent_batch(tmp_path, monkeypatch, problem):
    database, artifacts = tmp_path / "registry.duckdb", tmp_path / "artifacts"
    observations = {}
    with AutoencoderRegistry(database, artifacts) as registry:
        combined = _combined(registry, tmp_path, monkeypatch, arrow=True)
        first, second = combined.specs
        execute = _injected_worker(combined, observations, arrow=True)
        def corrupt_one(spec):
            receipt = execute(spec)
            if spec.run_id == first.run_id:
                if problem == "segment_bytes":
                    Path(receipt["sparse_patch_segments"][0]["path"]).write_bytes(b"corrupt accepted patch")
                else:
                    # Persist a false candidate identity while keeping the
                    # accepted patch intact; owner replay must catch mismatch.
                    receipt["candidate_state_identity"]["digest"] = "0" * 64
                    Path(spec.output_directory, "receipt.json").write_text(json.dumps(receipt))
            return receipt
        result = coordinator.run_training_jobs(registry, combined.specs, max_workers=2,
            executor_factory=ImmediateExecutor, worker_function=corrupt_one)
        assert [row["run_id"] for row in result["completed"]] == [second.run_id], json.dumps(result["failed"], sort_keys=True)
        assert [row["run_id"] for row in result["failed"]] == [first.run_id]
        assert result["failed"][0]["failure_recorded"] is True
        assert registry.get_run(first.run_id)["status"] == "failed"
        assert registry.get_run(second.run_id)["status"] == "completed"
        _assert_transport_result(registry, result["completed"][0], second, observations[second.run_id],
            combined, arrow=True, artifact_format="bundle")
        assert registry.resolve_head("english-0", "best")["version_id"] == first.base_version_id
    with AutoencoderRegistry(database, artifacts) as registry:
        assert registry.get_run(first.run_id)["status"] == "failed"
        assert registry.get_run(second.run_id)["status"] == "completed"
