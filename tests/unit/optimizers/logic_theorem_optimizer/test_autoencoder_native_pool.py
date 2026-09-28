"""Reuse must preserve fresh state, native-only dispatch and producer identity."""
from concurrent.futures import Future

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_native_pool as pools
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_coordinator as coordinator


class Executor:
    def __init__(self, **kwargs):
        assert kwargs["mp_context"].get_start_method() == "spawn"
        self.closed = False
        self.calls = []

    def submit(self, *args):
        self.calls.append(args)
        return Future()

    def shutdown(self, **kwargs):
        assert kwargs == {"wait": True, "cancel_futures": True}
        self.closed = True


def make_pool(monkeypatch):
    monkeypatch.setattr(pools, "ProcessPoolExecutor", Executor)
    monkeypatch.setattr(pools, "_package_manifest", lambda: {"sha256": "first", "file_count": 1})
    return pools._NativeTrainingPool(2)


def test_pool_refuses_drift_width_and_unbounded_lifetime(monkeypatch):
    pool = make_pool(monkeypatch)
    pool.validate_dispatch(2, 2)
    with pytest.raises(ValueError, match="width"):
        pool.validate_dispatch(1, 1)
    for _ in range(pools.MAX_POOL_JOBS):
        pool.submit(object())
    with pytest.raises(ValueError, match="lifetime"):
        pool.validate_dispatch(2, 1)
    with pytest.raises(ValueError, match="exhausted"):
        pool.submit(object())
    pool.submitted_jobs = 0
    monkeypatch.setattr(pools, "_package_manifest", lambda: {"sha256": "changed", "file_count": 1})
    with pytest.raises(ValueError, match="source changed"):
        pool.validate_dispatch(2, 1)
    pool.close()
    pool.close()
    assert pool.executor.closed


def test_pool_rejects_injected_native_authority_before_registry_access(monkeypatch):
    pool = make_pool(monkeypatch)
    with pytest.raises(coordinator.TrainingCoordinationError, match="injected"):
        coordinator.run_training_jobs(None, [], _native_pool=pool, executor_factory=Executor)
    with pytest.raises(coordinator.TrainingCoordinationError, match="injected"):
        coordinator.run_training_jobs(None, [], _native_pool=object())
    pool.close()


def test_recycled_pool_cannot_adopt_a_new_cycle_manifest(monkeypatch):
    original = make_pool(monkeypatch)
    binding = dict(original.manifest)
    original.close()
    replacement = pools._NativeTrainingPool(1, expected_manifest=binding)
    assert replacement.manifest == binding
    replacement.close()
    monkeypatch.setattr(pools, "_package_manifest", lambda: {"sha256": "changed", "file_count": 1})
    monkeypatch.setattr(pools, "ProcessPoolExecutor", lambda **kwargs: pytest.fail("started drifted executor"))
    with pytest.raises(ValueError, match="cycle manifest"):
        pools._NativeTrainingPool(1, expected_manifest=binding)


def test_worker_reloads_each_job_and_clears_targets_even_on_error(monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as modal
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
    manifest = {"sha256": "fixture", "file_count": 1}
    monkeypatch.setattr(pools, "_package_manifest", lambda: manifest)
    monkeypatch.setattr(pools, "_PROCESS_MANIFEST", None)
    monkeypatch.setattr(pools, "_PROCESS_JOBS", 0)
    monkeypatch.setattr(pools, "_WORKER_RUNTIME", None)
    monkeypatch.setattr(modal, "_LEGAL_IR_TARGET_CACHE", {"previous": "old"})
    calls = []

    def execute(spec):
        assert not modal._LEGAL_IR_TARGET_CACHE
        calls.append((spec, pools.worker_runtime()))
        modal._LEGAL_IR_TARGET_CACHE["this_job"] = object()
        if spec == "fail":
            raise RuntimeError("worker failed")
        return {"fixture_only": True}

    monkeypatch.setattr(worker, "execute_training_job", execute)
    assert pools._execute_pool_job("base-a", manifest) == {"fixture_only": True}
    assert pools._execute_pool_job("base-b", manifest) == {"fixture_only": True}
    with pytest.raises(RuntimeError, match="worker failed"):
        pools._execute_pool_job("fail", manifest)
    assert [row[0] for row in calls] == ["base-a", "base-b", "fail"]
    assert [row[1]["process_reused"] for row in calls] == [False, True, True]
    assert calls[0][1]["target_cache_cleared_entries"] == 1
    assert not modal._LEGAL_IR_TARGET_CACHE
    assert pools.worker_runtime() is None
    monkeypatch.setattr(pools, "_package_manifest", lambda: {"sha256": "drift", "file_count": 1})
    with pytest.raises(ValueError, match="source changed"):
        pools._execute_pool_job("unexecuted", manifest)
    assert len(calls) == 3


def test_worker_detects_mid_job_drift_before_returning_candidate(monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_training_worker as worker
    before = {"sha256": "before", "file_count": 1}
    after = {"sha256": "after", "file_count": 1}
    manifests = iter((before, after))
    monkeypatch.setattr(pools, "_package_manifest", lambda: next(manifests))
    monkeypatch.setattr(pools, "_PROCESS_MANIFEST", None)
    monkeypatch.setattr(worker, "execute_training_job", lambda spec: {"fixture_only": True})
    with pytest.raises(ValueError, match="unregistered"):
        pools._execute_pool_job(None, before)
