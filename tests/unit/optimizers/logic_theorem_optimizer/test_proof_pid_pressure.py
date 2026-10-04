"""Cheap kernel-task telemetry and default-on pressure without capacity migration."""
from dataclasses import replace
from pathlib import Path
import threading
import time

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import (
    ProofHostResources, collect_proof_host_resources,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler, ResourceSchedulerConfig, LeaseCancelledError,
    PROOF_PID_HEADROOM_TASKS, PROOF_PID_TASKS_PER_PROCESS,
)


@pytest.fixture
def counters(tmp_path, monkeypatch):
    proc, group = tmp_path / 'proc', tmp_path / 'cgroup'
    (proc / 'self').mkdir(parents=True)
    (group / 'parent/worker').mkdir(parents=True)
    (proc / 'meminfo').write_text('MemTotal: 8388608 kB\nMemAvailable: 6291456 kB\n')
    (proc / 'self/cgroup').write_text('0::/parent/worker\n')
    monkeypatch.setattr('os.sched_getaffinity', lambda _: set(range(20)))
    return proc, group


def _pid_files(root, limit, current):
    (root / 'pids.max').write_text(str(limit))
    if current is not None:
        (root / 'pids.current').write_text(str(current))


def test_visible_ancestor_limits_and_usage_are_combined_independently(counters):
    proc, group = counters
    _pid_files(group / 'parent', 128, 30)
    _pid_files(group / 'parent/worker', 200, 150)
    host = collect_proof_host_resources(proc, group)
    assert host.pid_task_limit == 128 and host.available_pid_tasks == 50


def test_unlimited_child_does_not_hide_finite_ancestor(counters):
    proc, group = counters
    _pid_files(group / 'parent', 64, 50)
    _pid_files(group / 'parent/worker', 'max', None)
    host = collect_proof_host_resources(proc, group)
    assert host.pid_task_limit == 64 and host.available_pid_tasks == 14


@pytest.mark.parametrize('limit,current', [(0, 4), (64, 72)])
def test_lowered_limit_below_current_usage_reports_zero_headroom(counters, limit, current):
    proc, group = counters
    _pid_files(group / 'parent/worker', limit, current)
    host = collect_proof_host_resources(proc, group)
    assert host.pid_task_limit == limit and host.available_pid_tasks == 0


@pytest.mark.parametrize('limit,current', [(64, None), (64, 'bad'), (64, -1), ('bad', 4), (-1, 4)])
def test_known_bad_counter_never_disappears_into_optional_telemetry(counters, limit, current):
    proc, group = counters
    _pid_files(group / 'parent/worker', limit, current)
    with pytest.raises((ValueError, OSError)):
        collect_proof_host_resources(proc, group)


def test_missing_controllers_preserve_unknown_optional_defaults(counters):
    proc, group = counters
    host = collect_proof_host_resources(proc, group)
    assert host.pid_task_limit is None and host.available_pid_tasks is None
    assert ProofHostResources(2, 1024, 512).available_pid_tasks is None


def test_global_thread_limit_uses_live_task_count_without_uid_scan(counters, monkeypatch):
    proc, group = counters
    (proc / 'sys/kernel').mkdir(parents=True)
    (proc / 'sys/kernel/threads-max').write_text('1000')
    (proc / 'loadavg').write_text('0.00 0.00 0.00 2/980 999\n')
    _pid_files(group / 'parent/worker', 200, 20)
    # Counting /proc PID directories is intentionally absent from the sampler.
    monkeypatch.setattr(Path, 'iterdir', lambda _: pytest.fail('unexpected task census'))
    host = collect_proof_host_resources(proc, group)
    assert host.pid_task_limit == 200 and host.available_pid_tasks == 20


