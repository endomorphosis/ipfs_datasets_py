"""Explicit, idle-only expansion of an existing 200 GB disk ledger to 220 GB.

The default is a read-only plan. No reservation object is constructed, no
scheduler lease is acquired, and no retained record is released or rewritten.
Applying requires a separately qualified 220 GB producer and an exact old-byte
preimage. The existing disk lock is taken before the native scheduler lock,
matching parented native admission's nested order. Both remain held through
the exact-byte backup, final census, atomic replacement and durable readback.

The filesystem census is cooperative and point-in-time, not an atomic global
snapshot. A successful migration grants no workload admission. Any error once
replacement is attempted requires inspecting durable state; do not blindly
retry or claim rollback. All paths and scheduler state must already exist.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import time
import uuid

from . import autoencoder_daemon_resources as resources
from . import existing_resource_scheduler as existing
from . import resource_scheduler as native
from . import proof_resource_safety as proof
from . import runtime_telemetry as telemetry

PREVIOUS_LIMIT_BYTES = 200_000_000_000
TARGET_LIMIT_BYTES = 220_000_000_000
MAX_SOURCE_BYTES = 4 * 1024 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_CHARGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,127}\Z")


class StorageCapacityExpansionError(resources.DaemonResourceError):
    """An exact administrative migration precondition was not established."""


class StorageCapacityWriteOutcomeUnknown(StorageCapacityExpansionError):
    """Replacement may have happened; inspect the ledger and exact backup."""

    def __init__(self, previous_sha256, successor_sha256, backup_path):
        super().__init__("storage_capacity_write_outcome_requires_durable_inspection")
        self.previous_ledger_sha256 = previous_sha256
        self.successor_ledger_sha256 = successor_sha256
        self.backup_path = str(backup_path)
        self.may_have_applied = True


def _need(condition, reason):
    if not condition:
        raise StorageCapacityExpansionError(reason)


def _integer(value, reason, *, minimum=1, maximum=(1 << 63) - 1):
    _need(type(value) is int and minimum <= value <= maximum, reason)
    return value


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _path(value):
    _need(isinstance(value, (str, Path)), "storage_capacity_path_type")
    text = os.fspath(value)
    _need(type(text) is str and text.startswith("/") and "\x00" not in text
          and len(os.fsencode(text)) <= 4096 and str(Path(text)) == text
          and ".." not in Path(text).parts, "storage_capacity_canonical_absolute_path")
    return Path(text)


def _directory_identity(info):
    return (info.st_dev, info.st_ino, info.st_uid, info.st_mode)


def _file_identity(info):
    return (info.st_dev, info.st_ino, info.st_uid, info.st_gid, info.st_mode,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


@contextmanager
def _directory(path):
    """Hold no-follow ancestors; refuse changed named identities on exit."""
    path = _path(path)
    descriptors, anchors = [], []
    try:
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(fd)
        anchors.append((Path("/"), _directory_identity(os.fstat(fd))))
        named = Path("/")
        for component in path.parts[1:]:
            before = os.stat(component, dir_fd=fd, follow_symlinks=False)
            _need(stat.S_ISDIR(before.st_mode), "storage_capacity_parent_not_directory")
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=fd)
            descriptors.append(child)
            _need(_directory_identity(os.fstat(child)) == _directory_identity(before),
                  "storage_capacity_parent_changed")
            fd = child
            named = named / component
            anchors.append((named, _directory_identity(before)))
        yield fd
        _need(all(_directory_identity(named.lstat()) == identity
                  for named, identity in anchors), "storage_capacity_parent_changed")
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def _read_file(path, maximum, *, source=False):
    path = _path(path)
    with _directory(path.parent) as parent:
        before = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
              and before.st_uid in ({0, os.geteuid()} if source else {os.geteuid()})
              and not before.st_mode & 0o022 and 0 < before.st_size <= maximum,
              "storage_capacity_unaliased_bounded_file_required")
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=parent)
        with os.fdopen(fd, "rb") as stream:
            opened = os.fstat(stream.fileno())
            _need(_file_identity(opened) == _file_identity(before),
                  "storage_capacity_file_changed")
            raw = stream.read(maximum + 1)
            after = os.fstat(stream.fileno())
        named = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        _need(len(raw) == before.st_size and _file_identity(after) == _file_identity(before)
              and _file_identity(named) == _file_identity(before),
              "storage_capacity_file_changed")
    return raw, _file_identity(before)


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        _need(key not in value, "storage_capacity_duplicate_json_field")
        value[key] = item
    return value


def _finite_float(text):
    value = float(text)
    _need(math.isfinite(value), "storage_capacity_nonfinite_json")
    return value


def _decode(raw):
    try:
        value = json.loads(raw, object_pairs_hook=_pairs, parse_float=_finite_float,
            parse_constant=lambda _: (_ for _ in ()).throw(
                StorageCapacityExpansionError("storage_capacity_nonfinite_json")))
    except (ValueError, UnicodeError, RecursionError) as error:
        raise StorageCapacityExpansionError("storage_capacity_invalid_json") from error
    pending, nodes = [(value, 0)], 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        _need(nodes <= 500_000 and depth <= 128, "storage_capacity_json_structure_bound")
        if type(item) is dict:
            pending.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
    return value


def _roots(values):
    _need(type(values) in (list, tuple) and 1 <= len(values) <= 64,
          "storage_capacity_root_inventory")
    paths = [_path(value) for value in values]
    for index, path in enumerate(paths):
        _need(not any(path == other or path in other.parents or other in path.parents
                      for other in paths[:index]), "storage_capacity_overlapping_roots")
    identities = []
    for path in paths:
        with _directory(path) as fd:
            info = os.fstat(fd)
            identities.append({"path": str(path), "device": info.st_dev, "inode": info.st_ino})
    return paths, identities


def _child(value, *, historical=False):
    if value is None:
        return
    allowed = ({"pid", "birth"}, {"pid", "birth", "group_observed_dead_at"}) if historical else ({"pid", "birth"},)
    _need(type(value) is dict and set(value) in allowed,
          "storage_capacity_child_identity")
    _integer(value["pid"], "storage_capacity_child_pid")
    _need(type(value["birth"]) is str and value["birth"].isascii()
          and value["birth"].isdigit() and int(value["birth"]) > 0,
          "storage_capacity_child_birth")
    if "group_observed_dead_at" in value:
        observed = value["group_observed_dead_at"]
        _need(type(observed) in (int, float) and math.isfinite(observed) and observed >= 0,
              "storage_capacity_historical_child_observation")


def _ledger(raw, identities, limit):
    """Native v1 required row constraints, at the explicit previous cap.

    Additional historical record fields are preserved without reinterpretation.
    Optional child identities are checked before calling the native group reader.
    This is not the normal reservation reader and never silently upgrades it.
    """
    value = _decode(raw)
    _need(type(value) is dict and set(value) == {"schema", "roots", "limit_bytes", "reservations"}
          and value["schema"] == resources.SCHEMA and value["roots"] == identities
          and type(value["limit_bytes"]) is int and value["limit_bytes"] == limit,
          "storage_capacity_ledger_scope")
    _need(type(value["roots"]) is list and all(type(row) is dict
          and set(row) == {"path", "device", "inode"} and type(row["path"]) is str
          and type(row["device"]) is int and row["device"] >= 0
          and type(row["inode"]) is int and row["inode"] > 0 for row in value["roots"]),
          "storage_capacity_typed_root_identity")
    rows = value["reservations"]
    _need(type(rows) is dict and len(rows) <= resources.MAX_RESERVATIONS,
          "storage_capacity_reservation_inventory")
    for key, row in rows.items():
        _need(type(key) is str and bool(key) and type(row) is dict
              and row.get("reservation_id") == key and type(row.get("status")) is str
              and row["status"] in {"reserved", "active", "retained", "released"},
              "storage_capacity_reservation_record")
        _integer(row.get("storage_bytes"), "storage_capacity_record_storage", maximum=limit)
        _integer(row.get("owner_pid"), "storage_capacity_record_owner")
        if "child_process_slots" in row:
            _integer(row["child_process_slots"], "storage_capacity_record_process_slots")
        charges = row.get("external_charges", {})
        _need(type(charges) is dict and len(charges) <= resources.MAX_EXTERNAL_CHARGES,
              "storage_capacity_external_inventory")
        for charge, amount in charges.items():
            _need(type(charge) is str and _CHARGE.fullmatch(charge),
                  "storage_capacity_external_key")
            _integer(amount, "storage_capacity_external_bytes", minimum=0, maximum=limit)
        _child(row.get("child"))
        children = row.get("prior_children", [])
        _need(type(children) is list and len(children) <= resources.MAX_CHILDREN_PER_RESERVATION,
              "storage_capacity_prior_children")
        for child in children:
            _child(child, historical=True)
    return value


def _sources(expected):
    modules = (resources, existing, native, proof, telemetry)
    required = {_path(__file__), *(_path(module.__file__) for module in modules)}
    _need(type(expected) is list and len(expected) == len(required),
          "storage_capacity_exact_source_pins")
    seen = set()
    for pin in expected:
        _need(type(pin) is dict and set(pin) == {"path", "bytes", "sha256"},
              "storage_capacity_source_pin_shape")
        path = _path(pin["path"])
        _need(path in required and path not in seen, "storage_capacity_source_inventory")
        seen.add(path)
        _integer(pin["bytes"], "storage_capacity_source_size", maximum=MAX_SOURCE_BYTES)
        _need(type(pin["sha256"]) is str and _SHA.fullmatch(pin["sha256"]),
              "storage_capacity_source_sha256")
        raw, _ = _read_file(path, MAX_SOURCE_BYTES, source=True)
        _need(len(raw) == pin["bytes"] and hashlib.sha256(raw).hexdigest() == pin["sha256"],
              "storage_capacity_source_changed")
    _need(seen == required, "storage_capacity_exact_source_pins")


def _idle(state):
    _need(not state["leases"] and not state["waiters"] and not state.get("proof_recovery"),
          "storage_capacity_idle_scheduler_required")
    backoff = state.get("proof_backoff", {})
    _need(type(backoff) is dict, "storage_capacity_backoff_shape")
    if backoff:
        until = backoff.get("until")
        _need(type(until) in (int, float) and math.isfinite(until) and until >= 0,
              "storage_capacity_backoff_deadline")
        _need(until <= time.time(), "storage_capacity_active_backoff")


def _retired(ledger):
    owners, groups = set(), {}
    for row in ledger["reservations"].values():
        if row["status"] == "released":
            continue
        owners.add(row["owner_pid"])
        for child in [row.get("child"), *row.get("prior_children", [])]:
            if child is not None:
                key = (child["pid"], child["birth"])
                groups[key] = {"pid": child["pid"], "birth": child["birth"]}
    for owner in sorted(owners):
        _need(resources._process(owner) is None, "storage_capacity_original_owner_present")
    for key in sorted(groups):
        usage = resources._group_usage(groups[key])
        _need(usage.get("available") is True and usage["live_processes"] == 0,
              "storage_capacity_original_group_present")


def _census(paths, ledger, new_limit):
    inventory = resources._inventory(paths)
    observed = _integer(inventory["apparent_bytes"], "storage_capacity_inventory_bytes", minimum=0)
    outstanding = sum(row["storage_bytes"] for row in ledger["reservations"].values()
                      if row["status"] != "released")
    free = min(resources.shutil.disk_usage(root).free for root in paths)
    _integer(free, "storage_capacity_filesystem_free", minimum=0)
    _need(observed + outstanding <= new_limit, "storage_capacity_target_insufficient")
    _need(free >= outstanding, "storage_capacity_filesystem_free_insufficient")
    return {"observed_apparent_bytes": observed,
        "outstanding_full_reservations_bytes": outstanding, "additional_requested_bytes": 0,
        "charged_bytes": observed + outstanding, "limit_bytes": new_limit,
        "minimum_filesystem_free_bytes": free, "inventory": deepcopy(inventory),
        "scope": "named_roots_only_apparent_bytes", "admitted": False}


@contextmanager
def _disk_lock(path):
    lock = path.with_name(path.name + ".lock")
    with _directory(lock.parent) as parent:
        before = os.stat(lock.name, dir_fd=parent, follow_symlinks=False)
        _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
              and before.st_uid == os.geteuid() and not before.st_mode & 0o022,
              "storage_capacity_existing_lock_required")
        fd = os.open(lock.name, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            _need(_file_identity(os.fstat(fd)) == _file_identity(before),
                  "storage_capacity_lock_changed")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise StorageCapacityExpansionError("storage_capacity_disk_lock_busy") from error
            _need(_file_identity(os.stat(lock.name, dir_fd=parent, follow_symlinks=False))
                  == _file_identity(before), "storage_capacity_lock_changed")
            yield
            _need(_file_identity(os.stat(lock.name, dir_fd=parent, follow_symlinks=False))
                  == _file_identity(before), "storage_capacity_lock_changed")
        finally:
            os.close(fd)


def _backup(path, raw):
    with _directory(path.parent) as parent:
        fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=parent)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(parent)
    actual, _ = _read_file(path, resources.MAX_LEDGER_BYTES)
    _need(actual == raw, "storage_capacity_backup_differs")
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _replace(path, raw, outcome):
    temporary = ".storage-capacity-" + uuid.uuid4().hex + ".tmp"
    with _directory(path.parent) as parent:
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=parent)
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            outcome["attempted"] = True
            os.replace(temporary, path.name, src_dir_fd=parent, dst_dir_fd=parent)
            os.fsync(parent)
        finally:
            try:
                os.unlink(temporary, dir_fd=parent)
            except FileNotFoundError:
                pass


def expand_storage_capacity(ledger_path, *, roots, expected_ledger_sha256,
        previous_limit_bytes, new_limit_bytes, scheduler_state_path,
        expected_scheduler_policy_sha256, expected_source_pins,
        backup_path=None, apply=False):
    """Plan, or explicitly apply, the reviewed 200-to-220 GB transition.

    ``expected_source_pins`` is an exact six-element list of closed
    ``{path, bytes, sha256}`` pins for this module, daemon resources, existing
    scheduler, native scheduler, proof resources and runtime telemetry.
    Apply requires an explicitly named, unused sibling backup. All metadata
    files/roots and both native sibling locks must already exist. The plan
    refuses live scheduler activity too; it never recovers stale state.
    The returned successor hash is a prediction until a durable apply succeeds.
    """
    _need(type(apply) is bool, "storage_capacity_explicit_apply_bool")
    _need(type(previous_limit_bytes) is int and previous_limit_bytes == PREVIOUS_LIMIT_BYTES
          and type(new_limit_bytes) is int and new_limit_bytes == TARGET_LIMIT_BYTES,
          "storage_capacity_reviewed_transition_required")
    _need(type(expected_ledger_sha256) is str and _SHA.fullmatch(expected_ledger_sha256),
          "storage_capacity_exact_ledger_sha256")
    path, scheduler_path = _path(ledger_path), _path(scheduler_state_path)
    _need(len({path, path.with_name(path.name + ".lock"), scheduler_path,
               scheduler_path.with_name(scheduler_path.name + ".lock")}) == 4,
          "storage_capacity_distinct_control_paths")
    backup = None if backup_path is None else _path(backup_path)
    _need(not apply or backup is not None, "storage_capacity_explicit_backup_required")
    if backup is not None:
        _need(backup.parent == path.parent and backup not in {
            path, path.with_name(path.name + ".lock"), scheduler_path,
            scheduler_path.with_name(scheduler_path.name + ".lock")},
            "storage_capacity_unused_sibling_backup_required")
    _sources(expected_source_pins)
    expected_source_pins = deepcopy(expected_source_pins)
    backend_ready = type(resources.MAX_STORAGE_BYTES) is int and resources.MAX_STORAGE_BYTES == new_limit_bytes
    _need(not apply or backend_ready, "storage_capacity_target_backend_required")
    paths, identities = _roots(roots)
    # The genuine public facade validates the stored typed policy. Opening it
    # creates no resource allocation and does not reconfigure any policy.
    # Require its sibling lock before opening so even planning creates no file.
    scheduler_lock = scheduler_path.with_name(scheduler_path.name + ".lock")
    lock_info = scheduler_lock.lstat()
    _need(stat.S_ISREG(lock_info.st_mode) and lock_info.st_nlink == 1
          and lock_info.st_uid == os.geteuid() and lock_info.st_gid == os.getegid()
          and not lock_info.st_mode & 0o002,
          "storage_capacity_existing_scheduler_lock_required")
    facade = existing.open_existing_scheduler(scheduler_path, expected_scheduler_policy_sha256)
    outcome = {"attempted": False}
    # The outcome guard exits after both lock contexts, including their final
    # identity checks, so a late error cannot be mistaken for a rollback.
    # The successor digest is filled only after the exact old ledger is read.
    outcome_digests = {"successor": None}
    @contextmanager
    def guarded_write_outcome():
        try:
            yield
        except BaseException as error:
            if outcome["attempted"]:
                raise StorageCapacityWriteOutcomeUnknown(expected_ledger_sha256,
                    outcome_digests["successor"], backup) from error
            raise
    with guarded_write_outcome(), _disk_lock(path):
        with facade._locked_state(persist=False) as scheduler_state:
            _idle(scheduler_state)
            scheduler_raw, scheduler_current = existing._read(scheduler_path)
            _need(scheduler_current == scheduler_state, "storage_capacity_scheduler_changed")
            original_raw, original_identity = _read_file(path, resources.MAX_LEDGER_BYTES)
            _need(hashlib.sha256(original_raw).hexdigest() == expected_ledger_sha256,
                  "storage_capacity_ledger_preimage_changed")
            ledger = _ledger(original_raw, identities, previous_limit_bytes)
            original_decoded_sha256 = _digest(ledger)
            preserved = {key: deepcopy(value) for key, value in ledger.items() if key != "limit_bytes"}
            successor = deepcopy(ledger)
            successor["limit_bytes"] = new_limit_bytes
            successor_raw = _canonical(successor) + b"\n"
            outcome_digests["successor"] = hashlib.sha256(successor_raw).hexdigest()
            _need(len(successor_raw) <= resources.MAX_LEDGER_BYTES, "storage_capacity_successor_byte_bound")

            def unchanged():
                _sources(expected_source_pins)
                _need(_digest(ledger) == original_decoded_sha256,
                      "storage_capacity_in_memory_ledger_changed")
                _need(not apply or resources.MAX_STORAGE_BYTES == new_limit_bytes,
                      "storage_capacity_target_backend_changed")
                _need(_roots(paths)[1] == identities, "storage_capacity_roots_changed")
                current_raw, current_identity = _read_file(path, resources.MAX_LEDGER_BYTES)
                _need(current_raw == original_raw and current_identity == original_identity,
                      "storage_capacity_ledger_changed_outside_lock")
                current_scheduler_raw, current_scheduler = existing._read(scheduler_path)
                _need(current_scheduler_raw == scheduler_raw and current_scheduler == scheduler_state,
                      "storage_capacity_scheduler_changed_outside_lock")
                _idle(current_scheduler)
                _retired(ledger)

            unchanged()
            first = _census(paths, ledger, new_limit_bytes)
            unchanged()
            backup_pin = _backup(backup, original_raw) if apply else None
            unchanged()
            final = _census(paths, ledger, new_limit_bytes)
            unchanged()
            _need({key: value for key, value in successor.items() if key != "limit_bytes"} == preserved,
                  "storage_capacity_preserved_state_changed")
            report = {"schema": "explicit-idle-disk-capacity-expansion/v1", "applied": False,
                "status": "ready_explicit_apply" if backend_ready else "plan_requires_target_backend",
                "previous_limit_bytes": previous_limit_bytes, "new_limit_bytes": new_limit_bytes,
                "target_backend_aligned": backend_ready, "previous_ledger_sha256": expected_ledger_sha256,
                "successor_ledger_sha256": hashlib.sha256(successor_raw).hexdigest(),
                "preserved_state_sha256": _digest(preserved), "reservation_count": len(ledger["reservations"]),
                "roots": deepcopy(identities), "scheduler_policy_sha256": expected_scheduler_policy_sha256,
                "scheduler_state_sha256": hashlib.sha256(scheduler_raw.encode()).hexdigest(),
                "initial_accounting": first, "final_prewrite_accounting": final,
                "fresh_global_inventory_count": 2, "backup_pin": backup_pin,
                "source_pins": deepcopy(expected_source_pins), "admitted": False,
                "new_reservation_created": False, "new_resource_lease_acquired": False,
                "reservation_records_changed": False, "scheduler_state_changed": False,
                "outputs_deleted": False, "atomic_global_snapshot": False,
                "continuous_custody_proved": False, "actual_postwrite_capacity_census_required": bool(apply)}
            if apply:
                _replace(path, successor_raw, outcome)
                written_raw, _ = _read_file(path, resources.MAX_LEDGER_BYTES)
                written = _ledger(written_raw, identities, new_limit_bytes)
                _need(written_raw == successor_raw and written == successor,
                      "storage_capacity_successor_readback_differs")
                _sources(expected_source_pins)
                _need(_roots(paths)[1] == identities and existing._read(scheduler_path)[0] == scheduler_raw,
                      "storage_capacity_postwrite_control_changed")
                report.update(applied=True, status="applied_requires_fresh_capacity_observation")
            return report


__all__ = ["expand_storage_capacity", "StorageCapacityExpansionError",
           "StorageCapacityWriteOutcomeUnknown"]
