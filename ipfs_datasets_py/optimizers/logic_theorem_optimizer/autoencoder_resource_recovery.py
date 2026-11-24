"""Explicit reconciliation of one dead owner's retained disk claim.

Never expires a claim by age or deletes its outputs. The caller supplies the
exact prior record and durable artifact inventory. This is an administrative
operation, separate from the original owner's resource lease lifecycle.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager, nullcontext
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
        capacity_policy="require_capacity", allow_empty_failed_admission=False,
        expected_ledger_limit_bytes=None):
    """Release exactly one retained claim after explicit, verified closeout.

    An explicit existing ledger limit is permitted only for administrative
    closeout. It binds the stored header; it never changes the ledger cap,
    admission policy, or the existing global-limit census. None preserves the
    legacy default.

    This group-only profile accepts legacy unscoped claims and exact recorded
    ``isolated_process_group_only`` custody. Other explicit scopes require
    separate recovery evidence.

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
    return _retained_reconciliation_engine(ledger_path, roots=roots, reservation_id=reservation_id,
        expected_record_sha256=expected_record_sha256, attempt_directory=attempt_directory,
        expected_artifacts=expected_artifacts, artifacts_durable=artifacts_durable,
        capacity_policy=capacity_policy, allow_empty_failed_admission=allow_empty_failed_admission,
        expected_ledger_limit_bytes=expected_ledger_limit_bytes)


def _retained_reconciliation_engine(ledger_path, *, roots, reservation_id,
        expected_record_sha256, attempt_directory, expected_artifacts, artifacts_durable=False,
        capacity_policy="require_capacity", allow_empty_failed_admission=False,
        expected_ledger_limit_bytes=None, _sampled=None, _ledger_lock_timeout_seconds=30):
    """Release exactly one retained claim after explicit, verified closeout.

    An explicit existing ledger limit is permitted only for administrative
    closeout. It binds the stored header; it never changes the ledger cap,
    admission policy, or the existing global-limit census. None preserves the
    legacy default.

    This group-only profile accepts legacy unscoped claims and exact recorded
    ``isolated_process_group_only`` custody. Other explicit scopes require
    separate recovery evidence.

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
    if expected_ledger_limit_bytes is not None:
        if capacity_policy != "administrative_closeout":
            raise resources.DaemonResourceError("explicit ledger limit requires administrative_closeout")
        if type(expected_ledger_limit_bytes) is not int or not 0 < expected_ledger_limit_bytes < (1 << 63):
            raise resources.DaemonResourceError("invalid expected ledger limit")
    if type(allow_empty_failed_admission) is not bool:
        raise resources.DaemonResourceError("invalid empty failed admission opt-in")
    if allow_empty_failed_admission and (type(expected_artifacts) is not list or expected_artifacts != []):
        raise resources.DaemonResourceError("empty failed admission requires an exact empty inventory list")
    if artifacts_durable is not True or (not allow_empty_failed_admission and not expected_artifacts):
        raise resources.DaemonResourceError("explicit durable artifact inventory required")
    storage_limit_binding = ({} if expected_ledger_limit_bytes is None else
        {"storage_limit_bytes": expected_ledger_limit_bytes})
    helper = resources.DaemonResourceReservation(ledger_path, roots=roots,
        storage_bytes=1, memory_mb=1, ledger_lock_timeout_seconds=_ledger_lock_timeout_seconds,
        require_existing_ledger=_sampled is not None, **storage_limit_binding)
    attempt = resources._safe_path(attempt_directory, directory=True)
    if not any(attempt == root or root in attempt.parents for root in helper.roots):
        raise resources.DaemonResourceError("recovery attempt outside named roots")
    with helper._locked():
        ledger = helper._read()
        record = ledger["reservations"].get(reservation_id)
        if record is None or _digest(record) != expected_record_sha256 or record["status"] != "retained":
            raise resources.DaemonResourceError("retained reservation identity changed")
        if _sampled is None and "process_scope" in record and (type(record["process_scope"]) is not str
                or record["process_scope"] != "isolated_process_group_only"):
            raise resources.DaemonResourceError("retained reservation process scope requires separate recovery evidence")
        if _sampled is not None:
            _sampled_bind(_sampled, helper, ledger, record)
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
            if _sampled is not None:
                _sampled_bind(_sampled, helper, ledger, record)
                _sampled_stopped(_sampled)
                return
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
        if _sampled is not None and _completed_compact_selection_v1(_sampled) is not None:
            _completed_compact_evidence_v1(_sampled, helper, record, inventory)
        if capacity_policy == "administrative_closeout":
            before_sha = _digest({key: value for key, value in ledger["reservations"].items()
                                  if key != reservation_id})
            accounting = _administrative_census(helper, ledger)
            unchanged_selected()
        else:
            accounting = helper._account(ledger)
        resources.native_deadlines._check_resource_operation_deadline()
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
            resources.native_deadlines._check_resource_operation_deadline()
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
        with (_sampled_write_guard(_sampled, helper, ledger, record)
                if _sampled is not None else nullcontext()):
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
            if _sampled is not None:
                recovery.update(schema="explicit-sampled-validation-reservation-reconciliation/v1",
                    process_scope="sampled_birth_bound_descendants",
                    sampled_custody_proof=copy.deepcopy(_sampled["summary"]),
                    new_reservation_created=False, new_resource_lease_acquired=False,
                    native_release_performed=False, arbitrary_descendant_completeness_claimed=False,
                capacity_policy=capacity_policy, cap_changed=False,
                final_accounting_is_prewrite_projection=True, actual_postwrite_census_required=True,
                fresh_global_inventory_count=2 if capacity_policy == "administrative_closeout" else 1)
            if _sampled is not None and _completed_compact_selection_v1(_sampled) is not None:
                compact = _completed_compact_evidence_v1(_sampled, helper, record, inventory)
                recovery.pop("artifacts")
                recovery.update(schema=_completed_compact_selection_v1(_sampled)["reconciliation"], **compact,
                    original_failure_preserved=True, request_budget_changed=False,
                    source_authority_granted=False, retroactive_qualification_claimed=False,
                    test_or_task_acceptance_asserted=False)
            record.update(status="released", artifacts_durable_asserted=True, released_at=time.time(),
                final_accounting=final, final_attempt_bytes=attempt_bytes,
                final_external_charged_bytes=0, final_total_charged_bytes=attempt_bytes,
                attempt_exceeded_reservation=False, explicit_reconciliation=recovery)
            if _digest({key: value for key, value in ledger["reservations"].items() if key != reservation_id}) != before_sha:
                raise resources.DaemonResourceError("another reservation changed")
            if capacity_policy == "administrative_closeout":
                helper._verify_owner_roots()
            resources.native_deadlines._check_resource_operation_deadline()
            if _sampled is not None and _completed_compact_selection_v1(_sampled) is not None:
                _unopened_need(len((json.dumps(ledger, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode())
                    <= resources.MAX_LEDGER_BYTES, _completed_compact_selection_v1(_sampled)["label"] + " recovery exceeds unchanged ledger byte bound")
            helper._write(ledger)
            return recovery


class _ValidationInspectionLockTimeout(resources.DaemonResourceError):
    """The inspection lock stayed busy for its bounded wait."""


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
        acquired = False
        while not acquired:
            resources.native_deadlines._check_resource_operation_deadline()
            try:
                resources.fcntl.flock(descriptor, resources.fcntl.LOCK_EX | resources.fcntl.LOCK_NB)
                acquired = True
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    break
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        resources.native_deadlines._check_resource_operation_deadline()
        current = helper.lock_path.lstat()
        if (not stat.S_ISREG(current.st_mode) or current.st_nlink != 1
                or (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino)):
            raise resources.DaemonResourceError("inspection ledger lock identity changed")
        helper._verify_owner_roots()
        if not acquired:
            resources.native_deadlines._check_resource_operation_deadline()
            raise _ValidationInspectionLockTimeout("inspection ledger lock unavailable")
        yield
    finally:
        os.close(descriptor)


def inspect_validation_reservation(ledger_path, *, roots, reservation_id,
        expected_request_sha256, attempt_directory, ledger_lock_timeout_seconds=5,
        process_scope="isolated_process_group_only"):
    """Inspect one existing validation claim without admission or recovery.

    The selected row's hash is the exact canonical digest used by the existing
    recovery API. The returned custody is recorded evidence, not a current
    scheduler observation, process census, historical release or recovery
    authorization. No foreign record or lease credential is exported.

    The default retains the original group-only profile. An explicit sampled
    profile must match the original validation owner's recorded scope exactly;
    it is not a process observation or permission to release that owner.
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
    need(type(process_scope) is str and process_scope in {
            "isolated_process_group_only", "sampled_birth_bound_descendants"},
         "explicit supported inspection process scope required")
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
             and row.get("process_scope") == process_scope,
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
            and type(original["storage_limit_bytes"]) is int and original["storage_limit_bytes"] > 0,
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


# Existing detached recovery inventories are independently bounded; this is not
# an increase to the original live-ledger or storage-admission limits.
MAX_RECOVERY_MANIFEST_BYTES = 32 * 1024 * 1024
_RELEASED_RELOCATION_SCHEMA = "released-reconciliation-artifact-relocation/v1"


def _released_metadata_file(path, maximum):
    path = resources._safe_path(path)
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o022
            or info.st_size > maximum):
        raise resources.DaemonResourceError("owned unaliased bounded released metadata required")
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _released_artifact_reference(reference, helper, attempt):
    """Read and fsync an existing descriptor; never create or scan artifacts."""
    need = _unopened_need
    need(type(reference) is dict and set(reference) == {"path", "bytes", "sha256"},
         "closed released metadata descriptor required")
    path = _unopened_path(reference["path"], "released metadata path")
    need(str(path) == reference["path"] and type(reference["bytes"]) is int
         and 0 < reference["bytes"] <= MAX_RECOVERY_MANIFEST_BYTES
         and type(reference["sha256"]) is str
         and re.fullmatch(r"[0-9a-f]{64}", reference["sha256"]),
         "exact bounded released metadata descriptor required")
    need(any(root in path.parents for root in helper.roots)
         and path not in (helper.ledger_path, helper.lock_path)
         and path != attempt and attempt not in path.parents,
         "released metadata must be a separate named-root descendant")
    witness = _released_metadata_file(path, MAX_RECOVERY_MANIFEST_BYTES)
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(path, flags), "rb") as stream:
        before = os.fstat(stream.fileno())
        identity = lambda value: (value.st_dev, value.st_ino, value.st_size,
                                  value.st_mtime_ns, value.st_ctime_ns)
        need(identity(before) == witness and before.st_uid == os.geteuid()
             and before.st_nlink == 1 and stat.S_ISREG(before.st_mode)
             and before.st_size == reference["bytes"], "released metadata identity differs")
        raw = stream.read(reference["bytes"] + 1)
        os.fsync(stream.fileno())
        need(identity(os.fstat(stream.fileno())) == witness,
             "released metadata changed while reading")
    need(len(raw) == reference["bytes"]
         and hashlib.sha256(raw).hexdigest() == reference["sha256"]
         and _released_metadata_file(path, MAX_RECOVERY_MANIFEST_BYTES) == witness,
         "released metadata bytes or identity differ")
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    need(_released_metadata_file(path, MAX_RECOVERY_MANIFEST_BYTES) == witness,
         "released metadata changed during durability")
    return _unopened_json(raw, MAX_RECOVERY_MANIFEST_BYTES, "released metadata"), witness


def _released_inline_artifacts(record, reservation_id):
    need = _unopened_need
    need(type(record) is dict and record.get("reservation_id") == reservation_id
         and record.get("status") == "released"
         and record.get("artifacts_durable_asserted") is True,
         "exact durable released archive record required")
    receipt = record.get("explicit_reconciliation")
    need(type(receipt) is dict and "artifact_metadata_relocation" not in receipt,
         "original inline released reconciliation required")
    schema = receipt.get("schema")
    if schema == "explicit-retained-reservation-batch-reconciliation/v1":
        owner = receipt.get("selected_claim")
        need(type(owner) is dict and owner.get("reservation_id") == reservation_id,
             "batch selected claim identity differs")
    else:
        need(schema in {"explicit-retained-reservation-reconciliation/v1",
                        "explicit-retained-reservation-reconciliation/v2"}
             and receipt.get("reservation_id") == reservation_id,
             "unsupported released reconciliation schema or identity")
        owner = receipt
    need(not any(name in owner for name in ("artifact_inventory_manifest", "artifact_count",
                                            "artifact_bytes", "artifact_manifest_schema")),
         "original inline receipt already has detached inventory fields")
    artifacts = owner.get("artifacts")
    need(type(artifacts) is list and 0 < len(artifacts) <= resources.MAX_INVENTORY_ENTRIES,
         "nonempty bounded original inline artifact inventory required")
    seen = set()
    for artifact in artifacts:
        need(type(artifact) is dict and set(artifact) == {"path", "bytes", "sha256"},
             "closed original artifact descriptor required")
        spelling = artifact["path"]
        need(type(spelling) is str and 0 < len(spelling) <= 4096 and "\x00" not in spelling
             and not Path(spelling).is_absolute()
             and not any(part in ("", ".", "..") for part in spelling.split("/"))
             and spelling not in seen and type(artifact["bytes"]) is int
             and artifact["bytes"] >= 0 and type(artifact["sha256"]) is str
             and re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"]),
             "exact unique typed original artifact rows required")
        seen.add(spelling)
    return receipt, artifacts


def externalize_released_reconciliation_artifacts_v1(ledger_path, *, roots,
        reservation_id, expected_record_sha256, artifact_inventory_manifest,
        released_record_archive, ledger_lock_timeout_seconds=30):
    """Relocate one already released inline inventory, with no resource release.

    Both descriptors must name preexisting durable ordinary files under the
    original named roots and outside the original attempt. The manifest uses
    retained-artifact-inventory/v1; the archive is the complete original released
    row JSON, including its receipt and literal native/outcome history. Only
    current original-owner/recorded-group absence is observed; no artifact
    payloads, scheduler or global inventory are inspected.
    Ordinary v1/v2 receipts become existing descriptor-backed v3; batch v1
    receipts become additive batch v2, with only selected_claim.artifacts
    detached. Their original complete envelopes survive verbatim in the archive.

    Retrying with the same original record digest and accepted references is
    read-only and idempotent. A write error is never rolled back or retried;
    independently read back before deciding whether the atomic write completed.
    """
    need = _unopened_need
    need(type(reservation_id) is str and re.fullmatch(r"[0-9a-f]{32}", reservation_id)
         and type(expected_record_sha256) is str
         and re.fullmatch(r"[0-9a-f]{64}", expected_record_sha256),
         "exact released reservation identity required")
    need(type(roots) in (list, tuple) and 1 <= len(roots) <= 64,
         "explicit original released metadata roots required")
    need(type(ledger_lock_timeout_seconds) in (int, float)
         and math.isfinite(ledger_lock_timeout_seconds) and 0 <= ledger_lock_timeout_seconds <= 30,
         "bounded released metadata lock timeout required")
    ledger_path = _unopened_path(os.fspath(ledger_path), "ledger path")
    roots = [_unopened_path(os.fspath(root), "named root") for root in roots]
    # Freeze supplied descriptor values, retaining their original primitive types.
    try:
        references_sha = _digest([artifact_inventory_manifest, released_record_archive])
    except (TypeError, ValueError, RecursionError) as error:
        raise resources.DaemonResourceError("bounded JSON released metadata descriptors required") from error
    manifest_ref, archive_ref = copy.deepcopy([artifact_inventory_manifest, released_record_archive])
    need(type(manifest_ref) is dict and type(archive_ref) is dict
         and manifest_ref.get("path") != archive_ref.get("path"),
         "distinct manifest and full original row archive required")
    helper = resources.DaemonResourceReservation(ledger_path, roots=roots,
        storage_bytes=1, memory_mb=1, ledger_lock_timeout_seconds=ledger_lock_timeout_seconds,
        require_existing_ledger=True)
    _released_metadata_file(helper.ledger_path, resources.MAX_LEDGER_BYTES)
    lock_witness = _released_metadata_file(helper.lock_path, resources.MAX_LEDGER_BYTES)
    with helper._locked():
        _released_metadata_file(helper.ledger_path, resources.MAX_LEDGER_BYTES)
        need(_released_metadata_file(helper.lock_path, resources.MAX_LEDGER_BYTES) == lock_witness,
             "released metadata lock identity changed")
        ledger = helper._read()
        need(_digest(ledger["roots"]) == _digest(helper.root_identities)
             and type(ledger["limit_bytes"]) is int and ledger["limit_bytes"] == resources.MAX_STORAGE_BYTES,
             "exact typed original ledger roots and cap required")
        current = ledger["reservations"].get(reservation_id)
        need(type(current) is dict and current.get("status") == "released"
             and current.get("artifacts_durable_asserted") is True,
             "only durable released reservations may relocate metadata")
        def currently_stopped():
            prior = current.get("prior_children", [])
            need(type(prior) is list and len(prior) <= 64,
                 "bounded released child history required")
            need(resources._process(current["owner_pid"]) is None,
                 "released original owner PID still exists")
            for child in [current.get("child"), *prior]:
                need(child is None or (type(child) is dict and type(child.get("pid")) is int
                     and child["pid"] > 0 and type(child.get("birth")) is str and child["birth"]),
                     "exact recorded released child identity required")
                need(not resources._group_usage(child)["live_processes"],
                     "released recorded child group is still alive")
        currently_stopped()
        attempt_identity = current.get("attempt_directory")
        need(type(attempt_identity) is dict and set(attempt_identity) == {"path", "device", "inode"}
             and type(attempt_identity["device"]) is int and attempt_identity["device"] >= 0
             and type(attempt_identity["inode"]) is int and attempt_identity["inode"] > 0,
             "exact original attempt identity required")
        attempt = _unopened_path(attempt_identity["path"], "released attempt")
        need(any(root in attempt.parents for root in helper.roots)
             and _digest(resources._root_identity(attempt)) == _digest(attempt_identity),
             "released attempt outside roots or identity changed")
        initial_ledger_sha = _digest(ledger)
        archive, archive_witness = _released_artifact_reference(archive_ref, helper, attempt)
        need(_digest(archive) == expected_record_sha256,
             "full original released record archive digest differs")
        receipt, inventory = _released_inline_artifacts(archive, reservation_id)
        need(_digest(archive.get("attempt_directory")) == _digest(attempt_identity),
             "archive belongs to another released attempt")
        manifest, manifest_witness = _released_artifact_reference(manifest_ref, helper, attempt)
        need(set(manifest) == {"schema", "attempt_directory", "artifacts"}
             and manifest["schema"] == "retained-artifact-inventory/v1"
             and _digest(manifest["attempt_directory"]) == _digest(attempt_identity)
             and _digest(manifest["artifacts"]) == _digest(inventory),
             "manifest is not the exact old inline inventory")
        byte_count = sum(row["bytes"] for row in inventory)
        need(type(archive.get("final_attempt_bytes")) is int
             and archive["final_attempt_bytes"] == byte_count,
             "released original attempt byte count differs")
        projected = copy.deepcopy(archive)
        projected_receipt = projected["explicit_reconciliation"]
        batch = receipt["schema"] == "explicit-retained-reservation-batch-reconciliation/v1"
        target = projected_receipt["selected_claim"] if batch else projected_receipt
        del target["artifacts"]
        target.update(artifact_inventory_manifest=manifest_ref, artifact_count=len(inventory),
            artifact_bytes=byte_count, artifact_manifest_schema="retained-artifact-inventory/v1")
        projected_receipt["schema"] = ("explicit-retained-reservation-batch-reconciliation/v2"
            if batch else "explicit-retained-reservation-reconciliation/v3")
        old_current = _digest(current) == expected_record_sha256
        if old_current:
            relocated_at = time.time()
        else:
            retained_receipt = current.get("explicit_reconciliation")
            need(type(retained_receipt) is dict,
                 "released record identity changed before relocation")
            retained_provenance = retained_receipt.get("artifact_metadata_relocation")
            need(type(retained_provenance) is dict,
                 "released record identity changed before relocation")
            relocated_at = retained_provenance.get("relocated_at")
            need(type(relocated_at) in (int, float) and math.isfinite(relocated_at) and relocated_at >= 0,
                 "invalid retained metadata relocation time")
        projected_receipt["artifact_metadata_relocation"] = {
            "schema": _RELEASED_RELOCATION_SCHEMA,
            "original_released_record_sha256": expected_record_sha256,
            "original_reconciliation_schema": receipt["schema"],
            "released_record_archive": archive_ref, "relocated_at": relocated_at}
        need(old_current or _digest(current) == _digest(projected),
             "released record or previously accepted references changed")
        updated = copy.deepcopy(ledger)
        updated["reservations"][reservation_id] = projected
        encode = lambda value: (json.dumps(value, sort_keys=True, separators=(",", ":"),
                                          allow_nan=False) + "\n").encode()
        before_bytes = len(encode(ledger))
        after_bytes = len(encode(updated))
        need(not old_current or after_bytes < before_bytes,
             "released metadata relocation must reduce hot ledger bytes")
        # Repeat all external evidence and the exact live ledger CAS immediately
        # before the single original atomic write; cooperating writers share flock.
        archive_again, archive_witness_again = _released_artifact_reference(archive_ref, helper, attempt)
        manifest_again, manifest_witness_again = _released_artifact_reference(manifest_ref, helper, attempt)
        need(_digest(archive_again) == _digest(archive) and archive_witness_again == archive_witness
             and _digest(manifest_again) == _digest(manifest) and manifest_witness_again == manifest_witness,
             "released metadata changed before write")
        currently_stopped()
        need(_digest([artifact_inventory_manifest, released_record_archive]) == references_sha,
             "released metadata descriptors changed during relocation")
        helper._verify_owner_roots()
        need(_digest(resources._root_identity(attempt)) == _digest(attempt_identity)
             and _released_metadata_file(helper.lock_path, resources.MAX_LEDGER_BYTES) == lock_witness,
             "released metadata roots, attempt or lock changed")
        need(_released_metadata_file(Path(archive_ref["path"]), MAX_RECOVERY_MANIFEST_BYTES) == archive_witness
             and _released_metadata_file(Path(manifest_ref["path"]), MAX_RECOVERY_MANIFEST_BYTES) == manifest_witness,
             "released metadata changed after process observation")
        _released_metadata_file(helper.ledger_path, resources.MAX_LEDGER_BYTES)
        need(_digest(helper._read()) == initial_ledger_sha,
             "on-disk released metadata ledger changed before write")
        if old_current:
            helper._write(updated)
        return {"schema": "released-reconciliation-artifact-externalization/v1",
            "reservation_id": reservation_id, "relocated_at": relocated_at,
            "original_released_record_sha256": expected_record_sha256,
            "current_record_sha256": _digest(projected),
            "artifact_inventory_manifest": copy.deepcopy(manifest_ref),
            "released_record_archive": copy.deepcopy(archive_ref),
            "artifact_count": len(inventory), "artifact_bytes": byte_count,
            "original_reconciliation_schema": receipt["schema"],
            "current_reconciliation_schema": projected_receipt["schema"],
            "ledger_bytes_before": before_bytes, "ledger_bytes_after": after_bytes,
            "hot_ledger_metadata_bytes_removed": before_bytes - after_bytes,
            "state_written": old_current, "idempotent_readback": not old_current,
            "atomic_ledger_write_count": int(old_current), "global_census_performed": False,
            "disk_promises_released": 0, "status_changed": False,
            "new_reservation_created": False, "new_resource_lease_acquired": False,
            "current_process_absence_observed_only": True,
            "native_cleanup_performed": False, "historical_native_release_established": False,
            "qualification_claimed": False, "admitted": False,
            "outputs_deleted": False, "cap_changed": False}


# Restore the existing read-only public disposition inspector without changing
# current recovery writes, deadlines, or released-artifact externalization.

