"""Exact nonpersistent observations of private native scheduler fixtures.

Regular-file/lock behavior is exercised against actual private files. Unsafe
alias inode modes and ELOOP are simulated at the filesystem boundary: this
suite never creates symlinks, hardlinks or FIFOs under the strict native owner.
No provider, model, host-pressure sampler or production control state is used.
"""
from contextlib import contextmanager
from copy import deepcopy
import errno
import fcntl
import json
import os
from pathlib import Path
import stat
import threading
import time
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import existing_resource_scheduler as existing
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as sdk


def forbidden(*args, **kwargs):
    pytest.fail("inspection must not admit, recover, sample pressure or persist")


@pytest.fixture
def private(tmp_path):
    scheduler = sdk.GlobalResourceScheduler(sdk.ResourceSchedulerConfig(
        state_path=tmp_path / "scheduler.json", total_cpu_slots=2, total_memory_mb=8,
        total_gpu_memory_mb=None, total_unified_memory_mb=None, total_child_process_slots=3,
        reserved_memory_mb=0, lane_reservations={}, auto_renew_leases=False,
        proof_safety_enabled=True, resource_pressure_sampler=forbidden,
        proof_resource_sampler=forbidden))
    marker = sdk._owner_birth_marker(os.getpid())
    assert marker, "the test process must have an independently observed birth marker"
    now = time.time()
    def record(identifier, parent=None, **overrides):
        value = dict(lease_id=identifier, lease_key="secret-key-" + identifier,
            request_id="validation:owned" if identifier == "owned" else "foreign-request-" + identifier,
            lane="validation", owner_pid=os.getpid(), owner_birth_marker=marker,
            owner_boot_id=sdk._owner_boot_id(), parent_lease_id=parent, acquired_at=now,
            heartbeat_at=now, expires_at=now + 120, cancelled=False,
            cpu_slots=1, memory_mb=1, gpu_memory_mb=0, unified_memory_mb=0,
            child_process_slots=0, metadata={"authority_token": "private-token-" + identifier})
        value.update(overrides)
        return value
    state = json.loads(scheduler.state_path.read_bytes())
    state["leases"] = {"owned": record("owned"), "child": record("child", "owned"),
        "leaf": record("leaf", "child"),
        "unrelated": record("unrelated", expires_at=1, owner_birth_marker="dead-foreign-owner")}
    state["waiters"] = {"foreign-waiter": record("foreign-waiter", expires_at=1)}
    state["proof_backoff"] = {"until": now + 60, "reason": "foreign retained pressure"}
    scheduler.state_path.write_text(json.dumps(state, sort_keys=True, separators=(",", ":")))
    return SimpleNamespace(scheduler=scheduler, marker=marker, state=state)


def inspect(private, **overrides):
    kwargs = dict(expected_request_id="validation:owned", expected_lane=sdk.ResourceLane.VALIDATION,
        expected_owner_pid=os.getpid(), expected_owner_birth_marker=private.marker)
    kwargs.update(overrides)
    return private.scheduler.inspect_lease("owned", **kwargs)


def save(private):
    private.scheduler.state_path.write_text(json.dumps(private.state, sort_keys=True, separators=(",", ":")))


def identity(path):
    item = path.stat()
    return item.st_dev, item.st_ino, item.st_mtime_ns, item.st_size


