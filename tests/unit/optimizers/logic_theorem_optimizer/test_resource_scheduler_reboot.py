"""Reboot recovery cannot confuse recycled PIDs with prior-boot owners."""
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as resources


BOOT_A = "11111111-1111-4111-8111-111111111111"
BOOT_B = "22222222-2222-4222-8222-222222222222"


def configuration(path):
    return resources.ResourceSchedulerConfig(
        state_path=path, total_cpu_slots=2, total_memory_mb=200,
        total_child_process_slots=2, lane_reservations={},
        auto_renew_leases=False, lease_ttl_seconds=30,
        poll_interval_seconds=.005,
    )


def scheduler(tmp_path):
    return resources.GlobalResourceScheduler(configuration(tmp_path / "leases.json"))


def acquire(owner, **extra):
    return owner.acquire("orchestration", cpu_slots=2, memory_mb=200,
                         child_process_slots=2, timeout=0, **extra)


def read(owner):
    return json.loads(owner.state_path.read_bytes())


def write(owner, state):
    owner.state_path.write_text(json.dumps(state, sort_keys=True, separators=(",", ":")))


@pytest.mark.parametrize("raw,expected", [
    (BOOT_A + "\n", BOOT_A), ("", ""), ("unavailable", ""),
    ("1" * 256, ""), (BOOT_A.upper(), BOOT_A),
    ("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa".upper(), ""),
])
def test_boot_reader_requires_bounded_canonical_uuid(monkeypatch, raw, expected):
    monkeypatch.setattr(Path, "open", lambda *a, **k: io.StringIO(raw))
    assert resources._owner_boot_id() == expected


@pytest.mark.parametrize("error", [FileNotFoundError(), PermissionError(), UnicodeError()])
def test_unavailable_boot_reader_reports_unknown(monkeypatch, error):
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(Path, "open", fail)
    assert resources._owner_boot_id() == ""


def test_new_lease_and_waiter_share_actual_boot_without_changing_birth_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(resources, "_owner_boot_id", lambda: BOOT_A)
    owner = scheduler(tmp_path)
    stop = threading.Event()
    errors = []
    with acquire(owner) as parent:
        row = read(owner)["leases"][parent.lease_id]
        assert row["owner_boot_id"] == BOOT_A
        assert row["owner_birth_marker"] == resources._owner_birth_marker(os.getpid())
        def wait():
            try:
                owner.acquire("hammer", memory_mb=1, timeout=2, cancel_event=stop)
            except BaseException as error:
                errors.append(error)
        worker = threading.Thread(target=wait)
        worker.start()
        try:
            deadline = time.monotonic() + 1
            while not read(owner)["waiters"] and time.monotonic() < deadline:
                time.sleep(.005)
            waiter, = read(owner)["waiters"].values()
            assert waiter["owner_boot_id"] == BOOT_A
            assert waiter["owner_birth_marker"] == row["owner_birth_marker"]
        finally:
            stop.set()
            worker.join(3)
        assert not worker.is_alive()
        assert len(errors) == 1 and isinstance(errors[0], resources.LeaseCancelledError)
    assert owner.snapshot()["active_lease_count"] == 0


def test_new_boot_recovers_identical_pid_birth_marker_and_future_heartbeat(tmp_path, monkeypatch):
    monkeypatch.setattr(resources, "_owner_boot_id", lambda: BOOT_A)
    owner = scheduler(tmp_path)
    parent = acquire(owner)
    child = parent.acquire_child(memory_mb=100, timeout=0)
    leaf = child.acquire_child(memory_mb=50, timeout=0)
    before = read(owner)
    assert all(row["expires_at"] > time.time() for row in before["leases"].values())
    assert {row["owner_pid"] for row in before["leases"].values()} == {os.getpid()}
    monkeypatch.setattr(resources, "_owner_boot_id", lambda: BOOT_B)
    assert set(owner.recover_stale_leases()) == {parent.lease_id, child.lease_id, leaf.lease_id}
    assert owner.snapshot()["allocated"] == {"cpu_slots": 0, "memory_mb": 0}
    assert not read(owner)["leases"]
    assert all(not lease.renew() for lease in (parent, child, leaf))


