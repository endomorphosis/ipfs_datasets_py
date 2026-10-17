"""Bounded, lossless administrative archival of released ledger metadata.

Pure planning/restoration imports only stdlib. The public effectful operation
requires genuine same-process native ORCHESTRATION root/phase leases. It is a
dedicated lock-held administrative admission, not a ParentedPhase reservation.
Nothing here publishes the private snapshot or changes native/storage caps.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import time
import uuid

SCHEMA = "released-reconciliation-archival/v1"
POINTER_SCHEMA = "released-reconciliation-archive-pointer/v1"
LEDGER_SCHEMA = "daemon-resource-reservations-v1"
MAX_LEDGER_BYTES = 8 * 1024 * 1024
MAX_ROWS = 8
MAX_JOURNAL_BYTES = 1024 * 1024
MAX_STORAGE_BYTES = 160_000_000_000
DEFAULT_PEAK_BYTES = 32 * 1024 * 1024
SELECTION_FIELDS = {"reservation_id", "expected_record_sha256", "expected_reconciliation_sha256",
                    "expected_owner_pid", "expected_attempt_path"}
POINTER_FIELDS = {"schema", "snapshot_path", "snapshot_sha256", "reservation_id",
                  "original_record_sha256", "original_field_sha256"}


class ArchivalRefusal(RuntimeError):
    pass


def need(condition, message):
    if not condition:
        raise ArchivalRefusal(message)


def wire(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    # Match the existing recovery SDK's canonical record hashing (no LF).
    return sha(wire(value)[:-1])


def decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            need(key not in result, "duplicate JSON field")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ArchivalRefusal("nonfinite JSON value")))


def absolute(spelling):
    need(type(spelling) is str and spelling.startswith("/") and "\x00" not in spelling,
         "absolute canonical path required")
    need(str(PurePosixPath(spelling)) == spelling and ".." not in PurePosixPath(spelling).parts,
         "absolute canonical path required")
    return Path(spelling)


def plan_reconciliation_archival(raw, *, selections, snapshot_path, administration_record):
    """Pure transform. No lease, file, scheduler or storage admission is implied."""
    need(type(raw) is bytes and 0 < len(raw) <= MAX_LEDGER_BYTES, "bounded original ledger required")
    absolute(snapshot_path)
    ledger = decode(raw)
    need(type(ledger) is dict and set(ledger) == {"schema", "roots", "limit_bytes", "reservations"}
         and ledger["schema"] == LEDGER_SCHEMA and ledger["limit_bytes"] == MAX_STORAGE_BYTES,
         "exact original ledger schema and cap required")
    rows = ledger["reservations"]
    need(type(rows) is dict and len(rows) < 4096, "bounded ledger population required")
    need(type(selections) is list and 0 < len(selections) <= MAX_ROWS, "bounded explicit selection required")
    selected = set()
    projected = copy.deepcopy(ledger)
    pointers = {}
    for selection in selections:
        need(type(selection) is dict and set(selection) == SELECTION_FIELDS, "exact selection schema required")
        identifier = selection["reservation_id"]
        need(type(identifier) is str and re.fullmatch(r"[0-9a-f]{32}", identifier) is not None
             and identifier not in selected, "unique reservation ID required")
        selected.add(identifier)
        row = rows.get(identifier)
        need(type(row) is dict and row.get("reservation_id") == identifier and row.get("status") == "released"
             and row.get("artifacts_durable_asserted") is True, "only durable released rows may be archived")
        need(row.get("owner_pid") == selection["expected_owner_pid"] and type(selection["expected_owner_pid"]) is int,
             "selected owner identity differs")
        attempt = row.get("attempt_directory")
        need(type(attempt) is dict and attempt.get("path") == str(absolute(selection["expected_attempt_path"])),
             "selected attempt identity differs")
        need(digest(row) == selection["expected_record_sha256"], "selected full record hash differs")
        field = row.get("explicit_reconciliation")
        need(type(field) is dict and field and field.get("schema") != POINTER_SCHEMA,
             "unarchived explicit reconciliation required")
        need(digest(field) == selection["expected_reconciliation_sha256"], "selected reconciliation hash differs")
        pointer = {"schema": POINTER_SCHEMA, "snapshot_path": snapshot_path, "snapshot_sha256": sha(raw),
                   "reservation_id": identifier, "original_record_sha256": digest(row),
                   "original_field_sha256": digest(field)}
        projected["reservations"][identifier]["explicit_reconciliation"] = pointer
        pointers[identifier] = pointer
    need(type(administration_record) is dict and administration_record.get("status") == "released"
         and administration_record.get("artifacts_durable_asserted") is True
         and administration_record.get("workload") == "canonical_resource_ledger_archival",
         "completed administrative archival record required")
    for name, maximum in (("owner_pid", None), ("storage_bytes", MAX_STORAGE_BYTES),
                          ("memory_mb", None), ("cpu_slots", None), ("child_process_slots", None)):
        value = administration_record.get(name)
        need(type(value) is int and value >= 1 and (maximum is None or value <= maximum),
             "valid administrative native/accounting fields required")
    need(administration_record.get("scheduler_lane") == "orchestration"
         and administration_record.get("child") is None and administration_record.get("prior_children") == []
         and administration_record.get("external_charges") == {}
         and type(administration_record.get("last_usage")) is dict
         and type(administration_record.get("archival")) is dict
         and all(type(administration_record.get(name)) is str and administration_record[name]
                 for name in ("native_lease_id", "parent_lease_id", "scheduler_state_path", "scheduler_policy_sha256")),
         "valid administrative native/accounting fields required")
    attempt = administration_record.get("attempt_directory")
    need(type(attempt) is dict and set(attempt) == {"path", "device", "inode"}
         and type(attempt["device"]) is int and attempt["device"] >= 0
         and type(attempt["inode"]) is int and attempt["inode"] > 0,
         "valid administrative attempt identity required")
    absolute(attempt["path"])
    admin_id = administration_record.get("reservation_id")
    need(type(admin_id) is str and re.fullmatch(r"[0-9a-f]{32}", admin_id) is not None and admin_id not in rows,
         "fresh administrative archival identity required")
    projected["reservations"][admin_id] = copy.deepcopy(administration_record)
    output = wire(projected)
    need(len(output) <= MAX_LEDGER_BYTES and len(raw) - len(output) >= 64 * 1024,
         "archival must recover at least64KiB of ledger headroom")
    # Reconstruction authenticates the exact original full record, not merely
    # an archive path or a selected field hash supplied by a caller.
    for identifier in selected:
        need(restore_archived_record(raw, projected["reservations"][identifier]) == rows[identifier],
             "lossless record reconstruction failed")
    return {"ledger": projected, "ledger_bytes": output, "snapshot_bytes": raw,
            "pointers": pointers, "administration_id": admin_id,
            "reclaimed_ledger_bytes": len(raw) - len(output)}


def restore_archived_record(snapshot_raw, folded_record):
    """Pure, exact original-record recovery; never trusts a pointer alone."""
    need(type(snapshot_raw) is bytes and 0 < len(snapshot_raw) <= MAX_LEDGER_BYTES,
         "bounded original snapshot required")
    pointer = folded_record.get("explicit_reconciliation")
    need(type(pointer) is dict and set(pointer) == POINTER_FIELDS and pointer["schema"] == POINTER_SCHEMA,
         "exact archival pointer required")
    absolute(pointer["snapshot_path"])
    need(sha(snapshot_raw) == pointer["snapshot_sha256"], "snapshot content hash differs")
    original = decode(snapshot_raw)["reservations"].get(pointer["reservation_id"])
    need(type(original) is dict and original.get("status") == "released"
         and original.get("reservation_id") == folded_record.get("reservation_id")
         and digest(original) == pointer["original_record_sha256"]
         and digest(original.get("explicit_reconciliation")) == pointer["original_field_sha256"],
         "original archived record hash differs")
    rebuilt = copy.deepcopy(folded_record)
    rebuilt["explicit_reconciliation"] = copy.deepcopy(original["explicit_reconciliation"])
    need(rebuilt == original, "non-reconciliation record fields changed")
    return rebuilt


def required_peak_bytes(snapshot_bytes, projected_ledger_bytes):
    """Snapshot + bounded intent/completion journals + atomic temp + dirs."""
    need(type(snapshot_bytes) is int and 0 < snapshot_bytes <= MAX_LEDGER_BYTES
         and type(projected_ledger_bytes) is int and 0 < projected_ledger_bytes <= MAX_LEDGER_BYTES,
         "bounded archival size inputs required")
    return snapshot_bytes + projected_ledger_bytes + 2 * MAX_JOURNAL_BYTES + 65536


def check_capacity_precharge(observation, additional_bytes):
    """Pure check of the genuine SDK census projection; grants nothing."""
    names = ("observed_apparent_bytes", "outstanding_full_reservations_bytes", "additional_requested_bytes",
             "charged_bytes", "limit_bytes", "minimum_filesystem_free_bytes")
    need(type(observation) is dict and all(type(observation.get(n)) is int and observation[n] >= 0 for n in names)
         and type(additional_bytes) is int and additional_bytes > 0,
         "valid capacity projection required")
    need(observation["limit_bytes"] == MAX_STORAGE_BYTES
         and observation["additional_requested_bytes"] == additional_bytes
         and observation["charged_bytes"] == observation["observed_apparent_bytes"]
             + observation["outstanding_full_reservations_bytes"] + additional_bytes,
         "capacity projection or cap differs")
    need(observation["charged_bytes"] <= MAX_STORAGE_BYTES
         and observation["minimum_filesystem_free_bytes"] >= observation["outstanding_full_reservations_bytes"] + additional_bytes,
         "capacity precharge does not fit")
    return True


def _read_regular(path, maximum):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_uid == os.geteuid()
             and not stat.S_IMODE(before.st_mode) & 0o022 and before.st_size <= maximum,
             "owned unaliased bounded regular metadata required")
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    witness = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    need(witness(before) == witness(after) == witness(path.lstat()) and len(raw) == before.st_size,
         "metadata changed while reading")
    return raw


def _fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_new(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    _fsync_dir(path.parent)


def archive_released_reconciliations(ledger_path, *, roots, archive_directory, selections,
        expected_ledger_sha256, root_lease, phase_lease, root_request_id, phase_request_id,
        scheduler_state_path, expected_scheduler_policy_sha256,
        peak_storage_bytes=DEFAULT_PEAK_BYTES, timeout_seconds=900):
    """Genuine native, lock-held administrative archival admission and commit.

