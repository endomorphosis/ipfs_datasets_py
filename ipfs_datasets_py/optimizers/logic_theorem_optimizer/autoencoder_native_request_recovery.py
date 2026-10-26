"""Explicit closeout of one stopped native-request owner's external disk claim.

The supported launcher digest establishes a request/receipt format and a charge
key recipe. It is not a cryptographic attestation of execution or permission to
release an arbitrary ledger. Callers must separately select the actual ledger,
named roots, retained preimage and original documents. This operation acquires no
scheduler grant, deletes no output and changes no capacity policy.

External trees receive repeated, bounded descriptor metadata observations. Their
payloads are not read or declared historically durable. Only the strict attempt
artifacts receive the existing durable-content inventory. Observations are
cooperative rather than atomic or continuous custody proofs.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import time

from . import autoencoder_resource_recovery as base
from . import existing_resource_scheduler as existing_scheduler
from .autoencoder_external_tree_inventory import observe_external_tree


SCHEMA = "explicit-native-request-retained-reservation-reconciliation/v1"
OPAQUE_SCHEMA = "explicit-native-request-retained-reservation-reconciliation/v2"
PROVENANCE_PROFILE = "native_owner_request_sha256_path_key/v1"
SUPPORTED_OWNER_SHA256 = "e2f66d5901f73ea99028d704703698745a16b83b4328589aa5e1b47c04d532c7"
MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
MAX_DESCRIPTOR_BYTES = 64 * 1024 * 1024
MAX_ARTIFACTS = 100_000
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[0-9a-f]{32}\Z")
_IDENTITY_KEYS = {"device", "inode", "mode", "uid", "gid", "nlink", "size", "mtime_ns", "ctime_ns"}
_BOUND_KEYS = {"max_entries", "max_bytes", "max_depth", "max_symlink_hops",
               "max_path_bytes", "max_link_target_bytes", "max_serialized_bytes",
               "max_resolution_steps"}
_INVENTORY_KEYS = {"schema", "root_path", "root_identity", "entries", "entry_count",
                   "apparent_bytes", "bounds", "metadata_only", "payload_files_opened",
                   "symlink_directories_enqueued", "directory_open_no_follow",
                   "atomic_snapshot", "continuous_custody_proved", "inventory_sha256"}
_OPAQUE_KEYS = {"symlink_resolution", "opaque_symlinks", "opaque_link_referents_observed",
                "opaque_link_target_custody_asserted", "opaque_link_target_durability_asserted"}
_OPAQUE_PROFILE = "internal_except_explicit_opaque"


def _need(condition, message):
    if not condition:
        raise base.resources.DaemonResourceError(message)


def _integer(value, name, *, minimum=0, maximum=(1 << 63) - 1):
    _need(type(value) is int and minimum <= value <= maximum, "invalid " + name)
    return value


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def _same(left, right):
    # Python object equality conflates True and 1; identities must not.
    return _canonical(left) == _canonical(right)


def _path(value):
    _need(type(value) is str and 0 < len(value.encode("utf-8")) <= 4096
          and "\x00" not in value, "invalid canonical path")
    path = Path(value)
    _need(path.is_absolute() and str(path) == value and os.path.normpath(value) == value,
          "noncanonical recovery path")
    return path


def _read_pin(pin, *, maximum=MAX_DOCUMENT_BYTES):
    _need(type(pin) is dict and set(pin) == {"path", "bytes", "sha256"}, "invalid original document pin")
    path = _path(pin["path"])
    _integer(pin["bytes"], "document bytes", minimum=1, maximum=maximum)
    _need(type(pin["sha256"]) is str and _SHA.fullmatch(pin["sha256"]), "invalid document digest")
    identity = lambda info: (info.st_dev, info.st_ino, info.st_mode, info.st_uid,
                             info.st_gid, info.st_nlink, info.st_size,
                             info.st_mtime_ns, info.st_ctime_ns)
    namespace = lambda info: (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid)
    _need(len(path.parts) <= 257, "original document path depth exceeded")
    anchors = []
    try:
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            root_before = os.fstat(fd)
        except BaseException:
            os.close(fd)
            raise
        anchors.append(("/", fd, root_before))
        for name in path.parts[1:-1]:
            parent = anchors[-1][1]
            observed = os.stat(name, dir_fd=parent, follow_symlinks=False)
            _need(stat.S_ISDIR(observed.st_mode), "original document parent is not a directory")
            fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            anchors.append((name, fd, observed))
            _need(namespace(os.fstat(fd)) == namespace(observed)
                  == namespace(os.stat(name, dir_fd=parent, follow_symlinks=False)),
                  "original document parent changed")
        parent = anchors[-1][1]
        expected = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        _need(stat.S_ISREG(expected.st_mode) and expected.st_nlink == 1
              and expected.st_size == pin["bytes"], "original document identity differs")
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            _need(identity(before) == identity(expected), "original document changed on open")
            raw = stream.read(maximum + 1)
            after = os.fstat(stream.fileno())
        _need(identity(before) == identity(after)
              == identity(os.stat(path.name, dir_fd=parent, follow_symlinks=False))
              and len(raw) == pin["bytes"] and hashlib.sha256(raw).hexdigest() == pin["sha256"],
              "original document changed")
        for index, (name, fd, before) in enumerate(anchors):
            current = (os.stat("/", follow_symlinks=False) if index == 0 else
                       os.stat(name, dir_fd=anchors[index - 1][1], follow_symlinks=False))
            _need(namespace(current) == namespace(before) == namespace(os.fstat(fd)),
                  "original document namespace changed")
        return raw
    finally:
        for _, fd, _ in reversed(anchors):
            os.close(fd)


def _decode(raw):
    def finite_float(text):
        number = float(text)
        _need(math.isfinite(number), "nonfinite original document number")
        return number
    try:
        return json.loads(raw, object_pairs_hook=base.resources._json_pairs,
                          parse_float=finite_float,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    except (ValueError, UnicodeError, RecursionError) as error:
        raise base.resources.DaemonResourceError("invalid original document JSON") from error


def _artifacts(value):
    _need(type(value) is list and 1 <= len(value) <= MAX_ARTIFACTS, "explicit durable artifact inventory required")
    names = set()
    for row in value:
        _need(type(row) is dict and set(row) == {"path", "bytes", "sha256"}, "invalid durable artifact row")
        name = row["path"]
        _need(type(name) is str and name and not Path(name).is_absolute()
              and str(Path(name)) == name and ".." not in Path(name).parts
              and "\x00" not in name and len(name.encode("utf-8")) <= 4096,
              "invalid durable artifact path")
        _need(name not in names, "durable artifacts must be unique")
        names.add(name)
        _integer(row["bytes"], "artifact bytes")
        _need(type(row["sha256"]) is str and _SHA.fullmatch(row["sha256"]), "invalid artifact digest")
    return copy.deepcopy(value)


def _descriptor(value, path, charged_bytes):
    _need(type(value) is dict, "invalid descriptor inventory schema")
    opaque = value.get("schema") == "autoencoder-external-tree-descriptor-inventory@2"
    _need(set(value) == (_INVENTORY_KEYS | _OPAQUE_KEYS if opaque else _INVENTORY_KEYS),
          "invalid descriptor inventory schema")
    _need(value["schema"] == ("autoencoder-external-tree-descriptor-inventory@2" if opaque
                              else "autoencoder-external-tree-descriptor-inventory@1")
          and value["root_path"] == str(path), "descriptor root differs")
    _need(value["metadata_only"] is True and value["payload_files_opened"] is False
          and value["symlink_directories_enqueued"] is False
          and value["directory_open_no_follow"] is True and value["atomic_snapshot"] is False
          and value["continuous_custody_proved"] is False, "invalid descriptor observation scope")
    bounds = value["bounds"]
    _need(type(bounds) is dict and set(bounds) == _BOUND_KEYS, "invalid descriptor bounds")
    _integer(bounds["max_entries"], "descriptor entry bound", maximum=65536)
    _integer(bounds["max_depth"], "descriptor depth bound", maximum=256)
    _integer(bounds["max_symlink_hops"], "descriptor hop bound", maximum=256)
    _integer(bounds["max_bytes"], "descriptor byte bound")
    _need(bounds["max_bytes"] == charged_bytes, "descriptor byte bound differs from original charge")
    for name, expected in (("max_path_bytes", 4096), ("max_link_target_bytes", 4096),
                           ("max_serialized_bytes", MAX_DESCRIPTOR_BYTES)):
        _need(type(bounds[name]) is int and bounds[name] == expected, "descriptor fixed bound differs")
    _integer(bounds["max_resolution_steps"], "descriptor resolution bound")
    _need(bounds["max_resolution_steps"] == 4 * (bounds["max_entries"] + 1)
          * (bounds["max_depth"] + bounds["max_symlink_hops"] + 1), "descriptor resolution bound differs")
    def identity(row):
        _need(type(row) is dict and set(row) == _IDENTITY_KEYS, "invalid descriptor identity")
        for name in _IDENTITY_KEYS:
            if name in {"mtime_ns", "ctime_ns"}:
                # POSIX timestamps may predate the epoch. A signed 64-bit
                # seconds value plus nanoseconds fits within this finite bound.
                _integer(row[name], "descriptor identity " + name,
                         minimum=-(1 << 95), maximum=(1 << 95) - 1)
            else:
                _integer(row[name], "descriptor identity " + name, maximum=(1 << 64) - 1)
    identity(value["root_identity"])
    _need(stat.S_ISDIR(value["root_identity"]["mode"]), "descriptor root is not a directory")
    rows = value["entries"]
    _need(type(rows) is list and len(rows) <= bounds["max_entries"], "descriptor entry bound exceeded")
    _integer(value["entry_count"], "descriptor entry count", maximum=bounds["max_entries"])
    _need(value["entry_count"] == len(rows), "descriptor entry count differs")
    _integer(value["apparent_bytes"], "descriptor apparent bytes", maximum=charged_bytes)
    opaque_links = {}
    if opaque:
        _need(value["symlink_resolution"] == _OPAQUE_PROFILE
              and value["opaque_link_referents_observed"] is False
              and value["opaque_link_target_custody_asserted"] is False
              and value["opaque_link_target_durability_asserted"] is False,
              "invalid opaque link observation scope")
        manifest = value["opaque_symlinks"]
        _need(type(manifest) is list and 1 <= len(manifest) <= min(128, bounds["max_entries"]),
              "explicit bounded nonempty opaque link manifest required")
        previous_opaque = None
        for link in manifest:
            _need(type(link) is dict and set(link) == {"path", "link_target"},
                  "invalid opaque link manifest row")
            name, target = link["path"], link["link_target"]
            _need(type(name) is str and name not in {"", "."} and not Path(name).is_absolute()
                  and str(Path(name)) == name and ".." not in Path(name).parts
                  and "\x00" not in name and len(os.fsencode(name)) <= 4096
                  and (previous_opaque is None or previous_opaque < name),
                  "opaque link paths must be canonical unique sorted leaves")
            _need(type(target) is str and target and "\x00" not in target
                  and len(os.fsencode(target)) <= 4096, "invalid opaque literal link target")
            previous_opaque = name
            opaque_links[name] = target
    previous, apparent = None, 0
    encountered_opaque = set()
    for row in rows:
        _need(type(row) is dict and set(row) == _IDENTITY_KEYS | {"path", "kind", "link_target", "resolved_target"},
              "invalid descriptor entry")
        identity({key: row[key] for key in _IDENTITY_KEYS})
        name = row["path"]
        _need(type(name) is str and name and not Path(name).is_absolute()
              and str(Path(name)) == name and ".." not in Path(name).parts
              and "\x00" not in name and len(name.encode("utf-8")) <= 4096
              and (previous is None or previous < name), "invalid descriptor entry path")
        previous = name
        _need(type(row["kind"]) is str and row["kind"] in {"directory", "regular", "symlink"},
              "invalid descriptor entry kind")
        mode_check = {"directory": stat.S_ISDIR, "regular": stat.S_ISREG, "symlink": stat.S_ISLNK}
        _need(mode_check[row["kind"]](row["mode"]), "descriptor entry kind differs from mode")
        if row["kind"] == "symlink":
            if name in opaque_links:
                _need(type(row["link_target"]) is str
                      and row["link_target"] == opaque_links[name]
                      and row["resolved_target"] is None
                      and len(os.fsencode(row["link_target"])) == row["size"],
                      "opaque link entry differs from explicit literal manifest")
                encountered_opaque.add(name)
            else:
                for key in ("link_target", "resolved_target"):
                    _need(type(row[key]) is str and row[key] and "\x00" not in row[key]
                          and len(row[key].encode("utf-8")) <= 4096, "invalid descriptor link field")
                target = row["resolved_target"]
                _need(not Path(target).is_absolute() and ".." not in Path(target).parts
                      and str(Path(target)) == target, "invalid resolved descriptor link path")
        else:
            _need(row["link_target"] is None and row["resolved_target"] is None, "unexpected descriptor link fields")
            _need(name not in opaque_links, "opaque manifest leaf is not a symlink")
        if row["kind"] != "directory":
            apparent += row["size"]
    _need(apparent == value["apparent_bytes"], "descriptor pathname bytes differ")
    _need(encountered_opaque == set(opaque_links), "opaque manifest leaves are missing from descriptor entries")
    _need(type(value["inventory_sha256"]) is str and _SHA.fullmatch(value["inventory_sha256"]),
          "invalid descriptor digest")
    body = {key: item for key, item in value.items() if key != "inventory_sha256"}
    encoded = _canonical(body)
    _need(len(encoded) <= MAX_DESCRIPTOR_BYTES and hashlib.sha256(encoded).hexdigest() == value["inventory_sha256"],
          "descriptor digest differs")


def _original_documents(attempt, inventory, request_pin, source_pin, record, roots):
    source = _read_pin(source_pin, maximum=1024 * 1024)
    _need(hashlib.sha256(source).hexdigest() == SUPPORTED_OWNER_SHA256, "unsupported native owner source profile")
    raw = _read_pin(request_pin)
    request = _decode(raw)
    required = {"schema", "purpose", "name", "attempt_directory", "command", "cwd",
                "duration_seconds", "storage_bytes", "external_charges", "source_sha256"}
    _need(type(request) is dict and required <= set(request)
          and set(request) <= required | {"scope", "validation_inputs"}, "unsupported native request fields")
    _need(request["schema"] == "legal-ir-native-orchestration-request@1"
          and request["purpose"] == "supervisor_preflight", "unsupported native request scope")
    _need(type(request["name"]) is str and 0 < len(request["name"]) <= 256
          and not any(ord(char) < 32 for char in request["name"]), "invalid native request name")
    _need(_path(request["attempt_directory"]) == attempt, "original request attempt differs")
    _path(request["cwd"])
    _integer(request["duration_seconds"], "original duration", minimum=10, maximum=2400)
    _integer(request["storage_bytes"], "original storage bytes", minimum=1, maximum=base.resources.MAX_STORAGE_BYTES)
    _need(request["storage_bytes"] == record["storage_bytes"], "original storage promise differs")
    command = request["command"]
    _need(type(command) is list and 1 <= len(command) <= 256
          and all(type(arg) is str and len(arg.encode("utf-8")) <= 4096 and "\x00" not in arg for arg in command),
          "invalid original command metadata")
    sources = request["source_sha256"]
    _need(type(sources) is dict and 1 <= len(sources) <= 32768, "invalid original source inventory")
    for name, digest in sources.items():
        _path(name)
        _need(type(digest) is str and _SHA.fullmatch(digest), "invalid original source digest")
    _need(sources.get(source_pin["path"]) == source_pin["sha256"], "original owner source absent from request")
    receipt_row = next((row for row in inventory if row["path"] == "receipt.json"), None)
    _need(receipt_row is not None, "original owner receipt absent from durable attempt")
    receipt_pin = {**receipt_row, "path": str(attempt / "receipt.json")}
    receipt = _decode(_read_pin(receipt_pin, maximum=1024 * 1024))
    receipt_keys = {"schema", "purpose", "request_sha256", "owner_pid", "status", "hard_enforcement",
                    "completion_authority", "root_lease_id", "phase_lease_id", "disk_reservation_id",
                    "child_pid", "child_pgid", "child_returncode", "failure_type", "owned_group_quiescent", "ended_at_epoch"}
    _need(type(receipt) is dict and set(receipt) == receipt_keys
          and receipt["schema"] == "legal-ir-native-orchestration-receipt@1"
          and receipt["purpose"] == request["purpose"]
          and receipt["status"] in {"failed", "completed"}
          and receipt["hard_enforcement"] is False and receipt["completion_authority"] is False
          and receipt["owned_group_quiescent"] is True, "invalid original terminal owner receipt")
    _need(receipt["request_sha256"] == request_pin["sha256"]
          and receipt["disk_reservation_id"] == record["reservation_id"], "original receipt request or reservation differs")
    _integer(receipt["owner_pid"], "original owner PID", minimum=1)
    _need(receipt["owner_pid"] == record["owner_pid"], "original receipt owner differs")
    child = record.get("child")
    _need(type(child) is dict and set(child) == {"pid", "birth"}, "original native child identity required")
    _integer(child["pid"], "original child PID", minimum=1)
    _need(type(child["birth"]) is str and child["birth"].isascii() and child["birth"].isdecimal()
          and int(child["birth"]) > 0, "invalid original child birth")
    _need(type(receipt["child_pid"]) is int and type(receipt["child_pgid"]) is int
          and receipt["child_pid"] == child["pid"] == receipt["child_pgid"]
          and child["pid"] != record["owner_pid"], "original receipt child differs")
    _need(type(receipt["child_returncode"]) is int
          and (receipt["failure_type"] is None or (type(receipt["failure_type"]) is str
               and 0 < len(receipt["failure_type"]) <= 128)), "invalid original terminal outcome")
    _need((receipt["status"] == "failed") == bool(receipt["failure_type"] or receipt["child_returncode"]),
          "original terminal status contradicts outcome")
    ended = receipt["ended_at_epoch"]
    _need(type(ended) in (int, float) and math.isfinite(ended) and ended > 0, "invalid original terminal timestamp")
    ids = [receipt["root_lease_id"], receipt["phase_lease_id"], record.get("native_lease_id")]
    _need(all(type(value) is str and _ID.fullmatch(value) for value in ids)
          and len(set(ids)) == 3 and receipt["phase_lease_id"] == record.get("parent_lease_id"),
          "original native lease identities differ")
    _need(record.get("workload") == "canonical_parented_phase" and record.get("scheduler_lane") == "orchestration",
          "unsupported native reservation scope")
    for key, expected in (("cpu_slots", 1), ("memory_mb", 2048), ("child_process_slots", 4)):
        _need(type(record.get(key)) is int and record[key] == expected, "native resource envelope differs")
    charges = request["external_charges"]
    _need(type(charges) is list and 1 <= len(charges) <= base.resources.MAX_EXTERNAL_CHARGES,
          "original external charges required")
    derived, paths = {}, []
    for row in charges:
        _need(type(row) is dict and set(row) == {"path", "bytes"}, "invalid original external charge")
        path = _path(row["path"])
        _integer(row["bytes"], "original external bytes", minimum=1, maximum=base.resources.MAX_STORAGE_BYTES)
        _need(any(path == root or root in path.parents for root in roots)
              and not (path == attempt or path in attempt.parents or attempt in path.parents),
              "original external path outside scope or overlaps attempt")
        _need(not any(path == other or path in other.parents or other in path.parents for other in paths),
              "original external paths overlap")
        paths.append(path)
        key = hashlib.sha256(str(path).encode("utf-8")).hexdigest()
        derived[key] = {"key": key, "path": str(path), "bytes": row["bytes"]}
    _need(_same({key: row["bytes"] for key, row in derived.items()}, base.resources._external_charges(record)),
          "original request does not cover exact external charges")
    return request, receipt_pin, ids, derived


def _stopped(record, request, lease_ids):
    resources = base.resources
    _need(resources._process(record["owner_pid"]) is None, "original reservation owner PID still exists")
    children = record.get("prior_children", [])
    _need(type(children) is list and len(children) <= resources.MAX_CHILDREN_PER_RESERVATION,
          "invalid original child history")
    for child in [record["child"], *children]:
        _need(type(child) is dict and set(child) == {"pid", "birth"}, "invalid original child history row")
        _integer(child["pid"], "recorded child PID", minimum=1)
        _need(type(child["birth"]) is str and child["birth"].isascii()
              and child["birth"].isdecimal() and int(child["birth"]) > 0, "invalid recorded child birth")
        _need(resources._group_usage(child)["live_processes"] == 0, "retained child group is still alive")
    scheduler_path = resources._safe_path(_path(record.get("scheduler_state_path")))
    policy = record.get("scheduler_policy_sha256")
    _need(type(policy) is str and _SHA.fullmatch(policy), "original scheduler policy identity required")
    _, state = existing_scheduler._read(scheduler_path)
    _need(existing_scheduler.policy_sha256(state["config"]) == policy, "original scheduler policy changed")
    names = {request["name"], request["name"] + ":phase", "daemon:" + record["reservation_id"]}
    for collection in ("leases", "waiters"):
        for identity, row in state[collection].items():
            _need(identity not in lease_ids and row.get("lease_id") not in lease_ids
                  and row.get("parent_lease_id") not in lease_ids
                  and row.get("owner_pid") != record["owner_pid"]
                  and row.get("request_id") not in names, "original native lease or waiter remains")


def reconcile_retained_native_request_reservation(ledger_path, *, roots, reservation_id,
        expected_record_sha256, attempt_directory, expected_artifacts,
        original_request_pin, original_owner_source_pin, external_dispositions,
        artifacts_durable=False):
    """Close exactly one retained request-bound claim using two native censuses.

    The complete claim stays charged for the first census. The second census is
    an administrative prewrite projection only: it grants no new allocation and
    does not require existing overage to disappear. An independent actual
    postwrite census remains required. A failure from the atomic writer may
    occur after replacement; callers must inspect durable state rather than
    assume rollback or blindly retry. No idempotent release of a later state is
    inferred: the exact original retained preimage is always required.

    Descriptor schema @1 retains strict internal target resolution. Explicit @2
    inventories may name a bounded, nonempty exact opaque-link manifest. Only
    those symlink inodes/literal targets are observed; their referents are never
    probed and receive no containment, custody or durability claim. Every other
    link retains the strict policy. The same exact manifest is reobserved at all
    three evidence boundaries; no link is ignored or its pathname bytes waived.
    """
    resources = base.resources
    _need(artifacts_durable is True, "explicit artifact durability assertion required")
    _need(type(reservation_id) is str and _ID.fullmatch(reservation_id), "invalid retained reservation ID")
    _need(type(expected_record_sha256) is str and _SHA.fullmatch(expected_record_sha256), "invalid retained preimage digest")
    artifacts = _artifacts(expected_artifacts)
    for pin in (original_request_pin, original_owner_source_pin):
        _need(type(pin) is dict and set(pin) == {"path", "bytes", "sha256"}, "invalid original document pin")
    request_pin = dict(original_request_pin)
    source_pin = dict(original_owner_source_pin)
    _need(type(external_dispositions) is list and 1 <= len(external_dispositions) <= resources.MAX_EXTERNAL_CHARGES,
          "explicit external dispositions required")
    dispositions = external_dispositions
    helper = resources.DaemonResourceReservation(ledger_path, roots=roots, storage_bytes=1,
        memory_mb=1, ledger_lock_timeout_seconds=30, require_existing_ledger=True)
    attempt = resources._safe_path(_path(os.fspath(attempt_directory)), directory=True)
    _need(any(root in attempt.parents for root in helper.roots), "recovery attempt outside named root descendants")
    with helper._locked():
        ledger = helper._read()
        ledger_sha = base._digest(ledger)
        record = ledger["reservations"].get(reservation_id)
        _need(type(record) is dict and base._digest(record) == expected_record_sha256
              and record["status"] == "retained", "retained reservation identity changed")
        _need(_same(record.get("attempt_directory"), resources._root_identity(attempt)), "recovery attempt identity changed")
        original_record = copy.deepcopy(record)
        other_sha = base._digest({key: value for key, value in ledger["reservations"].items() if key != reservation_id})
        request, receipt_pin, lease_ids, derived = _original_documents(
            attempt, artifacts, request_pin, source_pin, record, helper.roots)
        rows = {}
        serialized_bytes = 0
        for row in dispositions:
            _need(type(row) is dict and set(row) == {"key", "path", "bytes", "descriptor_inventory"},
                  "invalid external disposition fields")
            key = row["key"]
            _need(type(key) is str and key in derived and key not in rows, "external disposition key differs")
            _need(_same({name: row[name] for name in ("key", "path", "bytes")}, derived[key]),
                  "external disposition does not match original charge")
            _descriptor(row["descriptor_inventory"], Path(row["path"]), row["bytes"])
            serialized_bytes += len(_canonical(row["descriptor_inventory"]))
            _need(serialized_bytes <= MAX_DESCRIPTOR_BYTES, "external disposition aggregate byte bound exceeded")
            rows[key] = copy.deepcopy(row)
        _need(set(rows) == set(derived), "external dispositions do not cover exact original charge map")
        external_bytes = sum(row["bytes"] for row in rows.values())
        _need(external_bytes <= record["storage_bytes"], "external promises exceed original reservation")

        def verify():
            helper._verify_owner_roots()
            _need(base._digest(ledger) == ledger_sha
                  and base._digest(helper._read()) == ledger_sha and _same(record, original_record),
                  "retained ledger changed during recovery")
            _stopped(record, request, lease_ids)
            _need(_same(resources._root_identity(attempt), record["attempt_directory"]), "recovery attempt changed")
            local = resources._inventory([attempt], strict=True)
            _need(local["entry_count"] <= MAX_ARTIFACTS
                  and local["apparent_bytes"] + external_bytes <= record["storage_bytes"],
                  "retained attempt exceeds original reservation")
            _need(_same(base._durable_inventory(attempt), artifacts), "durable recovery inventory differs")
            current = _original_documents(attempt, artifacts, request_pin, source_pin, record, helper.roots)
            _need(_same(current, (request, receipt_pin, lease_ids, derived)), "original request evidence changed")
            for key in sorted(rows):
                row = rows[key]
                bounds = row["descriptor_inventory"]["bounds"]
                options = {name: bounds[name] for name in (
                    "max_entries", "max_bytes", "max_depth", "max_symlink_hops")}
                if row["descriptor_inventory"]["schema"] == "autoencoder-external-tree-descriptor-inventory@2":
                    options["opaque_symlinks"] = copy.deepcopy(row["descriptor_inventory"]["opaque_symlinks"])
                observed = observe_external_tree(row["path"], **options)
                _need(_same(observed, row["descriptor_inventory"]), "external descriptor inventory changed")

        verify()
        accounting = base._administrative_census(helper, ledger)
        verify()
        projected = copy.deepcopy(ledger)
        projected["reservations"][reservation_id]["status"] = "released"
        projected_sha = base._digest(projected)
        final = base._administrative_census(helper, projected)
        verify()
        _need(base._digest(projected) == projected_sha
              and accounting["outstanding_full_reservations_bytes"]
                  - final["outstanding_full_reservations_bytes"] == record["storage_bytes"]
              and accounting["additional_requested_bytes"] == 0 and final["additional_requested_bytes"] == 0
              and accounting["limit_bytes"] == resources.MAX_STORAGE_BYTES == final["limit_bytes"],
              "projected native closeout accounting differs")
        summaries = [{name: copy.deepcopy(row[name]) for name in ("key", "path", "bytes")}
                     | {"descriptor_inventory_sha256": row["descriptor_inventory"]["inventory_sha256"],
                        "root_identity": copy.deepcopy(row["descriptor_inventory"]["root_identity"]),
                        "bounds": copy.deepcopy(row["descriptor_inventory"]["bounds"]),
                        "entry_count": row["descriptor_inventory"]["entry_count"],
                        "apparent_bytes": row["descriptor_inventory"]["apparent_bytes"]}
                     for key, row in sorted(rows.items())]
        for summary in summaries:
            descriptor = rows[summary["key"]]["descriptor_inventory"]
            if descriptor["schema"] == "autoencoder-external-tree-descriptor-inventory@2":
                summary.update({key: copy.deepcopy(descriptor[key]) for key in _OPAQUE_KEYS})
        recovery = {"schema": SCHEMA, "provenance_profile": PROVENANCE_PROFILE,
            "reservation_id": reservation_id, "previous_record_sha256": expected_record_sha256,
            "original_owner_pid": record["owner_pid"], "reconciled_by_pid": os.getpid(),
            "original_request_pin": request_pin, "original_owner_source_pin": source_pin,
            "original_receipt_pin": receipt_pin, "original_native_lease_ids": lease_ids,
            "original_scheduler_state_path": record["scheduler_state_path"],
            "original_scheduler_policy_sha256": record["scheduler_policy_sha256"],
            "artifacts": artifacts, "external_dispositions": summaries,
            "other_reservations_sha256": other_sha, "full_claim_accounting": accounting,
            "final_accounting": final, "capacity_policy": "administrative_closeout",
            "fresh_global_inventory_count": 2, "descriptor_inventory_count_per_external_tree": 3,
            "final_accounting_is_prewrite_projection": True, "actual_postwrite_census_required": True,
            "cap_changed": False, "outputs_deleted": False, "automatic_expiry": False, "admitted": False,
            "new_reservation_created": False, "new_resource_lease_acquired": False,
            "external_payloads_opened": False, "external_historical_durability_asserted": False,
            "atomic_external_snapshot": False, "continuous_external_custody_proved": False,
            "source_profile_is_execution_attestation": False, "write_response_loss_requires_durable_state_inspection": True}
        if any("opaque_symlinks" in summary for summary in summaries):
            recovery.update(schema=OPAQUE_SCHEMA, external_symlink_resolution=_OPAQUE_PROFILE,
                opaque_link_referents_observed=False, opaque_link_target_custody_asserted=False,
                opaque_link_target_durability_asserted=False)
        selected = copy.deepcopy(record)
        attempt_bytes = sum(row["bytes"] for row in artifacts)
        selected.update(status="released", artifacts_durable_asserted=True, released_at=time.time(),
            final_accounting=final, final_attempt_bytes=attempt_bytes,
            final_external_charged_bytes=external_bytes, final_total_charged_bytes=attempt_bytes + external_bytes,
            attempt_exceeded_reservation=False, explicit_reconciliation=recovery)
        _need(_same(selected["external_charges"], original_record["external_charges"]), "original external map changed")
        projected["reservations"][reservation_id] = selected
        _need(base._digest({key: value for key, value in projected["reservations"].items() if key != reservation_id}) == other_sha,
              "another reservation changed")
        helper._verify_owner_roots()
        _need(base._digest(helper._read()) == ledger_sha, "retained ledger changed before atomic write")
        _stopped(record, request, lease_ids)
        helper._write(projected)
        return recovery


__all__ = ["reconcile_retained_native_request_reservation"]
