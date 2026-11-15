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
PHYSICAL_REQUEST_SCHEMA = "owned-validation-request/v2"

LIVE_REQUEST_SCHEMA = "owned-validation-request/v4"

LIVE_INVENTORY_SCHEMA = "owned-validation-live-census/v1"

STARTUP_CLOCK_REQUEST_SCHEMA = "owned-validation-request/v6"
STARTUP_CLOCK_PROFILE = {"schema": "owned-validation-startup-clock/v1",
    "admission_seconds": 180, "productive_seconds": 180, "total_seconds": 420}

ORDINARY_SCRATCH_REQUEST_SCHEMA = "owned-validation-request/v5"
ORDINARY_SCRATCH_PROFILE_SCHEMA = "owned-validation-ordinary-scratch-live/v1"

PHYSICAL_FIXTURE_SCHEMA = "owned-validation-physical-fixtures/v1"

PHYSICAL_REQUEST_ENV = "IPFS_DATASETS_OWNED_VALIDATION_REQUEST"

PHYSICAL_REQUEST_SHA_ENV = "IPFS_DATASETS_OWNED_VALIDATION_REQUEST_SHA256"

MAX_PHYSICAL_CASES = 32

MAX_PHYSICAL_ENTRIES = 128

MAX_PHYSICAL_CASE_DEPTH = 16

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


class LocalValidationObservationStopped(ValidationResourceError):
    """This one watcher stopped after its owner's actual zero-process barrier.

    This is not success, sealing, resource release or cancellation authority.
    Other observations and the final strict checks never consume this signal.
    """

    def __init__(self, observer_stop):
        super().__init__("local validation observation stopped after verified process quiescence")
        self._observer_stop = observer_stop


class _LocalValidationObservationStop:
    __slots__ = ("_scope", "_finished", "_creator_thread", "_observer_thread",
                 "_zero_processes", "_transition_lock", "_stage")

    def __init__(self, scope, finished):
        self._scope = scope
        self._finished = finished
        self._creator_thread = threading.current_thread()
        self._observer_thread = None
        self._zero_processes = None
        self._transition_lock = threading.RLock()
        self._stage = ("created", time.monotonic())


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