def _validation_disposition_archive(reference, record, helper, ledger):
    """Read the one existing released-field archive through anchored directories.

    This verifies recorded history, not current artifact contents or native
    custody. No path outside the owner's ledger-archives directory is opened.
    """
    need = _unopened_need
    fields = {"schema", "reservation_id", "snapshot_path", "snapshot_sha256",
              "original_record_sha256", "original_field_sha256"}
    need(type(reference) is dict and set(reference) == fields
         and reference["schema"] == "released-reconciliation-archive-pointer/v1"
         and reference["reservation_id"] == record["reservation_id"],
         "closed selected reconciliation archive required")
    for key in ("snapshot_sha256", "original_record_sha256", "original_field_sha256"):
        need(type(reference[key]) is str and re.fullmatch(r"[0-9a-f]{64}", reference[key]),
             "exact reconciliation archive digest required")
    path = _unopened_path(reference["snapshot_path"], "reconciliation archive")
    archive_root = helper.ledger_path.parent / "ledger-archives"
    need(archive_root in path.parents, "reconciliation archive outside ledger archive root")
    anchors = [root for root in helper.roots if root in path.parents]
    need(bool(anchors), "reconciliation archive outside named roots")
    anchor = max(anchors, key=lambda root: len(root.parts))
    helper._verify_owner_roots()
    anchor_identity = resources._root_identity(anchor)
    descriptors, edges = [], []
    try:
        parent = os.open(anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        descriptors.append(parent)
        opened = os.fstat(parent)
        anchor_uid = opened.st_uid
        need((opened.st_dev, opened.st_ino) == (anchor_identity["device"], anchor_identity["inode"]),
             "reconciliation archive named root changed")
        parts = path.relative_to(anchor).parts
        for name in parts[:-1]:
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                            dir_fd=parent)
            descriptors.append(child)
            info = os.fstat(child)
            edges.append((parent, name, (info.st_dev, info.st_ino)))
            parent = child
        # O_PATH observes entry type without connecting a FIFO/device payload.
        # The subsequent read refers to this already verified regular inode,
        # even if another writer replaces its directory entry concurrently.
        probe = os.open(parts[-1], os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
        descriptors.append(probe)
        before = os.fstat(probe)
        maximum = 16 * 1024 * 1024  # The existing ledger byte bound is unchanged.
        need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
             and before.st_uid == anchor_uid
             and 0 < before.st_size <= maximum, "bounded unaliased reconciliation snapshot required")
        descriptor = os.open(f"/proc/self/fd/{probe}", os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        descriptors.append(descriptor)
        need((os.fstat(descriptor).st_dev, os.fstat(descriptor).st_ino)
             == (before.st_dev, before.st_ino), "reconciliation regular inode changed before read")
        blocks, count = [], 0
        while count <= before.st_size:
            resources.native_deadlines._check_resource_operation_deadline()
            block = os.read(descriptor, min(65536, before.st_size + 1 - count))
            if not block:
                break
            blocks.append(block)
            count += len(block)
        identity = lambda info: (info.st_dev, info.st_ino, info.st_size,
                                 info.st_mtime_ns, info.st_ctime_ns)
        need(count == before.st_size and identity(before) == identity(os.fstat(descriptor))
             == identity(os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)),
             "reconciliation archive changed while reading")
        for directory, name, expected in edges:
            current = os.stat(name, dir_fd=directory, follow_symlinks=False)
            need(stat.S_ISDIR(current.st_mode) and (current.st_dev, current.st_ino) == expected,
                 "reconciliation archive directory changed")
        helper._verify_owner_roots()
        need(resources._root_identity(anchor) == anchor_identity,
             "reconciliation archive named root changed")
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
    raw = b"".join(blocks)
    need(hashlib.sha256(raw).hexdigest() == reference["snapshot_sha256"],
         "reconciliation archive bytes differ")
    snapshot = _unopened_json(raw, maximum, "reconciliation archive")
    resources.native_deadlines._check_resource_operation_deadline()
    # Historical storage limits are data, never a present admission policy.
    # Existing archives legitimately precede a separately recorded cap change.
    need(all(type(value.get("limit_bytes")) is int and value["limit_bytes"] > 0
             for value in (snapshot, ledger)), "reconciliation archive storage limit is invalid")
    need(_digest({key: value for key, value in snapshot.items()
                  if key not in {"reservations", "limit_bytes"}})
         == _digest({key: value for key, value in ledger.items()
                     if key not in {"reservations", "limit_bytes"}}),
         "reconciliation archive ledger schema or named roots differ")
    reservations = snapshot.get("reservations")
    need(type(reservations) is dict, "reconciliation archive reservations missing")
    original = reservations.get(record["reservation_id"])
    need(type(original) is dict and _digest(original) == reference["original_record_sha256"],
         "reconciliation archive original record differs")
    field = original.get("explicit_reconciliation")
    need(type(field) is dict and _digest(field) == reference["original_field_sha256"]
         and field.get("schema") != "released-reconciliation-archive-pointer/v1",
         "reconciliation archive original field differs")
    reconstructed = copy.deepcopy(record)
    reconstructed["explicit_reconciliation"] = field
    need(_digest(reconstructed) == reference["original_record_sha256"],
         "reconciliation archive is not the exact selected record history")
    return field, {"path": str(path), "bytes": len(raw), "sha256": reference["snapshot_sha256"]}


def inspect_validation_disposition(ledger_path, *, roots, reservation_id,
        expected_request_sha256, attempt_directory, expected_record_sha256,
        expected_previous_record_sha256, ledger_lock_timeout_seconds=5,
        process_scope="isolated_process_group_only"):
    """Authenticate one original storage closeout without performing recovery.

    Both the current row and the original retained row are explicitly pinned.
    A released status alone proves nothing: the original reconciliation must
    bind that retained digest and preserve the exact validation custody. The
    supported released-field archive must reconstruct the full original row.
    This never inspects the scheduler, artifact tree, provider, or process
    group, and never supplies native/source/process or task acceptance credit.
    """
    need = _unopened_need
    for value in (expected_record_sha256, expected_previous_record_sha256):
        need(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value),
             "exact current and previous disposition record digests required")
    report = inspect_validation_reservation(ledger_path, roots=roots,
        reservation_id=reservation_id, expected_request_sha256=expected_request_sha256,
        attempt_directory=attempt_directory, ledger_lock_timeout_seconds=ledger_lock_timeout_seconds,
        process_scope=process_scope)
    report.update(schema="validation-storage-disposition-inspection/v1",
        storage_release_established=False, expected_previous_record_sha256=expected_previous_record_sha256,
        native_release_established=False, release_evidence=None,
        scope="selected_original_validation_storage_closeout_only")
    if not report["present"]:
        return report
    need(report["record_sha256"] == expected_record_sha256,
         "selected disposition record changed before inspection")
    helper = resources.DaemonResourceReservation(ledger_path, roots=roots,
        storage_bytes=1, memory_mb=1, require_existing_ledger=True,
        ledger_lock_timeout_seconds=ledger_lock_timeout_seconds)
    with _validation_inspection_lock(helper):
        ledger = helper._read()
        row = ledger["reservations"].get(reservation_id)
        need(type(row) is dict and _digest(row) == expected_record_sha256,
             "selected disposition record changed between inspections")
        need(type(row.get("storage_bytes")) is int and row["storage_bytes"] > 0,
             "selected disposition storage promise is invalid")
        need(resources._root_identity(Path(attempt_directory)) == report["attempt_directory"],
             "selected disposition attempt identity changed")
        if row["status"] != "released":
            report["record_reason"] = "Original selected storage custody is not released."
            return report
        reconciliation = row.get("explicit_reconciliation")
        archive = None
        if type(reconciliation) is dict and reconciliation.get("schema") == "released-reconciliation-archive-pointer/v1":
            reconciliation, archive = _validation_disposition_archive(reconciliation, row, helper, ledger)
        if type(reconciliation) is not dict:
            report["record_reason"] = "No supported original reconciliation establishes this storage release."
            return report
        schema = reconciliation.get("schema")
        direct = schema in {"explicit-retained-reservation-reconciliation/v1",
                            "explicit-retained-reservation-reconciliation/v2",
                            "explicit-retained-reservation-reconciliation/v3",
                            "explicit-sampled-validation-reservation-reconciliation/v1",
                            "explicit-direct-Tool-quota-validation-reconciliation/v1",
                            "explicit-completed-watchdog-validation-reconciliation/v1",
                            _PRIVATE_COMPLETED_LEDGER_RECONCILIATION_SCHEMA}
        batch = schema in {"explicit-retained-reservation-batch-reconciliation/v1",
                           "retained-failed-filesystem-batch-disposition/v1"}
        if not (direct or batch):
            report["record_reason"] = "Original reconciliation schema is not supported by this inspection profile."
            return report
        if schema == "explicit-direct-Tool-quota-validation-reconciliation/v1":
            _direct_tool_quota_disposition_fields(row, reconciliation, helper, Path(attempt_directory))
        if schema == _COMPLETED_WATCHDOG_RECONCILIATION_SCHEMA:
            _completed_watchdog_disposition_fields(row, reconciliation, helper, Path(attempt_directory))
        if schema == _PRIVATE_COMPLETED_LEDGER_RECONCILIATION_SCHEMA:
            _private_completed_ledger_disposition_fields_v1(row, reconciliation, helper, Path(attempt_directory))
        if schema == "explicit-sampled-validation-reservation-reconciliation/v1":
            proof = reconciliation.get("sampled_custody_proof")
            need(row.get("process_scope") == reconciliation.get("process_scope") == "sampled_birth_bound_descendants"
                 and type(proof) is dict and proof.get("schema") == "selected-original-sampled-validation-custody/v1"
                 and proof.get("historical_evidence_selected_by_caller") is True
                 and proof.get("cryptographic_execution_attestation") is False
                 and proof.get("arbitrary_descendant_completeness_claimed") is False
                 and reconciliation.get("native_release_performed") is False,
                 "sampled storage disposition provenance is invalid")
        selected = reconciliation if direct else reconciliation.get("selected_claim")
        need(type(selected) is dict and selected.get("reservation_id") == reservation_id
             and selected.get("previous_record_sha256") == expected_previous_record_sha256
             and reconciliation.get("admitted") is False
             and reconciliation.get("outputs_deleted") is False,
             "original reconciliation does not bind the selected retained record")
        if direct:
            need(reconciliation.get("original_owner_pid") == row["owner_pid"]
                 and reconciliation.get("automatic_expiry") is False
                 and row["artifacts_durable_asserted"] is True,
                 "original direct reconciliation custody differs")
            before = reconciliation.get("full_claim_accounting")
            after = reconciliation.get("final_accounting")
            need(type(before) is dict and type(after) is dict
                 and all(type(value.get("outstanding_full_reservations_bytes")) is int
                         for value in (before, after))
                 and before["outstanding_full_reservations_bytes"]
                     - after["outstanding_full_reservations_bytes"] == row["storage_bytes"]
                 and _digest(after) == _digest(row.get("final_accounting")),
                 "original direct reconciliation accounting differs")
        else:
            need(reconciliation.get("cap_changed") is False
                 and type(reconciliation.get("claim_count")) is int
                 and 0 < reconciliation["claim_count"] <= 128
                 and type(reconciliation.get("fresh_global_inventory_count")) is int
                 and reconciliation["fresh_global_inventory_count"] == 2
                 and reconciliation.get("final_accounting_is_prewrite_projection") is True
                 and reconciliation.get("actual_postwrite_census_required") is True
                 and _digest(selected.get("preserved_external_charges"))
                     == _digest(resources._external_charges(row)),
                 "original batch reconciliation custody differs")
            if schema == "retained-failed-filesystem-batch-disposition/v1":
                need(row["artifacts_durable_asserted"] is False
                     and selected.get("ordinary_artifact_durability_asserted") is False
                     and selected.get("test_or_task_acceptance_asserted") is False,
                     "failed-filesystem storage closeout cannot assert ordinary or task acceptance")
                preserved = selected.get("failed_filesystem_disposition")
                absence = selected.get("native_absence")
                need(type(preserved) is dict
                     and preserved.get("schema") == "retained-failed-filesystem-manifest/v1"
                     and type(preserved.get("attempt_directory")) is dict
                     and all(preserved["attempt_directory"].get(key) == value
                             for key, value in report["attempt_directory"].items())
                     and preserved.get("targets_followed") is False
                     and preserved.get("special_payloads_opened") is False
                     and preserved.get("ordinary_artifact_durability_asserted") is False
                     and preserved.get("test_or_task_acceptance_asserted") is False
                     and type(preserved.get("entry_count")) is int and preserved["entry_count"] > 0
                     and type(preserved.get("apparent_bytes")) is int
                     and 0 <= preserved["apparent_bytes"] <= row["storage_bytes"]
                     and type(row.get("final_attempt_bytes")) is int
                     and row["final_attempt_bytes"] == preserved["apparent_bytes"]
                     and type(row.get("final_external_charged_bytes")) is int
                     and row["final_external_charged_bytes"] == 0
                     and type(row.get("final_total_charged_bytes")) is int
                     and row["final_total_charged_bytes"] == preserved["apparent_bytes"]
                     and row.get("attempt_exceeded_reservation") is False
                     and type(preserved.get("entries_sha256")) is str
                     and re.fullmatch(r"[0-9a-f]{64}", preserved["entries_sha256"]),
                     "original failed-filesystem manifest binding differs")
                pin = preserved.get("manifest")
                need(type(pin) is dict and set(pin) == {"path", "bytes", "sha256"}
                     and type(pin["bytes"]) is int and 0 < pin["bytes"] <= 8 * 1024 * 1024
                     and type(pin["sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", pin["sha256"]),
                     "original failed-filesystem manifest descriptor differs")
                manifest_path = _unopened_path(pin["path"], "failed-filesystem manifest")
                need(any(root in manifest_path.parents for root in helper.roots)
                     and manifest_path != Path(attempt_directory)
                     and Path(attempt_directory) not in manifest_path.parents,
                     "original failed-filesystem manifest is not detached under named roots")
                need(type(absence) is dict and absence.get("lease_id") == row["native_lease_id"]
                     and absence.get("request_id") == "validation:" + reservation_id
                     and absence.get("status") == "absent"
                     and type(absence.get("descendant_count")) is int and absence["descendant_count"] == 0
                     and type(absence.get("current_policy_sha256")) is str
                     and re.fullmatch(r"[0-9a-f]{64}", absence["current_policy_sha256"])
                     and absence.get("historical_release_established") is False,
                     "original failed-filesystem native-absence binding differs")
            else:
                need(row["artifacts_durable_asserted"] is True
                     and type(selected.get("artifacts")) is list and bool(selected["artifacts"]),
                     "ordinary storage closeout durability flag differs")
        released = row.get("released_at")
        need(type(released) in (int, float) and math.isfinite(released) and released > 0,
             "original storage release time is invalid")
        helper._verify_owner_roots()
        need(_digest(helper._read()["reservations"].get(reservation_id)) == expected_record_sha256,
             "selected disposition record changed during inspection")
        report.update(storage_release_established=True, record_reason=None, release_evidence={
            "schema": schema, "reconciliation_sha256": _digest(reconciliation),
            "previous_record_sha256": expected_previous_record_sha256,
            "released_at": released, "archive": archive,
            "artifacts_reinventoried": False, "native_release_established": False,
            "historical_capacity_is_admission_authority": False,
            "test_or_task_acceptance_asserted": False})
        return report



def _sampled_pin(value, label):
    _unopened_need(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value),
                   "exact sampled recovery " + label + " SHA256 required")


def _sampled_document(raw, expected, label, maximum=4 * 1024 * 1024):
    _sampled_pin(expected, label)
    value = _unopened_json(raw, maximum, label)
    _unopened_need(hashlib.sha256(raw).hexdigest() == expected,
                   "sampled recovery " + label + " bytes differ")
    try:
        _digest(value)
    except (ValueError, TypeError, RecursionError) as error:
        raise resources.DaemonResourceError("bounded finite sampled recovery document required") from error
    return value


def _sampled_cleanup_deadline():
    deadline = resources.native_deadlines.resource_operation_deadline()
    _unopened_need(deadline is not None and deadline.cleanup_only is True,
                   "sampled recovery requires an existing absolute cleanup deadline")
    resources.native_deadlines._check_resource_operation_deadline()


def _sampled_artifacts(value):
    _unopened_need(type(value) is list and 0 < len(value) <= 4096,
                   "complete nonempty sampled recovery artifact inventory required")
    seen = set()
    for row in value:
        _unopened_need(type(row) is dict and set(row) == {"path", "bytes", "sha256"},
                       "closed sampled recovery artifact required")
        path = row["path"]
        _unopened_need(type(path) is str and 0 < len(path) <= 4096 and "\x00" not in path
            and not Path(path).is_absolute() and all(part not in {"", ".", ".."}
                for part in path.split(os.sep)) and path not in seen
            and type(row["bytes"]) is int and row["bytes"] >= 0,
            "unique relative sampled recovery artifact required")
        _sampled_pin(row["sha256"], "artifact")
        seen.add(path)
    return copy.deepcopy(value)


# This digest selects the reviewed historical control flow whose child blocks
# on stdin before execvpe; it does not authenticate a caller or attest execution.
_REVIEWED_BEFORE_BARRIER_PRODUCER_SHA256 = (
    "07b57d067461d0ca6334e667db5c913cd5fe30739731e16e162c3c861051a997"
)


def _sampled_reviewed_before_barrier_capacity(parent, request, terminal, identities, producer):
    """Recognize only a closed, original07b capacity refusal before its barrier.

    The actual original child existed and its native lease was acquired. No
    no-native or successful-command claim follows from this historical profile.
    Every current sampled engine guard remains required after this check.
    """
    need = _unopened_need
    lifecycle, failure = terminal["source_custody_lifecycle"], terminal["failure"]
    need(producer["sha256"] == _REVIEWED_BEFORE_BARRIER_PRODUCER_SHA256
        and parent.get("schema") == "legal-phase8-reviewed-producer-pytest-actual-owner-closeout/v1"
        and request["schema"] == "owned-validation-request/v4" and len(identities) == 1,
        "unreviewed original before-barrier capacity profile")
    need(set(lifecycle) == set("schema request_sha256 producer owner reservation_id resource_request_id "
        "ledger_path scheduler attempt_directory outputs budgets process_scope events owner_child_attached "
        "native_grant source_guards storage".split())
        and lifecycle["events"] == {"owner_open_attempted": True, "owner_open_returned": True,
            "child_launch_attempted": True, "child_created": True, "barrier_release_attempted": False,
            "barrier_released": False, "owner_exit_handling_completed": True}
        and all(type(value) is bool for value in lifecycle["events"].values()),
        "original before-barrier capacity lifecycle differs")
    need(set(failure) == set("schema request_sha256 executed_checks returncode completed admitted Lean_admitted "
        "resource_scope model_weights_downloaded authority_granted error_type error elapsed_seconds "
        "watchdog_errors received_signals process_observation process_cleanup_error".split())
        and failure["schema"] == "owned-validation-result/v1"
        and failure["request_sha256"] == terminal["request_sha256"]
        and failure["returncode"] is None and failure["executed_checks"] == []
        and failure["error_type"] == "DaemonResourceError"
        and failure["error"] == "storage reservation capacity exceeded"
        and failure["received_signals"] == [] and failure["watchdog_errors"] == []
        and failure["process_cleanup_error"] is None
        and type(failure["elapsed_seconds"]) in (int, float)
        and math.isfinite(failure["elapsed_seconds"]) and failure["elapsed_seconds"] > 0
        and all(failure[key] is False for key in
            ("completed", "admitted", "Lean_admitted", "authority_granted", "model_weights_downloaded"))
        and _digest(failure["process_observation"]) == _digest(terminal["reservation"]["process_observation"])
        and failure["resource_scope"] == "cooperative_sampled_birth_bound_descendants_and_owned_attempt",
        "original before-barrier capacity failure differs")


def _sampled_reviewed_producer_parent(parent, request, terminal, record, identities,
        producer, expected_request_sha256, request_raw, *, before_barrier_capacity=False):
    """Check the selected original reviewed-producer parent without adapting it.

    This is a finite historical Popen-verifier profile, not a new execution
    attestation. Current process/native absence and durable artifacts still pass
    through the existing sampled engine before any storage commit.
    """
    need = _unopened_need
    fields = set("schema original_terminal owner_pid owner_birth returncode completed errors cleanup_errors "
        "genuine_wait_completed actual_a0b_terminal_cleanup_verified all_observed_identities_gone "
        "actual_observed_identity_count owner_identity_gone child_reaped original_native_compute_closed "
        "original_source_exit_lifecycle_closed source_READ_closed source_custody_closed source_pins_unchanged "
        "opening_source_READs closing_source_READs closing_source_READ_absolute_window_satisfied "
        "closing_source_READ_clock_renewed closing_source_READ_elapsed_seconds closing_source_READ_window_seconds "
        "parent_source_READ_closed_before_Popen attempt_precreated_empty_before_original_owner "
        "automatic_retry_authorized kill_signal_or_manual_reservation_release_performed "
        "new_resource_owner_implementation_created source_qualification_or_native_Lean_or_semantic_claimed "
        "storage_status storage_artifacts_durable_asserted storage_released_and_durable retained_storage_bytes "
        "unknown_wait_no_replay elapsed_seconds plan request".split())
    need(set(parent) == fields and request["schema"] == "owned-validation-request/v4"
        and parent["schema"] == "legal-phase8-reviewed-producer-pytest-actual-owner-closeout/v1"
        and type(parent["returncode"]) is int and parent["returncode"] == 1
        and ((terminal["failure"].get("returncode") is None) if before_barrier_capacity else
             (type(terminal["failure"].get("returncode")) is int and terminal["failure"]["returncode"] == 1))
        and _digest(parent["original_terminal"]) == _digest(terminal)
        and type(parent["owner_pid"]) is int and parent["owner_pid"] == record["owner_pid"]
        and type(parent["owner_birth"]) is int and parent["owner_birth"] > 0
        and str(parent["owner_birth"]) == record["owner_birth"]
        and type(parent["actual_observed_identity_count"]) is int
        and parent["actual_observed_identity_count"] == len(identities)
        and parent["errors"] == parent["cleanup_errors"] == []
        and parent["storage_status"] == "retained"
        and type(parent["retained_storage_bytes"]) is int
        and parent["retained_storage_bytes"] == record["storage_bytes"],
        "reviewed-producer original parent/terminal custody differs")
    true_fields = ("genuine_wait_completed", "actual_a0b_terminal_cleanup_verified",
        "all_observed_identities_gone", "owner_identity_gone", "child_reaped", "original_native_compute_closed",
        "original_source_exit_lifecycle_closed", "source_READ_closed", "source_custody_closed", "source_pins_unchanged",
        "parent_source_READ_closed_before_Popen", "attempt_precreated_empty_before_original_owner",
        "closing_source_READ_absolute_window_satisfied")
    false_fields = ("completed", "automatic_retry_authorized", "kill_signal_or_manual_reservation_release_performed",
        "new_resource_owner_implementation_created", "source_qualification_or_native_Lean_or_semantic_claimed",
        "storage_artifacts_durable_asserted", "storage_released_and_durable", "unknown_wait_no_replay",
        "closing_source_READ_clock_renewed")
    need(all(parent[key] is True for key in true_fields)
        and all(parent[key] is False for key in false_fields), "reviewed-producer original closure is incomplete")
    need(type(parent["closing_source_READ_window_seconds"]) in (int, float)
        and parent["closing_source_READ_window_seconds"] == 3
        and type(parent["closing_source_READ_elapsed_seconds"]) in (int, float)
        and math.isfinite(parent["closing_source_READ_elapsed_seconds"])
        and 0 <= parent["closing_source_READ_elapsed_seconds"] < 3
        and type(parent["elapsed_seconds"]) in (int, float)
        and math.isfinite(parent["elapsed_seconds"]) and parent["elapsed_seconds"] > 0,
        "reviewed-producer original Source clock differs")
    source_root = Path(producer["path"]).parents[3]
    source_roots = (source_root, source_root.parent / "ipfs_accelerate")
    for key in ("opening_source_READs", "closing_source_READs"):
        need(type(parent[key]) is list and len(parent[key]) == 2,
             "reviewed-producer paired Source owners required")
        for row, root in zip(parent[key], source_roots, strict=True):
            need(type(row) is dict and set(row) == {"canonical_root", "cooperative", "lock_path", "mode",
                "schema_version", "waited_seconds"} and row["canonical_root"] == str(root)
                and row["lock_path"] == str(root / "workspace/control-plane/source-leases/source.lock")
                and row["mode"] == "read" and row["schema_version"] == "autoencoder-source-lease/v1"
                and row["cooperative"] is True and type(row["waited_seconds"]) in (int, float)
                and math.isfinite(row["waited_seconds"]) and row["waited_seconds"] >= 0,
                "reviewed-producer original Source owner differs")
    for key in ("plan", "request"):
        row = parent[key]
        need(type(row) is dict and set(row) == {"path", "bytes", "sha256"}
            and type(row["bytes"]) is int and 0 < row["bytes"] <= 4 * 1024**2,
            "reviewed-producer original descriptor differs")
        _unopened_path(row["path"], "reviewed-producer " + key)
        _sampled_pin(row["sha256"], "reviewed-producer " + key)
    need(parent["request"]["sha256"] == expected_request_sha256
        and parent["request"]["bytes"] == len(request_raw)
        and request["source_sha256"].get(parent["plan"]["path"]) == parent["plan"]["sha256"],
        "reviewed-producer frozen request/plan binding differs")
    need(all(type(request.get(key)) is int and request[key] == value for key, value in
        {"timeout_seconds": 120, "cpu_slots": 1, "memory_mb": 1536,
         "storage_bytes": 64 * 1024**2, "child_process_slots": 2}.items()),
        "reviewed-producer original bounded request differs")
    live = terminal["reservation"].get("live_inventory_profile")
    need(type(live) is dict and set(live) == {"schema", "request_sha256", "live_exception_active",
        "complete_resamples_observed", "max_complete_resamples", "resample_limit_scope"}
        and live["schema"] == "owned-validation-live-census/v1"
        and live["request_sha256"] == expected_request_sha256 and live["live_exception_active"] is False
        and type(live["complete_resamples_observed"]) is int and live["complete_resamples_observed"] == 0
        and type(live["max_complete_resamples"]) is int and live["max_complete_resamples"] == 1
        and live["resample_limit_scope"] == "per_logical_live_census",
        "reviewed-producer original inactive V4 receipt differs")


