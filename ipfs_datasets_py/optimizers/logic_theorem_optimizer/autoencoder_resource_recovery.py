"""Explicit reconciliation of one dead owner's retained disk claim.

Never expires a claim by age or deletes its outputs. The caller supplies the
exact prior record and durable artifact inventory. This is an administrative
operation, separate from the original owner's resource lease lifecycle.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
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
        capacity_policy="require_capacity"):
    """Release exactly one retained claim after explicit, verified closeout.

    The previous owner PID must be absent (a reused PID also blocks recovery).
    Every recorded child process group must be dead. The full claim remains
    charged during a fresh census. The default ``require_capacity`` policy keeps
    the existing capacity cutoff. Explicit ``administrative_closeout`` records
    over-capacity observations for this one verified claim; it never admits work
    or changes the cap. Its final accounting is a fresh prewrite projection with
    only this claim released, and needs an independent actual postwrite census.
    External charges are deliberately unsupported here: their disposition needs
    a separate recovery design.
    """
    if type(capacity_policy) is not str or capacity_policy not in {
            "require_capacity", "administrative_closeout"}:
        raise resources.DaemonResourceError("invalid reconciliation capacity policy")
    if artifacts_durable is not True or not expected_artifacts:
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
        stopped()
        inventory = _durable_inventory(attempt)
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
        if resources._root_identity(attempt) != record["attempt_directory"] or _durable_inventory(attempt) != inventory:
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
                    or _durable_inventory(attempt) != inventory):
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
