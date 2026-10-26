"""Explicit reconciliation of one dead owner's retained disk claim.

Never expires a claim by age or deletes its outputs. The caller supplies the
exact prior record and durable artifact inventory. This is an administrative
operation, separate from the original owner's resource lease lifecycle.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import time

from . import autoencoder_daemon_resources as resources


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _durable_inventory(attempt):
    resources._inventory([attempt], strict=True)
    rows = []
    for path in sorted(attempt.rglob("*")):
        if path.is_dir():
            continue
        resources._safe_path(path)
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise resources.DaemonResourceError("recovery artifact must be an unaliased regular file")
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
            os.fsync(stream.fileno())
            after = os.fstat(stream.fileno())
        current = path.stat()
        identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
        if identity(before) != identity(after) or identity(before) != identity(current):
            raise resources.DaemonResourceError("recovery artifact changed")
        rows.append({"path": str(path.relative_to(attempt)), "bytes": before.st_size, "sha256": digest})
    for directory in [attempt, *(path for path in attempt.rglob("*") if path.is_dir())]:
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    return rows


def _administrative_census(helper, ledger):
    """Observe storage for a closeout; this grants no allocation authority.

    Admission still uses ``DaemonResourceReservation._account``. Recovery needs
    to record an existing overage instead of making a dead owner's durable
    claim impossible to close. Use the same exact roots and pathname accounting,
    with no additional request and no scheduler operation.
    """
    helper._verify_owner_roots()
    inventory = resources._inventory(helper.roots)
    observed = inventory["apparent_bytes"]
    outstanding = sum(row["storage_bytes"] for row in ledger["reservations"].values()
                      if row["status"] != "released")
    charged = observed + outstanding
    free = min(resources.shutil.disk_usage(root).free for root in helper.roots)
    helper._verify_owner_roots()
    over_limit = max(0, charged - resources.MAX_STORAGE_BYTES)
    free_shortfall = max(0, outstanding - free)
    return {"observed_apparent_bytes": observed,
            "outstanding_full_reservations_bytes": outstanding,
            "additional_requested_bytes": 0, "charged_bytes": charged,
            "limit_bytes": resources.MAX_STORAGE_BYTES,
            "minimum_filesystem_free_bytes": free,
            "scope": "named_roots_only_apparent_bytes", "inventory": inventory,
            "over_limit_bytes": over_limit,
            "filesystem_free_shortfall_bytes": free_shortfall,
            "capacity_satisfied": over_limit == 0 and free_shortfall == 0}


def reconcile_retained_reservation(ledger_path, *, roots, reservation_id,
        expected_record_sha256, attempt_directory, expected_artifacts, artifacts_durable=False,
        capacity_policy="require_capacity", allow_empty_failed_admission=False):
    """Release exactly one retained claim after explicit, verified closeout.

    The previous owner PID must be absent (a reused PID also blocks recovery).
    Every recorded child process group must be dead. The full claim remains
    charged during a fresh census. The default ``require_capacity`` policy keeps
    the existing capacity cutoff. Explicit ``administrative_closeout`` records
    over-capacity observations for this one verified claim; it never admits work
    or changes the cap. Its final accounting is a fresh prewrite projection with
    only this claim released, and needs an independent actual postwrite census.
    External charges are deliberately unsupported here: their disposition needs
    a separate recovery design. The explicit empty-failure opt-in accepts only
    a genuinely empty, bound validation attempt that failed before recorded
    native custody/outputs or child attachment; it never invents check results.
    """
    if type(capacity_policy) is not str or capacity_policy not in {
            "require_capacity", "administrative_closeout"}:
        raise resources.DaemonResourceError("invalid reconciliation capacity policy")
    if type(allow_empty_failed_admission) is not bool:
        raise resources.DaemonResourceError("invalid empty failed admission opt-in")
    if allow_empty_failed_admission and (type(expected_artifacts) is not list or expected_artifacts != []):
        raise resources.DaemonResourceError("empty failed admission requires an exact empty inventory list")
    if artifacts_durable is not True or (not allow_empty_failed_admission and not expected_artifacts):
        raise resources.DaemonResourceError("explicit durable artifact inventory required")
    helper = resources.DaemonResourceReservation(ledger_path, roots=roots,
        storage_bytes=1, memory_mb=1, ledger_lock_timeout_seconds=30)
    attempt = resources._safe_path(attempt_directory, directory=True)
    if not any(attempt == root or root in attempt.parents for root in helper.roots):
        raise resources.DaemonResourceError("recovery attempt outside named roots")
    with helper._locked():
        ledger = helper._read()
        record = ledger["reservations"].get(reservation_id)
        if record is None or _digest(record) != expected_record_sha256 or record["status"] != "retained":
            raise resources.DaemonResourceError("retained reservation identity changed")
        if allow_empty_failed_admission:
            # Admission writes only these fields before attempting a native grant.
            # Reject custody/output field presence even when its value is None.
            fields = set("artifacts_durable_asserted attempt_directory child child_process_slots cpu_slots "
                "created_at external_charges last_usage memory_mb owner_pid prior_children reservation_id "
                "retention_reason scheduler_lane status storage_bytes workload".split())
            if (set(record) != fields or record["retention_reason"] != "scheduler_admission_failed"
                    or record["scheduler_lane"] != "validation" or record["workload"] != "canonical_validation"
                    or record["child"] is not None or record["prior_children"] != []
                    or record["artifacts_durable_asserted"] is not False):
                raise resources.DaemonResourceError("empty failed admission record has custody, outputs or other history")
        if resources._external_charges(record):
            raise resources.DaemonResourceError("external charges require separate recovery")
        if record.get("attempt_directory") != resources._root_identity(attempt):
            raise resources.DaemonResourceError("recovery attempt identity changed")
        def unchanged_selected():
            if (ledger["reservations"].get(reservation_id) is not record
                    or _digest(record) != expected_record_sha256):
                raise resources.DaemonResourceError("retained reservation changed during census")
        def stopped():
            if resources._process(record["owner_pid"]) is not None:
                raise resources.DaemonResourceError("original reservation owner PID still exists")
            for child in [record.get("child"), *record.get("prior_children", ())]:
                if resources._group_usage(child)["live_processes"]:
                    raise resources.DaemonResourceError("retained child group is still alive")
        def durable_inventory():
            if allow_empty_failed_admission and any(attempt.iterdir()):
                raise resources.DaemonResourceError("empty failed admission attempt has entries")
            value = _durable_inventory(attempt)  # Also fsyncs the existing empty directory.
            if allow_empty_failed_admission and any(attempt.iterdir()):
                raise resources.DaemonResourceError("empty failed admission attempt changed")
            return value
        stopped()
        inventory = durable_inventory()
        if inventory != expected_artifacts:
            raise resources.DaemonResourceError("durable recovery inventory differs")
        if capacity_policy == "administrative_closeout":
            before_sha = _digest({key: value for key, value in ledger["reservations"].items()
                                  if key != reservation_id})
            accounting = _administrative_census(helper, ledger)
            unchanged_selected()
        else:
            accounting = helper._account(ledger)
        stopped()
        if resources._root_identity(attempt) != record["attempt_directory"] or durable_inventory() != inventory:
            raise resources.DaemonResourceError("recovery attempt changed during census")
        attempt_bytes = sum(row["bytes"] for row in inventory)
        if attempt_bytes > record["storage_bytes"]:
            raise resources.DaemonResourceError("retained attempt exceeds original reservation")
        others = {key: value for key, value in ledger["reservations"].items() if key != reservation_id}
        if capacity_policy == "administrative_closeout":
            if _digest(others) != before_sha:
                raise resources.DaemonResourceError("another reservation changed")
            projected = copy.deepcopy(ledger)
            projected["reservations"][reservation_id]["status"] = "released"
            projected_record_sha = _digest(projected["reservations"][reservation_id])
            final = _administrative_census(helper, projected)
            unchanged_selected()
            stopped()
            if (resources._root_identity(attempt) != record["attempt_directory"]
                    or durable_inventory() != inventory):
                raise resources.DaemonResourceError("recovery attempt changed during final census")
            if (accounting["outstanding_full_reservations_bytes"]
                    - final["outstanding_full_reservations_bytes"] != record["storage_bytes"]
                    or _digest(projected["reservations"].get(reservation_id)) != projected_record_sha
                    or _digest({key: value for key, value in projected["reservations"].items()
                                if key != reservation_id}) != before_sha):
                raise resources.DaemonResourceError("projected recovery accounting differs")
            unchanged_selected()
        else:
            before_sha = _digest(others)
            final = copy.deepcopy(accounting)
            final["outstanding_full_reservations_bytes"] -= record["storage_bytes"]
            final["charged_bytes"] -= record["storage_bytes"]
        recovery = {"schema": "explicit-retained-reservation-reconciliation/v1",
            "reservation_id": reservation_id, "previous_record_sha256": expected_record_sha256,
            "original_owner_pid": record["owner_pid"], "reconciled_by_pid": os.getpid(),
            "artifacts": inventory, "other_reservations_sha256": before_sha,
            "full_claim_accounting": accounting, "final_accounting": final,
            "outputs_deleted": False, "automatic_expiry": False, "admitted": False}
        if allow_empty_failed_admission:
            recovery["allow_empty_failed_admission"] = True
        if capacity_policy == "administrative_closeout":
            recovery.update(schema="explicit-retained-reservation-reconciliation/v2",
                capacity_policy=capacity_policy, cap_changed=False,
                final_accounting_is_prewrite_projection=True,
                actual_postwrite_census_required=True, fresh_global_inventory_count=2,
                new_reservation_created=False, new_resource_lease_acquired=False)
        record.update(status="released", artifacts_durable_asserted=True, released_at=time.time(),
            final_accounting=final, final_attempt_bytes=attempt_bytes,
            final_external_charged_bytes=0, final_total_charged_bytes=attempt_bytes,
            attempt_exceeded_reservation=False, explicit_reconciliation=recovery)
        if _digest({key: value for key, value in ledger["reservations"].items() if key != reservation_id}) != before_sha:
            raise resources.DaemonResourceError("another reservation changed")
        if capacity_policy == "administrative_closeout":
            helper._verify_owner_roots()
        helper._write(ledger)
        return recovery


@contextmanager
def _validation_inspection_lock(helper):
    """Use the owner's sibling lock without ever creating a missing lock."""
    helper._verify_owner_roots()
    resources._safe_path(helper.lock_path)
    descriptor = os.open(helper.lock_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise resources.DaemonResourceError("inspection lock must be an unaliased regular file")
        deadline = time.monotonic() + helper.ledger_lock_timeout_seconds
        operation = resources.native_deadlines.resource_operation_deadline()
        if operation is not None:
            deadline = min(deadline, resources.native_deadlines._operation_clock(operation))
        while True:
            resources.native_deadlines._check_resource_operation_deadline()
            try:
                resources.fcntl.flock(descriptor, resources.fcntl.LOCK_EX | resources.fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise resources.DaemonResourceError("inspection ledger lock unavailable") from None
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        resources.native_deadlines._check_resource_operation_deadline()
        current = helper.lock_path.lstat()
        if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
            raise resources.DaemonResourceError("inspection ledger lock identity changed")
        helper._verify_owner_roots()
        yield
    finally:
        os.close(descriptor)


def inspect_validation_reservation(ledger_path, *, roots, reservation_id,
        expected_request_sha256, attempt_directory, ledger_lock_timeout_seconds=5):
    """Inspect one existing validation claim without admission or recovery.

    The selected row's hash is the exact canonical digest used by the existing
    recovery API. The returned custody is recorded evidence, not a current
    scheduler observation, process census, historical release or recovery
    authorization. No foreign record or lease credential is exported.
    """
    def need(condition, message):
        if not condition:
            raise resources.DaemonResourceError(message)

    def absolute(value, name):
        need(isinstance(value, (str, Path)), "invalid inspection " + name)
        text = os.fspath(value)
        need(bool(text) and len(text) <= 4096 and "\x00" not in text
             and Path(text).is_absolute() and ".." not in text.split(os.sep),
             "absolute inspection " + name + " required")
        return Path(text)

    need(type(reservation_id) is str and re.fullmatch(r"[0-9a-f]{32}", reservation_id),
         "exact inspection reservation ID required")
    need(type(expected_request_sha256) is str
         and re.fullmatch(r"[0-9a-f]{64}", expected_request_sha256),
         "exact inspection request SHA256 required")
    need(type(ledger_lock_timeout_seconds) in (int, float)
         and math.isfinite(ledger_lock_timeout_seconds)
         and 0 <= ledger_lock_timeout_seconds <= 30,
         "inspection ledger lock timeout must be between zero and 30 seconds")
    need(type(roots) in (list, tuple) and 1 <= len(roots) <= 64,
         "one to 64 explicit inspection roots required")
    ledger_path = absolute(ledger_path, "ledger path")
    attempt = absolute(attempt_directory, "attempt directory")
    roots = [absolute(value, "root") for value in roots]
    # Scalar validation above deliberately precedes helper/path/state access.
    helper = resources.DaemonResourceReservation(ledger_path, roots=roots,
        storage_bytes=1, memory_mb=1, require_existing_ledger=True,
        ledger_lock_timeout_seconds=ledger_lock_timeout_seconds)
    resources._safe_path(helper.ledger_path)
    resources._safe_path(helper.lock_path)
    attempt = resources._safe_path(attempt, directory=True)
    need(any(root in attempt.parents for root in helper.roots),
         "inspection attempt must be a strict descendant of a named root")
    attempt_identity = resources._root_identity(attempt)
    with _validation_inspection_lock(helper):
        ledger = helper._read()
        row = ledger["reservations"].get(reservation_id)
        helper._verify_owner_roots()
        need(resources._root_identity(attempt) == attempt_identity,
             "inspection attempt identity changed")
        report = {
            "schema": "validation-reservation-inspection/v1",
            "reservation_id": reservation_id,
            "expected_request_sha256": expected_request_sha256,
            "attempt_directory": attempt_identity,
            "roots": copy.deepcopy(helper.root_identities),
            "observed_at": time.time(),
            "present": row is not None,
            "binding_verified": False,
            "record_sha256": None,
            "status": None,
            "custody": None,
            "record_reason": "No selected reservation exists in the observed ledger.",
            "native_lease_disposition": None,
            "native_lease_disposition_reason": "The scheduler was not inspected; row status cannot establish compute release.",
            "historical_release_established": False,
            "admitted": False,
            "state_written": False,
            "recovery_performed": False,
            "scope": "selected_existing_validation_storage_record_only",
        }
        if row is None:
            return report
        need(row.get("validation_request_sha256") == expected_request_sha256
             and row.get("scheduler_lane") == "validation"
             and row.get("workload") == "canonical_validation"
             and row.get("attempt_directory") == attempt_identity,
             "inspection validation request or attempt binding differs")
        need(row.get("status") in {"active", "retained", "released"},
             "inspection requires recorded validation custody")
        lease_id = row.get("native_lease_id")
        policy = row.get("scheduler_policy_sha256")
        birth = row.get("owner_birth")
        need(type(lease_id) is str and re.fullmatch(r"[0-9a-f]{32}", lease_id)
             and type(policy) is str and re.fullmatch(r"[0-9a-f]{64}", policy)
             and type(birth) is str and re.fullmatch(r"[0-9]{1,32}", birth)
             and row.get("process_scope") == "isolated_process_group_only",
             "inspection native lease custody is invalid")
        scheduler_path = absolute(row.get("scheduler_state_path"), "recorded scheduler path")
        # Validate the recorded path spelling only; never open scheduler state.
        need(str(scheduler_path) == row["scheduler_state_path"],
             "inspection recorded scheduler path is not canonical")
        outputs = {name: str(attempt / name)
                   for name in ("pytest", "tmp", "cache", "db", "exports", "logs")}
        need(row.get("outputs") == outputs, "inspection validation output binding differs")
        need(type(row.get("artifacts_durable_asserted")) is bool,
             "inspection artifact durability flag is invalid")
        child = row.get("child")
        need(child is None or (type(child) is dict and set(child) == {"pid", "birth"}
             and type(child["pid"]) is int and child["pid"] > 0
             and type(child["birth"]) is str and re.fullmatch(r"[0-9]{1,32}", child["birth"])),
             "inspection recorded child identity is invalid")
        need(row.get("prior_children") == [],
             "inspection validation custody cannot contain prior child groups")
        report.update(binding_verified=True, record_sha256=_digest(row),
            status=row["status"], record_reason=None, custody={
                "native_lease_id": lease_id,
                "scheduler_state_path": str(scheduler_path),
                "scheduler_policy_sha256": policy,
                "scheduler_request_id": "validation:" + reservation_id,
                "scheduler_lane": "validation",
                "workload": "canonical_validation",
                "owner_pid": row["owner_pid"], "owner_birth": birth,
                "child": copy.deepcopy(child),
                "process_scope": row["process_scope"],
                "outputs": outputs,
                "artifacts_durable_asserted": row["artifacts_durable_asserted"],
                "storage_bytes": row["storage_bytes"],
            })
        return report


_UNOPENED_PROFILE = "pinned-owned-validation-open-refusal-497e92a8/v1"
_UNOPENED_SOURCE_PINS = {
    "scripts/ops/legal_ir/run_owned_validation.py":
        "497e92a85709d1bb49385f85385ddcfef5b83c68820fa7479c9aa728e102e938",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/validation_run_resources.py":
        "1cf169b22c944c878e1e622ce45e5f381ca831aaa40f4b1186082cae2383f429",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py":
        "0cf17951048015d4ce01817c0bfdd74394a161cd5e7999b01a29f18f358e666a",
    "ipfs_datasets_py/optimizers/logic_theorem_optimizer/resource_scheduler.py":
        "2c00683202b4a783b5050329caa24a411f83788010baba86d9380123bae7d083",
}
_UNOPENED_RECORD_FIELDS = frozenset("artifacts_durable_asserted attempt_directory child "
    "child_process_slots cpu_slots created_at external_charges last_usage memory_mb "
    "owner_pid prior_children reservation_id scheduler_lane status storage_bytes workload".split())


def _unopened_need(condition, message):
    if not condition:
        raise resources.DaemonResourceError(message)


def _unopened_json(raw, maximum, label):
    _unopened_need(type(raw) is bytes and 0 < len(raw) <= maximum,
                   "bounded raw bytes required for " + label)
    def pairs(items):
        value = {}
        for key, item in items:
            _unopened_need(key not in value, "duplicate field in " + label)
            value[key] = item
        return value
    def constant(_):
        raise resources.DaemonResourceError("nonfinite value in " + label)
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, ValueError, RecursionError) as error:
        raise resources.DaemonResourceError("invalid JSON in " + label) from error
    _unopened_need(type(value) is dict, "JSON object required for " + label)
    return value


def _unopened_path(value, label):
    _unopened_need(type(value) is str and 0 < len(value) <= 4096
        and "\x00" not in value and Path(value).is_absolute()
        and ".." not in value.split(os.sep), "absolute " + label + " required")
    return Path(value)


def _unopened_proof(raw, expected_sha256):
    """Interpret only the explicitly reviewed historical open-refusal profile.

    This is an independently committed administrative evidence bundle, not a
    reconstructed original native terminal. Producer identities and the actual
    retained traceback establish where open failed; null custody fields alone
    are never evidence of an unopened run. Historical source files are data
    declarations in the original request, never imported or executed here.
    """
    _unopened_need(type(expected_sha256) is str
        and re.fullmatch(r"[0-9a-f]{64}", expected_sha256), "exact proof SHA256 required")
    proof = _unopened_json(raw, 8 * 1024 * 1024, "unopened proof")
    _unopened_need(hashlib.sha256(raw).hexdigest() == expected_sha256, "unopened proof hash differs")
    fields = {"schema", "profile", "request_raw_utf8", "terminal_raw_utf8",
              "stderr_utf8", "controller_closeout_raw_utf8"}
    _unopened_need(set(proof) == fields and proof["schema"] == "empty-unopened-validation-proof/v1"
        and proof["profile"] == _UNOPENED_PROFILE, "unsupported unopened proof profile")
    for key in fields - {"schema", "profile"}:
        _unopened_need(type(proof[key]) is str, "exact retained UTF-8 evidence required")
        try:
            proof[key].encode("utf-8")
        except UnicodeError as error:
            raise resources.DaemonResourceError("retained evidence is not valid UTF-8") from error
    request_raw = proof["request_raw_utf8"].encode("utf-8")
    request = _unopened_json(request_raw, 1024 * 1024, "original request")
    terminal = _unopened_json(proof["terminal_raw_utf8"].encode("utf-8"), 4 * 1024 * 1024,
                              "original failure terminal")
    closeout = _unopened_json(proof["controller_closeout_raw_utf8"].encode("utf-8"),
                              64 * 1024, "abnormal controller closeout")
    request_fields = set("argv attempt_directory child_process_slots cpu_slots cwd "
        "declared_external_writable_paths expected_scheduler_policy_sha256 memory_mb outputs "
        "process_scope roots scheduler_state_path schema selected_checks source_sha256 "
        "storage_bytes timeout_seconds".split())
    _unopened_need(set(request) == request_fields and request["schema"] == "owned-validation-request/v1"
        and request["process_scope"] == "sampled_birth_bound_descendants",
        "unsupported original request profile")
    pins = request["source_sha256"]
    _unopened_need(type(pins) is dict and 0 < len(pins) <= 256, "bounded original source pins required")
    for path, digest in pins.items():
        _unopened_path(path, "original source path")
        _unopened_need(type(digest) is str and re.fullmatch(r"[0-9a-f]{64}", digest),
                       "exact original source hash required")
    launcher_rel = "scripts/ops/legal_ir/run_owned_validation.py"
    launchers = [p for p in pins if p.endswith("/" + launcher_rel)]
    _unopened_need(len(launchers) == 1, "one original launcher identity required")
    source_root = Path(launchers[0]).parents[3]
    for relative, digest in _UNOPENED_SOURCE_PINS.items():
        _unopened_need(pins.get(str(source_root / relative)) == digest,
                       "unreviewed original open-refusal producer")
    stderr = proof["stderr_utf8"]
    _unopened_need(0 < len(stderr.encode("utf-8")) <= 64 * 1024,
                   "bounded original failure traceback required")
    frames = re.findall(r'^  File "([^"\n]+)", line ([0-9]+), in ([^\n]+)$', stderr, re.M)
    expected_frames = [
        (str(source_root / launcher_rel), "336", "<module>"),
        (str(source_root / launcher_rel), "188", "main"),
        (str(source_root / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/validation_run_resources.py"), "273", "open"),
        (str(source_root / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py"), "486", "__enter__"),
        (str(source_root / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py"), "500", "_acquire_native_lease"),
        (str(source_root / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/resource_scheduler.py"), "2318", "acquire"),
    ]
    _unopened_need(stderr.startswith("Traceback (most recent call last):\n")
        and frames == expected_frames and stderr.splitlines()[-1] ==
        "ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler.LeaseTimeoutError: timed out waiting for a resource lease",
        "retained traceback does not prove the reviewed owner.open refusal")
    request_sha = hashlib.sha256(request_raw).hexdigest()
    _unopened_need(set(terminal) == set("schema request_sha256 completed admitted Lean_admitted "
        "failure reservation process_cleanup_error owner_exit_error".split())
        and terminal["schema"] == "owned-validation-failure-terminal/v1"
        and terminal["request_sha256"] == request_sha,
        "original failure terminal binding differs")
    failure = terminal["failure"]
    failure_fields = set("Lean_admitted admitted authority_granted completed elapsed_seconds error "
        "error_type executed_checks model_weights_downloaded process_cleanup_error process_observation "
        "received_signals request_sha256 resource_scope returncode schema watchdog_errors".split())
    _unopened_need(type(failure) is dict and set(failure) == failure_fields and failure.get("schema") == "owned-validation-result/v1"
        and failure.get("request_sha256") == request_sha
        and failure.get("error_type") == "LeaseTimeoutError"
        and failure.get("error") == "timed out waiting for a resource lease"
        and failure.get("executed_checks") == [] and failure.get("returncode") is None
        and failure.get("watchdog_errors") == [] and failure.get("received_signals") == []
        and failure.get("process_observation") is None
        and failure.get("process_cleanup_error") is None,
        "original failure does not establish reviewed unopened refusal")
    for value in (terminal, failure):
        for key in ("completed", "admitted", "Lean_admitted"):
            _unopened_need(value.get(key) is False, "unopened proof grants authority or completion")
    _unopened_need(failure.get("authority_granted") is False
        and failure.get("model_weights_downloaded") is False
        and terminal["process_cleanup_error"] is None and terminal["owner_exit_error"] is None,
        "unopened proof has unresolved process exit or authority")
    reserved = terminal["reservation"]
    reserved_fields = set("cleanup_error enforcement ledger_path process_observation record reservation_id "
        "resource_lease roots scheduler_lane schema status storage_limit_bytes workload".split())
    _unopened_need(type(reserved) is dict and set(reserved) == reserved_fields
        and type(reserved.get("record")) is dict
        and reserved.get("schema") == resources.SCHEMA
        and reserved.get("status") == "reserved" and reserved.get("resource_lease") is None
        and reserved.get("process_observation") is None
        and reserved.get("cleanup_error") == "DaemonResourceError",
        "original reserved storage failure differs")
    record = reserved["record"]
    _unopened_need(set(record) == _UNOPENED_RECORD_FIELDS
        and record["status"] == "reserved" and record["scheduler_lane"] == "validation"
        and record["workload"] == "canonical_validation" and record["child"] is None
        and record["prior_children"] == [] and record["external_charges"] == {}
        and record["artifacts_durable_asserted"] is False,
        "reserved unopened record has custody, outputs or other history")
    closeout_fields = set("argv closed_at_utc controller_PID_absent_after_original_exec_reap "
        "controller_birth controller_pid inspection_sha256 native_resource_lease_recorded "
        "original_exec_session_exit_code peer_review pidfd_exit_observed post_signal_observation_error "
        "recorded_at_utc request_sha256 schema signal source_lock_descriptor_closed source_release_scope "
        "storage_bytes_fully_charged storage_reconciled storage_reservation_id storage_status_preserved "
        "tests_executed".split())
    _unopened_need(set(closeout) == closeout_fields
        and closeout.get("schema") == "parent-replay-files-responsible-abnormal-controller-close/v1"
        and closeout.get("request_sha256") == request_sha
        and closeout.get("storage_reservation_id") == record["reservation_id"]
        and closeout.get("storage_bytes_fully_charged") == record["storage_bytes"]
        and closeout.get("storage_status_preserved") == "reserved"
        and closeout.get("storage_reconciled") is False
        and type(closeout.get("tests_executed")) is int and closeout["tests_executed"] == 0
        and closeout.get("native_resource_lease_recorded") is None
        and closeout.get("pidfd_exit_observed") is True
        and closeout.get("controller_PID_absent_after_original_exec_reap") is True
        and closeout.get("source_lock_descriptor_closed") is True
        and type(closeout.get("original_exec_session_exit_code")) is int
        and closeout["original_exec_session_exit_code"] == 137,
        "original abnormal controller closeout differs")
    _unopened_need(type(closeout.get("controller_pid")) is int and closeout["controller_pid"] > 0
        and type(record["owner_pid"]) is int and record["owner_pid"] > 0
        and closeout["controller_pid"] != record["owner_pid"], "exact distinct original owner PIDs required")
    return request, reserved, closeout, {
        "profile": _UNOPENED_PROFILE, "proof_sha256": expected_sha256,
        "original_request_sha256": request_sha,
        "original_terminal_sha256": hashlib.sha256(proof["terminal_raw_utf8"].encode()).hexdigest(),
        "original_stderr_sha256": hashlib.sha256(stderr.encode()).hexdigest(),
        "original_controller_closeout_sha256": hashlib.sha256(proof["controller_closeout_raw_utf8"].encode()).hexdigest(),
        "historical_source_pins": {str(source_root / p): h for p, h in _UNOPENED_SOURCE_PINS.items()},
        "interpretation": "explicit_administrative_review_of_pinned_original_open_refusal",
        "new_original_native_terminal_created": False, "historical_native_release_established": False,
    }


@contextmanager
def _unopened_no_scheduler_request(scheduler, request_id, policy):
    """Observe only exact request absence; never recover, sample or persist."""
    with scheduler._locked_state(persist=False, strict_existing=True) as state:
        for name in ("leases", "waiters"):
            rows = state.get(name)
            _unopened_need(type(rows) is dict and len(rows) <= 16384,
                           "bounded complete scheduler request inventory required")
            for row in rows.values():
                resources.native_deadlines._check_resource_operation_deadline()
                _unopened_need(type(row) is dict, "invalid scheduler request record")
                _unopened_need(row.get("request_id") != request_id,
                               "original validation scheduler request is still present")
        yield {"schema": "exact-unopened-validation-request-absence/v1",
               "scheduler_state_path": str(scheduler.state_path),
               "expected_policy_sha256": policy, "request_id": request_id,
               "matching_leases": 0, "matching_waiters": 0,
               "state_written": False, "historical_release_established": False}


def reconcile_empty_unopened_validation_reservation_v1(ledger_path, *, roots,
        reservation_id, expected_record_sha256, attempt_directory,
        proof_raw, expected_proof_sha256, artifacts_durable=False,
        capacity_policy="require_capacity", ledger_lock_timeout_seconds=30):
    """Explicitly release one reviewed dead owner's empty UNOPENED reserved claim.

    This separate historical profile does not broaden retained recovery. Exact
    original request/producer/trace/terminal/controller evidence is mandatory;
    null fields alone cannot authorize recovery. The original claim stays fully
    charged through both real named-root censuses. No source/native lifecycle,
    validation qualification, admission or historical release is reconstructed.
    The final accounting is a prewrite projection; independent actual postwrite
    readback remains required, including when an atomic write raises.
    """
    _unopened_need(capacity_policy in ("require_capacity", "administrative_closeout")
        and type(capacity_policy) is str, "invalid reconciliation capacity policy")
    _unopened_need(artifacts_durable is True, "explicit durable empty attempt assertion required")
    _unopened_need(type(reservation_id) is str and re.fullmatch(r"[0-9a-f]{32}", reservation_id)
        and type(expected_record_sha256) is str and re.fullmatch(r"[0-9a-f]{64}", expected_record_sha256),
        "exact unopened reservation identity required")
    _unopened_need(type(ledger_lock_timeout_seconds) in (int, float)
        and math.isfinite(ledger_lock_timeout_seconds) and 0 <= ledger_lock_timeout_seconds <= 30,
        "bounded original ledger lock timeout required")
    ledger_path = _unopened_path(os.fspath(ledger_path), "ledger path")
    attempt = _unopened_path(os.fspath(attempt_directory), "attempt directory")
    _unopened_need(type(roots) in (list, tuple) and 1 <= len(roots) <= 64, "explicit named roots required")
    roots = [_unopened_path(os.fspath(root), "named root") for root in roots]
    request, original, closeout, proof = _unopened_proof(proof_raw, expected_proof_sha256)
    original_row = original["record"]
    _unopened_need(_digest(original_row) == expected_record_sha256
        and original_row["reservation_id"] == original["reservation_id"] == reservation_id
        and original["ledger_path"] == str(ledger_path)
        and original.get("scheduler_lane") == "validation"
        and original.get("workload") == "canonical_validation",
        "original selected reserved claim binding differs")
    _unopened_need(request["attempt_directory"] == str(attempt)
        and request["roots"] == [str(root) for root in roots], "original request paths differ")
    for key in ("storage_bytes", "cpu_slots", "memory_mb", "child_process_slots"):
        _unopened_need(type(request[key]) is int and request[key] > 0
            and type(original_row[key]) is int and original_row[key] == request[key],
            "original request and reserved budget differ")
    _unopened_need(request["outputs"] == {name: str(attempt / name)
        for name in ("pytest", "tmp", "cache", "db", "exports", "logs")}
        and request["declared_external_writable_paths"] == [], "original writable layout differs")
    scheduler_path = _unopened_path(request["scheduler_state_path"], "scheduler state path")
    policy = request["expected_scheduler_policy_sha256"]
    _unopened_need(type(policy) is str and re.fullmatch(r"[0-9a-f]{64}", policy),
                   "exact original scheduler policy required")
    from .existing_resource_scheduler import open_existing_scheduler
    scheduler = open_existing_scheduler(scheduler_path, policy, inspection_only=True)
    helper = resources.DaemonResourceReservation(ledger_path, roots=roots, storage_bytes=1,
        memory_mb=1, ledger_lock_timeout_seconds=ledger_lock_timeout_seconds,
        require_existing_ledger=True)
    attempt = resources._safe_path(attempt, directory=True)
    _unopened_need(any(root in attempt.parents for root in helper.roots), "attempt outside named roots")
    # This is the same exclusive original ledger lock, opened without creation.
    with _validation_inspection_lock(helper):
        ledger = helper._read()
        record = ledger["reservations"].get(reservation_id)
        _unopened_need(record == original_row and _digest(record) == expected_record_sha256,
                       "unopened reserved record identity changed")
        _unopened_need(original["roots"] == helper.root_identities
            and original["storage_limit_bytes"] == resources.MAX_STORAGE_BYTES,
            "original storage roots or cap differ")
        initial_ledger_sha = _digest(ledger)
        others_sha = _digest({k: v for k, v in ledger["reservations"].items() if k != reservation_id})
        def unchanged():
            helper._verify_owner_roots()
            _unopened_need(ledger["reservations"].get(reservation_id) is record
                and record == original_row and _digest(record) == expected_record_sha256,
                "selected unopened claim changed during closeout")
            _unopened_need(_digest({k: v for k, v in ledger["reservations"].items()
                if k != reservation_id}) == others_sha, "another reservation changed")
        def stopped_empty():
            unchanged()
            for pid in (record["owner_pid"], closeout["controller_pid"]):
                _unopened_need(resources._process(pid) is None,
                               "original owner or controller PID still exists")
            _unopened_need(resources._root_identity(attempt) == record["attempt_directory"],
                           "unopened attempt identity changed")
            _unopened_need(not any(attempt.iterdir()), "unopened attempt has entries")
            _unopened_need(_durable_inventory(attempt) == [] and not any(attempt.iterdir()),
                           "unopened durable inventory changed")
            _unopened_need(resources._root_identity(attempt) == record["attempt_directory"],
                           "unopened attempt identity changed during durability")
        stopped_empty()
        request_id = "validation:" + reservation_id
        with _unopened_no_scheduler_request(scheduler, request_id, policy) as first_scheduler:
            first_scheduler = copy.deepcopy(first_scheduler)
        census = _administrative_census if capacity_policy == "administrative_closeout" else None
        accounting = census(helper, ledger) if census else helper._account(ledger)
        stopped_empty()
        projected = copy.deepcopy(ledger)
        projected["reservations"][reservation_id]["status"] = "released"
        projected_sha = _digest(projected)
        final = census(helper, projected) if census else helper._account(projected)
        _unopened_need(_digest(projected) == projected_sha, "projected unopened accounting body changed")
        stopped_empty()
        _unopened_need(accounting["outstanding_full_reservations_bytes"]
            - final["outstanding_full_reservations_bytes"] == record["storage_bytes"],
            "unopened claim accounting differs")
        with _unopened_no_scheduler_request(scheduler, request_id, policy) as final_scheduler:
            stopped_empty()
            # Detect actual file replacement/body drift, not merely mutations of
            # our loaded object. Cooperating writers remain excluded by flock.
            _unopened_need(_digest(helper._read()) == initial_ledger_sha,
                           "on-disk unopened ledger changed before write")
            recovery = {"schema": "explicit-empty-unopened-reserved-reconciliation/v1",
                "reservation_id": reservation_id, "previous_status": "reserved",
                "previous_record_sha256": expected_record_sha256,
                "original_owner_pid": record["owner_pid"], "reconciled_by_pid": os.getpid(),
                "proof": proof, "other_reservations_sha256": others_sha,
                "artifacts": [], "original_claim_bytes": record["storage_bytes"],
                "full_claim_accounting": accounting, "final_accounting": final,
                "opening_scheduler_observation": first_scheduler,
                "prewrite_scheduler_observation": copy.deepcopy(final_scheduler),
                "capacity_policy": capacity_policy, "cap_changed": False,
                "final_accounting_is_prewrite_projection": True,
                "actual_postwrite_census_required": True, "fresh_global_inventory_count": 2,
                "outputs_deleted": False, "automatic_expiry": False,
                "new_reservation_created": False, "new_resource_lease_acquired": False,
                "admitted": False, "validation_qualification_claimed": False,
                "historical_native_release_established": False}
            # One direct administrative transition; never invent retained history.
            record.update(status="released", artifacts_durable_asserted=True, released_at=time.time(),
                final_accounting=final, final_attempt_bytes=0, final_external_charged_bytes=0,
                final_total_charged_bytes=0, attempt_exceeded_reservation=False,
                explicit_reconciliation=recovery)
            _unopened_need(_digest({k: v for k, v in ledger["reservations"].items()
                if k != reservation_id}) == others_sha, "another reservation changed")
            helper._verify_owner_roots()
            helper._write(ledger)
            return recovery
