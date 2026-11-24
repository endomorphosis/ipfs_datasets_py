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
import hashlib
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
from . import resource_scheduler as native_deadlines

# Legacy default campaign capacity. Callers may configure a finite byte limit;
# existing ledgers change only through explicit lock-held migration. _read never
# upgrades historical ledgers or releases retained reservations implicitly.
MAX_STORAGE_BYTES = 250_000_000_000
# Bound the retained JSON metadata independently of storage admission.
# Reading/writing a larger ledger never changes its schema or storage cap.
MAX_LEDGER_BYTES = 16 * 1024 * 1024
MAX_RESERVATIONS = 4096
MAX_CHILDREN_PER_RESERVATION = 16
MAX_EXTERNAL_CHARGES = 128
# Explicit ledger waits may cover several full named-root censuses. This
# ceiling does not extend the original resource-operation deadline.
MAX_LEDGER_LOCK_TIMEOUT_SECONDS = 600
# The same exact-root census observed 1,359,805 entries on 2026-10-02. Increase
# only the finite scan bound; path/identity checks and accounting stay unchanged.
MAX_INVENTORY_ENTRIES = 4_000_000
SCHEMA = "daemon-resource-reservations-v1"
SCHEDULER_LANE = ResourceLane.HAMMER_LEAN
SCHEDULER_WORKLOAD = "canonical_trainer"
_CHARGE_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,127}\Z")


class DaemonResourceError(RuntimeError):
    """Admission, accounting, or explicit release could not be verified."""

    @property
    def capacity_observation(self):
        """Return a detached aggregate snapshot, when capacity caused refusal.

        The captured observation has no inventory or reservation records. Each
        access returns a copy so a diagnostic consumer cannot change it.
        """
        return copy.deepcopy(getattr(self, "_capacity_observation", None))

    @property
    def lock_observation(self):
        """Detached diagnostic from the genuine pre-yield lock timeout only."""
        return copy.deepcopy(getattr(self, "_lock_observation", None))

    @property
    def ledger_write_bound_observation(self):
        """Detached size observation from a refusal before ledger writing."""
        return copy.deepcopy(getattr(self, "_ledger_write_bound_observation", None))


class OwnedInventoryDisappearance(DaemonResourceError):
    """A strict live sample lost a confirmed owned descendant, not its root.

    This is a partial observation, never a successful census or durability
    receipt. Consumers must start any permitted replacement census at the root.
    """

    def __init__(self, *, frozen_root, vanished_path, partial_inventory):
        super().__init__(f"owned inventory descendant disappeared: {vanished_path}")
        self._frozen_root = copy.deepcopy(frozen_root)
        self._vanished_path = str(vanished_path)
        self._partial_inventory = copy.deepcopy(partial_inventory)

    @property
    def frozen_root(self):
        return copy.deepcopy(self._frozen_root)

    @property
    def vanished_path(self):
        return self._vanished_path

    @property
    def partial_inventory(self):
        return copy.deepcopy(self._partial_inventory)

def _integer(value, name, *, minimum=1, maximum=None):
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise DaemonResourceError(f"invalid {name}")
    return value


def _external_charges(record, *, limit_bytes=None):
    # Original v1 records predate named charges and have an empty inventory.
    limit_bytes = _integer(MAX_STORAGE_BYTES if limit_bytes is None else limit_bytes,
                           "storage_limit_bytes", maximum=(1 << 63) - 1)
    charges = record.get("external_charges", {})
    if type(charges) is not dict or len(charges) > MAX_EXTERNAL_CHARGES:
        raise DaemonResourceError("invalid external charge inventory")
    for key, value in charges.items():
        if type(key) is not str or not _CHARGE_KEY.fullmatch(key):
            raise DaemonResourceError("invalid external charge key")
        _integer(value, "external charge bytes", minimum=0, maximum=limit_bytes)
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


