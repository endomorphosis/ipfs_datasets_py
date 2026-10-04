"""Real shared-lease admission with deterministic external-pressure evidence."""
from dataclasses import replace
import threading
import time

import pytest

from ipfs_datasets_py.logic.software_contracts import codebase_resources as resources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources


@pytest.fixture
def owner(tmp_path):
    healthy = ProofHostResources(8, 4096, 4096)
    current = [healthy]
    config = schedulers.ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / "resources.json",
        proof_resource_sampler=lambda: current[0],
        total_child_process_slots=4,
        lane_reservations={},
        auto_renew_leases=False,
        proof_backoff_seconds=0.05,
        poll_interval_seconds=0.005,
    )
    return schedulers.GlobalResourceScheduler(config), healthy, current


def assert_idle(scheduler):
    state = scheduler.snapshot()
    assert state["active_lease_count"] == 0
    assert state["waiting_request_count"] == 0


def test_default_uses_the_shared_safe_owner(owner, monkeypatch):
    scheduler, _, _ = owner
    monkeypatch.setattr(schedulers, "default_resource_scheduler_config", lambda: scheduler.config)
    shared = schedulers.get_global_resource_scheduler()
    with resources.acquire_codebase_resources(timeout_seconds=0) as lease:
        assert shared.config.proof_safety_enabled
        assert lease.token.state_path == str(shared.state_path)
        assert lease.parent_lease_id is None
        assert shared.snapshot()["active_root_lease_count"] == 1
    assert lease.released
    assert_idle(shared)


@pytest.mark.parametrize("fail", [False, True])
def test_nested_accounting_releases_child_but_preserves_parent(owner, monkeypatch, fail):
    scheduler, _, _ = owner
    def unexpected_global():
        raise AssertionError("a supplied parent must not allocate a separate root")
    monkeypatch.setattr(resources, "get_global_resource_scheduler", unexpected_global)
    with scheduler.acquire("orchestration", cpu_slots=2, memory_mb=1024,
                           child_process_slots=2, timeout=0) as parent:
        allocated = scheduler.snapshot()["allocated"]
        try:
            with resources.acquire_codebase_resources(parent_lease=parent, timeout_seconds=0) as child:
                assert child.parent_lease_id == parent.lease_id
                assert child.token.state_path == parent.token.state_path
                state = scheduler.snapshot()
                assert state["active_root_lease_count"] == 1
                assert state["active_lease_count"] == 2
                assert state["allocated"] == allocated
                if fail:
                    raise RuntimeError("extraction failed")
        except RuntimeError as error:
            assert fail and str(error) == "extraction failed"
        assert child.released
        assert not parent.released
        assert scheduler.snapshot()["active_lease_count"] == 1
    assert_idle(scheduler)


@pytest.mark.parametrize("pressure,reason", [
    ({"available_memory_mb": 100}, "proof_memory_headroom"),
    ({"cpu_stall_percent": 75}, "proof_cpu_stall"),
    ({"memory_stall_percent": 5}, "proof_memory_stall"),
    ({"io_stall_percent": 20}, "proof_io_stall"),
])
def test_pressure_defers_parent_child_then_recovers(owner, pressure, reason):
    scheduler, healthy, current = owner
    entered = threading.Event()
    errors = []
    with scheduler.acquire("orchestration", memory_mb=1024,
                           child_process_slots=1, timeout=0) as parent:
        current[0] = replace(healthy, **pressure)
        def run():
            try:
                with resources.acquire_codebase_resources(parent_lease=parent, timeout_seconds=2):
                    entered.set()
            except BaseException as error:
                errors.append(error)
        worker = threading.Thread(target=run)
        worker.start()
        try:
            deadline = time.monotonic() + 1
            while not scheduler.snapshot()["proof_backoff"] and time.monotonic() < deadline:
                time.sleep(0.005)
            assert scheduler.snapshot()["proof_backoff"]["reason"] == reason
            assert not entered.is_set()
            current[0] = healthy
            assert entered.wait(1)
        finally:
            current[0] = healthy
            worker.join(3)
        assert not worker.is_alive()
        assert not errors
        assert scheduler.snapshot()["active_lease_count"] == 1
        assert scheduler.snapshot()["waiting_request_count"] == 0
    assert_idle(scheduler)


