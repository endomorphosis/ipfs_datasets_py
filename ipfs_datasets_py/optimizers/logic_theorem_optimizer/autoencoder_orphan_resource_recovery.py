"""Explicit closeout of one dead ordinary-supervisor owner's active disk claim.

This additive administrative API does not transfer productive custody. It never
admits work, acquires native leases, signals processes, removes containers or
files, changes caps, or synthesizes a retained transition. The original active
record and failed owner receipt stay attributable to their actual producer.

Install/import this module inside the logic_theorem_optimizer package through
the caller's independently pinned source loader. Existing recovery and owner
modules remain unchanged. Callers must preserve the inspection, exact request,
receipt pins, external metadata snapshots and returned closeout receipt.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import heapq
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time

from . import autoencoder_resource_recovery as base
from .existing_resource_scheduler import open_existing_scheduler

resources = base.resources
SCHEMA = "explicit-dead-active-ordinary-phase-reconciliation/v2"
MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_REQUEST_BYTES = 2 * 1024 * 1024
SHA = re.compile(r"[0-9a-f]{64}\Z")
HEX_ID = re.compile(r"[0-9a-f]{32}\Z")
TERMINAL_SCHEMA = "ipfs_accelerate_py.agent_supervisor.multi-supervisor-terminal@1"
ENDPOINT = "unix:///var/run/docker.sock"
INERT_LAUNCHERS = {
    "task-launchers/provider-command-env", "task-launchers/task-bootstrap.py",
}
RELEASE_FIELDS = {"status", "artifacts_durable_asserted", "released_at", "final_accounting",
                  "final_attempt_bytes", "final_external_charged_bytes", "final_total_charged_bytes",
                  "attempt_exceeded_reservation", "explicit_orphan_reconciliation"}


def _need(value, message):
    if not value:
        raise resources.DaemonResourceError(message)


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _cid(value):
    raw = b"\x01\xa9\x02\x12\x20" + hashlib.sha256(_wire(value)).digest()
    return "b" + base64.b32encode(raw).decode("ascii").rstrip("=").lower()


def _decode(raw):
    return json.loads(raw, object_pairs_hook=resources._json_pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(resources.DaemonResourceError("nonfinite recovery metadata")))


def _read_pin(pin, *, maximum=MAX_METADATA_BYTES):
    _need(type(pin) is dict and set(pin) == {"path", "bytes", "sha256"}
          and type(pin["path"]) is str and Path(pin["path"]).is_absolute()
          and type(pin["bytes"]) is int and 0 < pin["bytes"] <= maximum
          and type(pin["sha256"]) is str and SHA.fullmatch(pin["sha256"]),
          "bounded exact metadata pin required")
    path = resources._safe_path(pin["path"])
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
              and before.st_size == pin["bytes"], "recovery metadata file identity differs")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(pin["bytes"] + 1)
            os.fsync(stream.fileno())
        identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
        _need(len(raw) == pin["bytes"] and hashlib.sha256(raw).hexdigest() == pin["sha256"]
              and identity(before) == identity(os.fstat(descriptor))
              and identity(before) == identity(path.lstat()), "recovery metadata changed")
    finally:
        os.close(descriptor)
    value = _decode(raw)
    _need(type(value) is dict, "recovery metadata object required")
    return value


def _directory_identity(path):
    path = resources._safe_path(path, directory=True)
    info = path.lstat()
    return {"path": str(path), "device": info.st_dev, "inode": info.st_ino,
            "mode": info.st_mode, "uid": info.st_uid}


def snapshot_named_root_external_directory(path, *, roots):
    """Snapshot lstat metadata only; never open regular files or follow links.

    This current pathname inventory has the same apparent-byte semantics as
    the storage ledger. It authenticates no historical external file contents,
    credentials, model data, corpus data, database state or producer outputs.
    """
    named = tuple(resources._safe_path(root, directory=True) for root in roots)
    path = resources._safe_path(path, directory=True)
    _need(any(root in path.parents for root in named), "external directory outside named roots")
    identity = _directory_identity(path)
    pending = []
    entries_sha = hashlib.sha256()
    count, apparent_bytes = 0, 0
    kinds = {"directory": 0, "file": 0, "symlink": 0}
    def enqueue(directory):
        resources._safe_path(directory, directory=True)
        with os.scandir(directory) as iterator:
            for entry in iterator:
                relative = str(Path(entry.path).relative_to(path))
                heapq.heappush(pending, (relative, Path(entry.path)))
                _need(count + len(pending) <= resources.MAX_INVENTORY_ENTRIES,
                      "external entry bound exceeded")
    enqueue(path)
    while pending:
        relative, current = heapq.heappop(pending)
        info = current.lstat()
        kind = ("directory" if stat.S_ISDIR(info.st_mode) else "file" if stat.S_ISREG(info.st_mode)
                else "symlink" if stat.S_ISLNK(info.st_mode) else "special")
        _need(kind != "special", "external special entry requires separate recovery")
        row = {"path": relative, "kind": kind, "device": info.st_dev,
               "inode": info.st_ino, "mode": info.st_mode, "uid": info.st_uid,
               "gid": info.st_gid, "bytes": info.st_size, "nlink": info.st_nlink,
               "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns}
        entries_sha.update(_wire(row) + b"\n")
        count += 1
        kinds[kind] += 1
        if kind == "directory":
            enqueue(current)
        else:
            apparent_bytes += info.st_size
    _need(_directory_identity(path) == identity, "external directory identity changed")
    value = {"schema": "named-root-external-metadata-disposition/v2",
             "path": str(path), "directory_identity": identity,
             "scope": "current_lstat_only_no_file_bodies_no_symlink_following",
             "entries_canonicalization": "UTF-8 sorted-key compact JSON rows plus LF, sorted by relative path",
             "entries_sha256": entries_sha.hexdigest(), "entry_count": count,
             "kind_counts": kinds, "apparent_bytes": apparent_bytes}
    return value


def snapshot_inert_launcher_residue(path, *, roots):
    """Read only the two generated launchers after complete metadata validation.

    Unknown credentials/capability/payload names are rejected unopened. Bound
    no-follow directory/file descriptors prevent path replacement from routing
    a subsequent read through a symlink. No file or directory is removed.
    """
    named = tuple(resources._safe_path(root, directory=True) for root in roots)
    path = resources._safe_path(path, directory=True)
    _need(any(root in path.parents for root in named)
          and path.name.startswith(("asref-grok-container-", "asref-codex-container-")),
          "inert residue outside provider named-root scope")
    identity = _directory_identity(path)
    root_info = path.lstat()
    _need(_directory_identity(path) == identity and root_info.st_uid == os.getuid()
          and not stat.S_IMODE(root_info.st_mode) & 0o077,
          "residual lease directory is not owner-only")
    children = list(path.iterdir())
    _need(len(children) == 1 and children[0].name == "task-launchers",
          "residual lease has unsupported capability or artifacts")
    launchers = children[0]
    directory_info = launchers.lstat()
    _need(stat.S_ISDIR(directory_info.st_mode) and directory_info.st_uid == os.getuid()
          and not stat.S_IMODE(directory_info.st_mode) & 0o077,
          "residual launcher directory is not owner-only")
    sources = sorted(launchers.iterdir())
    _need({str(file.relative_to(path)) for file in sources} == INERT_LAUNCHERS
          and len(sources) == len(INERT_LAUNCHERS),
          "residual lease has unsupported capability or artifacts")
    expected = {}
    for file in sources:
        info = file.lstat()
        _need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_uid == os.getuid()
              and stat.S_IMODE(info.st_mode) == 0o500 and 0 < info.st_size <= MAX_METADATA_BYTES,
              "residual launcher is not bounded owner-only readonly source")
        expected[file.name] = info
    root_fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    launcher_fd = None
    artifacts = []
    physical = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mode,
                            info.st_uid, info.st_nlink, info.st_mtime_ns, info.st_ctime_ns)
    try:
        _need(physical(os.fstat(root_fd)) == physical(root_info), "residual lease root changed")
        launcher_fd = os.open("task-launchers", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
        _need(physical(os.fstat(launcher_fd)) == physical(directory_info), "residual launcher directory changed")
        for name, before in sorted(expected.items()):
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=launcher_fd)
            try:
                _need(physical(os.fstat(descriptor)) == physical(before), "residual launcher source changed before read")
                digest = hashlib.sha256()
                count = 0
                while True:
                    block = os.read(descriptor, min(65536, before.st_size + 1 - count))
                    if not block:
                        break
                    count += len(block)
                    _need(count <= before.st_size, "residual launcher source grew")
                    digest.update(block)
                os.fsync(descriptor)
                current = os.stat(name, dir_fd=launcher_fd, follow_symlinks=False)
                _need(count == before.st_size and physical(os.fstat(descriptor)) == physical(before)
                      and physical(current) == physical(before), "residual launcher source changed")
                artifacts.append({"path": "task-launchers/" + name, "bytes": count, "sha256": digest.hexdigest()})
            finally:
                os.close(descriptor)
        _need({entry.name for entry in path.iterdir()} == {"task-launchers"}
              and {entry.name for entry in launchers.iterdir()} == set(expected), "residual tree changed during read")
        _need(physical(path.lstat()) == physical(root_info)
              and physical(launchers.lstat()) == physical(directory_info)
              and _directory_identity(path) == identity, "residual directory changed during read")
        os.fsync(launcher_fd)
        os.fsync(root_fd)
    finally:
        if launcher_fd is not None:
            os.close(launcher_fd)
        os.close(root_fd)
    return {"path": str(path), "directory_identity": identity, "artifacts": artifacts}


def _helper(ledger_path, roots):
    _need(type(roots) in (list, tuple) and len(roots) == 4, "original four named roots required")
    return resources.DaemonResourceReservation(ledger_path, roots=roots,
        storage_bytes=1, memory_mb=1, ledger_lock_timeout_seconds=60, require_existing_ledger=True)


def _selected(ledger, reservation_id, owner_pid, attempt):
    _need(type(reservation_id) is str and HEX_ID.fullmatch(reservation_id), "exact reservation ID required")
    _need(type(owner_pid) is int and owner_pid > 0, "exact original owner PID required")
    record = ledger["reservations"].get(reservation_id)
    _need(record is not None and record["status"] == "active" and record["owner_pid"] == owner_pid,
          "exact active orphan reservation differs")
    _need(record.get("workload") == "canonical_parented_phase" and record.get("scheduler_lane") == "orchestration",
          "only original ordinary orchestration phase supported")
    _need(record.get("attempt_directory") == resources._root_identity(attempt), "orphan attempt identity differs")
    _need(resources._process(owner_pid) is None, "original owner PID still exists")
    for child in [record.get("child"), *record.get("prior_children", ())]:
        _need(not resources._group_usage(child)["live_processes"], "original recorded group still live")
    return record


def inspect_selected_orphan_reservation(ledger_path, *, roots, reservation_id,
                                        expected_owner_pid, attempt_directory):
    """Inspect exactly one dead active owner; expose no foreign record bodies."""
    helper = _helper(ledger_path, roots)
    attempt = resources._safe_path(attempt_directory, directory=True)
    _need(any(root in attempt.parents for root in helper.roots), "attempt outside named roots")
    with helper._locked():
        ledger = helper._read()
        record = _selected(ledger, reservation_id, expected_owner_pid, attempt)
        result = {"schema": "selected-dead-active-phase-inspection/v1", "reservation_id": reservation_id,
                  "record_sha256": base._digest(record), "original_status": record["status"],
                  "owner_pid": record["owner_pid"], "storage_bytes": record["storage_bytes"],
                  "attempt_directory": copy.deepcopy(record["attempt_directory"]),
                  "external_charges": copy.deepcopy(resources._external_charges(record)),
                  "native_lease_id": record.get("native_lease_id"), "parent_lease_id": record.get("parent_lease_id"),
                  "expected_artifacts": base._durable_inventory(attempt),
                  "new_resource_lease_acquired": False, "ledger_written": False}
        _selected(ledger, reservation_id, expected_owner_pid, attempt)
        return result


def _docker_probe(*arguments):
    executable = Path("/usr/bin/docker")
    info = executable.lstat()
    _need(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022
          and os.access(executable, os.X_OK), "trusted Docker executable unavailable")
    result = subprocess.run([str(executable), "--host=" + ENDPOINT, "--config", "/nonexistent", *arguments],
        stdin=subprocess.DEVNULL, capture_output=True, timeout=15, check=False,
        env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "LANG": "C"})
    _need(len(result.stdout) <= 4096 and len(result.stderr) <= 4096, "Docker observation exceeded bound")
    if result.returncode:
        if arguments[:2] == ("container", "inspect") and b"No such container:" in result.stderr:
            return None
        raise resources.DaemonResourceError("Docker observation unavailable")
    return result.stdout.decode("ascii").strip()


def _runtime_fences(request, owner_receipt, proof, attempt, helper):
    _need(type(proof) is dict and set(proof) == {"native_terminal_pin", "provider_observations_pin",
          "provider_allocation_pin", "inert_residual_lease_directories"}, "closed runtime proof required")
    terminal = _read_pin(proof["native_terminal_pin"])
    _need(proof["native_terminal_pin"]["path"] == request["native_terminal_receipt"], "native terminal path differs")
    body = dict(terminal)
    terminal_cid = body.pop("terminal_receipt_cid", None)
    observed = owner_receipt.get("native_fence_proof")
    fields = {"master_pid", "run_started_at_epoch_nanoseconds", "master_start_time_ticks",
              "active_binding_cid", "terminal_receipt_cid", "all_trees_fenced"}
    _need(type(observed) is dict and set(observed) == fields and observed["all_trees_fenced"] is True
          and owner_receipt.get("native_stop_verified") is True
          and owner_receipt.get("owned_group_quiescent") is True,
          "original bound native fence missing")
    _need(terminal.get("schema") == TERMINAL_SCHEMA and terminal_cid == _cid(body)
          and terminal.get("all_trees_fenced") is True
          and terminal.get("label") == request["board_namespace"], "invalid native terminal CID or fence")
    for field in fields - {"master_start_time_ticks"}:
        _need(terminal.get(field) == observed[field], "native fence generation differs")
    _need(type(observed["master_pid"]) is int and observed["master_pid"] > 0
          and type(observed["master_start_time_ticks"]) is int
          and type(observed["run_started_at_epoch_nanoseconds"]) is int
          and 0 < observed["run_started_at_epoch_nanoseconds"] <= time.time_ns()
          and isinstance(observed["active_binding_cid"], str) and observed["active_binding_cid"],
          "invalid original master birth")
    master = resources._process(observed["master_pid"])
    _need(master is None or (master["birth"] == str(observed["master_start_time_ticks"])
          and master["state"] == "Z"), "native master is live or PID reused")
    allocation = _read_pin(proof["provider_allocation_pin"])
    observations = _read_pin(proof["provider_observations_pin"])
    _need(all(attempt in Path(proof[key]["path"]).parents for key in
              ("provider_observations_pin", "provider_allocation_pin")), "provider proofs outside original attempt")
    temporary = resources._safe_path(request["supervised_provider_temporary_root"], directory=True)
    _need(any(root in temporary.parents for root in helper.roots)
          and temporary != attempt and attempt not in temporary.parents, "provider temporary scope differs")
    _need(allocation.get("schema") == "legal-ir-ordinary-provider-daemon-allocation@1"
          and allocation.get("endpoint") == ENDPOINT and allocation.get("temporary_root") == str(temporary)
          and isinstance(allocation.get("daemon_id"), str)
          and re.fullmatch(r"[0-9a-f-]{36}", allocation["daemon_id"]), "original Docker allocation differs")
    _need(observations.get("schema") == "legal-ir-owned-ordinary-provider-cleanup-observations@1"
          and observations.get("observation_only") is True
          and type(observations.get("bindings")) is list and 0 < len(observations["bindings"]) <= 16,
          "original provider bindings missing")
    _need(_docker_probe("info", "--format", "{{.ID}}") == allocation["daemon_id"], "Docker daemon identity differs")
    roots = set()
    names = set()
    for binding in observations["bindings"]:
        _need(type(binding) is dict and set(binding) == {"provider", "container_name", "lease_root",
              "watchdog_pid", "watchdog_start_time_ticks", "creator_pid", "endpoint", "daemon_id"},
              "closed original provider binding required")
        provider, name = binding["provider"], binding["container_name"]
        _need(provider in {"grok", "codex"} and type(name) is str, "invalid provider binding")
        match = re.fullmatch(r"ipfs-accelerate-" + provider + r"-([0-9]+)-[0-9a-f]{32}", name)
        _need(match is not None and type(binding["creator_pid"]) is int and binding["creator_pid"] > 0
              and int(match.group(1)) == binding["creator_pid"]
              and name not in names and binding["endpoint"] == ENDPOINT
              and binding["daemon_id"] == allocation["daemon_id"], "provider daemon or container binding differs")
        names.add(name)
        lease_root = Path(binding["lease_root"])
        _need(lease_root.is_absolute() and str(lease_root) == binding["lease_root"]
              and str(lease_root) not in roots and lease_root.parent == temporary
              and lease_root.name.startswith("asref-" + provider + "-container-"),
              "provider lease directory differs")
        roots.add(str(lease_root))
        _need(type(binding["watchdog_pid"]) is int and binding["watchdog_pid"] > 0
              and type(binding["watchdog_start_time_ticks"]) is int, "invalid watchdog birth")
        watchdog = resources._process(binding["watchdog_pid"])
        _need(watchdog is None or (watchdog["birth"] == str(binding["watchdog_start_time_ticks"])
              and watchdog["state"] == "Z"), "watchdog is live or PID reused")
        _need(_docker_probe("container", "inspect", "--format", "{{.Id}}", name) is None,
              "original provider container still exists")
    residuals = proof["inert_residual_lease_directories"]
    _need(type(residuals) is list and len(residuals) <= len(roots), "bounded inert residue disposition required")
    present = {str(path) for pattern in ("asref-grok-container-*", "asref-codex-container-*")
               for path in temporary.glob(pattern)}
    _need(present <= roots, "unbound provider lease directory remains")
    seen = set()
    for residue in residuals:
        _need(type(residue) is dict and set(residue) == {"path", "directory_identity", "artifacts"}
              and residue["path"] in present and residue["path"] not in seen,
              "unknown or duplicate inert residue")
        seen.add(residue["path"])
        path = resources._safe_path(residue["path"], directory=True)
        _need(snapshot_inert_launcher_residue(path, roots=helper.roots) == residue,
              "inert residue tree or generated source changed")
    _need(present == seen, "remaining lease directory has no exact inert disposition")
    return {"native_terminal_cid": terminal_cid, "active_binding_cid": observed["active_binding_cid"],
            "master_pid": observed["master_pid"], "daemon_id": allocation["daemon_id"],
            "container_names": sorted(names), "all_observed_containers_absent": True,
            "watchdogs_absent_or_exact_zombies": True, "inert_residual_directory_count": len(seen),
            "historical_observer_unresolved": observations.get("unresolved"),
            "historical_observer_error_cleared": False}


def reconcile_dead_active_external_reservation(ledger_path, *, roots, reservation_id,
        expected_owner_pid, expected_record_sha256, attempt_directory, expected_artifacts,
        original_request_pin, original_owner_receipt_pin, runtime_proof, external_dispositions,
        scheduler_state_path, expected_scheduler_policy_sha256, artifacts_durable=False):
    """Atomically close one dead active phase after fresh native/OS/Docker fences.

    All metadata inputs are frozen by value and rechecked around two complete
    storage censuses. External directory inventories are lstat-only; original
    declared charges remain historical estimates. Native leases must already
    be inactive through the public scheduler. This API never retires them.
    """
    _need(artifacts_durable is True, "explicit durability assertion required")
    _need(type(expected_record_sha256) is str and SHA.fullmatch(expected_record_sha256), "exact original record hash required")
    _need(type(expected_artifacts) is list and bool(expected_artifacts), "nonempty exact attempt inventory required")
    packet = {"original_request_pin": original_request_pin, "original_owner_receipt_pin": original_owner_receipt_pin,
              "runtime_proof": runtime_proof, "external_dispositions": external_dispositions,
              "expected_artifacts": expected_artifacts}
    frozen_raw = _wire(packet)
    _need(len(frozen_raw) <= 32 * 1024 * 1024, "orphan recovery packet exceeds bound")
    frozen = _decode(frozen_raw)
    helper = _helper(ledger_path, roots)
    attempt = resources._safe_path(attempt_directory, directory=True)
    _need(any(root in attempt.parents for root in helper.roots), "attempt outside named roots")
    scheduler = open_existing_scheduler(scheduler_state_path, expected_scheduler_policy_sha256)
    with helper._locked():
        ledger = helper._read()
        record = _selected(ledger, reservation_id, expected_owner_pid, attempt)
        _need(base._digest(record) == expected_record_sha256, "original active record hash differs")
        _need(record.get("scheduler_state_path") == str(Path(scheduler_state_path))
              and record.get("scheduler_policy_sha256") == expected_scheduler_policy_sha256,
              "original scheduler state/policy binding differs")
        original_record = copy.deepcopy(record)
        others_sha = base._digest({key: value for key, value in ledger["reservations"].items() if key != reservation_id})
        request = _read_pin(frozen["original_request_pin"], maximum=MAX_REQUEST_BYTES)
        receipt = _read_pin(frozen["original_owner_receipt_pin"])
        _need(Path(frozen["original_owner_receipt_pin"]["path"]) == attempt / "receipt.json",
              "original owner receipt path differs")
        _need(request.get("schema") == "legal-ir-native-orchestration-request@1"
              and request.get("purpose") == "supervisor_launch" and request.get("attempt_directory") == str(attempt)
              and request.get("storage_bytes") == record["storage_bytes"], "original supervisor request differs")
        _need(receipt.get("schema") == "legal-ir-native-orchestration-receipt@1"
              and receipt.get("purpose") == "supervisor_launch" and receipt.get("owner_pid") == expected_owner_pid
              and receipt.get("request_sha256") == frozen["original_request_pin"]["sha256"]
              and receipt.get("disk_reservation_id") == reservation_id, "owner receipt does not bind original request/claim")
        lease_ids = {receipt.get("root_lease_id"), receipt.get("phase_lease_id"), record.get("native_lease_id")}
        _need(len(lease_ids) == 3 and all(type(value) is str and HEX_ID.fullmatch(value) for value in lease_ids)
              and record.get("parent_lease_id") == receipt["phase_lease_id"], "native lease lineage differs")
        child = record.get("child")
        _need(type(child) is dict and child.get("pid") == receipt.get("child_pid") == receipt.get("child_pgid"),
              "original attached child differs")
        charges = copy.deepcopy(resources._external_charges(record))
        declared = request.get("external_charges")
        _need(type(declared) is list and len(declared) == 2 and len(charges) == 2,
              "exact ordinary repo/provider external charges required")
        paths = {}
        for charge in declared:
            _need(type(charge) is dict and set(charge) == {"path", "bytes"} and type(charge["path"]) is str
                  and Path(charge["path"]).is_absolute() and ".." not in Path(charge["path"]).parts
                  and type(charge["bytes"]) is int and charge["bytes"] > 0, "invalid original external charge")
            key = hashlib.sha256(charge["path"].encode()).hexdigest()
            _need(key not in paths and charges.get(key) == charge["bytes"], "original external charge derivation differs")
            paths[key] = charge
        _need(set(paths) == set(charges)
              and {value["path"] for value in paths.values()} == {request.get("cwd"), request.get("supervised_provider_temporary_root")},
              "external scopes differ from original repo/provider declarations")
        dispositions = frozen["external_dispositions"]
        _need(type(dispositions) is list and len(dispositions) == len(paths), "complete current external disposition required")
        by_path = {value.get("path"): value for value in dispositions if type(value) is dict}
        _need(len(by_path) == len(paths) and set(by_path) == {value["path"] for value in paths.values()},
              "external disposition path population differs")
        def unchanged():
            _need(_wire(packet) == frozen_raw, "recovery packet substituted")
            _need(ledger["reservations"].get(reservation_id) is record and base._digest(record) == expected_record_sha256,
                  "selected active record changed")
            _need(base._digest({key: value for key, value in ledger["reservations"].items() if key != reservation_id}) == others_sha,
                  "foreign reservation changed")
        def verify():
            unchanged()
            _selected(ledger, reservation_id, expected_owner_pid, attempt)
            _need(not any(row["lease_id"] in lease_ids for row in scheduler.active_leases()), "original native leases still active")
            _need(_read_pin(frozen["original_request_pin"], maximum=MAX_REQUEST_BYTES) == request
                  and _read_pin(frozen["original_owner_receipt_pin"]) == receipt, "original request/receipt changed")
            inventory = base._durable_inventory(attempt)
            _need(inventory == frozen["expected_artifacts"], "original durable attempt inventory differs")
            _need(sum(row["bytes"] for row in inventory) + sum(charges.values()) <= record["storage_bytes"],
                  "original total declared claim exceeded")
            current_external = []
            for key, charge in sorted(paths.items()):
                path = Path(charge["path"])
                _need(path != attempt and attempt not in path.parents and path not in attempt.parents,
                      "external scope overlaps original attempt")
                current = snapshot_named_root_external_directory(path, roots=helper.roots)
                _need(current == by_path[charge["path"]], "current external metadata disposition changed")
                current_external.append({"key": key, "path": charge["path"], "declared_bytes": charge["bytes"],
                    "current_apparent_bytes": current["apparent_bytes"], "entry_count": current["entry_count"],
                    "metadata_sha256": _sha(current), "historical_payloads_authenticated": False})
            runtime = _runtime_fences(request, receipt, frozen["runtime_proof"], attempt, helper)
            _selected(ledger, reservation_id, expected_owner_pid, attempt)
            _need(not any(row["lease_id"] in lease_ids for row in scheduler.active_leases()), "native lease reappeared")
            unchanged()
            return inventory, current_external, runtime
        verified = verify()
        accounting = base._administrative_census(helper, ledger)
        _need(verify() == verified, "orphan evidence changed during first census")
        projected = copy.deepcopy(ledger)
        projected["reservations"][reservation_id]["status"] = "released"
        projected_record_sha = base._digest(projected["reservations"][reservation_id])
        final = base._administrative_census(helper, projected)
        _need(verify() == verified, "orphan evidence changed during projected census")
        _need(accounting["outstanding_full_reservations_bytes"] - final["outstanding_full_reservations_bytes"] == record["storage_bytes"]
              and base._digest(projected["reservations"][reservation_id]) == projected_record_sha
              and base._digest({key: value for key, value in projected["reservations"].items() if key != reservation_id}) == others_sha,
              "projected orphan accounting differs")
        inventory, external, runtime = verified
        outcome = {"schema": SCHEMA, "reservation_id": reservation_id,
            "previous_record_sha256": expected_record_sha256, "original_status": original_record["status"],
            "original_record_fields": sorted(original_record),
            "original_overwritten_fields": {key: copy.deepcopy(original_record[key])
                for key in sorted(RELEASE_FIELDS) if key in original_record},
            "released_at_epoch": time.time(),
            "original_owner_pid": expected_owner_pid, "reconciled_by_pid": os.getpid(),
            "request_sha256": frozen["original_request_pin"]["sha256"],
            "original_owner_receipt_sha256": frozen["original_owner_receipt_pin"]["sha256"],
            "packet_sha256": hashlib.sha256(frozen_raw).hexdigest(), "artifacts": inventory,
            "preserved_external_charges": charges, "external_observations": external,
            "runtime_fences": runtime, "inactive_native_lease_ids": sorted(lease_ids),
            "other_reservations_sha256": others_sha, "full_claim_accounting": accounting, "final_accounting": final,
            "final_accounting_is_prewrite_projection": True, "actual_postwrite_census_required": True,
            "fresh_global_inventory_count": 2, "atomic_ledger_write_count": 1,
            "historical_retained_transition_synthesized": False, "old_failed_receipt_rewritten": False,
            "new_reservation_created": False, "new_resource_lease_acquired": False, "cap_changed": False,
            "outputs_deleted": False, "automatic_expiry": False, "admitted": False,
            "productive_custody_transferred": False}
        unchanged()
        record.update(status="released", artifacts_durable_asserted=True, released_at=outcome["released_at_epoch"],
            final_accounting=final, final_attempt_bytes=sum(row["bytes"] for row in inventory),
            final_external_charged_bytes=sum(charges.values()),
            final_total_charged_bytes=sum(row["bytes"] for row in inventory) + sum(charges.values()),
            attempt_exceeded_reservation=False, explicit_orphan_reconciliation=outcome)
        _need(base._digest({key: value for key, value in ledger["reservations"].items() if key != reservation_id}) == others_sha,
              "foreign reservation changed before write")
        _need(resources._process(expected_owner_pid) is None, "original owner PID reappeared before write")
        for original_child in [original_record.get("child"), *original_record.get("prior_children", ())]:
            _need(not resources._group_usage(original_child)["live_processes"], "recorded group reappeared before write")
        helper._verify_owner_roots()
        helper._write(ledger)
        return outcome


def verify_selected_orphan_closeout(ledger_path, *, roots, reservation_id,
        attempt_directory, expected_reconciliation, scheduler_state_path,
        expected_scheduler_policy_sha256):
    """Verify the public closeout result against actual released state/census.

    This is a read-only administrative observation. It obtains no resource
    grant and never writes a ledger. Actual current accounting can differ from
    the closeout's prewrite projection because unrelated owners may progress.
    Only aggregate foreign-record hashes are exposed, never their bodies.
    """
    _need(type(reservation_id) is str and HEX_ID.fullmatch(reservation_id), "exact reservation ID required")
    _need(type(expected_reconciliation) is dict, "exact public reconciliation result required")
    frozen_raw = _wire(expected_reconciliation)
    _need(len(frozen_raw) <= 4 * 1024 * 1024, "postwrite verification receipt exceeds bound")
    frozen = _decode(frozen_raw)
    _need(frozen.get("schema") == SCHEMA and frozen.get("reservation_id") == reservation_id
          and frozen.get("original_status") == "active"
          and frozen.get("historical_retained_transition_synthesized") is False
          and frozen.get("actual_postwrite_census_required") is True,
          "exact dead-active closeout receipt required")
    helper = _helper(ledger_path, roots)
    attempt = resources._safe_path(attempt_directory, directory=True)
    _need(any(root in attempt.parents for root in helper.roots), "attempt outside named roots")
    scheduler = open_existing_scheduler(scheduler_state_path, expected_scheduler_policy_sha256)
    with helper._locked():
        ledger = helper._read()
        selected = ledger["reservations"].get(reservation_id)
        _need(selected is not None and selected["status"] == "released"
              and selected.get("explicit_orphan_reconciliation") == frozen
              and selected.get("owner_pid") == frozen.get("original_owner_pid")
              and selected.get("attempt_directory") == resources._root_identity(attempt)
              and selected.get("scheduler_state_path") == str(Path(scheduler_state_path))
              and selected.get("scheduler_policy_sha256") == expected_scheduler_policy_sha256,
              "actual released claim or original binding differs")
        original_fields = frozen.get("original_record_fields")
        overwritten = frozen.get("original_overwritten_fields")
        _need(type(original_fields) is list and all(type(key) is str for key in original_fields)
              and original_fields == sorted(set(original_fields))
              and type(overwritten) is dict and set(overwritten) == set(original_fields) & RELEASE_FIELDS
              and set(selected) == set(original_fields) | RELEASE_FIELDS,
              "original/released field population differs")
        reconstructed = {key: copy.deepcopy(selected[key]) for key in original_fields}
        reconstructed.update(copy.deepcopy(overwritten))
        _need(base._digest(reconstructed) == frozen.get("previous_record_sha256")
              and selected.get("released_at") == frozen.get("released_at_epoch")
              and selected.get("final_accounting") == frozen.get("final_accounting"),
              "untouched original claim fields or release attribution differ")
        selected_sha = base._digest(selected)
        others_sha = base._digest({key: value for key, value in ledger["reservations"].items() if key != reservation_id})
        def verify():
            _need(_wire(expected_reconciliation) == frozen_raw
                  and ledger["reservations"].get(reservation_id) is selected
                  and base._digest(selected) == selected_sha,
                  "released claim or public receipt changed during postwrite census")
            _need(base._digest({key: value for key, value in ledger["reservations"].items() if key != reservation_id}) == others_sha,
                  "foreign record changed during locked postwrite census")
            _need(resources._process(selected["owner_pid"]) is None, "original owner PID still exists")
            for child in [selected.get("child"), *selected.get("prior_children", ())]:
                _need(not resources._group_usage(child)["live_processes"], "original recorded group still live")
            _need(not any(row["lease_id"] in frozen["inactive_native_lease_ids"] for row in scheduler.active_leases()),
                  "original native lease remains active")
            inventory = base._durable_inventory(attempt)
            _need(inventory == frozen["artifacts"] and resources._root_identity(attempt) == selected["attempt_directory"],
                  "original durable artifacts or attempt identity differ")
            _need(resources._external_charges(selected) == frozen["preserved_external_charges"]
                  and selected.get("artifacts_durable_asserted") is True
                  and selected.get("final_attempt_bytes") == sum(item["bytes"] for item in inventory)
                  and selected.get("final_external_charged_bytes") == sum(frozen["preserved_external_charges"].values())
                  and selected.get("final_total_charged_bytes") == selected["final_attempt_bytes"] + selected["final_external_charged_bytes"]
                  and selected.get("attempt_exceeded_reservation") is False,
                  "released claim final accounting differs")
            return inventory
        inventory = verify()
        actual = base._administrative_census(helper, ledger)
        _need(verify() == inventory, "postwrite evidence changed during actual census")
        return {"schema": "actual-dead-active-orphan-closeout-verification/v1",
            "reservation_id": reservation_id, "selected_status": "released",
            "selected_record_sha256": selected_sha, "previous_record_sha256": frozen["previous_record_sha256"],
            "reconciliation_sha256": hashlib.sha256(frozen_raw).hexdigest(),
            "original_status": "active", "actual_accounting": actual,
            "actual_postwrite_census_complete": True, "accounting_is_prewrite_projection": False,
            "current_other_reservations_sha256": others_sha,
            "matches_closeout_foreign_snapshot": others_sha == frozen["other_reservations_sha256"],
            "original_artifacts_preserved": True, "native_lease_ids_inactive": True,
            "ledger_written": False, "new_resource_lease_acquired": False, "admitted": False,
            "observed_at_epoch": time.time()}


__all__ = ["inspect_selected_orphan_reservation", "snapshot_named_root_external_directory",
           "snapshot_inert_launcher_residue", "reconcile_dead_active_external_reservation",
           "verify_selected_orphan_closeout"]
