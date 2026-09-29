"""Cooperative, durable resource reservations for an owned daemon attempt.

Disk accounting counts apparent file bytes under the exact named roots,
including hard links once per pathname and symlink/special-file lstat sizes
without following or opening them. It is not a filesystem quota or a global
census. Outstanding reservations remain fully charged in addition to observed
bytes. Failed or abandoned entries never expire automatically. The owner must
stop/reap its isolated child group, make artifacts durable, then explicitly call
``release(artifacts_durable=True)``. Context exit alone retains the disk claim.

CPU/RAM/process admission uses the existing host resource scheduler's canonical
trainer mapping: HAMMER_LEAN, as in pipeline_stage_scheduler._default_lane and
legal_ir_hparam_scheduler.admit_work's default policy. This does not change the
host's lane reservations. Linux group RSS and disk growth are polling
observations, not kernel-enforced hard limits.
"""
from __future__ import annotations

from contextlib import contextmanager
import copy
import fcntl
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import time
import uuid

from .resource_scheduler import ResourceLane, get_global_resource_scheduler

# Campaign cap increased with operator authorization on 2026-09-29. Existing
# ledgers require an explicit, lock-held limit migration; _read never upgrades
# historical ledgers or releases their retained reservations implicitly.
MAX_STORAGE_BYTES = 85_000_000_000
MAX_LEDGER_BYTES = 8 * 1024 * 1024
MAX_RESERVATIONS = 4096
MAX_CHILDREN_PER_RESERVATION = 16
MAX_EXTERNAL_CHARGES = 128
MAX_INVENTORY_ENTRIES = 1_000_000
SCHEMA = "daemon-resource-reservations-v1"
SCHEDULER_LANE = ResourceLane.HAMMER_LEAN
SCHEDULER_WORKLOAD = "canonical_trainer"
_CHARGE_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,127}\Z")


class DaemonResourceError(RuntimeError):
    """Admission, accounting, or explicit release could not be verified."""


def _integer(value, name, *, minimum=1, maximum=None):
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise DaemonResourceError(f"invalid {name}")
    return value


def _external_charges(record):
    # Original v1 records predate named charges and have an empty inventory.
    charges = record.get("external_charges", {})
    if type(charges) is not dict or len(charges) > MAX_EXTERNAL_CHARGES:
        raise DaemonResourceError("invalid external charge inventory")
    for key, value in charges.items():
        if type(key) is not str or not _CHARGE_KEY.fullmatch(key):
            raise DaemonResourceError("invalid external charge key")
        _integer(value, "external charge bytes", minimum=0, maximum=MAX_STORAGE_BYTES)
    return charges


def _safe_path(value, *, directory=False, missing=False):
    path = Path(os.path.abspath(os.fspath(value)))
    return _checked_path(path, (*reversed(path.parents), path), directory=directory, missing=missing)


def _checked_path(path, components, *, directory=False, missing=False):
    """Check fresh metadata using only precomputed lexical path objects."""
    for part in components:
        try:
            info = part.lstat()
        except FileNotFoundError:
            if part == path and missing:
                return path
            raise DaemonResourceError(f"missing resource path: {part}") from None
        if stat.S_ISLNK(info.st_mode):
            raise DaemonResourceError(f"symlink resource path: {part}")
        if part != path and not stat.S_ISDIR(info.st_mode):
            raise DaemonResourceError(f"non-directory resource parent: {part}")
    if directory and not stat.S_ISDIR(info.st_mode):
        raise DaemonResourceError(f"resource root is not a directory: {path}")
    if not directory and not stat.S_ISREG(info.st_mode):
        raise DaemonResourceError(f"resource file is not regular: {path}")
    return path


def _root_identity(path):
    path = _safe_path(path, directory=True)
    info = path.stat()
    return {"path": str(path), "device": info.st_dev, "inode": info.st_ino}