def test_exact_read_never_changes_any_foreign_row_metrics_or_recovery(private, monkeypatch):
    scheduler = private.scheduler
    original = scheduler.state_path.read_bytes()
    before = identity(scheduler.state_path), identity(scheduler.lock_path)
    for name in ("_new_state", "_recover_stale_locked", "recover_stale_leases", "snapshot",
                 "acquire", "renew", "release", "cancel", "_observe_recovery"):
        monkeypatch.setattr(scheduler, name, forbidden)
    monkeypatch.setattr(sdk.os, "fsync", forbidden)
    monkeypatch.setattr(sdk.os, "replace", forbidden)
    result = inspect(private)
    assert result["status"] == "present" and result["binding_verified"] is True
    assert result["owner_birth_binding_verified"] is True and result["read_only"] is True
    assert result["lease"]["owner_alive"] is True
    assert [row["lease_id"] for row in result["descendants"]] == ["child", "leaf"]
    assert result["descendant_count"] == result["live_descendant_count"] == 2
    assert result["historical_release_status"] is None
    assert scheduler.state_path.read_bytes() == original
    assert (identity(scheduler.state_path), identity(scheduler.lock_path)) == before
    assert not list(scheduler.state_path.parent.glob(".scheduler.json.*.tmp"))


def test_public_existing_facade_preserves_policy_and_uses_readonly_existing_lock(private, monkeypatch):
    before = private.scheduler.state_path.read_bytes()
    policy = private.state["config"]
    facade = existing.open_existing_scheduler(private.scheduler.state_path,
        existing.policy_sha256(policy), inspection_only=True)
    calls, original = [], sdk.os.open
    def observed(path, flags, *args, **kwargs):
        if Path(path) in (facade.state_path, facade.lock_path):
            calls.append((Path(path), flags))
            assert flags & os.O_ACCMODE == os.O_RDONLY
            assert flags & os.O_NOFOLLOW and flags & os.O_NONBLOCK
            assert not flags & (os.O_CREAT | os.O_TRUNC)
        return original(path, flags, *args, **kwargs)
    monkeypatch.setattr(sdk.os, "open", observed)
    private.scheduler = facade
    assert inspect(private)["binding_verified"] is True
    assert facade.state_path.read_bytes() == before
    assert {path for path, _ in calls} == {facade.state_path, facade.lock_path}
    assert json.loads(before)["config"] == policy


@pytest.mark.parametrize("field,value", [
    ("expected_request_id", "validation:other"), ("expected_lane", "proof"),
    ("expected_owner_pid", 2147483647), ("expected_owner_birth_marker", "recycled-pid-birth")])
def test_each_exact_binding_rejects_other_record_identity(private, field, value):
    before = private.scheduler.state_path.read_bytes()
    with pytest.raises(sdk.LeaseNotFoundError, match="identity"):
        inspect(private, **{field: value})
    assert private.scheduler.state_path.read_bytes() == before


@pytest.mark.parametrize("field,value", [
    ("expected_request_id", ""), ("expected_request_id", "validation:\0owned"),
    ("expected_lane", ""), ("expected_owner_pid", True),
    ("expected_owner_birth_marker", ""), ("bounded_lock_timeout", 0),
    ("bounded_lock_timeout", float("nan")), ("bounded_lock_timeout", 31)])
def test_invalid_identity_or_unbounded_timeout_refuses_before_state_read(private, monkeypatch, field, value):
    monkeypatch.setattr(private.scheduler, "_locked_state", forbidden)
    with pytest.raises(sdk.ResourceConfigurationError):
        inspect(private, **{field: value})


@pytest.mark.parametrize("status", ["present", "expired", "cancelled", "release_requested"])
def test_retained_statuses_do_not_imply_stopped_work_or_reclaimed_capacity(private, status):
    row = private.state["leases"]["owned"]
    if status == "expired":
        row["expires_at"] = 1
    elif status == "cancelled":
        row["cancelled"] = True
    elif status == "release_requested":
        row.update(release_requested=True, cancelled=True, expires_at=1)
    save(private)
    before = private.scheduler.state_path.read_bytes()
    result = inspect(private)
    assert result["status"] == status and result["lease"]["owner_alive"] is True
    assert result["live_descendant_count"] == 2
    assert result["lease"]["release_requested"] is (status == "release_requested")
    assert result["lease"]["cancelled"] is (status in {"cancelled", "release_requested"})
    assert result["lease"]["expired"] is (status in {"expired", "release_requested"})
    assert result["historical_release_status"] is None
    assert private.scheduler.state_path.read_bytes() == before


