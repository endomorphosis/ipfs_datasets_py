"""Read-side IO reductions preserve durable scheduler authority transitions."""
from contextlib import contextmanager
import json
import multiprocessing
import os
from pathlib import Path
import time
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as resources


def configuration(path):
    return resources.ResourceSchedulerConfig(state_path=path, total_cpu_slots=2,
        total_memory_mb=200, total_child_process_slots=2, lane_reservations={},
        auto_renew_leases=False, lease_ttl_seconds=30, poll_interval_seconds=.005)


@contextmanager
def tree(path):
    scheduler = resources.GlobalResourceScheduler(configuration(path))
    parent = scheduler.acquire("orchestration", cpu_slots=2, memory_mb=200, timeout=0)
    child = parent.acquire_child(cpu_slots=2, memory_mb=200, timeout=0)
    leaf = child.acquire_child(cpu_slots=1, memory_mb=100, timeout=0)
    try:
        yield scheduler, parent, child, leaf
    finally:
        leaf.release()
        child.release()
        parent.release()


def document(path):
    return json.loads(path.read_bytes())


def test_healthy_reads_do_not_replace_state_or_fsync(tmp_path, monkeypatch):
    with tree(tmp_path / "state.json") as (scheduler, _, _, leaf):
        scheduler.snapshot()  # Ensure the lane telemetry is already materialized.
        original = scheduler.state_path.read_bytes()
        before = scheduler.state_path.stat()
        with monkeypatch.context() as patch:
            patch.setattr(resources.os, "fsync", lambda *args: pytest.fail("unchanged read called fsync"))
            patch.setattr(resources.os, "replace", lambda *args: pytest.fail("unchanged read replaced state"))
            for _ in range(4):
                assert scheduler.snapshot()["active_lease_count"] == 3
                assert len(scheduler.active_leases()) == 3
                assert scheduler.recover_stale_leases() == []
                assert not leaf.cancelled
        after = scheduler.state_path.stat()
        assert scheduler.state_path.read_bytes() == original
        assert (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)
        assert not list(tmp_path.glob(".state.json.*.tmp"))


def test_liveness_observation_reused_per_owner_only_within_one_operation(tmp_path, monkeypatch):
    with tree(tmp_path / "state.json") as (scheduler, _, _, leaf):
        native = resources._owner_is_alive
        observed = []
        def probe(pid, marker):
            observed.append((pid, marker))
            return native(pid, marker)
        monkeypatch.setattr(resources, "_owner_is_alive", probe)
        for call in (scheduler.snapshot, scheduler.active_leases, lambda: leaf.cancelled):
            before = len(observed)
            call()
            assert len(observed) == before + 1
        assert len(set(observed)) == 1


def test_birth_marker_remains_part_of_owner_identity(tmp_path, monkeypatch):
    with tree(tmp_path / "state.json") as (scheduler, parent, child, leaf):
        with scheduler._locked_state() as state:
            state["leases"][leaf.lease_id]["owner_birth_marker"] = "different-process-incarnation"
        native = resources._owner_is_alive
        observed = []
        def probe(pid, marker):
            observed.append((pid, marker))
            return native(pid, marker)
        monkeypatch.setattr(resources, "_owner_is_alive", probe)
        state = scheduler.snapshot()
        assert len(observed) == 2
        assert len({pid for pid, _ in observed}) == 1
        assert len({marker for _, marker in observed}) == 2
        assert state["active_lease_count"] == 2
        assert set(document(scheduler.state_path)["leases"]) == {parent.lease_id, child.lease_id}


def test_read_triggered_expiry_revocation_is_persisted_and_live_capacity_retained(tmp_path, monkeypatch):
    clock = [time.time()]
    monkeypatch.setattr(resources, "time", SimpleNamespace(
        time=lambda: clock[0], monotonic=time.monotonic, sleep=time.sleep))
    with tree(tmp_path / "state.json") as (scheduler, parent, child, leaf):
        before = scheduler.state_path.read_bytes()
        clock[0] += 31
        state = scheduler.snapshot()
        assert state["active_lease_count"] == 3
        assert state["allocated"] == {"cpu_slots": 2, "memory_mb": 200}
        assert scheduler.state_path.read_bytes() != before
        saved = document(scheduler.state_path)
        assert all(row["cancelled"] for row in saved["leases"].values())
        reopened = resources.GlobalResourceScheduler(configuration(scheduler.state_path))
        assert all(reopened.is_cancelled(item.lease_id) for item in (parent, child, leaf))
        assert reopened.try_acquire("orchestration", memory_mb=1) is None
        after = scheduler.state_path.read_bytes()
        with monkeypatch.context() as patch:
            patch.setattr(resources.os, "fsync", lambda *args: pytest.fail("repeat revocation wrote unchanged state"))
            assert len(reopened.active_leases()) == 3
        assert scheduler.state_path.read_bytes() == after