_REVIEWED_H16_V4_PRODUCER_SHA256 = "8a5f43b09892fbafb21060f98f546b8df3bec5135488939d9734f346577c203b"


def _sampled_reviewed_H16_V4_parent(parent, request, terminal, producer, expected_request_sha256):
    """Validate the selected nested H16 V4 completed-command/deadline failure.

    This finite historical shape neither proves its unit tests nor changes the
    original overall failure. All existing sampled current-state checks follow.
    """
    need = _unopened_need
    fields = set("schema tag owner_returncode owner_pid request_sha256 attempt_directory source_pins "
        "source_drift source_closed elapsed_seconds tests_passed_not_inferred_from_owner_exit cap_or_budget_changed "
        "recovery_performed original_owner_custody parent_capture_bytes parent_capture_allowance_bytes "
        "actual_attempt_file_bytes source_receipts".split())
    custody_fields = set("original_terminal owner_pid owner_birth returncode errors storage_status retained_storage_bytes "
        "actual_observed_identity_count storage_artifacts_durable_asserted storage_released_and_durable "
        "genuine_wait_completed actual_a0b_terminal_cleanup_verified all_observed_identities_gone owner_identity_gone "
        "child_reaped original_native_compute_closed original_source_exit_lifecycle_closed".split())
    failure = terminal["failure"]
    need(set(parent) == fields and type(parent.get("original_owner_custody")) is dict
        and set(parent["original_owner_custody"]) == custody_fields
        and producer["sha256"] == _REVIEWED_H16_V4_PRODUCER_SHA256
        and parent["schema"] == "sampled-recovery-owned-validation-observation/v1"
        and parent["tag"] == "postinstall276-live1"
        and parent["attempt_directory"] == request["attempt_directory"]
        and type(parent["owner_returncode"]) is int and parent["owner_returncode"] == 1
        and parent["tests_passed_not_inferred_from_owner_exit"] is True
        and parent["cap_or_budget_changed"] is False and parent["recovery_performed"] is False
        and type(parent["source_pins"]) is int and parent["source_pins"] == len(request["source_sha256"]) == 35
        and type(parent["elapsed_seconds"]) in (int, float) and math.isfinite(parent["elapsed_seconds"])
        and parent["elapsed_seconds"] > 0
        and type(parent["parent_capture_bytes"]) is int and 0 <= parent["parent_capture_bytes"] < 1024**2
        and type(parent["parent_capture_allowance_bytes"]) is int
        and parent["parent_capture_allowance_bytes"] == 1024**2
        and type(parent["actual_attempt_file_bytes"]) is int
        and 0 <= parent["actual_attempt_file_bytes"] <= 15 * 1024**2,
        "reviewed H16 V4 original parent differs")
    need(all(type(request.get(key)) is int and request[key] == value for key, value in
        {"timeout_seconds": 120, "cpu_slots": 1, "memory_mb": 1536,
         "storage_bytes": 16 * 1024**2, "child_process_slots": 2}.items())
        and type(failure.get("returncode")) is int and failure["returncode"] == 0
        and failure.get("error_type") == "ValidationResourceError"
        and failure.get("error") == "validation run deadline exceeded"
        and failure.get("received_signals") == []
        and type(failure.get("elapsed_seconds")) in (int, float)
        and math.isfinite(failure["elapsed_seconds"]) and failure["elapsed_seconds"] > 0,
        "reviewed H16 V4 completed command/deadline profile differs")
    live = terminal["reservation"].get("live_inventory_profile")
    need(type(live) is dict and set(live) == {"schema", "request_sha256", "live_exception_active",
        "complete_resamples_observed", "max_complete_resamples", "resample_limit_scope"}
        and live["schema"] == "owned-validation-live-census/v1"
        and live["request_sha256"] == expected_request_sha256 and live["live_exception_active"] is False
        and type(live["complete_resamples_observed"]) is int and live["complete_resamples_observed"] == 0
        and type(live["max_complete_resamples"]) is int and live["max_complete_resamples"] == 1
        and live["resample_limit_scope"] == "per_logical_live_census",
        "reviewed H16 V4 inactive live receipt differs")
    roots = (Path(producer["path"]).parents[3], Path(producer["path"]).parents[3].parent / "ipfs_accelerate")
    need(type(parent["source_receipts"]) is list and len(parent["source_receipts"]) == 2,
         "reviewed H16 paired Source receipts required")
    for row, root in zip(parent["source_receipts"], roots, strict=True):
        need(type(row) is dict and set(row) == {"canonical_root", "cooperative", "lock_path", "mode",
            "schema_version", "waited_seconds"} and row["canonical_root"] == str(root)
            and row["lock_path"] == str(root / "workspace/control-plane/source-leases/source.lock")
            and row["mode"] == "read" and row["schema_version"] == "autoencoder-source-lease/v1"
            and row["cooperative"] is True and type(row["waited_seconds"]) in (int, float)
            and math.isfinite(row["waited_seconds"]) and row["waited_seconds"] >= 0,
            "reviewed H16 original Source owner differs")


# The reviewed producer selects the historical retained-command-failure shape.
# Its digest binds source bytes; caller-selected parent custody remains a premise.
_REVIEWED_SAMPLED_V5_PRODUCER_SHA256 = (
    "280bf5bcb4d1cdc42ba91d5e1d71d6c867fb6e575833957eca7fc79d5e3228a4"
)
# Two reviewed source generations; a producer never selects an arbitrary SDK.
_REVIEWED_SAMPLED_V5_SDK_SHA256 = (
    "11e5110aa8dcf39c5b11c0bd06a6d02933052e917fa46bf6d53a5467107d6def"
)
_REVIEWED_SAMPLED_V5_COOPERATIVE_PRODUCER_SHA256 = (
    "269eca283dbe83548602a102f31d81eed1232b85d1dfbeb861cde9d17edb0d4f"
)
_REVIEWED_SAMPLED_V5_COOPERATIVE_SDK_SHA256 = (
    "4df3f7f2c6d2952550dd78153b579f4e928e9f119e697bded8a7dc001021f8d2"
)
# This finite map selects source generations only. Every existing V5 request,
# terminal, parent, source, native, process and storage predicate still applies.
_COMPLETED_LEDGER_SOURCE_PAIRS = {
    "86c8c151e559e4f4e665c475348e3a81665f008ba69298b3829d474b4873035f": "4df3f7f2c6d2952550dd78153b579f4e928e9f119e697bded8a7dc001021f8d2",
    "7ce92270e5a203b4bea00451997712ba5255ba3552728721d6457486157d57e3": "860d25af0ab629c48bb7a2c7356c7690c09fdfe81b53777777c0a41384f1b293",
}
_SAMPLED_V5_REQUEST_SCHEMA = "owned-validation-request/v5"
_SAMPLED_V5_SCRATCH_SCHEMA = "owned-validation-ordinary-scratch-live/v1"
_SAMPLED_V5_PARENT_SCHEMA = "source-held-owned-validation-v5-observation/v1"