There is no borrowed disk owner. Before the first file write, the normal SDK
capacity check reserves a finite peak allowance while its exclusive ledger
lock prevents competing ledger admissions. All operation writes finish before
that lock is released. A crash before commit leaves the original ledger intact
and the durable private intent/snapshot counted in the ordinary named-root
census; it creates no continuing storage promise or productive child.
"""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as resources
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.existing_resource_scheduler import open_existing_scheduler
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import ResourceLease
    need(type(root_lease) is ResourceLease and type(phase_lease) is ResourceLease,
         "genuine native ResourceLease objects required")
    need(type(peak_storage_bytes) is int and DEFAULT_PEAK_BYTES <= peak_storage_bytes <= 64 * 1024 * 1024
         and type(timeout_seconds) in (int, float) and 0 < timeout_seconds <= 1800,
         "finite administrative archival envelope required")
    scheduler = open_existing_scheduler(scheduler_state_path, expected_scheduler_policy_sha256)
    deadline = time.monotonic() + timeout_seconds
    root_path = absolute(str(archive_directory))
    state_path = str(scheduler.state_path)
    def guard():
        need(time.monotonic() < deadline, "administrative archival deadline expired")
        need(str(Path(root_lease.token.state_path).absolute()) == state_path
             and str(Path(phase_lease.token.state_path).absolute()) == state_path,
             "actual native lease scheduler differs")
        need(root_lease.renew() and phase_lease.renew(), "native archival authority renewal failed")
        active = {row["lease_id"]: row for row in scheduler.active_leases()}
        for lease, request_id, parent_id in ((root_lease, root_request_id, None),
                                            (phase_lease, phase_request_id, root_lease.lease_id)):
            public = lease.to_dict()
            actual = active.get(public["lease_id"])
            need(public["owner_pid"] == os.getpid() and public["lane"] == "orchestration"
                 and public["parent_lease_id"] == parent_id and public["cpu_slots"] >= 1
                 and public["memory_mb"] >= 256 and public["child_process_slots"] >= 1 and not public["requires_gpu"]
                 and not public["released"] and not public["cancelled"] and actual is not None
                 and actual.get("request_id") == request_id, "actual archival native root/phase differs")
            for key in ("lease_id", "owner_pid", "lane", "parent_lease_id", "cpu_slots", "memory_mb",
                        "child_process_slots", "requires_gpu", "gpu_memory_mb", "unified_memory_mb"):
                need(actual.get(key) == public[key], "actual archival native envelope differs")
    guard()
    helper = resources.DaemonResourceReservation(ledger_path, roots=roots,
        storage_bytes=peak_storage_bytes, memory_mb=256, cpu_slots=1, child_process_slots=1,
        ledger_lock_timeout_seconds=60, scheduler_state_path=scheduler_state_path,
        expected_scheduler_policy_sha256=expected_scheduler_policy_sha256, require_existing_ledger=True)
    need(resources.MAX_LEDGER_BYTES == MAX_LEDGER_BYTES and resources.MAX_STORAGE_BYTES == MAX_STORAGE_BYTES,
         "unchanged native caps required")
    resources._safe_path(root_path, directory=True)
    identity = resources._root_identity(root_path)
    info = root_path.lstat()
    need(info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o700 and not any(root_path.iterdir())
         and any(root in root_path.parents for root in helper.roots), "fresh private named-root archive directory required")
    snapshot_path = root_path / "ledger-before.private.json"
    with helper._locked():
        guard()
        ledger = helper._read()
        raw = _read_regular(helper.ledger_path, MAX_LEDGER_BYTES)
        need(sha(raw) == expected_ledger_sha256 and decode(raw) == ledger, "exact current ledger pin differs")
        for row in ledger["reservations"].values():
            attempt = row.get("attempt_directory")
            if row["status"] != "released" and attempt is not None:
                other = Path(attempt["path"])
                need(root_path != other and root_path not in other.parents and other not in root_path.parents,
                     "archive directory overlaps outstanding ownership")
        now = time.time()
        admin_id = uuid.uuid4().hex
        admin = {"reservation_id": admin_id, "status": "released", "owner_pid": os.getpid(),
                 "storage_bytes": peak_storage_bytes, "memory_mb": 256, "cpu_slots": 1,
                 "child_process_slots": 1, "scheduler_lane": "orchestration",
                 "workload": "canonical_resource_ledger_archival", "created_at": now, "released_at": now,
                 "released_at_semantics": "planned transaction metadata time; observed atomic commit is returned separately",
                 "attempt_directory": identity, "child": None, "prior_children": [], "external_charges": {},
                 "artifacts_durable_asserted": True, "native_lease_id": phase_lease.lease_id,
                 "parent_lease_id": root_lease.lease_id, "scheduler_state_path": state_path,
                 "scheduler_policy_sha256": expected_scheduler_policy_sha256,
                 "archival": {"schema": SCHEMA, "snapshot_path": str(snapshot_path), "snapshot_sha256": sha(raw),
                              "selected_reservation_ids": [s["reservation_id"] for s in selections],
                              "admission": "dedicated lock-held administrative operation; not ParentedPhase",
                              "all_operation_writes_finish_before_lock_release": True}}
        admitted = helper._account(ledger, additional=peak_storage_bytes)
        check_capacity_precharge(admitted, peak_storage_bytes)
        admin["last_usage"] = admitted
        admin["archival"]["postcommit_verification_readonly"] = True
        admin["archival"]["postrelease_file_writes"] = False
        plan = plan_reconciliation_archival(raw, selections=selections, snapshot_path=str(snapshot_path),
                                            administration_record=admin)
        need(required_peak_bytes(len(raw), len(plan["ledger_bytes"])) <= peak_storage_bytes,
             "snapshot journal and atomic-temp amplification exceeds precharge")
        intent = {"schema": SCHEMA, "status": "admitted_history_not_yet_folded", "ledger_sha256_before": sha(raw),
                  "snapshot_path": str(snapshot_path), "snapshot_sha256": sha(raw), "snapshot_bytes": len(raw),
                  "ledger_sha256_planned": sha(plan["ledger_bytes"]), "administration_record_id": admin_id,
                  "selected_records": selections, "pointers": plan["pointers"], "peak_storage_bytes": peak_storage_bytes,
                  "actual_native_root": root_lease.to_dict(), "actual_native_phase": phase_lease.to_dict(),
                  "actual_capacity_precheck": admitted, "private_snapshot_publication_authorized": False,
                  "native_disk_grant_fabricated": False}
        encoded = wire(intent)
        need(len(encoded) <= MAX_JOURNAL_BYTES, "bounded archival intent required")
        guard()
        _write_new(root_path / "admission-intent.private.json", encoded)
        _write_new(snapshot_path, raw)
        need(_read_regular(snapshot_path, MAX_LEDGER_BYTES) == raw, "durable full history snapshot differs")
        _fsync_dir(root_path)
        _fsync_dir(root_path.parent)
        guard()
        # This second real census includes every archive byte already written.
        # Remaining atomic-temp/journal growth still has a finite extra charge.
        before_commit = helper._account(ledger, additional=len(plan["ledger_bytes"]) + MAX_JOURNAL_BYTES + 65536)
        need(resources._root_identity(root_path) == identity and _read_regular(helper.ledger_path, MAX_LEDGER_BYTES) == raw
             and helper._read() == ledger, "ledger or archive identity changed before commit")
        guard()
        # The SDK writer fsyncs the replacement and ledger parent. The exact
        # archived history above is already durable before this first fold.
        helper._write(plan["ledger"])
        actual = helper._read()
        actual_raw = _read_regular(helper.ledger_path, MAX_LEDGER_BYTES)
        need(actual == plan["ledger"] and actual_raw == plan["ledger_bytes"], "atomic archival commit differs")
        saved = _read_regular(snapshot_path, MAX_LEDGER_BYTES)
        for selection in selections:
            identifier = selection["reservation_id"]
            need(restore_archived_record(saved, actual["reservations"][identifier]) == ledger["reservations"][identifier],
                 "postwrite original record restoration differs")
        guard()
        completed = {"schema": SCHEMA, "status": "history_archived_ledger_folded_verified",
                     "observed_atomic_commit_at": time.time(),
                     "administration_record_id": admin_id, "ledger_sha256_before": sha(raw),
                     "ledger_sha256_after": sha(actual_raw), "snapshot_sha256": sha(saved),
                     "reclaimed_ledger_bytes": plan["reclaimed_ledger_bytes"],
                     "selected_reservation_ids": list(plan["pointers"]), "actual_capacity_precommit": before_commit,
                     "all_original_selected_records_reconstructed": True, "unselected_rows_changed": False,
                     "active_or_retained_rows_changed": False, "native_caps_changed": False,
                     "actual_native_root_id": root_lease.lease_id, "actual_native_phase_id": phase_lease.lease_id,
                     "private_snapshot_publication_authorized": False, "native_disk_grant_fabricated": False}
        # The primary atomic commit above is the release point. Every archive
        # file was fsynced before it. From here onward verification is read-only
        # and its result is returned to the actual native caller, never written
        # into a released attempt by this SDK operation.
        guard()
        postwrite = helper._account(actual)
        need(resources._root_identity(root_path) == identity, "archive directory identity changed")
        return {**completed, "actual_postwrite_accounting": postwrite,
                "archive_directory": str(root_path), "archive_history_durable": True,
                "actual_postwrite_capacity_satisfied": True}


__all__ = ["ArchivalRefusal", "plan_reconciliation_archival", "restore_archived_record",
           "required_peak_bytes", "check_capacity_precharge", "archive_released_reconciliations"]