@pytest.mark.parametrize("operation", ["renew", "cancel", "release", "poll", "token", "parent"])
def test_old_boot_cannot_supply_lease_authority(tmp_path, monkeypatch, operation):
    monkeypatch.setattr(resources, "_owner_boot_id", lambda: BOOT_A)
    owner = scheduler(tmp_path)
    parent = acquire(owner)
    token = parent.token
    before = owner.state_path.read_bytes()
    monkeypatch.setattr(resources, "_owner_boot_id", lambda: BOOT_B)
    if operation == "poll":
        assert parent.cancellation_signal.is_set()
        assert parent.combined_cancellation_signal(threading.Event()).is_set()
        assert owner.state_path.read_bytes() == before  # Polls stay read-only.
    elif operation in ("token", "parent"):
        with pytest.raises(resources.LeaseNotFoundError):
            owner.acquire("hammer", memory_mb=1, timeout=0,
                          parent=token if operation == "token" else parent)
    else:
        assert not getattr(parent, operation)()
        assert not read(owner)["leases"]
    assert owner.snapshot()["active_lease_count"] == 0


@pytest.mark.parametrize("stored", [None, "", "unknown", "ABC", 123, False, [], {}, BOOT_A.replace("-", "")])
def test_unknown_or_malformed_stored_boot_preserves_live_owner(tmp_path, monkeypatch, stored):
    monkeypatch.setattr(resources, "_owner_boot_id", lambda: BOOT_B)
    owner = scheduler(tmp_path)
    parent = acquire(owner)
    data = read(owner)
    if stored is None:
        data["leases"][parent.lease_id].pop("owner_boot_id")
    else:
        data["leases"][parent.lease_id]["owner_boot_id"] = stored
    write(owner, data)
    try:
        assert owner.recover_stale_leases() == []
        assert not parent.cancelled
        assert parent.renew()
        assert owner.snapshot()["allocated"]["memory_mb"] == 200
    finally:
        parent.release()


@pytest.mark.parametrize("current", ["", "unknown", None, 123, BOOT_B.replace("-", "")])
def test_unknown_current_boot_cannot_reclaim_live_record(tmp_path, monkeypatch, current):
    monkeypatch.setattr(resources, "_owner_boot_id", lambda: BOOT_A)
    owner = scheduler(tmp_path)
    parent = acquire(owner)
    monkeypatch.setattr(resources, "_owner_boot_id", lambda: current)
    try:
        assert owner.recover_stale_leases() == []
        assert not parent.cancelled
        assert parent.renew()
    finally:
        parent.release()


def test_boot_identity_is_in_operation_cache_and_read_only_once(tmp_path, monkeypatch):
    monkeypatch.setattr(resources, "_owner_boot_id", lambda: BOOT_A)
    owner = scheduler(tmp_path)
    parent = acquire(owner)
    child = parent.acquire_child(memory_mb=100, timeout=0)
    data = read(owner)
    data["leases"][child.lease_id]["owner_boot_id"] = BOOT_B
    write(owner, data)
    observed = []
    monkeypatch.setattr(resources, "_owner_boot_id", lambda: observed.append(1) or BOOT_A)
    try:
        assert owner.snapshot()["active_lease_count"] == 1
        assert len(observed) == 1
        assert not parent.cancelled
        assert len(observed) == 2  # No liveness cache across operations.
        assert set(read(owner)["leases"]) == {parent.lease_id}
    finally:
        parent.release()


def test_boot_recovery_keeps_independently_live_child_reserved(tmp_path, monkeypatch):
    monkeypatch.setattr(resources, "_owner_boot_id", lambda: BOOT_A)
    owner = scheduler(tmp_path)
    parent = acquire(owner)
    child = parent.acquire_child(memory_mb=100, timeout=0)
    data = read(owner)
    data["leases"][parent.lease_id]["owner_boot_id"] = BOOT_B
    write(owner, data)
    try:
        assert owner.recover_stale_leases() == []
        assert child.cancelled and not parent.renew()
        assert owner.snapshot()["allocated"]["memory_mb"] == 200
        assert owner.try_acquire("hammer", memory_mb=1) is None
        with pytest.raises(resources.ResourceConfigurationError, match="active shared state"):
            resources.GlobalResourceScheduler(replace(owner.config, total_memory_mb=300))
    finally:
        child.release()
        parent.release()
    assert not read(owner)["leases"]


