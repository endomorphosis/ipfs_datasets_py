"""Private feature lanes exercise real registry/sparse replay with injected metrics.

These tests establish execution/integrity, never semantic embedding authority,
model quality, source qualification, or Lean admission.
"""
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import time
from unittest.mock import patch

import duckdb
import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_feature_training as feature
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_incremental_training as inc
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_target_preparation as preparation
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_snapshot import TargetSnapshotConfig, build_target_snapshot
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import build_us_code_sample
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_training_coordinator import ImmediateExecutor, _prepare, _sparse_trainer
from tests.unit.optimizers.logic_theorem_optimizer.test_legal_ir_target_snapshot import target_for


def _config():
    return TargetSnapshotConfig(worker.BRIDGE_NAMES, False, 1, {"injected_test": "f" * 64})


def _templates(registry, root, count=8, *, target_problem=None, target_format="json"):
    training = {"title": "5", "section": "train", "text": "The agency shall retain records.",
                "embedding_model": "injected-fixture:2", "embedding_vector": [1., 0.]}
    tuning = {"title": "5", "section": "tuning", "text": "The officer shall not disclose files.",
              "embedding_model": "injected-fixture:2", "embedding_vector": [0., 1.]}
    samples = [build_us_code_sample(**row) for row in (training, tuning)]
    targets = {}
    for sample in samples:
        target = target_for(sample)
        metadata = {**target.document.metadata, "bridge_names": list(worker.BRIDGE_NAMES),
                    "attempted_bridge_count": 5, "implemented_bridge_count": 5,
                    "accepted_bridge_count": 5, "failed_bridge_count": 0}
        targets[sample.sample_id] = replace(target, bridge_names=worker.BRIDGE_NAMES, accepted=True,
                                            document=replace(target.document, metadata=metadata))
    key = samples[0].sample_id
    if target_problem == "rejected":
        targets[key] = replace(targets[key], accepted=False)
    elif target_problem == "names":
        targets[key] = replace(targets[key], bridge_names=worker.BRIDGE_NAMES[:4])
    elif target_problem is not None:
        metadata = dict(targets[key].document.metadata)
        if target_problem == "missing_metadata": metadata = {}
        elif target_problem == "missing_report": metadata["implemented_bridge_count"] = 4
        elif target_problem == "rejected_report": metadata["accepted_bridge_count"] = 4
        elif target_problem == "exception": metadata["failed_bridge_count"] = 1
        elif target_problem == "metadata_names": metadata["bridge_names"] = list(worker.BRIDGE_NAMES[:4])
        else: raise AssertionError(target_problem)
        targets[key] = replace(targets[key], document=replace(targets[key].document, metadata=metadata))
    if target_format == "bundle":
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_target_bundle import write_target_bundle
        saved = write_target_bundle(root / "targets.bundle", [(row, targets[row.sample_id], "ready") for row in samples], config=_config())
    else:
        saved = build_target_snapshot(samples, targets, config=_config()).save(root / "targets.json")
    target_ref = {key: saved[key] for key in ("path", "sha256", "bytes")}
    original = _prepare(registry, root,
        training_config={"projection_reconstruction_objective": "raw_decoder"},
        job_updates={"schema_version": "autoencoder-training-job-v3", "capture_sparse_patches": True,
                     "candidate_storage": "sparse", "samples": [training], "validation_samples": [tuning],
                     "target_snapshot_artifact": target_ref, "target_snapshot_id": saved["snapshot_id"]})
    return [replace(original, dataset_snapshot_id=f"feature-source-{index}") for index in range(count)]


