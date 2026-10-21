"""One native VALIDATION grant and aggregate storage owner for a concrete run.

All declared writable outputs belong to one private attempt. This is sampled
accounting, not a filesystem quota or a sandbox. Process observations cover the
original isolated child group by default. The explicit sampled-descendant
profile additionally retains observed birth-bound descendants across new
sessions and reparenting. Neither profile contains an unobserved escaping
daemon; arbitrary-tree containment requires a separately qualified kernel
scope. No result from this module constitutes Lean admission.

Constructing a reservation never initializes the scheduler or ledger. Native
host admission is fail-fast; ``timeout_seconds`` bounds the productive run.
Launchers must attach an isolated direct child behind a startup barrier before
allowing productive writes. Stop and reap that group on *any* guard failure.
The caller remains responsible for actually redirecting every writable cache,
database/sidecar, spill, fixture, export and log into the declared layout.
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
import sys
import threading
import time

from . import autoencoder_daemon_resources as host
from .resource_scheduler import ResourceLane

REQUEST_SCHEMA = "owned-validation-request/v1"
RESULT_SCHEMA = "owned-validation-result/v1"
MAX_REQUEST_BYTES = 1_048_576
MAX_SOURCE_BYTES = 4 * 1024 * 1024
MAX_SOURCE_PINS = 256
MAX_DURABILITY_ENTRIES = 20_000
OUTPUT_NAMES = ("pytest", "tmp", "cache", "db", "exports", "logs")
GROUP_SCOPE = "isolated_process_group"
TRACKED_SCOPE = "sampled_birth_bound_descendants"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class ValidationResourceError(host.DaemonResourceError):
    """A concrete validation run's ownership or limits could not be verified."""


def _need(condition, message):
    if not condition:
        raise ValidationResourceError(message)


def _finite_positive(value, name, maximum):
    _need(type(value) in (int, float) and math.isfinite(value)
          and 0 < value <= maximum, f"invalid {name}")
    return float(value)


def _regular_bytes(value, bound):
    path = host._safe_path(value)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        opened = os.fstat(stream.fileno())
        _need(stat.S_ISREG(opened.st_mode) and opened.st_nlink == 1 and opened.st_size <= bound,
              "validation input is not a bounded regular file")
        raw = stream.read(bound + 1)
        _need(len(raw) <= bound, "validation input byte bound exceeded")
        after = os.fstat(stream.fileno())
    host._safe_path(path)
    current = path.lstat()
    _need((opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns,
           opened.st_ctime_ns) == (after.st_dev, after.st_ino, after.st_size,
                                   after.st_mtime_ns, after.st_ctime_ns)
          and (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns,
               current.st_ctime_ns) == (after.st_dev, after.st_ino, after.st_size,
                                       after.st_mtime_ns, after.st_ctime_ns),
          "validation input changed while reading")
    return path, raw, {"device": opened.st_dev, "inode": opened.st_ino}


def _decode(raw):
    try:
        return json.loads(raw, object_pairs_hook=host._json_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(
                              ValidationResourceError("nonfinite validation JSON")))
    except (ValueError, UnicodeError) as exc:
        raise ValidationResourceError("invalid validation JSON") from exc