@pytest.mark.parametrize("dead_by", ["boot", "birth_marker"])
def test_capacity_change_recovers_only_proven_dead_lease_and_waiter(tmp_path, monkeypatch, dead_by):
    monkeypatch.setattr(resources, "_owner_boot_id", lambda: BOOT_A)
    owner = scheduler(tmp_path)
    parent = acquire(owner)
    data = read(owner)
    row = data["leases"][parent.lease_id]
    data["waiters"]["abandoned"] = dict(row)
    if dead_by == "boot":
        monkeypatch.setattr(resources, "_owner_boot_id", lambda: BOOT_B)
    else:
        row["owner_birth_marker"] = "previous incarnation"
        data["waiters"]["abandoned"]["owner_birth_marker"] = "previous incarnation"
    write(owner, data)
    reopened = resources.GlobalResourceScheduler(replace(owner.config, total_memory_mb=300))
    assert not read(reopened)["leases"] and not read(reopened)["waiters"]
    assert reopened.config.total_memory_mb == 300
    with reopened.acquire("hammer", memory_mb=300, timeout=0):
        pass


@pytest.mark.parametrize("expired,legacy", [(False, False), (True, False), (True, True)])
def test_capacity_change_refuses_live_or_ambiguous_old_owner(tmp_path, monkeypatch, expired, legacy):
    monkeypatch.setattr(resources, "_owner_boot_id", lambda: BOOT_A)
    owner = scheduler(tmp_path)
    parent = acquire(owner)
    data = read(owner)
    row = data["leases"][parent.lease_id]
    if expired:
        row["expires_at"] = 0
    if legacy:
        row.pop("owner_boot_id")
    write(owner, data)
    before = owner.state_path.read_bytes()
    try:
        with pytest.raises(resources.ResourceConfigurationError, match="active shared state"):
            resources.GlobalResourceScheduler(replace(owner.config, total_memory_mb=300))
        assert owner.state_path.read_bytes() == before
        assert owner.snapshot()["allocated"]["memory_mb"] == 200
    finally:
        parent.release()


def test_future_schema_rejected_before_boot_recovery(tmp_path, monkeypatch):
    monkeypatch.setattr(resources, "_owner_boot_id", lambda: BOOT_A)
    owner = scheduler(tmp_path)
    parent = acquire(owner)
    data = read(owner)
    data["schema_version"] = "unreviewed-future-schema"
    write(owner, data)
    before = owner.state_path.read_bytes()
    monkeypatch.setattr(resources, "_owner_boot_id", lambda: BOOT_B)
    with pytest.raises(resources.SchedulerStateError, match="unsupported"):
        resources.GlobalResourceScheduler(replace(owner.config, total_memory_mb=300))
    assert owner.state_path.read_bytes() == before


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="native Linux boot identity")
def test_fresh_python_process_recovers_prior_boot_without_pid_death(tmp_path):
    current = resources._owner_boot_id()
    if not current:
        pytest.skip("kernel boot identity is unavailable")
    owner = scheduler(tmp_path)
    parent = acquire(owner)
    data = read(owner)
    data["leases"][parent.lease_id]["owner_boot_id"] = BOOT_A if current != BOOT_A else BOOT_B
    write(owner, data)
    program = """
import json, sys
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import GlobalResourceScheduler, ResourceSchedulerConfig
config = ResourceSchedulerConfig(state_path=sys.argv[1], total_cpu_slots=2,
    total_memory_mb=300, total_child_process_slots=2, lane_reservations={},
    auto_renew_leases=False, lease_ttl_seconds=30, poll_interval_seconds=.005)
owner = GlobalResourceScheduler(config)
assert owner.snapshot()['active_lease_count'] == 0
with owner.acquire('hammer', cpu_slots=1, memory_mb=300, timeout=0):
    assert owner.snapshot()['allocated']['memory_mb'] == 300
print(json.dumps({'leases': owner.snapshot()['active_lease_count'], 'memory_mb': config.total_memory_mb}))
"""
    completed = subprocess.run([sys.executable, "-c", program, str(owner.state_path)],
                               capture_output=True, text=True, timeout=30, check=True)
    assert json.loads(completed.stdout) == {"leases": 0, "memory_mb": 300}
    assert os.getpid() == data["leases"][parent.lease_id]["owner_pid"]
    assert not read(owner)["leases"]


