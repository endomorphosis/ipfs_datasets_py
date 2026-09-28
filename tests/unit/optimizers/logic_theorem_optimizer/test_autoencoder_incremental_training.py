"""Real registry/resume with injected bounded updates, never model admission."""
from pathlib import Path
import time
import os
import duckdb
from dataclasses import replace
import json
import threading

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_incremental_training as inc
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import execute_training_job
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_training_coordinator import (
    ImmediateExecutor, _prepare, _sparse_worker,
)


def _templates(registry, tmp_path, count=6):
    original = _prepare(registry, tmp_path, job_updates={
        "schema_version": "autoencoder-training-job-v3", "capture_sparse_patches": True,
        "candidate_storage": "sparse"})
    result = []
    for index in range(count):
        result.append(replace(original, dataset_snapshot_id=f"source-record-{index}"))
    return result


def _run(registry, root, specs, **kwargs):
    return inc.run_incremental_training(registry, specs, state_directory=root / "incremental",
        executor_factory=ImmediateExecutor, worker_function=_sparse_worker, **kwargs)


def test_two_lanes_resume_skip_and_checkpoint_chain(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        specs = _templates(registry, tmp_path)
        first = _run(registry, tmp_path, specs, max_batches=2)
        assert len(first["completed"]) == 2
        assert first["execution_mode"] == "injected_test"
        second = _run(registry, tmp_path, specs, max_batches=8)
        assert len(second["completed"]) == 6
        assert len(second["dispatched_run_ids"]) == 4
        third = _run(registry, tmp_path, list(reversed(specs)))
        assert not third["dispatched_run_ids"]
        assert third["completed_batch_count"] == second["completed_batch_count"] == 6
        assert len(third["completed"]) <= 2
        assert third["pending_batch_count"] == 0
        assert third["admitted"] is False
        lanes = {}
        for row in second["completed"]:
            run = registry.get_run(row["run_id"])
            lane = row["lane_index"]
            assert run["base_version_id"] == lanes.get(lane, specs[0].base_version_id)
            lanes[lane] = row["candidate_version_id"]
        assert registry.resolve_head("english-0", "best")["version_id"] == specs[0].base_version_id


def _parallel_worker(spec):
    marker = Path(spec.output_directory).parent / (spec.run_id + ".ready")
    marker.write_text(str(os.getpid()))
    deadline = time.monotonic() + 20
    while len(list(marker.parent.glob("*.ready"))) < 2:
        if time.monotonic() > deadline:
            raise RuntimeError("parallel fixture did not overlap")
        time.sleep(.01)
    return _sparse_worker(spec)


def test_independent_workers_overlap(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        all_specs = _templates(registry, tmp_path, count=20)
        selected = {}
        for spec in all_specs:
            selected.setdefault(inc.assignment(spec, 1, 2)["lane_index"], spec)
        assert len(selected) == 2
        result = inc.run_incremental_training(registry, list(selected.values()),
            state_directory=tmp_path / "incremental", worker_function=_parallel_worker, max_batches=2)
        assert len(result["completed"]) == 2, json.dumps(result["dispatch_reports"], indent=2)
        assert not result["blocked"]
        assert result["execution_mode"] == "injected_test"
        assert len({path.read_text() for path in (tmp_path / "incremental/outputs").glob("*.ready")}) == 2


def test_rejected_batch_retains_parent_and_is_consumed(tmp_path):
    def rejected(spec):
        return execute_training_job(spec, trainer=lambda *args, **kwargs: {
            "accepted_epochs": 0, "after": {"legal_ir_target_count": 1}, "stopped_reason": "fixture_rejected"})
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        specs = _templates(registry, tmp_path, count=2)
        result = inc.run_incremental_training(registry, specs, state_directory=tmp_path / "incremental",
            lane_count=1, executor_factory=ImmediateExecutor, worker_function=rejected)
        assert len(result["completed"]) == 2
        assert all(row["consumed_without_update"] for row in result["completed"])
        assert {row["next_base_version_id"] for row in result["completed"]} == {specs[0].base_version_id}
        replay = inc.run_incremental_training(registry, specs, state_directory=tmp_path / "incremental",
            lane_count=1, executor_factory=ImmediateExecutor, worker_function=rejected)
        assert not replay["dispatched_run_ids"]


def test_failed_lane_blocks_without_retry(tmp_path):
    calls = []
    def fail(spec):
        calls.append(spec.run_id)
        raise RuntimeError("fixture interrupted optimizer")
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        specs = _templates(registry, tmp_path, count=2)
        for _ in range(2):
            result = inc.run_incremental_training(registry, specs, state_directory=tmp_path / "incremental",
                lane_count=1, executor_factory=ImmediateExecutor, worker_function=fail)
            assert len(result["blocked"]) == 1
            assert result["blocked"][0]["recovery_required"]
            assert result["pending_batch_count"] == 2
        assert len(calls) == 1


def test_completed_registry_recovered_after_lost_response(tmp_path, monkeypatch):
    original = inc.coordinator.run_training_jobs
    def lost(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("fixture lost response after durable completion")
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        specs = _templates(registry, tmp_path, count=1)
        monkeypatch.setattr(inc.coordinator, "run_training_jobs", lost)
        with pytest.raises(RuntimeError, match="lost response"):
            _run(registry, tmp_path, specs)
        monkeypatch.setattr(inc.coordinator, "run_training_jobs", lambda *a, **k: pytest.fail("must not retrain"))
        recovered = _run(registry, tmp_path, specs)
        assert len(recovered["completed"]) == 1
        assert not recovered["dispatched_run_ids"]


def test_topology_and_policy_drift_reject(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        specs = _templates(registry, tmp_path, count=1)
        _run(registry, tmp_path, specs)
        with pytest.raises(inc.IncrementalTrainingError, match="topology"):
            _run(registry, tmp_path, specs, lane_count=3)
        with pytest.raises(inc.IncrementalTrainingError, match="policy"):
            _run(registry, tmp_path, [replace(specs[0], code_identity="changed-source")])
        db = duckdb.connect(str(tmp_path / "incremental/progress.duckdb"))
        batch_id, template_json = db.execute("SELECT batch_id,template FROM batches").fetchone()
        template = json.loads(template_json)
        template["samples"][0]["text"] = "tampered"
        db.execute("UPDATE batches SET template=? WHERE batch_id=?", [json.dumps(template), batch_id])
        db.close()
        with pytest.raises(inc.IncrementalTrainingError, match="identity"):
            _run(registry, tmp_path, [])


def test_machine_shards_disjoint_and_path_independent(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        specs = _templates(registry, tmp_path, count=12)
        owners = [{inc.batch_identity(spec) for spec in specs if inc.assignment(spec, 3, 2)["machine_shard_index"] == host}
                  for host in range(3)]
        assert set.union(*owners) == {inc.batch_identity(spec) for spec in specs}
        assert not any(owners[a] & owners[b] for a in range(3) for b in range(a))
        assert inc.batch_identity(specs[0]) == inc.batch_identity(replace(specs[0],
            output_directory=str(tmp_path / "other"), run_id="elsewhere", job_id="elsewhere"))


def test_campaign_shared_targets_arrow_first_parent_and_sparse_continuation(tmp_path, monkeypatch):
    from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_campaign_shared_sparse_arrow import (
        _combined, _injected_worker,
    )
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        combined = _combined(registry, tmp_path, monkeypatch, arrow=True)
        observations = {}
        seen_arrow = []
        def worker(spec):
            arrow = spec.arrow_feature_weights_artifact is not None
            seen_arrow.append(arrow)
            return _injected_worker(combined, observations, arrow=arrow)(spec)
        result = inc.run_incremental_training(registry, list(combined.specs),
            state_directory=tmp_path / "incremental", lane_count=1,
            executor_factory=ImmediateExecutor, worker_function=worker)
        assert result["completed_batch_count"] == 2
        assert seen_arrow == [True, False]
        assert all(row["result"]["shared_targets_verified"] for row in result["completed"])
        assert all(row["result"]["sparse_replay_verified"] for row in result["completed"])
        assert all(row["result"]["source_campaign_verified"] for row in result["completed"])
        assert all(Path(path).read_bytes() == raw for path, raw in combined.shared_files.items())


def test_registry_and_progress_reopen_resume_tip_only(tmp_path, monkeypatch):
    database, artifacts = tmp_path / "owner.duckdb", tmp_path / "artifacts"
    with AutoencoderRegistry(database, artifacts) as registry:
        specs = _templates(registry, tmp_path, count=12)
        result = _run(registry, tmp_path, specs, max_batches=12)
        assert result["completed_batch_count"] == 12
    calls = []
    verify = inc._verify_completed
    def counted(registry, spec):
        calls.append(spec.run_id)
        return verify(registry, spec)
    monkeypatch.setattr(inc, "_verify_completed", counted)
    with AutoencoderRegistry(database, artifacts) as registry:
        result = _run(registry, tmp_path, [])
        assert result["completed_batch_count"] == 12
        assert not result["dispatched_run_ids"]
        assert len(calls) == len(result["completed"]) == 2


def test_running_lane_remains_uncertain_after_reopen(tmp_path, monkeypatch):
    database, artifacts = tmp_path / "owner.duckdb", tmp_path / "artifacts"
    original = inc.coordinator.run_training_jobs
    def leave_running(registry, specs, **kwargs):
        registry.claim_run("fixture-claim", specs[0].run_id, "fixture-lost-owner")
        raise RuntimeError("owner vanished")
    with AutoencoderRegistry(database, artifacts) as registry:
        specs = _templates(registry, tmp_path, count=2)
        monkeypatch.setattr(inc.coordinator, "run_training_jobs", leave_running)
        with pytest.raises(RuntimeError, match="vanished"):
            _run(registry, tmp_path, specs, lane_count=1)
    monkeypatch.setattr(inc.coordinator, "run_training_jobs", original)
    with AutoencoderRegistry(database, artifacts) as registry:
        result = _run(registry, tmp_path, specs, lane_count=1)
        assert result["blocked"][0]["status"] == "running"
        assert not result["dispatched_run_ids"]