@pytest.mark.parametrize("retained_descendants", [False, True])
def test_absence_is_current_absence_with_null_history_not_a_release(private, retained_descendants):
    private.state["leases"].pop("owned")
    if not retained_descendants:
        private.state["leases"].pop("child")
        private.state["leases"].pop("leaf")
    save(private)
    before = private.scheduler.state_path.read_bytes()
    result = inspect(private)
    assert result["status"] == "absent" and result["lease"] is None
    assert result["binding_verified"] is result["owner_birth_binding_verified"] is None
    assert result["historical_release_status"] is None
    assert "no release history" in result["historical_release_reason"]
    assert result["descendant_count"] == (2 if retained_descendants else 0)
    assert private.scheduler.state_path.read_bytes() == before


def test_birth_binding_is_explicitly_unknown_when_not_supplied(private):
    result = inspect(private, expected_owner_birth_marker=None)
    assert result["binding_verified"] is True
    assert result["owner_birth_binding_verified"] is None


def test_only_related_owner_liveness_is_observed_and_output_is_detached(private, monkeypatch):
    private.state["leases"]["leaf"]["owner_birth_marker"] = "dead-child-owner"
    save(private)
    observed = []
    def alive(pid, marker):
        observed.append((pid, marker))
        return marker == private.marker
    monkeypatch.setattr(sdk, "_owner_is_alive", alive)
    first = inspect(private)
    assert set(marker for _, marker in observed) == {private.marker, "dead-child-owner"}
    assert first["live_descendant_count"] == 1
    encoded = json.dumps(first)
    for secret in ("secret-key", "private-token", "authority_token", "lease_key",
                   "foreign-request", "foreign-waiter", "unrelated", "dead-foreign-owner"):
        assert secret not in encoded
    first["lease"]["owner_pid"] = 1
    first["descendants"].clear()
    second = inspect(private)
    assert second["lease"]["owner_pid"] == os.getpid() and len(second["descendants"]) == 2


@pytest.mark.parametrize("missing", ["state", "lock", "empty_state"])
def test_missing_existing_files_never_initialize_or_create(private, monkeypatch, missing):
    scheduler = private.scheduler
    target = scheduler.lock_path if missing == "lock" else scheduler.state_path
    if missing == "empty_state":
        target.write_bytes(b"")
    else:
        target.unlink()
    before = {path.name: path.read_bytes() for path in target.parent.iterdir() if path.is_file()}
    monkeypatch.setattr(scheduler, "_new_state", forbidden)
    with pytest.raises((OSError, sdk.SchedulerStateError)):
        inspect(private)
    after = {path.name: path.read_bytes() for path in target.parent.iterdir() if path.is_file()}
    assert before == after
    assert target.exists() is (missing == "empty_state")


@pytest.mark.parametrize("target,unsafe", [
    ("state", "hardlink"), ("lock", "hardlink"),
    ("state", "fifo"), ("lock", "fifo"), ("parent", "symlink"), ("state", "nofollow_error")])
