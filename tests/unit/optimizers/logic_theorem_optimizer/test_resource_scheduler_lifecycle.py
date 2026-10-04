"""Native shared-state accounting while revoked nested execution drains."""
from dataclasses import replace
import multiprocessing
import os
import threading
import time
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as resources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources


def config(path, **overrides):
    values = dict(state_path=path, total_cpu_slots=2, total_memory_mb=200,
                  total_gpu_memory_mb=80, total_unified_memory_mb=300,
                  total_child_process_slots=2, lane_reservations={},
                  auto_renew_leases=False, lease_ttl_seconds=30,
                  poll_interval_seconds=.005)
    values.update(overrides)
    return resources.ResourceSchedulerConfig(**values)


def acquire(owner, **overrides):
    values = dict(cpu_slots=2, memory_mb=200, child_process_slots=2, timeout=0)
    values.update(overrides)
    return owner.acquire("orchestration", **values)


def test_parent_release_retains_capacity_and_revokes_until_leaf_acknowledgement(tmp_path):
    owner = resources.GlobalResourceScheduler(config(tmp_path / "leases.json"))
    parent = acquire(owner)
    child = parent.acquire_child(cpu_slots=2, memory_mb=200, child_process_slots=2, timeout=0)
    try:
        assert parent.release()
        assert parent.released and child.cancelled
        assert not parent.release()
        state = owner.snapshot()
        assert state["allocated"] == {"cpu_slots": 2, "memory_mb": 200}
        assert state["active_lease_count"] == 2
        assert owner.try_acquire("orchestration", memory_mb=1) is None
        assert child.renew()  # A retained execution hold may keep heartbeating.
        with pytest.raises(resources.LeaseCancelledError):
            child.acquire_child(memory_mb=1, timeout=0)
    finally:
        child.release()
        parent.release()
    assert owner.snapshot()["active_lease_count"] == 0
    with acquire(owner):
        pass


def test_nested_release_does_not_open_sibling_capacity_before_grandchild_finishes(tmp_path):
    owner = resources.GlobalResourceScheduler(config(tmp_path / "leases.json"))
    with acquire(owner) as parent:
        middle = parent.acquire_child(cpu_slots=2, memory_mb=200, child_process_slots=2, timeout=0)
        leaf = middle.acquire_child(cpu_slots=1, memory_mb=150, child_process_slots=1, timeout=0)
        try:
            middle.release()
            assert leaf.cancelled
            assert owner.try_acquire("hammer", parent=parent, memory_mb=1) is None
            assert owner.snapshot()["active_lease_count"] == 3
        finally:
            leaf.release()
            middle.release()
        with parent.acquire_child(cpu_slots=2, memory_mb=200, child_process_slots=2, timeout=0):
            pass
    assert owner.snapshot()["active_lease_count"] == 0


def test_expired_live_owner_cannot_be_reclaimed_or_resurrected_by_heartbeat(tmp_path, monkeypatch):
    clock = [time.time()]
    monkeypatch.setattr(resources, "time", SimpleNamespace(
        time=lambda: clock[0], monotonic=time.monotonic, sleep=time.sleep))
    owner = resources.GlobalResourceScheduler(config(tmp_path / "leases.json", lease_ttl_seconds=10))
    parent = acquire(owner)
    try:
        clock[0] += 11
        assert owner.recover_stale_leases() == []
        assert parent.cancelled
        assert owner.try_acquire("orchestration", memory_mb=1) is None
        assert parent.renew()
        assert parent.cancelled  # Renewal retains the hold; it cannot undo revocation.
        with pytest.raises(resources.LeaseCancelledError):
            parent.acquire_child(memory_mb=1, timeout=0)
    finally:
        parent.release()
    assert owner.snapshot()["active_lease_count"] == 0


def test_cancellation_poll_observes_expired_ancestor_without_mutating_recovery(tmp_path, monkeypatch):
    clock = [time.time()]
    monkeypatch.setattr(resources, "time", SimpleNamespace(
        time=lambda: clock[0], monotonic=time.monotonic, sleep=time.sleep))
    owner = resources.GlobalResourceScheduler(config(tmp_path / "leases.json", lease_ttl_seconds=10))
    parent = acquire(owner)
    clock[0] += 5
    child = parent.acquire_child(memory_mb=100, timeout=0)
    before = owner.state_path.read_bytes()
    try:
        clock[0] += 6  # Child remains within its own TTL; parent has expired.
        assert child.cancellation_signal.is_set()
        assert owner.state_path.read_bytes() == before
    finally:
        child.release()
        parent.release()


def _hold_native_child(path, token, ready, stop, observed):
    owner = resources.GlobalResourceScheduler(config(path, auto_renew_leases=True))
    with acquire(owner, parent=token) as child:
        ready.set()
        observed.value = int(child.cancellation_signal.wait(5))
        stop.wait(5)  # Retained work is still running after it sees revocation.