@pytest.mark.parametrize('usage', [None, 'invalid', '0 0 0 9/2 42', '0 0 0 1/-2 42'])
def test_known_host_limit_with_unknown_task_usage_fails_closed(counters, usage):
    proc, group = counters
    (proc / 'sys/kernel').mkdir(parents=True)
    (proc / 'sys/kernel/threads-max').write_text('1000')
    if usage is not None:
        (proc / 'loadavg').write_text(usage)
    with pytest.raises((ValueError, OSError)):
        collect_proof_host_resources(proc, group)


@pytest.mark.parametrize('values', [
    {'pid_task_limit': 100}, {'available_pid_tasks': 10},
    {'pid_task_limit': True, 'available_pid_tasks': 0},
    {'pid_task_limit': 100, 'available_pid_tasks': -1},
    {'pid_task_limit': 100, 'available_pid_tasks': 101},
])
def test_optional_pid_snapshot_requires_a_valid_complete_pair(values):
    with pytest.raises(ValueError):
        ProofHostResources(8, 8192, 8192, **values)


def _scheduler(tmp_path, current, **overrides):
    return GlobalResourceScheduler(ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / 'leases.json', proof_resource_sampler=lambda: current[0],
        lane_reservations={}, proof_backoff_seconds=overrides.pop('proof_backoff_seconds', 0),
        poll_interval_seconds=.005, auto_renew_leases=False, **overrides))


def test_default_process_capacity_and_active_persisted_configuration_are_unchanged(tmp_path, monkeypatch):
    monkeypatch.delenv('IPFS_DATASETS_RESOURCE_CHILD_PROCESS_SLOTS', raising=False)
    healthy = ProofHostResources(20, 8192, 8192, pid_task_limit=10000, available_pid_tasks=9000)
    current = [healthy]
    scheduler = _scheduler(tmp_path, current)
    assert scheduler.config.total_child_process_slots == 16  # Deliberately no policy migration.
    before = scheduler.config.persisted_dict()
    assert not any('pid_' in field for field in before)
    with scheduler.acquire('hammer', cpu_slots=2, memory_mb=100, child_process_slots=2, timeout=0) as root:
        current[0] = replace(healthy, available_pid_tasks=200)
        reopened = _scheduler(tmp_path, current)
        assert reopened.config.persisted_dict() == before
        with reopened.acquire('hammer', cpu_slots=1, memory_mb=50, child_process_slots=1, parent=root, timeout=0):
            pass
    monkeypatch.setenv('IPFS_DATASETS_RESOURCE_CHILD_PROCESS_SLOTS', '7')
    assert ResourceSchedulerConfig.for_proof_host(proof_resource_sampler=lambda: healthy).total_child_process_slots == 7
    assert ResourceSchedulerConfig.for_proof_host(proof_resource_sampler=lambda: healthy,
        total_child_process_slots=3).total_child_process_slots == 3


def test_children_use_existing_root_credit_once_across_nested_layers(tmp_path):
    exactly_two = PROOF_PID_HEADROOM_TASKS + 2 * PROOF_PID_TASKS_PER_PROCESS
    current = [ProofHostResources(8, 8192, 8192, pid_task_limit=1000, available_pid_tasks=exactly_two)]
    scheduler = _scheduler(tmp_path, current)
    with scheduler.acquire('hammer', cpu_slots=2, memory_mb=200, child_process_slots=2, timeout=0) as root:
        with root.acquire_child(cpu_slots=2, memory_mb=200, child_process_slots=2, timeout=0) as middle:
            with middle.acquire_child(cpu_slots=1, memory_mb=100, child_process_slots=1, timeout=0):
                assert scheduler.snapshot()['active_lease_count'] == 3
                assert scheduler.snapshot()['allocated_child_process_slots'] == 2
        assert scheduler.try_acquire('hammer', cpu_slots=1, memory_mb=100, child_process_slots=1) is None
        assert scheduler.snapshot()['proof_backoff']['reason'] == 'proof_pid_headroom'
    assert scheduler.snapshot()['active_lease_count'] == 0


