"""Explicit administrative closeout of a source-bound, failed pre-master owner.

This separate public recovery path handles a positively identified orchestration
failure before the first native master was created. It never synthesizes a
native STOP/fence, expires by age, admits work, deletes files, changes storage
roots/cap, or rehydrates another process's ResourceLease. The original owner must
already be absent. Every proof/input is explicitly pinned by the operator.

Install this module beside autoencoder_resource_recovery in the native package;
it deliberately uses that package's unchanged ledger, durability, census and
atomic-write implementation. A later independent actual census is required.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time

from . import autoencoder_resource_recovery as base

resources = base.resources
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MAX_PIN_BYTES = 32 * 1024 * 1024
PROOF_SCHEMA = "source-bound-quack-pre-master-failure/v1"


def _need(value, message):
    if not value:
        raise resources.DaemonResourceError(message)


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _pinned(pin):
    _need(type(pin) is dict and set(pin) == {"path", "bytes", "sha256"}
          and type(pin["path"]) is str and Path(pin["path"]).is_absolute()
          and type(pin["bytes"]) is int and 0 < pin["bytes"] <= _MAX_PIN_BYTES
          and type(pin["sha256"]) is str and _SHA.fullmatch(pin["sha256"]),
          "closed bounded source/evidence pin required")
    path = resources._safe_path(pin["path"])
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        before = os.fstat(descriptor)
        _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
              and before.st_uid == os.getuid() and not before.st_mode & 0o002
              and before.st_size == pin["bytes"], "pinned evidence is not an owned regular file")
        blocks, count = [], 0
        while True:
            block = os.read(descriptor, min(65536, pin["bytes"] + 1 - count))
            if not block:
                break
            count += len(block)
            _need(count <= pin["bytes"], "pinned evidence grew")
            blocks.append(block)
        raw = b"".join(blocks)
        os.fsync(descriptor)
        identity = lambda v: (v.st_dev, v.st_ino, v.st_size, v.st_mtime_ns, v.st_ctime_ns)
        _need(count == pin["bytes"] and hashlib.sha256(raw).hexdigest() == pin["sha256"]
              and identity(before) == identity(os.fstat(descriptor))
              and identity(before) == identity(path.stat()), "pinned evidence changed")
        return raw
    finally:
        os.close(descriptor)


def _document(pin):
    return json.loads(_pinned(pin), object_pairs_hook=resources._json_pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(resources.DaemonResourceError("nonfinite evidence")))


def _contained(path, roots):
    return any(root in path.parents for root in roots)


def _absent_branch(path):
    """Prove absence even when no parent directories were ever created."""
    _need(path.is_absolute() and ".." not in path.parts, "absolute unaliased generation path required")
    for part in (*reversed(path.parents), path):
        try:
            info = part.lstat()
        except FileNotFoundError:
            return True
        _need(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode),
              "native generation path has an aliased or nondirectory prefix")
    return False


def durable_external_inventory(directory):
    """Fsync/hash owned external files and lexical symlinks without following.

    Unlike an attempt inventory, an existing repository may already contain a
    symlink. Preserve its lstat byte charge and hash only readlink bytes. No
    target is opened, resolved, authorized or claimed durable. Special files and
    aliased regular files still refuse. The caller freezes this exact inventory
    before closeout; closeout repeats it around both global censuses.
    """
    root = resources._safe_path(directory, directory=True)
    root_identity = resources._root_identity(root)
    pending, directories, rows, count = [root], [], [], 0
    identity = lambda value: (value.st_dev, value.st_ino, value.st_mode, value.st_size,
                              value.st_mtime_ns, value.st_ctime_ns)
    while pending:
        current = resources._safe_path(pending.pop(), directory=True)
        directories.append(current)
        with os.scandir(current) as entries:
            children = sorted(entries, key=lambda entry: entry.name)
        for entry in children:
            count += 1
            _need(count <= resources.MAX_INVENTORY_ENTRIES, "external inventory bound exceeded")
            path = current / entry.name
            before = path.lstat()
            if stat.S_ISDIR(before.st_mode):
                resources._safe_path(path, directory=True)
                pending.append(path)
                continue
            if stat.S_ISLNK(before.st_mode):
                resources._safe_path(path.parent, directory=True)
                raw = os.readlink(os.fsencode(path))
                _need(type(raw) is bytes and len(raw) == before.st_size
                      and identity(before) == identity(path.lstat()), "external symlink changed")
                rows.append({"path": str(path.relative_to(root)), "kind": "symlink",
                             "bytes": before.st_size, "sha256": hashlib.sha256(raw).hexdigest()})
                continue
            _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
                  "external inventory requires unaliased regular files or lexical symlinks")
            resources._safe_path(path)
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
            with os.fdopen(descriptor, "rb") as stream:
                opened = os.fstat(stream.fileno())
                _need(identity(before) == identity(opened) and stat.S_ISREG(opened.st_mode)
                      and opened.st_nlink == 1, "external regular file identity changed")
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
                os.fsync(stream.fileno())
                _need(identity(before) == identity(os.fstat(stream.fileno()))
                      and identity(before) == identity(path.lstat()), "external regular file changed")
            rows.append({"path": str(path.relative_to(root)), "kind": "regular",
                         "bytes": before.st_size, "sha256": digest})
    for path in directories:
        resources._safe_path(path, directory=True)
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    _need(resources._root_identity(root) == root_identity, "external root changed during inventory")
    return sorted(rows, key=lambda row: row["path"])


def _source_contract(proof, request):
    """Bind a reviewed source graph; check the decisive launch ordering as well."""
    roles = proof["source_roles"]
    _need(type(roles) is dict and set(roles) == {
        "orchestration_owner", "controller_entry", "master_launcher", "quack_owner"},
        "exact reviewed startup source roles required")
    declared = request.get("source_sha256")
    _need(type(declared) is dict and 0 < len(declared) <= 512, "original source graph missing")
    source_pins = proof["source_pins"]
    _need(type(source_pins) is list and len(source_pins) == len(declared), "complete original source graph required")
    by_path = {}
    for pin in source_pins:
        raw = _pinned(pin)
        _need(pin["path"] not in by_path and declared.get(pin["path"]) == pin["sha256"],
              "source pin differs from original admission request")
        by_path[pin["path"]] = raw
    _need(set(by_path) == set(declared) and len(set(roles.values())) == 4
          and all(path in by_path for path in roles.values()), "startup source graph is incomplete")
    _need(request["command"] == ["/usr/bin/python3", "-B", roles["controller_entry"]],
          "only the original explicit Python controller is supported")
    launcher = ast.parse(by_path[roles["master_launcher"]], roles["master_launcher"])
    owners = ast.parse(by_path[roles["quack_owner"]], roles["quack_owner"])
    funcs = [node for node in launcher.body if isinstance(node, ast.FunctionDef)
             and node.name == "run_retained_supervisor"]
    owner_funcs = [node for node in owners.body if isinstance(node, ast.FunctionDef)
                   and node.name == "retained_quack_owner"]
    _need(len(funcs) == len(owner_funcs) == 1, "reviewed startup function identity differs")
    contexts = [node for node in ast.walk(funcs[0]) if isinstance(node, ast.With)
                and any(isinstance(item.context_expr, ast.Call)
                        and isinstance(item.context_expr.func, ast.Attribute)
                        and item.context_expr.func.attr == "retained_quack_owner" for item in node.items)]
    popens = [node for node in ast.walk(funcs[0]) if isinstance(node, ast.Call)
              and isinstance(node.func, ast.Attribute) and node.func.attr == "Popen"]
    _need(len(contexts) == len(popens) == 1 and popens[0] in list(ast.walk(contexts[0])),
          "master Popen is not contained by successful original owner startup")
    starts = [node for node in ast.walk(owner_funcs[0]) if isinstance(node, ast.Call)
              and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
              and node.func.value.id == "server" and node.func.attr == "start"]
    yields = [node for node in ast.walk(owner_funcs[0]) if isinstance(node, (ast.Yield, ast.YieldFrom))]
    _need(len(starts) == 1 and yields and all(node.lineno > starts[0].lineno for node in yields),
          "original owner can yield before successful server startup")


def _failure_evidence(proof, request, record, attempt, inventory):
    receipt = _document(proof["receipt_pin"])
    expected_request = proof["original_request_pin"]["sha256"]
    child = record.get("child")
    _need(type(child) is dict and record.get("prior_children", []) == []
          and child == proof["child_identity"], "original child custody differs")
    _need(receipt.get("schema") == "legal-ir-native-orchestration-receipt@1"
          and receipt.get("purpose") == "supervisor_launch"
          and receipt.get("request_sha256") == expected_request
          and receipt.get("owner_pid") == record["owner_pid"] == proof["owner_identity"]["pid"]
          and receipt.get("disk_reservation_id") == record["reservation_id"]
          and receipt.get("phase_lease_id") == record.get("parent_lease_id")
          and receipt.get("child_pid") == child["pid"] == receipt.get("child_pgid")
          and receipt.get("status") in {"resource_held_pending_native_fence", "resource_held_native_observer_unavailable"}
          and receipt.get("native_stop_verified") is not True,
          "original failure receipt has another identity or claims native STOP")
    for key in ("receipt_pin", "failure_log_pin", "operations_pin"):
        pin = proof[key]
        path = resources._safe_path(pin["path"])
        _need(attempt in path.parents and {"path": str(path.relative_to(attempt)),
              "bytes": pin["bytes"], "sha256": pin["sha256"]} in inventory,
              "failure evidence is not in the exact original attempt inventory")
    operations = _document(proof["operations_pin"])
    _need(type(operations) is list and len(operations) == 1
          and operations[0].get("operation") == "original_quack_capability"
          and operations[0].get("body", {}).get("catalog_opened") is False
          and operations[0].get("body", {}).get("worker_dispatched") is False,
          "native owner yielded or master startup intent was recorded")
    log = _pinned(proof["failure_log_pin"]).decode("utf-8", errors="strict")
    _need(log.startswith("Traceback (most recent call last):\n")
          and all(proof["source_roles"][role] in log
                  for role in ("controller_entry", "master_launcher", "quack_owner"))
          and all(text in log for text in ("run_retained_supervisor", "retained_quack_owner",
                  "identity = server.start()", "_bind_configured_database_status", "_resolve_database_status_scope"))
          and log.rstrip().endswith("TypedStateOwnerAuthorizationError: [REDACTED] status source binding changed"),
          "unsupported or incomplete original pre-master failure trace")
    terminal = Path(request["native_terminal_receipt"])
    generation = Path(proof["native_generation_directory"])
    _need(terminal.is_absolute() and generation == terminal.parent.parent
          and any(Path(row["path"]) in generation.parents for row in request["external_charges"]),
          "absent native generation is not the original charged runtime")
    _need(_absent_branch(generation),
          "native master generation exists; ordinary native fencing is required")
    quack = resources._safe_path(proof["quack_state_directory"], directory=True)
    _need(quack.name == "quack-owner" and any(quack.parent == Path(row["path"])
          for row in request["external_charges"]) and not any(quack.iterdir()),
          "failed original Quack state is populated or unbound")


def reconcile_failed_prelaunch_reservation(ledger_path, *, roots, reservation_id,
        expected_record_sha256, attempt_directory, expected_artifacts, proof,
        external_dispositions, artifacts_durable=False):
    """Close exactly one stopped failed-pre-master claim; never stop it here.

    ``proof`` must be a frozen closed object in PROOF_SCHEMA. Its original
    request/source/trace pins are reviewed provenance, not a replacement fence.
    External dispositions have exact original path/hash/charge and current
    durable file/lexical-symlink inventories. The full original promise stays charged through both
    censuses. A live or reused owner PID, live group, changed source/file/root,
    native generation, or later-stage launch refuses before the single write.
    """
    _need(artifacts_durable is True and type(roots) in (list, tuple) and len(roots) == 4,
          "explicit durability and original four named roots required")
    _need(type(expected_record_sha256) is str and _SHA.fullmatch(expected_record_sha256)
          and type(expected_artifacts) is list and bool(expected_artifacts), "exact original claim and durable attempt required")
    proof_fields = {"schema", "original_request_pin", "source_roles", "source_pins", "receipt_pin",
        "failure_log_pin", "operations_pin", "owner_identity", "child_identity",
        "native_generation_directory", "quack_state_directory"}
    _need(type(proof) is dict and set(proof) == proof_fields and proof["schema"] == PROOF_SCHEMA,
          "closed source-bound failed-pre-master proof required")
    _need(type(proof["owner_identity"]) is dict and set(proof["owner_identity"]) == {"pid", "birth"}
          and type(proof["owner_identity"]["pid"]) is int and proof["owner_identity"]["pid"] > 0
          and type(proof["owner_identity"]["birth"]) is str and proof["owner_identity"]["birth"].isdecimal(),
          "original owner birth witness required")
    frozen = _wire({"proof": proof, "external_dispositions": external_dispositions,
                    "expected_artifacts": expected_artifacts})
    _need(len(frozen) <= 64 * 1024 * 1024, "bounded prelaunch disposition required")
    request = _document(proof["original_request_pin"])
    _need(type(request) is dict and request.get("schema") == "legal-ir-native-orchestration-request@1"
          and request.get("purpose") == "supervisor_launch"
          and request.get("attempt_directory") == str(attempt_directory), "original launch request differs")
    _source_contract(proof, request)
    helper = resources.DaemonResourceReservation(ledger_path, roots=roots, storage_bytes=1, memory_mb=1,
        ledger_lock_timeout_seconds=30, require_existing_ledger=True)
    attempt = resources._safe_path(attempt_directory, directory=True)
    _need(_contained(attempt, helper.roots), "attempt is outside original roots")
    with helper._locked():
        ledger = helper._read()
        record = ledger["reservations"].get(reservation_id)
        _need(record is not None and record["status"] in {"active", "retained"}
              and base._digest(record) == expected_record_sha256
              and record["storage_bytes"] == request.get("storage_bytes")
              and record.get("attempt_directory") == resources._root_identity(attempt),
              "original active/retained prelaunch reservation differs")
        others_sha = base._digest({key: row for key, row in ledger["reservations"].items() if key != reservation_id})
        charges = copy.deepcopy(resources._external_charges(record))
        declared = request.get("external_charges")
        _need(type(declared) is list and 0 < len(declared) <= resources.MAX_EXTERNAL_CHARGES
              and type(external_dispositions) is list and len(external_dispositions) == len(declared),
              "complete original external charge disposition required")
        expected = {}
        for row in declared:
            _need(type(row) is dict and set(row) == {"path", "bytes"}
                  and type(row["path"]) is str and Path(row["path"]).is_absolute()
                  and type(row["bytes"]) is int and row["bytes"] >= 0, "closed original external declaration required")
            key = hashlib.sha256(row["path"].encode()).hexdigest()
            _need(key not in expected, "duplicate original external path")
            expected[key] = row
        _need({key: row["bytes"] for key, row in expected.items()} == charges,
              "original request does not bind every unchanged external charge")
        def unchanged():
            _need(_wire({"proof": proof, "external_dispositions": external_dispositions,
                        "expected_artifacts": expected_artifacts}) == frozen
                  and ledger["reservations"].get(reservation_id) is record
                  and base._digest(record) == expected_record_sha256
                  and base._digest({key: row for key, row in ledger["reservations"].items()
                                    if key != reservation_id}) == others_sha, "closeout inputs or another claim changed")
        def stopped():
            _need(resources._process(record["owner_pid"]) is None, "original owner PID still exists")
            for child in [record.get("child"), *record.get("prior_children", ())]:
                _need(not resources._group_usage(child)["live_processes"], "original child group is live")
        def verify():
            unchanged()
            stopped()
            _need(_document(proof["original_request_pin"]) == request, "original request changed")
            _source_contract(proof, request)
            inventory = base._durable_inventory(attempt)
            _need(inventory == expected_artifacts and resources._root_identity(attempt) == record["attempt_directory"],
                  "original attempt inventory changed")
            _failure_evidence(proof, request, record, attempt, inventory)
            seen, observations = set(), []
            for disposition in external_dispositions:
                _need(type(disposition) is dict and set(disposition) == {
                    "key", "path", "bytes", "directory_identity", "expected_artifacts"},
                    "closed current external disposition required")
                key = disposition["key"]
                _need(key in expected and key not in seen and disposition["path"] == expected[key]["path"]
                      and disposition["bytes"] == charges[key], "current external declaration differs")
                seen.add(key)
                path = resources._safe_path(disposition["path"], directory=True)
                _need(_contained(path, helper.roots) and path != attempt and path not in attempt.parents
                      and attempt not in path.parents, "external path overlaps attempt or escapes original roots")
                _need(resources._root_identity(path) == disposition["directory_identity"], "external directory identity changed")
                current = durable_external_inventory(path)
                _need(current == disposition["expected_artifacts"]
                      and resources._root_identity(path) == disposition["directory_identity"], "current external inventory changed")
                observations.append({"key": key, "path": str(path), "original_charged_bytes": charges[key],
                    "current_apparent_file_bytes": sum(row["bytes"] for row in current),
                    "directory_identity": disposition["directory_identity"],
                    "durable_inventory_sha256": base._digest(current), "artifact_count": len(current)})
            _need(seen == set(charges), "external disposition is incomplete")
            stopped()
            unchanged()
            helper._verify_owner_roots()
            return inventory, observations
        verified = verify()
        accounting = base._administrative_census(helper, ledger)
        _need(verify() == verified, "prelaunch evidence changed during first census")
        projected = copy.deepcopy(ledger)
        projected["reservations"][reservation_id]["status"] = "released"
        final = base._administrative_census(helper, projected)
        _need(verify() == verified and accounting["outstanding_full_reservations_bytes"]
              - final["outstanding_full_reservations_bytes"] == record["storage_bytes"]
              and base._digest({key: row for key, row in projected["reservations"].items()
                                if key != reservation_id}) == others_sha, "projected prelaunch accounting differs")
        inventory, observations = verified
        attempt_bytes = sum(row["bytes"] for row in inventory)
        external_bytes = sum(charges.values())
        receipt = {"schema": "explicit-failed-pre-master-reservation-reconciliation/v1",
            "reservation_id": reservation_id, "previous_record_sha256": expected_record_sha256,
            "original_status": record["status"], "operator_observed_owner_identity": copy.deepcopy(proof["owner_identity"]),
            "original_request_pin": copy.deepcopy(proof["original_request_pin"]),
            "proof_and_dispositions_sha256": hashlib.sha256(frozen).hexdigest(),
            "artifacts": inventory, "preserved_external_charges": charges, "external_observations": observations,
            "other_reservations_sha256": others_sha, "full_claim_accounting": accounting,
            "final_accounting": final, "capacity_policy": "administrative_closeout",
            "final_accounting_is_prewrite_projection": True, "actual_postwrite_census_required": True,
            "fresh_global_inventory_count": 2, "atomic_ledger_write_count": 1,
            "native_master_created": False, "native_fence_synthesized": False,
            "native_stop_verified": False, "failed_prelaunch_only": True,
            "historical_external_payloads_authenticated": False,
            "original_four_named_roots_preserved": True, "cap_changed": False,
            "new_reservation_created": False, "new_resource_lease_acquired": False,
            "outputs_deleted": False, "automatic_expiry": False, "admitted": False}
        # Check custody and all source/evidence again immediately before the one
        # native atomic write; there are no caller callbacks inside the lock.
        _need(verify() == verified, "prelaunch evidence changed before write")
        record.update(status="released", artifacts_durable_asserted=True, released_at=time.time(),
            final_accounting=final, final_attempt_bytes=attempt_bytes,
            final_external_charged_bytes=external_bytes, final_total_charged_bytes=attempt_bytes + external_bytes,
            attempt_exceeded_reservation=attempt_bytes + external_bytes > record["storage_bytes"],
            explicit_reconciliation=receipt)
        _need(base._digest({key: row for key, row in ledger["reservations"].items()
                           if key != reservation_id}) == others_sha, "another reservation changed before write")
        helper._verify_owner_roots()
        helper._write(ledger)
        return receipt


__all__ = ["PROOF_SCHEMA", "durable_external_inventory", "reconcile_failed_prelaunch_reservation"]
