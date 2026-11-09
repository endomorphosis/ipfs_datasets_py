"""Read-only binding of an active, already funded parented operation.

This does not admit a job.  The caller must authenticate the owner-published
sealed handoff and acquire/hold an original nested native lease before claim.
The token authenticates compute ancestry; the selected disk row independently
binds storage and the current direct child.  No root allocation, census,
recovery, telemetry substitution, or credential export occurs here.
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import stat
import time

from . import autoencoder_daemon_resources as resources
from . import resource_scheduler as native
from .autoencoder_resource_recovery import _digest, _validation_inspection_lock
from .existing_resource_scheduler import open_existing_scheduler


def _need(condition, message):
    if not condition:
        raise resources.DaemonResourceError(message)


def _absolute(value):
    _need(isinstance(value, (str, Path)), "absolute bounded path required")
    text = os.fspath(value)
    _need(bool(text) and len(text) <= 4096 and "\0" not in text
          and Path(text).is_absolute() and ".." not in text.split(os.sep),
          "absolute bounded path required")
    return Path(text)


def _identity(value):
    _need(type(value) is dict and set(value) == {"pid", "birth"}
          and type(value["pid"]) is int and value["pid"] > 0
          and type(value["birth"]) is str
          and re.fullmatch(r"[0-9]{1,32}", value["birth"]),
          "exact process PID and birth identity required")
    return dict(value)


def _safe_output(path):
    """Check an existing prefix without creating a missing output."""
    for item in (path, *path.parents):
        _need(not item.is_symlink(), "writable path is aliased")
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        _need(stat.S_ISDIR(info.st_mode) or (
            item == path and stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and info.st_uid == os.geteuid()), "writable path is nonregular or hardlinked")


def _read_pin(pin):
    _need(type(pin) is dict and set(pin) == {"path", "bytes", "sha256"}
          and type(pin["bytes"]) is int and 0 < pin["bytes"] <= 4 * 1024**2
          and type(pin["sha256"]) is str
          and re.fullmatch(r"[0-9a-f]{64}", pin["sha256"]), "closed bounded file descriptor required")
    path = _absolute(pin["path"])
    resources._safe_path(path)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        first = os.fstat(stream.fileno())
        _need(stat.S_ISREG(first.st_mode) and first.st_nlink == 1
              and first.st_uid == os.geteuid() and first.st_size == pin["bytes"],
              "bound descriptor file identity differs")
        raw = stream.read(pin["bytes"] + 1)
        last = os.fstat(stream.fileno())
    stamp = lambda v: (v.st_dev, v.st_ino, v.st_mode, v.st_uid, v.st_nlink,
                       v.st_size, v.st_mtime_ns, v.st_ctime_ns)
    _need(stamp(first) == stamp(last) == stamp(path.lstat())
          and len(raw) == pin["bytes"] and hashlib.sha256(raw).hexdigest() == pin["sha256"],
          "bound descriptor file changed")
    def pairs(items):
        result = {}
        for key, value in items:
            _need(key not in result, "duplicate JSON field")
            result[key] = value
        return result
    try:
        result = json.loads(raw, object_pairs_hook=pairs,
                            parse_constant=lambda _: _need(False, "nonfinite JSON"))
    except (ValueError, UnicodeError) as error:
        raise resources.DaemonResourceError("invalid bound JSON object") from error
    _need(type(result) is dict, "bound JSON object required")
    return result


def inspect_active_parented_reservation(ledger_path, *, roots, reservation_id,
        execution_request_pin, expected_request_sha256, owner_identity, child_identity,
        native_lease_token, expected_phase_lease_id, expected_scheduler_policy_sha256,
        demand, writable_paths, sealed_work_deadline_monotonic, expected_boot_id,
        lock_timeout_seconds=5):
    """Observe one ACTIVE parented disk/compute binding without changing state.

    All path, request and deadline parameters must come from that authenticated
    owner handoff; arbitrary caller-selected lookup data is not disk authority.
    The exact original ``ResourceLeaseToken`` is secret capability material from
    the real owner's public ``native_lease.token``.  A report/RID is not a token.
    The deadline must come from the authenticated, same-boot original operation
    handoff; this observer checks it and clamps it to current ancestor expiry.
    It cannot independently derive an owner's private Python monotonic deadline.

    ``demand`` is a closed CPU/memory/children/storage envelope.  Its storage
    budget is inside an existing charged namespace, never an additional disk
    promise.  The keeper's original output/growth/deadline monitor must remain
    active.  Actual native child acquisition owns race-free compute reservation.
    """
    _need(type(reservation_id) is str and re.fullmatch(r"[0-9a-f]{32}", reservation_id),
          "exact reservation ID required")
    for value in (expected_request_sha256, expected_scheduler_policy_sha256):
        _need(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value), "exact SHA256 required")
    _need(type(expected_phase_lease_id) is str
          and re.fullmatch(r"[0-9a-f]{32}", expected_phase_lease_id), "exact phase ID required")
    owner, child = _identity(owner_identity), _identity(child_identity)
    _need(child["pid"] == os.getpid(), "inspection must bind the current direct child")
    _need(type(native_lease_token) is native.ResourceLeaseToken
          and type(native_lease_token.lease_id) is str
          and re.fullmatch(r"[0-9a-f]{32}", native_lease_token.lease_id)
          and type(native_lease_token.lease_key) is str
          and 0 < len(native_lease_token.lease_key) <= 256
          and native_lease_token.lease_key.isascii()
          and "\0" not in native_lease_token.lease_key, "original native capability required")
    state_path = _absolute(native_lease_token.state_path)
    _need(type(demand) is dict and set(demand) == {
        "cpu_slots", "memory_mb", "child_process_slots", "storage_bytes"}
        and all(type(value) is int and 0 < value <= 2**63 - 1 for value in demand.values()),
        "closed positive integer demand required")
    _need(type(roots) in (list, tuple) and 1 <= len(roots) <= 64, "bounded named roots required")
    roots = [_absolute(value) for value in roots]
    ledger_path = _absolute(ledger_path)
    _need(type(writable_paths) in (list, tuple) and 1 <= len(writable_paths) <= 64,
          "bounded writable path declaration required")
    paths = [_absolute(value) for value in writable_paths]
    _need(len(set(paths)) == len(paths), "duplicate writable path")
    _need(type(lock_timeout_seconds) in (int, float) and math.isfinite(lock_timeout_seconds)
          and 0 < lock_timeout_seconds <= 30, "bounded inspection timeout required")
    _need(type(sealed_work_deadline_monotonic) in (int, float)
          and math.isfinite(sealed_work_deadline_monotonic)
          and sealed_work_deadline_monotonic > time.monotonic(), "sealed operation deadline expired")
    _need(type(expected_boot_id) is str and bool(expected_boot_id)
          and expected_boot_id == native._owner_boot_id(), "original operation boot differs or is unknown")
    previous = native.resource_operation_deadline()
    _need(previous is None or not previous.cleanup_only, "cleanup has no execution inspection authority")

    execution = _read_pin(execution_request_pin)
    attempt = resources._safe_path(Path(execution_request_pin["path"]).parent, directory=True)
    _need(Path(execution_request_pin["path"]) == attempt / "execution-request.json",
          "original execution-request location differs")
    _need(execution.get("disk_reservation_id") == reservation_id, "execution request RID differs")
    request_pin = execution.get("request")
    request = _read_pin(request_pin)
    _need(request_pin["sha256"] == expected_request_sha256
          and request.get("attempt_directory") == str(attempt)
          and request.get("resource_ledger") == str(ledger_path)
          and request.get("scheduler_state_path") == str(state_path)
          and request.get("expected_scheduler_policy_sha256") == expected_scheduler_policy_sha256,
          "original enclosing request binding differs")
    request_id = request.get("request_id")
    _need(type(request_id) is str and 0 < len(request_id) <= 220, "bounded original request ID required")
    dialect = execution.get("schema")
    _need(dialect in {"native-metadata-qualification-execution-request/v1",
                     "native-metadata-resource-owner-execution-request/v1"},
          "unsupported original execution-request dialect")
    if dialect == "native-metadata-qualification-execution-request/v1":
        _need(request.get("schema") == "legal-ir-original-parented-private-git-validation/v1"
              and execution.get("request_sha256") == expected_request_sha256
              and execution.get("owner_pid") == owner["pid"]
              and execution.get("owner_birth") == owner["birth"], "qualification owner binding differs")
        external = execution.get("external_precharge")
        _need(type(external) is dict and set(external) == {"root", "bytes"}, "single charged root required")
        charged_root = resources._safe_path(_absolute(external["root"]), directory=True)
        _need(request.get("fixture_directory") == str(charged_root)
              and request.get("fixture_max_bytes") == external["bytes"], "fixture charge differs")
        charge_key = execution.get("external_charge_key")
        _need(charge_key == "physical-" + hashlib.sha256(str(charged_root).encode()).hexdigest(),
              "fixture charge key differs")
        exact_files = set()
        lane = "validation"
    else:
        _need(request.get("schema") == "legal-ir-original-native-control-request/v1"
              and execution.get("provider_authority") is False
              and execution.get("completion_authority") is False,
              "actual operation authority differs")
        external = execution.get("external_precharge")
        _need(type(external) is dict and set(external) == {"key", "bytes", "files"}
              and external["files"] == request.get("external_files"), "exact actual file bundle required")
        files = external["files"]
        _need(type(files) is list and 1 <= len(files) <= 64
              and all(type(f) is dict and set(f) == {"path", "max_bytes"}
                      and type(f["max_bytes"]) is int and f["max_bytes"] > 0 for f in files),
              "bounded actual file charge required")
        exact_files = {_absolute(f["path"]) for f in files}
        _need(len(exact_files) == len(files) and sum(f["max_bytes"] for f in files) == external["bytes"],
              "actual charge bytes differ")
        charge_key, charged_root, lane = external["key"], None, "orchestration"
        _need(charge_key == "control-" + hashlib.sha256(json.dumps(
            files, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "actual file charge key differs")
    _need(type(external["bytes"]) is int and external["bytes"] > 0
          and type(charge_key) is str and bool(charge_key), "positive declared external charge required")
    for path in paths:
        _safe_output(path)
        _need(attempt in path.parents or path in exact_files
              or (charged_root is not None and charged_root in path.parents),
              "writable path has no enclosing storage charge")

    helper = resources.DaemonResourceReservation(ledger_path, roots=roots,
        storage_bytes=1, memory_mb=1, require_existing_ledger=True,
        ledger_lock_timeout_seconds=lock_timeout_seconds)
    _need(any(root in attempt.parents for root in helper.roots), "attempt outside named roots")
    attempt_identity = resources._root_identity(attempt)
    deadline = min(sealed_work_deadline_monotonic, time.monotonic() + lock_timeout_seconds)
    if previous is not None:
        deadline = min(deadline, previous.work_deadline_monotonic,
                       previous.native_deadline_monotonic)
    with native.resource_admission_deadline(work_deadline_monotonic=deadline,
                                            native_deadline_monotonic=deadline):
        scheduler = open_existing_scheduler(state_path, expected_scheduler_policy_sha256,
                                            inspection_only=True)
        def processes():
            o, c = resources._process(owner["pid"]), resources._process(child["pid"])
            _need(o is not None and o["birth"] == owner["birth"]
                  and c is not None and c["birth"] == child["birth"]
                  and c["parent_pid"] == owner["pid"], "current owner/direct-child identity differs")
        def credential():
            with scheduler._locked_state(persist=False, strict_existing=True) as state:
                row = state["leases"].get(native_lease_token.lease_id)
                _need(row is not None and type(row.get("lease_key")) is str
                      and row["lease_key"].isascii() and row.get("owner_boot_id") == expected_boot_id
                      and hmac.compare_digest(row["lease_key"], native_lease_token.lease_key),
                      "original native capability is not authentic")
                envelope = {k: row.get(k) for k in (
                    "cpu_slots", "memory_mb", "child_process_slots", "gpu_memory_mb",
                    "unified_memory_mb", "requires_gpu")}
                _need(all(type(envelope[k]) is int and envelope[k] > 0 for k in (
                    "cpu_slots", "memory_mb", "child_process_slots"))
                    and envelope["gpu_memory_mb"] == envelope["unified_memory_mb"] == 0
                    and envelope["requires_gpu"] is False, "original CPU parent envelope differs")
                return envelope
        def live(identifier, request_name, expected_lane):
            value = scheduler.inspect_lease(identifier, expected_request_id=request_name,
                expected_lane=expected_lane, expected_owner_pid=owner["pid"],
                expected_owner_birth_marker=owner["birth"], bounded_lock_timeout=lock_timeout_seconds)
            _need(value["status"] == "present" and value["binding_verified"] is True
                  and value["owner_birth_binding_verified"] is True
                  and value["lease"]["owner_alive"] is True
                  and not any(value["lease"][k] for k in ("expired", "cancelled", "release_requested")),
                  "native parent ancestry is not live")
            return value["lease"]
        with _validation_inspection_lock(helper):
            ledger = helper._read()
            row = ledger["reservations"].get(reservation_id)
            _need(row is not None and row.get("status") == "active"
                  and row.get("workload") == "canonical_parented_phase"
                  and row.get("scheduler_lane") == lane and row.get("owner_pid") == owner["pid"]
                  and row.get("attempt_directory") == attempt_identity
                  and row.get("child") == child and row.get("prior_children") == []
                  and row.get("native_lease_id") == native_lease_token.lease_id
                  and row.get("parent_lease_id") == expected_phase_lease_id
                  and row.get("scheduler_state_path") == str(state_path)
                  and row.get("scheduler_policy_sha256") == expected_scheduler_policy_sha256,
                  "active parented disk/current child binding differs")
            _need(row.get("external_charges") == {charge_key: external["bytes"]},
                  "active external storage charge differs")
            _need(all(type(row.get(k)) is int and row[k] == request.get(k)
                      and demand[k] <= row[k] for k in demand)
                  and external["bytes"] <= row["storage_bytes"], "enclosing disk/compute budget differs")
            processes()
            envelope = credential()
            _need(all(demand[k] <= envelope[k] for k in demand if k != "storage_bytes"),
                  "compute demand exceeds authentic native parent")
            _need(all(row[k] == envelope[k] for k in demand if k != "storage_bytes"),
                  "disk record and native allocation envelopes differ")
            owned = live(native_lease_token.lease_id, "daemon:" + reservation_id, lane)
            phase = live(expected_phase_lease_id, request_id + ":phase", lane)
            _need(owned["parent_lease_id"] == expected_phase_lease_id
                  and type(phase["parent_lease_id"]) is str, "native phase ancestry differs")
            root = live(phase["parent_lease_id"], request_id + ":root", lane)
            _need(root["parent_lease_id"] is None, "native root ancestry differs")
            for identity, name, expected_lane in (
                    (owned["lease_id"], "daemon:" + reservation_id, lane),
                    (phase["lease_id"], request_id + ":phase", lane),
                    (root["lease_id"], request_id + ":root", lane)):
                live(identity, name, expected_lane)
            _need(credential() == envelope and helper._read()["reservations"].get(reservation_id) == row,
                  "active authority changed during inspection")
            processes()
            _need(_read_pin(execution_request_pin) == execution and _read_pin(request_pin) == request
                  and resources._root_identity(attempt) == attempt_identity,
                  "original request/attempt changed during inspection")
            helper._verify_owner_roots()
            expires = min(v["expires_at"] for v in (owned, phase, root))
            effective_deadline = min(sealed_work_deadline_monotonic,
                                     time.monotonic() + max(0, expires - time.time()))
            if previous is not None:
                effective_deadline = min(effective_deadline, previous.work_deadline_monotonic,
                                         previous.native_deadline_monotonic)
            _need(effective_deadline > time.monotonic(), "enclosing operation expired")
            return {"schema": "active-parented-resource-inspection/v1", "read_only": True,
                "binding_verified": True, "native_capability_authenticated": True,
                "reservation_id": reservation_id, "record_sha256": _digest(row),
                "owner_identity": owner, "child_identity": child,
                "attempt_directory": attempt_identity, "execution_request_pin": copy.deepcopy(execution_request_pin),
                "request_sha256": expected_request_sha256, "native_lease_id": owned["lease_id"],
                "phase_lease_id": phase["lease_id"], "root_lease_id": root["lease_id"],
                "allocated_envelope": {**envelope, "storage_bytes": row["storage_bytes"]},
                "external_charged_bytes": external["bytes"], "demand": dict(demand),
                "writable_paths": [str(p) for p in paths], "expected_boot_id": expected_boot_id,
                "effective_work_deadline_monotonic": effective_deadline,
                "deadline_provenance": "authenticated caller handoff, clamped to live ancestry expiry",
                "compute_suballocation_reserved": False, "admitted": False,
                "state_written": False, "new_host_reservation": False, "recovery_performed": False,
                "credential_exported": False, "parent_keeper_must_continue_monitoring": True}


__all__ = ["inspect_active_parented_reservation"]