def test_external_pid_pressure_blocks_children_then_recovers_without_cancelling_existing_work(tmp_path):
    healthy = ProofHostResources(8, 8192, 8192, pid_task_limit=1000, available_pid_tasks=900)
    current = [healthy]
    scheduler = _scheduler(tmp_path, current)
    with scheduler.acquire('hammer', cpu_slots=2, memory_mb=200, child_process_slots=2, timeout=0) as root:
        current[0] = replace(healthy, available_pid_tasks=63)
        assert scheduler.try_acquire('hammer', cpu_slots=1, memory_mb=100, child_process_slots=1, parent=root) is None
        assert scheduler.snapshot()['proof_backoff']['reason'] == 'proof_pid_headroom'
        assert not root.cancelled
        current[0] = healthy
        with root.acquire_child(cpu_slots=1, memory_mb=100, child_process_slots=1, timeout=0):
            pass
    assert scheduler.snapshot()['waiting_request_count'] == 0


def test_pid_backoff_is_shared_and_keeps_its_cooldown(tmp_path, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as module
    wall = [1000.0]
    monkeypatch.setattr(module.time, 'time', lambda: wall[0])
    healthy = ProofHostResources(8, 8192, 8192, pid_task_limit=1000, available_pid_tasks=900)
    current = [healthy]
    first = _scheduler(tmp_path, current, proof_backoff_seconds=2)
    second = _scheduler(tmp_path, current, proof_backoff_seconds=2)
    with first.acquire('hammer', cpu_slots=2, memory_mb=200, child_process_slots=2, timeout=0) as root:
        current[0] = replace(healthy, available_pid_tasks=32)
        assert second.try_acquire('hammer', memory_mb=100, child_process_slots=1) is None
        current[0] = healthy
        assert first.try_acquire('hammer', memory_mb=100, child_process_slots=1, parent=root) is None
        wall[0] += 2.01
        with root.acquire_child(memory_mb=100, child_process_slots=1, timeout=0):
            pass


def test_pid_pressure_wait_is_cancellable_without_leases_or_waiter_leaks(tmp_path):
    healthy = ProofHostResources(8, 8192, 8192, pid_task_limit=1000, available_pid_tasks=900)
    current = [healthy]
    scheduler = _scheduler(tmp_path, current, proof_backoff_seconds=.02)
    cancel, errors = threading.Event(), []
    with scheduler.acquire('hammer', cpu_slots=2, memory_mb=200, child_process_slots=2, timeout=0) as root:
        current[0] = replace(healthy, available_pid_tasks=32)
        def wait():
            try:
                root.acquire_child(memory_mb=100, child_process_slots=1, timeout=2, cancel_event=cancel)
            except Exception as exc:
                errors.append(exc)
        worker = threading.Thread(target=wait)
        worker.start()
        try:
            deadline = time.monotonic() + 1
            while not scheduler.snapshot()['waiting_request_count'] and time.monotonic() < deadline:
                time.sleep(.005)
            assert scheduler.snapshot()['waiting_request_count'] == 1
            cancel.set()
            worker.join(1)
            assert not worker.is_alive()
            assert len(errors) == 1 and isinstance(errors[0], LeaseCancelledError)
            assert scheduler.snapshot()['active_lease_count'] == 1
            assert scheduler.snapshot()['waiting_request_count'] == 0
        finally:
            cancel.set()
            worker.join(2)
    assert scheduler.snapshot()['active_lease_count'] == 0


def test_known_counter_failure_produces_shared_telemetry_backoff(counters, tmp_path):
    proc, group = counters
    leaf = group / 'parent/worker'
    _pid_files(leaf, 1000, 10)
    scheduler = GlobalResourceScheduler(ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path / 'leases.json', proof_resource_sampler=lambda: collect_proof_host_resources(proc, group),
        lane_reservations={}, proof_backoff_seconds=0))
    (leaf / 'pids.current').unlink()
    assert scheduler.try_acquire('hammer', memory_mb=100, child_process_slots=1) is None
    assert scheduler.snapshot()['proof_backoff']['reason'] == 'proof_resource_telemetry_unknown'