@pytest.mark.parametrize("operation", [
    "snapshot", "active_leases", "recover_stale_leases", "admit", "renew",
    "cancel", "release", "poll", "reset",
])
def test_old_facade_cannot_restore_previous_idle_configuration(tmp_path, operation):
    owner = scheduler(tmp_path)
    lease = acquire(owner)
    lease.release()
    updated = resources.GlobalResourceScheduler(replace(owner.config, total_memory_mb=100))
    before = owner.state_path.read_bytes()
    before_stat = owner.state_path.stat()
    actions = {
        "snapshot": owner.snapshot,
        "active_leases": owner.active_leases,
        "recover_stale_leases": owner.recover_stale_leases,
        "admit": lambda: owner.acquire("hammer", memory_mb=150, timeout=0),
        "renew": lambda: owner.renew(lease.lease_id, lease.lease_key),
        "cancel": lambda: owner.cancel(lease.lease_id, lease.lease_key),
        "release": lambda: owner.release(lease.lease_id, lease.lease_key),
        "poll": lambda: owner.is_cancelled(lease.lease_id),
        "reset": owner.reset,
    }
    with pytest.raises(resources.ResourceConfigurationError, match="configuration changed"):
        actions[operation]()
    assert owner.state_path.read_bytes() == before
    after_stat = owner.state_path.stat()
    assert (after_stat.st_ino, after_stat.st_mtime_ns) == (before_stat.st_ino, before_stat.st_mtime_ns)
    assert updated.snapshot()["capacity"]["memory_mb"] == 100
    assert not list(tmp_path.glob(".leases.json.*.tmp"))


def test_explicit_new_facade_can_reconfigure_idle_pool_and_continue(tmp_path):
    first = scheduler(tmp_path)
    second = resources.GlobalResourceScheduler(replace(first.config, total_memory_mb=100))
    same = resources.GlobalResourceScheduler(second.config)
    with same.acquire("hammer", memory_mb=100, timeout=0):
        assert second.snapshot()["allocated"]["memory_mb"] == 100
        with pytest.raises(resources.ResourceConfigurationError, match="configuration changed"):
            first.snapshot()
    # Explicit construction is still the intentional idle reconfiguration API.
    restored = resources.GlobalResourceScheduler(first.config)
    with acquire(restored):
        assert first.snapshot()["allocated"]["memory_mb"] == 200


def test_explicit_global_configure_replaces_cached_facade_only_when_idle(tmp_path, monkeypatch):
    monkeypatch.setattr(resources, "_GLOBAL_SCHEDULERS", {})
    config = configuration(tmp_path / "leases.json")
    first = resources.configure_global_resource_scheduler(config)
    parent = acquire(first)
    limited = replace(config, total_memory_mb=100)
    before = first.state_path.read_bytes()
    try:
        with pytest.raises(resources.ResourceConfigurationError, match="active shared state"):
            resources.configure_global_resource_scheduler(limited)
        assert first.state_path.read_bytes() == before
        assert resources.get_global_resource_scheduler(config) is first
        assert first.snapshot()["allocated"]["memory_mb"] == 200
    finally:
        parent.release()
    second = resources.configure_global_resource_scheduler(limited)
    assert resources.get_global_resource_scheduler(limited) is second
    with pytest.raises(resources.ResourceConfigurationError, match="configuration changed"):
        first.snapshot()
    with second.acquire("hammer", memory_mb=100, timeout=0):
        pass


def test_existing_facade_still_normalizes_equivalent_legacy_configuration(tmp_path):
    owner = scheduler(tmp_path)
    parent = acquire(owner)
    data = read(owner)
    original_lease = data["leases"][parent.lease_id]
    data["config"].pop("max_waiting_requests")
    write(owner, data)
    try:
        assert owner.snapshot()["allocated"]["memory_mb"] == 200
        assert read(owner)["config"]["max_waiting_requests"] is None
        assert read(owner)["leases"][parent.lease_id] == original_lease
    finally:
        parent.release()


def test_old_facade_refuses_changed_configuration_before_recovering_dead_records(tmp_path, monkeypatch):
    monkeypatch.setattr(resources, "_owner_boot_id", lambda: BOOT_A)
    owner = scheduler(tmp_path)
    updated = resources.GlobalResourceScheduler(replace(owner.config, total_memory_mb=100))
    updated.acquire("hammer", memory_mb=100, timeout=0)
    monkeypatch.setattr(resources, "_owner_boot_id", lambda: BOOT_B)
    before = owner.state_path.read_bytes()
    with pytest.raises(resources.ResourceConfigurationError, match="configuration changed"):
        owner.recover_stale_leases()
    assert owner.state_path.read_bytes() == before
    assert updated.snapshot()["active_lease_count"] == 0