def _sampled_source_held_v5_parent(parent, request, terminal, producer, request_sha256, ledger_path, *, _manual_private_snapshot=False, _completed_watchdog=False, _completed_ledger_finalization=False, _completed_ledger_private_snapshot=False):
    """Verify the historical V5 shape before the common custody/current-state checks."""
    need = _unopened_need
    need(type(_completed_ledger_finalization) is bool and not (_completed_ledger_finalization
         and (_manual_private_snapshot or _completed_watchdog)),
         "distinct explicit completed-ledger source profile required")
    parent_fields = set("schema request_schema ordinary_scratch_profile current_sampled_recovery_profile_qualified "
        "request_sha256 owner_pid owner_returncode source_closed source_drift original_owner_custody "
        "automatic_retry_authorized recovery_or_storage_release_authorized original_source_READs "
        "actual_original_owner_argv native_and_source_exit_verified_before_parent_Source_close state".split())
    custody_fields = set("original_terminal owner_pid owner_birth returncode errors storage_status retained_storage_bytes "
        "actual_observed_identity_count storage_artifacts_durable_asserted storage_released_and_durable "
        "genuine_wait_completed actual_a0b_terminal_cleanup_verified all_observed_identities_gone owner_identity_gone "
        "child_reaped original_native_compute_closed original_source_exit_lifecycle_closed "
        "original_completed_result_verified".split())
    custody = parent.get("original_owner_custody")
    need(set(parent) == parent_fields and parent["schema"] == _SAMPLED_V5_PARENT_SCHEMA
        and parent["request_schema"] == _SAMPLED_V5_REQUEST_SCHEMA
        and parent["ordinary_scratch_profile"] == request["ordinary_scratch_profile"]
        and parent["state"] == "ORIGINAL_OWNER_WAITED_SOURCE_CLOSED_STORAGE_SEPARATE"
        and type(parent["owner_returncode"]) is int and parent["owner_returncode"] == 1
        and parent["native_and_source_exit_verified_before_parent_Source_close"] is True
        and all(parent[key] is False for key in ("current_sampled_recovery_profile_qualified",
            "automatic_retry_authorized", "recovery_or_storage_release_authorized"))
        and type(custody) is dict and set(custody) == custody_fields
        and custody["original_completed_result_verified"] is False,
        "original Source-held V5 parent profile differs")

    need(type(_completed_ledger_private_snapshot) is bool
         and (not _completed_ledger_private_snapshot or _completed_ledger_finalization),
         "private completed-ledger selection requires the explicit completed-ledger profile")
    need(type(_manual_private_snapshot) is bool, "exact manual private snapshot selection required")
    need(type(_completed_watchdog) is bool and (not _completed_watchdog or _manual_private_snapshot),
         "completed watchdog requires explicit manual private snapshot selection")
    root = (_unopened_path(request.get("cwd"), "manual private snapshot cwd")
            if _manual_private_snapshot else Path(request["cwd"]))
    if _manual_private_snapshot:
        # A cwd is not a Source root. This explicitly selected manual profile
        # interprets both original meanings without rewriting any frame.
        snapshot = _unopened_path(request.get("cwd"), "manual private snapshot cwd")
        need(str(snapshot) == request["cwd"], "manual private snapshot cwd must be lexically normalized")
        need(type(producer) is dict and set(producer) == {"path", "sha256"},
             "manual private snapshot exact original producer required")
        path = _unopened_path(producer["path"], "manual original producer path")
        need(str(path) == producer["path"] and len(path.parts) >= 5
             and path.parts[-4:] == ("scripts", "ops", "legal_ir", "run_owned_validation.py"),
             "manual original producer path must be normalized canonical runner")
        root = path.parents[3]
        need(all(snapshot != canonical and canonical not in snapshot.parents and snapshot not in canonical.parents
                 for canonical in (root, root.parent / "ipfs_accelerate")),
             "manual private snapshot and canonical Source roots must be distinct nonoverlapping roots")
        pairs = {
            "280bf5bcb4d1cdc42ba91d5e1d71d6c867fb6e575833957eca7fc79d5e3228a4":
                "11e5110aa8dcf39c5b11c0bd06a6d02933052e917fa46bf6d53a5467107d6def",
            "269eca283dbe83548602a102f31d81eed1232b85d1dfbeb861cde9d17edb0d4f":
                "4df3f7f2c6d2952550dd78153b579f4e928e9f119e697bded8a7dc001021f8d2",
            "86c8c151e559e4f4e665c475348e3a81665f008ba69298b3829d474b4873035f":
                "4df3f7f2c6d2952550dd78153b579f4e928e9f119e697bded8a7dc001021f8d2",
            "7ce92270e5a203b4bea00451997712ba5255ba3552728721d6457486157d57e3":
                "860d25af0ab629c48bb7a2c7356c7690c09fdfe81b53777777c0a41384f1b293",
        }
        need(type(producer["sha256"]) is str and producer["sha256"] in pairs,
             "manual private snapshot finite producer/SDK pair required")
        pins = request.get("source_sha256")
        if _completed_watchdog:
            private_cli = str(snapshot / "scripts/ops/legal_ir/run_owned_validation.py")
            private_sdk = str(snapshot / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/validation_run_resources.py")
            need(type(pins) is dict and type(pins.get(private_cli)) is str and pins[private_cli] in pairs
                 and pins.get(private_sdk) == pairs[pins[private_cli]]
                 and pins.get(str(root / "scripts/ops/legal_ir/run_owned_validation.py")) == producer["sha256"]
                 and pins.get(str(root / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/validation_run_resources.py"))
                     == pairs[producer["sha256"]],
                 "completed watchdog canonical-owner/private-subject producer/SDK pins differ")
            need(type(request.get("selected_checks")) is list and request["selected_checks"]
                 and all(type(check) is str and _unopened_path(check, "private subject check").is_relative_to(snapshot)
                         and check in pins for check in request["selected_checks"]),
                 "completed watchdog selected private checks are not source-pinned below original cwd")
        else:
            need(type(pins) is dict and all(
                pins.get(str(base / "scripts/ops/legal_ir/run_owned_validation.py")) == producer["sha256"]
                and pins.get(str(base / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/validation_run_resources.py"))
                    == pairs[producer["sha256"]] for base in (root, snapshot)),
                 "manual private snapshot canonical/private producer/SDK pins differ")
        failure = terminal.get("failure")
        if _completed_watchdog:
            need(request.get("schema") == _SAMPLED_V5_REQUEST_SCHEMA
                 and type(failure) is dict and type(failure.get("returncode")) is int
                 and failure["returncode"] == 0
                 and type(request.get("selected_checks")) is list and request["selected_checks"]
                 and failure.get("executed_checks") == request["selected_checks"],
                 "completed watchdog requires the exact V5 completed dispatched body")
        else:
            need(request.get("schema") == _SAMPLED_V5_REQUEST_SCHEMA
                 and type(failure) is dict and type(failure.get("returncode")) is int
                 and failure["returncode"] != 0
                 and type(request.get("selected_checks")) is list and request["selected_checks"]
                 and failure.get("executed_checks") == request["selected_checks"],
                 "manual private snapshot requires a genuine V5 nonzero dispatched body")
    if _completed_ledger_finalization:
        root = _completed_ledger_finalization_original_scope_v1(request, producer,
            _private_snapshot=_completed_ledger_private_snapshot)
    owner_dir = root / "ipfs_datasets_py/optimizers/logic_theorem_optimizer"
    reviewed_pairs = {
        _REVIEWED_SAMPLED_V5_PRODUCER_SHA256: _REVIEWED_SAMPLED_V5_SDK_SHA256,
        _REVIEWED_SAMPLED_V5_COOPERATIVE_PRODUCER_SHA256: _REVIEWED_SAMPLED_V5_COOPERATIVE_SDK_SHA256,
        "86c8c151e559e4f4e665c475348e3a81665f008ba69298b3829d474b4873035f":
            "4df3f7f2c6d2952550dd78153b579f4e928e9f119e697bded8a7dc001021f8d2",
        "7ce92270e5a203b4bea00451997712ba5255ba3552728721d6457486157d57e3":
            "860d25af0ab629c48bb7a2c7356c7690c09fdfe81b53777777c0a41384f1b293",
    }
    need(producer["sha256"] in reviewed_pairs
        and producer["path"] == str(root / "scripts/ops/legal_ir/run_owned_validation.py")
        and all(str(owner_dir / name) in request["source_sha256"] for name in (
            "validation_run_resources.py", "autoencoder_daemon_resources.py", "resource_scheduler.py",
            "existing_resource_scheduler.py", "proof_resource_safety.py")),
        "original Source-held V5 producer or source pins differ")
    need(request["source_sha256"][str(owner_dir / "validation_run_resources.py")]
        == reviewed_pairs[producer["sha256"]],
        "original Source-held V5 producer/SDK pair differs")
    argv = parent["actual_original_owner_argv"]
    need(type(argv) is list and len(argv) == 9
        and argv[:4] == [request["argv"][0], "-B", producer["path"], "--request"]
        and argv[5:] == ["--expected-request-sha256", request_sha256, "--resource-ledger", str(ledger_path)],
        "original Source-held V5 owner invocation differs")
    _unopened_path(argv[0], "original V5 owner executable")
    _unopened_path(argv[4], "original V5 request path")
    source_reads = parent["original_source_READs"]
    roots = (root, root.parent / "ipfs_accelerate")
    need(type(source_reads) is list and len(source_reads) == len(roots),
        "original V5 paired Source READs required")
    for row, source_root in zip(source_reads, roots, strict=True):
        need(type(row) is dict and set(row) == {"canonical_root", "cooperative", "lock_path", "mode",
            "schema_version", "waited_seconds"} and row["canonical_root"] == str(source_root)
            and row["lock_path"] == str(source_root / "workspace/control-plane/source-leases/source.lock")
            and row["mode"] == "read" and row["schema_version"] == "autoencoder-source-lease/v1"
            and row["cooperative"] is True and type(row["waited_seconds"]) in (int, float)
            and 0 <= row["waited_seconds"] < 2**63, "original V5 Source READ owner differs")

    failure, lifecycle, reservation = (terminal[key] for key in
        ("failure", "source_custody_lifecycle", "reservation"))
    if _completed_ledger_finalization:
        need(set(failure) == set("schema request_sha256 executed_checks returncode completed admitted Lean_admitted "
            "resource_scope model_weights_downloaded authority_granted error_type error elapsed_seconds "
            "watchdog_errors received_signals process_observation process_cleanup_error".split())
            and type(failure["returncode"]) is int and failure["returncode"] == 0
            and failure["error_type"] == "DaemonResourceError"
            and failure["error"] == "disk ledger lock unavailable"
            and failure["watchdog_errors"] == [] and failure["received_signals"] == []
            and failure["process_cleanup_error"] is None
            and type(failure["elapsed_seconds"]) in (int, float)
            and math.isfinite(failure["elapsed_seconds"]) and 0 <= failure["elapsed_seconds"] < 2**63,
            "completed-ledger exact completed-body/finalize-lock failure required")
    elif _completed_watchdog:
        need(set(failure) == set("schema request_sha256 executed_checks returncode completed admitted Lean_admitted "
            "resource_scope model_weights_downloaded authority_granted error_type error elapsed_seconds "
            "watchdog_errors received_signals process_observation process_cleanup_error".split())
            and type(failure["returncode"]) is int and failure["returncode"] == 0
            and failure["error_type"] == "RuntimeError"
            and failure["error"] == "validation watchdog did not finish cleanly"
            and failure["watchdog_errors"] == [] and failure["received_signals"] == []
            and failure["process_cleanup_error"] is None
            and type(failure["elapsed_seconds"]) in (int, float)
            and 0 <= failure["elapsed_seconds"] < 2**63,
            "completed watchdog original successful-body/failed-outer terminal differs")
    else:
        need(set(failure) == set("schema request_sha256 executed_checks returncode completed admitted Lean_admitted "
            "resource_scope model_weights_downloaded authority_granted error_type error elapsed_seconds "
            "watchdog_errors received_signals process_observation process_cleanup_error".split())
            and failure["returncode"] != 0 and failure["error_type"] == "RuntimeError"
            and failure["error"] == f"validation command failed with returncode {failure['returncode']}"
            and failure["received_signals"] == [] and type(failure["elapsed_seconds"]) in (int, float)
            and 0 <= failure["elapsed_seconds"] < 2**63,
            "original V5 retained command failure differs")
    need(set(lifecycle) == set("schema request_sha256 producer owner reservation_id resource_request_id "
        "ledger_path scheduler attempt_directory outputs budgets process_scope events owner_child_attached "
        "native_grant source_guards storage".split())
        and set(reservation) == set("schema ledger_path reservation_id status record resource_lease process_observation "
            "cleanup_error roots scheduler_lane workload storage_limit_bytes enforcement ordinary_scratch_profile".split())
        and reservation["enforcement"] == "cooperative_admission_and_polled_usage_not_kernel_quota",
        "original V5 closed custody fields differ")
    scratch = reservation["ordinary_scratch_profile"]
    need(type(scratch) is dict and set(scratch) == {"schema", "request_sha256", "ordinary_absences_observed",
        "live_exception_active", "unseen_leaf_ownership_attested", "whole_census_resampling"}
        and scratch["schema"] == _SAMPLED_V5_SCRATCH_SCHEMA and scratch["request_sha256"] == request_sha256
        and type(scratch["ordinary_absences_observed"]) is int and 0 <= scratch["ordinary_absences_observed"] < 2**63
        and all(scratch[key] is False for key in
            ("live_exception_active", "unseen_leaf_ownership_attested", "whole_census_resampling")),
        "original V5 closed ordinary scratch receipt differs")
    lease = reservation["resource_lease"]
    need(set(lease) == set("lease_id lane owner_pid parent_lease_id cpu_slots memory_mb child_process_slots "
        "gpu_memory_mb unified_memory_mb requires_gpu acquired_at wait_seconds released cancelled".split())
        and all(type(lease[key]) is int and lease[key] == 0 for key in ("gpu_memory_mb", "unified_memory_mb"))
        and all(type(lease[key]) in (int, float) and 0 <= lease[key] < 2**63 for key in ("acquired_at", "wait_seconds")),
        "original V5 native release receipt differs")



def _sampled_manual_private_snapshot_v5_parent(parent, request, terminal, producer, request_sha256, ledger_path):
    """Explicit manual parser; preserve original cwd, Source and custody frames."""
    return _sampled_source_held_v5_parent(parent, request, terminal, producer,
        request_sha256, ledger_path, _manual_private_snapshot=True)


# This exact producer handled the ORIGINAL V4 transport and its distinct live
# inventory receipt. It does not identify V4 with the V5 scratch protocol.
_REVIEWED_SAMPLED_SOURCE_HELD_V4_PRODUCER_SHA256 = (
    "280bf5bcb4d1cdc42ba91d5e1d71d6c867fb6e575833957eca7fc79d5e3228a4"
)
_SAMPLED_SOURCE_HELD_V4_PARENT_SCHEMA = "source-held-owned-validation-v4-observation/v1"


def _sampled_source_held_v4_parent(parent, request, terminal, producer, request_sha256, ledger_path):
    """Verify the historical Source-held V4 shape before the common custody/current-state checks."""
    need = _unopened_need
    parent_fields = set("schema request_schema live_inventory_profile current_sampled_recovery_profile_qualified "
        "request_sha256 owner_pid owner_returncode source_closed source_drift original_owner_custody "
        "automatic_retry_authorized recovery_or_storage_release_authorized original_source_READs "
        "actual_original_owner_argv native_and_source_exit_verified_before_parent_Source_close state".split())
    custody_fields = set("original_terminal owner_pid owner_birth returncode errors storage_status retained_storage_bytes "
        "actual_observed_identity_count storage_artifacts_durable_asserted storage_released_and_durable "
        "genuine_wait_completed actual_a0b_terminal_cleanup_verified all_observed_identities_gone owner_identity_gone "
        "child_reaped original_native_compute_closed original_source_exit_lifecycle_closed "
        "original_completed_result_verified".split())
    custody = parent.get("original_owner_custody")
    need(set(parent) == parent_fields and parent["schema"] == _SAMPLED_SOURCE_HELD_V4_PARENT_SCHEMA
        and parent["request_schema"] == "owned-validation-request/v4"
        and _digest(parent["live_inventory_profile"]) == _digest(request["live_inventory_profile"])
        and parent["state"] == "ORIGINAL_OWNER_WAITED_SOURCE_CLOSED_STORAGE_SEPARATE"
        and type(parent["owner_returncode"]) is int and parent["owner_returncode"] == 1
        and parent["native_and_source_exit_verified_before_parent_Source_close"] is True
        and all(parent[key] is False for key in ("current_sampled_recovery_profile_qualified",
            "automatic_retry_authorized", "recovery_or_storage_release_authorized"))
        and type(custody) is dict and set(custody) == custody_fields
        and custody["original_completed_result_verified"] is False,
        "original Source-held V4 parent profile differs")

    root = Path(request["cwd"])
    owner_dir = root / "ipfs_datasets_py/optimizers/logic_theorem_optimizer"
    need(producer["sha256"] == _REVIEWED_SAMPLED_SOURCE_HELD_V4_PRODUCER_SHA256
        and producer["path"] == str(root / "scripts/ops/legal_ir/run_owned_validation.py")
        and all(str(owner_dir / name) in request["source_sha256"] for name in (
            "validation_run_resources.py", "autoencoder_daemon_resources.py", "resource_scheduler.py",
            "existing_resource_scheduler.py", "proof_resource_safety.py")),
        "original Source-held V4 producer or source pins differ")
    argv = parent["actual_original_owner_argv"]
    need(type(argv) is list and len(argv) == 9
        and argv[:4] == [request["argv"][0], "-B", producer["path"], "--request"]
        and argv[5:] == ["--expected-request-sha256", request_sha256, "--resource-ledger", str(ledger_path)],
        "original Source-held V4 owner invocation differs")
    _unopened_path(argv[0], "original Source-held V4 owner executable")
    _unopened_path(argv[4], "original Source-held V4 request path")
    source_reads = parent["original_source_READs"]
    roots = (root, root.parent / "ipfs_accelerate")
    need(type(source_reads) is list and len(source_reads) == len(roots),
        "original Source-held V4 paired Source READs required")
    for row, source_root in zip(source_reads, roots, strict=True):
        need(type(row) is dict and set(row) == {"canonical_root", "cooperative", "lock_path", "mode",
            "schema_version", "waited_seconds"} and row["canonical_root"] == str(source_root)
            and row["lock_path"] == str(source_root / "workspace/control-plane/source-leases/source.lock")
            and row["mode"] == "read" and row["schema_version"] == "autoencoder-source-lease/v1"
            and row["cooperative"] is True and type(row["waited_seconds"]) in (int, float)
            and 0 <= row["waited_seconds"] < 2**63, "original Source-held V4 Source READ owner differs")

    failure, lifecycle, reservation = (terminal[key] for key in
        ("failure", "source_custody_lifecycle", "reservation"))
    need(set(failure) == set("schema request_sha256 executed_checks returncode completed admitted Lean_admitted "
        "resource_scope model_weights_downloaded authority_granted error_type error elapsed_seconds "
        "watchdog_errors received_signals process_observation process_cleanup_error".split())
        and failure["returncode"] != 0 and failure["error_type"] == "RuntimeError"
        and failure["error"] == f"validation command failed with returncode {failure['returncode']}"
        and failure["received_signals"] == [] and type(failure["elapsed_seconds"]) in (int, float)
        and 0 <= failure["elapsed_seconds"] < 2**63,
        "original Source-held V4 retained command failure differs")
    need(set(lifecycle) == set("schema request_sha256 producer owner reservation_id resource_request_id "
        "ledger_path scheduler attempt_directory outputs budgets process_scope events owner_child_attached "
        "native_grant source_guards storage".split())
        and set(reservation) == set("schema ledger_path reservation_id status record resource_lease process_observation "
            "cleanup_error roots scheduler_lane workload storage_limit_bytes enforcement live_inventory_profile".split())
        and reservation["enforcement"] == "cooperative_admission_and_polled_usage_not_kernel_quota",
        "original Source-held V4 closed custody fields differ")
    live = reservation["live_inventory_profile"]
    need(type(live) is dict and set(live) == {"schema", "max_complete_resamples", "request_sha256",
        "complete_resamples_observed", "live_exception_active", "resample_limit_scope"}
        and live["schema"] == "owned-validation-live-census/v1" and live["request_sha256"] == request_sha256
        and type(live["max_complete_resamples"]) is int and live["max_complete_resamples"] == 1
        and type(live["complete_resamples_observed"]) is int and live["complete_resamples_observed"] == 0
        and live["live_exception_active"] is False
        and live["resample_limit_scope"] == "per_logical_live_census",
        "original Source-held V4 closed live inventory receipt differs")
    lease = reservation["resource_lease"]
    need(set(lease) == set("lease_id lane owner_pid parent_lease_id cpu_slots memory_mb child_process_slots "
        "gpu_memory_mb unified_memory_mb requires_gpu acquired_at wait_seconds released cancelled".split())
        and all(type(lease[key]) is int and lease[key] == 0 for key in ("gpu_memory_mb", "unified_memory_mb"))
        and all(type(lease[key]) in (int, float) and 0 <= lease[key] < 2**63 for key in ("acquired_at", "wait_seconds")),
        "original Source-held V4 native release receipt differs")


def _sampled_proof(proof_raw, *, expected_proof_sha256, expected_request_sha256,
        expected_terminal_sha256, expected_stdout_sha256, expected_parent_closeout_sha256, expected_producer_sha256,
        ledger_path, roots, reservation_id, expected_record_sha256, attempt_directory,
        expected_artifacts, artifacts_durable, _manual_private_snapshot=False, _completed_watchdog=False, _completed_ledger_finalization=False, _completed_ledger_private_snapshot=False):
    """Bind selected original documents, never attest execution from a digest.

    The original parent's genuine Popen verification is a caller-selected
    historical custody premise. This profile checks its exact complete bytes
    and cross-bindings; it neither invents a Popen handle nor reruns a producer.
    The original v1 nested parent, reviewed V4 profiles, and reviewed
    Source-held V5 retained command failure use the same live guards.
    """
    need = _unopened_need
    need(type(_completed_ledger_finalization) is bool and not (_completed_ledger_finalization
         and (_manual_private_snapshot or _completed_watchdog)),
         "distinct explicit completed-ledger proof profile required")
    need(type(_completed_ledger_private_snapshot) is bool
         and (not _completed_ledger_private_snapshot or _completed_ledger_finalization),
         "private completed-ledger selection requires the explicit completed-ledger profile")
    need(type(_manual_private_snapshot) is bool, "exact manual private snapshot selection required")
    need(type(_completed_watchdog) is bool and (not _completed_watchdog or _manual_private_snapshot),
         "completed watchdog requires explicit manual private snapshot selection")
    _sampled_cleanup_deadline()
    need(artifacts_durable is True, "explicit sampled artifact durability assertion required")
    _sampled_pin(expected_record_sha256, "record")
    need(type(reservation_id) is str and re.fullmatch(r"[0-9a-f]{32}", reservation_id),
         "exact sampled reservation ID required")
    ledger_path = _unopened_path(os.fspath(ledger_path), "sampled ledger path")
    attempt = _unopened_path(os.fspath(attempt_directory), "sampled attempt")
    need(type(roots) in (list, tuple) and 1 <= len(roots) <= 64, "explicit sampled named roots required")
    roots = [_unopened_path(os.fspath(root), "sampled named root") for root in roots]
    need(any(root in attempt.parents for root in roots), "sampled attempt must be below a named root")
    artifacts = (_completed_watchdog_artifacts(expected_artifacts) if (_completed_watchdog or _completed_ledger_private_snapshot)
                 else _sampled_artifacts(expected_artifacts))
    proof = _sampled_document(proof_raw, expected_proof_sha256, "proof", 4 * 1024 * 1024)
    need(set(proof) == {"schema", "request_raw_utf8", "terminal_raw_utf8", "stdout_raw_utf8", "parent_closeout_raw_utf8",
        "producer_source_utf8", "provenance"}
        and proof["schema"] == "sampled-validation-recovery-proof/v1"
        and proof["provenance"] == "original_parent_popen_verified_closeout/v1",
        "closed original sampled recovery provenance required")
    need(all(type(proof[key]) is str for key in ("request_raw_utf8", "terminal_raw_utf8",
        "stdout_raw_utf8", "parent_closeout_raw_utf8", "producer_source_utf8")), "original sampled UTF8 buffers required")
    try:
        buffers = {key: proof[key].encode("utf-8") for key in ("request_raw_utf8", "terminal_raw_utf8",
            "stdout_raw_utf8", "parent_closeout_raw_utf8", "producer_source_utf8")}
    except UnicodeError as error:
        raise resources.DaemonResourceError("original sampled buffers must be valid UTF8") from error
    request = _sampled_document(buffers["request_raw_utf8"], expected_request_sha256,
                                "original request", 1024 * 1024)
    terminal = _sampled_document(proof["terminal_raw_utf8"].encode(), expected_terminal_sha256,
                                 "original terminal")
    stdout_terminal = _sampled_document(buffers["stdout_raw_utf8"], expected_stdout_sha256,
        "original stdout")
    need(_digest(stdout_terminal) == _digest(terminal), "original stdout does not contain exactly the selected terminal")
    parent = _sampled_document(buffers["parent_closeout_raw_utf8"],
                              expected_parent_closeout_sha256, "original parent closeout")
    _sampled_pin(expected_producer_sha256, "original producer")
    producer_raw = buffers["producer_source_utf8"]
    need(0 < len(producer_raw) <= 4 * 1024 * 1024
         and hashlib.sha256(producer_raw).hexdigest() == expected_producer_sha256,
         "original sampled producer capture differs")
    request_fields = set("schema argv cwd selected_checks source_sha256 timeout_seconds storage_bytes memory_mb "
        "cpu_slots child_process_slots attempt_directory outputs declared_external_writable_paths process_scope "
        "scheduler_state_path expected_scheduler_policy_sha256 roots".split())
    if request.get("schema") == "owned-validation-request/v4":
        need(set(request) == request_fields | {"live_inventory_profile"}
            and type(request["live_inventory_profile"]) is dict
            and set(request["live_inventory_profile"]) == {"schema", "max_complete_resamples"}
            and request["live_inventory_profile"]["schema"] == "owned-validation-live-census/v1"
            and type(request["live_inventory_profile"]["max_complete_resamples"]) is int
            and request["live_inventory_profile"]["max_complete_resamples"] == 1,
            "original sampled V4 request profile differs")
    elif request.get("schema") == _SAMPLED_V5_REQUEST_SCHEMA:
        need(set(request) == request_fields | {"ordinary_scratch_profile"}
            and request["ordinary_scratch_profile"] == {"schema": _SAMPLED_V5_SCRATCH_SCHEMA},
            "original sampled V5 request profile differs")
    else:
        need(set(request) == request_fields and request["schema"] == "owned-validation-request/v1",
             "original sampled request version differs")
    need(request["process_scope"] == "sampled_birth_bound_descendants"
         and request["roots"] == [str(root) for root in roots]
         and request["attempt_directory"] == str(attempt)
         and request["outputs"] == {name: str(attempt / name) for name in
             ("pytest", "tmp", "cache", "db", "exports", "logs")}
         and request["declared_external_writable_paths"] == [], "original sampled request scope differs")
    if _completed_ledger_finalization:
        need(request.get("schema") == _SAMPLED_V5_REQUEST_SCHEMA
             and parent.get("schema") == _SAMPLED_V5_PARENT_SCHEMA,
             "completed-ledger exact V5 Source-held transport required")
    for key in ("argv", "selected_checks"):
        need(type(request[key]) is list and 0 < len(request[key]) <= 256
            and all(type(x) is str and 0 < len(x) <= 8192 and "\x00" not in x for x in request[key]),
            "bounded original sampled command/checks required")
    need(len(set(request["selected_checks"])) == len(request["selected_checks"]),
         "duplicate original sampled checks")
    need(type(request["source_sha256"]) is dict and 1 <= len(request["source_sha256"]) <= 256,
         "original sampled source pin population required")
    for path, pin in request["source_sha256"].items():
        _unopened_path(path, "original sampled source")
        _sampled_pin(pin, "original source")
    need(type(request["timeout_seconds"]) in (int, float) and math.isfinite(request["timeout_seconds"])
         and request["timeout_seconds"] > 0, "original sampled timeout is invalid")
    _unopened_path(request["cwd"], "original sampled cwd")
    _unopened_path(request["scheduler_state_path"], "original sampled scheduler")
    _sampled_pin(request["expected_scheduler_policy_sha256"], "original scheduler policy")
    need(set(terminal) == {"schema", "request_sha256", "completed", "admitted", "Lean_admitted", "failure",
        "reservation", "process_cleanup_error", "owner_exit_error", "source_custody_lifecycle"}
        and terminal["schema"] == "owned-validation-failure-terminal/v1"
        and terminal["request_sha256"] == expected_request_sha256
        and terminal["completed"] is False and terminal["admitted"] is False
        and terminal["Lean_admitted"] is False and terminal["process_cleanup_error"] is None
        and terminal["owner_exit_error"] is None, "original admitted sampled failure terminal required")
    reservation, lifecycle, failure = terminal["reservation"], terminal["source_custody_lifecycle"], terminal["failure"]
    need(type(reservation) is dict and type(lifecycle) is dict and type(failure) is dict,
         "original sampled custody frames required")
    if _manual_private_snapshot:
        need(request.get("schema") == _SAMPLED_V5_REQUEST_SCHEMA
             and parent.get("schema") == _SAMPLED_V5_PARENT_SCHEMA
             and parent.get("source_closed") is True and parent.get("source_drift") == []
             and type(failure.get("returncode")) is int
             and (failure["returncode"] == 0 if _completed_watchdog else failure["returncode"] != 0)
             and type(lifecycle.get("events")) is dict
             and lifecycle["events"].get("barrier_release_attempted") is True,
             "manual private snapshot requires exact closed V5 Source-held nonzero-body provenance")
    record, lease, observation = reservation.get("record"), reservation.get("resource_lease"), reservation.get("process_observation")
    record_fields = set("artifacts_durable_asserted attempt_directory child child_process_slots cpu_slots created_at "
        "external_charges last_usage memory_mb native_lease_id outputs owner_birth owner_pid prior_children process_scope "
        "reservation_id retention_reason scheduler_lane scheduler_policy_sha256 scheduler_state_path status storage_bytes "
        "validation_request_sha256 workload".split())
    need(type(record) is dict and set(record) == record_fields and _digest(record) == expected_record_sha256
        and record["reservation_id"] == reservation_id and record["status"] == reservation.get("status") == "retained"
        and record["retention_reason"] == "context_failed" and record["artifacts_durable_asserted"] is False
        and record["external_charges"] == {} and record["prior_children"] == []
        and record["scheduler_lane"] == reservation.get("scheduler_lane") == "validation"
        and record["workload"] == reservation.get("workload") == "canonical_validation"
        and reservation.get("schema") == resources.SCHEMA and reservation.get("reservation_id") == reservation_id
        and type(reservation.get("storage_limit_bytes")) is int
        and reservation["storage_limit_bytes"] > 0
        and reservation.get("ledger_path") == str(ledger_path) and reservation.get("cleanup_error") is None
        and record["validation_request_sha256"] == expected_request_sha256
        and record["process_scope"] == request["process_scope"]
        and record["outputs"] == request["outputs"]
        and record["scheduler_state_path"] == request["scheduler_state_path"]
        and record["scheduler_policy_sha256"] == request["expected_scheduler_policy_sha256"],
        "original sampled retained custody binding differs")
    original_roots = reservation.get("roots")
    need(type(original_roots) is list and len(original_roots) == len(roots)
        and all(type(row) is dict and set(row) == {"path", "device", "inode"}
            and row["path"] == str(root) and type(row["device"]) is int and row["device"] >= 0
            and type(row["inode"]) is int and row["inode"] > 0
            for row, root in zip(original_roots, roots, strict=True)), "original sampled named-root identities differ")
    need(type(record["owner_pid"]) is int and record["owner_pid"] > 0
         and type(record["owner_birth"]) is str and re.fullmatch(r"[0-9]{1,32}", record["owner_birth"]),
         "exact original sampled owner identity required")
    need(type(record["native_lease_id"]) is str and re.fullmatch(r"[0-9a-f]{32}", record["native_lease_id"]),
         "exact original sampled native lease required")
    for key in ("storage_bytes", "memory_mb", "cpu_slots", "child_process_slots"):
        need(type(record[key]) is int and record[key] > 0 and type(request[key]) is int
             and record[key] == request[key], "original sampled budget differs")
    need(type(lease) is dict and lease.get("lease_id") == record["native_lease_id"]
        and lease.get("owner_pid") == record["owner_pid"] and type(lease.get("owner_pid")) is int
        and lease.get("lane") == "validation" and lease.get("parent_lease_id") is None
        and lease.get("released") is True and lease.get("cancelled") is True
        and lease.get("requires_gpu") is False
        and all(type(lease.get(key)) is int and lease[key] == record[key]
            for key in ("cpu_slots", "memory_mb", "child_process_slots")),
        "original sampled native release binding differs")
    identity = record["attempt_directory"]
    need(type(identity) is dict and set(identity) == {"path", "device", "inode"}
         and identity["path"] == str(attempt) and type(identity["device"]) is int and identity["device"] >= 0
         and type(identity["inode"]) is int and identity["inode"] > 0, "exact original sampled directory identity required")
    child = record["child"]
    need(type(child) is dict and set(child) == {"pid", "birth"}
         and type(child["pid"]) is int and child["pid"] > 0 and child["pid"] != record["owner_pid"]
         and type(child["birth"]) is str and re.fullmatch(r"[0-9]{1,32}", child["birth"]),
         "original sampled attached child identity required")
    need(type(observation) is dict and set(observation) == {"scope", "group_rss", "live_processes", "rss_bytes",
        "observed_identities", "out_of_group_live_identities", "tracking_error"}
        and observation["scope"] == request["process_scope"]
        and type(observation["live_processes"]) is int and observation["live_processes"] == 0
        and type(observation["rss_bytes"]) is int and observation["rss_bytes"] == 0
        and observation["out_of_group_live_identities"] == [] and observation["tracking_error"] == ""
        and type(observation["group_rss"]) is dict and set(observation["group_rss"]) == {"available", "live_processes", "rss_bytes"}
        and observation["group_rss"]["available"] is True
        and all(type(observation["group_rss"][key]) is int and observation["group_rss"][key] == 0
                for key in ("live_processes", "rss_bytes")), "original sampled zero-process observation required")
    identities, seen = observation["observed_identities"], set()
    need(type(identities) is list and 1 <= len(identities) <= 100000, "complete bounded original sampled history required")
    for item in identities:
        need(type(item) is dict and set(item) == {"pid", "birth_ticks", "parent_pid", "process_group_id", "session_id"}
            and all(type(item[key]) is int and item[key] > 0 for key in item)
            and item["pid"] not in seen and item["pid"] != record["owner_pid"],
            "unique exact original sampled identity required")
        seen.add(item["pid"])
    need(any(item["pid"] == child["pid"] and str(item["birth_ticks"]) == child["birth"]
        and item["parent_pid"] == record["owner_pid"] and item["process_group_id"] == child["pid"]
        and item["session_id"] == child["pid"] for item in identities), "attached child missing from original sampled history")
    producer = lifecycle.get("producer")
    need(type(producer) is dict and set(producer) == {"path", "sha256"}
        and type(producer["path"]) is str and producer["path"].endswith("/scripts/ops/legal_ir/run_owned_validation.py")
        and producer["sha256"] == expected_producer_sha256
        and request["source_sha256"].get(producer["path"]) == expected_producer_sha256,
        "captured original sampled producer/request binding differs")
    completed_storage_limits = None
    if _completed_watchdog or _completed_ledger_finalization:
        owner_root = Path(producer["path"]).parents[3]
        resource_path = str(owner_root / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py")
        completed_storage_limits = _completed_watchdog_storage_limits(
            reservation["storage_limit_bytes"], resources.MAX_STORAGE_BYTES,
            request["source_sha256"].get(resource_path))
        if _completed_ledger_finalization:
            need(reservation["storage_limit_bytes"] == resources.MAX_STORAGE_BYTES,
                 "completed-ledger original and current storage cap must match")
    need(lifecycle.get("schema") == "owned-validation-source-custody-lifecycle/v1"
        and lifecycle.get("request_sha256") == expected_request_sha256
        and _digest(lifecycle.get("owner")) == _digest({"pid": record["owner_pid"], "birth": record["owner_birth"]})
        and lifecycle.get("reservation_id") == reservation_id
        and lifecycle.get("resource_request_id") == "validation:" + reservation_id
        and lifecycle.get("ledger_path") == str(ledger_path)
        and lifecycle.get("attempt_directory") == str(attempt)
        and lifecycle.get("outputs") == request["outputs"]
        and _digest(lifecycle.get("budgets")) == _digest({key: record[key] for key in ("cpu_slots", "memory_mb", "child_process_slots", "storage_bytes")})
        and lifecycle.get("process_scope") == request["process_scope"]
        and lifecycle.get("scheduler") == {"state_path": request["scheduler_state_path"],
            "policy_sha256": request["expected_scheduler_policy_sha256"], "lane": "validation", "workload": "canonical_validation"}
        and lifecycle.get("owner_child_attached") is True
        and _digest(lifecycle.get("native_grant")) == _digest({"status": "acquired", "exact_native_timeout": False, "timeout_decision": None})
        and _digest(lifecycle.get("source_guards")) == _digest({"request_unchanged": True, "source_pins_unchanged": True,
            "owner_identity_unchanged": True, "errors": []})
        and _digest(lifecycle.get("storage")) == _digest({"status": "retained", "cleanup_error": None, "release_authorized": False}),
        "original sampled lifecycle binding differs")
    event_names = {"owner_open_attempted", "owner_open_returned", "child_launch_attempted", "child_created",
        "barrier_release_attempted", "barrier_released", "owner_exit_handling_completed"}
    before_barrier_capacity = (type(lifecycle.get("events")) is dict
        and lifecycle["events"].get("barrier_release_attempted") is False)
    if before_barrier_capacity:
        _sampled_reviewed_before_barrier_capacity(parent, request, terminal, identities, producer)
    else:
        need(type(lifecycle.get("events")) is dict and set(lifecycle["events"]) == event_names
             and all(value is True for value in lifecycle["events"].values()), "original sampled exit handling incomplete")
        need(failure.get("schema") == "owned-validation-result/v1" and failure.get("request_sha256") == expected_request_sha256
            and type(failure.get("returncode")) is int and -128 <= failure["returncode"] <= 255
            and failure.get("completed") is False and failure.get("executed_checks") == request["selected_checks"]
            and _digest(failure.get("process_observation")) == _digest(observation)
            and failure.get("process_cleanup_error") is None and failure.get("watchdog_errors") == []
            and all(failure.get(key) is False for key in ("admitted", "Lean_admitted", "authority_granted", "model_weights_downloaded"))
            and failure.get("resource_scope") == "cooperative_sampled_birth_bound_descendants_and_owned_attempt",
            "original sampled failed-command observation differs")
    if parent.get("schema") == "legal-phase8-reviewed-producer-pytest-actual-owner-closeout/v1":
        _sampled_reviewed_producer_parent(parent, request, terminal, record, identities,
            producer, expected_request_sha256, buffers["request_raw_utf8"],
            before_barrier_capacity=before_barrier_capacity)
        original_cli_returncode = parent["returncode"]
    else:
        parent_schema = "sampled-recovery-owned-validation-observation/v1"
        if request["schema"] == "owned-validation-request/v4":
            if parent.get("schema") == _SAMPLED_SOURCE_HELD_V4_PARENT_SCHEMA:
                _sampled_source_held_v4_parent(parent, request, terminal, producer, expected_request_sha256, ledger_path)
                parent_schema = _SAMPLED_SOURCE_HELD_V4_PARENT_SCHEMA
            else:
                _sampled_reviewed_H16_V4_parent(parent, request, terminal, producer, expected_request_sha256)
        elif request["schema"] == _SAMPLED_V5_REQUEST_SCHEMA:
            if _completed_ledger_finalization:
                _sampled_source_held_v5_parent(parent, request, terminal, producer, expected_request_sha256,
                    ledger_path, _completed_ledger_finalization=True,
                    _completed_ledger_private_snapshot=_completed_ledger_private_snapshot)
            elif _completed_watchdog:
                _sampled_source_held_v5_parent(parent, request, terminal, producer, expected_request_sha256,
                    ledger_path, _manual_private_snapshot=True, _completed_watchdog=True)
            elif _manual_private_snapshot:
                _sampled_manual_private_snapshot_v5_parent(parent, request, terminal, producer,
                    expected_request_sha256, ledger_path)
            else:
                _sampled_source_held_v5_parent(parent, request, terminal, producer, expected_request_sha256, ledger_path)
            parent_schema = _SAMPLED_V5_PARENT_SCHEMA
        else:
            need(request["schema"] == "owned-validation-request/v1",
                 "original sampled parent/request profile differs")
        custody = parent.get("original_owner_custody")
        need(parent.get("schema") == parent_schema
            and parent.get("source_closed") is True and parent.get("source_drift") == []
            and parent.get("request_sha256") == expected_request_sha256
            and type(parent.get("owner_returncode")) is int
            and -128 <= parent["owner_returncode"] <= 255 and parent["owner_returncode"] != 0
            and parent.get("owner_pid") == record["owner_pid"] and type(parent.get("owner_pid")) is int
            and type(custody) is dict and _digest(custody.get("original_terminal")) == _digest(terminal)
            and custody.get("owner_pid") == record["owner_pid"] and type(custody.get("owner_pid")) is int
            and custody.get("owner_birth") == record["owner_birth"]
            and type(custody.get("returncode")) is int and custody["returncode"] == parent["owner_returncode"]
            and custody.get("errors") == [] and custody.get("storage_status") == "retained"
            and type(custody.get("actual_observed_identity_count")) is int
            and custody["actual_observed_identity_count"] == len(identities)
            and custody.get("storage_artifacts_durable_asserted") is False
            and custody.get("storage_released_and_durable") is False
            and type(custody.get("retained_storage_bytes")) is int and custody["retained_storage_bytes"] == record["storage_bytes"]
            and all(custody.get(key) is True for key in ("genuine_wait_completed", "actual_a0b_terminal_cleanup_verified",
                "all_observed_identities_gone", "owner_identity_gone", "child_reaped", "original_native_compute_closed",
                "original_source_exit_lifecycle_closed")), "selected original Popen-verified parent closeout differs")
        original_cli_returncode = parent["owner_returncode"]
    summary = {"schema": "selected-original-sampled-validation-custody/v1", "proof_sha256": expected_proof_sha256,
        "request_sha256": expected_request_sha256, "terminal_sha256": expected_terminal_sha256,
        "stdout_sha256": expected_stdout_sha256, "parent_closeout_sha256": expected_parent_closeout_sha256, "producer_sha256": expected_producer_sha256,
        "historical_evidence_selected_by_caller": True, "cryptographic_execution_attestation": False,
        "reconstructed_Popen_handle": False, "original_failure_preserved": True,
        "original_command_returncode": failure["returncode"], "original_cli_returncode": original_cli_returncode,
        "scope": "original_cooperative_sampled_birth_bound_observations_only",
        "arbitrary_descendant_completeness_claimed": False, "observed_identity_count": len(identities)}
    if before_barrier_capacity:
        summary.update(original_failure_profile="reviewed-before-barrier-capacity-refusal/v1",
            original_command_dispatch="original_barrier_never_attempted")
    if request["schema"] == _SAMPLED_V5_REQUEST_SCHEMA:
        summary["original_failure_profile"] = "source-held-V5-retained-command-failure/v1"
    if _manual_private_snapshot:
        summary.update(original_failure_profile="manual-private-snapshot-source-held-V5-retained-command-failure/v1",
            manual_private_snapshot_optin=True,
            canonical_source_owner_root=str(Path(producer["path"]).parents[3]),
            original_working_directory=request["cwd"])

    if _completed_watchdog:
        root = Path(producer["path"]).parents[3]
        snapshot = Path(request["cwd"])
        summary.update(original_failure_profile=_COMPLETED_WATCHDOG_FAILURE_PROFILE,
            **completed_storage_limits,
            completed_body_watchdog_finalization_optin=True,
            original_owner_completed=False, retroactive_qualification_claimed=False,
            canonical_source_owner_root=str(root), original_working_directory=str(snapshot),
            owner_sdk_sha256=request["source_sha256"][str(root / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/validation_run_resources.py")],
            private_subject_producer_sha256=request["source_sha256"][str(snapshot / "scripts/ops/legal_ir/run_owned_validation.py")],
            private_subject_sdk_sha256=request["source_sha256"][str(snapshot / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/validation_run_resources.py")],
            private_subject_pin_scope="original_declared_subject_pins_not_execution_attestation")
    if _completed_ledger_finalization:
        root = Path(producer["path"]).parents[3]
        summary.update(original_failure_profile=(_PRIVATE_SNAPSHOT_COMPLETED_LEDGER_FINALIZATION_PROFILE
            if _completed_ledger_private_snapshot else _COMPLETED_LEDGER_FINALIZATION_PROFILE),
            **completed_storage_limits, completed_body_ledger_finalization_optin=True,
            original_owner_completed=False, retroactive_qualification_claimed=False,
            test_or_task_acceptance_asserted=False, new_productive_authority_granted=False,
            canonical_source_owner_root=str(root), original_working_directory=request["cwd"],
            owner_sdk_sha256=request["source_sha256"][str(root / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/validation_run_resources.py")],
            private_subject_pin_scope="original_declared_pytest_file_pins_not_execution_attestation")
        if _completed_ledger_private_snapshot:
            snapshot = Path(request["cwd"])
            summary.update(completed_body_ledger_private_snapshot_optin=True,
                private_subject_producer_sha256=request["source_sha256"][str(snapshot / "scripts/ops/legal_ir/run_owned_validation.py")],
                private_subject_sdk_sha256=request["source_sha256"][str(snapshot / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/validation_run_resources.py")],
                private_subject_resource_owner_sha256=request["source_sha256"][str(snapshot / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py")])
    if parent.get("schema") == _SAMPLED_SOURCE_HELD_V4_PARENT_SCHEMA:
        summary["original_failure_profile"] = "source-held-V4-retained-command-failure/v1"
    return dict(record=copy.deepcopy(record), request=request, observation=observation, summary=summary,
        ledger_path=ledger_path, roots=roots, attempt=attempt, artifacts=artifacts,
        expected_record_sha256=expected_record_sha256, reservation_id=reservation_id,
        original_root_identities=copy.deepcopy(original_roots), original_ledger_sha256=None, scheduler=None)


def _sampled_open_scheduler(profile):
    from . import existing_resource_scheduler
    request = profile["request"]
    profile["scheduler"] = existing_resource_scheduler.open_existing_scheduler(request["scheduler_state_path"],
        request["expected_scheduler_policy_sha256"], inspection_only=True)


def _sampled_processes_stopped(profile):
    _sampled_cleanup_deadline()
    record = profile["record"]
    # Retain the stricter generic convention: any current use of these PIDs,
    # including a reused birth or zombie, refuses; this operation signals none.
    pids = {record["owner_pid"], record["child"]["pid"],
            *(item["pid"] for item in profile["observation"]["observed_identities"])}
    for pid in sorted(pids):
        resources.native_deadlines._check_resource_operation_deadline()
        _unopened_need(resources._process(pid) is None, "sampled recovery owner or observed PID still exists")
    _unopened_need(not resources._group_usage(record["child"])["live_processes"],
                   "sampled recovery original child group is still alive")


def _sampled_scheduler_observation(profile, state):
    need = _unopened_need
    record = profile["record"]
    lease_id, request_id = record["native_lease_id"], "validation:" + record["reservation_id"]
    leases, waiters = state.get("leases"), state.get("waiters")
    need(type(leases) is dict and type(waiters) is dict and len(leases) <= 16384 and len(waiters) <= 16384,
         "bounded complete sampled scheduler inventory required")
    children = {}
    for name, rows in (("leases", leases), ("waiters", waiters)):
        for key, row in rows.items():
            resources.native_deadlines._check_resource_operation_deadline()
            need(type(key) is str and key and type(row) is dict, "invalid sampled scheduler record")
            need(key != lease_id and row.get("lease_id") != lease_id and row.get("request_id") != request_id,
                 "original sampled native lease or request is still present")
            if name == "leases":
                parent = row.get("parent_lease_id")
                need(parent is None or (type(parent) is str and 0 < len(parent) <= 256 and "\x00" not in parent),
                     "invalid sampled native lease ancestry")
                if parent is not None:
                    children.setdefault(parent, []).append(key)
    need(not children.get(lease_id), "original sampled native descendant lease is still present")
    return {"schema": "exact-sampled-validation-native-absence/v1", "lease_id": lease_id,
        "request_id": request_id, "matching_leases": 0, "matching_waiters": 0, "descendant_count": 0,
        "scheduler_state_path": record["scheduler_state_path"], "policy_sha256": record["scheduler_policy_sha256"],
        "state_written": False, "historical_release_established": False}


@contextmanager
def _sampled_scheduler_absence(profile):
    with profile["scheduler"]._locked_state(persist=False, strict_existing=True) as state:
        yield _sampled_scheduler_observation(profile, state)


def _sampled_stopped(profile):
    _sampled_processes_stopped(profile)
    record = profile["record"]
    observation = profile["scheduler"].inspect_lease(record["native_lease_id"],
        expected_request_id="validation:" + record["reservation_id"], expected_lane="validation",
        expected_owner_pid=record["owner_pid"], expected_owner_birth_marker=record["owner_birth"],
        bounded_lock_timeout=1)
    _unopened_need(observation.get("status") == "absent" and type(observation.get("descendant_count")) is int
        and observation["descendant_count"] == 0, "original sampled native lease or descendants remain")
    with _sampled_scheduler_absence(profile):
        pass


def _sampled_bind(profile, helper, ledger, record):
    _sampled_cleanup_deadline()
    need = _unopened_need
    need(_digest(record) == profile["expected_record_sha256"]
         and _digest(record) == _digest(profile["record"]), "selected sampled retained record changed")
    need(_digest(helper.root_identities) == _digest(profile["original_root_identities"])
         and [str(root) for root in helper.roots] == profile["request"]["roots"]
         and resources._root_identity(profile["attempt"]) == record["attempt_directory"],
         "sampled attempt or named root binding changed")
    value = _digest(ledger)
    if profile["original_ledger_sha256"] is None:
        profile["original_ledger_sha256"] = value
    need(value == profile["original_ledger_sha256"]
         and _digest(helper._read()) == profile["original_ledger_sha256"],
         "sampled selected or foreign on-disk ledger changed")


@contextmanager
def _sampled_write_guard(profile, helper, ledger, record):
    _sampled_bind(profile, helper, ledger, record)
    _sampled_processes_stopped(profile)
    with profile["scheduler"]._locked_state(persist=False, strict_existing=True) as state:
        observation = _sampled_scheduler_observation(profile, state)
        _sampled_bind(profile, helper, ledger, record)
        _unopened_need(_durable_inventory(profile["attempt"]) == profile["artifacts"],
                       "sampled recovery durable inventory changed before commit")
        _sampled_processes_stopped(profile)
        _sampled_bind(profile, helper, ledger, record)
        _unopened_need(_sampled_scheduler_observation(profile, state) == observation,
                       "sampled native absence changed before commit")
        if profile.get("_completed_ledger_sealed") is not None:
            _completed_ledger_finalization_sealed_evidence_v1(profile)
            profile["summary"]["sealed_full9_rechecked_before_write"] = True
        profile["summary"]["prewrite_native_absence"] = observation
        resources.native_deadlines._check_resource_operation_deadline()
        yield


def inspect_sampled_validation_recovery_v1(ledger_path, *, roots, reservation_id,
        expected_record_sha256, attempt_directory, expected_artifacts, proof_raw,
        expected_proof_sha256, expected_request_sha256, expected_terminal_sha256,
        expected_stdout_sha256, expected_parent_closeout_sha256, expected_producer_sha256, artifacts_durable=False,
        ledger_lock_timeout_seconds=5, expected_ledger_limit_bytes=None):
    """Observe exact sampled recovery readiness without a census, grant or write.

    This is a current cooperative observation, not an authorization token. An
    explicit reconciliation repeats every check under its own original locks.
    """
    _unopened_need(type(ledger_lock_timeout_seconds) in (int, float)
        and math.isfinite(ledger_lock_timeout_seconds) and 0 <= ledger_lock_timeout_seconds <= 30,
        "bounded sampled ledger lock timeout required")
    profile = _sampled_proof(proof_raw, expected_proof_sha256=expected_proof_sha256,
        expected_request_sha256=expected_request_sha256, expected_terminal_sha256=expected_terminal_sha256,
        expected_stdout_sha256=expected_stdout_sha256, expected_parent_closeout_sha256=expected_parent_closeout_sha256, expected_producer_sha256=expected_producer_sha256,
        ledger_path=ledger_path, roots=roots, reservation_id=reservation_id, expected_record_sha256=expected_record_sha256,
        attempt_directory=attempt_directory, expected_artifacts=expected_artifacts, artifacts_durable=artifacts_durable)
    return _inspect_sampled_validation_profile_v1(ledger_path, profile, roots,
        reservation_id, expected_record_sha256, ledger_lock_timeout_seconds, expected_ledger_limit_bytes)


def reconcile_sampled_validation_reservation_v1(ledger_path, *, roots, reservation_id,
        expected_record_sha256, attempt_directory, expected_artifacts, proof_raw,
        expected_proof_sha256, expected_request_sha256, expected_terminal_sha256,
        expected_stdout_sha256, expected_parent_closeout_sha256, expected_producer_sha256, artifacts_durable=False,
        capacity_policy="require_capacity", ledger_lock_timeout_seconds=5, expected_ledger_limit_bytes=None):
    """Close one exact original sampled validation storage claim, preserving history.

    No native lease is acquired or released. Selected historical Popen-verified
    custody is an explicit premise, rechecked against fresh process and native
    absence. This does not establish arbitrary descendant completeness.
    """
    _unopened_need(type(capacity_policy) is str and capacity_policy in
        {"require_capacity", "administrative_closeout"}, "invalid reconciliation capacity policy")
    _unopened_need(type(ledger_lock_timeout_seconds) in (int, float)
        and math.isfinite(ledger_lock_timeout_seconds) and 0 <= ledger_lock_timeout_seconds <= 30,
        "bounded sampled ledger lock timeout required")
    profile = _sampled_proof(proof_raw, expected_proof_sha256=expected_proof_sha256,
        expected_request_sha256=expected_request_sha256, expected_terminal_sha256=expected_terminal_sha256,
        expected_stdout_sha256=expected_stdout_sha256, expected_parent_closeout_sha256=expected_parent_closeout_sha256, expected_producer_sha256=expected_producer_sha256,
        ledger_path=ledger_path, roots=roots, reservation_id=reservation_id, expected_record_sha256=expected_record_sha256,
        attempt_directory=attempt_directory, expected_artifacts=expected_artifacts, artifacts_durable=artifacts_durable)
    return _reconcile_sampled_validation_profile_v1(ledger_path, profile, roots,
        reservation_id, expected_record_sha256, attempt_directory, artifacts_durable,
        capacity_policy, ledger_lock_timeout_seconds, expected_ledger_limit_bytes)




def _inspect_sampled_validation_profile_v1(ledger_path, profile, roots,
        reservation_id, expected_record_sha256, ledger_lock_timeout_seconds, expected_ledger_limit_bytes=None):
    if expected_ledger_limit_bytes is not None and (type(expected_ledger_limit_bytes) is not int
            or not 0 < expected_ledger_limit_bytes < (1 << 63)):
        raise resources.DaemonResourceError("invalid expected ledger limit")
    storage_limit_binding = ({} if expected_ledger_limit_bytes is None else
        {"storage_limit_bytes": expected_ledger_limit_bytes})
    _sampled_open_scheduler(profile)
    helper = resources.DaemonResourceReservation(ledger_path, roots=roots, storage_bytes=1, memory_mb=1,
        require_existing_ledger=True, ledger_lock_timeout_seconds=ledger_lock_timeout_seconds, **storage_limit_binding)
    with _validation_inspection_lock(helper):
        ledger = helper._read()
        record = ledger["reservations"].get(reservation_id)
        _sampled_bind(profile, helper, ledger, record)
        _sampled_stopped(profile)
        inventory = _durable_inventory(profile["attempt"])
        _unopened_need(inventory == profile["artifacts"] and sum(row["bytes"] for row in inventory) <= record["storage_bytes"],
                       "sampled recovery durable inventory differs or exceeds promise")
        if _completed_compact_selection_v1(profile) is not None:
            _completed_compact_evidence_v1(profile, helper, record, inventory)
        with _sampled_write_guard(profile, helper, ledger, record):
            if _completed_compact_selection_v1(profile) is not None:
                compact = _completed_compact_evidence_v1(profile, helper, record, inventory)
                return {"schema": _completed_compact_selection_v1(profile)["readiness"], "ready": True,
                    "reservation_id": reservation_id, "record_sha256": expected_record_sha256,
                    **compact, "proof": copy.deepcopy(profile["summary"]), "capacity_not_assessed": True,
                    "state_written": False, "recovery_performed": False, "admitted": False,
                    "native_release_performed": False, "historical_release_invented": False,
                    "retroactive_qualification_claimed": False}
            return {"schema": "sampled-validation-recovery-readiness/v1", "ready": True,
                "reservation_id": reservation_id, "record_sha256": expected_record_sha256,
                "artifacts": inventory, "proof": copy.deepcopy(profile["summary"]),
                "capacity_not_assessed": True, "state_written": False, "recovery_performed": False,
                "admitted": False, "native_release_performed": False, "historical_release_invented": False}


def _reconcile_sampled_validation_profile_v1(ledger_path, profile, roots,
        reservation_id, expected_record_sha256, attempt_directory, artifacts_durable,
        capacity_policy, ledger_lock_timeout_seconds, expected_ledger_limit_bytes=None):
    if expected_ledger_limit_bytes is not None:
        if capacity_policy != "administrative_closeout":
            raise resources.DaemonResourceError("explicit ledger limit requires administrative_closeout")
        if type(expected_ledger_limit_bytes) is not int or not 0 < expected_ledger_limit_bytes < (1 << 63):
            raise resources.DaemonResourceError("invalid expected ledger limit")
    storage_limit_binding = ({} if expected_ledger_limit_bytes is None else
        {"expected_ledger_limit_bytes": expected_ledger_limit_bytes})
    _unopened_need(profile["request"]["schema"] != _SAMPLED_V5_REQUEST_SCHEMA
        or capacity_policy == "administrative_closeout",
        "original sampled V5 recovery requires administrative_closeout")
    _unopened_need(profile["summary"].get("original_failure_profile") != "source-held-V4-retained-command-failure/v1"
        or capacity_policy == "administrative_closeout",
        "original Source-held V4 recovery requires administrative_closeout")
    _sampled_open_scheduler(profile)
    return _retained_reconciliation_engine(ledger_path, roots=roots, reservation_id=reservation_id,
        expected_record_sha256=expected_record_sha256, attempt_directory=attempt_directory,
        expected_artifacts=profile["artifacts"], artifacts_durable=artifacts_durable,
        capacity_policy=capacity_policy, _sampled=profile,
        _ledger_lock_timeout_seconds=ledger_lock_timeout_seconds, **storage_limit_binding)


def inspect_manual_private_snapshot_validation_recovery_v1(ledger_path, *, roots, reservation_id,
        expected_record_sha256, attempt_directory, expected_artifacts, proof_raw,
        expected_proof_sha256, expected_request_sha256, expected_terminal_sha256,
        expected_stdout_sha256, expected_parent_closeout_sha256, expected_producer_sha256, artifacts_durable=False,
        ledger_lock_timeout_seconds=5):
    """Explicit manual-only private-snapshot/canonical-owner readiness.

    This is a current cooperative observation, not an authorization token. An
    explicit reconciliation repeats every check under its own original locks.
    """
    _unopened_need(type(ledger_lock_timeout_seconds) in (int, float)
        and math.isfinite(ledger_lock_timeout_seconds) and 0 <= ledger_lock_timeout_seconds <= 30,
        "bounded sampled ledger lock timeout required")
    profile = _sampled_proof(proof_raw, expected_proof_sha256=expected_proof_sha256,
        expected_request_sha256=expected_request_sha256, expected_terminal_sha256=expected_terminal_sha256,
        expected_stdout_sha256=expected_stdout_sha256, expected_parent_closeout_sha256=expected_parent_closeout_sha256, expected_producer_sha256=expected_producer_sha256,
        ledger_path=ledger_path, roots=roots, reservation_id=reservation_id, expected_record_sha256=expected_record_sha256,
        attempt_directory=attempt_directory, expected_artifacts=expected_artifacts, artifacts_durable=artifacts_durable,
        _manual_private_snapshot=True)
    return _inspect_sampled_validation_profile_v1(ledger_path, profile, roots,
        reservation_id, expected_record_sha256, ledger_lock_timeout_seconds)


def reconcile_manual_private_snapshot_validation_reservation_v1(ledger_path, *, roots, reservation_id,
        expected_record_sha256, attempt_directory, expected_artifacts, proof_raw,
        expected_proof_sha256, expected_request_sha256, expected_terminal_sha256,
        expected_stdout_sha256, expected_parent_closeout_sha256, expected_producer_sha256, artifacts_durable=False,
        capacity_policy="require_capacity", ledger_lock_timeout_seconds=5):
    """Explicit manual-only private-snapshot/canonical-owner administrative closeout.

    No native lease is acquired or released. Selected historical Popen-verified
    custody is an explicit premise, rechecked against fresh process and native
    absence. This does not establish arbitrary descendant completeness.
    """
    _unopened_need(type(capacity_policy) is str and capacity_policy in
        {"require_capacity", "administrative_closeout"}, "invalid reconciliation capacity policy")
    _unopened_need(type(ledger_lock_timeout_seconds) in (int, float)
        and math.isfinite(ledger_lock_timeout_seconds) and 0 <= ledger_lock_timeout_seconds <= 30,
        "bounded sampled ledger lock timeout required")
    _unopened_need(capacity_policy == "administrative_closeout",
        "manual private snapshot recovery requires administrative_closeout")
    profile = _sampled_proof(proof_raw, expected_proof_sha256=expected_proof_sha256,
        expected_request_sha256=expected_request_sha256, expected_terminal_sha256=expected_terminal_sha256,
        expected_stdout_sha256=expected_stdout_sha256, expected_parent_closeout_sha256=expected_parent_closeout_sha256, expected_producer_sha256=expected_producer_sha256,
        ledger_path=ledger_path, roots=roots, reservation_id=reservation_id, expected_record_sha256=expected_record_sha256,
        attempt_directory=attempt_directory, expected_artifacts=expected_artifacts, artifacts_durable=artifacts_durable,
        _manual_private_snapshot=True)
    return _reconcile_sampled_validation_profile_v1(ledger_path, profile, roots,
        reservation_id, expected_record_sha256, attempt_directory, artifacts_durable,
        capacity_policy, ledger_lock_timeout_seconds)


_DIRECT_TOOL_QUOTA_SCHEMA = 'direct-tool-quota-validation-recovery-proof/v1'
_DIRECT_TOOL_QUOTA_WATCHDOG = 'ValidationResourceError: validation aggregate storage limit exceeded'
_DIRECT_TOOL_QUOTA_MAX_ARTIFACTS = 16384  # Metadata population only; no runtime/storage cap increase.
_DIRECT_TOOL_VALIDATION_ENV = ('PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 '
    'IPFS_DATASETS_PY_MINIMAL_IMPORTS=1 IPFS_ACCELERATE_SKIP_CORE=1 '
    'IPFS_DATASETS_AUTO_INSTALL=0 IPFS_AUTO_INSTALL=false HF_HUB_OFFLINE=1 '
    'TRANSFORMERS_OFFLINE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1')


def _direct_tool_json_outputs(payload):
    need = _unopened_need
    rows = payload.get('output')
    need(type(rows) is list and 1 <= len(rows) <= 8, 'bounded original Tool output required')
    values = []
    for row in rows:
        need(type(row) is dict and row.get('type') == 'input_text'
             and type(row.get('text')) is str and len(row['text']) <= 65536,
             'original Tool text output differs')
        try:
            value = _unopened_json(row['text'].encode(), 65536, 'original Tool output item')
        except resources.DaemonResourceError:
            continue  # The framework's human-readable completion header is not evidence.
        if type(value) is dict:
            values.append(value)
    return values


def _direct_tool_quota_journal(journal, request_ref, request, producer, stdout_ref, stderr_ref, *, reread=True):
    """Verify selected existing journal DATA, not a reconstructed parent or attestation."""
    import base64
    need = _unopened_need
    need(type(journal) is dict and journal.get('schema') == 'historical-original-Tool-invocation-wait-journal-DATA/v1'
         and journal.get('provenance') == 'Existing local provider response journal; historical Tool DATA only'
         and journal.get('request_sha256') == request_ref['sha256']
         and all(journal.get(k) is False for k in ('reconstructed_Python_Popen', 'actual_a0b_parent_verification',
             'source_native_or_storage_release_authority', 'retroactive_full367_qualification')),
         'honest original direct-Tool provenance required')
    rows, source = journal.get('records'), journal.get('source_range')
    need(type(rows) is list and len(rows) == 4 and type(source) is dict
         and type(journal.get('Tool_session_id')) is int and journal['Tool_session_id'] > 0
         and source.get('may_append') is True and source.get('reread_exact') is True
         and all(type(source.get(k)) is int and source[k] >= 0 for k in ('device','inode','first_file_size','last_file_size'))
         and source['last_file_size'] >= source['first_file_size']
         and type(source.get('offset')) is int and source['offset'] >= 0
         and type(source.get('bytes')) is int and 0 < source['bytes'] <= 16 * 1024**2,
         'exact four original Tool record ranges required')
    path = _unopened_path(journal['source_journal_path'], 'original Tool journal')
    decoded = []
    end = source['offset']
    scope = (_direct_tool_journal_descriptor(journal) if reread
             else nullcontext(None))
    with scope as descriptor:
        for row in rows:
            need(type(row) is dict and type(row.get('journal_byte_offset')) is int
                 and row['journal_byte_offset'] >= end and type(row.get('bytes')) is int
                 and 0 < row['bytes'] <= 16384 and row['journal_byte_offset'] + row['bytes'] <= source['offset'] + source['bytes'],
                 'original Tool ranges overlap or exceed bound')
            raw = base64.b64decode(row['raw_record_base64'], validate=True)
            need(len(raw) == row['bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256'],
                 'original Tool record bytes differ')
            if reread:
                resources.native_deadlines._check_resource_operation_deadline()
                need(os.pread(descriptor, row['bytes'], row['journal_byte_offset']) == raw,
                     'original journal record no longer matches selected DATA')
            item = _unopened_json(raw, 16384, 'original Tool record')
            payload = item.get('payload')
            need(item.get('type') == 'response_item' and type(payload) is dict
                 and item.get('timestamp') == row.get('timestamp')
                 and payload.get('call_id') == row.get('call_id')
                 and payload.get('type') == row.get('type'), 'original Tool record envelope differs')
            decoded.append(payload);end = row['journal_byte_offset'] + row['bytes']
    launch, opened, wait, final = decoded
    need([r['type'] for r in decoded] == ['custom_tool_call', 'custom_tool_call_output'] * 2
         and launch.get('name') == wait.get('name') == 'exec'
         and launch['call_id'] == opened['call_id'] and wait['call_id'] == final['call_id']
         and launch['call_id'] != wait['call_id'], 'original Tool invocation/wait pairing differs')
    objects = _direct_tool_json_outputs(opened)
    pre = [r for r in objects if type(r.get('exit_code')) is int and r['exit_code'] == 0 and type(r.get('output')) is str]
    live = [r for r in objects if type(r.get('session_id')) is int and r['session_id'] == journal['Tool_session_id'] and 'exit_code' not in r]
    done = [r for r in _direct_tool_json_outputs(final) if 'exit_code' in r]
    need(len(pre) == len(live) == len(done) == 1 and type(done[0]['exit_code']) is int
         and done[0]['exit_code'] == 1 and done[0].get('output') == '', 'original Tool final EXIT1 not established')
    prepared = _unopened_json(pre[0]['output'].strip().splitlines()[-1].encode(), 65536, 'original preflight request descriptor')
    need(_digest(prepared) == _digest(request_ref), 'Tool preflight selected another original request')
    text = launch.get('input');marker = 'const r=await tools.exec_command({cmd:'
    need(type(text) is str and text.count(marker) == 1
         and hashlib.sha256(text.encode('utf-8')).hexdigest() == _DIRECT_TOOL_QUOTA_LAUNCH_INPUT_SHA256,
         'unsupported original Tool control source or launcher expression')
    tail = text.split(marker, 1)[1];parts = [];decoder = json.JSONDecoder()
    for token in ('+ref.path+', '+ref.sha256+', None):
        part, count = decoder.raw_decode(tail);need(type(part) is str, 'literal Tool command segment required')
        parts.append(part);tail = tail[count:]
        if token is not None:
            need(tail.startswith(token), 'unsupported original Tool reference expression');tail = tail[len(token):]
    command = parts[0] + request_ref['path'] + parts[1] + request_ref['sha256'] + parts[2]
    spellings = (request['argv'][0], producer['path'], request_ref['path'], stdout_ref['path'], stderr_ref['path'], request['resource_ledger'])
    need(all(type(s) is str and re.fullmatch(r'[A-Za-z0-9_./-]+', s) for s in spellings), 'unsupported Tool shell path spelling')
    expected = ('exec env ' + _DIRECT_TOOL_VALIDATION_ENV + ' ' + request['argv'][0] + ' -I -B ' + producer['path']
        + ' --request ' + request_ref['path'] + ' --expected-request-sha256 ' + request_ref['sha256']
        + ' --resource-ledger ' + request['resource_ledger'] + ' > ' + stdout_ref['path'] + ' 2> ' + stderr_ref['path'])
    # The V1 request has no ledger field; this local command view is joined to the lifecycle's ledger.
    need(re.fullmatch(r',\"?yield_time_ms\"?:1000,\"?max_output_tokens\"?:1000\}\);text\(r\);store\(\"[A-Za-z0-9_]+\",r\);\s*', tail) is not None,
         'unsupported statements after original Tool launch')
    need(command == expected, 'Tool did not invoke the selected original CLI/request/output paths')
    needle = 'tools.write_stdin({session_id:' + str(journal['Tool_session_id']) + ',chars:"",yield_time_ms:1000,max_output_tokens:1000})'
    need(type(wait.get('input')) is str and wait['input'].count(needle) == 1,
         'Tool wait does not bind the original live session')
    return dict(schema='selected-direct-Tool-validation-custody/v1', session_id=journal['Tool_session_id'],
        launch_call_id=launch['call_id'], final_wait_call_id=wait['call_id'], original_owner_exit_code=1,
        historical_Tool_DATA_selected_by_caller=True, cryptographic_execution_attestation=False,
        reconstructed_Popen_handle=False, actual_a0b_parent_verification=False, source_authority_granted=False,
        native_release_performed=False, qualification_claimed=False)


def _direct_tool_quota_profile(proof_raw, expected_proof_sha256, snapshot_raw, expected_snapshot_sha256, *,
        ledger_path, roots, reservation_id, expected_record_sha256, attempt_directory, expected_artifacts, artifacts_durable):
    need = _unopened_need;_sampled_cleanup_deadline()
    need(artifacts_durable is True, 'explicit direct-Tool artifact durability assertion required')
    _sampled_pin(expected_record_sha256, 'record')
    need(type(reservation_id) is str and re.fullmatch(r'[0-9a-f]{32}', reservation_id), 'exact reservation identity required')
    proof = _sampled_document(proof_raw, expected_proof_sha256, 'direct-Tool proof')
    need(set(proof) == {'schema','provenance','request_raw_utf8','owner_stdout_raw_utf8','owner_stderr_raw_utf8',
         'producer_source_utf8','tool_journal_raw_utf8','refs'} and proof['schema'] == _DIRECT_TOOL_QUOTA_SCHEMA
         and proof['provenance'] == 'selected_original_direct_Tool_DATA/v1', 'closed direct-Tool quota proof required')
    refs = proof['refs'];need(type(refs) is dict and set(refs) == {'request','stdout','stderr','producer','tool_journal'}, 'closed original references required')
    buffers = {}
    for key, field in (('request','request_raw_utf8'),('stdout','owner_stdout_raw_utf8'),('stderr','owner_stderr_raw_utf8'),
            ('producer','producer_source_utf8'),('tool_journal','tool_journal_raw_utf8')):
        need(type(proof[field]) is str, 'original UTF8 buffer required');raw = proof[field].encode();r = refs[key]
        need(type(r) is dict and set(r) == {'path','bytes','sha256'} and type(r['bytes']) is int
             and r['bytes'] == len(raw) and 0 <= len(raw) <= 4 * 1024**2
             and hashlib.sha256(raw).hexdigest() == r['sha256'], 'original direct-Tool buffer differs')
        _unopened_path(r['path'], 'original direct-Tool reference');buffers[key] = raw
    request = _unopened_json(buffers['request'], 1024**2, 'original request')
    terminal = _unopened_json(buffers['stdout'], 4*1024**2, 'original stdout terminal')
    fields = set('schema argv cwd selected_checks source_sha256 timeout_seconds storage_bytes memory_mb cpu_slots child_process_slots attempt_directory outputs declared_external_writable_paths process_scope scheduler_state_path expected_scheduler_policy_sha256 roots'.split())
    need(type(request) is dict and set(request) == fields and request['schema'] == 'owned-validation-request/v1'
         and request['process_scope'] == 'sampled_birth_bound_descendants' and request['declared_external_writable_paths'] == [],
         'original direct-Tool V1 sampled request required')
    need(type(request['argv']) is list and 0 < len(request['argv']) <= 256
         and all(type(v) is str and 0 < len(v) <= 8192 and '\x00' not in v for v in request['argv'])
         and type(request['selected_checks']) is list and 0 < len(request['selected_checks']) <= 256
         and all(type(v) is str and 0 < len(v) <= 8192 and '\x00' not in v for v in request['selected_checks'])
         and len(set(request['selected_checks'])) == len(request['selected_checks'])
         and type(request['source_sha256']) is dict and 0 < len(request['source_sha256']) <= 256
         and type(request['timeout_seconds']) in (int,float) and math.isfinite(request['timeout_seconds'])
         and request['timeout_seconds'] > 0, 'bounded original command/source request required')
    for path, pin in request['source_sha256'].items():
        _unopened_path(path, 'original source pin');_sampled_pin(pin, 'original source')
    _sampled_pin(request['expected_scheduler_policy_sha256'], 'scheduler policy')
    attempt = _unopened_path(os.fspath(attempt_directory), 'direct-Tool attempt');roots = [_unopened_path(os.fspath(r), 'named root') for r in roots]
    ledger_path = _unopened_path(os.fspath(ledger_path), 'direct-Tool ledger')
    need(request['roots'] == [str(r) for r in roots] and request['attempt_directory'] == str(attempt)
         and request['outputs'] == {k:str(attempt/k)for k in ('pytest','tmp','cache','db','exports','logs')}
         and any(r in attempt.parents for r in roots), 'original direct-Tool storage scope differs')
    need(type(terminal) is dict and set(terminal) == {'schema','request_sha256','completed','admitted','Lean_admitted','failure','reservation','process_cleanup_error','owner_exit_error','source_custody_lifecycle'} and terminal.get('schema') == 'owned-validation-failure-terminal/v1'
         and terminal.get('request_sha256') == refs['request']['sha256']
         and all(terminal.get(k) is False for k in ('completed','admitted','Lean_admitted'))
         and terminal.get('process_cleanup_error') is None and terminal.get('owner_exit_error') is None,
         'original failed owner terminal required')
    reservation = terminal['reservation'];record = reservation['record'];observation = reservation['process_observation'];failure = terminal['failure'];lifecycle = terminal['source_custody_lifecycle']
    need(type(record) is dict and _digest(record) == expected_record_sha256 and record.get('reservation_id') == reservation_id
         and record.get('status') == 'retained' and record.get('artifacts_durable_asserted') is False
         and type(record.get('owner_pid')) is int and record['owner_pid'] > 0
         and type(record.get('owner_birth')) is str and record['owner_birth'].isdigit()
         and record.get('scheduler_lane') == 'validation' and record.get('workload') == 'canonical_validation'
         and record.get('retention_reason') == 'context_failed'
         and record.get('scheduler_state_path') == request['scheduler_state_path']
         and record.get('scheduler_policy_sha256') == request['expected_scheduler_policy_sha256']
         and _digest(record.get('outputs')) == _digest(request['outputs'])
         and record.get('process_scope') == request['process_scope'] and record.get('prior_children') == []
         and record.get('external_charges') == {} and record.get('validation_request_sha256') == refs['request']['sha256']
         and record.get('attempt_directory') == resources._root_identity(attempt), 'exact retained original claim required')
    need(all(type(request[k]) is int and request[k] > 0 and request[k] == record[k]
         for k in ('storage_bytes','cpu_slots','memory_mb','child_process_slots')),
         'original unchanged typed resource bounds required')
    need(failure.get('schema') == 'owned-validation-result/v1' and failure.get('request_sha256') == refs['request']['sha256']
         and type(failure.get('returncode')) is int and failure['returncode'] == 0
         and failure.get('completed') is False and _digest(failure.get('executed_checks')) == _digest(request['selected_checks'])
         and failure.get('watchdog_errors') == [_DIRECT_TOOL_QUOTA_WATCHDOG]
         and failure.get('error_type') == 'RuntimeError'
         and failure.get('error') == 'validation cancelled: '+repr([_DIRECT_TOOL_QUOTA_WATCHDOG])
         and failure.get('received_signals') == [] and failure.get('process_cleanup_error') is None
         and all(failure.get(k) is False for k in ('admitted','Lean_admitted','authority_granted','model_weights_downloaded')),
         'only completed command / exact owner quota failure is supported')
    need(type(observation) is dict and _digest(failure.get('process_observation')) == _digest(observation)
         and observation.get('scope') == request['process_scope'] and observation.get('tracking_error') == ''
         and observation.get('out_of_group_live_identities') == []
         and all(type(observation.get(k)) is int and observation[k] == 0 for k in ('live_processes','rss_bytes'))
         and _digest(observation.get('group_rss')) == _digest(dict(available=True,live_processes=0,rss_bytes=0)),
         'closed original sampled observation required')
    identities = observation.get('observed_identities');child = record.get('child')
    need(type(identities) is list and len(identities) == 1 and type(child) is dict
         and set(child) == {'pid','birth'} and type(child['pid']) is int and child['pid'] > 0
         and child['pid'] != record['owner_pid'] and type(child['birth']) is str and child['birth'].isdigit()
         and all(type(v) is int and v > 0 for v in identities[0].values())
         and _digest(identities[0]) == _digest(dict(pid=child['pid'],birth_ticks=int(child['birth']),parent_pid=record['owner_pid'],process_group_id=child['pid'],session_id=child['pid'])),
         'exact single original child observation required')
    producer = lifecycle.get('producer');lease = reservation.get('resource_lease')
    need(_digest(lifecycle.get('owner')) == _digest(dict(pid=record['owner_pid'],birth=record['owner_birth']))
         and lifecycle.get('reservation_id') == reservation_id and lifecycle.get('request_sha256') == refs['request']['sha256']
         and lifecycle.get('ledger_path') == str(ledger_path) and lifecycle.get('resource_request_id') == 'validation:'+reservation_id
         and lifecycle.get('schema') == 'owned-validation-source-custody-lifecycle/v1'
         and lifecycle.get('attempt_directory') == str(attempt) and _digest(lifecycle.get('outputs')) == _digest(request['outputs'])
         and _digest(lifecycle.get('scheduler')) == _digest(dict(state_path=record['scheduler_state_path'],policy_sha256=record['scheduler_policy_sha256'],lane='validation',workload='canonical_validation'))
         and _digest(lifecycle.get('native_grant')) == _digest(dict(status='acquired',exact_native_timeout=False,timeout_decision=None))
         and lifecycle.get('process_scope') == request['process_scope']
         and _digest(lifecycle.get('budgets')) == _digest({k:record[k]for k in ('cpu_slots','memory_mb','child_process_slots','storage_bytes')})
         and lifecycle.get('owner_child_attached') is True
         and type(lifecycle.get('events')) is dict and set(lifecycle['events']) == {'owner_open_attempted','owner_open_returned','child_launch_attempted','child_created','barrier_release_attempted','barrier_released','owner_exit_handling_completed'} and all(v is True for v in lifecycle['events'].values())
         and _digest(lifecycle.get('source_guards')) == _digest(dict(request_unchanged=True,source_pins_unchanged=True,owner_identity_unchanged=True,errors=[]))
         and _digest(lifecycle.get('storage')) == _digest(dict(status='retained',cleanup_error=None,release_authorized=False)),
         'original direct-Tool source/exit lifecycle differs')
    need(type(producer) is dict and producer.get('path') == refs['producer']['path']
         and producer.get('sha256') == refs['producer']['sha256'] and producer['path'].endswith('/scripts/ops/legal_ir/run_owned_validation.py')
         and request['source_sha256'].get(producer['path']) == producer['sha256']
         and type(lease) is dict and lease.get('released') is True and lease.get('lease_id') == record['native_lease_id']
         and type(lease.get('owner_pid')) is int and lease['owner_pid'] == record['owner_pid']
         and 'parent_lease_id' in lease and lease['parent_lease_id'] is None and lease.get('lane') == 'validation'
         and lease.get('requires_gpu') is False
         and all(type(lease.get(k)) is int and lease[k] == record[k] for k in ('cpu_slots','memory_mb','child_process_slots'))
         and reservation.get('cleanup_error') is None and reservation.get('status') == 'retained'
         and reservation.get('ledger_path') == str(ledger_path), 'original native/producer binding differs')
    journal = _unopened_json(buffers['tool_journal'], 4*1024**2, 'original Tool journal DATA')
    command_request = copy.deepcopy(request);command_request['resource_ledger'] = str(ledger_path)
    summary = _direct_tool_quota_journal(journal, refs['request'], command_request, producer, refs['stdout'], refs['stderr'])
    snapshot = _sampled_document(snapshot_raw, expected_snapshot_sha256, 'retained metadata snapshot', 16*1024**2)
    need(type(snapshot) is dict and snapshot.get('schema') == 'native-full367-retained-inventory-and-selected-runtime-fresh-source/v1'
         and snapshot.get('no_claim_or_artifact_mutation') is True
         and snapshot.get('Source_READ_closed') is True and snapshot.get('all_entries_ordinary_regular') is True
         and _digest(snapshot.get('own_full367_reservation',{}).get('record')) == expected_record_sha256,
         'selected pre-recovery retained snapshot differs')
    metadata = snapshot['retained_attempt_metadata_inventory'];expected = copy.deepcopy(expected_artifacts)
    need(type(expected) is list and 0 < len(expected) <= _DIRECT_TOOL_QUOTA_MAX_ARTIFACTS
         and type(metadata) is list and len(metadata) == len(expected)
         and type(snapshot.get('retained_file_entries')) is int and snapshot['retained_file_entries'] == len(expected)
         and len(json.dumps(expected,sort_keys=True,separators=(',',':'),allow_nan=False).encode()) <= MAX_RECOVERY_MANIFEST_BYTES,
         'bounded complete direct-Tool inventory required')
    seen = set();sizes = {}
    for item in metadata:
        p = _unopened_path(item['path'], 'retained artifact metadata');info = item['identity']
        need(type(info) is dict and set(info) == {'st_dev','st_ino','st_mode','st_uid','st_gid','st_nlink','st_size','st_mtime_ns','st_ctime_ns'}
             and all(type(v) is int for v in info.values())
             and attempt in p.parents and p not in seen and stat.S_ISREG(info['st_mode']) and info['st_nlink'] == 1
             and info['st_uid'] == os.geteuid(), 'ordinary owned retained artifact metadata required')
        seen.add(p);sizes[str(p.relative_to(attempt))] = info['st_size']
    need([row.get('path')for row in expected] == sorted(sizes, key=Path)
         and all(type(row) is dict and set(row) == {'path','bytes','sha256'} and type(row['bytes']) is int
             and row['bytes'] == sizes[row['path']] and type(row['sha256']) is str
             and re.fullmatch(r'[0-9a-f]{64}',row['sha256']) for row in expected)
         and type(snapshot.get('retained_apparent_bytes')) is int
         and sum(sizes.values()) == snapshot['retained_apparent_bytes'] > record['storage_bytes'],
         'original overrun namespace/bytes must be preserved exactly')
    return dict(record=copy.deepcopy(record),request=request,observation=observation,summary=summary,
        ledger_path=ledger_path,roots=roots,attempt=attempt,artifacts=expected,expected_record_sha256=expected_record_sha256,
        reservation_id=reservation_id,original_root_identities=copy.deepcopy(reservation['roots']),
        original_ledger_sha256=None,scheduler=None,metadata=metadata,journal=journal,command_request=command_request,
        refs=refs,producer=producer,proof_sha256=expected_proof_sha256,proof_raw_bytes=len(proof_raw))


def _direct_tool_quota_metadata_unchanged(profile):
    for row in profile['metadata']:
        resources.native_deadlines._check_resource_operation_deadline()
        p = resources._safe_path(row['path']);info = p.lstat()
        actual = {key:getattr(info,key)for key in row['identity']}
        _unopened_need(_digest(actual) == _digest(row['identity']), 'retained artifact identity changed')


def reconcile_direct_tool_quota_validation_reservation_v1(ledger_path, *, roots, reservation_id,
        expected_record_sha256, attempt_directory, expected_artifacts, proof_raw, expected_proof_sha256,
        retained_snapshot_raw, expected_retained_snapshot_sha256, artifact_inventory_manifest,
        evidence_archive, artifacts_durable=False, ledger_lock_timeout_seconds=5):
    """Explicit admin storage-only closeout of one dead direct-Tool quota failure.

    All old APIs keep their original no-overrun/count/provenance rules. Original
    Tool DATA is verified at fixed existing journal ranges; no Python Popen/a0b
    parent, Source authority or successful resource qualification is invented.
    Both supplied durable metadata archives must already exist outside ATT under
    named roots, and remain charged in the two real censuses. No archive is
    created or truncated here. Actual postwrite census is separately required.
    """
    need = _unopened_need
    need(type(ledger_lock_timeout_seconds) in (int,float) and math.isfinite(ledger_lock_timeout_seconds)
         and 0 <= ledger_lock_timeout_seconds <= 30, 'bounded direct-Tool ledger lock required')
    supplied_refs_sha = _digest([artifact_inventory_manifest,evidence_archive])
    manifest_ref, evidence_ref = copy.deepcopy([artifact_inventory_manifest,evidence_archive])
    profile = _direct_tool_quota_profile(proof_raw,expected_proof_sha256,retained_snapshot_raw,
        expected_retained_snapshot_sha256,ledger_path=ledger_path,roots=roots,reservation_id=reservation_id,
        expected_record_sha256=expected_record_sha256,attempt_directory=attempt_directory,
        expected_artifacts=expected_artifacts,artifacts_durable=artifacts_durable)
    _sampled_open_scheduler(profile)
    helper = resources.DaemonResourceReservation(ledger_path,roots=roots,storage_bytes=1,memory_mb=1,
        require_existing_ledger=True,ledger_lock_timeout_seconds=ledger_lock_timeout_seconds)
    with helper._locked():
        ledger = helper._read();record = ledger['reservations'].get(reservation_id)
        _sampled_bind(profile,helper,ledger,record);_sampled_stopped(profile)
        _direct_tool_quota_metadata_unchanged(profile)
        inventory = _durable_inventory(profile['attempt'])
        need(_digest(inventory) == _digest(profile['artifacts']), 'complete durable inventory differs')
        need(type(manifest_ref) is dict and type(evidence_ref) is dict and manifest_ref.get('path') != evidence_ref.get('path')
             and type(manifest_ref.get('bytes')) is int and type(evidence_ref.get('bytes')) is int
             and manifest_ref['bytes'] + evidence_ref['bytes'] <= record['storage_bytes'],
             'bounded distinct recovery metadata within the unchanged full promise required')
        manifest, mw = _released_artifact_reference(manifest_ref,helper,profile['attempt'])
        archive, aw = _released_artifact_reference(evidence_ref,helper,profile['attempt'])
        need(set(manifest) == {'schema','attempt_directory','artifacts'}
             and manifest['schema'] == 'retained-artifact-inventory/v1'
             and _digest(manifest['attempt_directory']) == _digest(record['attempt_directory'])
             and _digest(manifest['artifacts']) == _digest(inventory)
             and evidence_ref['sha256'] == expected_proof_sha256
             and evidence_ref['bytes'] == len(proof_raw), 'descriptor-backed original evidence differs')
        foreign = _digest({k:v for k,v in ledger['reservations'].items()if k != reservation_id})
        accounting = _administrative_census(helper,ledger)
        _sampled_bind(profile,helper,ledger,record);_sampled_stopped(profile);_direct_tool_quota_metadata_unchanged(profile)
        projected = copy.deepcopy(ledger);projected['reservations'][reservation_id]['status'] = 'released'
        projected_sha = _digest(projected['reservations'][reservation_id])
        final = _administrative_census(helper,projected)
        need(_digest(projected['reservations'][reservation_id]) == projected_sha
             and _digest({k:v for k,v in projected['reservations'].items()if k!=reservation_id}) == foreign,
             'projected original or foreign record changed')
        _sampled_bind(profile,helper,ledger,record)
        need(accounting['outstanding_full_reservations_bytes']-final['outstanding_full_reservations_bytes'] == record['storage_bytes'],
             'full original promise delta differs')
        with _sampled_write_guard(profile,helper,ledger,record):
            _direct_tool_quota_journal(profile['journal'],profile['refs']['request'],profile['command_request'],
                profile['producer'],profile['refs']['stdout'],profile['refs']['stderr'])
            _direct_tool_quota_metadata_unchanged(profile)
            mm, mmw = _released_artifact_reference(manifest_ref,helper,profile['attempt'])
            aa, aaw = _released_artifact_reference(evidence_ref,helper,profile['attempt'])
            need(_digest(mm)==_digest(manifest) and mmw==mw and _digest(aa)==_digest(archive) and aaw==aw,
                 'recovery evidence changed before commit')
            need(_digest([artifact_inventory_manifest,evidence_archive]) == supplied_refs_sha,
                 'supplied archive descriptors changed during closeout')
            actual_bytes = sum(row['bytes']for row in inventory)
            receipt = dict(schema='explicit-direct-Tool-quota-validation-reconciliation/v1',
                reservation_id=reservation_id,previous_record_sha256=expected_record_sha256,
                original_owner_pid=record['owner_pid'],reconciled_by_pid=os.getpid(),
                artifact_inventory_manifest=copy.deepcopy(manifest_ref),artifact_manifest_schema='retained-artifact-inventory/v1',
                artifact_count=len(inventory),artifact_bytes=actual_bytes,evidence_archive=copy.deepcopy(evidence_ref),
                historical_Tool_custody=copy.deepcopy(profile['summary']),other_reservations_sha256=foreign,
                original_storage_budget_bytes=record['storage_bytes'],original_quota_violation_preserved=True,
                overrun_bytes=actual_bytes-record['storage_bytes'],full_claim_accounting=accounting,final_accounting=final,
                capacity_policy='administrative_closeout',cap_changed=False,request_budget_changed=False,
                final_accounting_is_prewrite_projection=True,actual_postwrite_census_required=True,
                fresh_global_inventory_count=2,native_release_performed=False,outputs_deleted=False,
                new_reservation_created=False,new_resource_lease_acquired=False,admitted=False,
                source_authority_granted=False,retroactive_qualification_claimed=False,automatic_expiry=False)
            record.update(status='released',artifacts_durable_asserted=True,released_at=time.time(),
                final_accounting=final,final_attempt_bytes=actual_bytes,final_external_charged_bytes=0,
                final_total_charged_bytes=actual_bytes,attempt_exceeded_reservation=True,explicit_reconciliation=receipt)
            need(_digest({k:v for k,v in ledger['reservations'].items()if k!=reservation_id})==foreign,
                 'foreign reservation changed')
            need(len((json.dumps(ledger,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()) <= resources.MAX_LEDGER_BYTES,
                 'compact recovery would exceed unchanged ledger byte bound')
            helper._verify_owner_roots();resources.native_deadlines._check_resource_operation_deadline()
            helper._write(ledger)
            return receipt


# This version supports the one inspected historical control source. Checking
# the full source binds the actual ref dataflow, not just a command suffix with
# caller-substituted ref.path/ref.sha256. Fictional tests explicitly inject their
# own control source commitment and never claim provider execution attestation.
_DIRECT_TOOL_QUOTA_LAUNCH_INPUT_SHA256 = '71fc778fc87977e7e050f4484f861faf8e683d206688996704b2c5540f6ae4e3'


@contextmanager
def _direct_tool_journal_descriptor(journal):
    """Anchor the existing journal path; allow append, never path replacement.

    Every acquired descriptor, including an invalid leaf, closes in finally.
    Parent directory stable identities and the named leaf stay joined to the
    fd throughout selected-range reads. No journal entry is created or changed.
    """
    need = _unopened_need
    path = _unopened_path(journal['source_journal_path'], 'original Tool journal')
    need(str(path) == journal['source_journal_path'], 'literal original Tool journal path required')
    source = journal['source_range']
    descriptors, edges = [], []
    stable_directory = lambda info: (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid)
    stable_leaf = lambda info: (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid, info.st_nlink)
    try:
        root_fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        descriptors.append(root_fd)
        parent = root_fd
        for name in path.parts[1:-1]:
            resources.native_deadlines._check_resource_operation_deadline()
            fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                         dir_fd=parent)
            descriptors.append(fd)
            opened = os.fstat(fd)
            named = os.stat(name, dir_fd=parent, follow_symlinks=False)
            need(stat.S_ISDIR(opened.st_mode) and stable_directory(opened) == stable_directory(named),
                 'original Tool journal parent identity differs')
            edges.append((parent, name, stable_directory(opened)))
            parent = fd
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                     dir_fd=parent)
        descriptors.append(fd)
        first = os.fstat(fd)
        need(stat.S_ISREG(first.st_mode) and first.st_uid == os.geteuid() and first.st_nlink == 1
             and (first.st_dev, first.st_ino) == (source['device'], source['inode'])
             and first.st_size >= source['last_file_size'], 'original Tool journal identity changed')
        def guard():
            resources.native_deadlines._check_resource_operation_deadline()
            named = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            current = os.fstat(fd)
            need(stable_leaf(current) == stable_leaf(named) == stable_leaf(first)
                 and current.st_size == named.st_size and current.st_size >= first.st_size,
                 'original Tool journal truncated or named entry replaced')
            for directory_fd, name, expected in edges:
                info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                need(stat.S_ISDIR(info.st_mode) and stable_directory(info) == expected,
                     'original Tool journal ancestry changed')
        guard()
        yield fd
        guard()
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def _direct_tool_quota_disposition_fields(row, receipt, helper, attempt):
    """Validate the compact recorded storage disposition, not live artifacts.

    The existing inspector remains record-only: it does not re-inventory an
    artifact tree or re-read provider history, and grants no native/Source/test
    authority. This explicit schema is the only added disposition profile.
    """
    need = _unopened_need
    proof = receipt.get('historical_Tool_custody')
    actual = row.get('final_attempt_bytes')
    need(row.get('process_scope') == 'sampled_birth_bound_descendants'
         and type(actual) is int and actual > row['storage_bytes']
         and row.get('attempt_exceeded_reservation') is True
         and type(row.get('final_external_charged_bytes')) is int
         and row['final_external_charged_bytes'] == 0
         and type(row.get('final_total_charged_bytes')) is int
         and row['final_total_charged_bytes'] == actual
         and receipt.get('original_quota_violation_preserved') is True
         and type(receipt.get('original_storage_budget_bytes')) is int
         and receipt['original_storage_budget_bytes'] == row['storage_bytes']
         and type(receipt.get('overrun_bytes')) is int
         and receipt['overrun_bytes'] == actual - row['storage_bytes']
         and type(receipt.get('artifact_count')) is int
         and 1 <= receipt['artifact_count'] <= _DIRECT_TOOL_QUOTA_MAX_ARTIFACTS
         and type(receipt.get('artifact_bytes')) is int and receipt['artifact_bytes'] == actual
         and receipt.get('artifact_manifest_schema') == 'retained-artifact-inventory/v1'
         and 'artifacts' not in receipt,
         'direct-Tool quota disposition lost original overrun or compact inventory')
    need(type(proof) is dict and proof.get('schema') == 'selected-direct-Tool-validation-custody/v1'
         and type(proof.get('session_id')) is int and proof['session_id'] > 0
         and type(proof.get('original_owner_exit_code')) is int and proof['original_owner_exit_code'] == 1
         and proof.get('historical_Tool_DATA_selected_by_caller') is True
         and all(proof.get(k) is False for k in ('cryptographic_execution_attestation',
             'reconstructed_Popen_handle', 'actual_a0b_parent_verification',
             'source_authority_granted', 'native_release_performed', 'qualification_claimed'))
         and receipt.get('capacity_policy') == 'administrative_closeout'
         and all(receipt.get(k) is False for k in ('cap_changed', 'request_budget_changed',
             'native_release_performed', 'source_authority_granted', 'retroactive_qualification_claimed',
             'new_reservation_created', 'new_resource_lease_acquired'))
         and receipt.get('final_accounting_is_prewrite_projection') is True
         and receipt.get('actual_postwrite_census_required') is True
         and type(receipt.get('fresh_global_inventory_count')) is int
         and receipt['fresh_global_inventory_count'] == 2,
         'direct-Tool quota disposition provenance or accounting profile differs')
    references = [receipt.get('artifact_inventory_manifest'), receipt.get('evidence_archive')]
    for reference in references:
        need(type(reference) is dict and set(reference) == {'path', 'bytes', 'sha256'}
             and type(reference['bytes']) is int and 0 < reference['bytes'] <= MAX_RECOVERY_MANIFEST_BYTES
             and type(reference['sha256']) is str and re.fullmatch(r'[0-9a-f]{64}', reference['sha256']),
             'direct-Tool quota recorded evidence descriptor differs')
        path = _unopened_path(reference['path'], 'direct-Tool quota archive')
        need(str(path) == reference['path'] and any(root in path.parents for root in helper.roots)
             and path not in (helper.ledger_path, helper.lock_path, attempt)
             and attempt not in path.parents, 'direct-Tool quota archive scope differs')
    need(references[0]['path'] != references[1]['path']
         and sum(r['bytes'] for r in references) <= row['storage_bytes'],
         'direct-Tool quota detached metadata footprint differs')


# Explicit successor: historical body success is not successful owner finalization.
_COMPLETED_WATCHDOG_FAILURE_PROFILE = "source-held-V5-completed-command-watchdog-finalization/v1"
_COMPLETED_WATCHDOG_RECONCILIATION_SCHEMA = "explicit-completed-watchdog-validation-reconciliation/v1"
_COMPLETED_WATCHDOG_MAX_ARTIFACTS = 16384  # Metadata population only; no storage/runtime budget change.


def _completed_watchdog_artifacts(value):
    """Validate the complete larger population without changing the old parser."""
    need = _unopened_need
    need(type(value) is list and 0 < len(value) <= _COMPLETED_WATCHDOG_MAX_ARTIFACTS,
         "complete bounded completed watchdog artifact inventory required")
    result, seen = [], set()
    for start in range(0, len(value), 4096):
        for row in _sampled_artifacts(value[start:start + 4096]):
            need(row["path"] not in seen, "duplicate completed watchdog artifact across inventory chunks")
            seen.add(row["path"])
            result.append(row)
    need(len(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
         <= MAX_RECOVERY_MANIFEST_BYTES, "complete completed watchdog manifest exceeds existing metadata byte bound")
    return result


_PRIVATE_COMPLETED_LEDGER_RECONCILIATION_SCHEMA = "explicit-private-snapshot-completed-ledger-validation-reconciliation/v1"


def _completed_compact_selection_v1(profile):
    """Select one explicit compact profile without translating failure categories."""
    watchdog = profile.get("_completed_watchdog_compact") is not None
    ledger = profile.get("_private_completed_ledger_compact") is not None
    _unopened_need(not (watchdog and ledger), "conflicting completed compact profiles")
    if not (watchdog or ledger):
        return None
    proof = profile["summary"]
    if watchdog:
        _unopened_need(proof.get("original_failure_profile") == _COMPLETED_WATCHDOG_FAILURE_PROFILE
            and proof.get("completed_body_watchdog_finalization_optin") is True,
            "completed watchdog compact failure category differs")
        return dict(key="_completed_watchdog_compact", label="completed watchdog",
            readiness="completed-watchdog-validation-recovery-readiness/v1",
            reconciliation=_COMPLETED_WATCHDOG_RECONCILIATION_SCHEMA)
    _unopened_need(proof.get("original_failure_profile") == _PRIVATE_SNAPSHOT_COMPLETED_LEDGER_FINALIZATION_PROFILE
        and proof.get("completed_body_ledger_finalization_optin") is True
        and proof.get("completed_body_ledger_private_snapshot_optin") is True
        and "completed_body_watchdog_finalization_optin" not in proof,
        "private completed-ledger compact failure category differs")
    return dict(key="_private_completed_ledger_compact", label="private completed-ledger",
        readiness="private-snapshot-completed-ledger-validation-recovery-readiness/v1",
        reconciliation=_PRIVATE_COMPLETED_LEDGER_RECONCILIATION_SCHEMA)


def _completed_compact_bind_v1(profile, proof_raw, artifact_inventory_manifest, evidence_archive, *, key):
    """Bind the same two already-existing detached DATA archives for either profile."""
    _unopened_need(key in ("_completed_watchdog_compact", "_private_completed_ledger_compact"),
        "unknown completed compact evidence profile")
    label = "completed watchdog" if key == "_completed_watchdog_compact" else "private completed-ledger"
    need = _unopened_need
    references = [artifact_inventory_manifest, evidence_archive]
    copied = copy.deepcopy(references)
    for reference in copied:
        need(type(reference) is dict and set(reference) == {"path", "bytes", "sha256"}
             and type(reference["bytes"]) is int
             and 0 < reference["bytes"] <= MAX_RECOVERY_MANIFEST_BYTES,
             f"closed bounded {label} evidence descriptor required")
        _sampled_pin(reference["sha256"], f"{label} evidence")
        path = _unopened_path(reference["path"], f"{label} evidence")
        need(str(path) == reference["path"] and any(root in path.parents for root in profile["roots"])
             and path not in (profile["ledger_path"], profile["ledger_path"].with_suffix(profile["ledger_path"].suffix + ".lock"), profile["attempt"])
             and profile["attempt"] not in path.parents,
             f"{label} evidence must be detached under the original named roots")
    need(copied[0]["path"] != copied[1]["path"]
         and sum(row["bytes"] for row in copied) <= profile["record"]["storage_bytes"],
         f"{label} distinct metadata footprint exceeds original promise")
    need(copied[1]["sha256"] == profile["summary"]["proof_sha256"]
         and copied[1]["bytes"] == len(proof_raw),
         f"{label} evidence archive must preserve the exact original proof bytes")
    profile[key] = {
        "references": copied, "supplied_references": references,
        "supplied_sha256": _digest(references), "witnesses": None,
    }
    _completed_compact_selection_v1(profile)
    return profile


def _completed_compact_evidence_v1(profile, helper, record, inventory):
    """Re-read/fsync detached evidence through the existing original owner."""
    need = _unopened_need
    selected = _completed_compact_selection_v1(profile)
    need(selected is not None, "explicit completed compact evidence profile required")
    label = selected["label"]
    spec = profile[selected["key"]]
    need(_digest(spec["supplied_references"]) == spec["supplied_sha256"],
         f"supplied {label} evidence descriptors changed")
    manifest_ref, evidence_ref = spec["references"]
    need(sum(row["bytes"] for row in spec["references"]) <= record["storage_bytes"],
         f"{label} detached metadata footprint exceeds original promise")
    manifest, mw = _released_artifact_reference(manifest_ref, helper, profile["attempt"])
    archive, aw = _released_artifact_reference(evidence_ref, helper, profile["attempt"])
    need(type(manifest) is dict and set(manifest) == {"schema", "attempt_directory", "artifacts"}
         and manifest["schema"] == "retained-artifact-inventory/v1"
         and _digest(manifest["attempt_directory"]) == _digest(record["attempt_directory"])
         and _digest(manifest["artifacts"]) == _digest(inventory) == _digest(profile["artifacts"]),
         f"{label} detached full inventory differs")
    need(type(archive) is dict and archive.get("schema") == "sampled-validation-recovery-proof/v1"
         and evidence_ref["sha256"] == profile["summary"]["proof_sha256"],
         f"{label} original proof archive differs")
    witness = (mw, aw)
    if spec["witnesses"] is None:
        spec["witnesses"] = witness
    else:
        need(spec["witnesses"] == witness, f"{label} detached evidence generation changed")
    need(_digest(spec["supplied_references"]) == spec["supplied_sha256"],
         f"supplied {label} evidence descriptors changed during durability")
    if selected["key"] == "_private_completed_ledger_compact":
        need(profile["summary"].get("original_storage_limit_bytes")
             == profile["summary"].get("current_storage_limit_bytes") == resources.MAX_STORAGE_BYTES,
             "private completed-ledger original/current storage cap changed")
    caps = _completed_watchdog_storage_limits(
        profile["summary"].get("original_storage_limit_bytes"), resources.MAX_STORAGE_BYTES,
        profile["summary"].get("original_resource_owner_sha256"))
    need(all(profile["summary"].get(key) == value for key, value in caps.items()),
         f"{label} current storage limit changed during recovery")
    return {
        "artifact_inventory_manifest": copy.deepcopy(manifest_ref),
        "artifact_manifest_schema": "retained-artifact-inventory/v1",
        "artifact_count": len(inventory), "artifact_bytes": sum(row["bytes"] for row in inventory),
        "evidence_archive": copy.deepcopy(evidence_ref),
        **caps,
    }


def _completed_compact_disposition_inventory_v1(row, receipt, *, label):
    """Authenticate the bounded recorded inventory without reading retained files."""
    need = _unopened_need
    actual = row.get("final_attempt_bytes")
    need(type(row.get("storage_bytes")) is int and row["storage_bytes"] > 0
         and type(actual) is int and 0 <= actual <= row["storage_bytes"]
         and row.get("attempt_exceeded_reservation") is False
         and type(row.get("final_external_charged_bytes")) is int
         and row["final_external_charged_bytes"] == 0
         and type(row.get("final_total_charged_bytes")) is int
         and row["final_total_charged_bytes"] == actual
         and row.get("process_scope") == receipt.get("process_scope") == "sampled_birth_bound_descendants"
         and type(receipt.get("artifact_count")) is int
         and 1 <= receipt["artifact_count"] <= _COMPLETED_WATCHDOG_MAX_ARTIFACTS
         and type(receipt.get("artifact_bytes")) is int and receipt["artifact_bytes"] == actual
         and receipt.get("artifact_manifest_schema") == "retained-artifact-inventory/v1"
         and "artifacts" not in receipt,
         f"{label} compact disposition inventory differs")


def _completed_compact_disposition_references_v1(row, receipt, helper, attempt, proof, *, label):
    """Authenticate the same pair of detached recorded descriptors for both categories."""
    need = _unopened_need
    references = [receipt.get("artifact_inventory_manifest"), receipt.get("evidence_archive")]
    for reference in references:
        need(type(reference) is dict and set(reference) == {"path", "bytes", "sha256"}
             and type(reference["bytes"]) is int and 0 < reference["bytes"] <= MAX_RECOVERY_MANIFEST_BYTES,
             f"{label} recorded evidence descriptor differs")
        _sampled_pin(reference.get("sha256"), f"recorded {label} evidence")
        path = _unopened_path(reference.get("path"), f"{label} recorded archive")
        need(str(path) == reference["path"] and any(root in path.parents for root in helper.roots)
             and path not in (helper.ledger_path, helper.lock_path, attempt) and attempt not in path.parents,
             f"{label} recorded archive scope differs")
    need(references[0]["path"] != references[1]["path"]
         and sum(ref["bytes"] for ref in references) <= row["storage_bytes"]
         and references[1]["sha256"] == proof["proof_sha256"],
         f"{label} detached inventory/evidence binding differs")

def _private_completed_ledger_disposition_fields_v1(row, receipt, helper, attempt):
    """Inspect private-ledger compact accounting history without qualification credit."""
    need = _unopened_need
    label = "private completed-ledger"
    _completed_compact_disposition_inventory_v1(row, receipt, label=label)
    proof = receipt.get("sampled_custody_proof")
    need(type(proof) is dict and proof.get("schema") == "selected-original-sampled-validation-custody/v1"
         and proof.get("original_failure_profile") == _PRIVATE_SNAPSHOT_COMPLETED_LEDGER_FINALIZATION_PROFILE
         and type(proof.get("original_command_returncode")) is int and proof["original_command_returncode"] == 0
         and type(proof.get("original_cli_returncode")) is int and proof["original_cli_returncode"] == 1
         and proof.get("original_failure_preserved") is True
         and proof.get("historical_evidence_selected_by_caller") is True
         and proof.get("completed_body_ledger_finalization_optin") is True
         and proof.get("completed_body_ledger_private_snapshot_optin") is True
         and "completed_body_watchdog_finalization_optin" not in proof
         and proof.get("sealed_full9_prewrite_guard_required") is True
         and proof.get("sealed_full9_rechecked_before_write") is True
         and all(proof.get(key) is False for key in (
             "original_owner_completed", "retroactive_qualification_claimed",
             "cryptographic_execution_attestation", "reconstructed_Popen_handle",
             "arbitrary_descendant_completeness_claimed")),
         "private completed-ledger disposition lost failed original-owner provenance")
    cli = proof.get("producer_sha256")
    sdk = _COMPLETED_LEDGER_SOURCE_PAIRS.get(cli) if type(cli) is str else None
    host = "3d1086df85ca33394c71f848e6bb45f954d369d2e977b9b73df92941f9ff4075"
    need(sdk is not None
         and proof.get("producer_sha256") == proof.get("private_subject_producer_sha256") == cli
         and proof.get("owner_sdk_sha256") == proof.get("private_subject_sdk_sha256") == sdk
         and proof.get("private_subject_resource_owner_sha256") == host
         and proof.get("private_subject_pin_scope") == "original_declared_pytest_file_pins_not_execution_attestation",
         "private completed-ledger recorded source pairs differ")
    canonical = _unopened_path(proof.get("canonical_source_owner_root"), "private completed-ledger canonical root")
    snapshot = _unopened_path(proof.get("original_working_directory"), "private completed-ledger snapshot root")
    need(str(canonical) == proof["canonical_source_owner_root"]
         and str(snapshot) == proof["original_working_directory"]
         and all(snapshot != root and root not in snapshot.parents and snapshot not in root.parents
                 for root in (canonical, canonical.parent / "ipfs_accelerate")),
         "private completed-ledger recorded cwd scope differs")
    original, current = proof.get("original_storage_limit_bytes"), proof.get("current_storage_limit_bytes")
    need(type(original) is int and original > 0 and type(current) is int and current == original
         and proof.get("storage_limit_transition") == "unchanged/v1"
         and proof.get("original_resource_owner_sha256") is None
         and all(receipt.get(key) == proof.get(key) for key in (
             "original_storage_limit_bytes", "current_storage_limit_bytes",
             "storage_limit_transition", "original_resource_owner_sha256")),
         "private completed-ledger recorded storage cap differs")
    sealed = proof.get("sealed_completed_artifacts")
    need(type(sealed) is dict and set(sealed) == {"result", "execution", "durability"}
         and type(proof.get("original_sealed_artifact_count")) is int
         and 1 <= proof["original_sealed_artifact_count"] <= _COMPLETED_WATCHDOG_MAX_ARTIFACTS
         and proof["original_sealed_artifact_count"] + 2 == receipt["artifact_count"],
         "private completed-ledger recorded sealed population differs")
    for name, relative in (("result", "logs/result.json"), ("execution", "logs/execution.json"),
                           ("durability", "logs/validation-durability.json")):
        reference = sealed[name]
        need(type(reference) is dict and set(reference) == {"path", "bytes", "sha256"}
             and reference.get("path") == str(attempt / relative)
             and type(reference.get("bytes")) is int and 0 < reference["bytes"] <= 4 * 1024**2,
             "private completed-ledger recorded sealed descriptor differs")
        _sampled_pin(reference.get("sha256"), "recorded private completed-ledger sealed artifact")
    for key in ("proof_sha256", "request_sha256", "terminal_sha256", "stdout_sha256", "parent_closeout_sha256"):
        _sampled_pin(proof.get(key), "recorded private completed-ledger " + key)
    need(proof["request_sha256"] == row.get("validation_request_sha256")
         and receipt.get("capacity_policy") == "administrative_closeout"
         and receipt.get("original_failure_preserved") is True
         and all(receipt.get(key) is False for key in (
             "cap_changed", "request_budget_changed", "native_release_performed",
             "source_authority_granted", "retroactive_qualification_claimed",
             "test_or_task_acceptance_asserted", "new_reservation_created", "new_resource_lease_acquired"))
         and receipt.get("final_accounting_is_prewrite_projection") is True
         and receipt.get("actual_postwrite_census_required") is True
         and type(receipt.get("fresh_global_inventory_count")) is int
         and receipt["fresh_global_inventory_count"] == 2,
         "private completed-ledger disposition authority or accounting profile differs")
    _completed_compact_disposition_references_v1(row, receipt, helper, attempt, proof, label=label)


def _completed_watchdog_profile(proof_raw, artifact_inventory_manifest, evidence_archive, **inputs):
    """Bind existing original DATA; never adapt original frames or create archives."""
    profile = _sampled_proof(proof_raw, **inputs,
        _manual_private_snapshot=True, _completed_watchdog=True)
    return _completed_compact_bind_v1(profile, proof_raw, artifact_inventory_manifest,
        evidence_archive, key="_completed_watchdog_compact")


def _completed_watchdog_evidence(profile, helper, record, inventory):
    """Preserve the existing watchdog-only evidence boundary."""
    selected = _completed_compact_selection_v1(profile)
    _unopened_need(selected is not None and selected["key"] == "_completed_watchdog_compact",
        "completed watchdog compact failure category differs")
    return _completed_compact_evidence_v1(profile, helper, record, inventory)


def inspect_completed_watchdog_validation_recovery_v1(ledger_path, *, roots, reservation_id,
        expected_record_sha256, attempt_directory, expected_artifacts, proof_raw,
        expected_proof_sha256, expected_request_sha256, expected_terminal_sha256,
        expected_stdout_sha256, expected_parent_closeout_sha256, expected_producer_sha256,
        artifact_inventory_manifest, evidence_archive, artifacts_durable=False,
        ledger_lock_timeout_seconds=5):
    """Observe exact failed-finalization storage readiness, without recovery.

    A completed command is an historical fact. The original owner still failed;
    this profile supplies no test/native qualification or retry authority.
    Detached metadata must already exist; this operation creates no archive.
    """
    _unopened_need(type(ledger_lock_timeout_seconds) in (int, float)
        and math.isfinite(ledger_lock_timeout_seconds) and 0 <= ledger_lock_timeout_seconds <= 30,
        "bounded completed watchdog ledger lock timeout required")
    profile = _completed_watchdog_profile(proof_raw, artifact_inventory_manifest, evidence_archive,
        expected_proof_sha256=expected_proof_sha256, expected_request_sha256=expected_request_sha256,
        expected_terminal_sha256=expected_terminal_sha256, expected_stdout_sha256=expected_stdout_sha256,
        expected_parent_closeout_sha256=expected_parent_closeout_sha256,
        expected_producer_sha256=expected_producer_sha256, ledger_path=ledger_path, roots=roots,
        reservation_id=reservation_id, expected_record_sha256=expected_record_sha256,
        attempt_directory=attempt_directory, expected_artifacts=expected_artifacts,
        artifacts_durable=artifacts_durable)
    return _inspect_sampled_validation_profile_v1(ledger_path, profile, roots,
        reservation_id, expected_record_sha256, ledger_lock_timeout_seconds)


def reconcile_completed_watchdog_validation_reservation_v1(ledger_path, *, roots, reservation_id,
        expected_record_sha256, attempt_directory, expected_artifacts, proof_raw,
        expected_proof_sha256, expected_request_sha256, expected_terminal_sha256,
        expected_stdout_sha256, expected_parent_closeout_sha256, expected_producer_sha256,
        artifact_inventory_manifest, evidence_archive, artifacts_durable=False,
        capacity_policy="require_capacity", ledger_lock_timeout_seconds=5):
    """Explicitly close one failed original owner's storage promise only.

    Default reconciliation remains denial. The explicit administrative selection
    repeats all original process/native/root/record/durable-inventory guards,
    performs two fresh censuses, and commits only a compact inventory/proof
    reference. It changes no runtime budget and preserves the failed outcome.
    """
    _unopened_need(type(capacity_policy) is str and capacity_policy == "administrative_closeout",
        "completed watchdog recovery requires explicit administrative_closeout")
    _unopened_need(type(ledger_lock_timeout_seconds) in (int, float)
        and math.isfinite(ledger_lock_timeout_seconds) and 0 <= ledger_lock_timeout_seconds <= 30,
        "bounded completed watchdog ledger lock timeout required")
    profile = _completed_watchdog_profile(proof_raw, artifact_inventory_manifest, evidence_archive,
        expected_proof_sha256=expected_proof_sha256, expected_request_sha256=expected_request_sha256,
        expected_terminal_sha256=expected_terminal_sha256, expected_stdout_sha256=expected_stdout_sha256,
        expected_parent_closeout_sha256=expected_parent_closeout_sha256,
        expected_producer_sha256=expected_producer_sha256, ledger_path=ledger_path, roots=roots,
        reservation_id=reservation_id, expected_record_sha256=expected_record_sha256,
        attempt_directory=attempt_directory, expected_artifacts=expected_artifacts,
        artifacts_durable=artifacts_durable)
    return _reconcile_sampled_validation_profile_v1(ledger_path, profile, roots,
        reservation_id, expected_record_sha256, attempt_directory, artifacts_durable,
        capacity_policy, ledger_lock_timeout_seconds)


def _completed_watchdog_disposition_fields(row, receipt, helper, attempt):
    """Authenticate compact recorded storage history without opening archives."""
    need = _unopened_need
    _completed_compact_disposition_inventory_v1(row, receipt, label="completed watchdog")
    proof = receipt.get("sampled_custody_proof")
    need(type(proof) is dict and proof.get("schema") == "selected-original-sampled-validation-custody/v1"
         and proof.get("original_failure_profile") == _COMPLETED_WATCHDOG_FAILURE_PROFILE
         and type(proof.get("original_command_returncode")) is int and proof["original_command_returncode"] == 0
         and type(proof.get("original_cli_returncode")) is int and proof["original_cli_returncode"] == 1
         and proof.get("original_failure_preserved") is True
         and proof.get("historical_evidence_selected_by_caller") is True
         and proof.get("completed_body_watchdog_finalization_optin") is True
         and all(proof.get(key) is False for key in (
             "original_owner_completed", "retroactive_qualification_claimed",
             "cryptographic_execution_attestation", "reconstructed_Popen_handle",
             "arbitrary_descendant_completeness_claimed")),
         "completed watchdog disposition lost failed original-owner provenance")
    caps = _completed_watchdog_storage_limits(proof.get("original_storage_limit_bytes"),
        proof.get("current_storage_limit_bytes"), proof.get("original_resource_owner_sha256"))
    # Both recorded limits describe the release epoch. The original ledger
    # reader independently binds today's live cap; a later authorized ledger
    # migration does not invalidate authentic recorded storage closeout.
    need(type(resources.MAX_STORAGE_BYTES) is int
         and type(receipt.get("original_storage_limit_bytes")) is int
         and type(receipt.get("current_storage_limit_bytes")) is int
         and all(proof.get(key) == value and receipt.get(key) == value
                 for key, value in caps.items()),
         "completed watchdog recorded original/current storage limits differ")
    pairs = {
        "280bf5bcb4d1cdc42ba91d5e1d71d6c867fb6e575833957eca7fc79d5e3228a4":
            "11e5110aa8dcf39c5b11c0bd06a6d02933052e917fa46bf6d53a5467107d6def",
        "269eca283dbe83548602a102f31d81eed1232b85d1dfbeb861cde9d17edb0d4f":
            "4df3f7f2c6d2952550dd78153b579f4e928e9f119e697bded8a7dc001021f8d2",
        "86c8c151e559e4f4e665c475348e3a81665f008ba69298b3829d474b4873035f":
            "4df3f7f2c6d2952550dd78153b579f4e928e9f119e697bded8a7dc001021f8d2",
        "7ce92270e5a203b4bea00451997712ba5255ba3552728721d6457486157d57e3":
            "860d25af0ab629c48bb7a2c7356c7690c09fdfe81b53777777c0a41384f1b293",
    }
    owner = proof.get("producer_sha256")
    subject = proof.get("private_subject_producer_sha256")
    need(type(owner) is str and owner in pairs and proof.get("owner_sdk_sha256") == pairs[owner]
         and type(subject) is str and subject in pairs
         and proof.get("private_subject_sdk_sha256") == pairs[subject]
         and proof.get("private_subject_pin_scope") == "original_declared_subject_pins_not_execution_attestation",
         "completed watchdog recorded owner/subject source pairs differ")
    for key in ("proof_sha256", "request_sha256", "terminal_sha256", "stdout_sha256",
                "parent_closeout_sha256"):
        _sampled_pin(proof.get(key), "recorded completed watchdog " + key)
    need(proof["request_sha256"] == row.get("validation_request_sha256")
         and receipt.get("capacity_policy") == "administrative_closeout"
         and receipt.get("original_failure_preserved") is True
         and all(receipt.get(key) is False for key in (
             "cap_changed", "request_budget_changed", "native_release_performed",
             "source_authority_granted", "retroactive_qualification_claimed",
             "test_or_task_acceptance_asserted", "new_reservation_created", "new_resource_lease_acquired"))
         and receipt.get("final_accounting_is_prewrite_projection") is True
         and receipt.get("actual_postwrite_census_required") is True
         and type(receipt.get("fresh_global_inventory_count")) is int
         and receipt["fresh_global_inventory_count"] == 2,
         "completed watchdog disposition authority or accounting profile differs")
    _completed_compact_disposition_references_v1(row, receipt, helper, attempt, proof, label="completed watchdog")


def _completed_watchdog_storage_limits(original, current, original_resource_pin):
    """Preserve historical receipt limits without changing current admission.

    Only this explicit completed-watchdog profile recognizes the recorded
    220GB-to-250GB transition. Current Source/caller pins and the existing
    ledger owner still establish the live cap; no migration is performed here.
    Equal-limit fixtures and earlier equal-limit observations retain their
    existing meaning, including independently modeled unit limits.
    """
    need = _unopened_need
    need(type(original) is int and original > 0 and type(current) is int and current > 0,
         "completed watchdog exact positive original/current storage limits required")
    transitioned = original != current
    if transitioned:
        need(original == 220_000_000_000 and current == 250_000_000_000
             and type(original_resource_pin) is str
             and original_resource_pin == "3d11147bbaa9bba35dadda391baa074fefd2ad9c851fff3a5fe2ed9542a072e3",
             "completed watchdog requires exact historical220GB/current250GB original resource source pin")
    return dict(original_storage_limit_bytes=original, current_storage_limit_bytes=current,
        storage_limit_transition=("historical220GB-current250GB/v1" if transitioned else "unchanged/v1"),
        original_resource_owner_sha256=original_resource_pin if transitioned else None)


# An explicit accounting profile; the original owner still failed.
_COMPLETED_LEDGER_FINALIZATION_PROFILE = "source-held-V5-completed-command-ledger-finalization/v1"
_PRIVATE_SNAPSHOT_COMPLETED_LEDGER_FINALIZATION_PROFILE = "private-snapshot-source-held-V5-completed-command-ledger-finalization/v1"


def _completed_ledger_finalization_original_scope_v1(request, producer, *, _private_snapshot=False):
    """Keep the original canonical cwd and private pytest selectors distinct."""
    need = _unopened_need
    need(type(_private_snapshot) is bool, "explicit completed-ledger cwd profile required")
    need(type(producer) is dict and set(producer) == {"path", "sha256"},
         "exact canonical completed-ledger producer required")
    path = _unopened_path(producer["path"], "completed-ledger producer")
    need(path.parts[-4:] == ("scripts", "ops", "legal_ir", "run_owned_validation.py"),
         "canonical completed-ledger producer path differs")
    root = path.parents[3]
    snapshot = _unopened_path(request.get("cwd"), "original completed-ledger cwd")
    need(str(snapshot) == request.get("cwd"), "original completed-ledger cwd must be normalized")
    if _private_snapshot:
        need(all(snapshot != canonical and canonical not in snapshot.parents and snapshot not in canonical.parents
                 for canonical in (root, root.parent / "ipfs_accelerate")),
             "private completed-ledger snapshot must not overlap canonical Source roots")
    else:
        need(snapshot == root, "completed-ledger canonical cwd required")
    pins = request.get("source_sha256")
    need(request.get("schema") == _SAMPLED_V5_REQUEST_SCHEMA
         and type(producer.get("sha256")) is str
         and producer["sha256"] in _COMPLETED_LEDGER_SOURCE_PAIRS
         and type(pins) is dict and pins.get(str(path)) == producer["sha256"]
         and pins.get(str(root / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/validation_run_resources.py"))
             == _COMPLETED_LEDGER_SOURCE_PAIRS[producer["sha256"]]
         and pins.get(str(root / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py"))
             == "3d1086df85ca33394c71f848e6bb45f954d369d2e977b9b73df92941f9ff4075",
         "completed-ledger canonical cwd or exact original source generation differs")
    if _private_snapshot:
        for suffix in ("scripts/ops/legal_ir/run_owned_validation.py",
                "ipfs_datasets_py/optimizers/logic_theorem_optimizer/validation_run_resources.py",
                "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py"):
            need(pins.get(str(snapshot / suffix)) == pins.get(str(root / suffix)),
                 "private completed-ledger original producer/SDK/resource source pair differs")
    checks = request.get("selected_checks")
    need(type(checks) is list and 1 <= len(checks) <= 256 and len(set(checks)) == len(checks),
         "complete original completed-ledger pytest selection required")
    for check in checks:
        need(type(check) is str and 0 < len(check) <= 8192 and "\x00" not in check,
             "literal completed-ledger pytest selector required")
        filename, separator, node = check.partition("::")
        source = _unopened_path(filename, "completed-ledger selected source")
        need(separator == "::" and node.startswith("test_") and "::" not in node
             and str(source) == filename and source.suffix == ".py" and filename in pins
             and all(source != canonical and canonical not in source.parents and source not in canonical.parents
                     for canonical in (root, root.parent / "ipfs_accelerate")),
             "completed-ledger selector must bind an exact pinned private pytest file")
        if _private_snapshot:
            need(snapshot in source.parents, "selected completed-ledger pytest file is outside original private cwd")
        _sampled_pin(pins[filename], "completed-ledger selected source")
    return root


def _completed_ledger_finalization_sealed_evidence_v1(profile):
    """Recheck the original sealed files and their owned identities before write."""
    _sampled_cleanup_deadline()
    need = _unopened_need
    spec = profile["_completed_ledger_sealed"]
    need(_digest(spec["supplied"]) == spec["supplied_sha256"],
         "completed-ledger supplied sealed descriptors changed")
    need(profile["summary"]["original_storage_limit_bytes"]
         == profile["summary"]["current_storage_limit_bytes"] == resources.MAX_STORAGE_BYTES,
         "completed-ledger original/current storage cap changed")
    attempt = profile["attempt"]
    inventory = {row["path"]: row for row in profile["artifacts"]}
    fixed = {"result": "logs/result.json", "execution": "logs/execution.json",
             "durability": "logs/validation-durability.json"}
    references = spec["references"]
    need(type(references) is dict and set(references) == set(fixed),
         "closed completed-ledger sealed artifact references required")
    stamps = {}
    fields = ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink",
              "st_size", "st_mtime_ns", "st_ctime_ns")
    def identity(info):
        return {key: getattr(info, key) for key in fields}
    def read(relative, reference):
        need(type(reference) is dict and set(reference) == {"path", "bytes", "sha256"}
             and type(reference["bytes"]) is int and 0 < reference["bytes"] <= 4 * 1024**2
             and reference["path"] == str(attempt / relative)
             and inventory.get(relative) == {"path": relative, "bytes": reference["bytes"],
                 "sha256": reference["sha256"]},
             "completed-ledger sealed descriptor/inventory binding differs")
        path = resources._safe_path(reference["path"])
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            before = os.fstat(descriptor)
            need(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid()
                 and before.st_nlink == 1 and before.st_size == reference["bytes"],
                 "owned ordinary completed-ledger sealed file required")
            blocks, count = [], 0
            while count <= before.st_size:
                _sampled_cleanup_deadline()
                block = os.read(descriptor, min(65536, before.st_size + 1 - count))
                if not block:
                    break
                blocks.append(block); count += len(block)
            os.fsync(descriptor)
            need(count == before.st_size and identity(before) == identity(os.fstat(descriptor))
                 == identity(path.lstat()), "completed-ledger sealed file changed while reading")
            stamps[relative] = identity(before)
        finally:
            os.close(descriptor)
        return _sampled_document(b"".join(blocks), reference["sha256"], "completed-ledger " + relative)
    documents = {name: read(relative, references[name]) for name, relative in fixed.items()}
    failure_row = inventory.get("logs/failure.json")
    need(type(failure_row) is dict, "original completed-ledger failure artifact required")
    failure = read("logs/failure.json", {"path": str(attempt / "logs/failure.json"),
        "bytes": failure_row["bytes"], "sha256": failure_row["sha256"]})
    need(_digest(failure) == _digest(profile["_completed_ledger_original_failure"]),
         "completed-ledger failure artifact differs from original terminal")
    request = profile["request"]
    result, execution, durability = (documents[key] for key in ("result", "execution", "durability"))
    evidence_order = ("logs/stdout.log", "logs/stderr.log", "logs/execution.json")
    need(all(relative in inventory for relative in evidence_order),
         "complete original completed-ledger output logs required")
    expected_evidence = [str(attempt / relative) for relative in evidence_order
                         if inventory[relative]["bytes"] > 0]
    need(type(result) is dict and set(result) == {"schema", "request_sha256", "executed_checks",
         "returncode", "completed", "evidence_paths"}
         and result["schema"] == "owned-validation-result/v1"
         and result["request_sha256"] == profile["summary"]["request_sha256"]
         and _digest(result["executed_checks"]) == _digest(request["selected_checks"])
         and type(result["returncode"]) is int and result["returncode"] == 0
         and result["completed"] is True
         and result["evidence_paths"] == expected_evidence,
         "exact original completed-ledger result required")
    need(type(execution) is dict and set(execution) == {"schema", "request_sha256", "executed_checks",
         "returncode", "completed", "admitted", "Lean_admitted", "resource_scope", "model_weights_downloaded",
         "authority_granted", "elapsed_seconds", "process_observation"}
         and execution["schema"] == result["schema"]
         and execution["request_sha256"] == result["request_sha256"]
         and _digest(execution["executed_checks"]) == _digest(request["selected_checks"])
         and type(execution["returncode"]) is int and execution["returncode"] == 0
         and execution["completed"] is True
         and all(execution[key] is False for key in
             ("admitted", "Lean_admitted", "model_weights_downloaded", "authority_granted"))
         and execution["resource_scope"] == "cooperative_sampled_birth_bound_descendants_and_owned_attempt"
         and _digest(execution["process_observation"]) == _digest(profile["observation"])
         and type(execution["elapsed_seconds"]) in (int, float)
         and math.isfinite(execution["elapsed_seconds"])
         and 0 <= execution["elapsed_seconds"]
         and execution["elapsed_seconds"] <= failure["elapsed_seconds"],
         "exact original completed-ledger execution required")
    need(type(durability) is dict and set(durability) == {"schema", "request_sha256", "reservation_id",
         "result_path", "result_sha256", "scope", "files", "admitted", "arbitrary_descendant_containment"}
         and durability["schema"] == "owned-validation-durability/v1"
         and durability["request_sha256"] == result["request_sha256"]
         and durability["reservation_id"] == profile["reservation_id"]
         and durability["result_path"] == "logs/result.json"
         and durability["result_sha256"] == references["result"]["sha256"]
         and durability["scope"] == "owned_files_fsynced_after_recorded_group_observed_stopped"
         and durability["admitted"] is False and durability["arbitrary_descendant_containment"] is False
         and type(durability["files"]) is list and 1 <= len(durability["files"]) <=
             (_COMPLETED_WATCHDOG_MAX_ARTIFACTS
              if profile["summary"].get("completed_body_ledger_private_snapshot_optin") is True else 4096),
         "original completed-ledger durability manifest required")
    sealed = {}
    for row in durability["files"]:
        need(type(row) is dict and set(row) == {"path", "bytes", "sha256", "device", "inode"}
             and type(row["path"]) is str and row["path"] not in sealed
             and type(row["device"]) is int and row["device"] >= 0
             and type(row["inode"]) is int and row["inode"] > 0,
             "unique original completed-ledger sealed file identity required")
        expected = {key: row[key] for key in ("path", "bytes", "sha256")}
        _sampled_artifacts([expected])
        need(inventory.get(row["path"]) == expected,
             "original completed-ledger sealed file inventory differs")
        path = resources._safe_path(attempt / row["path"])
        info = path.lstat()
        need(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1
             and info.st_dev == row["device"] and info.st_ino == row["inode"]
             and info.st_size == row["bytes"],
             "original completed-ledger sealed file inode differs")
        stamps[row["path"]] = identity(info)
        sealed[row["path"]] = expected
    need(set(sealed) == set(inventory) - {"logs/validation-durability.json", "logs/failure.json"}
         and {"logs/result.json", "logs/execution.json", "logs/stdout.log", "logs/stderr.log"} <= set(sealed),
         "complete original completed-ledger pre-failure sealed population required")
    if spec["witnesses"] is None:
        spec["witnesses"] = stamps
    else:
        need(spec["witnesses"] == stamps, "completed-ledger sealed owned full9 generation changed")
    need(_digest(spec["supplied"]) == spec["supplied_sha256"],
         "completed-ledger sealed references changed during observation")
    return {"sealed_artifact_count": len(sealed), "sealed_descriptors": copy.deepcopy(references)}


def _completed_ledger_finalization_profile_v1(proof_raw, sealed_artifacts, *, _private_snapshot=False, **inputs):
    """Select original completed-body/failed-finalize facts without changing them."""
    profile = _sampled_proof(proof_raw, **inputs, _completed_ledger_finalization=True,
        _completed_ledger_private_snapshot=_private_snapshot)
    need = _unopened_need
    need(type(sealed_artifacts) is dict and set(sealed_artifacts) == {"result", "execution", "durability"},
         "three exact completed-ledger sealed descriptors required")
    profile["_completed_ledger_sealed"] = {"references": copy.deepcopy(sealed_artifacts),
        "supplied": sealed_artifacts, "supplied_sha256": _digest(sealed_artifacts), "witnesses": None}
    original = json.loads(json.loads(proof_raw)["terminal_raw_utf8"])
    profile["_completed_ledger_original_failure"] = copy.deepcopy(original["failure"])
    sealed = _completed_ledger_finalization_sealed_evidence_v1(profile)
    profile["summary"].update(sealed_completed_artifacts=copy.deepcopy(sealed_artifacts),
        original_sealed_artifact_count=sealed["sealed_artifact_count"],
        sealed_full9_prewrite_guard_required=True)
    return profile


def inspect_completed_ledger_finalization_validation_recovery_v1(ledger_path, *, roots, reservation_id,
        expected_record_sha256, attempt_directory, expected_artifacts, proof_raw,
        expected_proof_sha256, expected_request_sha256, expected_terminal_sha256,
        expected_stdout_sha256, expected_parent_closeout_sha256, expected_producer_sha256,
        sealed_artifacts, artifacts_durable=False, ledger_lock_timeout_seconds=5):
    """Inspect this exact completed-body ledger refusal; grant no retry or release."""
    _unopened_need(type(ledger_lock_timeout_seconds) in (int, float)
        and math.isfinite(ledger_lock_timeout_seconds) and 0 <= ledger_lock_timeout_seconds <= 30,
        "bounded completed-ledger inspection lock timeout required")
    profile = _completed_ledger_finalization_profile_v1(proof_raw, sealed_artifacts,
        expected_proof_sha256=expected_proof_sha256, expected_request_sha256=expected_request_sha256,
        expected_terminal_sha256=expected_terminal_sha256, expected_stdout_sha256=expected_stdout_sha256,
        expected_parent_closeout_sha256=expected_parent_closeout_sha256,
        expected_producer_sha256=expected_producer_sha256, ledger_path=ledger_path, roots=roots,
        reservation_id=reservation_id, expected_record_sha256=expected_record_sha256,
        attempt_directory=attempt_directory, expected_artifacts=expected_artifacts,
        artifacts_durable=artifacts_durable)
    return _inspect_sampled_validation_profile_v1(ledger_path, profile, roots,
        reservation_id, expected_record_sha256, ledger_lock_timeout_seconds)


def reconcile_completed_ledger_finalization_validation_reservation_v1(ledger_path, *, roots, reservation_id,
        expected_record_sha256, attempt_directory, expected_artifacts, proof_raw,
        expected_proof_sha256, expected_request_sha256, expected_terminal_sha256,
        expected_stdout_sha256, expected_parent_closeout_sha256, expected_producer_sha256,
        sealed_artifacts, artifacts_durable=False, capacity_policy="require_capacity", ledger_lock_timeout_seconds=5):
    """Close only original accounting, retaining the failed outer owner outcome."""
    _unopened_need(type(capacity_policy) is str and capacity_policy == "administrative_closeout",
        "completed-ledger recovery requires explicit administrative_closeout")
    _unopened_need(type(ledger_lock_timeout_seconds) in (int, float)
        and math.isfinite(ledger_lock_timeout_seconds) and 0 <= ledger_lock_timeout_seconds <= 30,
        "bounded completed-ledger reconciliation lock timeout required")
    profile = _completed_ledger_finalization_profile_v1(proof_raw, sealed_artifacts,
        expected_proof_sha256=expected_proof_sha256, expected_request_sha256=expected_request_sha256,
        expected_terminal_sha256=expected_terminal_sha256, expected_stdout_sha256=expected_stdout_sha256,
        expected_parent_closeout_sha256=expected_parent_closeout_sha256,
        expected_producer_sha256=expected_producer_sha256, ledger_path=ledger_path, roots=roots,
        reservation_id=reservation_id, expected_record_sha256=expected_record_sha256,
        attempt_directory=attempt_directory, expected_artifacts=expected_artifacts,
        artifacts_durable=artifacts_durable)
    return _reconcile_sampled_validation_profile_v1(ledger_path, profile, roots,
        reservation_id, expected_record_sha256, attempt_directory, artifacts_durable,
        capacity_policy, ledger_lock_timeout_seconds)


def inspect_private_snapshot_completed_ledger_finalization_validation_recovery_v1(ledger_path, *, roots, reservation_id,
        expected_record_sha256, attempt_directory, expected_artifacts, proof_raw,
        expected_proof_sha256, expected_request_sha256, expected_terminal_sha256,
        expected_stdout_sha256, expected_parent_closeout_sha256, expected_producer_sha256,
        sealed_artifacts, artifact_inventory_manifest, evidence_archive, artifacts_durable=False, ledger_lock_timeout_seconds=5):
    """Inspect this exact completed-body ledger refusal; grant no retry or release."""
    _unopened_need(type(ledger_lock_timeout_seconds) in (int, float)
        and math.isfinite(ledger_lock_timeout_seconds) and 0 <= ledger_lock_timeout_seconds <= 30,
        "bounded completed-ledger inspection lock timeout required")
    profile = _completed_ledger_finalization_profile_v1(proof_raw, sealed_artifacts, _private_snapshot=True,
        expected_proof_sha256=expected_proof_sha256, expected_request_sha256=expected_request_sha256,
        expected_terminal_sha256=expected_terminal_sha256, expected_stdout_sha256=expected_stdout_sha256,
        expected_parent_closeout_sha256=expected_parent_closeout_sha256,
        expected_producer_sha256=expected_producer_sha256, ledger_path=ledger_path, roots=roots,
        reservation_id=reservation_id, expected_record_sha256=expected_record_sha256,
        attempt_directory=attempt_directory, expected_artifacts=expected_artifacts,
        artifacts_durable=artifacts_durable)
    _completed_compact_bind_v1(profile, proof_raw, artifact_inventory_manifest,
        evidence_archive, key="_private_completed_ledger_compact")
    return _inspect_sampled_validation_profile_v1(ledger_path, profile, roots,
        reservation_id, expected_record_sha256, ledger_lock_timeout_seconds)



def reconcile_private_snapshot_completed_ledger_finalization_validation_reservation_v1(ledger_path, *, roots, reservation_id,
        expected_record_sha256, attempt_directory, expected_artifacts, proof_raw,
        expected_proof_sha256, expected_request_sha256, expected_terminal_sha256,
        expected_stdout_sha256, expected_parent_closeout_sha256, expected_producer_sha256,
        sealed_artifacts, artifact_inventory_manifest, evidence_archive, artifacts_durable=False, capacity_policy="require_capacity", ledger_lock_timeout_seconds=5):
    """Close only original accounting, retaining the failed outer owner outcome."""
    _unopened_need(type(capacity_policy) is str and capacity_policy == "administrative_closeout",
        "completed-ledger recovery requires explicit administrative_closeout")
    _unopened_need(type(ledger_lock_timeout_seconds) in (int, float)
        and math.isfinite(ledger_lock_timeout_seconds) and 0 <= ledger_lock_timeout_seconds <= 30,
        "bounded completed-ledger reconciliation lock timeout required")
    profile = _completed_ledger_finalization_profile_v1(proof_raw, sealed_artifacts, _private_snapshot=True,
        expected_proof_sha256=expected_proof_sha256, expected_request_sha256=expected_request_sha256,
        expected_terminal_sha256=expected_terminal_sha256, expected_stdout_sha256=expected_stdout_sha256,
        expected_parent_closeout_sha256=expected_parent_closeout_sha256,
        expected_producer_sha256=expected_producer_sha256, ledger_path=ledger_path, roots=roots,
        reservation_id=reservation_id, expected_record_sha256=expected_record_sha256,
        attempt_directory=attempt_directory, expected_artifacts=expected_artifacts,
        artifacts_durable=artifacts_durable)
    _completed_compact_bind_v1(profile, proof_raw, artifact_inventory_manifest,
        evidence_archive, key="_private_completed_ledger_compact")
    return _reconcile_sampled_validation_profile_v1(ledger_path, profile, roots,
        reservation_id, expected_record_sha256, attempt_directory, artifacts_durable,
        capacity_policy, ledger_lock_timeout_seconds)