def _owned_strict_inventory(roots):
    """Report only confirmed descendant loss; all other strict failures stand."""
    native_deadlines._check_resource_operation_deadline()
    identities = [_root_identity(root) for root in roots]
    native_deadlines._check_resource_operation_deadline()
    counts = {"apparent_bytes": 0, "entry_count": 0,
              "symlink_count": 0, "special_file_count": 0}
    # Freeze ancestor identities before walking. A replacement regular directory
    # is not disappearance and cannot acquire retry authority.
    frozen_directories = {}
    queued_owned_directories = {}
    for root in identities:
        native_deadlines._check_resource_operation_deadline()
        named = Path(root["path"])
        for directory in (*reversed(named.parents), named):
            native_deadlines._check_resource_operation_deadline()
            info = directory.lstat()
            native_deadlines._check_resource_operation_deadline()
            if not stat.S_ISDIR(info.st_mode):
                raise DaemonResourceError(f"non-directory resource parent: {directory}")
            identity = (info.st_dev, info.st_ino)
            if directory in frozen_directories and frozen_directories[directory] != identity:
                raise DaemonResourceError("storage ancestor identity changed")
            frozen_directories[directory] = identity
        if named.lstat().st_uid != os.geteuid():
            raise DaemonResourceError("owned live census root is not owned")

    def check_roots():
        for root in identities:
            native_deadlines._check_resource_operation_deadline()
            named = Path(root["path"])
            for directory in (*reversed(named.parents), named):
                native_deadlines._check_resource_operation_deadline()
                info = directory.lstat()
                native_deadlines._check_resource_operation_deadline()
                if (not stat.S_ISDIR(info.st_mode)
                        or (info.st_dev, info.st_ino) != frozen_directories[directory]):
                    raise DaemonResourceError("storage root or ancestor identity changed")
            if _root_identity(named) != root:
                raise DaemonResourceError("storage root identity changed")
            if named.lstat().st_uid != os.geteuid():
                raise DaemonResourceError("owned live census root is not owned")

    def check_path(root, path, *, directory):
        named = Path(root["path"])
        path = Path(path)
        if path != named and named not in path.parents:
            raise DaemonResourceError("inventory descendant is outside its named root")
        check_roots()
        for part in (*reversed(path.parents), path):
            native_deadlines._check_resource_operation_deadline()
            try:
                info = part.lstat()
                native_deadlines._check_resource_operation_deadline()
            except FileNotFoundError:
                # The root and every existing ancestor were checked nofollow.
                # Recheck all named roots immediately before typing the loss.
                if part == named or named not in part.parents:
                    raise
                # A directory must have been successfully observed as owned
                # before it was queued. Enumeration without a successful stat,
                # and disappearance of an ancestor of the requested leaf, do
                # not establish ownership or acquire retry authority.
                prior = queued_owned_directories.get(path)
                if part != path or prior is None:
                    raise
                if (prior[2] != os.geteuid() or prior[3] != stat.S_IFDIR
                        or frozen_directories.get(path) != prior[:2]):
                    raise DaemonResourceError("queued owned directory binding changed")
                # A stable named root alone cannot distinguish a removed leaf
                # from replacement of an internal ancestor after its first
                # check. Reconfirm every surviving ancestor nofollow against
                # the original traversal identities, then confirm absence a
                # second time. Any additional disappearance here remains an
                # ordinary failure; it does not authorize an unbounded search
                # for a retryable path.
                check_roots()
                for ancestor in reversed(part.parents):
                    native_deadlines._check_resource_operation_deadline()
                    before_loss = ancestor.lstat()
                    native_deadlines._check_resource_operation_deadline()
                    if (not stat.S_ISDIR(before_loss.st_mode)
                            or (before_loss.st_dev, before_loss.st_ino)
                            != frozen_directories.get(ancestor)):
                        raise DaemonResourceError(
                            "storage descendant or ancestor identity changed before loss confirmation")
                    if (ancestor == named or named in ancestor.parents) and (
                            before_loss.st_uid != os.geteuid()):
                        raise DaemonResourceError("owned live census ancestor is not owned")
                try:
                    part.lstat()
                except FileNotFoundError:
                    check_roots()
                    raise OwnedInventoryDisappearance(
                        frozen_root=root, vanished_path=str(part),
                        partial_inventory=counts) from None
                raise DaemonResourceError("inventory descendant reappeared before loss confirmation")
            if stat.S_ISLNK(info.st_mode):
                raise DaemonResourceError(f"symlink resource path: {part}")
            expected_directory = part != path or directory
            if expected_directory and not stat.S_ISDIR(info.st_mode):
                raise DaemonResourceError(f"non-directory resource parent: {part}")
            if part in frozen_directories:
                if (info.st_dev, info.st_ino) != frozen_directories[part]:
                    raise DaemonResourceError("storage descendant or ancestor identity changed")
            if (part == named or named in part.parents) and info.st_uid != os.geteuid():
                raise DaemonResourceError("owned live census descendant is not owned")
            if part == path and not directory and not (
                    stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                raise DaemonResourceError(f"nonregular attempt entry: {part}")
        native_deadlines._check_resource_operation_deadline()
        return path

    check_roots()
    pending = [(Path(root["path"]), root) for root in identities]
    while pending:
        native_deadlines._check_resource_operation_deadline()
        directory, root = pending.pop()
        check_path(root, directory, directory=True)
        try:
            entries = os.scandir(directory)
        except FileNotFoundError:
            check_path(root, directory, directory=True)
            raise
        with entries:
            native_deadlines._check_resource_operation_deadline()
            while True:
                native_deadlines._check_resource_operation_deadline()
                try:
                    entry = next(entries)
                    native_deadlines._check_resource_operation_deadline()
                except StopIteration:
                    break
                except FileNotFoundError:
                    check_path(root, directory, directory=True)
                    raise
                counts["entry_count"] += 1
                if counts["entry_count"] > MAX_INVENTORY_ENTRIES:
                    raise DaemonResourceError("storage inventory entry bound exceeded")
                try:
                    info = entry.stat(follow_symlinks=False)
                    native_deadlines._check_resource_operation_deadline()
                except FileNotFoundError:
                    check_path(root, Path(entry.path), directory=False)
                    raise
                if info.st_uid != os.geteuid():
                    raise DaemonResourceError("owned live census descendant is not owned")
                if stat.S_ISLNK(info.st_mode):
                    raise DaemonResourceError(f"symlink in attempt inventory: {entry.path}")
                if stat.S_ISDIR(info.st_mode):
                    path = Path(entry.path)
                    identity = (info.st_dev, info.st_ino)
                    if path in frozen_directories and frozen_directories[path] != identity:
                        raise DaemonResourceError("storage descendant identity changed")
                    frozen_directories[path] = identity
                    queued_owned_directories[path] = (
                        info.st_dev, info.st_ino, info.st_uid, stat.S_IFMT(info.st_mode))
                    pending.append((path, root))
                elif stat.S_ISREG(info.st_mode):
                    counts["apparent_bytes"] += info.st_size
                else:
                    raise DaemonResourceError(f"nonregular attempt entry: {entry.path}")
    check_roots()
    native_deadlines._check_resource_operation_deadline()
    return counts

def _inventory(roots, *, strict=False, report_owned_disappearance=False):
    native_deadlines._check_resource_operation_deadline()
    if type(report_owned_disappearance) is not bool:
        raise DaemonResourceError("report_owned_disappearance must be a boolean")
    if report_owned_disappearance:
        if strict is not True:
            raise DaemonResourceError("owned disappearance reporting requires strict=True")
        native_deadlines._check_resource_operation_deadline()
        return _owned_strict_inventory(roots)
    count, total, symlinks, special = 0, 0, 0, 0
    identities = [_root_identity(root) for root in roots]
    native_deadlines._check_resource_operation_deadline()
    # Cache path spelling only. Every root and ancestor is freshly lstat'ed at
    # every previous guard boundary; no identity, size or absence is reused.
    lexical_roots = {
        root["path"]: (named, (*reversed(named.parents), named))
        for root in identities for named in (Path(root["path"]),)
    }
    pending = [(lexical_roots[root["path"]][0], root) for root in identities]
    while pending:
        native_deadlines._check_resource_operation_deadline()
        directory, root = pending.pop()
        directory = (_safe_path(directory, directory=True) if strict
                     else _inventory_descendant(root, directory, lexical_root=lexical_roots[root["path"]]))
        native_deadlines._check_resource_operation_deadline()
        if directory is None:
            continue
        try:
            with os.scandir(directory) as entries:
                native_deadlines._check_resource_operation_deadline()
                for entry in entries:
                    native_deadlines._check_resource_operation_deadline()
                    count += 1
                    if count > MAX_INVENTORY_ENTRIES:
                        raise DaemonResourceError("storage inventory entry bound exceeded")
                    try:
                        info = entry.stat(follow_symlinks=False)
                        native_deadlines._check_resource_operation_deadline()
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
    native_deadlines._check_resource_operation_deadline()
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


def _bounded_cleanup_failure_observation(stage, error, lock_path, *, origin_owner):
    """Report typed cleanup metadata; never stringify an exception or its args.

    Diagnostics are DATA, not evidence of resource closure. Only the original owner-bound
    exact lock-timeout observation has a recognized reason; other causes remain
    unclassified, including malformed/foreign observations.
    """
    stages = {'failure_retention', 'native_release', 'tracked_process_stop', 'tracker_close'}
    kind = ('resource_deadline' if type(error) is native_deadlines.ResourceAdmissionDeadlineError else
            'daemon_resource_error' if isinstance(error, DaemonResourceError) else
            'os_error' if isinstance(error, OSError) else 'unknown_error')
    result = dict(schema='owned-resource-cleanup-failure/v1',
        stage=stage if type(stage) is str and stage in stages else 'unknown_cleanup_stage',
        error_kind=kind, reason_code='unclassified', lock_observation_status='absent',
        lock_observation=None)
    # The typed owner exception has an ordinary instance dictionary; no custom
    # exception attributes, messages, traceback or arbitrary nested data escape.
    if type(error) is not DaemonResourceError:
        return result
    offered = vars(error).get('_lock_observation')
    if offered is None:
        return result
    result['lock_observation_status'] = 'rejected'
    try:
        fields = {'schema', 'stage', 'lock_path', 'opened_lock_identity',
            'configured_lock_timeout_seconds', 'started_monotonic',
            'deadline_monotonic', 'observed_monotonic', 'lock_acquired',
            'holder_identity_established'}
        if (type(offered) is not dict or any(type(key) is not str for key in offered)
                or set(offered) != fields):
            return result
        if (type(offered['schema']) is not str
                or offered['schema'] != 'daemon-resource-ledger-lock-timeout/v1'
                or type(offered['stage']) is not str
                or offered['stage'] != 'exclusive_acquire_before_yield'
                or type(offered['lock_path']) is not str or offered['lock_path'] != str(lock_path)
                or len(offered['lock_path'].encode()) > 4096
                or offered['lock_acquired'] is not False
                or offered['holder_identity_established'] is not False):
            return result
        identity = offered['opened_lock_identity']
        keys = {'st_dev','st_ino','st_mode','st_uid','st_gid','st_nlink','st_size','st_mtime_ns','st_ctime_ns'}
        if (type(identity) is not dict or any(type(key) is not str for key in identity)
                or set(identity) != keys
                or not all(type(v) is int and 0 <= v < 2**63 for v in identity.values())
                or identity['st_dev'] <= 0 or identity['st_ino'] <= 0
                or not stat.S_ISREG(identity['st_mode']) or identity['st_nlink'] != 1
                or identity['st_uid'] != os.geteuid()):
            return result
        names = ('configured_lock_timeout_seconds','started_monotonic','deadline_monotonic','observed_monotonic')
        if not all(type(offered[k]) in (int,float) and math.isfinite(offered[k])
                   and 0 <= offered[k] < 2**63 for k in names):
            return result
        timeout, started, deadline, observed = (offered[k] for k in names)
        if not (timeout <= MAX_LEDGER_LOCK_TIMEOUT_SECONDS and started <= deadline <= observed
                and deadline - started <= timeout + 1e-6):
            return result
        # Origin and contents are bound at the exact original _locked raise.
        # This private identity never appears in a receipt and grants no authority.
        binding = vars(error).get('_lock_observation_binding')
        if (origin_owner is None or type(binding) is not tuple or len(binding) != 2
                or binding[0] is not origin_owner or type(binding[1]) is not bytes
                or json.dumps(offered, sort_keys=True, allow_nan=False).encode() != binding[1]):
            return result
        checked = {key: offered[key] for key in fields - {'opened_lock_identity'}}
        checked['opened_lock_identity'] = {key: identity[key] for key in keys}
        result.update(reason_code='ledger_lock_unavailable',
            lock_observation_status='accepted', lock_observation=checked)
    except BaseException:
        # Diagnostic formatting must not replace the original exception.
        pass
    return result


class DaemonResourceReservation:
    """One explicit owner reservation; enter once, release only after durability.

    No scheduler/model/runtime injection is exposed in this production API.
    ``check_usage`` must attach the child PID immediately after Popen with
    ``start_new_session=True``; the child must be a direct child of this owner.
    The owner is responsible for stopping it on a limit error.
    """

    def __init__(self, ledger_path, *, roots, storage_bytes, memory_mb, cpu_slots=1, child_process_slots=1,
                 timeout_seconds=0, ledger_lock_timeout_seconds=None,
                 scheduler_state_path=None, expected_scheduler_policy_sha256=None,
                 require_existing_ledger=False, storage_limit_bytes=None):
        self.storage_limit_bytes = _integer(
            MAX_STORAGE_BYTES if storage_limit_bytes is None else storage_limit_bytes,
            "storage_limit_bytes", maximum=(1 << 63) - 1)
        self.storage_bytes = _integer(storage_bytes, "storage_bytes", maximum=self.storage_limit_bytes)
        self.memory_mb = _integer(memory_mb, "memory_mb")
        self.cpu_slots = _integer(cpu_slots, "cpu_slots")
        self.child_process_slots = _integer(child_process_slots, "child_process_slots")
        if (scheduler_state_path is None) != (expected_scheduler_policy_sha256 is None):
            raise DaemonResourceError("strict scheduler state and policy must be supplied together")
        if scheduler_state_path is not None and (
                not isinstance(scheduler_state_path, (str, Path)) or not str(scheduler_state_path)
                or type(expected_scheduler_policy_sha256) is not str
                or not re.fullmatch(r"[0-9a-f]{64}", expected_scheduler_policy_sha256)):
            raise DaemonResourceError("invalid strict existing scheduler identity")
        if type(require_existing_ledger) is not bool:
            raise DaemonResourceError("require_existing_ledger must be a boolean")
        self._scheduler_state_path = scheduler_state_path
        self._expected_scheduler_policy_sha256 = expected_scheduler_policy_sha256
        self._require_existing_ledger = require_existing_ledger
        if type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or timeout_seconds < 0:
            raise DaemonResourceError("invalid timeout_seconds")
        self.timeout_seconds = float(timeout_seconds)
        if ledger_lock_timeout_seconds is not None and (
                type(ledger_lock_timeout_seconds) not in (int, float)
                or not math.isfinite(ledger_lock_timeout_seconds)
                or not 0 <= ledger_lock_timeout_seconds <= MAX_LEDGER_LOCK_TIMEOUT_SECONDS):
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
        self._cleanup_failure_observations = []
        self._cleanup_failure_observation_overflow = False

    @classmethod
    def migrate_storage_limit(cls, ledger_path, *, roots, expected_limit_bytes,
                              storage_limit_bytes, ledger_lock_timeout_seconds=30):
        """Explicitly raise one existing ledger capacity without releasing claims.

        No reservation or scheduler lease is acquired. Every nonreleased owner
        must be dead under the existing PID/group rules: old live implementations
        otherwise still require their previous exact cap and cannot reopen it.
        Historical records, roots, charges and child histories are never edited.
        Callers reopening the migrated ledger must explicitly select its new cap.
        """
        previous = _integer(expected_limit_bytes, "expected_limit_bytes", maximum=(1 << 63) - 1)
        target = _integer(storage_limit_bytes, "storage_limit_bytes", maximum=(1 << 63) - 1)
        if target <= previous:
            raise DaemonResourceError("storage limit migration must increase capacity")
        control = cls(ledger_path, roots=roots, storage_bytes=1, memory_mb=1,
                      storage_limit_bytes=previous, require_existing_ledger=True,
                      ledger_lock_timeout_seconds=ledger_lock_timeout_seconds)
        with control._locked():
            ledger = control._read()
            original_records = copy.deepcopy(ledger["reservations"])

            def refuse_live_owners():
                for record in original_records.values():
                    native_deadlines._check_resource_operation_deadline()
                    if record["status"] == "released":
                        continue
                    owner = _process(record["owner_pid"])
                    if owner is not None and owner["state"] != "Z":
                        raise DaemonResourceError(
                            "live disk ledger owner prevents storage limit migration: "
                            + str(record["reservation_id"]))
                    if _group_usage(record.get("child"))["live_processes"]:
                        raise DaemonResourceError(
                            "live disk ledger child prevents storage limit migration: "
                            + str(record["reservation_id"]))

            refuse_live_owners()
            migrated = copy.deepcopy(ledger)
            migrated["limit_bytes"] = target
            control.storage_limit_bytes = target
            # Existing over-cap accounting can be repaired by a larger capacity;
            # all full claims still count, and filesystem free space still binds.
            accounting = control._account(migrated)
            refuse_live_owners()
            if migrated["reservations"] != original_records:
                raise DaemonResourceError("storage limit migration changed reservation records")
            control._write(migrated)
            if control._read() != migrated:
                raise DaemonResourceError("storage limit migration readback differs")
            records_raw = json.dumps(original_records, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()
            return {"schema": "daemon-resource-storage-limit-migration/v1",
                    "ledger_path": str(control.ledger_path),
                    "roots": copy.deepcopy(control.root_identities),
                    "previous_limit_bytes": previous, "storage_limit_bytes": target,
                    "reservation_count": len(original_records),
                    "reservation_records_sha256": hashlib.sha256(records_raw).hexdigest(),
                    "records_roots_history_and_charges_preserved": True,
                    "live_nonreleased_owners_and_current_children_refused": True,
                    "accounting": copy.deepcopy(accounting),
                    "reservation_or_scheduler_lease_acquired": False}


    @classmethod
    def lower_storage_limit(cls, ledger_path, *, roots, expected_limit_bytes,
                            storage_limit_bytes, ledger_lock_timeout_seconds=30):
        """Explicitly lower one stopped ledger's cap without discarding charges.

        This does not reserve resources, change defaults, or relax the existing
        increase-only migration. Historical records must remain readable at the
        new cap, and full claims plus any retained external overage still count.
        """
        previous = _integer(expected_limit_bytes, "expected_limit_bytes", maximum=(1 << 63) - 1)
        target = _integer(storage_limit_bytes, "storage_limit_bytes", maximum=(1 << 63) - 1)
        if target >= previous:
            raise DaemonResourceError("storage limit lowering must decrease capacity")
        control = cls(ledger_path, roots=roots, storage_bytes=1, memory_mb=1,
                      storage_limit_bytes=previous, require_existing_ledger=True,
                      ledger_lock_timeout_seconds=ledger_lock_timeout_seconds)
        with control._locked():
            ledger = control._read()
            original_records = copy.deepcopy(ledger["reservations"])

            def refuse_live_owners():
                for record in original_records.values():
                    native_deadlines._check_resource_operation_deadline()
                    if record["status"] == "released":
                        continue
                    owner = _process(record["owner_pid"])
                    if owner is not None and owner["state"] != "Z":
                        raise DaemonResourceError(
                            "live disk ledger owner prevents storage limit lowering: "
                            + str(record["reservation_id"]))
                    if _group_usage(record.get("child"))["live_processes"]:
                        raise DaemonResourceError(
                            "live disk ledger child prevents storage limit lowering: "
                            + str(record["reservation_id"]))

            refuse_live_owners()
            retained_external_overage = 0
            for record in original_records.values():
                native_deadlines._check_resource_operation_deadline()
                # _read applies these same per-record bounds at the new cap.
                # Refuse before writing if immutable history could not reopen.
                _integer(record["storage_bytes"], "ledger storage_bytes", maximum=target)
                charges = _external_charges(record, limit_bytes=target)
                if record["status"] != "released":
                    retained_external_overage += max(0, sum(charges.values()) - record["storage_bytes"])
            lowered = copy.deepcopy(ledger)
            lowered["limit_bytes"] = target
            control.storage_limit_bytes = target
            accounting = control._account(lowered, additional=retained_external_overage)
            refuse_live_owners()
            if lowered["reservations"] != original_records:
                raise DaemonResourceError("storage limit lowering changed reservation records")
            control._write(lowered)
            if control._read() != lowered:
                raise DaemonResourceError("storage limit lowering readback differs")
            records_raw = json.dumps(original_records, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()
            return {"schema": "daemon-resource-storage-limit-migration/v1",
                    "ledger_path": str(control.ledger_path),
                    "roots": copy.deepcopy(control.root_identities),
                    "previous_limit_bytes": previous, "storage_limit_bytes": target,
                    "reservation_count": len(original_records),
                    "reservation_records_sha256": hashlib.sha256(records_raw).hexdigest(),
                    "records_roots_history_and_charges_preserved": True,
                    "live_nonreleased_owners_and_current_children_refused": True,
                    "retained_external_overage_bytes": retained_external_overage,
                    "accounting": copy.deepcopy(accounting),
                    "reservation_or_scheduler_lease_acquired": False}

    def _scheduler_identity(self):
        """Private fixed-lane hook; the daemon public API stays HAMMER_LEAN."""
        return SCHEDULER_LANE, SCHEDULER_WORKLOAD

    def _scheduler_request_id(self):
        return "daemon:" + self.reservation_id

    def _validate_new_reservation(self, ledger):
        """Private pre-admission hook; existing daemon attempts bind later."""

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
            lock_started = time.monotonic()
            deadline = lock_started + self.ledger_lock_timeout_seconds
            lock_acquired = False
            operation = native_deadlines.resource_operation_deadline()
            if operation is not None:
                deadline = min(deadline, native_deadlines._operation_clock(operation))
            while True:
                native_deadlines._check_resource_operation_deadline()
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    lock_acquired = True
                    break
                except BlockingIOError:
                    observed_at = time.monotonic()
                    if observed_at >= deadline:
                        error = DaemonResourceError("disk ledger lock unavailable")
                        error._lock_observation = {
                            "schema": "daemon-resource-ledger-lock-timeout/v1",
                            "stage": "exclusive_acquire_before_yield",
                            "lock_path": str(self.lock_path),
                            "opened_lock_identity": {key: getattr(info, key) for key in
                                ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink",
                                 "st_size", "st_mtime_ns", "st_ctime_ns")},
                            "configured_lock_timeout_seconds": self.ledger_lock_timeout_seconds,
                            "started_monotonic": lock_started,
                            "deadline_monotonic": deadline,
                            "observed_monotonic": observed_at,
                            "lock_acquired": False,
                            "holder_identity_established": False,
                        }
                        error._lock_observation_binding = (self, json.dumps(
                            error._lock_observation, sort_keys=True, allow_nan=False).encode())
                        raise error from None
                    time.sleep(min(0.05, max(0, deadline - time.monotonic())))
            native_deadlines._check_resource_operation_deadline()
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
            if self._entered or self._require_existing_ledger:
                raise DaemonResourceError("disk ledger disappeared") from None
            return {"schema": SCHEMA, "roots": self.root_identities,
                    "limit_bytes": self.storage_limit_bytes, "reservations": {}}
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
        if (value["schema"] != SCHEMA or value["roots"] != self.root_identities
                or type(value["limit_bytes"]) is not int
                or value["limit_bytes"] != self.storage_limit_bytes):
            raise DaemonResourceError("disk ledger storage scope differs")
        records = value["reservations"]
        if type(records) is not dict or len(records) > MAX_RESERVATIONS:
            raise DaemonResourceError("invalid disk reservation inventory")
        for key, record in records.items():
            if type(record) is not dict or record.get("reservation_id") != key or record.get("status") not in {"reserved", "active", "retained", "released"}:
                raise DaemonResourceError("invalid disk reservation record")
            _integer(record.get("storage_bytes"), "ledger storage_bytes", maximum=self.storage_limit_bytes)
            _integer(record.get("owner_pid"), "ledger owner_pid")
            if "child_process_slots" in record:
                _integer(record["child_process_slots"], "ledger child_process_slots")
            _external_charges(record, limit_bytes=self.storage_limit_bytes)
        return value

    def _write(self, value):
        self._verify_owner_roots()
        _safe_path(self.ledger_path, missing=True)
        raw = (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
        if len(raw) > MAX_LEDGER_BYTES:
            error = DaemonResourceError("disk ledger byte bound exceeded")
            error._ledger_write_bound_observation = dict(
                schema="daemon-resource-ledger-write-bound/v1",
                serialized_bytes=len(raw), maximum_bytes=MAX_LEDGER_BYTES,
                excess_bytes=len(raw) - MAX_LEDGER_BYTES, write_started=False)
            raise error
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.ledger_path.parent, prefix=".daemon-reservation-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            native_deadlines._check_resource_operation_deadline()
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
        native_deadlines._check_resource_operation_deadline()
        inventory = _inventory(self.roots)
        native_deadlines._check_resource_operation_deadline()
        observed = inventory["apparent_bytes"]
        outstanding = 0
        for row in ledger["reservations"].values():
            native_deadlines._check_resource_operation_deadline()
            if row["status"] != "released":
                outstanding += row["storage_bytes"]
        charged = observed + outstanding + additional
        free_values = []
        for root in self.roots:
            native_deadlines._check_resource_operation_deadline()
            free_values.append(shutil.disk_usage(root).free)
            native_deadlines._check_resource_operation_deadline()
        free = min(free_values)
        result = {"observed_apparent_bytes": observed, "outstanding_full_reservations_bytes": outstanding,
                  "additional_requested_bytes": additional, "charged_bytes": charged,
                  "limit_bytes": self.storage_limit_bytes, "minimum_filesystem_free_bytes": free,
                  "scope": "named_roots_only_apparent_bytes", "inventory": inventory}
        if charged > self.storage_limit_bytes or free < outstanding + additional:
            error = DaemonResourceError("storage reservation capacity exceeded")
            error._capacity_observation = copy.deepcopy({
                "schema": "daemon-resource-capacity-observation/v1",
                **{key: result[key] for key in (
                    "observed_apparent_bytes", "outstanding_full_reservations_bytes",
                    "additional_requested_bytes", "charged_bytes", "limit_bytes",
                    "minimum_filesystem_free_bytes", "scope")},
                "storage_capacity_exceeded": charged > self.storage_limit_bytes,
                "filesystem_free_insufficient": free < outstanding + additional,
                "storage_capacity_deficit_bytes": max(0, charged - self.storage_limit_bytes),
                "filesystem_free_deficit_bytes": max(0, outstanding + additional - free),
            })
            raise error
        self._verify_owner_roots()
        native_deadlines._check_resource_operation_deadline()
        return result

    @contextmanager
    def _admission_scope(self):
        """Default callers retain their existing operation context unchanged."""
        yield

    @contextmanager
    def _admission_cleanup_scope(self):
        """Use only an already declared native cleanup end; never renew it."""
        operation = native_deadlines.resource_operation_deadline()
        if operation is None:
            yield
        else:
            with native_deadlines.resource_cleanup_deadline(
                    native_deadline_monotonic=operation.native_deadline_monotonic):
                yield

    def __enter__(self):
        if self._entered:
            raise DaemonResourceError("reservation can only be entered once")
        scheduler = None
        scheduler_lane, scheduler_workload = self._scheduler_identity()
        try:
            # The admission scope exits BEFORE original post-entry cleanup.
            with self._admission_scope():
                if self._scheduler_state_path is not None:
                    from .existing_resource_scheduler import open_existing_scheduler
                    scheduler = open_existing_scheduler(self._scheduler_state_path,
                                                        self._expected_scheduler_policy_sha256)
                with self._locked():
                    ledger = self._read()
                    if len(ledger["reservations"]) >= MAX_RESERVATIONS:
                        raise DaemonResourceError("disk reservation inventory full")
                    self._validate_new_reservation(ledger)
                    observation = self._account(ledger, additional=self.storage_bytes)
                    record = {"reservation_id": self.reservation_id, "status": "reserved",
                              "owner_pid": self._owner_pid, "storage_bytes": self.storage_bytes,
                              "memory_mb": self.memory_mb, "cpu_slots": self.cpu_slots,
                              "child_process_slots": self.child_process_slots,
                              "scheduler_lane": scheduler_lane.value, "workload": scheduler_workload,
                              "created_at": time.time(), "attempt_directory": self._attempt, "child": None,
                              "prior_children": [], "external_charges": {},
                              "last_usage": observation, "artifacts_durable_asserted": False}
                    ledger["reservations"][self.reservation_id] = record
                    self._write(ledger)
                    self._record = copy.deepcopy(record)
                    self._entered = True
                self._lease = self._acquire_native_lease(scheduler, scheduler_lane)
                self._update(status="active")
        except BaseException:
            # Preserve unknown first-write failures and original native cleanup.
            if self._entered:
                cleanup_errors = []
                try:
                    with self._admission_cleanup_scope():
                        try:
                            self._retain("scheduler_admission_failed")
                        except BaseException as cleanup:
                            cleanup_errors.append(type(cleanup).__name__)
                        finally:
                            if self._lease is not None:
                                try:
                                    self._lease.release()
                                except BaseException as cleanup:
                                    cleanup_errors.append(type(cleanup).__name__)
                except BaseException as cleanup:
                    cleanup_errors.append(type(cleanup).__name__)
                if cleanup_errors:
                    self._cleanup_error = "+".join(cleanup_errors)
            raise
        return self

    def _acquire_native_lease(self, scheduler, lane):
        """Private acquisition hook; the daemon still owns one native root."""
        return (scheduler if scheduler is not None else get_global_resource_scheduler()).acquire(
            lane, cpu_slots=self.cpu_slots, memory_mb=self.memory_mb,
            child_process_slots=self.child_process_slots, requires_gpu=False,
            timeout=self.timeout_seconds, request_id=self._scheduler_request_id())

    def heartbeat(self):
        """Renew owned native custody without exposing its authority token."""
        self._verify_owner_roots()
        if not self._entered or self._lease is None or self._record["status"] == "released":
            return False
        return bool(self._lease.renew())

    @property
    def cancelled(self):
        """Missing, released or revoked native custody is a cancellation."""
        self._verify_owner_roots()
        return (not self._entered or self._lease is None or self._record["status"] == "released"
                or self._lease.cancelled)

    def _update(self, **fields):
        with self._locked():
            ledger = self._read()
            record = ledger["reservations"].get(self.reservation_id)
            if record is None or record["owner_pid"] != self._owner_pid or record["storage_bytes"] != self.storage_bytes:
                raise DaemonResourceError("owned disk reservation differs")
            record.update(fields)
            self._write(ledger)
            self._record = copy.deepcopy(record)

    def _remember_cleanup_failure(self, stage, error):
        observation = _bounded_cleanup_failure_observation(stage, error, self.lock_path, origin_owner=self)
        if len(self._cleanup_failure_observations) < 4:
            self._cleanup_failure_observations.append(observation)
        else:
            self._cleanup_failure_observation_overflow = True

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
        _integer(byte_count, "external charge bytes", minimum=0, maximum=self.storage_limit_bytes)
        with self._locked():
            ledger = self._read()
            row = ledger["reservations"].get(self.reservation_id)
            if row is None or row["owner_pid"] != self._owner_pid or row["status"] == "released":
                raise DaemonResourceError("owned disk reservation differs")
            charges = dict(_external_charges(row, limit_bytes=self.storage_limit_bytes))
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

    def _usage_inventory(self, attempt):
        # Live observers may be explicitly specialized by a concrete owner.
        # Finalize and release deliberately retain their strict inventories.
        return _inventory([attempt], strict=True)

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
        attempt_bytes = self._usage_inventory(attempt)["apparent_bytes"]
        with self._locked():
            ledger = self._read()
            usage = self._account(ledger)
            row = ledger["reservations"][self.reservation_id]
            external_bytes = sum(_external_charges(row, limit_bytes=self.storage_limit_bytes).values())
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
        if self._scheduler_state_path is not None and usage["process_slot_estimate_exceeded"]:
            raise DaemonResourceError("child group process-slot limit exceeded")
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
            external_bytes = sum(_external_charges(row, limit_bytes=self.storage_limit_bytes).values())
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
            row["final_external_charged_bytes"] = sum(_external_charges(row, limit_bytes=self.storage_limit_bytes).values())
            row["final_total_charged_bytes"] = (row["final_attempt_bytes"] or 0) + row["final_external_charged_bytes"]
            row["attempt_exceeded_reservation"] = row["final_total_charged_bytes"] > self.storage_bytes
            self._write(ledger)
            self._record = copy.deepcopy(row)
        if self._lease is not None:
            self._lease.release()
        return self.to_dict()

    close = release

    def to_dict(self):
        scheduler_lane, scheduler_workload = self._scheduler_identity()
        value = {"schema": SCHEMA, "reservation_id": self.reservation_id,
                "scheduler_lane": scheduler_lane.value, "workload": scheduler_workload,
                "status": self._record["status"] if self._record is not None else "not_entered",
                "ledger_path": str(self.ledger_path), "roots": copy.deepcopy(self.root_identities),
                "storage_limit_bytes": self.storage_limit_bytes, "record": copy.deepcopy(self._record),
                "resource_lease": self._lease.to_dict() if self._lease is not None else None,
                "cleanup_error": self._cleanup_error,
                "enforcement": "cooperative_admission_and_polled_usage_not_kernel_quota"}
        observations = getattr(self, '_cleanup_failure_observations', [])
        if observations:
            value['cleanup_failure_observations'] = copy.deepcopy(observations)
            value['cleanup_failure_observation_overflow'] = self._cleanup_failure_observation_overflow
        return value

    def __exit__(self, exc_type, exc, traceback):
        if self._record is not None and self._record["status"] != "released":
            try:
                try:
                    self._retain("context_failed" if exc_type else "explicit_release_required")
                except BaseException as cleanup:
                    self._remember_cleanup_failure('failure_retention', cleanup)
                    raise
                finally:
                    try:
                        if self._lease is not None and not _group_usage(self._child)["live_processes"]:
                            self._lease.release()
                    except BaseException as cleanup:
                        self._remember_cleanup_failure('native_release', cleanup)
                        raise
            except BaseException as cleanup:
                self._cleanup_error = type(cleanup).__name__
                if exc_type is None:
                    raise
        return False


__all__ = ["DaemonResourceReservation", "DaemonResourceError", "MAX_STORAGE_BYTES"]