def _trainer(model, samples, *, validation_samples, accepted=True, **kwargs):
    assert kwargs["projection_reconstruction_objective"] == "raw_decoder"
    assert len(kwargs["legal_ir_targets"]) == len(samples) + len(validation_samples)
    if accepted:
        _sparse_trainer(model, samples, validation_samples=validation_samples, **kwargs)
    def evaluation(after):
        value = .2 if after and accepted else .1
        return {"sample_count": len(validation_samples), "legal_ir_target_count": len(validation_samples),
                "embedding_cosine_similarity": value, "reconstruction_loss": .5 - value,
                "cross_entropy_loss": .3, "legal_ir_losses": {"fixture_loss": .3, "fixture_cosine_similarity": value}}
    def observation(values):
        return {"complete": True, "finite": True, "used_for_acceptance": True, "sample_memory_used": False,
                "requested_sample_count": len(validation_samples), "observed_sample_count": len(validation_samples),
                "embedding_cosine_similarity_mean": values["embedding_cosine_similarity"],
                "reconstruction_loss_mean": values["reconstruction_loss"],
                "sample_metrics": [{"sample_id": row.sample_id,
                                    "embedding_cosine_similarity": values["embedding_cosine_similarity"],
                                    "reconstruction_loss": values["reconstruction_loss"]} for row in validation_samples]}
    before, after = evaluation(False), evaluation(True)
    return {"accepted_epochs": int(accepted), "projection_reconstruction_objective": "raw_decoder",
            "before": before, "after": after,
            "decoder_preprojection_observation": {"changes_acceptance": True, "sample_scope": "tuning",
                                                  "before": observation(before), "after": observation(after)},
            "epoch_reports": [{"accepted": True, "committed_objective_delta": .1,
                               "pareto_regressions": {}}] if accepted else [],
            "stopped_reason": "injected_feature_fixture"}


def _worker(spec):
    with patch.object(preparation, "target_snapshot_config", return_value=_config()):
        return worker.execute_training_job(spec, trainer=_trainer)


def _rejected_worker(spec):
    with patch.object(preparation, "target_snapshot_config", return_value=_config()):
        return worker.execute_training_job(spec, trainer=lambda *a, **k: _trainer(*a, **k, accepted=False))


def _parallel_worker(spec):
    marker = Path(spec.output_directory).parent / (spec.run_id + ".ready")
    marker.write_text(str(os.getpid()))
    deadline = time.monotonic() + 30
    while len(list(marker.parent.glob("*.ready"))) < 2:
        if time.monotonic() > deadline:
            raise RuntimeError("feature workers failed to overlap")
        time.sleep(.01)
    return _worker(spec)


def _run(registry, root, specs, **kwargs):
    return feature.run_feature_incremental_training(registry, specs, state_directory=root / "feature",
        executor_factory=ImmediateExecutor, worker_function=_worker, **kwargs)