@pytest.mark.skipif(os.name != "posix", reason="native shared owner needs POSIX locks")
def test_another_process_cannot_reuse_released_parent_while_native_child_drains(tmp_path):
    context = multiprocessing.get_context("spawn")
    path = tmp_path / "leases.json"
    owner = resources.GlobalResourceScheduler(config(path))
    parent = acquire(owner)
    ready, stop, observed = context.Event(), context.Event(), context.Value("i", 0)
    worker = context.Process(target=_hold_native_child, args=(path, parent.token, ready, stop, observed))
    worker.start()
    try:
        assert ready.wait(10)
        parent.release()
        deadline = time.monotonic() + 5
        while not observed.value and time.monotonic() < deadline:
            time.sleep(.005)
        assert observed.value == 1 and worker.is_alive()
        other = resources.GlobalResourceScheduler(config(path))
        assert other.try_acquire("orchestration", memory_mb=1) is None
        assert other.snapshot()["active_lease_count"] == 2
    finally:
        stop.set()
        worker.join(10)
        if worker.is_alive():
            worker.terminate()
            worker.join(5)
        parent.release()
    assert worker.exitcode == 0
    assert owner.snapshot()["active_lease_count"] == 0


def _root_until_os_exit(path, pipe, stop):
    owner = resources.GlobalResourceScheduler(config(path))
    parent = acquire(owner)
    pipe.send(parent.token)
    pipe.close()
    stop.wait(10)
    os._exit(0)


@pytest.mark.skipif(os.name != "posix", reason="native shared owner needs POSIX locks")
def test_dead_parent_does_not_reclaim_independently_live_child_owner(tmp_path):
    context = multiprocessing.get_context("spawn")
    path = tmp_path / "leases.json"
    receive, send = context.Pipe(duplex=False)
    stop = context.Event()
    process = context.Process(target=_root_until_os_exit, args=(path, send, stop))
    process.start()
    child = None
    try:
        assert receive.poll(10)
        token = receive.recv()
        owner = resources.GlobalResourceScheduler(config(path))
        child = acquire(owner, parent=token)
        stop.set()
        process.join(10)
        assert process.exitcode == 0
        assert owner.recover_stale_leases() == []
        assert child.cancelled
        assert owner.snapshot()["allocated"]["memory_mb"] == 200
        assert owner.try_acquire("orchestration", memory_mb=1) is None
        child.release()
        assert owner.snapshot()["active_lease_count"] == 0
    finally:
        stop.set()
        if child is not None:
            child.release()
        process.join(10)
        if process.is_alive():
            process.terminate()
            process.join(5)
        receive.close()
        send.close()


def test_external_pressure_stops_new_children_and_cancelled_waiter_drains(tmp_path):
    healthy = ProofHostResources(4, 1000, 900)
    observed = [healthy]
    owner = resources.GlobalResourceScheduler(config(tmp_path / "leases.json",
        proof_safety_enabled=True, proof_memory_headroom_mb=100,
        proof_backoff_seconds=.02, proof_resource_sampler=lambda: observed[0]))
    with acquire(owner) as parent:
        observed[0] = replace(healthy, available_memory_mb=200)
        result = []
        def wait():
            try:
                parent.acquire_child(memory_mb=100, timeout=2)
            except Exception as error:
                result.append(error)
        thread = threading.Thread(target=wait)
        thread.start()
        deadline = time.monotonic() + 2
        while owner.snapshot()["waiting_request_count"] == 0 and time.monotonic() < deadline:
            time.sleep(.005)
        assert owner.snapshot()["waiting_request_count"] == 1
        parent.cancel()
        thread.join(3)
        assert not thread.is_alive()
        assert len(result) == 1 and isinstance(result[0], resources.LeaseCancelledError)
        assert owner.snapshot()["waiting_request_count"] == 0
    observed[0] = healthy
    with acquire(owner, timeout=1):
        pass
    assert owner.snapshot()["active_lease_count"] == 0


def test_repeated_reverse_order_release_leaves_no_durable_tombstones(tmp_path):
    owner = resources.GlobalResourceScheduler(config(tmp_path / "leases.json"))
    for _ in range(16):
        parent = acquire(owner)
        middle = parent.acquire_child(cpu_slots=2, memory_mb=200, timeout=0)
        leaf = middle.acquire_child(memory_mb=100, timeout=0)
        parent.release()
        middle.release()
        assert owner.snapshot()["active_lease_count"] == 3
        leaf.release()
        assert owner.active_leases() == []
    state = owner.snapshot()
    assert state["waiting_request_count"] == 0
    assert state["allocated"] == {"cpu_slots": 0, "memory_mb": 0}