def test_unsafe_filesystem_boundaries_refuse_without_creating_real_aliases(private, monkeypatch, target, unsafe):
    scheduler = private.scheduler
    path = scheduler.state_path if target == "state" else scheduler.lock_path
    before = scheduler.state_path.read_bytes()
    if target == "parent":
        original = Path.lstat
        def lstat(item, *args, **kwargs):
            info = original(item, *args, **kwargs)
            if item == scheduler.state_path.parent:
                return SimpleNamespace(st_mode=stat.S_IFLNK | 0o777, st_dev=info.st_dev, st_ino=info.st_ino)
            return info
        monkeypatch.setattr(Path, "lstat", lstat)
    elif unsafe == "nofollow_error":
        original = sdk.os.open
        def nofollow(item, flags, *args, **kwargs):
            if Path(item) == path:
                assert flags & os.O_NOFOLLOW and not flags & os.O_CREAT
                raise OSError(errno.ELOOP, "simulated no-follow refusal")
            return original(item, flags, *args, **kwargs)
        monkeypatch.setattr(sdk.os, "open", nofollow)
    else:
        original, wanted = sdk.os.fstat, path.stat()
        def unsafe_stat(descriptor):
            info = original(descriptor)
            if (info.st_dev, info.st_ino) == (wanted.st_dev, wanted.st_ino):
                values = {name: getattr(info, name) for name in
                    ("st_mode", "st_nlink", "st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")}
                values["st_nlink" if unsafe == "hardlink" else "st_mode"] = (
                    2 if unsafe == "hardlink" else stat.S_IFIFO | 0o600)
                return SimpleNamespace(**values)
            return info
        monkeypatch.setattr(sdk.os, "fstat", unsafe_stat)
    with pytest.raises((OSError, sdk.SchedulerStateError)):
        inspect(private)
    assert scheduler.state_path.read_bytes() == before


@pytest.mark.parametrize("lock_kind", ["thread", "file"])
def test_existing_lock_waits_are_bounded_without_mutating_state(private, lock_kind):
    scheduler = private.scheduler
    before = scheduler.state_path.read_bytes()
    ready, release = threading.Event(), threading.Event()
    def hold_thread():
        with scheduler._thread_lock:
            ready.set()
            release.wait(2)
    worker = None
    blocker = None
    try:
        if lock_kind == "thread":
            worker = threading.Thread(target=hold_thread)
            worker.start()
            assert ready.wait(1)
        else:
            blocker = scheduler.lock_path.open("rb")
            fcntl.flock(blocker.fileno(), fcntl.LOCK_EX)
        started = time.monotonic()
        with pytest.raises(sdk.ResourceAdmissionDeadlineError):
            inspect(private, bounded_lock_timeout=.04)
        assert time.monotonic() - started < .6
        assert scheduler.state_path.read_bytes() == before
        assert sdk.resource_operation_deadline() is None
    finally:
        release.set()
        if worker is not None:
            worker.join(2)
            assert not worker.is_alive()
        if blocker is not None:
            fcntl.flock(blocker.fileno(), fcntl.LOCK_UN)
            blocker.close()


@pytest.mark.parametrize("cleanup", [False, True])
def test_inspection_preserves_enclosing_productive_or_cleanup_deadline(private, cleanup):
    end = time.monotonic() + 2
    scope = sdk.resource_cleanup_deadline(native_deadline_monotonic=end) if cleanup else (
        sdk.resource_admission_deadline(work_deadline_monotonic=end - .25, native_deadline_monotonic=end))
    with scope:
        previous = sdk.resource_operation_deadline()
        assert inspect(private, bounded_lock_timeout=3)["status"] == "present"
        assert sdk.resource_operation_deadline() is previous
    assert sdk.resource_operation_deadline() is None


def test_deep_descendants_use_bounded_adjacency_instead_of_global_repeated_scan(private, monkeypatch):
    template = deepcopy(private.state["leases"]["child"])
    private.state["leases"].pop("child")
    private.state["leases"].pop("leaf")
    parent = "owned"
    for number in range(160):
        identifier = f"chain-{number:03}"
        row = deepcopy(template)
        row.update(lease_id=identifier, parent_lease_id=parent)
        private.state["leases"][identifier] = row
        parent = identifier
    save(private)
    monkeypatch.setattr(private.scheduler, "_descendants", forbidden)
    result = inspect(private)
    assert result["descendant_count"] == result["live_descendant_count"] == 160
    assert [row["lease_id"] for row in result["descendants"]] == [f"chain-{n:03}" for n in range(160)]


@pytest.mark.parametrize("limit,value,reason", [
    ("_LEASE_INSPECTION_MAX_RECORDS", 3, "total-record"),
    ("_LEASE_INSPECTION_MAX_DESCENDANTS", 1, "descendant")])
