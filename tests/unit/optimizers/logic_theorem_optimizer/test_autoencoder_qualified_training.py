"""Durable retries and fail-closed qualification with explicitly injected work."""
from dataclasses import replace
import json
from pathlib import Path

import duckdb
import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_qualified_training as qt
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_incremental_training import IncrementalTrainingError, assignment
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_training_worker import SampleRecord
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_training_coordinator import (
    ImmediateExecutor, _prepare_sparse, _sparse_worker,
)


def _receipt(artifact, version, *, metric=True, syntax=True, heldout=True):
    gates = {name: {"passed": True} for name in qt.GATES}
    gates["metric_gate"]["passed"] = metric
    gates["family_syntax_gate"]["passed"] = syntax
    gates["heldout_gate"]["passed"] = heldout
    return {"candidate_version_id": version, "candidate_artifact": {k: artifact[k] for k in ("sha256", "bytes")},
            "gate_results": gates, "metric_gate": gates["metric_gate"],
            "qualified": all(gate["passed"] for gate in gates.values()), "needs_training": not metric,
            "repair_todos": [] if syntax else [{"kind": "source_repair", "gate": "family_syntax_gate"}],
            "admitted": False}


def _pass(artifact, version, samples, output, **kwargs):
    return _receipt(artifact, version)


def _run(registry, root, templates, **kwargs):
    return qt.run_qualified_incremental_training(registry, templates,
        state_directory=root / "qualified", lane_count=kwargs.pop("lane_count", 1),
        control_transport="owner",
        executor_factory=ImmediateExecutor, worker_function=_sparse_worker,
        qualifier=kwargs.pop("qualifier", _pass), **kwargs)


def test_failed_metric_retries_exact_private_parent_then_qualifies(tmp_path):
    calls = []
    def qualify(artifact, version, *args, **kwargs):
        calls.append(version)
        return _receipt(artifact, version, metric=len(calls) > 1)
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare_sparse(registry, tmp_path)
        first = _run(registry, tmp_path, [spec], qualifier=qualify, max_batches=1)
        assert first["qualified_batch_count"] == 0
        assert first["pending_batch_count"] == 1
        accepted = first["completed"][0]["optimizer"]["candidate_version_id"]
        second = _run(registry, tmp_path, [spec], qualifier=qualify)
        assert second["qualified_batch_count"] == 1
        assert len(second["dispatched_run_ids"]) == 1
        assert registry.get_run(second["dispatched_run_ids"][0])["base_version_id"] == accepted
        assert registry.resolve_head("english-0", "best")["version_id"] == spec.base_version_id
        third = _run(registry, tmp_path, [spec], qualifier=qualify)
        assert not third["dispatched_run_ids"] and len(calls) == 2
        assert third["admitted"] is False and third["execution_mode"] == "injected_test"


def test_metric_exhaustion_is_repair_work_never_qualified(tmp_path):
    def qualify(artifact, version, *args, **kwargs):
        return _receipt(artifact, version, metric=False, syntax=False)
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare_sparse(registry, tmp_path)
        result = _run(registry, tmp_path, [spec], qualifier=qualify, max_training_rounds=2)
        assert len(result["dispatched_run_ids"]) == 2
        assert result["batch_status_counts"] == {"training_exhausted": 1}
        assert result["qualified_batch_count"] == 0
        last = result["completed"][-1]
        outbox = qt._read_artifact(registry, last["repair_outbox"])
        assert {task["kind"] for task in outbox["tasks"]} == {"source_repair", "training_repair"}
        assert not outbox["supervisor_submitted"] and not outbox["published"]
        assert not _run(registry, tmp_path, [], qualifier=qualify, max_training_rounds=2)["dispatched_run_ids"]


def test_structural_failure_stops_sgd_and_advances_lane_with_repair_outbox(tmp_path):
    def qualify(artifact, version, *args, **kwargs):
        return _receipt(artifact, version, syntax=False)
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare_sparse(registry, tmp_path)
        result = _run(registry, tmp_path, [spec, replace(spec, dataset_snapshot_id="second")], qualifier=qualify)
        assert len(result["dispatched_run_ids"]) == 2
        assert result["batch_status_counts"] == {"needs_repair": 2}
        assert all(not row["qualified"] for row in result["completed"])