def _inventory_descendant(root, directory, *, lexical_root=None):
    """Validate a discovered directory; only a missing descendant is absent.

    Shared roots can contain another process's temporary trees. Their deletion
    is ordinary census churn, but a missing/replaced named root, symlink or
    non-directory ancestor still invalidates the observation. This helper is
    deliberately separate from strict owned-attempt path validation.
    """
    named, ancestry = lexical_root or (Path(root["path"]), None)
    if ancestry is None:
        ancestry = (*reversed(named.parents), named)
    _checked_path(named, ancestry, directory=True)
    info = named.stat()
    if {"path": str(named), "device": info.st_dev, "inode": info.st_ino} != root:
        raise DaemonResourceError("storage root identity changed")
    named_parts, directory_parts = named.parts, Path(directory).parts
    if directory_parts[:len(named_parts)] != named_parts:
        raise DaemonResourceError("inventory descendant is outside its named root")
    components = directory_parts[len(named_parts):]
    current = named
    for component in components:
        current = current / component
        try:
            info = current.lstat()
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(info.st_mode):
            raise DaemonResourceError(f"symlink resource path: {current}")
        if not stat.S_ISDIR(info.st_mode):
            raise DaemonResourceError(f"non-directory resource parent: {current}")
    return current


def _inventory_entry_disappeared(root, path):
    """Confirm genuine absence without treating a dangling link as missing."""
    path = Path(path)
    if _inventory_descendant(root, path.parent) is None:
        return True
    try:
        path.lstat()
    except FileNotFoundError:
        return True
    return False


def _inventory(roots, *, strict=False):
    count, total, symlinks, special = 0, 0, 0, 0
    identities = [_root_identity(root) for root in roots]
    # Cache path spelling only. Every root and ancestor is freshly lstat'ed at
    # every previous guard boundary; no identity, size or absence is reused.
    lexical_roots = {
        root["path"]: (named, (*reversed(named.parents), named))
        for root in identities for named in (Path(root["path"]),)
    }
    pending = [(lexical_roots[root["path"]][0], root) for root in identities]
    while pending:
        directory, root = pending.pop()
        directory = (_safe_path(directory, directory=True) if strict
                     else _inventory_descendant(root, directory, lexical_root=lexical_roots[root["path"]]))
        if directory is None:
            continue
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    count += 1
                    if count > MAX_INVENTORY_ENTRIES:
                        raise DaemonResourceError("storage inventory entry bound exceeded")
                    try:
                        info = entry.stat(follow_symlinks=False)
                    except FileNotFoundError:
                        if strict or not _inventory_entry_disappeared(root, entry.path):
                            raise
                        continue
                    if stat.S_ISLNK(info.st_mode):
                        if strict:
                            raise DaemonResourceError(f"symlink in attempt inventory: {entry.path}")
                        symlinks += 1
                        total += info.st_size
                    elif stat.S_ISDIR(info.st_mode):
                        pending.append((Path(entry.path), root))
                    elif stat.S_ISREG(info.st_mode):
                        total += info.st_size
                    else:
                        if strict:
                            raise DaemonResourceError(f"nonregular attempt entry: {entry.path}")
                        special += 1
                        total += info.st_size
        except FileNotFoundError:
            if strict or _inventory_descendant(root, directory) is not None:
                raise
    if [_root_identity(Path(root["path"])) for root in identities] != identities:
        raise DaemonResourceError("storage root identity changed")
    return {"apparent_bytes": total, "entry_count": count,
            "symlink_count": symlinks, "special_file_count": special}


def _process(pid):
    """Linux PID identity and group; no command lines or environment retained."""
    try:
        raw = (Path("/proc") / str(pid) / "stat").read_text()
    except (FileNotFoundError, ProcessLookupError):
        return None
    fields = raw[raw.rfind(")") + 2:].split()
    if len(fields) < 22:
        raise DaemonResourceError("invalid /proc process identity")
    return {"pid": pid, "state": fields[0], "parent_pid": int(fields[1]),
            "group_pid": int(fields[2]), "birth": fields[19],
            "rss_bytes": int(fields[21]) * os.sysconf("SC_PAGE_SIZE")}


def _group_usage(child):
    if child is None:
        return {"available": True, "live_processes": 0, "rss_bytes": 0}
    if not Path("/proc/self/stat").is_file():
        raise DaemonResourceError("Linux /proc is required for child group accounting")
    leader = _process(child["pid"])
    if leader is not None and leader["birth"] != child["birth"]:
        raise DaemonResourceError("child PID was reused")
    live, rss = 0, 0
    entries = list(Path("/proc").iterdir())
    if len(entries) > 100_000:
        raise DaemonResourceError("process inventory bound exceeded")
    for entry in entries:
        if entry.name.isdecimal():
            process = _process(int(entry.name))
            if process is not None and process["group_pid"] == child["pid"] and process["state"] != "Z":
                live += 1
                rss += process["rss_bytes"]
    return {"available": True, "live_processes": live, "rss_bytes": rss}