def _parse_physical_fixture_profile(request, directory):
    cases, entries_by_path = {}, {}
    profile = request["physical_fixture_profile"]
    root = directory / "tmp" / "physical-fixtures"
    _need(type(profile) is dict and set(profile) == {"schema", "root", "cases"}
          and profile["schema"] == PHYSICAL_FIXTURE_SCHEMA
          and profile["root"] == str(root), "invalid owned physical fixture profile")
    argv = request["argv"]
    plugin = "ipfs_datasets_py.optimizers.logic_theorem_optimizer.validation_pytest"
    _need(argv.count("--owned-physical-fixtures") == 1
          and any(argv[index:index + 2] == ["-p", plugin]
                  for index in range(len(argv) - 1)),
          "physical fixture profile requires its explicit pytest plugin and flag")
    rows = profile["cases"]
    _need(type(rows) is list and 1 <= len(rows) <= MAX_PHYSICAL_CASES,
          "bounded nonempty physical fixture cases required")

    def relative(value):
        _need(type(value) is str and 0 < len(value) <= 256
              and "\\" not in value and "\x00" not in value,
              "invalid relative physical fixture path")
        parts = value.split("/")
        _need(len(parts) <= 8 and all(part not in ("", ".", "..") for part in parts),
              "plain relative physical fixture components required")
        try:
            value.encode("utf-8")
        except UnicodeError as exc:
            raise ValidationResourceError("invalid physical fixture path encoding") from exc
        return Path(value)

    total = 0
    for row in rows:
        _need(type(row) is dict and set(row) == {"nodeid", "entries"},
              "closed physical fixture case required")
        node = row["nodeid"]
        _need(type(node) is str and node in request["selected_checks"]
              and node not in cases, "exact unique frozen physical case required")
        try:
            suffix = hashlib.sha256(node.encode("utf-8")).hexdigest()
        except UnicodeError as exc:
            raise ValidationResourceError("invalid physical case encoding") from exc
        test_path, separator, _ = node.partition("::")
        if separator and Path(test_path).is_absolute():
            _need(test_path in request["source_sha256"], "physical test source must be pinned")
        case = root / suffix
        entries = row["entries"]
        _need(type(entries) is list and 1 <= len(entries) <= 4,
              "bounded typed physical entries required")
        paths, parsed = set(), []
        for entry in entries:
            _need(type(entry) is dict
                  and set(entry) == {"path", "kind", "target", "target_kind"},
                  "closed typed physical fixture entry required")
            path = relative(entry["path"])
            _need(path not in paths and all(path not in previous.parents
                      and previous not in path.parents for previous in paths),
                  "duplicate or overlapping physical fixture slots")
            paths.add(path)
            _need(type(entry["kind"]) is str and entry["kind"] in ("symlink", "fifo"),
                  "unsupported physical fixture kind")
            if entry["kind"] == "fifo":
                _need(entry["target"] is None and entry["target_kind"] is None,
                      "FIFO target fields must be null")
            else:
                target = relative(entry["target"])
                _need(type(entry["target_kind"]) is str
                      and entry["target_kind"] in ("file", "directory")
                      and len(str(case / target).encode("utf-8")) <= 4096,
                      "invalid physical symlink target type or length")
            parsed.append(copy.deepcopy(entry))
        for entry in parsed:
            if entry["kind"] == "symlink":
                target = Path(entry["target"])
                _need(all(target != special and special not in target.parents
                          for special in paths), "physical target traverses a special slot")
            key = str((case / entry["path"]).relative_to(directory))
            entries_by_path[key] = dict(entry, case_path=case)
        total += len(entries)
        _need(total <= MAX_PHYSICAL_ENTRIES, "too many physical fixture entries")
        cases[node] = case
    return copy.deepcopy(profile), cases, entries_by_path

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
        self._physical_profile = None
        self._live_inventory_profile = None
        self._ordinary_scratch_profile = None
        self._ordinary_scratch_absences = 0
        self._live_inventory_active = False
        self._live_inventory_in_progress = False
        self._live_inventory_lock = threading.RLock()
        self._live_inventory_thread = None
        self._live_inventory_resamples = 0
        self._physical_cases = {}
        self._physical_entries = {}
        self._physical_identities = {}
        self._physical_active = False
        self._opened = False
        self._opening = False
        self._started = None
        self._admission_started = None
        self._startup_clock_profile = None
        self._startup_original_profile = None
        self._startup_open_attempted = False
        self._startup_attachment_attempted = False
        self._startup_attachment_ready = False
        self._sealed = None
        self._process_lock = threading.RLock()
        self._local_observation_stop = None
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
        _need(type(request) is dict, "invalid frozen validation request schema")
        physical = request.get("schema") == PHYSICAL_REQUEST_SCHEMA
        startup = request.get("schema") == STARTUP_CLOCK_REQUEST_SCHEMA
        live = request.get("schema") == LIVE_REQUEST_SCHEMA or startup
        scratch = request.get("schema") == ORDINARY_SCRATCH_REQUEST_SCHEMA
        expected_fields = fields | ({"physical_fixture_profile"} if physical else
                                    {"live_inventory_profile"} if live else
                                    {"ordinary_scratch_profile"} if scratch else set())
        if startup:
            expected_fields |= {"startup_clock_profile"}
        _need(set(request) == expected_fields
              and request.get("schema") in (REQUEST_SCHEMA, PHYSICAL_REQUEST_SCHEMA,
                                             LIVE_REQUEST_SCHEMA, ORDINARY_SCRATCH_REQUEST_SCHEMA,
                                             STARTUP_CLOCK_REQUEST_SCHEMA),
              "invalid frozen validation request schema")
        if startup:
            profile = request["startup_clock_profile"]
            _need(type(profile) is dict and set(profile) == set(STARTUP_CLOCK_PROFILE)
                  and type(profile["schema"]) is str
                  and all(type(profile[key]) is int for key in ("admission_seconds", "productive_seconds", "total_seconds"))
                  and profile == STARTUP_CLOCK_PROFILE
                  and type(request["timeout_seconds"]) is int and request["timeout_seconds"] == 180
                  and request["process_scope"] == TRACKED_SCOPE,
                  "closed startup-clock profile and exact180 work bound required")
            self._startup_clock_profile = copy.deepcopy(profile)
            self._startup_original_profile = (STARTUP_CLOCK_REQUEST_SCHEMA, 180, 180, 420)
        if live:
            profile = request["live_inventory_profile"]
            _need(type(profile) is dict
                  and set(profile) == {"schema", "max_complete_resamples"}
                  and profile["schema"] == LIVE_INVENTORY_SCHEMA
                  and type(profile["max_complete_resamples"]) is int
                  and profile["max_complete_resamples"] == 1,
                  "invalid frozen live inventory profile")
            self._live_inventory_profile = copy.deepcopy(profile)
        if scratch:
            profile = request["ordinary_scratch_profile"]
            _need(type(profile) is dict and set(profile) == {"schema"}
                  and profile["schema"] == ORDINARY_SCRATCH_PROFILE_SCHEMA,
                  "invalid frozen ordinary scratch profile")
            self._ordinary_scratch_profile = copy.deepcopy(profile)
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
        if physical:
            self._configure_physical_profile()

    def _configure_physical_profile(self):
        (self._physical_profile, self._physical_cases,
         self._physical_entries) = _parse_physical_fixture_profile(self.request, self.directory)

    def _prepare_physical_fixtures(self):
        if self._physical_profile is None:
            return
        root = Path(self._physical_profile["root"])
        for path in (root, *self._physical_cases.values()):
            path.mkdir(mode=0o700)
            info = path.lstat()
            identity = (info.st_dev, info.st_ino, info.st_uid, info.st_mode)
            _need(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
                  and stat.S_IMODE(info.st_mode) == 0o700,
                  "physical fixture directories must be private and owned")
            self._physical_identities[path] = identity
            _fsync_directory(path)
        _fsync_directory(root.parent)
        self._physical_active = True

    def _live_inventory_boundary(self, attempt):
        """Opt-in live source/deadline, cancellation and root-return fence.

        Cancellation uses the original lease inspection; it does not renew,
        acquire or reset a native grant. Native/filesystem IO retains its
        original sampled, non-hard-realtime scope.
        """
        self.guard()
        _need(not self.cancelled, "native validation custody was lost during live census")
        _need(host._root_identity(attempt) == self.identity,
              "validation attempt identity changed")
        self.guard()

    def _local_observation_scope(self):
        return (id(self), self._owner_identity["pid"], self._owner_identity["birth"],
                self.reservation_id, self.request_sha256,
                None if self._record is None else self._record.get("native_lease_id"))

    def _new_local_observation_stop(self, finished_event):
        """Bind the existing CLI event to one V5 watcher, without a new owner."""
        self.guard()
        _need(self._ordinary_scratch_profile is not None,
              "local observation stop requires the explicit ordinary-scratch profile")
        _need(type(finished_event) is threading.Event and not finished_event.is_set(),
              "original unset local observation finished event required")
        _need(self._local_observation_stop is None, "one local observation stop per owner required")
        token = _LocalValidationObservationStop(self._local_observation_scope(), finished_event)
        self._local_observation_stop = token
        return token

    def _validate_local_observation_stop(self, token, *, observing=False):
        _need(type(token) is _LocalValidationObservationStop and token is self._local_observation_stop,
              "original owner-bound local observation stop required")
        _need(os.getpid() == self._owner_identity["pid"],
              "local observation stop belongs to the actual original owner process")
        _need(token._scope == self._local_observation_scope(),
              "local observation stop owner/request/native identity differs")
        if observing:
            current = threading.current_thread()
            with token._transition_lock:
                if token._observer_thread is None:
                    token._observer_thread = current
                _need(token._observer_thread is current, "one original local observation thread required")
        return token

    def _local_observation_stage(self, token, stage):
        if token is None:
            return
        self._validate_local_observation_stop(token, observing=True)
        if token._stage[0] != stage:
            token._stage = (stage, time.monotonic())

    def _local_observation_diagnostic(self, token):
        """Bounded memory observations only; never a thread/Native closeout."""
        self._validate_local_observation_stop(token)
        stage, started = token._stage
        return {"stage": stage, "stage_started_monotonic": started,
                "stage_elapsed_seconds": max(0.0, time.monotonic() - started),
                "zero_process_barrier_observed": token._zero_processes is not None,
                "finished_event_set": token._finished.is_set(),
                "observer_native_thread_id": (None if token._observer_thread is None
                                               else token._observer_thread.native_id)}

    def _stop_local_observation(self, token):
        """Arm stop only through this owner's actual zero-process barrier.

        Publish the proof and the original event together. A watcher noticing
        the permanently closed live window waits for this short transition,
        rather than misclassifying a legitimate shutdown as formal-stop drift.
        """
        self._validate_local_observation_stop(token)
        _need(threading.current_thread() is token._creator_thread,
              "local observation shutdown belongs to the original creator thread")
        with token._transition_lock:
            if token._zero_processes is not None:
                token._finished.set()
                return copy.deepcopy(token._zero_processes)
            self._check_process_owner()
            observation = self._require_processes_stopped()
            _need(observation["live_processes"] == 0, "local observation shutdown requires stopped processes")
            self._validate_local_observation_stop(token)
            token._zero_processes = copy.deepcopy(observation)
            token._finished.set()
            return copy.deepcopy(observation)

    def _check_local_observation_stop(self, token):
        if token is None:
            return
        self._validate_local_observation_stop(token, observing=True)
        with token._transition_lock:
            requested = token._finished.is_set()
            proof = token._zero_processes
        if requested:
            # Current real errors retain priority over a normal observation
            # stop. This neither resets a clock nor renews a native grant.
            self.guard()
            _need(not self.cancelled, "native validation custody was lost during local observation stop")
            _need(proof is not None and proof["live_processes"] == 0
                  and not self._live_inventory_active,
                  "local observation stop lacks verified zero-process proof")
            raise LocalValidationObservationStopped(token)

    def _observation_window_need(self, condition, message, token):
        if not condition and token is not None:
            # Stop closes the exception window while holding the token lock;
            # the check above sees either the complete stop or a real refusal.
            self._check_local_observation_stop(token)
        _need(condition, message)

    def _accept_local_observation_stop(self, error, token):
        self._validate_local_observation_stop(token)
        with token._transition_lock:
            _need(type(error) is LocalValidationObservationStopped and error._observer_stop is token
                  and token._finished.is_set() and token._zero_processes is not None
                  and token._zero_processes["live_processes"] == 0 and not self._live_inventory_active,
                  "unverified local observation stop cannot be accepted")
        return True

    def _usage_inventory(self, attempt, *, _observer_stop=None):
        _need(attempt == self.directory, "physical inventory attempt differs")
        self._check_local_observation_stop(_observer_stop)
        if self._live_inventory_profile is not None or self._ordinary_scratch_profile is not None:
            scratch_live_started = self._ordinary_scratch_profile is not None and self._live_inventory_active
            thread_id = threading.get_ident()
            _need(self._live_inventory_thread != thread_id,
                  "reentrant live census cannot reset the logical census budget")
            # One original absolute deadline covers ALL wait slices and scans.
            # A stopped waiter remains serialized but receives no live retry.
            started = self._admission_started if self._uses_admission_clock() else self._started
            _need(started is not None, "validation clock phase is not established")
            deadline = started + self.validation_timeout_seconds
            acquired = False
            try:
                while not acquired:
                    self._local_observation_stage(_observer_stop, "inventory_serialization_wait")
                    self._check_local_observation_stop(_observer_stop)
                    self._live_inventory_boundary(attempt)
                    if scratch_live_started:
                        self._observation_window_need(self._live_inventory_active,
                            "ordinary scratch live window closed during census wait", _observer_stop)
                    remaining = deadline - time.monotonic()
                    _need(remaining > 0, "validation run deadline exceeded before census wait")
                    acquired = self._live_inventory_lock.acquire(timeout=min(0.1, remaining))
                self._live_inventory_boundary(attempt)
                self._check_local_observation_stop(_observer_stop)
                if scratch_live_started:
                    self._observation_window_need(self._live_inventory_active,
                        "ordinary scratch live window closed after census wait", _observer_stop)
                _need(not self._live_inventory_in_progress
                      and self._live_inventory_thread is None,
                      "live census serialization ownership differs")
                try:
                    self._live_inventory_thread = thread_id
                    self._live_inventory_in_progress = True
                    if self._ordinary_scratch_profile is not None and self._live_inventory_active:
                        self._local_observation_stage(_observer_stop, "ordinary_scratch_inventory")
                        observed = (self._physical_inventory(ordinary_scratch=True) if _observer_stop is None
                                    else self._physical_inventory(ordinary_scratch=True, _observer_stop=_observer_stop))
                        self._live_inventory_boundary(attempt)
                        self._check_local_observation_stop(_observer_stop)
                        self._observation_window_need(self._live_inventory_active,
                            "ordinary scratch live window closed", _observer_stop)
                        return observed
                    if not self._live_inventory_active:
                        self._check_local_observation_stop(_observer_stop)
                        observed = host._inventory([attempt], strict=True)
                        self._live_inventory_boundary(attempt)
                        _need(not self._live_inventory_active,
                              "closed census exception window cannot reopen")
                        return observed
                    highwater = {"apparent_bytes": 0, "entry_count": 0,
                                 "symlink_count": 0, "special_file_count": 0}
                    # Max1 belongs to this logical live census; owner deadline,
                    # claim/lease budgets and cumulative observations never reset.
                    resamples = 0
                    while True:
                        self._live_inventory_boundary(attempt)
                        _need(self._live_inventory_active, "live census exception window is closed")
                        _need(host._root_identity(attempt) == self.identity,
                              "validation attempt identity changed")
                        try:
                            observed = host._inventory(
                                [attempt], strict=True, report_owned_disappearance=True)
                        except host.OwnedInventoryDisappearance as disappeared:
                            self._live_inventory_boundary(attempt)
                            _need(self._live_inventory_active, "live census exception window is closed")
                            _need(host._root_identity(attempt) == self.identity,
                                  "validation attempt identity changed")
                            vanished = Path(disappeared.vanished_path)
                            _need(disappeared.frozen_root == self.identity
                                  and vanished.is_absolute() and attempt in vanished.parents,
                                  "live census disappearance binding differs")
                            observed = disappeared.partial_inventory
                            _need(type(observed) is dict and set(observed) == set(highwater)
                                  and all(type(value) is int and value >= 0
                                          for value in observed.values())
                                  and observed["symlink_count"] == 0
                                  and observed["special_file_count"] == 0,
                                  "invalid live census partial observation")
                            highwater = {key: max(highwater[key], observed[key]) for key in highwater}
                            _need(highwater["apparent_bytes"] <= self.storage_bytes,
                                  "validation aggregate storage limit exceeded")
                            _need(highwater["entry_count"] <= host.MAX_INVENTORY_ENTRIES,
                                  "storage inventory entry bound exceeded")
                            _need(resamples < 1,
                                  "validation live census complete resample exhausted")
                            resamples += 1
                            self._live_inventory_resamples += 1
                            continue
                        self._live_inventory_boundary(attempt)
                        _need(self._live_inventory_active, "live census exception window is closed")
                        _need(host._root_identity(attempt) == self.identity,
                              "validation attempt identity changed")
                        return {key: max(highwater[key], observed[key]) for key in highwater}

                finally:
                    self._live_inventory_in_progress = False
                    self._live_inventory_thread = None
            finally:
                if acquired:
                    self._live_inventory_lock.release()
        if not self._physical_active:
            return host._inventory([attempt], strict=True)
        return self._physical_inventory()

    def _physical_inventory(self, *, ordinary_scratch=False, _observer_stop=None):
        """Sample a private attempt without following declared physical leaves.

        This is a live sample, not an atomic snapshot. Observed bytes remain
        charged when a sampled leaf disappears during cleanup. Only ordinary
        scratch paths may disappear; bound roots and declared target walks stay
        strict. Final durability and sealing use the ordinary strict inventory.
        """
        _need(type(ordinary_scratch) is bool, "ordinary scratch mode must be boolean")
        _need(_observer_stop is None or ordinary_scratch,
              "local observation stop belongs only to ordinary scratch observation")
        self._check_local_observation_stop(_observer_stop)
        if ordinary_scratch:
            self._observation_window_need(self._ordinary_scratch_profile is not None and self._live_inventory_active
                  and self._live_inventory_in_progress
                  and self._live_inventory_thread == threading.get_ident(),
                  "ordinary scratch requires its admitted serialized live window", _observer_stop)
        elif self._physical_profile is None or not self._physical_active:
            return host._inventory([self.directory], strict=True)

        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        uid = os.geteuid()
        directory = Path(self.directory)
        _need(directory.is_absolute() and ".." not in directory.parts,
              "physical inventory requires an absolute plain attempt path")
        expected_directories = {} if ordinary_scratch else self._physical_identities
        cases = set() if ordinary_scratch else set(self._physical_cases.values())
        entries_by_path = {} if ordinary_scratch else self._physical_entries
        _need((not expected_directories and not cases and not entries_by_path) if ordinary_scratch
              else set(expected_directories) == {Path(self._physical_profile["root"]), *cases},
              "physical fixture directory bindings are incomplete")
        observed_directories = set()
        counts = {"apparent_bytes": 0, "entry_count": 0,
                  "symlink_count": 0, "special_file_count": 0}
        ancestors = []

        def checkpoint():
            # Per-step fences are cheap; full Source/root checks surround the
            # serialized scan. Never reset the original productive clock.
            if ordinary_scratch:
                host.native_deadlines._check_resource_operation_deadline()
                if _observer_stop is not None:
                    # A known overage remains a real refusal even if shutdown
                    # races the next observation checkpoint.
                    _need(counts["apparent_bytes"] <= self.storage_bytes,
                          "validation aggregate storage limit exceeded")
                    self._check_local_observation_stop(_observer_stop)
                self._observation_window_need(self._live_inventory_active and self._live_inventory_in_progress
                      and self._live_inventory_thread == threading.get_ident(),
                      "ordinary scratch live window closed during census", _observer_stop)
                _need(not self.cancelled, "native validation custody lost during ordinary scratch census")
                started = self._admission_started if self._uses_admission_clock() else self._started
                _need(started is not None, "validation clock phase is not established")
                _need(time.monotonic() <= started + self.validation_timeout_seconds,
                      "validation run deadline exceeded during ordinary scratch census")
                _need(counts["apparent_bytes"] <= self.storage_bytes,
                      "validation aggregate storage limit exceeded")

        def identity(info):
            return (info.st_dev, info.st_ino, info.st_uid, info.st_mode)

        def owned_directory(info, path):
            if _observer_stop is not None:
                # The stat result is already observed. Do not turn a concrete
                # directory refusal into an expected stop at its checkpoint.
                _need(stat.S_ISDIR(info.st_mode) and info.st_uid == uid
                      and not stat.S_IMODE(info.st_mode) & 0o022,
                      "physical inventory directory must be owned and nonwritable by others")
                if path in expected_directories:
                    _need(identity(info) == expected_directories[path]
                          and stat.S_IMODE(info.st_mode) == 0o700,
                          "physical fixture directory identity changed")
            checkpoint()
            _need(stat.S_ISDIR(info.st_mode) and info.st_uid == uid
                  and not stat.S_IMODE(info.st_mode) & 0o022,
                  "physical inventory directory must be owned and nonwritable by others")
            if path in expected_directories:
                _need(identity(info) == expected_directories[path]
                      and stat.S_IMODE(info.st_mode) == 0o700,
                      "physical fixture directory identity changed")
                observed_directories.add(path)

        def binding(parent_fd, name, descriptor, before):
            checkpoint()
            current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            opened = os.fstat(descriptor)
            _need(identity(current) == identity(before) == identity(opened)
                  and stat.S_ISDIR(current.st_mode),
                  "physical inventory directory binding changed")

        def regular(info):
            _need(stat.S_ISREG(info.st_mode) and info.st_uid == uid
                  and info.st_nlink == 1,
                  "physical inventory requires owned single-link regular files")

        protected_directories = {directory, *self.output_layout.values(),
                                 *expected_directories}

        def protected(path):
            return any(path == bound or path in bound.parents
                       for bound in protected_directories)

        def ordinary_identity(before, after):
            """Allow only private cleanup's owner permission-bit transitions."""
            _need((before.st_dev, before.st_ino, before.st_uid,
                   stat.S_IFMT(before.st_mode)) ==
                  (after.st_dev, after.st_ino, after.st_uid,
                   stat.S_IFMT(after.st_mode)),
                  "physical ordinary entry identity changed")
            _need(not (before.st_mode ^ after.st_mode) & ~0o700,
                  "physical ordinary nonowner permission bits changed")

        def ordinary_disappeared(parent_fd, name, path):
            """Confirm bounded absence without following a replacement leaf."""
            _need(not protected(path),
                  "protected physical directory disappeared")
            for _ in range(2):
                checkpoint()
                try:
                    os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                _need(False, "physical ordinary entry reappeared after disappearance")
            if ordinary_scratch:
                # This counts confirmed absence, never unseen ownership/type.
                self._ordinary_scratch_absences += 1

        def ordinary_binding(parent_fd, name, descriptor, before, path):
            # Root/output/case bindings retain the exact original full identity.
            if protected(path):
                binding(parent_fd, name, descriptor, before)
                return True
            opened = os.fstat(descriptor)
            if _observer_stop is not None:
                ordinary_identity(before, opened)
            owned_directory(opened, path)
            ordinary_identity(before, opened)
            try:
                current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                ordinary_disappeared(parent_fd, name, path)
                return False
            if _observer_stop is not None:
                ordinary_identity(before, current)
                ordinary_identity(opened, current)
            owned_directory(current, path)
            ordinary_identity(before, current)
            ordinary_identity(opened, current)
            return True

        def special_identity(info):
            return (info.st_dev, info.st_ino, info.st_uid, info.st_mode,
                    info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

        def check_target(case_fd, case_path, spec):
            """Walk the declared spelling, never the observed symlink."""
            parts = Path(spec["target"]).parts
            _need(parts and all(part not in ("", ".", "..") for part in parts),
                  "invalid physical target spelling")
            target_path = case_path
            for part in parts:
                target_path /= part
                _need(str(target_path.relative_to(directory)) not in entries_by_path,
                      "physical target traverses a declared special leaf")
            held = []
            parent = case_fd
            current_path = case_path
            try:
                for part in parts[:-1]:
                    current_path /= part
                    before = os.stat(part, dir_fd=parent, follow_symlinks=False)
                    owned_directory(before, current_path)
                    child = os.open(part, flags, dir_fd=parent)
                    held.append((parent, part, child, before))
                    binding(parent, part, child, before)
                    parent = child
                leaf = parts[-1]
                before = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
                if spec["target_kind"] == "directory":
                    owned_directory(before, target_path)
                    child = os.open(leaf, flags, dir_fd=parent)
                    held.append((parent, leaf, child, before))
                    binding(parent, leaf, child, before)
                else:
                    _need(spec["target_kind"] == "file", "invalid physical target kind")
                    regular(before)
                    after = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
                    regular(after)
                    _need(identity(before) == identity(after),
                          "physical symlink target identity changed")
                for parent_fd, name, descriptor, initial in reversed(held):
                    binding(parent_fd, name, descriptor, initial)
            finally:
                for _, _, descriptor, _ in reversed(held):
                    os.close(descriptor)

        def special(parent_fd, name, path, spec, case_fd, case_path):
            """Permit bounded disappearance only at this declared leaf."""
            _need(case_fd is not None and spec["case_path"] == case_path,
                  "physical leaf is outside its bound case")
            expected = None
            initially_missing = False
            for turn in range(2):
                try:
                    before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                except FileNotFoundError:
                    if turn == 0:
                        initially_missing = True
                        continue
                    return expected
                _need(not initially_missing,
                      "physical leaf reappeared after an unbound disappearance")
                _need(before.st_uid == uid and before.st_nlink == 1,
                      "physical leaf must be owned and single-link")
                if spec["kind"] == "symlink":
                    _need(stat.S_ISLNK(before.st_mode), "declared physical symlink changed kind")
                    target_bytes = str(case_path / spec["target"]).encode("utf-8")
                    _need(0 < len(target_bytes) <= 4096
                          and before.st_size == len(target_bytes),
                          "physical symlink target metadata exceeds its exact bounded spelling")
                else:
                    _need(spec["kind"] == "fifo" and stat.S_ISFIFO(before.st_mode),
                          "declared physical FIFO changed kind")
                if expected is not None:
                    _need(special_identity(before) == special_identity(expected),
                          "physical leaf identity changed during cleanup")
                expected = before
                if spec["kind"] == "symlink":
                    try:
                        target = os.readlink(name, dir_fd=parent_fd)
                    except FileNotFoundError:
                        continue
                    _need(target == str(case_path / spec["target"]),
                          "physical symlink target spelling changed")
                    check_target(case_fd, case_path, spec)
                # A FIFO is never opened, read, or followed.
                try:
                    after = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                _need(special_identity(before) == special_identity(after),
                      "physical leaf changed while sampled")
                return after
            try:
                remaining = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                return expected
            _need(expected is not None
                  and special_identity(remaining) == special_identity(expected),
                  "physical leaf substituted during cleanup")
            if spec["kind"] == "symlink":
                try:
                    target = os.readlink(name, dir_fd=parent_fd)
                except FileNotFoundError:
                    try:
                        os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                    except FileNotFoundError:
                        return expected
                    _need(False, "physical leaf reappeared during its final cleanup check")
                _need(target == str(case_path / spec["target"]),
                      "physical symlink target changed during cleanup")
                check_target(case_fd, case_path, spec)
            return remaining

        def walk(descriptor, path, depth, case_fd=None, case_path=None, case_depth=0):
            checkpoint()
            _need(depth <= 32, "physical inventory depth bound exceeded")
            here = os.fstat(descriptor)
            owned_directory(here, path)
            if path in cases:
                _need(case_path is None, "nested physical case directory")
                case_fd, case_path, case_depth = descriptor, path, 0
            if case_path is not None:
                _need(case_depth <= MAX_PHYSICAL_CASE_DEPTH,
                      "physical case depth bound exceeded")
            # scandir consumes a directory offset; open a fresh description.
            scan_fd = os.open(".", flags, dir_fd=descriptor)
            try:
                _need(identity(os.fstat(scan_fd)) == identity(here),
                      "physical scan directory identity changed")
                with os.scandir(scan_fd) as entries:
                    for entry in entries:
                        checkpoint()
                        counts["entry_count"] += 1
                        _need(counts["entry_count"] <= MAX_DURABILITY_ENTRIES,
                              "physical inventory entry bound exceeded")
                        name = entry.name
                        _need(name not in ("", ".", "..") and "/" not in name,
                              "invalid physical inventory entry name")
                        child_path = path / name
                        _need(depth + 1 <= 32, "physical inventory leaf depth bound exceeded")
                        if case_path is not None:
                            _need(case_depth + 1 <= MAX_PHYSICAL_CASE_DEPTH,
                                  "physical case leaf depth bound exceeded")
                        key = str(child_path.relative_to(directory))
                        spec = entries_by_path.get(key)
                        if spec is not None:
                            info = special(descriptor, name, child_path, spec,
                                           case_fd, case_path)
                            if info is not None:
                                counts["apparent_bytes"] += info.st_size
                                counts["symlink_count" if spec["kind"] == "symlink"
                                       else "special_file_count"] += 1
                            continue
                        try:
                            before = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                        except FileNotFoundError:
                            ordinary_disappeared(descriptor, name, child_path)
                            continue
                        if stat.S_ISDIR(before.st_mode):
                            owned_directory(before, child_path)
                            try:
                                child = os.open(name, flags, dir_fd=descriptor)
                            except FileNotFoundError:
                                ordinary_disappeared(descriptor, name, child_path)
                                continue
                            try:
                                if ordinary_binding(descriptor, name, child, before, child_path):
                                    walk(child, child_path, depth + 1, case_fd, case_path,
                                         case_depth + 1 if case_path is not None else 0)
                                    ordinary_binding(descriptor, name, child, before, child_path)
                            finally:
                                os.close(child)
                        else:
                            regular(before)
                            observed_bytes = before.st_size
                            try:
                                after = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                            except FileNotFoundError:
                                ordinary_disappeared(descriptor, name, child_path)
                                counts["apparent_bytes"] += observed_bytes
                                continue
                            regular(after)
                            ordinary_identity(before, after)
                            counts["apparent_bytes"] += max(observed_bytes, after.st_size)
            finally:
                os.close(scan_fd)
            checkpoint()
            after = os.fstat(descriptor)
            if _observer_stop is not None:
                if protected(path):
                    _need(identity(after) == identity(here),
                          "physical directory identity changed while sampled")
                else:
                    ordinary_identity(here, after)
            owned_directory(after, path)
            if protected(path):
                _need(identity(after) == identity(here),
                      "physical directory identity changed while sampled")
            else:
                ordinary_identity(here, after)

        root_fd = os.open("/", flags)
        try:
            parent = root_fd
            for part in directory.parts[1:]:
                before = os.stat(part, dir_fd=parent, follow_symlinks=False)
                _need(stat.S_ISDIR(before.st_mode), "physical attempt ancestor is not a directory")
                child = os.open(part, flags, dir_fd=parent)
                ancestors.append((parent, part, child, before))
                binding(parent, part, child, before)
                parent = child
            walk(parent, directory, 0)
            _need(observed_directories == set(expected_directories),
                  "physical fixture root or case directory disappeared")
            for parent_fd, name, descriptor, before in reversed(ancestors):
                binding(parent_fd, name, descriptor, before)
            checkpoint()
            return counts
        finally:
            for _, _, descriptor, _ in reversed(ancestors):
                os.close(descriptor)
            os.close(root_fd)

    def _guard_inputs(self):
        if (self._startup_original_profile is not None or self.request.get("schema") == STARTUP_CLOCK_REQUEST_SCHEMA
                or self._startup_clock_profile is not None):
            _need(self._startup_original_profile == (STARTUP_CLOCK_REQUEST_SCHEMA, 180, 180, 420)
                  and self.request.get("schema") == STARTUP_CLOCK_REQUEST_SCHEMA
                  and self.request.get("startup_clock_profile") == self._startup_clock_profile == STARTUP_CLOCK_PROFILE
                  and json.dumps(self._startup_clock_profile, sort_keys=True, separators=(",", ":"), allow_nan=False)
                      == json.dumps(STARTUP_CLOCK_PROFILE, sort_keys=True, separators=(",", ":"), allow_nan=False),
                  "startup-clock late opt-in, opt-out or profile retagging is forbidden")
        path, raw, identity = _regular_bytes(self.request_path, MAX_REQUEST_BYTES)
        _need(identity == self._request_identity and hashlib.sha256(raw).hexdigest() == self.request_sha256,
              "frozen validation request changed")
        _need(_decode(raw) == self.request, "in-memory validation request changed")
        if self._startup_original_profile is not None:
            _need(json.dumps(_decode(raw), sort_keys=True, separators=(",", ":"), allow_nan=False)
                  == json.dumps(self.request, sort_keys=True, separators=(",", ":"), allow_nan=False),
                  "startup-clock typed original request changed")
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
        for path, identity in self._physical_identities.items():
            host._safe_path(path, directory=True)
            info = path.lstat()
            _need((info.st_dev, info.st_ino, info.st_uid, info.st_mode) == identity
                  and stat.S_IMODE(info.st_mode) == 0o700,
                  "physical fixture directory identity changed")
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

    def _admission_scope(self):
        """Bind admission to one original epoch; preserve a parent's cleanup end."""
        _need(self._admission_started is not None, "validation admission clock not started")
        work = self._admission_started + self.validation_timeout_seconds
        native = (self._admission_started + 420 if self._startup_original_profile is not None else work)
        previous = host.native_deadlines.resource_operation_deadline()
        if previous is not None:
            work = min(work, previous.work_deadline_monotonic)
            native = (min(native, previous.native_deadline_monotonic)
                      if self._startup_original_profile is not None else previous.native_deadline_monotonic)
        return host.native_deadlines.resource_admission_deadline(
            work_deadline_monotonic=work, native_deadline_monotonic=native)

    def open(self):
        if self._startup_original_profile is not None:
            _need(not self._startup_open_attempted, "startup-clock open is one-shot")
            self._startup_open_attempted = True
        _need(not self._opened and not self._opening and self._started is None,
              "validation resources are already open")
        if self._admission_started is None:
            self._admission_started = time.monotonic()
        self._opening = True
        try:
            # Preserve the original pure input validation on every attempt;
            # it consumes this same admission epoch and cannot renew it.
            self._guard_inputs()
            with self._admission_scope():
                host.native_deadlines._check_resource_operation_deadline()
            # The base owns its original admission scope AND post-scope failure
            # cleanup. An outer scope here could block native retirement when
            # the original work deadline expires after a grant was acquired.
            super().__enter__()
            self._opened = True
            # Complete SDK setup under the SAME original admission epoch.
            # Neither this scope nor live census waits receive a fresh budget.
            with self._admission_scope():
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
                self._prepare_physical_fixtures()
                _fsync_directory(self.directory)
                if self._live_inventory_profile is not None or self._ordinary_scratch_profile is not None:
                    self._live_inventory_active = True
                self.check_limits()
                host.native_deadlines._check_resource_operation_deadline()
            # The productive epoch is published once, after all successful
            # open/setup checks and their original admission scope have closed.
            if self._startup_original_profile is None:
                self._started = time.monotonic()
        except BaseException:
            # Cleanup starts after the SDK admission scope has exited. If a
            # caller declared a later original native end, use only that
            # existing stopped-cleanup clock; never renew either epoch.
            failure_info = sys.exc_info()
            if self._opened:
                try:
                    with self._admission_cleanup_scope():
                        self.__exit__(*failure_info)
                except BaseException as cleanup:
                    # An already expired native end can refuse scope entry.
                    # Preserve the primary failure and the unresolved claim.
                    self._cleanup_error = type(cleanup).__name__
            raise
        finally:
            self._opening = False
        return self

    __enter__ = open

    def guard(self):
        """Verify only local frozen inputs, owner, paths and run deadline."""
        _need(self._opened and self._record is not None and self._record["status"] != "released",
              "validation resource reservation is not open")
        self._verify_owner_roots()
        self._guard_inputs()
        self._guard_startup_clock_contract()
        started = self._admission_started if self._uses_admission_clock() else self._started
        _need(started is not None, "validation clock phase is not established")
        if self._uses_admission_clock():
            host.native_deadlines._check_resource_operation_deadline()
        _need(time.monotonic() - started <= self.validation_timeout_seconds,
              "validation admission deadline exceeded" if self._uses_admission_clock() else
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
        # Ambient metadata cannot opt a legacy run into the fixture profile.
        values.pop(PHYSICAL_REQUEST_ENV, None)
        values.pop(PHYSICAL_REQUEST_SHA_ENV, None)
        if self._physical_profile is not None:
            values[PHYSICAL_REQUEST_ENV] = str(self.request_path)
            values[PHYSICAL_REQUEST_SHA_ENV] = self.request_sha256
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
        if self._startup_original_profile is None:
            return self._attach_child_observed(child_pid)
        self.guard()
        _need(self._started is None and not self._startup_attachment_attempted,
              "startup-clock attachment is one-shot before work")
        self._startup_attachment_attempted = True
        with self._admission_scope():
            value = self._attach_child_observed(child_pid)
            self.guard()
            host.native_deadlines._check_resource_operation_deadline()
            self._startup_attachment_ready = True
            return value

    def _attach_child_observed(self, child_pid):
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
        # This formal zero-process barrier permanently closes the exception
        # before sealing/final checks. Even an in-progress census must refuse
        # at its next guard boundary; failed sealing cannot reopen the window.
        if self._live_inventory_profile is not None or self._ordinary_scratch_profile is not None:
            self._live_inventory_active = False
        return observation

    def to_dict(self):
        value = super().to_dict()
        if self.tracks_descendants:
            value["process_observation"] = copy.deepcopy(self._last_process_observation)
        if self._live_inventory_profile is not None:
            value["live_inventory_profile"] = {
                **copy.deepcopy(self._live_inventory_profile),
                "request_sha256": self.request_sha256,
                "complete_resamples_observed": self._live_inventory_resamples,
                "live_exception_active": self._live_inventory_active,
                "resample_limit_scope": "per_logical_live_census",
            }
        if self._ordinary_scratch_profile is not None:
            value["ordinary_scratch_profile"] = {
                **copy.deepcopy(self._ordinary_scratch_profile),
                "request_sha256": self.request_sha256,
                "ordinary_absences_observed": self._ordinary_scratch_absences,
                "live_exception_active": self._live_inventory_active,
                "unseen_leaf_ownership_attested": False,
                "whole_census_resampling": False,
            }
        if self._startup_original_profile is not None:
            value["startup_clock_profile"] = self.startup_clock_observation()
        if self._physical_profile is not None:
            value["physical_fixture_profile"] = {
                "schema": PHYSICAL_FIXTURE_SCHEMA,
                "request_sha256": self.request_sha256,
                "root": self._physical_profile["root"],
                "case_count": len(self._physical_cases),
                "entry_count": len(self._physical_entries),
                "live_special_file_window": self._physical_active,
            }
        return value

    def check_limits(self, *, full=False, _observer_stop=None):
        """Observe local aggregate bytes/RSS/processes; full=True adds real census."""
        _need(type(full) is bool, "full must be a boolean")
        _need(_observer_stop is None or not full, "full validation checks cannot use a local observation stop")
        self._local_observation_stage(_observer_stop, "source_guard")
        self.guard()
        self._check_local_observation_stop(_observer_stop)
        self._local_observation_stage(_observer_stop, "process_observation")
        processes = self.observe_processes()
        group = processes["group_rss"]
        owner = host._process(os.getpid())
        _need(owner is not None, "validation owner telemetry unavailable")
        rss = owner["rss_bytes"] + processes["rss_bytes"]
        _need(rss <= self.memory_mb * 1024 * 1024, "validation owner and child RSS limit exceeded")
        _need(processes["live_processes"] <= self.child_process_slots, "validation child process limit exceeded")
        self._local_observation_stage(_observer_stop, "owned_inventory")
        inventory = (self._usage_inventory(self.directory) if _observer_stop is None
                     else self._usage_inventory(self.directory, _observer_stop=_observer_stop))
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
        self._local_observation_stage(_observer_stop, "closing_source_guard")
        self.guard()
        self._check_local_observation_stop(_observer_stop)
        self._local_observation_stage(_observer_stop, "between_observations")
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
        if self._startup_original_profile is not None:
            self.require_productive_work()
        _need(self._child is not None, "validation results require an attached actual child")
        self._require_processes_stopped()
        # Close the opt-in live exception permanently. Failed sealing cannot
        # reopen it; finalization still uses the original strict owner scan.
        if self._physical_profile is not None or self._ordinary_scratch_profile is not None:
            self._physical_active = False
            host._inventory([self.directory], strict=True)
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
        if self._startup_original_profile is not None:
            self.require_productive_work()
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
        if self._startup_original_profile is not None and self._admission_started is not None:
            _need(type(self._startup_original_profile) is tuple
                  and self._startup_original_profile == (STARTUP_CLOCK_REQUEST_SCHEMA, 180, 180, 420)
                  and type(self._startup_original_profile[0]) is str
                  and all(type(value) is int for value in self._startup_original_profile[1:]),
                  "startup-clock original cleanup profile differs")
            end = self._admission_started + 420
            previous = host.native_deadlines.resource_operation_deadline()
            if previous is not None:
                end = min(end, previous.native_deadline_monotonic)
            with host.native_deadlines.resource_cleanup_deadline(native_deadline_monotonic=end):
                return self._exit_observed_resources(exc_type, exc, traceback)
        return self._exit_observed_resources(exc_type, exc, traceback)

    def _exit_observed_resources(self, exc_type, exc, traceback):
        # Closing/failed-open handling cannot leave a retry window active.
        if self._live_inventory_profile is not None or self._ordinary_scratch_profile is not None:
            self._live_inventory_active = False
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


    def _uses_admission_clock(self):
        return self._opening or (self._startup_original_profile is not None and self._started is None)

    def _guard_startup_clock_contract(self):
        if self._startup_original_profile is None:
            return
        _need(self.request.get("schema") == STARTUP_CLOCK_REQUEST_SCHEMA
              and self.request.get("startup_clock_profile") == self._startup_clock_profile == STARTUP_CLOCK_PROFILE
              and self._startup_open_attempted and self._admission_started is not None,
              "startup-clock frozen request or original epoch differs")
        _need(time.monotonic() <= self._admission_started + 420,
              "startup-clock original total deadline exceeded")
        _need(self._started is None or self._startup_attachment_ready,
              "startup-clock work lacks original verified attachment")

    def startup_clock_observation(self):
        """Original process-local phase DATA; grants no cleanup or source closure."""
        _need(self._startup_original_profile is not None,
              "startup-clock profile was not selected before construction")
        self._guard_inputs()
        admission, productive = self._admission_started, self._started
        return {"schema": "owned-validation-startup-clock-observation/v1",
                "request_sha256": self.request_sha256,
                "profile": copy.deepcopy(self._startup_clock_profile),
                "clock_scope": "original_owner_process_monotonic",
                "admission_started_monotonic": admission,
                "admission_deadline_monotonic": None if admission is None else admission + 180,
                "productive_started_monotonic": productive,
                "productive_deadline_monotonic": None if productive is None else productive + 180,
                "total_deadline_monotonic": None if admission is None else admission + 420,
                "attachment_attempted": self._startup_attachment_attempted,
                "attachment_verified": self._startup_attachment_ready,
                "attached_child": copy.deepcopy(self._child),
                "original_owner": copy.deepcopy(self._owner_identity),
                "original_native_lease_id": None if self._lease is None else self._lease.to_dict()["lease_id"],
                "source_or_storage_release_authorized": False}

    def require_productive_work(self):
        self.guard()
        _need(self._startup_original_profile is None or self._started is not None,
              "startup-clock productive work has not started")
        return True

    def start_productive_work(self, child_pid, child_birth):
        """Publish once after genuine attachment, while the caller's barrier is closed."""
        _need(self._startup_original_profile is not None,
              "startup-clock late opt-in is forbidden")
        with self._process_lock:
            self.guard()
            _need(self._started is None and self._startup_attachment_attempted
                  and self._startup_attachment_ready and self._sealed is None,
                  "startup-clock work publication is one-shot after attachment")
            _need(type(child_pid) is int and child_pid > 0 and type(child_birth) is str
                  and child_birth.isdecimal() and self._child == {"pid": child_pid, "birth": child_birth},
                  "startup-clock original attached PID/birth required")
            with self._admission_scope():
                self.guard()
                current = host._process(child_pid)
                _need(current is not None and current["pid"] == child_pid
                      and current["state"] != "Z"
                      and current["birth"] == child_birth and current["parent_pid"] == os.getpid()
                      and current["group_pid"] == child_pid and self._descendants is not None,
                      "startup-clock original child identity or tracker differs")
                _need(self._record["child"] == self._child and not self.cancelled and self.heartbeat(),
                      "startup-clock original native custody differs")
                host.native_deadlines._check_resource_operation_deadline()
                started = time.monotonic()
                _need(started < self._admission_started + 180,
                      "startup-clock original admission deadline exceeded")
                self._started = started
            return self.startup_clock_observation()



__all__ = ["ValidationResourceReservation", "ValidationResourceError", "REQUEST_SCHEMA", "PHYSICAL_REQUEST_SCHEMA", "RESULT_SCHEMA"]