def test_false_summary_or_different_candidate_never_qualifies(tmp_path):
    def forged(artifact, version, *args, **kwargs):
        return {**_receipt(artifact, version, syntax=False), "qualified": True}
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare_sparse(registry, tmp_path)
        with pytest.raises(IncrementalTrainingError, match="summary"):
            _run(registry, tmp_path, [spec], qualifier=forged)
        with duckdb.connect(str(tmp_path / "qualified/qualification.duckdb")) as db:
            assert db.execute("SELECT status FROM batches").fetchone()[0] == "pending"


def test_lost_owner_after_training_replays_without_retraining(tmp_path, monkeypatch):
    original = qt.coordinator.run_training_jobs
    def lost(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("lost response")
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare_sparse(registry, tmp_path)
        monkeypatch.setattr(qt.coordinator, "run_training_jobs", lost)
        with pytest.raises(RuntimeError, match="lost response"):
            _run(registry, tmp_path, [spec])
        monkeypatch.setattr(qt.coordinator, "run_training_jobs", lambda *a, **k: pytest.fail("duplicate training"))
        result = _run(registry, tmp_path, [])
        assert result["qualified_batch_count"] == 1 and not result["dispatched_run_ids"]


def test_unfinished_qualification_keeps_original_attempt_and_blocks_overwrite(tmp_path):
    def interrupted(artifact, version, samples, output, **kwargs):
        output.mkdir()
        raise RuntimeError("interrupted qualification")
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare_sparse(registry, tmp_path)
        with pytest.raises(RuntimeError, match="interrupted"):
            _run(registry, tmp_path, [spec], qualifier=interrupted)
        with pytest.raises(IncrementalTrainingError, match="unfinished qualification"):
            _run(registry, tmp_path, [])


def test_resume_rejects_modified_qualification_artifact(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare_sparse(registry, tmp_path)
        result = _run(registry, tmp_path, [spec])
        descriptor = result["completed"][0]["qualification_artifact"]
        registry.artifact_path({key: descriptor[key] for key in ("sha256", "bytes")}).write_text("{}")
        with pytest.raises(ValueError):
            _run(registry, tmp_path, [])


def test_validation_overlap_across_batches_and_policy_change_reject(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        original = _prepare_sparse(registry, tmp_path)
        validation = SampleRecord("5", "2", "The officer shall report changes.")
        spec = replace(original, validation_samples=(validation,))
        _run(registry, tmp_path, [spec])
        with pytest.raises(IncrementalTrainingError, match="overlap"):
            _run(registry, tmp_path, [replace(spec, samples=(replace(validation, text=validation.text.upper()),))])
        with pytest.raises(IncrementalTrainingError, match="binding"):
            _run(registry, tmp_path, [], max_training_rounds=4)


def test_two_lanes_dispatch_before_qualification(tmp_path):
    observations = []
    def qualify(artifact, version, *args, **kwargs):
        observations.append(version)
        return _receipt(artifact, version)
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare_sparse(registry, tmp_path)
        selected = {}
        for index in range(30):
            candidate = replace(spec, dataset_snapshot_id=str(index))
            selected.setdefault(assignment(candidate, 1, 2)["lane_index"], candidate)
        result = _run(registry, tmp_path, list(selected.values()), lane_count=2, qualifier=qualify)
        assert len(result["dispatch_reports"]) == 1 and len(observations) == 2
        assert result["qualified_batch_count"] == 2


def _lane_templates(spec, count):
    selected = {}
    for index in range(200):
        candidate = replace(spec, dataset_snapshot_id="capacity-" + str(index))
        selected.setdefault(assignment(candidate, 1, count)["lane_index"], candidate)
        if len(selected) == count:
            return list(selected.values())
    raise AssertionError("unable to fill test lanes")


def test_dispatch_capacity_recomputed_at_boundaries_keeps_logical_lane_bindings(tmp_path):
    decisions, dispatched_widths = [], []
    capacities = iter((1, 2))
    def capacity(**request):
        decisions.append(request)
        return {"workers": next(capacities), "reason": "injected resource envelope"}
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare_sparse(registry, tmp_path)
        templates = _lane_templates(spec, 3)
        result = _run(registry, tmp_path, templates, lane_count=3, capacity_callback=capacity)
        assert [plan["workers"] for plan in result["capacity_reports"]] == [1, 2]
        assert decisions == [{"pending_count": 3, "max_workers": 3},
                             {"pending_count": 2, "max_workers": 3}]
        assert result["qualified_batch_count"] == 3
        assert result["binding"]["lane_count"] == 3
        assert {row["lane_index"] for row in result["completed"]} == {0, 1, 2}
        assert "capacity_callback" not in result["binding"]


def test_zero_capacity_defers_without_registering_attempt_and_resume_can_scale_up(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare_sparse(registry, tmp_path)
        templates = _lane_templates(spec, 3)
        paused = _run(registry, tmp_path, templates, lane_count=3, max_parallel_workers=1,
                      capacity_callback=lambda **request: {"workers": 0, "reason": "memory"})
        assert paused["capacity_deferred"] is True
        assert paused["pending_batch_count"] == 3
        assert paused["dispatched_run_ids"] == []
        with duckdb.connect(str(tmp_path / "qualified/qualification.duckdb")) as db:
            assert db.execute("SELECT count(*) FROM attempts").fetchone()[0] == 0
        resumed = _run(registry, tmp_path, [], lane_count=3, max_parallel_workers=2)
        assert resumed["binding"] == paused["binding"]
        assert [plan["workers"] for plan in resumed["capacity_reports"]] == [2, 1]
        assert resumed["qualified_batch_count"] == 3


def test_completed_attempt_recovers_even_when_capacity_is_now_zero(tmp_path, monkeypatch):
    original = qt.coordinator.run_training_jobs
    def lost(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("lost response")
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare_sparse(registry, tmp_path)
        monkeypatch.setattr(qt.coordinator, "run_training_jobs", lost)
        with pytest.raises(RuntimeError, match="lost response"):
            _run(registry, tmp_path, [spec])
        monkeypatch.setattr(qt.coordinator, "run_training_jobs", lambda *args, **kwargs: pytest.fail("duplicate training"))
        resumed = _run(registry, tmp_path, [], capacity_callback=lambda **request: {"workers": 0})
        assert resumed["qualified_batch_count"] == 1
        assert not resumed["dispatched_run_ids"]


@pytest.mark.parametrize("returned", [{"workers": -1}, {"workers": 2}, {"workers": True},
                                      {"workers": 1, "pressure": float("nan")}, 1])
def test_bad_capacity_callback_cannot_override_dispatch_budget(tmp_path, returned):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare_sparse(registry, tmp_path)
        with pytest.raises(IncrementalTrainingError, match="capacity"):
            _run(registry, tmp_path, [spec], capacity_callback=lambda **request: returned)
        with duckdb.connect(str(tmp_path / "qualified/qualification.duckdb")) as db:
            assert db.execute("SELECT count(*) FROM attempts").fetchone()[0] == 0


@pytest.mark.parametrize("reuse", [False, True])
def test_native_cycle_rejects_dispatch_drift_even_with_fresh_workers(tmp_path, monkeypatch, reuse):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_native_pool as pools
    manifest = {"sha256": "original", "file_count": 1}
    monkeypatch.setattr(pools, "_package_manifest", lambda: dict(manifest))
    monkeypatch.setattr(qt.coordinator, "run_training_jobs", lambda *a, **k: pytest.fail("drifted dispatch"))

    def capacity(**request):
        manifest["sha256"] = "changed"
        return {"workers": 1}

    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare_sparse(registry, tmp_path)
        with pytest.raises(IncrementalTrainingError, match="cycle producer source changed"):
            qt.run_qualified_incremental_training(registry, [spec], state_directory=tmp_path / "qualified",
                lane_count=1, control_transport="owner", capacity_callback=capacity,
                reuse_native_workers=reuse)
        with duckdb.connect(str(tmp_path / "qualified/qualification.duckdb")) as db:
            assert db.execute("SELECT count(*) FROM attempts").fetchone()[0] == 0


@pytest.mark.parametrize("phase", ["before", "during"])
def test_cycle_drift_cannot_stage_a_new_qualification(tmp_path, monkeypatch, phase):
    """Isolated control-flow injection; no native workers or Lake are executed."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_native_pool as pools
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_candidate_qualification as qualifier
    manifest = {"sha256": "original", "file_count": 1}
    monkeypatch.setattr(pools, "_package_manifest", lambda: dict(manifest))
    calls = []
    original_dispatch = qt.coordinator.run_training_jobs
    original_completion = qt.inc._completion

    def injected_dispatch(registry, specs, **kwargs):
        report = original_dispatch(registry, specs, max_workers=1,
                                   executor_factory=ImmediateExecutor, worker_function=_sparse_worker)
        assert report["execution_mode"] == "injected_test"
        return report

    def completion(*args, **kwargs):
        result = original_completion(*args, **kwargs)
        if phase == "before":
            manifest["sha256"] = "changed"
        return result

    def qualify(*args, **kwargs):
        calls.append("injected qualifier")
        manifest["sha256"] = "changed"
        return _pass(*args, **kwargs)

    monkeypatch.setattr(qt.coordinator, "run_training_jobs", injected_dispatch)
    monkeypatch.setattr(qt.inc, "_completion", completion)
    monkeypatch.setattr(qualifier, "qualify_candidate", qualify)
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare_sparse(registry, tmp_path)
        with pytest.raises(IncrementalTrainingError, match="cycle producer source changed"):
            qt.run_qualified_incremental_training(registry, [spec], state_directory=tmp_path / "qualified",
                lane_count=1, control_transport="owner", reuse_native_workers=False)
        assert len(calls) == int(phase == "during")
        assert not list((tmp_path / "qualified").glob("*.qualification.json"))
        assert not list((tmp_path / "qualified").glob("*.qualification-payload.json"))
        with duckdb.connect(str(tmp_path / "qualified/qualification.duckdb")) as db:
            assert db.execute("SELECT status FROM batches").fetchone()[0] == "pending"


def test_native_manifest_binds_resume_but_fresh_worker_flag_does_not(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_native_pool as pools
    manifest = {"sha256": "original", "file_count": 1}
    monkeypatch.setattr(pools, "_package_manifest", lambda: dict(manifest))
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        first = qt.run_qualified_incremental_training(registry, [], state_directory=tmp_path / "qualified",
                                                      control_transport="owner", reuse_native_workers=True)
        second = qt.run_qualified_incremental_training(registry, [], state_directory=tmp_path / "qualified",
                                                       control_transport="owner", reuse_native_workers=False)
        assert first["binding"] == second["binding"]
        assert first["native_cycle_manifest"] == second["native_cycle_manifest"] == manifest
        assert first["binding"]["policy"]["native_producer_manifest"] == manifest
        assert not first["dispatched_run_ids"] and not second["dispatched_run_ids"]
        manifest["sha256"] = "changed-non-core-bridge"
        with pytest.raises(IncrementalTrainingError, match="owner/topology/policy binding changed"):
            qt.run_qualified_incremental_training(registry, [], state_directory=tmp_path / "qualified",
                                                  control_transport="owner", reuse_native_workers=True)
        with duckdb.connect(str(tmp_path / "qualified/qualification.duckdb")) as db:
            persisted = json.loads(db.execute("SELECT binding FROM stream WHERE singleton=1").fetchone()[0])
            assert persisted == first["binding"]
            assert db.execute("SELECT count(*) FROM attempts").fetchone()[0] == 0


def test_injected_runner_has_no_native_producer_manifest(tmp_path):
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        report = _run(registry, tmp_path, [])
        assert report["binding"]["policy"]["native_producer_manifest"] is None
        assert report["native_cycle_manifest"] is None
        assert report["execution_mode"] == "injected_test"


def test_legacy_optimizer_progress_requires_explicit_new_stream(tmp_path):
    (tmp_path / "qualified").mkdir()
    (tmp_path / "qualified/progress.duckdb").touch()
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        with pytest.raises(IncrementalTrainingError, match="new qualified stream"):
            _run(registry, tmp_path, [])


def test_separate_qualification_samples_are_bound_excluded_and_passed_to_gate(tmp_path):
    observed = []
    validation = {"title": "5", "section": "2", "text": "The officer shall report changes."}
    def qualify(artifact, version, samples, output, **kwargs):
        observed.extend(kwargs["heldout_samples"])
        return _receipt(artifact, version)
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare_sparse(registry, tmp_path)
        result = _run(registry, tmp_path, [spec], qualifier=qualify, qualification_samples=[validation])
        job = json.loads((tmp_path / "qualified" / (result["dispatched_run_ids"][0] + ".json")).read_bytes())
        assert job["validation_samples"] == []
        assert observed[0]["text"] == validation["text"]
        with pytest.raises(IncrementalTrainingError, match="overlap"):
            _run(registry, tmp_path, [replace(spec, samples=(SampleRecord.from_dict(validation),))],
                 qualifier=qualify, qualification_samples=[validation])
        with pytest.raises(IncrementalTrainingError, match="binding"):
            _run(registry, tmp_path, [], qualifier=qualify, qualification_samples=[])


def test_qualified_runner_preserves_shared_targets_and_arrow_weight_continuation(tmp_path, monkeypatch):
    from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_campaign_shared_sparse_arrow import (
        _combined, _injected_worker,
    )
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        combined = _combined(registry, tmp_path, monkeypatch, arrow=True)
        seen, observations = [], {}
        def worker(spec):
            arrow = spec.arrow_feature_weights_artifact is not None
            seen.append(arrow)
            return _injected_worker(combined, observations, arrow=arrow)(spec)
        result = qt.run_qualified_incremental_training(registry, combined.specs,
            state_directory=tmp_path / "qualified", lane_count=1,
            control_transport="owner",
            executor_factory=ImmediateExecutor, worker_function=worker, qualifier=_pass)
        assert seen == [True, False], result["dispatch_reports"]
        assert result["qualified_batch_count"] == 2 and result["execution_mode"] == "injected_test"
        assert all(row["optimizer"]["result"]["shared_targets_verified"] for row in result["completed"])
        assert all(row["optimizer"]["result"]["sparse_replay_verified"] for row in result["completed"])
        assert all(Path(path).read_bytes() == content for path, content in combined.shared_files.items())


PUBLICATION_REPOSITORY = "justicedao/uscode-autoformal-span-cache"


def _mock_publication_boundaries(monkeypatch, *, progress_path, fail_phase=None, lose_first_enqueue=False):
    """Mock packaging only; use the actual registry's durable publication outbox.

    These tests exercise runner sequencing with injected qualification. The
    fixture manifest is explicitly not native publication evidence, and no Hub
    client, package validator, or network upload is invoked.
    """
    from ipfs_datasets_py.huggingface import autoencoder_incremental as publication
    calls = []
    lost = False

    def assert_before_attempt_commit():
        with duckdb.connect(str(progress_path)) as progress:
            assert progress.execute("SELECT status FROM batches").fetchall() == [("pending",)]
            assert progress.execute("SELECT completed FROM attempts").fetchall() == [(None,)]

    def stage(registry, version_id, qualification_artifact, output_directory, *, lane_id, repository_id):
        assert_before_attempt_commit()
        assert repository_id == PUBLICATION_REPOSITORY
        registry.verify_artifact(qualification_artifact)
        receipt = qt._read_artifact(registry, qualification_artifact)
        assert receipt["candidate_version_id"] == version_id
        assert receipt["qualified"] is True
        assert all(receipt["gate_results"][name]["passed"] is True for name in qt.GATES)
        assert receipt["admitted"] is False
        calls.append(("stage", version_id, dict(qualification_artifact), lane_id))
        if fail_phase == "stage":
            raise publication.IncrementalPublicationError("fixture: full anchor upload is not authorized")
        directory = Path(output_directory)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "fixture.manifest.json"
        manifest = {"schema": "injected-qualification-publication-boundary-fixture",
                    "version_id": version_id, "qualification_artifact": qualification_artifact,
                    "repository_id": repository_id, "lane_id": lane_id, "admitted": False}
        raw = json.dumps(manifest, sort_keys=True).encode()
        if path.exists():
            assert path.read_bytes() == raw
        else:
            path.write_bytes(raw)
        return {"manifest_path": str(path), "uploaded": False}

    def enqueue(registry, manifest_path):
        nonlocal lost
        assert_before_attempt_commit()
        manifest = json.loads(Path(manifest_path).read_bytes())
        calls.append(("enqueue", manifest["version_id"], str(manifest_path)))
        if fail_phase == "enqueue":
            raise publication.IncrementalPublicationError("fixture: publication closure is incomplete")
        artifact = registry.stage_artifact(manifest_path)
        result = registry.enqueue_publication("test-publication:" + manifest["version_id"],
                                               manifest["version_id"], artifact)
        if lose_first_enqueue and not lost:
            lost = True
            raise RuntimeError("publication enqueue response lost after durable commit")
        return result

    monkeypatch.setattr(publication, "stage_sparse_update", stage)
    monkeypatch.setattr(publication, "enqueue_sparse_update", enqueue)
    return calls


def test_qualified_publication_is_enqueued_before_attempt_commit_and_not_uploaded(tmp_path, monkeypatch):
    calls = _mock_publication_boundaries(monkeypatch,
        progress_path=tmp_path / "qualified/qualification.duckdb")
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare_sparse(registry, tmp_path)
        result = _run(registry, tmp_path, [spec], publication_repository=PUBLICATION_REPOSITORY)
        assert [call[0] for call in calls] == ["stage", "enqueue"]
        assert result["execution_mode"] == "injected_test"
        assert result["qualified_batch_count"] == 1
        assert not result["publication_performed"] and not result["admitted"]
        completed = result["completed"][0]
        assert completed["publication"]["uploaded"] is False
        events = registry.pending_outbox("huggingface")
        assert len(events) == 1 and events[0]["event_id"] == completed["publication"]["event_id"]
        assert events[0]["payload"]["version_id"] == completed["optimizer"]["candidate_version_id"]
        assert calls[0][2] == {key: completed["qualification_artifact"][key] for key in ("sha256", "bytes")}
        assert calls[0][3] == "shard-0-lane-0"
        resumed = _run(registry, tmp_path, [], publication_repository=PUBLICATION_REPOSITORY)
        assert not resumed["dispatched_run_ids"]
        assert resumed["completed"][0]["publication"] == completed["publication"]
        assert len(calls) == 2 and len(registry.pending_outbox("huggingface")) == 1


def test_lost_publication_enqueue_response_replays_same_event_without_training(tmp_path, monkeypatch):
    calls = _mock_publication_boundaries(monkeypatch,
        progress_path=tmp_path / "qualified/qualification.duckdb", lose_first_enqueue=True)
    qualifications = []
    def qualify(artifact, version, *args, **kwargs):
        qualifications.append(version)
        return _receipt(artifact, version)
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare_sparse(registry, tmp_path)
        with pytest.raises(RuntimeError, match="response lost after durable commit"):
            _run(registry, tmp_path, [spec], qualifier=qualify, publication_repository=PUBLICATION_REPOSITORY)
        event = registry.pending_outbox("huggingface")[0]
        with duckdb.connect(str(tmp_path / "qualified/qualification.duckdb")) as progress:
            assert progress.execute("SELECT status FROM batches").fetchone()[0] == "pending"
            assert progress.execute("SELECT completed FROM attempts").fetchone()[0] is None
        monkeypatch.setattr(qt.coordinator, "run_training_jobs",
                            lambda *args, **kwargs: pytest.fail("publication retry retrained the model"))
        result = _run(registry, tmp_path, [], qualifier=qualify, publication_repository=PUBLICATION_REPOSITORY)
        assert result["qualified_batch_count"] == 1 and not result["dispatched_run_ids"]
        assert len(qualifications) == 1
        assert [call[0] for call in calls] == ["stage", "enqueue", "stage", "enqueue"]
        assert calls[0] == calls[2] and calls[1] == calls[3]
        assert result["completed"][0]["publication"]["event_id"] == event["event_id"]
        assert registry.pending_outbox("huggingface") == [event]


@pytest.mark.parametrize("phase", ["stage", "enqueue"])
def test_publication_rejection_keeps_qualification_and_records_deferred_repair(tmp_path, monkeypatch, phase):
    calls = _mock_publication_boundaries(monkeypatch,
        progress_path=tmp_path / "qualified/qualification.duckdb", fail_phase=phase)
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare_sparse(registry, tmp_path)
        result = _run(registry, tmp_path, [spec], publication_repository=PUBLICATION_REPOSITORY)
        completed = result["completed"][0]
        assert completed["qualified"] and completed["qualification_status"] == "qualified"
        assert completed["publication"]["status"] == "deferred"
        assert completed["publication"]["uploaded"] is False
        assert "fixture:" in completed["publication"]["reason"]
        outbox = qt._read_artifact(registry, completed["repair_outbox"])
        assert len(outbox["tasks"]) == 1 and outbox["tasks"][0]["kind"] == "publication_repair"
        task = outbox["tasks"][0]
        assert task["candidate_version_id"] == completed["optimizer"]["candidate_version_id"]
        assert task["qualification_artifact"] == completed["qualification_artifact"]
        assert task["evidence"] == completed["publication"]
        assert not task["admitted"] and not outbox["published"] and not outbox["supervisor_submitted"]
        assert not registry.pending_outbox("huggingface")
        assert len(calls) == (1 if phase == "stage" else 2)
        resumed = _run(registry, tmp_path, [], publication_repository=PUBLICATION_REPOSITORY)
        assert resumed["completed"][0]["publication"] == completed["publication"]
        assert not resumed["dispatched_run_ids"]


@pytest.mark.parametrize("failed_gate", ["metric", "syntax", "heldout"])
def test_unqualified_candidates_never_reach_publication_boundaries(tmp_path, monkeypatch, failed_gate):
    from ipfs_datasets_py.huggingface import autoencoder_incremental as publication
    monkeypatch.setattr(publication, "stage_sparse_update", lambda *a, **k: pytest.fail("staged an unqualified candidate"))
    monkeypatch.setattr(publication, "enqueue_sparse_update", lambda *a, **k: pytest.fail("enqueued an unqualified candidate"))
    def qualify(artifact, version, *args, **kwargs):
        return _receipt(artifact, version, **{failed_gate: False})
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare_sparse(registry, tmp_path)
        result = _run(registry, tmp_path, [spec], qualifier=qualify, max_training_rounds=1,
                      publication_repository=PUBLICATION_REPOSITORY)
        assert result["qualified_batch_count"] == 0
        assert all(row["publication"] is None for row in result["completed"])
        assert not registry.pending_outbox("huggingface")
        assert result["execution_mode"] == "injected_test" and not result["publication_performed"]


def test_publication_repository_policy_is_bound_on_resume(tmp_path, monkeypatch):
    _mock_publication_boundaries(monkeypatch, progress_path=tmp_path / "qualified/qualification.duckdb")
    with AutoencoderRegistry(tmp_path / "owner.duckdb", tmp_path / "artifacts") as registry:
        spec = _prepare_sparse(registry, tmp_path)
        _run(registry, tmp_path, [spec], publication_repository=PUBLICATION_REPOSITORY)
        with pytest.raises(IncrementalTrainingError, match="policy binding changed"):
            _run(registry, tmp_path, [], publication_repository=None)
        with pytest.raises(IncrementalTrainingError, match="unsupported sparse publication repository"):
            _run(registry, tmp_path, [], publication_repository="different/public-dataset")
        assert len(registry.pending_outbox("huggingface")) == 1