def test_complete_population_bounds_refuse_without_truncating(private, monkeypatch, limit, value, reason):
    before = private.scheduler.state_path.read_bytes()
    monkeypatch.setattr(sdk, limit, value)
    with pytest.raises(sdk.SchedulerStateError, match=reason + " bound"):
        inspect(private)
    assert private.scheduler.state_path.read_bytes() == before


def test_reachable_ancestry_cycle_refuses_instead_of_reporting_drained(private):
    private.state["leases"]["owned"]["parent_lease_id"] = "leaf"
    save(private)
    before = private.scheduler.state_path.read_bytes()
    with pytest.raises(sdk.SchedulerStateError, match="cycle"):
        inspect(private)
    assert private.scheduler.state_path.read_bytes() == before


def test_deadline_is_rechecked_during_index_and_walk_not_only_after_projection(private, monkeypatch):
    original = private.scheduler._locked_state
    check = sdk._check_resource_operation_deadline
    observed = []
    @contextmanager
    def locked(**kwargs):
        with original(**kwargs) as state:
            def expire_during_walk():
                observed.append(True)
                if len(observed) == 2:
                    raise sdk.ResourceAdmissionDeadlineError("injected traversal deadline")
                check()
            with monkeypatch.context() as patch:
                patch.setattr(sdk, "_check_resource_operation_deadline", expire_during_walk)
                yield state
    monkeypatch.setattr(private.scheduler, "_locked_state", locked)
    before = private.scheduler.state_path.read_bytes()
    with pytest.raises(sdk.ResourceAdmissionDeadlineError, match="traversal deadline"):
        inspect(private)
    assert len(observed) == 2 and sdk.resource_operation_deadline() is None
    assert private.scheduler.state_path.read_bytes() == before


def test_inspection_only_public_opener_requires_existing_lock_without_creation(private):
    scheduler = private.scheduler
    scheduler.lock_path.unlink()
    before = scheduler.state_path.read_bytes()
    with pytest.raises(FileNotFoundError):
        existing.open_existing_scheduler(scheduler.state_path,
            existing.policy_sha256(private.state["config"]), inspection_only=True)
    assert not scheduler.lock_path.exists()
    assert scheduler.state_path.read_bytes() == before


@pytest.mark.parametrize("operation", ["acquire", "release", "snapshot", "persist", "reconfigure"])
def test_inspection_only_facade_refuses_all_persistent_operations(private, operation):
    scheduler = existing.open_existing_scheduler(private.scheduler.state_path,
        existing.policy_sha256(private.state["config"]), inspection_only=True)
    before = scheduler.state_path.read_bytes()
    paths = identity(scheduler.state_path), identity(scheduler.lock_path)
    with pytest.raises(existing.ExistingResourceSchedulerError, match="inspection-only"):
        if operation == "acquire":
            scheduler.acquire("validation", cpu_slots=1, memory_mb=1, timeout=0)
        elif operation == "release":
            scheduler.release("owned")
        elif operation == "snapshot":
            scheduler.snapshot()
        elif operation == "persist":
            scheduler._persist_locked_state(before.decode(), deepcopy(private.state))
        else:
            with scheduler._locked_state(persist=False, allow_reconfigure=True):
                pytest.fail("inspection-only facade admitted reconfiguration")
    assert scheduler.state_path.read_bytes() == before
    assert (identity(scheduler.state_path), identity(scheduler.lock_path)) == paths


def test_default_existing_facade_retains_explicit_persistence(private):
    scheduler = existing.open_existing_scheduler(private.scheduler.state_path,
        existing.policy_sha256(private.state["config"]))
    with scheduler._locked_state() as state:
        state["metrics"]["private_fixture_marker"] = "default writer preserved"
    saved = json.loads(scheduler.state_path.read_bytes())
    assert saved["metrics"]["private_fixture_marker"] == "default writer preserved"
    assert saved["leases"] == private.state["leases"]
    assert saved["config"] == private.state["config"]