@pytest.mark.parametrize("cancel", [False, True])
def test_blocked_root_timeout_or_external_cancellation_cleans_waiter(owner, cancel):
    scheduler, healthy, current = owner
    current[0] = replace(healthy, memory_stall_percent=8)
    event = threading.Event()
    if cancel:
        event.set()
    error = schedulers.LeaseCancelledError if cancel else schedulers.LeaseTimeoutError
    with pytest.raises(error):
        with resources.acquire_codebase_resources(scheduler=scheduler, cancel_event=event,
                                                  timeout_seconds=0.01):
            pytest.fail("preparation started during pressure")
    assert_idle(scheduler)


def test_running_parent_cancellation_is_visible_to_preparation(owner):
    scheduler, _, _ = owner
    with scheduler.acquire("orchestration", memory_mb=1024,
                           child_process_slots=1, timeout=0) as parent:
        with resources.acquire_codebase_resources(parent_lease=parent, timeout_seconds=0) as child:
            signal = child.combined_cancellation_signal(threading.Event())
            assert not signal.is_set()
            parent.cancel()
            assert signal.is_set()
    assert_idle(scheduler)


def test_external_cancellation_removes_an_existing_waiter(owner):
    scheduler, healthy, current = owner
    current[0] = replace(healthy, cpu_stall_percent=80)
    cancel = threading.Event()
    errors = []
    entered = threading.Event()
    def run():
        try:
            with resources.acquire_codebase_resources(scheduler=scheduler,
                                                      cancel_event=cancel,
                                                      timeout_seconds=2):
                entered.set()
        except BaseException as error:
            errors.append(error)
    worker = threading.Thread(target=run)
    worker.start()
    try:
        deadline = time.monotonic() + 1
        while scheduler.snapshot()["waiting_request_count"] == 0 and time.monotonic() < deadline:
            time.sleep(0.005)
        assert scheduler.snapshot()["waiting_request_count"] == 1
        cancel.set()
    finally:
        cancel.set()
        worker.join(3)
    assert not worker.is_alive()
    assert not entered.is_set()
    assert len(errors) == 1 and isinstance(errors[0], schedulers.LeaseCancelledError)
    assert_idle(scheduler)


def test_child_capacity_rejection_does_not_release_parent(owner):
    scheduler, _, _ = owner
    with scheduler.acquire("orchestration", memory_mb=256,
                           child_process_slots=1, timeout=0) as parent:
        with pytest.raises(schedulers.ResourceUnavailableError, match="parent lease capacity"):
            with resources.acquire_codebase_resources(parent_lease=parent, timeout_seconds=0):
                pytest.fail("oversized child entered")
        assert scheduler.snapshot()["active_lease_count"] == 1
        assert scheduler.snapshot()["waiting_request_count"] == 0
    assert_idle(scheduler)


@pytest.mark.parametrize("arguments,error", [
    ({"scheduler": object()}, TypeError),
    ({"parent_lease": object()}, TypeError),
    ({"cancel_event": object()}, TypeError),
    ({"memory_mb": 0}, schedulers.ResourceConfigurationError),
    ({"memory_mb": True}, schedulers.ResourceConfigurationError),
    ({"cpu_slots": 0}, schedulers.ResourceConfigurationError),
    ({"cpu_slots": 1.5}, schedulers.ResourceConfigurationError),
    ({"timeout_seconds": -1}, schedulers.ResourceConfigurationError),
    ({"timeout_seconds": float("inf")}, schedulers.ResourceConfigurationError),
    ({"timeout_seconds": float("nan")}, schedulers.ResourceConfigurationError),
    ({"timeout_seconds": True}, schedulers.ResourceConfigurationError),
    ({"timeout_seconds": "1"}, schedulers.ResourceConfigurationError),
])
def test_invalid_controls_reject_before_scheduler_access(arguments, error, monkeypatch):
    def unexpected_global():
        raise AssertionError("invalid controls must not access shared scheduler")
    monkeypatch.setattr(resources, "get_global_resource_scheduler", unexpected_global)
    with pytest.raises(error):
        with resources.acquire_codebase_resources(**arguments):
            pytest.fail("invalid controls entered")


def test_parent_and_scheduler_are_ambiguous(owner):
    scheduler, _, _ = owner
    with scheduler.acquire("orchestration", memory_mb=1024,
                           child_process_slots=1, timeout=0) as parent:
        with pytest.raises(schedulers.ResourceConfigurationError, match="not both"):
            with resources.acquire_codebase_resources(scheduler=scheduler, parent_lease=parent):
                pytest.fail("ambiguous authority entered")
    assert_idle(scheduler)
