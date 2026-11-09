"""Temporary native state plus simulated cgroups; never F07 qualification.

Native scheduler persistence, locking, cancellation and deferred release are
real, but only in pytest's private temporary directory. The proof host sampler
is explicitly mocked for deterministic unit admission. The cgroup backend is
the existing explicit simulation; no kernel scope, worker, model, Docker
container, production ledger, global scheduler or F07 grant is created.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import copy, deepcopy
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_kernel_custody as kernel
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_kernel_fence as fences
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import existing_resource_scheduler as existing
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as native
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_kernel_custody import (
    ROOT, WORKER, SimulatedCgroupFS,
)


@pytest.fixture
def private(tmp_path):
    path = tmp_path / "private-native-unit-state.json"
    # Initializing a NEW private unit fixture is deliberate. Production callers
    # must open existing authority and must never initialize or reconfigure it.
    native.GlobalResourceScheduler(native.ResourceSchedulerConfig(
        state_path=path, total_cpu_slots=8, total_memory_mb=4096,
        total_child_process_slots=16, lane_reservations={},
        proof_safety_enabled=True, auto_renew_leases=False,
        lease_ttl_seconds=120))
    policy = deepcopy(json.loads(path.read_bytes())["config"])
    expected = existing.policy_sha256(policy)
    scheduler = existing.open_existing_scheduler(path, expected)
    # Only host observations are mocked. No scheduler operation is replaced.
    scheduler.config.proof_resource_sampler = lambda: native.ProofHostResources(
        8, 8192, 8192, pid_task_limit=500, available_pid_tasks=400)
    scheduler.config.auto_renew_leases = False
    root = scheduler.acquire("validation", cpu_slots=4, memory_mb=256,
        child_process_slots=8, timeout=0)
    child = root.acquire_child(cpu_slots=2, memory_mb=128,
        child_process_slots=4, timeout=0)
    fs = SimulatedCgroupFS()
    fs.boot = native._owner_boot_id()
    guardian = os.getpid()
    fs.processes[guardian] = dict(pid=guardian,
        birth=int(native._owner_birth_marker(guardian)), state="S",
        membership="/unit/guardian")
    scope = kernel.bind_cgroup(WORKER, expected_root=ROOT,
        expected_owner_uid=1000, required_memory_max=1024,
        required_pids_max=8, required_cpu_quota_us=100000,
        required_cpu_period_us=100000, allow_drain=True, _backend=fs)
    value = SimpleNamespace(path=path, policy=policy, expected=expected,
        scheduler=scheduler, root=root, child=child, fs=fs, scope=scope,
        consumers=[])
    try:
        yield value
    finally:
        # Failure-retention assertions run BEFORE explicit private-fixture
        # teardown. Teardown neither represents nor performs productive work.
        scope.close()
        for consumer in reversed(value.consumers):
            if not consumer.released:
                consumer.release()
        if not child.released:
            child.release()
        if not root.released:
            root.release()
        assert scheduler.active_leases() == []
        assert json.loads(path.read_bytes())["config"] == policy
        assert fs.handles == {}


def make_fence(private, lease=None, scope=None, **changes):
    values = dict(scheduler_state_path=private.path,
        expected_scheduler_policy_sha256=private.expected)
    values.update(changes)
    return fences.KernelDrainFence(private.child if lease is None else lease,
        private.scope if scope is None else scope, **values)


def rows(private):
    with private.scheduler._locked_state(persist=False) as state:
        return deepcopy(state["leases"])


def assert_charged(private, *, root_released=False):
    current = rows(private)
    assert private.root.lease_id in current
    assert private.child.lease_id in current
    assert not current[private.child.lease_id].get("release_requested")
    assert private.child.released is False
    if root_released:
        assert current[private.root.lease_id]["release_requested"] is True
    with private.scheduler._locked_state(persist=False) as state:
        usage = private.scheduler._root_usage(state)
    assert usage[:2] == (private.root.cpu_slots, private.root.memory_mb)


@contextmanager
def changed_row(private, lease, **changes):
    # Deliberate corrupt-state testing exclusively under the private native lock.
    with private.scheduler._locked_state() as state:
        original = deepcopy(state["leases"][lease.lease_id])
        state["leases"][lease.lease_id].update(changes)
    try:
        yield
    finally:
        with private.scheduler._locked_state() as state:
            state["leases"][lease.lease_id] = original


def consumer(private):
    lease = private.child.acquire_child(cpu_slots=1, memory_mb=32,
        child_process_slots=1, timeout=0)
    private.consumers.append(lease)
    return lease


def test_real_temporary_native_grant_and_simulated_kernel_are_explicit(private):
    fence = make_fence(private)
    report = fence.guard_work()
    assert report["worker"]["simulation"] is True
    assert report["native_admission"] is report["admitted"] is report["Lean_admitted"] is False
    assert report["guardian_death_qualified"] is False
    assert type(private.scheduler) is existing._PinnedGlobalResourceScheduler
    assert report["child_lease_id"] == private.child.lease_id
    assert report["guardian_distinct_from_root_owner"] is False
    assert report["root_owner_pid"] == report["guardian_pid"] == os.getpid()
    assert_charged(private)


def test_released_parent_revokes_work_but_child_holds_full_root_until_drain(private):
    fence = make_fence(private)
    assert private.root.release()
    assert private.child.cancelled
    with pytest.raises(kernel.KernelCustodyError, match="revoked"):
        fence.guard_work()
    assert_charged(private, root_released=True)
    assert private.fs.nodes[str(WORKER / "cgroup.events")]["text"].startswith("populated 1")
    before_release = []
    def reaped():
        assert private.fs.nodes[str(WORKER / "cgroup.events")]["text"].startswith("populated 0")
        assert_charged(private, root_released=True)
        before_release.append(True)
    result = fence.drain_and_release(before_release=reaped)
    assert before_release == [True]
    assert private.fs.writes
    assert fence.released and private.child.released
    assert rows(private) == {}
    assert result["root_capacity_still_charged_before_drain"] is True
    assert result["root_lease_remains"] is False
    assert result["worker_drain"]["simulation"] is True
    assert result["disk_claim_reconciled"] is result["admitted"] is False


def test_cancelled_parent_is_retained_after_drained_child_release(private):
    fence = make_fence(private)
    assert private.root.cancel()
    with pytest.raises(kernel.KernelCustodyError, match="revoked"):
        fence.guard_work()
    result = fence.drain_and_release()
    assert result["root_lease_remains"] is True
    assert set(rows(private)) == {private.root.lease_id}
    assert rows(private)[private.root.lease_id]["cancelled"] is True


def test_timeout_keeps_actual_child_and_revoked_root_charged(private):
    fence = make_fence(private)
    private.root.release()
    private.fs.kill_works = False
    with pytest.raises(kernel.KernelCustodyError, match="deadline"):
        fence.drain_and_release(timeout_seconds=0.1)
    assert not fence.released
    assert_charged(private, root_released=True)


def test_failed_reaping_callback_cannot_release_even_after_successful_drain(private):
    fence = make_fence(private)
    private.root.release()
    def failed_reap():
        assert_charged(private, root_released=True)
        raise RuntimeError("tracked child birth not reaped")
    with pytest.raises(RuntimeError, match="not reaped"):
        fence.drain_and_release(before_release=failed_reap)
    assert private.fs.nodes[str(WORKER / "cgroup.events")]["text"].startswith("populated 0")
    assert not fence.released
    assert_charged(private, root_released=True)


@pytest.mark.parametrize("identity_fault", ["boot", "directory", "kill_control", "events"])
def test_unknown_original_scope_identity_never_releases(private, identity_fault):
    fence = make_fence(private)
    private.root.release()
    if identity_fault == "boot":
        private.fs.boot += "x"
    elif identity_fault == "directory":
        private.fs.add(WORKER, directory=True)
    elif identity_fault == "kill_control":
        private.fs.add(WORKER / "cgroup.kill")
    else:
        private.fs.text("cgroup.events", "unknown 1")
    with pytest.raises(kernel.KernelCustodyError):
        fence.drain_and_release()
    assert not fence.released
    assert_charged(private, root_released=True)


def test_fresh_identity_check_after_callback_is_mandatory(private):
    fence = make_fence(private)
    def replace_events():
        private.fs.add(WORKER / "cgroup.events", text="populated 0\nfrozen 0")
    with pytest.raises(kernel.KernelCustodyError, match="identity"):
        fence.drain_and_release(before_release=replace_events)
    assert not fence.released
    assert_charged(private)


@pytest.mark.parametrize("value", [None, {}, {"lease_id": "public-row"}, object()])
def test_public_rows_or_objects_are_not_native_child_capabilities(private, value):
    with pytest.raises(kernel.KernelCustodyError, match="native child capability"):
        fences.KernelDrainFence(value, private.scope,
            scheduler_state_path=private.path,
            expected_scheduler_policy_sha256=private.expected)
    assert_charged(private)


def test_native_root_lease_cannot_be_a_drain_fence(private):
    with pytest.raises(kernel.KernelCustodyError, match="child owned"):
        make_fence(private, lease=private.root)
    assert_charged(private)


def test_actual_public_native_lease_report_cannot_reconstruct_capability(private):
    with pytest.raises(kernel.KernelCustodyError, match="native child capability"):
        make_fence(private, lease=private.child.to_dict())
    assert_charged(private)


def test_scope_report_cannot_reconstruct_a_held_kill_binding(private):
    with pytest.raises(kernel.KernelCustodyError, match="held worker"):
        make_fence(private, scope=private.scope.observe())
    assert_charged(private)


def test_closed_binding_is_not_cached_custody(private):
    private.scope.close()
    with pytest.raises(kernel.KernelCustodyError, match="closed"):
        make_fence(private)
    assert_charged(private)


def test_binding_without_drain_permission_is_rejected(private):
    with kernel.bind_cgroup(WORKER, expected_root=ROOT, expected_owner_uid=1000,
            required_memory_max=1024, required_pids_max=8,
            required_cpu_quota_us=100000, required_cpu_period_us=100000,
            _backend=private.fs) as scope:
        with pytest.raises(kernel.KernelCustodyError, match="drain authorization"):
            make_fence(private, scope=scope)
    assert_charged(private)


@pytest.mark.parametrize("change", ["policy", "state", "relative_state"])
def test_exact_native_state_and_policy_are_required(private, change):
    values = {}
    if change == "policy":
        values["expected_scheduler_policy_sha256"] = "0" * 64
    elif change == "state":
        values["scheduler_state_path"] = private.path.with_name("other-native.json")
    else:
        values["scheduler_state_path"] = Path(private.path.name)
    with pytest.raises(kernel.KernelCustodyError, match="scheduler identity"):
        make_fence(private, **values)
    assert_charged(private)


def test_unpinned_native_facade_is_rejected(private):
    unpinned = native.GlobalResourceScheduler(native.ResourceSchedulerConfig(
        state_path=private.path, total_cpu_slots=8, total_memory_mb=4096,
        total_child_process_slots=16, lane_reservations={},
        proof_safety_enabled=True, auto_renew_leases=False))
    alias = copy(private.child)
    alias._scheduler = unpinned
    with pytest.raises(kernel.KernelCustodyError, match="existing pinned"):
        make_fence(private, lease=alias)
    assert_charged(private)


def test_child_capability_owned_by_another_pid_is_rejected(private):
    alias = copy(private.child)
    alias.owner_pid += 1
    with pytest.raises(kernel.KernelCustodyError, match="this surviving guardian"):
        make_fence(private, lease=alias)
    assert_charged(private)


@pytest.mark.parametrize("field,value", [
    ("owner_pid", 123456789), ("owner_birth_marker", "wrong-birth"),
    ("owner_boot_id", "wrong-boot"), ("lease_key", "wrong-private-key"),
])
def test_actual_native_owner_identity_is_rechecked_before_release(private, field, value):
    fence = make_fence(private)
    with changed_row(private, private.child, **{field: value}):
        with pytest.raises((kernel.KernelCustodyError, native.ResourceSchedulerError)):
            fence.drain_and_release()
        assert not fence.released and not private.child.released
        # Deliberate corruption of privileged owner metadata is not a claim of
        # retained native capacity: native stale-owner validation can prune a
        # local observation. The fence must make no explicit release call.
        assert private.child.lease_id in json.loads(private.path.read_bytes())["leases"]
    assert_charged(private)


def test_native_ancestor_envelope_change_is_not_accepted_as_new_authority(private):
    fence = make_fence(private)
    with changed_row(private, private.root, memory_mb=257):
        with pytest.raises(kernel.KernelCustodyError, match="envelope changed"):
            fence.drain_and_release()
        assert not private.child.released
    assert_charged(private)


@pytest.mark.parametrize("parent_id", ["missing-native-ancestor", "self"])
def test_broken_or_cyclic_native_ancestry_never_releases(private, parent_id):
    fence = make_fence(private)
    if parent_id == "self":
        parent_id = private.child.lease_id
    with changed_row(private, private.child, parent_lease_id=parent_id):
        with pytest.raises(kernel.KernelCustodyError, match="ancestry|ancestor|consumers"):
            fence.drain_and_release()
        assert not fence.released and not private.child.released
    assert_charged(private)


def test_forked_or_changed_guardian_pid_cannot_release(private, monkeypatch):
    fence = make_fence(private)
    actual_pid = os.getpid()
    with monkeypatch.context() as patch:
        patch.setattr(fences.os, "getpid", lambda: actual_pid + 1)
        with pytest.raises(kernel.KernelCustodyError, match="guardian changed"):
            fence.drain_and_release()
    assert private.fs.writes == []
    assert_charged(private)


def test_existing_independent_consumers_reject_fence_construction(private):
    consumer(private)
    with pytest.raises(kernel.KernelCustodyError, match="consumers"):
        make_fence(private)
    assert_charged(private)


def test_callback_created_native_consumer_refuses_release_before_changing_lease(private):
    fence = make_fence(private)
    with pytest.raises(kernel.KernelCustodyError, match="consumers"):
        fence.drain_and_release(before_release=lambda: consumer(private))
    assert not fence.released
    assert_charged(private)
    assert rows(private)[private.consumers[0].lease_id]["cancelled"] is False


def test_racing_consumer_defers_native_capacity_and_refuses_success(private, monkeypatch):
    fence = make_fence(private)
    original_release = private.child.release
    def race_before_native_release():
        # The real native operation happens after the fence's final independent
        # no-consumer observation. No release implementation is mocked.
        consumer(private)
        return original_release()
    monkeypatch.setattr(private.child, "release", race_before_native_release)
    with pytest.raises(kernel.KernelCustodyError, match="consumers after release"):
        fence.drain_and_release()
    current = rows(private)
    assert fence.released and private.child.released
    assert set(current) == {private.root.lease_id, private.child.lease_id,
        private.consumers[0].lease_id}
    assert current[private.child.lease_id]["release_requested"] is True
    assert current[private.child.lease_id]["cancelled"] is True
    assert current[private.consumers[0].lease_id]["cancelled"] is True
    with private.scheduler._locked_state(persist=False) as state:
        assert private.scheduler._root_usage(state)[:2] == (
            private.root.cpu_slots, private.root.memory_mb)
    # A post-release failure is not a reusable fence; only the actual racing
    # consumer can acknowledge its own completion. The native root stays
    # charged until that occurs and the root itself requests release.
    private.consumers[0].release()
    assert set(rows(private)) == {private.root.lease_id}


@pytest.mark.parametrize("membership", ["/unit/worker", "/unit/worker/new-nested"])
def test_guardian_migration_into_worker_refuses_first_kill(private, membership):
    fence = make_fence(private)
    private.fs.processes[os.getpid()]["membership"] = membership
    with pytest.raises(kernel.KernelCustodyError, match="guardian entered"):
        fence.drain_and_release()
    assert private.fs.writes == []
    assert_charged(private)


@pytest.mark.parametrize("membership", ["/unit/worker", "/unit/worker/new-nested"])
def test_guardian_migration_during_callback_refuses_final_kill(private, membership):
    fence = make_fence(private)
    def migrate():
        private.fs.processes[os.getpid()]["membership"] = membership
    with pytest.raises(kernel.KernelCustodyError, match="guardian entered"):
        fence.drain_and_release(before_release=migrate)
    assert len(private.fs.writes) == 1
    assert not fence.released
    assert_charged(private)


def test_unknown_guardian_identity_refuses_kill_and_release(private):
    fence = make_fence(private)
    del private.fs.processes[os.getpid()]
    with pytest.raises(kernel.KernelCustodyError, match="guardian entered"):
        fence.drain_and_release()
    assert private.fs.writes == []
    assert_charged(private)


def test_guardian_already_in_worker_inventory_cannot_construct_fence(private):
    private.fs.text("cgroup.procs", f"100 {os.getpid()}")
    private.fs.text("pids.current", "3")
    private.fs.processes[os.getpid()]["membership"] = "/unit/worker"
    with pytest.raises(kernel.KernelCustodyError, match="guardian must stay outside"):
        make_fence(private)
    assert_charged(private)


def test_new_topology_refuses_productivity_but_original_fd_still_drains(private):
    fence = make_fence(private)
    nested = WORKER / "new-child"
    private.fs.group(nested, processes="101", tasks=1, memory=32)
    private.fs.processes[101] = dict(pid=101, birth=109, state="S",
        membership="/unit/worker/new-child")
    with pytest.raises(kernel.KernelCustodyError, match="population changed"):
        fence.guard_work()
    assert_charged(private)
    private.root.release()
    result = fence.drain_and_release()
    assert result["worker_final_drain"]["populated"] is False
    assert private.fs.nodes[str(nested / "cgroup.events")]["text"].startswith("populated 0")
    assert private.fs.processes[101]["state"] == "Z"
    assert rows(private) == {}


def test_invalid_reap_callback_is_refused_before_any_drain(private):
    fence = make_fence(private)
    with pytest.raises(kernel.KernelCustodyError, match="callable"):
        fence.drain_and_release(before_release={"success": True})
    assert private.fs.writes == []
    assert_charged(private)


def test_no_implicit_context_or_destructor_release_interface(private):
    fence = make_fence(private)
    assert not hasattr(fence, "__enter__")
    assert not hasattr(fence, "__exit__")
    assert not hasattr(type(fence), "__del__")
    assert_charged(private)


def test_success_cannot_be_replayed_as_a_second_release(private):
    fence = make_fence(private)
    result = fence.drain_and_release()
    assert result["child_release_acknowledged"] is True
    with pytest.raises(kernel.KernelCustodyError, match="released"):
        fence.drain_and_release()
    assert set(rows(private)) == {private.root.lease_id}
