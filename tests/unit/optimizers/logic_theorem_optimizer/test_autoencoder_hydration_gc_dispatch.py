"""GC policy dispatch contracts only; fake executors never prove native work."""

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_coordinator as coordinator
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker


class _Untouched:
    def __iter__(self):
        raise AssertionError("invalid option must be rejected before consuming jobs")

    def __getattr__(self, name):
        raise AssertionError("invalid option must be rejected before registry access")


@pytest.mark.parametrize("option", [None, 0, 1, 0.0, "true", [], {}])
def test_nonboolean_gc_option_rejected_before_jobs_or_registry(option):
    with pytest.raises(coordinator.TrainingCoordinationError, match="must be boolean"):
        coordinator.run_training_jobs(_Untouched(), _Untouched(), defer_target_hydration_gc=option)


@pytest.mark.parametrize("injection", ["executor", "worker", "both"])
def test_gc_optin_rejects_injected_execution_before_registry_mutation(injection):
    def forbidden(*args, **kwargs):
        raise AssertionError("injected execution must not be reached")

    kwargs = {"defer_target_hydration_gc": True}
    if injection in ("executor", "both"):
        kwargs["executor_factory"] = forbidden
    if injection in ("worker", "both"):
        kwargs["worker_function"] = forbidden
    with pytest.raises(coordinator.TrainingCoordinationError, match="native spawned worker"):
        coordinator.run_training_jobs(_Untouched(), _Untouched(), **kwargs)


@pytest.mark.parametrize("deferred", [False, True])
def test_declared_native_dispatch_selects_expected_entry_without_executing_it(monkeypatch, tmp_path, deferred):
    """Replace the pool to inspect submission; this is unit evidence only."""
    spec = worker.TrainingJobSpec.from_dict({
        "job_id": "dispatch-fixture", "run_id": "dispatch-run", "base_version_id": "fixture-base",
        "base_checkpoint": {"path": str(tmp_path / "absent-base.json"), "bytes": 1, "sha256": "a" * 64},
        "output_directory": str(tmp_path / "absent-output"), "code_identity": "unit-fixture",
        "dataset_snapshot_id": "fixture-data", "split_snapshot_id": "fixture-split",
        "samples": [{"title": "5", "section": "1", "text": "The agency shall retain records."}],
    })
    submissions, shutdowns, claims, failures = [], [], [], []

    class StoppedBeforeExecution(RuntimeError):
        pass

    class FakePool:
        def __init__(self, *, max_workers, mp_context):
            assert max_workers == 1
            assert mp_context.get_start_method() == "spawn"

        def submit(self, function, submitted):
            submissions.append((function, submitted))
            raise StoppedBeforeExecution("unit-only pool did not execute a worker")

        def shutdown(self, **kwargs):
            shutdowns.append(kwargs)

    class FakeRegistry:
        def claim_run(self, operation_id, run_id, worker_id, lease_seconds):
            claims.append(run_id)
            return {"lease": {"run_id": run_id, "expires_at": 300.0}}

        def get_run(self, run_id):
            return {"status": "running", "run_id": run_id}

        def fail_run(self, operation_id, lease, error):
            failures.append(error)
            return {"status": "failed"}

    monkeypatch.setattr(coordinator, "ProcessPoolExecutor", FakePool)
    monkeypatch.setattr(coordinator, "_validate_runs", lambda registry, specs: {spec.run_id: {}})
    report = coordinator.run_training_jobs(FakeRegistry(), [spec], max_workers=1, clock=lambda: 0.0,
                                          defer_target_hydration_gc=deferred)
    expected = worker._execute_native_training_job_with_deferred_gc if deferred else worker.execute_training_job
    assert submissions == [(expected, spec)]
    assert claims == [spec.run_id]
    assert shutdowns == [{"wait": True, "cancel_futures": True}]
    assert report["defer_target_hydration_gc"] is deferred
    assert report["completed"] == []
    assert len(failures) == 1 and failures[0]["error_type"] == "StoppedBeforeExecution"
    assert not (tmp_path / "absent-output").exists()