def _json_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DaemonResourceError("duplicate disk ledger field")
        result[key] = value
    return result


class DaemonResourceReservation:
    """One explicit owner reservation; enter once, release only after durability.

    No scheduler/model/runtime injection is exposed in this production API.
    ``check_usage`` must attach the child PID immediately after Popen with
    ``start_new_session=True``; the child must be a direct child of this owner.
    The owner is responsible for stopping it on a limit error.
    """

    def __init__(self, ledger_path, *, roots, storage_bytes, memory_mb, cpu_slots=1, child_process_slots=1,
                 timeout_seconds=0, ledger_lock_timeout_seconds=None):
        self.storage_bytes = _integer(storage_bytes, "storage_bytes", maximum=MAX_STORAGE_BYTES)
        self.memory_mb = _integer(memory_mb, "memory_mb")
        self.cpu_slots = _integer(cpu_slots, "cpu_slots")
        self.child_process_slots = _integer(child_process_slots, "child_process_slots")
        if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or timeout_seconds < 0:
            raise DaemonResourceError("invalid timeout_seconds")
        self.timeout_seconds = float(timeout_seconds)
        if ledger_lock_timeout_seconds is not None and (
                type(ledger_lock_timeout_seconds) not in (int, float)
                or not math.isfinite(ledger_lock_timeout_seconds)
                or not 0 <= ledger_lock_timeout_seconds <= 60):
            raise DaemonResourceError("invalid ledger_lock_timeout_seconds")
        # Disk bookkeeping serializes short updates even when host capacity
        # admission is fail-fast. Existing callers retain their old deadline.
        self.ledger_lock_timeout_seconds = (
            self.timeout_seconds if ledger_lock_timeout_seconds is None
            else float(ledger_lock_timeout_seconds))
        values = list(roots)
        if not 1 <= len(values) <= 64:
            raise DaemonResourceError("one to 64 storage roots required")
        self.roots = tuple(_safe_path(value, directory=True) for value in values)
        for index, root in enumerate(self.roots):
            if any(root == other or root in other.parents or other in root.parents
                   for other in self.roots[:index]):
                raise DaemonResourceError("storage roots overlap")
        self.root_identities = [_root_identity(root) for root in self.roots]
        self.ledger_path = _safe_path(ledger_path, missing=True)
        self.lock_path = self.ledger_path.with_name(self.ledger_path.name + ".lock")
        _safe_path(self.lock_path, missing=True)
        self.reservation_id = uuid.uuid4().hex
        self._owner_pid = os.getpid()
        self._lease = None
        self._record = None
        self._attempt = None
        self._child = None
        self._child_history = []
        self._entered = False
        self._cleanup_error = None

    def _verify_owner_roots(self):
        if os.getpid() != self._owner_pid:
            raise DaemonResourceError("reservation cannot move to another owner process")
        if [_root_identity(root) for root in self.roots] != self.root_identities:
            raise DaemonResourceError("storage root identity changed")

    @contextmanager
    def _locked(self):
        self._verify_owner_roots()
        _safe_path(self.lock_path, missing=True)
        descriptor = os.open(self.lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise DaemonResourceError("lock must be an unaliased regular file")
            deadline = time.monotonic() + self.ledger_lock_timeout_seconds
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise DaemonResourceError("disk ledger lock unavailable") from None
                    time.sleep(min(0.05, max(0, deadline - time.monotonic())))
            current = self.lock_path.lstat()
            if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                raise DaemonResourceError("disk ledger lock identity changed")
            self._verify_owner_roots()
            yield
        finally:
            os.close(descriptor)

    def _read(self):
        _safe_path(self.ledger_path, missing=True)
        try:
            descriptor = os.open(self.ledger_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            if self._entered:
                raise DaemonResourceError("disk ledger disappeared") from None
            return {"schema": SCHEMA, "roots": self.root_identities,
                    "limit_bytes": MAX_STORAGE_BYTES, "reservations": {}}
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_LEDGER_BYTES:
                raise DaemonResourceError("invalid disk ledger file")
            raw = stream.read(MAX_LEDGER_BYTES + 1)
        try:
            value = json.loads(raw, object_pairs_hook=_json_pairs,
                               parse_constant=lambda _: (_ for _ in ()).throw(DaemonResourceError("nonfinite disk ledger value")))
        except (ValueError, UnicodeError) as exc:
            raise DaemonResourceError("invalid disk ledger JSON") from exc
        if type(value) is not dict or set(value) != {"schema", "roots", "limit_bytes", "reservations"}:
            raise DaemonResourceError("invalid disk ledger schema")
        if value["schema"] != SCHEMA or value["roots"] != self.root_identities or value["limit_bytes"] != MAX_STORAGE_BYTES:
            raise DaemonResourceError("disk ledger storage scope differs")
        records = value["reservations"]
        if type(records) is not dict or len(records) > MAX_RESERVATIONS:
            raise DaemonResourceError("invalid disk reservation inventory")
        for key, record in records.items():
            if type(record) is not dict or record.get("reservation_id") != key or record.get("status") not in {"reserved", "active", "retained", "released"}:
                raise DaemonResourceError("invalid disk reservation record")
            _integer(record.get("storage_bytes"), "ledger storage_bytes", maximum=MAX_STORAGE_BYTES)
            _integer(record.get("owner_pid"), "ledger owner_pid")
            if "child_process_slots" in record:
                _integer(record["child_process_slots"], "ledger child_process_slots")
            _external_charges(record)
        return value

    def _write(self, value):
        self._verify_owner_roots()
        _safe_path(self.ledger_path, missing=True)
        raw = (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
        if len(raw) > MAX_LEDGER_BYTES:
            raise DaemonResourceError("disk ledger byte bound exceeded")
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.ledger_path.parent, prefix=".daemon-reservation-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.ledger_path)
            temporary = None
            descriptor = os.open(self.ledger_path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _account(self, ledger, *, additional=0):
        inventory = _inventory(self.roots)
        observed = inventory["apparent_bytes"]
        outstanding = sum(row["storage_bytes"] for row in ledger["reservations"].values()
                          if row["status"] != "released")
        charged = observed + outstanding + additional
        free = min(shutil.disk_usage(root).free for root in self.roots)
        result = {"observed_apparent_bytes": observed, "outstanding_full_reservations_bytes": outstanding,
                  "additional_requested_bytes": additional, "charged_bytes": charged,
                  "limit_bytes": MAX_STORAGE_BYTES, "minimum_filesystem_free_bytes": free,
                  "scope": "named_roots_only_apparent_bytes", "inventory": inventory}
        if charged > MAX_STORAGE_BYTES or free < outstanding + additional:
            raise DaemonResourceError("storage reservation capacity exceeded")
        self._verify_owner_roots()
        return result

    def __enter__(self):
        if self._entered:
            raise DaemonResourceError("reservation can only be entered once")
        with self._locked():
            ledger = self._read()
            if len(ledger["reservations"]) >= MAX_RESERVATIONS:
                raise DaemonResourceError("disk reservation inventory full")
            observation = self._account(ledger, additional=self.storage_bytes)
            record = {"reservation_id": self.reservation_id, "status": "reserved",
                      "owner_pid": self._owner_pid, "storage_bytes": self.storage_bytes,
                      "memory_mb": self.memory_mb, "cpu_slots": self.cpu_slots,
                      "child_process_slots": self.child_process_slots,
                      "scheduler_lane": SCHEDULER_LANE.value, "workload": SCHEDULER_WORKLOAD,
                      "created_at": time.time(), "attempt_directory": None, "child": None,
                      "prior_children": [], "external_charges": {},
                      "last_usage": observation, "artifacts_durable_asserted": False}
            ledger["reservations"][self.reservation_id] = record
            self._write(ledger)
            self._record = copy.deepcopy(record)
            self._entered = True
        try:
            self._lease = get_global_resource_scheduler().acquire(
                SCHEDULER_LANE, cpu_slots=self.cpu_slots, memory_mb=self.memory_mb,
                child_process_slots=self.child_process_slots, requires_gpu=False, timeout=self.timeout_seconds,
                request_id="daemon:" + self.reservation_id)
            self._update(status="active")
        except BaseException:
            try:
                self._retain("scheduler_admission_failed")
                if self._lease is not None:
                    self._lease.release()
            except BaseException as cleanup:
                self._cleanup_error = type(cleanup).__name__
            raise
        return self

    def _update(self, **fields):
        with self._locked():
            ledger = self._read()
            record = ledger["reservations"].get(self.reservation_id)
            if record is None or record["owner_pid"] != self._owner_pid or record["storage_bytes"] != self.storage_bytes:
                raise DaemonResourceError("owned disk reservation differs")
            record.update(fields)
            self._write(ledger)
            self._record = copy.deepcopy(record)

    def _retain(self, reason):
        if self._record is not None and self._record["status"] != "released":
            self._update(status="retained", retention_reason=reason)

    def account_external_bytes(self, key: str, byte_count: int):
        """Durably charge CAS/journal bytes before the owner writes them.

        Identical keys/amounts are idempotent; changed amounts are forbidden.
        These are conservative per-attempt charges, not additional physical
        bytes in the global inventory. Failed admission does not add a charge.
        The caller must only charge outputs within this ledger's named roots.
        """
        if not self._entered or self._record["status"] == "released":
            raise DaemonResourceError("reservation is not outstanding")
        if type(key) is not str or not _CHARGE_KEY.fullmatch(key):
            raise DaemonResourceError("invalid external charge key")
        _integer(byte_count, "external charge bytes", minimum=0, maximum=MAX_STORAGE_BYTES)
        with self._locked():
            ledger = self._read()
            row = ledger["reservations"].get(self.reservation_id)
            if row is None or row["owner_pid"] != self._owner_pid or row["status"] == "released":
                raise DaemonResourceError("owned disk reservation differs")
            charges = dict(_external_charges(row))
            already_charged = key in charges
            if already_charged and charges[key] != byte_count:
                raise DaemonResourceError("external charge amount changed")
            if not already_charged and len(charges) >= MAX_EXTERNAL_CHARGES:
                raise DaemonResourceError("external charge inventory bound exceeded")
            charges[key] = byte_count
            attempt_bytes = 0
            if self._attempt is not None:
                attempt = Path(self._attempt["path"])
                if _root_identity(attempt) != self._attempt:
                    raise DaemonResourceError("attempt directory identity changed")
                attempt_bytes = _inventory([attempt], strict=True)["apparent_bytes"]
            external_bytes = sum(charges.values())
            if attempt_bytes + external_bytes > self.storage_bytes:
                raise DaemonResourceError("combined attempt and external storage byte limit exceeded")
            usage = self._account(ledger)
            usage.update(attempt_bytes=attempt_bytes, external_charged_bytes=external_bytes,
                         total_attempt_charged_bytes=attempt_bytes + external_bytes,
                         attempt_limit_bytes=self.storage_bytes, checked_at=time.time())
            row.update(external_charges=charges, last_charge_usage=usage)
            self._write(ledger)
            self._record = copy.deepcopy(row)
        return {"key": key, "bytes": byte_count, "already_charged": already_charged,
                "usage": copy.deepcopy(usage)}

    def check_usage(self, attempt_directory: Path, child_pid: int | None = None):
        if not self._entered or self._record["status"] == "released":
            raise DaemonResourceError("reservation is not outstanding")
        attempt = _safe_path(attempt_directory, directory=True)
        if not any(attempt == root or root in attempt.parents for root in self.roots):
            raise DaemonResourceError("attempt directory is outside named storage roots")
        identity = _root_identity(attempt)
        if self._attempt is not None and self._attempt != identity:
            raise DaemonResourceError("attempt directory identity changed")
        self._attempt = identity
        if child_pid is not None:
            _integer(child_pid, "child_pid")
            if self._child is None or child_pid != self._child["pid"]:
                if self._child is not None:
                    if _group_usage(self._child)["live_processes"]:
                        raise DaemonResourceError("previous child process group is still alive")
                    if len(self._child_history) >= MAX_CHILDREN_PER_RESERVATION - 1:
                        raise DaemonResourceError("reservation child history bound exceeded")
                child = _process(child_pid)
                if child is None or child["parent_pid"] != self._owner_pid or child["group_pid"] != child_pid:
                    raise DaemonResourceError("child must be an owned isolated process-group leader")
                if self._child is not None:
                    self._child_history.append({**self._child, "group_observed_dead_at": time.time()})
                self._child = {key: child[key] for key in ("pid", "birth")}
        self._update(attempt_directory=self._attempt, child=self._child,
                     prior_children=copy.deepcopy(self._child_history))
        group = _group_usage(self._child)
        attempt_bytes = _inventory([attempt], strict=True)["apparent_bytes"]
        with self._locked():
            ledger = self._read()
            usage = self._account(ledger)
            row = ledger["reservations"][self.reservation_id]
            external_bytes = sum(_external_charges(row).values())
            usage.update(attempt_bytes=attempt_bytes, attempt_limit_bytes=self.storage_bytes,
                         external_charged_bytes=external_bytes,
                         total_attempt_charged_bytes=attempt_bytes + external_bytes,
                         group_rss=group, memory_limit_bytes=self.memory_mb * 1024 * 1024,
                         reserved_child_process_slots=self.child_process_slots,
                         process_slot_estimate_exceeded=group["live_processes"] > self.child_process_slots,
                         checked_at=time.time())
            row["last_usage"] = usage
            self._write(ledger)
            self._record = copy.deepcopy(row)
        if attempt_bytes + external_bytes > self.storage_bytes:
            raise DaemonResourceError("attempt storage byte limit exceeded")
        if group["rss_bytes"] > self.memory_mb * 1024 * 1024:
            raise DaemonResourceError("child group RSS limit exceeded")
        return copy.deepcopy(usage)

    def finalize(self, attempt_directory: Path, *, artifacts_durable=False):
        """Check and release a bound, stopped attempt using one fresh census.

        This is the strict success path equivalent to a final ``check_usage``
        followed by ``release``. The full claim remains charged while limits
        are checked. Only the claim arithmetic is adjusted after success; no
        filesystem observation is cached across calls or ledger-lock scopes.
        Legacy ``release`` remains available for explicitly audited recovery.
        """
        if not self._entered:
            raise DaemonResourceError("reservation was not entered")
        if self._record["status"] == "released":
            return self.to_dict()
        if artifacts_durable is not True:
            raise DaemonResourceError("explicit artifact durability assertion required")
        attempt = _safe_path(attempt_directory, directory=True)
        if not any(attempt == root or root in attempt.parents for root in self.roots):
            raise DaemonResourceError("attempt directory is outside named storage roots")
        if self._attempt is None:
            raise DaemonResourceError("finalization requires a previously bound attempt")
        if _root_identity(attempt) != self._attempt:
            raise DaemonResourceError("attempt directory identity changed")
        started = time.monotonic()
        with self._locked():
            lock_acquired = time.monotonic()
            ledger = self._read()
            row = ledger["reservations"].get(self.reservation_id)
            if (row is None or row["owner_pid"] != self._owner_pid
                    or row["storage_bytes"] != self.storage_bytes
                    or row["status"] == "released"):
                raise DaemonResourceError("owned disk reservation differs")
            if row.get("attempt_directory") != self._attempt or row.get("child") != self._child:
                raise DaemonResourceError("bound attempt or child identity changed")
            group_started = time.monotonic()
            group = _group_usage(self._child)
            group_seconds = time.monotonic() - group_started
            attempt_started = time.monotonic()
            attempt_bytes = _inventory([attempt], strict=True)["apparent_bytes"]
            attempt_seconds = time.monotonic() - attempt_started
            account_started = time.monotonic()
            accounting = self._account(ledger)
            account_seconds = time.monotonic() - account_started
            if _root_identity(attempt) != self._attempt:
                raise DaemonResourceError("attempt directory identity changed")
            external_bytes = sum(_external_charges(row).values())
            usage = copy.deepcopy(accounting)
            usage.update(attempt_bytes=attempt_bytes, attempt_limit_bytes=self.storage_bytes,
                         external_charged_bytes=external_bytes,
                         total_attempt_charged_bytes=attempt_bytes + external_bytes,
                         group_rss=group, memory_limit_bytes=self.memory_mb * 1024 * 1024,
                         reserved_child_process_slots=self.child_process_slots,
                         process_slot_estimate_exceeded=group["live_processes"] > self.child_process_slots,
                         checked_at=time.time())
            row["last_usage"] = usage
            failure = None
            if attempt_bytes + external_bytes > self.storage_bytes:
                failure = "attempt storage byte limit exceeded"
            elif group["rss_bytes"] > self.memory_mb * 1024 * 1024:
                failure = "child group RSS limit exceeded"
            else:
                group_started = time.monotonic()
                final_group = _group_usage(self._child)
                group_seconds += time.monotonic() - group_started
                if final_group["live_processes"]:
                    failure = "child process group is still alive"
            if failure is not None:
                # Preserve the observed failed usage before context cleanup
                # retains this claim. No release event is written on failure.
                self._write(ledger)
                self._record = copy.deepcopy(row)
                raise DaemonResourceError(failure)
            final_accounting = copy.deepcopy(accounting)
            final_accounting["outstanding_full_reservations_bytes"] -= self.storage_bytes
            final_accounting["charged_bytes"] -= self.storage_bytes
            row.update(status="released", artifacts_durable_asserted=True, released_at=time.time(),
                       final_accounting=final_accounting, final_attempt_bytes=attempt_bytes,
                       final_external_charged_bytes=external_bytes,
                       final_total_charged_bytes=attempt_bytes + external_bytes,
                       attempt_exceeded_reservation=False,
                       finalization_profile={
                           "schema_version": "daemon-resource-finalization-profile/v1",
                           "ledger_lock_wait_seconds": lock_acquired - started,
                           "strict_attempt_inventory_seconds": attempt_seconds,
                           "global_accounting_seconds": account_seconds,
                           "process_check_seconds": group_seconds,
                           "global_inventory_count": 1, "strict_attempt_inventory_count": 1,
                           "scope": "one_fresh_locked_census_with_full_claim_checked_before_release",
                       })
            self._write(ledger)
            self._record = copy.deepcopy(row)
        if self._lease is not None:
            self._lease.release()
        return self.to_dict()

    def release(self, *, artifacts_durable=False):
        if not self._entered:
            raise DaemonResourceError("reservation was not entered")
        if self._record["status"] == "released":
            return self.to_dict()
        if artifacts_durable is not True:
            raise DaemonResourceError("explicit artifact durability assertion required")
        if _group_usage(self._child)["live_processes"]:
            raise DaemonResourceError("child process group is still alive")
        if self._attempt is not None and _root_identity(Path(self._attempt["path"])) != self._attempt:
            raise DaemonResourceError("attempt directory identity changed")
        with self._locked():
            ledger = self._read()
            # Completed outputs replace this reservation with observed bytes.
            row = ledger["reservations"][self.reservation_id]
            row.update(status="released", artifacts_durable_asserted=True, released_at=time.time())
            row["final_accounting"] = self._account(ledger)
            row["final_attempt_bytes"] = (_inventory([Path(self._attempt["path"])], strict=True)["apparent_bytes"]
                                          if self._attempt is not None else None)
            row["final_external_charged_bytes"] = sum(_external_charges(row).values())
            row["final_total_charged_bytes"] = (row["final_attempt_bytes"] or 0) + row["final_external_charged_bytes"]
            row["attempt_exceeded_reservation"] = row["final_total_charged_bytes"] > self.storage_bytes
            self._write(ledger)
            self._record = copy.deepcopy(row)
        if self._lease is not None:
            self._lease.release()
        return self.to_dict()

    close = release

    def to_dict(self):
        return {"schema": SCHEMA, "reservation_id": self.reservation_id,
                "scheduler_lane": SCHEDULER_LANE.value, "workload": SCHEDULER_WORKLOAD,
                "status": self._record["status"] if self._record is not None else "not_entered",
                "ledger_path": str(self.ledger_path), "roots": copy.deepcopy(self.root_identities),
                "storage_limit_bytes": MAX_STORAGE_BYTES, "record": copy.deepcopy(self._record),
                "resource_lease": self._lease.to_dict() if self._lease is not None else None,
                "cleanup_error": self._cleanup_error,
                "enforcement": "cooperative_admission_and_polled_usage_not_kernel_quota"}

    def __exit__(self, exc_type, exc, traceback):
        if self._record is not None and self._record["status"] != "released":
            try:
                try:
                    self._retain("context_failed" if exc_type else "explicit_release_required")
                finally:
                    if self._lease is not None and not _group_usage(self._child)["live_processes"]:
                        self._lease.release()
            except BaseException as cleanup:
                self._cleanup_error = type(cleanup).__name__
                if exc_type is None:
                    raise
        return False


__all__ = ["DaemonResourceReservation", "DaemonResourceError", "MAX_STORAGE_BYTES"]