def test_private_training_quack_resume_and_parent_chain_without_qualification(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_candidate_qualification as qualification
    monkeypatch.setattr(qualification, "qualify_candidate", lambda *a, **k: pytest.fail("feature mode must not qualify"))
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        specs = _templates(registry, tmp_path, 6)
        first = _run(registry, tmp_path, specs, max_batches=2)
        assert first["completed_batch_count"] == 2
        assert first["pending_batch_count"] == 4
        second = _run(registry, tmp_path, specs, max_batches=8)
        assert second["completed_batch_count"] == 6
        assert len(second["dispatched_run_ids"]) == 4
        assert all(row["feature_status"] == "updated" for row in second["completed"])
        assert all(row["optimizer_accepted_epochs"] == 1 for row in second["completed"])
        third = _run(registry, tmp_path, [])
        assert third["completed_batch_count"] == 6
        assert not third["dispatched_run_ids"]
        assert registry.resolve_head("english-0", "best")["version_id"] == specs[0].base_version_id
        for result in (first, second, third):
            for key in feature._FALSE:
                assert result[key] is False
            assert result["semantic_qualification_status"] == "deferred_not_evaluated"
            assert result["lake_executed"] is False and result["source_repair_submitted"] is False
            for reference in result["dispatch_report_artifacts"]:
                wave = json.loads(registry.artifact_path(reference).read_bytes())
                transport = wave["dispatch_reports"][0]["weight_control"]
                assert transport["transport"] == "native_scoped_quack_prototype"
                assert transport["database_writer_count"] == 1
                assert transport["workers_open_database"] is False
        completed = [json.loads(raw) for (raw,) in duckdb.connect(str(tmp_path / "feature/progress.duckdb"), read_only=True).execute(
            "SELECT completed FROM batches ORDER BY ordinal").fetchall()]
        heads = {}
        for row in completed:
            run = registry.get_run(row["run_id"])
            assert run["base_version_id"] == heads.get(row["lane_index"], specs[0].base_version_id)
            heads[row["lane_index"]] = row["next_base_version_id"]


def test_real_parallel_feature_workers_use_separate_processes(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        specs = _templates(registry, tmp_path, 20)
        chosen = {}
        for spec in specs:
            chosen.setdefault(inc.assignment(spec, 1, 2)["lane_index"], spec)
        assert len(chosen) == 2
        result = feature.run_feature_incremental_training(registry, list(chosen.values()),
            state_directory=tmp_path / "feature", worker_function=_parallel_worker, max_batches=2)
        assert result["completed_batch_count"] == 2, result
        assert not result["blocked"]
        assert len({path.read_text() for path in (tmp_path / "feature/outputs").glob("*.ready")}) == 2
        assert result["execution_mode"] == "injected_test"


def test_capacity_zero_intake_is_durable_and_wider_resume_preserves_topology(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        specs = _templates(registry, tmp_path, 5)
        zero = _run(registry, tmp_path, specs, capacity_callback=lambda **kwargs: {"workers": 0})
        assert zero["intake_durable"] and zero["capacity_deferred"]
        assert zero["pending_batch_count"] == 5 and not zero["dispatched_run_ids"]
        calls = []
        def capacity(**kwargs):
            calls.append(kwargs)
            return {"workers": 1 if len(calls) == 1 else min(2, kwargs["max_workers"])}
        result = _run(registry, tmp_path, [], capacity_callback=capacity, max_batches=5)
        assert result["completed_batch_count"] == 5
        assert len(calls) >= 3
        assert result["policy"]["lane_count"] == 2


def test_rejected_feature_batch_consumes_without_blocking_or_advancing_parent(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        specs = _templates(registry, tmp_path, 3)
        result = feature.run_feature_incremental_training(registry, specs, state_directory=tmp_path / "feature",
            lane_count=1, executor_factory=ImmediateExecutor, worker_function=_rejected_worker)
        assert result["completed_batch_count"] == 3
        assert all(row["feature_status"] == "consumed_without_update" for row in result["completed"])
        assert {row["next_base_version_id"] for row in result["completed"]} == {specs[0].base_version_id}
        assert not result["blocked"]


@pytest.mark.parametrize("problem", ["projected", "mock", "overlap", "bridge", "memory", "target", "publication"])
def test_feature_intake_rejects_invalid_policy_before_dispatch(tmp_path, problem):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        spec = _templates(registry, tmp_path, 1)[0]
        kwargs = {}
        if problem == "projected":
            spec = replace(spec, training_config=replace(spec.training_config, projection_reconstruction_objective="safety_projected"))
        elif problem == "mock":
            spec = replace(spec, samples=(replace(spec.samples[0], embedding_model="mock:2"),))
        elif problem == "overlap":
            with pytest.raises(ValueError, match="disjoint"):
                replace(spec, validation_samples=(replace(spec.validation_samples[0], text=spec.samples[0].text),))
            return
        elif problem == "bridge":
            spec = replace(spec, training_config=replace(spec.training_config, legal_ir_bridge_names=worker.BRIDGE_NAMES[:1]))
        elif problem == "memory":
            # TrainingConfig itself is stricter and rejects memory shortcuts.
            with pytest.raises(ValueError):
                replace(spec.training_config, use_sample_memory=True)
            return
        elif problem == "target":
            spec = replace(spec, target_snapshot_artifact=None, target_snapshot_id="")
        else:
            kwargs["publication_repository"] = "fixture/no-publication"
        with pytest.raises(ValueError):
            _run(registry, tmp_path, [spec], **kwargs)
        assert not (tmp_path / "feature/progress.duckdb").exists()


@pytest.mark.parametrize("problem", ["source_identity", "embedding", "split", "transport"])
def test_feature_resume_rejects_policy_or_split_drift(tmp_path, problem):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        specs = _templates(registry, tmp_path, 1)
        _run(registry, tmp_path, specs, producer_identity={"verified_fixture": "a"})
        kwargs = {"producer_identity": {"verified_fixture": "a"}}
        if problem == "source_identity":
            kwargs["producer_identity"] = {"verified_fixture": "b"}
        elif problem == "embedding":
            specs = [replace(specs[0], samples=(replace(specs[0].samples[0], embedding_vector=(.2, .8)),))]
        elif problem == "split":
            with pytest.raises(ValueError, match="disjoint"):
                replace(specs[0], samples=(replace(specs[0].samples[0], text=specs[0].validation_samples[0].text),))
            return
        else:
            kwargs["control_transport"] = "owner"
        with pytest.raises(ValueError):
            _run(registry, tmp_path, specs, **kwargs)


@pytest.mark.parametrize("problem", ["projected", "partial", "mean", "ir", "guard", "objective", "accepted_count", "sample_id", "empty_ir"])
def test_completion_checks_run_before_lane_advancement_and_again_on_resume(tmp_path, problem):
    def corrupt(model, samples, *, validation_samples, **kwargs):
        result = _trainer(model, samples, validation_samples=validation_samples, **kwargs)
        if problem == "projected": result["projection_reconstruction_objective"] = "safety_projected"
        elif problem == "partial": result["decoder_preprojection_observation"]["after"]["complete"] = False
        elif problem == "mean": result["decoder_preprojection_observation"]["after"]["embedding_cosine_similarity_mean"] = .9
        elif problem == "ir": result["after"]["legal_ir_losses"]["fixture_loss"] = 1.0
        elif problem == "guard": result["epoch_reports"][0]["pareto_regressions"] = {"fixture": .2}
        elif problem == "objective": result["epoch_reports"][0]["committed_objective_delta"] = -.1
        elif problem == "accepted_count": result["epoch_reports"] = []
        elif problem == "sample_id": result["decoder_preprojection_observation"]["after"]["sample_metrics"][0]["sample_id"] = "different"
        else: result["after"]["legal_ir_losses"] = {}
        return result
    def corrupt_worker(spec):
        with patch.object(preparation, "target_snapshot_config", return_value=_config()):
            return worker.execute_training_job(spec, trainer=corrupt)
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        specs = _templates(registry, tmp_path, 1)
        for _ in range(2):
            with pytest.raises(ValueError, match="feature"):
                feature.run_feature_incremental_training(registry, specs, state_directory=tmp_path / "feature",
                    executor_factory=ImmediateExecutor, worker_function=corrupt_worker)
            db = duckdb.connect(str(tmp_path / "feature/progress.duckdb"), read_only=True)
            assert db.execute("SELECT completed_batches FROM stream").fetchone() == (0,)
            assert db.execute("SELECT DISTINCT head FROM lanes").fetchall() == [(specs[0].base_version_id,)]
            db.close()


def test_incremental_completion_hook_cannot_mutate_owner_evidence(tmp_path):
    from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_incremental_training import _templates as simple_templates
    from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_training_coordinator import _sparse_worker
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        specs = simple_templates(registry, tmp_path, 1)
        def mutation(registry, spec, completion):
            completion["next_base_version_id"] = "not-owner-verified"
        with pytest.raises(ValueError, match="mutated"):
            inc.run_incremental_training(registry, specs, state_directory=tmp_path / "incremental",
                executor_factory=ImmediateExecutor, worker_function=_sparse_worker, completion_validator=mutation)
        with pytest.raises(ValueError, match="max_batches"):
            inc.run_incremental_training(registry, specs, state_directory=tmp_path / "incremental", max_batches=0)


def test_native_feature_training_requires_bound_verified_embedding_evidence(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        specs = _templates(registry, tmp_path, 1)
        with pytest.raises(ValueError, match="caller-verified local embedding"):
            feature.run_feature_incremental_training(registry, specs, state_directory=tmp_path / "feature")
        assert not (tmp_path / "feature").exists()


@pytest.mark.parametrize("problem", ["rejected", "names", "missing_metadata", "missing_report", "rejected_report", "exception", "metadata_names"])
def test_partial_ready_targets_reject_before_training_and_remain_failed_on_resume(tmp_path, problem):
    def never_train(*args, **kwargs):
        pytest.fail("incomplete bridge supervision must fail before training")
    def incomplete_worker(spec):
        with patch.object(preparation, "target_snapshot_config", return_value=_config()):
            return worker.execute_training_job(spec, trainer=never_train)
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        if problem == "names":
            with pytest.raises(ValueError, match="bridge order/config mismatch"):
                _templates(registry, tmp_path, 1, target_problem=problem)
            return
        specs = _templates(registry, tmp_path, 1, target_problem=problem)
        for attempt in range(2):
            report = feature.run_feature_incremental_training(registry, specs, state_directory=tmp_path / "feature",
                executor_factory=ImmediateExecutor, worker_function=incomplete_worker)
            assert report["completed_batch_count"] == 0 and report["pending_batch_count"] == 1
            assert len(report["blocked"]) == 1 and report["blocked"][0]["status"] == "failed"
            assert bool(report["dispatched_run_ids"]) is (attempt == 0)
            assert not list((tmp_path / "feature/outputs").glob("*/candidate*"))
            assert registry.resolve_head("english-0", "best")["version_id"] == specs[0].base_version_id


def test_nonready_target_status_is_not_complete_feature_supervision(tmp_path):
    sample = build_us_code_sample(title="5", section="1", text="The agency shall retain records.")
    with pytest.raises(ValueError, match="timeout or nonready"):
        feature.verify_feature_target_supervision({sample.sample_id: target_for(sample)},
            {sample.sample_id: "timeout"}, worker.BRIDGE_NAMES, sample_ids=[sample.sample_id])


@pytest.mark.parametrize("problem", [None, "rejected_report"])
def test_raw_streamed_reduction_checks_native_payload_before_conversion(tmp_path, monkeypatch, problem):
    # Native entry/hydration/reducer with an explicitly injected training gate;
    # this is control-flow coverage, never native training/quality evidence.
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_paths
    calls = []
    def gate(model, samples, **kwargs):
        calls.append(True)
        return _trainer(model, samples, **kwargs)
    monkeypatch.setattr(autoencoder_paths, "gated_projection_training", gate)
    monkeypatch.setattr(worker, "_target_reduction_skip_reason", lambda *args: None)
    monkeypatch.setattr(preparation, "target_snapshot_config", lambda _: _config())
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        spec = _templates(registry, tmp_path, 1, target_problem=problem, target_format="bundle")[0]
        if problem:
            with pytest.raises(ValueError, match="bridge returns/acceptance"):
                worker._execute_native_training_job_with_reduced_targets(spec)
            assert not calls
            assert not Path(spec.output_directory).exists()
        else:
            receipt = worker._execute_native_training_job_with_reduced_targets(spec)
            assert calls == [True]
            assert receipt["shared_target_supervision"]["complete"] is True
            assert receipt["shared_target_supervision"]["target_count"] == 2
            assert receipt["target_reduction"]["streaming"]["validation_pass_targets"] == 2
            assert receipt["target_reduction"]["streaming"]["conversion_pass_targets"] == 2
            assert receipt["target_reduction"]["applied"] is True