def test_active_legacy_configuration_normalization_is_still_durable(tmp_path):
    with tree(tmp_path / "state.json") as (scheduler, _, _, _):
        prior = document(scheduler.state_path)
        prior["config"].pop("max_waiting_requests")
        scheduler.state_path.write_text(json.dumps(prior, sort_keys=True, separators=(",", ":")))
        resources.GlobalResourceScheduler(configuration(scheduler.state_path))
        saved = document(scheduler.state_path)
        assert "max_waiting_requests" in saved["config"]
        assert saved["config"]["max_waiting_requests"] is None
        assert saved["leases"] == prior["leases"]


def test_each_real_mutation_keeps_atomic_replace_and_fsync(tmp_path, monkeypatch):
    scheduler = resources.GlobalResourceScheduler(configuration(tmp_path / "state.json"))
    native_sync, native_replace = resources.os.fsync, resources.os.replace
    syncs, replacements = [], []
    def sync(descriptor):
        syncs.append(descriptor)
        return native_sync(descriptor)
    def replace(source, target):
        replacements.append((source, target))
        return native_replace(source, target)
    monkeypatch.setattr(resources.os, "fsync", sync)
    monkeypatch.setattr(resources.os, "replace", replace)
    lease = scheduler.acquire("orchestration", cpu_slots=1, memory_mb=100, timeout=0)
    assert len(syncs) == 2 and len(replacements) == 1
    assert lease.lease_id in document(scheduler.state_path)["leases"]
    assert lease.cancel()
    assert len(syncs) == 4 and len(replacements) == 2
    assert document(scheduler.state_path)["leases"][lease.lease_id]["cancelled"]
    assert not lease.cancel()
    assert len(syncs) == 4 and len(replacements) == 2
    assert lease.release()
    assert len(syncs) == 6 and len(replacements) == 3
    assert not document(scheduler.state_path)["leases"]


@pytest.mark.parametrize("failing_operation", ["fsync", "replace"])
def test_mutation_io_failure_preserves_original_state_and_cleans_temporary_file(tmp_path, monkeypatch, failing_operation):
    with tree(tmp_path / "state.json") as (scheduler, parent, _, _):
        before = scheduler.state_path.read_bytes()
        def fail(*arguments):
            raise OSError("injected durable-write failure")
        with monkeypatch.context() as patch:
            patch.setattr(resources.os, failing_operation, fail)
            with pytest.raises(OSError, match="durable-write failure"):
                parent.cancel()
        assert scheduler.state_path.read_bytes() == before
        assert not list(tmp_path.glob(".state.json.*.tmp"))
        assert not parent.cancelled
        assert parent.cancel()
        assert document(scheduler.state_path)["leases"][parent.lease_id]["cancelled"]


def test_corrupt_fresh_state_is_not_hidden_by_previous_successful_read(tmp_path):
    with tree(tmp_path / "state.json") as (scheduler, _, _, leaf):
        scheduler.snapshot()
        valid = scheduler.state_path.read_bytes()
        try:
            broken = b'{"schema_version":'
            scheduler.state_path.write_bytes(broken)
            for action in (scheduler.snapshot, scheduler.active_leases, lambda: leaf.cancelled):
                with pytest.raises(resources.SchedulerStateError, match="corrupt"):
                    action()
                assert scheduler.state_path.read_bytes() == broken
            assert not list(tmp_path.glob(".state.json.*.tmp"))
        finally:
            scheduler.state_path.write_bytes(valid)


def _owner_until_death(path, ready, stop):
    scheduler = resources.GlobalResourceScheduler(configuration(path))
    root = scheduler.acquire("orchestration", cpu_slots=2, memory_mb=200, timeout=0)
    root.acquire_child(cpu_slots=2, memory_mb=200, timeout=0)
    ready.set()
    stop.wait(10)
    os._exit(0)


@pytest.mark.skipif(os.name != "posix", reason="native shared owner requires POSIX locks")
def test_next_read_detects_native_owner_death_and_durably_reclaims_capacity(tmp_path):
    context = multiprocessing.get_context("spawn")
    path = tmp_path / "state.json"
    ready, stop = context.Event(), context.Event()
    process = context.Process(target=_owner_until_death, args=(path, ready, stop))
    process.start()
    try:
        assert ready.wait(10)
        scheduler = resources.GlobalResourceScheduler(configuration(path))
        assert scheduler.snapshot()["active_lease_count"] == 2
        assert len(document(path)["leases"]) == 2
        stop.set()
        process.join(10)
        assert process.exitcode == 0
        assert scheduler.active_leases() == []
        assert document(path)["leases"] == {}
        reopened = resources.GlobalResourceScheduler(configuration(path))
        assert reopened.snapshot()["active_lease_count"] == 0
        with reopened.acquire("orchestration", cpu_slots=2, memory_mb=200, timeout=0):
            pass
    finally:
        stop.set()
        process.join(10)
        if process.is_alive():
            process.terminate()
            process.join(5)
