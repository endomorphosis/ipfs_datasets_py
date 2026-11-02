"""Selected storage inspection using private ordinary files, without admission.

Alias rejection injects metadata/open errors; it never creates real aliases
inside the owned validation attempt. No fixture accesses a host control file.
"""
import errno
import hashlib
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_resource_recovery as recovery


RID = "a" * 32
REQUEST = "b" * 64
LEASE = "c" * 32


def identity(path):
    info = path.stat()
    return {"path": str(path), "device": info.st_dev, "inode": info.st_ino}


@pytest.fixture
def inspection(tmp_path):
    roots = [tmp_path / "outputs", tmp_path / "cache"]
    for root in roots:
        root.mkdir()
    attempt = roots[0] / "attempt"
    attempt.mkdir()
    (attempt / "retained-evidence.json").write_text('{"completed":true}\n')
    ledger = tmp_path / "ledger.json"
    lock = tmp_path / "ledger.json.lock"
    lock.write_bytes(b"")
    row = {
        "reservation_id": RID, "status": "retained", "owner_pid": 99999999,
        "storage_bytes": 4096, "memory_mb": 128, "cpu_slots": 1,
        "child_process_slots": 1, "scheduler_lane": "validation",
        "workload": "canonical_validation", "created_at": 1.0,
        "attempt_directory": identity(attempt), "child": {"pid": 99999998, "birth": "123"},
        "prior_children": [], "external_charges": {}, "last_usage": {},
        "artifacts_durable_asserted": False, "validation_request_sha256": REQUEST,
        "owner_birth": "122", "scheduler_state_path": str(tmp_path / "scheduler-not-opened.json"),
        "scheduler_policy_sha256": "d" * 64, "native_lease_id": LEASE,
        "process_scope": "isolated_process_group_only",
        "outputs": {name: str(attempt / name) for name in ("pytest", "tmp", "cache", "db", "exports", "logs")},
        "private_extra": "not-exported", "lease_key": "never-export-a-credential",
    }
    foreign = {"reservation_id": "foreign", "status": "active", "owner_pid": 99999997,
               "storage_bytes": 1024, "external_charges": {}, "private_extra": "foreign-secret"}
    data = {"schema": recovery.resources.SCHEMA, "roots": [identity(root) for root in roots],
            "limit_bytes": recovery.resources.MAX_STORAGE_BYTES,
            "reservations": {RID: row, "foreign": foreign}}
    def write():
        ledger.write_text(json.dumps(data))
    write()
    args = dict(roots=roots, reservation_id=RID, expected_request_sha256=REQUEST,
                attempt_directory=attempt, ledger_lock_timeout_seconds=0)
    return SimpleNamespace(ledger=ledger, lock=lock, attempt=attempt, roots=roots,
                           row=row, data=data, args=args, write=write)