def _fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class ValidationResourceReservation(host.DaemonResourceReservation):
    """Fixed VALIDATION/canonical_validation owner, with no borrowed authority.

    ``validation_manifest_path`` is an immutable, bounded input outside the
    initially empty private attempt. Its SHA256, exact budgets, selected checks,
    source pins and output layout are verified before native admission and at
    every guard. ``check_limits(full=False)`` performs local observations only;
    call ``heartbeat`` separately and ``check_limits(full=True)`` at explicit
    global checkpoints. A slow global census cannot hold up a separate local
    watchdog unless the caller serializes those operations itself.
    """

    def __init__(self, ledger_path, *, roots, attempt_directory, storage_bytes,
                 memory_mb, cpu_slots, child_process_slots, scheduler_state_path,
                 expected_scheduler_policy_sha256, validation_manifest_path,
                 frozen_validation_manifest_sha256, timeout_seconds,
                 ledger_lock_timeout_seconds=60, full_check_interval_seconds=300):
        _need(type(frozen_validation_manifest_sha256) is str
              and _DIGEST.fullmatch(frozen_validation_manifest_sha256),
              "exact frozen validation request SHA256 required")
        self.validation_timeout_seconds = _finite_positive(timeout_seconds, "timeout_seconds", 3600)
        self.full_check_interval_seconds = _finite_positive(
            full_check_interval_seconds, "full_check_interval_seconds", 3600)
        self.directory = host._safe_path(attempt_directory, directory=True)
        self.identity = host._root_identity(self.directory)
        self.output_layout = {name: self.directory / name for name in OUTPUT_NAMES}
        self.request_path, raw, self._request_identity = _regular_bytes(
            validation_manifest_path, MAX_REQUEST_BYTES)
        _need(self.request_path != self.directory and self.directory not in self.request_path.parents,
              "validation request must be outside the owned attempt")
        self.request_sha256 = frozen_validation_manifest_sha256
        _need(hashlib.sha256(raw).hexdigest() == self.request_sha256,
              "frozen validation request hash differs")
        self.request = _decode(raw)
        self._source_identities = {}
        self._output_identities = {}
        self._opened = False
        self._started = None
        self._sealed = None
        self._process_lock = threading.RLock()
        self._descendants = None
        self._last_process_observation = None
        self._owner_identity = host._process(os.getpid())
        _need(self._owner_identity is not None, "Linux owner process telemetry required")
        # The actual existing state is validated before ledger access. This
        # opener grants nothing and cannot initialize or reconfigure a policy.
        from .existing_resource_scheduler import open_existing_scheduler
        open_existing_scheduler(scheduler_state_path, expected_scheduler_policy_sha256)
        super().__init__(ledger_path, roots=roots, storage_bytes=storage_bytes,
                         memory_mb=memory_mb, cpu_slots=cpu_slots,
                         child_process_slots=child_process_slots, timeout_seconds=0,
                         ledger_lock_timeout_seconds=ledger_lock_timeout_seconds,
                         scheduler_state_path=scheduler_state_path,
                         expected_scheduler_policy_sha256=expected_scheduler_policy_sha256,
                         require_existing_ledger=True)
        self._validate_request()
        self._process_scope = self.request["process_scope"]
        self._guard_inputs()
        _need(any(root in self.directory.parents for root in self.roots),
              "validation attempt must be a strict descendant of one named root")

    def _scheduler_identity(self):
        return ResourceLane.VALIDATION, "canonical_validation"

    def _scheduler_request_id(self):
        return "validation:" + self.reservation_id

    def _validate_request(self):
        request = self.request
        fields = {"schema", "argv", "cwd", "selected_checks", "source_sha256",
                  "timeout_seconds", "storage_bytes", "memory_mb", "cpu_slots",
                  "child_process_slots", "attempt_directory", "outputs",
                  "declared_external_writable_paths", "process_scope",
                  "scheduler_state_path", "expected_scheduler_policy_sha256", "roots"}
        _need(type(request) is dict and set(request) == fields
              and request["schema"] == REQUEST_SCHEMA, "invalid frozen validation request schema")
        for field in ("argv", "selected_checks"):
            values = request[field]
            _need(type(values) is list and 0 < len(values) <= 256
                  and all(type(value) is str and value.strip() and "\x00" not in value
                          and len(value) <= 8192 for value in values),
                  f"nonempty concrete validation {field} required")
        _need(len(set(request["selected_checks"])) == len(request["selected_checks"]),
              "duplicate validation checks")
        _need(type(request["cwd"]) is str and Path(request["cwd"]).is_absolute(),
              "absolute validation cwd required")
        host._safe_path(request["cwd"], directory=True)
        self._cwd_identity = host._root_identity(Path(request["cwd"]))
        _need(request["roots"] == [str(root) for root in self.roots],
              "frozen validation named roots differ")
        _need(request["attempt_directory"] == str(self.directory)
              and request["outputs"] == {name: str(path) for name, path in self.output_layout.items()}
              and request["declared_external_writable_paths"] == []
              and request["process_scope"] in (GROUP_SCOPE, TRACKED_SCOPE),
              "validation writable outputs must use the exact private attempt layout")
        budgets = {"storage_bytes": self.storage_bytes, "memory_mb": self.memory_mb,
                   "cpu_slots": self.cpu_slots, "child_process_slots": self.child_process_slots}
        _need(all(type(request[name]) is int and request[name] == value
                  for name, value in budgets.items()), "frozen validation budgets differ")
        _need(type(request["timeout_seconds"]) in (int, float)
              and request["timeout_seconds"] == self.validation_timeout_seconds,
              "frozen validation deadline differs")
        _need(request["scheduler_state_path"] == str(self._scheduler_state_path)
              and request["expected_scheduler_policy_sha256"] == self._expected_scheduler_policy_sha256,
              "frozen validation scheduler identity differs")
        sources = request["source_sha256"]
        _need(type(sources) is dict and 0 < len(sources) <= MAX_SOURCE_PINS,
              "nonempty validation source pins required")
        for spelling, digest in sources.items():
            _need(type(spelling) is str and Path(spelling).is_absolute()
                  and type(digest) is str and _DIGEST.fullmatch(digest),
                  "invalid validation source pin")
            path, raw, identity = _regular_bytes(spelling, MAX_SOURCE_BYTES)
            _need(str(path) == spelling and hashlib.sha256(raw).hexdigest() == digest,
                  "validation source pin differs")
            self._source_identities[spelling] = identity

    def _guard_inputs(self):
        path, raw, identity = _regular_bytes(self.request_path, MAX_REQUEST_BYTES)
        _need(identity == self._request_identity and hashlib.sha256(raw).hexdigest() == self.request_sha256,
              "frozen validation request changed")
        _need(_decode(raw) == self.request, "in-memory validation request changed")
        _need(host._root_identity(Path(self.request["cwd"])) == self._cwd_identity,
              "validation cwd identity changed")
        _need(host._root_identity(self.directory) == self.identity, "validation attempt identity changed")
        info = self.directory.lstat()
        _need(info.st_uid == os.geteuid() and not stat.S_IMODE(info.st_mode) & 0o077,
              "validation attempt must be private and owned by this user")
        for spelling, digest in self.request["source_sha256"].items():
            path, raw, identity = _regular_bytes(spelling, MAX_SOURCE_BYTES)
            _need(identity == self._source_identities[spelling]
                  and hashlib.sha256(raw).hexdigest() == digest, "validation source changed")
        for name, identity in self._output_identities.items():
            _need(host._root_identity(self.output_layout[name]) == identity,
                  "validation output directory identity changed")
        owner = host._process(os.getpid())
        _need(owner is not None and owner["pid"] == self._owner_identity["pid"]
              and owner["birth"] == self._owner_identity["birth"], "validation owner identity changed")

    def _read(self):
        # Reuse the actual native ledger-lock scopes. Every inherited update or
        # finalization reads here *before* it can overwrite an altered owned
        # row. No extra ledger access is added to the independent local guard.
        ledger = super()._read()
        if self._record is not None:
            _need(ledger["reservations"].get(self.reservation_id) == self._record,
                  "owned validation ledger record changed")
        return ledger

    def _validate_new_reservation(self, ledger):
        # Called while the original native ledger lock is held, before writing
        # this full storage promise or acquiring the one actual native grant.
        self._guard_inputs()
        _need(not any(self.directory.iterdir()), "validation attempt must initially be empty")
        for record in ledger["reservations"].values():
            if record["status"] == "released" or record.get("attempt_directory") is None:
                continue
            previous = record["attempt_directory"]
            _need(type(previous) is dict and type(previous.get("path")) is str,
                  "existing attempt identity is invalid")
            path = Path(previous["path"])
            _need(not (path == self.directory or path in self.directory.parents
                       or self.directory in path.parents
                       or (previous.get("device"), previous.get("inode")) ==
                          (self.identity["device"], self.identity["inode"])),
                  "validation attempt overlaps another outstanding claim")
        # A scheduler refusal now retains a truthfully bound empty attempt.
        self._attempt = copy.deepcopy(self.identity)

    def open(self):
        _need(not self._opened, "validation resources are already open")
        self._guard_inputs()
        super().__enter__()
        self._opened = True
        self._started = time.monotonic()
        try:
            self.guard()
            lease = self._lease.to_dict()
            _need(lease["lane"] == ResourceLane.VALIDATION.value
                  and lease["owner_pid"] == os.getpid()
                  and lease["parent_lease_id"] is None, "native validation root grant differs")
            self._update(validation_request_sha256=self.request_sha256,
                         owner_birth=self._owner_identity["birth"],
                         scheduler_state_path=str(self._scheduler_state_path),
                         scheduler_policy_sha256=self._expected_scheduler_policy_sha256,
                         native_lease_id=lease["lease_id"],
                         process_scope=("isolated_process_group_only" if not self.tracks_descendants
                                        else TRACKED_SCOPE),
                         outputs={name: str(path) for name, path in self.output_layout.items()})
            for name, path in self.output_layout.items():
                path.mkdir(mode=0o700)
                self._output_identities[name] = host._root_identity(path)
                _fsync_directory(path)
            _fsync_directory(self.directory)
            self.check_limits()
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise
        return self

    __enter__ = open

    def guard(self):
        """Verify only local frozen inputs, owner, paths and run deadline."""
        _need(self._opened and self._record is not None and self._record["status"] != "released",
              "validation resource reservation is not open")
        self._verify_owner_roots()
        self._guard_inputs()
        _need(time.monotonic() - self._started <= self.validation_timeout_seconds,
              "validation run deadline exceeded")
        return True

    def heartbeat(self):
        self.guard()
        lease = self._lease.to_dict()
        _need(lease["lane"] == ResourceLane.VALIDATION.value
              and lease["lease_id"] == self._record["native_lease_id"]
              and lease["owner_pid"] == self._owner_pid
              and lease["parent_lease_id"] is None
              and lease["cpu_slots"] == self.cpu_slots
              and lease["memory_mb"] == self.memory_mb
              and lease["child_process_slots"] == self.child_process_slots
              and lease["requires_gpu"] is False, "native validation grant identity differs")
        return super().heartbeat()

    def environment(self, base=None):
        """Return declared redirects; caller still owns every library DB/cache path."""
        self.guard()
        values = dict(os.environ if base is None else base)
        values.update(TMPDIR=str(self.output_layout["tmp"]), TMP=str(self.output_layout["tmp"]),
                      TEMP=str(self.output_layout["tmp"]),
                      XDG_CACHE_HOME=str(self.output_layout["cache"]), PYTHONDONTWRITEBYTECODE="1")
        return values

    def _retain_attached_descendants(self):
        if not self.tracks_descendants or self._child is None or self._descendants is not None:
            return
        child = self._child
        current = host._process(child["pid"])
        _need(current is not None and current["pid"] == child["pid"]
              and current["birth"] == child["birth"],
              "attached descendant leader birth differs before sampling")
        # Keep the genuine tracker private until its initial sample and both
        # current PID/birth checks agree with the base owner's saved identity.
        from ipfs_datasets_py.logic.backends.process import _LinuxDescendantTracker
        tracker = None
        try:
            tracker = _LinuxDescendantTracker(child["pid"], retain_history=True)
            _need(tracker.enabled, "Linux descendant observations required")
            tracker.refresh()
            leader = tracker.records.get(child["pid"])
            _need(leader is not None and str(leader[0]) == child["birth"],
                  "attached descendant leader birth differs")
            _need(not tracker.error, "initial validation descendant observation failed: " + tracker.error)
            current = host._process(child["pid"])
            _need(current is not None and current["pid"] == child["pid"]
                  and current["birth"] == child["birth"],
                  "attached descendant leader birth differs after sampling")
        except BaseException as tracking_error:
            if tracker is not None:
                try:
                    tracker.close()
                except BaseException as close_error:
                    tracking_error.add_note("discarding initial descendant sample: "
                                            + type(close_error).__name__ + ": " + str(close_error)[:300])
            raise
        # An unverified sample is never published for later drain/signalling.
        self._descendants = tracker

    def attach_child(self, child_pid):
        self.guard()
        _need(self._sealed is None, "sealed validation cannot attach more work")
        _need(self._child is None, "one validation process group per reservation required")
        with self._process_lock:
            try:
                usage = super().check_usage(self.directory, child_pid=child_pid)
            except BaseException as attachment_error:
                try:
                    self._retain_attached_descendants()
                except BaseException as tracking_error:
                    attachment_error.add_note("descendant retention after attachment failure: "
                                              + type(tracking_error).__name__ + ": " + str(tracking_error)[:300])
                raise
            # The launcher keeps its child behind the startup barrier until
            # both the durable attachment and this genuine tracker succeed.
            self._retain_attached_descendants()
            self.check_limits()
            return usage

    @property
    def tracks_descendants(self):
        return self._process_scope == TRACKED_SCOPE

    def _check_process_owner(self):
        # Cleanup must remain possible after a source/deadline/watchdog refusal;
        # it does not invoke the productive guard or acquire a new grant.
        current = host._process(os.getpid())
        _need(current is not None and current["pid"] == self._owner_identity["pid"]
              and current["birth"] == self._owner_identity["birth"],
              "validation process cleanup belongs to another owner")

    def observe_processes(self):
        """Sample the original group plus retained out-of-group descendants.

        This is cooperative ancestry observation, not kernel containment. Short
        lived unobserved escaping daemons remain outside this explicit scope.
        Every retained identity is checked before counting or signalling it.
        """
        with self._process_lock:
            self._check_process_owner()
            group = host._group_usage(self._child)
            if not self.tracks_descendants:
                return {"scope": "isolated_process_group_only", "group_rss": group,
                        "live_processes": group["live_processes"],
                        "rss_bytes": group["rss_bytes"]}
            tracker = self._descendants
            _need(self._child is None or tracker is not None,
                  "attached validation child has no retained descendant owner")
            if tracker is None:
                result = {"scope": TRACKED_SCOPE, "group_rss": group,
                          "live_processes": 0, "rss_bytes": 0,
                          "observed_identities": [], "out_of_group_live_identities": [],
                          "tracking_error": ""}
            else:
                tracker.refresh()
                extra, extra_rss = [], 0
                # Count the original group once. Only retained identities now
                # outside that group are added; setsid does not lose custody.
                for pid, (birth, _) in tuple(tracker.records.items()):
                    identity = host._process(pid)
                    if identity is None or identity["birth"] != str(birth) or identity["state"] == "Z":
                        continue
                    if identity["group_pid"] != self._child["pid"]:
                        extra.append({"pid": pid, "birth": str(birth),
                                      "parent_pid": identity["parent_pid"],
                                      "process_group_id": identity["group_pid"],
                                      "rss_bytes": identity["rss_bytes"]})
                        extra_rss += identity["rss_bytes"]
                result = {"scope": TRACKED_SCOPE, "group_rss": group,
                          "live_processes": group["live_processes"] + len(extra),
                          "rss_bytes": group["rss_bytes"] + extra_rss,
                          "observed_identities": [identity.to_dict()
                              for _, identity in sorted(tracker.history.items())],
                          "out_of_group_live_identities": sorted(extra, key=lambda row: row["pid"]),
                          "tracking_error": tracker.error}
            self._last_process_observation = copy.deepcopy(result)
            _need(not result["tracking_error"], "validation descendant observation failed: " + result["tracking_error"])
            return result

    def drain_tracked_descendants(self, grace_seconds=3.0):
        """Drain retained native descendants independently of the pytest group.

        The original owner is retained on a survivor or observation error. No
        PID-name scan, foreign lease mutation or new scheduler owner is used.
        """
        _finite_positive(grace_seconds, "descendant cleanup grace", 60)
        with self._process_lock:
            self._check_process_owner()
            if not self.tracks_descendants or self._descendants is None:
                return None
            # A sticky observation error must not prevent attempts to stop the
            # already retained identities. It still prevents a release claim.
            _, survivors = self._descendants.drain(grace_seconds)
            observation = self.observe_processes()
            _need(not survivors and not observation["live_processes"],
                  "validation tracked descendant cleanup remains unresolved")
            return observation

    def _require_processes_stopped(self):
        observation = self.observe_processes()
        _need(not observation["live_processes"],
              "validation child group or tracked descendants are still alive")
        return observation

    def to_dict(self):
        value = super().to_dict()
        if self.tracks_descendants:
            value["process_observation"] = copy.deepcopy(self._last_process_observation)
        return value

    def check_limits(self, *, full=False):
        """Observe local aggregate bytes/RSS/processes; full=True adds real census."""
        _need(type(full) is bool, "full must be a boolean")
        self.guard()
        processes = self.observe_processes()
        group = processes["group_rss"]
        owner = host._process(os.getpid())
        _need(owner is not None, "validation owner telemetry unavailable")
        rss = owner["rss_bytes"] + processes["rss_bytes"]
        _need(rss <= self.memory_mb * 1024 * 1024, "validation owner and child RSS limit exceeded")
        _need(processes["live_processes"] <= self.child_process_slots, "validation child process limit exceeded")
        inventory = host._inventory([self.directory], strict=True)
        _need(not host._external_charges(self._record), "validation external writable charges are unsupported")
        _need(inventory["apparent_bytes"] <= self.storage_bytes, "validation aggregate storage limit exceeded")
        result = {"scope": ("owned_attempt_and_isolated_process_group_only" if not self.tracks_descendants
                            else "owned_attempt_and_" + TRACKED_SCOPE),
                  "attempt_bytes": inventory["apparent_bytes"], "inventory": inventory,
                  "owner_and_child_rss_bytes": rss, "group_rss": group,
                  "checked_at": time.time(), "full_ledger_check": False,
                  "enforcement": "sampled_not_kernel_quota_or_arbitrary_tree_containment"}
        if self.tracks_descendants:
            result["process_observation"] = processes
        if full:
            _need(not self.cancelled and self.heartbeat(), "native validation custody was lost")
            result["ledger_usage"] = super().check_usage(self.directory)
            result["full_ledger_check"] = True
        self.guard()
        return result

    def account_external_bytes(self, *args, **kwargs):
        raise ValidationResourceError("validation writable outputs must remain inside its attempt")

    def _evidence_path(self, value):
        _need(type(value) is str and value, "invalid validation evidence path")
        path = Path(value)
        path = host._safe_path(path if path.is_absolute() else self.directory / path)
        _need(self.directory in path.parents, "validation evidence is outside the owned attempt")
        return path

    def _durable_inventory(self, *, fsync):
        """Hash unaliased regular owned files; never follow a symlink or export bytes."""
        files, directories, pending = [], [], [self.directory]
        receipt = self.output_layout["logs"] / "validation-durability.json"
        while pending:
            directory = host._safe_path(pending.pop(), directory=True)
            directories.append(directory)
            with os.scandir(directory) as entries:
                for entry in entries:
                    _need(len(files) + len(directories) + len(pending) < MAX_DURABILITY_ENTRIES,
                          "validation durability inventory entry bound exceeded")
                    path = Path(entry.path)
                    info = entry.stat(follow_symlinks=False)
                    if stat.S_ISDIR(info.st_mode):
                        pending.append(path)
                        continue
                    _need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                          and info.st_uid == os.geteuid(), "invalid owned validation artifact")
                    if path == receipt:
                        continue
                    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                    with os.fdopen(descriptor, "rb") as stream:
                        opened = os.fstat(stream.fileno())
                        _need((opened.st_dev, opened.st_ino) == (info.st_dev, info.st_ino),
                              "validation artifact identity changed")
                        digest = hashlib.sha256()
                        while chunk := stream.read(1024 * 1024):
                            digest.update(chunk)
                        if fsync:
                            os.fsync(stream.fileno())
                        after = os.fstat(stream.fileno())
                    _need((opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) ==
                          (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                          and path.lstat() == after, "validation artifact changed while sealing")
                    files.append({"path": str(path.relative_to(self.directory)),
                                  "bytes": opened.st_size, "sha256": digest.hexdigest(),
                                  "device": opened.st_dev, "inode": opened.st_ino})
        if fsync:
            for directory in reversed(directories):
                _fsync_directory(directory)
        return sorted(files, key=lambda row: row["path"])

    def seal_results(self, result_path):
        """Fsync concrete result/evidence after the attached group has stopped.

        The result is the launcher's report of the selected checks, never an
        independent truth/Lean attestation. This private inventory is not a Hub
        export; it may identify private database sidecars by name and hash.
        """
        self.guard()
        _need(self._child is not None, "validation results require an attached actual child")
        self._require_processes_stopped()
        _need(self._sealed is None, "validation results are already sealed")
        path = self._evidence_path(os.fspath(result_path))
        path, raw, _ = _regular_bytes(path, MAX_REQUEST_BYTES)
        result = _decode(raw)
        required = {"schema", "request_sha256", "executed_checks", "returncode", "completed", "evidence_paths"}
        _need(type(result) is dict and set(result) == required
            and result["schema"] == RESULT_SCHEMA
            and result["request_sha256"] == self.request_sha256
            and result["executed_checks"] == self.request["selected_checks"]
            and type(result["returncode"]) is int and result["returncode"] == 0
            and result["completed"] is True, "validation result does not report all successful checks")
        evidence = result["evidence_paths"]
        _need(type(evidence) is list and 0 < len(evidence) <= 256,
              "nonempty concrete validation evidence required")
        nonempty_evidence = False
        for value in evidence:
            evidence_path = self._evidence_path(value)
            _need(evidence_path != path, "validation result cannot be its only evidence")
            nonempty_evidence |= evidence_path.stat().st_size > 0
        _need(nonempty_evidence, "empty validation evidence")
        self.check_limits()
        files = self._durable_inventory(fsync=True)
        receipt = self.output_layout["logs"] / "validation-durability.json"
        payload = {"schema": "owned-validation-durability/v1", "request_sha256": self.request_sha256,
                   "reservation_id": self.reservation_id,
                   "result_path": str(path.relative_to(self.directory)),
                   "result_sha256": hashlib.sha256(raw).hexdigest(), "files": files,
                   "scope": "owned_files_fsynced_after_recorded_group_observed_stopped",
                   "admitted": False, "arbitrary_descendant_containment": False}
        encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
        _need(sum(row["bytes"] for row in files) + len(encoded) <= self.storage_bytes,
              "validation durability receipt exceeds aggregate storage allowance")
        descriptor = os.open(receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        _fsync_directory(receipt.parent)
        self._sealed = {"files": files, "receipt_sha256": hashlib.sha256(encoded).hexdigest()}
        self.check_limits()
        return copy.deepcopy(payload)

    def finalize(self, *, artifacts_durable=False):
        _need(artifacts_durable is True, "explicit artifact durability assertion required")
        if self._record is not None and self._record["status"] == "released":
            return self.to_dict()
        self.guard()
        _need(self._child is not None and self._sealed is not None,
              "validation finalization requires actual checks and sealed results")
        self._require_processes_stopped()
        _need(self._durable_inventory(fsync=True) == self._sealed["files"],
              "validation artifacts changed after sealing")
        receipt = self.output_layout["logs"] / "validation-durability.json"
        _, raw, _ = _regular_bytes(receipt, MAX_REQUEST_BYTES * 16)
        _need(hashlib.sha256(raw).hexdigest() == self._sealed["receipt_sha256"],
              "validation durability receipt changed")
        _need(not self.cancelled and self.heartbeat(), "native validation custody was lost")
        value = super().finalize(self.directory, artifacts_durable=True)
        self._opened = False
        with self._process_lock:
            if self._descendants is not None:
                self._descendants.close()
        return value

    def release(self, *, artifacts_durable=False):
        # Do not expose the daemon's weaker compatibility release as a bypass.
        return self.finalize(artifacts_durable=artifacts_durable)

    close = release

    def __exit__(self, exc_type, exc, traceback):
        if self._opened:
            if self.tracks_descendants:
                try:
                    self._require_processes_stopped()
                except BaseException as cleanup:
                    # The base owner's group-only failure exit may release a
                    # native lease when nested sessions remain. Do not enter
                    # that weaker path until this owner's larger scope drains.
                    self._cleanup_error = type(cleanup).__name__ + ": " + str(cleanup)
                    self._retain("tracked_descendant_cleanup_unresolved")
                    if exc_type is None:
                        raise
                    return False
            try:
                return super().__exit__(exc_type, exc, traceback)
            finally:
                self._opened = False
                with self._process_lock:
                    if self._descendants is not None:
                        self._descendants.close()
        return False


__all__ = ["ValidationResourceReservation", "ValidationResourceError", "REQUEST_SCHEMA", "RESULT_SCHEMA"]