@pytest.mark.parametrize("status", ["active", "retained", "released"])
def test_exact_selected_status_hash_and_custody_do_not_assert_compute_release(inspection, status):
    c = inspection
    c.row["status"] = status
    c.write()
    before = c.ledger.read_bytes()
    result = recovery.inspect_validation_reservation(c.ledger, **c.args)
    expected = hashlib.sha256(json.dumps(c.row, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    assert result["present"] is result["binding_verified"] is True
    assert result["status"] == status and result["record_sha256"] == expected
    assert result["custody"]["native_lease_id"] == LEASE
    assert result["custody"]["scheduler_request_id"] == "validation:" + RID
    assert result["custody"]["owner_birth"] == "122"
    assert result["native_lease_disposition"] is None
    assert result["native_lease_disposition_reason"]
    assert result["historical_release_established"] is False
    assert result["admitted"] is result["state_written"] is result["recovery_performed"] is False
    encoded = json.dumps(result)
    assert "never-export-a-credential" not in encoded and "lease_key" not in encoded
    assert "foreign-secret" not in encoded and "not-exported" not in encoded
    assert c.ledger.read_bytes() == before


def test_missing_selected_row_is_unknown_not_released(inspection):
    c = inspection
    del c.data["reservations"][RID]
    c.write()
    before = c.ledger.read_bytes()
    result = recovery.inspect_validation_reservation(c.ledger, **c.args)
    assert result["present"] is result["binding_verified"] is False
    assert result["status"] is result["record_sha256"] is result["custody"] is None
    assert result["record_reason"] and result["historical_release_established"] is False
    assert c.ledger.read_bytes() == before


@pytest.mark.parametrize("field,value", [
    ("validation_request_sha256", "e" * 64),
    ("scheduler_lane", "hammer_lean"),
    ("workload", "unrelated"),
    ("status", "reserved"),
    ("native_lease_id", "not-a-native-id"),
    ("native_lease_id", None),
    ("scheduler_policy_sha256", "bad"),
    ("scheduler_state_path", "relative-scheduler"),
    ("owner_birth", True),
    ("process_scope", "unbounded"),
    ("outputs", {}),
    ("prior_children", [{"pid": 123, "birth": "1"}]),
    ("child", {"pid": True, "birth": "1"}),
    ("artifacts_durable_asserted", "true"),
])
def test_mismatched_or_malformed_recorded_custody_is_refused(inspection, field, value):
    c = inspection
    c.row[field] = value
    c.write()
    before = c.ledger.read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError):
        recovery.inspect_validation_reservation(c.ledger, **c.args)
    assert c.ledger.read_bytes() == before


def test_changed_physical_attempt_cannot_reuse_recorded_binding(inspection):
    c = inspection
    c.row["attempt_directory"]["inode"] += 1
    c.write()
    before = c.ledger.read_bytes()
    with pytest.raises(recovery.resources.DaemonResourceError, match="binding differs"):
        recovery.inspect_validation_reservation(c.ledger, **c.args)
    assert c.ledger.read_bytes() == before


@pytest.mark.parametrize("field,value", [
    ("reservation_id", ""), ("reservation_id", "A" * 32),
    ("expected_request_sha256", ""), ("expected_request_sha256", True),
    ("ledger_lock_timeout_seconds", True), ("ledger_lock_timeout_seconds", float("nan")),
    ("ledger_lock_timeout_seconds", 31), ("attempt_directory", "relative"),
    ("roots", []),
])
def test_invalid_scalar_inputs_fail_before_any_helper_or_state_access(monkeypatch, field, value):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid scalar input reached the resource helper")
    monkeypatch.setattr(recovery.resources, "DaemonResourceReservation", forbidden)
    args = dict(roots=["/not-opened"], reservation_id=RID, expected_request_sha256=REQUEST,
                attempt_directory="/not-opened/attempt", ledger_lock_timeout_seconds=0)
    args[field] = value
    with pytest.raises(recovery.resources.DaemonResourceError):
        recovery.inspect_validation_reservation("/not-opened/ledger", **args)


def test_inspection_never_writes_admits_recovers_opens_scheduler_or_counts_processes(inspection, monkeypatch):
    c = inspection
    def forbidden(*args, **kwargs):
        pytest.fail("read-only inspection invoked a forbidden operation")
    for name in ("__enter__", "_write", "_account", "_acquire_native_lease", "_locked"):
        monkeypatch.setattr(recovery.resources.DaemonResourceReservation, name, forbidden)
    for name in ("get_global_resource_scheduler", "_inventory", "_process", "_group_usage"):
        monkeypatch.setattr(recovery.resources, name, forbidden)
    monkeypatch.setattr(recovery, "reconcile_retained_reservation", forbidden)
    monkeypatch.setattr(recovery, "_durable_inventory", forbidden)
    monkeypatch.setattr(recovery, "_administrative_census", forbidden)
    real_open = os.open
    flags_seen = []
    def bounded_open(path, flags, *args, **kwargs):
        assert Path(path) in (c.ledger, c.lock)
        assert flags & os.O_NOFOLLOW
        assert not flags & (os.O_CREAT | os.O_TRUNC | os.O_WRONLY | os.O_RDWR)
        flags_seen.append(flags)
        return real_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(os, "open", bounded_open)
    before = c.ledger.read_bytes()
    result = recovery.inspect_validation_reservation(c.ledger, **c.args)
    assert result["binding_verified"] and len(flags_seen) == 2
    assert c.ledger.read_bytes() == before
    assert not Path(c.row["scheduler_state_path"]).exists()


def test_returned_nested_values_are_detached_from_storage(inspection):
    c = inspection
    before = c.ledger.read_bytes()
    result = recovery.inspect_validation_reservation(c.ledger, **c.args)
    result["custody"]["child"]["pid"] = 1
    result["custody"]["outputs"]["logs"] = "changed"
    result["attempt_directory"]["inode"] = 0
    result["roots"][0]["inode"] = 0
    fresh = recovery.inspect_validation_reservation(c.ledger, **c.args)
    assert fresh["custody"]["child"] == c.row["child"]
    assert fresh["attempt_directory"] == c.row["attempt_directory"]
    assert fresh["roots"] == c.data["roots"]
    assert c.ledger.read_bytes() == before


@pytest.mark.parametrize("which", ["ledger", "lock"])
def test_missing_existing_state_is_not_initialized(inspection, which):
    c = inspection
    target = getattr(c, which)
    target.unlink()
    with pytest.raises(recovery.resources.DaemonResourceError, match="missing resource path"):
        recovery.inspect_validation_reservation(c.ledger, **c.args)
    assert not target.exists()


def test_lock_disappearing_between_precheck_and_open_is_never_recreated(inspection, monkeypatch):
    c = inspection
    before = c.ledger.read_bytes()
    real_open = os.open
    def disappear(path, flags, *args, **kwargs):
        if Path(path) == c.lock:
            c.lock.unlink()
            assert not flags & os.O_CREAT
        return real_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(os, "open", disappear)
    with pytest.raises(FileNotFoundError):
        recovery.inspect_validation_reservation(c.ledger, **c.args)
    assert not c.lock.exists() and c.ledger.read_bytes() == before


def test_existing_lock_contention_has_bounded_refusal_without_state_change(inspection):
    c = inspection
    before = c.ledger.read_bytes()
    with c.lock.open("rb") as held:
        recovery.resources.fcntl.flock(held.fileno(), recovery.resources.fcntl.LOCK_EX | recovery.resources.fcntl.LOCK_NB)
        with pytest.raises(recovery.resources.DaemonResourceError, match="lock unavailable"):
            recovery.inspect_validation_reservation(c.ledger, **c.args)
    assert c.ledger.read_bytes() == before


@pytest.mark.parametrize("which,kind", [
    ("ledger", "symlink"), ("lock", "symlink"), ("ledger", "fifo"),
    ("ledger", "hardlink"), ("lock", "hardlink"),
])
def test_synthetic_alias_metadata_refuses_without_creating_real_aliases(inspection, monkeypatch, which, kind):
    c = inspection
    target = getattr(c, which)
    before = c.ledger.read_bytes()
    if kind in {"symlink", "fifo"}:
        original = Path.lstat
        def synthetic(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            if path == target:
                values = list(info)
                values[0] = stat.S_IFLNK if kind == "symlink" else stat.S_IFIFO
                return os.stat_result(values)
            return info
        monkeypatch.setattr(Path, "lstat", synthetic)
    else:
        original = os.fstat
        selected = target.stat()
        def synthetic(fd):
            info = original(fd)
            if (info.st_dev, info.st_ino) == (selected.st_dev, selected.st_ino):
                values = list(info)
                values[3] = 2
                return os.stat_result(values)
            return info
        monkeypatch.setattr(os, "fstat", synthetic)
    with pytest.raises(recovery.resources.DaemonResourceError):
        recovery.inspect_validation_reservation(c.ledger, **c.args)
    assert c.ledger.read_bytes() == before


def test_synthetic_nofollow_open_error_cannot_create_or_follow_lock_alias(inspection, monkeypatch):
    c = inspection
    real_open = os.open
    def alias_error(path, flags, *args, **kwargs):
        if Path(path) == c.lock:
            assert flags & os.O_NOFOLLOW and not flags & os.O_CREAT
            raise OSError(errno.ELOOP, "synthetic alias race")
        return real_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(os, "open", alias_error)
    before = c.ledger.read_bytes()
    with pytest.raises(OSError, match="synthetic alias"):
        recovery.inspect_validation_reservation(c.ledger, **c.args)
    assert c.ledger.read_bytes() == before


def test_existing_owner_byte_bound_is_preserved(inspection, monkeypatch):
    c = inspection
    before = c.ledger.read_bytes()
    monkeypatch.setattr(recovery.resources, "MAX_LEDGER_BYTES", len(before) - 1)
    with pytest.raises(recovery.resources.DaemonResourceError, match="invalid disk ledger file"):
        recovery.inspect_validation_reservation(c.ledger, **c.args)
    assert c.ledger.read_bytes() == before


def test_duplicate_json_members_are_refused_without_normalization(inspection):
    c = inspection
    before = c.ledger.read_text().replace('"status": "retained"', '"status": "active", "status": "retained"')
    c.ledger.write_text(before)
    with pytest.raises(recovery.resources.DaemonResourceError):
        recovery.inspect_validation_reservation(c.ledger, **c.args)
    assert c.ledger.read_text() == before
