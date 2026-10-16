"""Live, cooperative resources for one in-process metadata registration.

The canonical persistent store is outside the daemon ledger's named roots.
Its bounded growth is explicit and separate; it is never charged through the
named-root-only ``account_external_bytes`` API. No model/database owner is
imported here. A frozen launcher owns this process group and hard-stop cleanup.
This registration purpose alone uses the native scheduler's existing bounded
60-second admission queue. Its productive deadline starts after the grant;
native pressure vetoes, policy, sampler, lane and resource caps stay unchanged.
"""
from __future__ import annotations

from contextlib import contextmanager
import copy
import fcntl
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import threading
import time

REQUEST_SCHEMA = "model-manager-metadata-registration-resource-request/v1"
PROFILE = "model-manager-in-process-metadata-registration/v1"
GIB = 1024 ** 3
ATTEMPT_BYTES = 4 * GIB
GROWTH_BYTES = 256 * 1024 ** 2
MAX_WAL_BYTES = 128 * 1024 ** 2
STORE = Path("/home/barberb/lift_coding/external/ipfs_accelerate/model_manager.duckdb")
LOCK = Path("/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/federal-corpus-audits/owned-daemon-resource-control/model-manager-registration.lock")
HEX = re.compile(r"[0-9a-f]{64}\Z")
REV = re.compile(r"[0-9a-f]{40}\Z")
MAX_FILES = 4096
ADMISSION_TIMEOUT_SECONDS = 60


class RegistrationResourceError(RuntimeError):
    """The original live registration resource scope is not usable."""


def _need(value, message):
    if not value:
        raise RegistrationResourceError(message)


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def _decode(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            _need(key not in value, "duplicate request field")
            value[key] = item
        return value
    return json.loads(raw, object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(RegistrationResourceError("nonfinite JSON")))


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_uid, info.st_gid, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _path(value, *, directory=False, missing=False):
    _need((type(value) is str or isinstance(value, Path)) and Path(value).is_absolute()
          and ".." not in Path(value).parts, "absolute direct path required")
    path = Path(value)
    for part in (*reversed(path.parents), path):
        try:
            info = part.lstat()
        except FileNotFoundError:
            _need(part == path and missing, "required path disappeared")
            return path
        _need(not stat.S_ISLNK(info.st_mode), "symlink resource path refused")
        if part != path or directory:
            _need(stat.S_ISDIR(info.st_mode), "direct directory required")
        else:
            _need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                  "single-link regular file required")
    return path


def _read(path, *, maximum, digest=None):
    path = _path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
              and 0 < before.st_size <= maximum, "bounded regular input required")
        blocks, count = [], 0
        while True:
            block = os.read(fd, min(65536, maximum + 1 - count))
            if not block:
                break
            count += len(block)
            _need(count <= maximum, "input grew beyond bound")
            blocks.append(block)
        raw = b"".join(blocks)
        _need(len(raw) == before.st_size and _identity(os.fstat(fd)) == _identity(before)
              and _identity(path.lstat()) == _identity(before), "input identity changed")
        _need(digest is None or hashlib.sha256(raw).hexdigest() == digest, "input hash changed")
        return raw, _identity(before)
    finally:
        os.close(fd)


def _leaf(path, *, optional=False):
    path = _path(path, missing=optional)
    try:
        return _identity(path.lstat())
    except FileNotFoundError:
        _need(optional, "persistent store disappeared")
        return None


class ModelManagerRegistrationScope:
    """One actual same-process daemon grant; detached receipts grant nothing.

    The inherited native HAMMER_LEAN/canonical_trainer resource mapping stays
    unchanged. The operation's purpose is metadata registration, with no ML.
    The fixed F07 policy and original named-root ledger are never reconfigured.
    """

    def __init__(self, *, request_path, expected_request_sha256):
        _need(type(expected_request_sha256) is str and HEX.fullmatch(expected_request_sha256),
              "independently pinned resource request required")
        self.request_path = _path(request_path)
        raw, identity = _read(self.request_path, maximum=1024 ** 2, digest=expected_request_sha256)
        request = _decode(raw)
        fields = {"schema", "cwd", "attempt_directory", "ledger_path", "roots",
            "scheduler_state_path", "expected_scheduler_policy_sha256", "memory_mb", "cpu_slots",
            "child_process_slots", "timeout_seconds", "admission_timeout_seconds", "storage_bytes", "attempt_storage_bytes",
            "persistent_store", "source_sha256", "read_only_git_commands"}
        _need(type(request) is dict and set(request) == fields and request["schema"] == REQUEST_SCHEMA,
              "closed metadata registration resource request required")
        _need(request["storage_bytes"] == ATTEMPT_BYTES + GROWTH_BYTES
              and type(request["storage_bytes"]) is int
              and request["attempt_storage_bytes"] == ATTEMPT_BYTES
              and type(request["attempt_storage_bytes"]) is int, "exact backup/growth reservation required")
        _need(type(request["memory_mb"]) is int and 1 <= request["memory_mb"] <= 16384
              and request["cpu_slots"] == 1 and type(request["cpu_slots"]) is int
              and request["child_process_slots"] == 1 and type(request["child_process_slots"]) is int,
              "bounded one-CPU/one-Git-child envelope required")
        seconds = request["timeout_seconds"]
        _need(type(seconds) in (int, float) and math.isfinite(seconds) and 0 < seconds <= 3600,
              "bounded positive operation deadline required")
        _need(type(request["admission_timeout_seconds"]) is int
              and request["admission_timeout_seconds"] == ADMISSION_TIMEOUT_SECONDS,
              "exact native60-second registration admission wait required")
        persistent = request["persistent_store"]
        _need(type(persistent) is dict and set(persistent) == {"path", "wal_path", "writer_lock_path",
            "fallback_json_path", "max_database_bytes", "max_wal_bytes", "max_growth_bytes"},
            "closed external persistent-store scope required")
        _need(persistent == {"path": str(STORE), "wal_path": str(STORE) + ".wal",
            "writer_lock_path": str(LOCK), "fallback_json_path": str(STORE) + ".json",
            "max_database_bytes": ATTEMPT_BYTES, "max_wal_bytes": MAX_WAL_BYTES,
            "max_growth_bytes": GROWTH_BYTES}, "exact canonical store/budgets required")
        self.directory = _path(request["attempt_directory"], directory=True)
        info = self.directory.stat()
        _need(stat.S_IMODE(info.st_mode) == 0o700 and info.st_uid == os.getuid()
              and not list(self.directory.iterdir()), "empty owned0700 attempt required")
        self._attempt_identity = (info.st_dev, info.st_ino, info.st_mode, info.st_uid)
        self.cwd = _path(request["cwd"], directory=True)
        self._cwd_identity = (self.cwd.stat().st_dev, self.cwd.stat().st_ino)
        _need(type(request["roots"]) is list and len(request["roots"]) == 4,
              "the existing four named ledger roots are required")
        self._roots = tuple(_path(p, directory=True) for p in request["roots"])
        _need(any(p in self.directory.parents for p in self._roots)
              and any(p in LOCK.parents for p in self._roots), "attempt/lock must stay inside named roots")
        _need(self.directory not in LOCK.parents and LOCK != self.directory,
              "writer lock must be shared outside the attempt")
        _need(self.request_path != self.directory and self.directory not in self.request_path.parents,
              "frozen request must remain outside attempt")
        sources = request["source_sha256"]
        _need(type(sources) is dict and 0 < len(sources) <= 256, "bounded exact source pins required")
        self._source_identities = {}
        aggregate = 0
        for spelling, digest in sources.items():
            _need(type(spelling) is str and type(digest) is str and HEX.fullmatch(digest),
                  "exact source path/hash required")
            body, witness = _read(spelling, maximum=4 * 1024 ** 2, digest=digest)
            aggregate += len(body)
            _need(aggregate <= 32 * 1024 ** 2, "source cohort exceeds aggregate bound")
            self._source_identities[spelling] = witness
        _need(str(Path(__file__).absolute()) in sources, "this exact resource owner must be source pinned")
        commands = request["read_only_git_commands"]
        _need(type(commands) is list and 0 < len(commands) <= 256, "finite exact Git argv required")
        self._git_commands = set()
        for command in commands:
            _need(type(command) is list and 5 <= len(command) <= 64
                  and all(type(v) is str and v and "\x00" not in v and len(v) <= 4096 for v in command),
                  "bounded Git argv required")
            _need(command[:2] == ["git", "-C"]
                  and command[2] in (str(self.cwd), str(STORE.parent)), "fixed read-only Git roots required")
            operation = command[3:]
            okay = operation == ["rev-parse", "HEAD"]
            if len(operation) == 2 and operation[0] == "show" and ":" in operation[1]:
                revision, relative = operation[1].split(":", 1)
                okay = bool(REV.fullmatch(revision)) and not relative.startswith("/") and ".." not in Path(relative).parts and str(Path(command[2]) / relative) in sources
            if operation and operation[0] == "ls-files":
                okay = operation == ["ls-files", "ipfs_accelerate_py/model_catalog/*.py", "ipfs_accelerate_py/model_catalog/**/*.py"] and command[2] == str(STORE.parent)
            _need(okay, "only explicit pinned source-inspection Git operations are allowed")
            self._git_commands.add(tuple(command))
        _need(len(self._git_commands) == len(commands), "duplicate Git argv refused")
        self._request_raw, self._request_identity = raw, identity
        self._request = copy.deepcopy(request)
        self.request_sha256 = expected_request_sha256
        self._owner_pid = os.getpid()
        self._host = self._owner = self._original_owner = self._owner_birth = None
        self._lock_fd = None
        self._lock_identity = None
        self._store_initial = self._fallback_initial = self._store_parent = None
        self._started = None
        self._opened = self._finished = self._closing = False
        self._fault = None
        self._last_usage = None
        self._sealed = None
        self._git_births = {}
        self._git_call_count = 0
        self._mutex = threading.RLock()
        self._stop = threading.Event()
        self._watchdog = None
        self._native_lease = None
        self._native_scheduler = None

    def _inputs(self):
        raw, identity = _read(self.request_path, maximum=1024 ** 2, digest=self.request_sha256)
        _need(raw == self._request_raw and identity == self._request_identity, "resource request substituted")
        _need((self.cwd.stat().st_dev, self.cwd.stat().st_ino) == self._cwd_identity,
              "registration source root substituted")
        for path, digest in self._request["source_sha256"].items():
            _, identity = _read(path, maximum=4 * 1024 ** 2, digest=digest)
            _need(identity == self._source_identities[path], "resource/source identity substituted")
        info = _path(self.directory, directory=True).stat()
        _need((info.st_dev, info.st_ino, info.st_mode, info.st_uid) == self._attempt_identity,
              "attempt directory substituted")

    def _group(self, *, drained=False):
        owner = self._host._process(self._owner_pid)
        _need(owner is not None and owner["birth"] == self._owner_birth
              and owner["group_pid"] == self._owner_pid, "original owner process group differs")
        usage = self._host._group_usage({"pid": self._owner_pid, "birth": self._owner_birth})
        _need(usage["live_processes"] <= 1 + self._request["child_process_slots"]
              and usage["rss_bytes"] <= self._request["memory_mb"] * 1024 ** 2,
              "metadata owner-group RSS/process limit exceeded")
        entries = list(Path("/proc").iterdir())
        _need(len(entries) <= 100000, "process census bound exceeded")
        for entry in entries:
            if not entry.name.isdecimal() or int(entry.name) == self._owner_pid:
                continue
            item = self._host._process(int(entry.name))
            if item is not None and item["group_pid"] == self._owner_pid and item["state"] != "Z":
                _need(item["parent_pid"] == self._owner_pid, "unexpected descendant process")
                previous = self._git_births.get(item["pid"])
                _need(previous in (None, item["birth"]), "observed Git process identity changed")
                self._git_births[item["pid"]] = item["birth"]
        _need(not drained or usage["live_processes"] == 1, "read-only Git processes must finish first")
        return usage

    def _store(self):
        parent = _path(STORE.parent, directory=True).stat()
        _need((parent.st_dev, parent.st_ino) == self._store_parent, "canonical store parent substituted")
        current = _leaf(STORE)
        _need(current[:6] == self._store_initial[:6], "canonical store physical identity substituted")
        wal = _leaf(str(STORE) + ".wal", optional=True)
        fallback = _leaf(str(STORE) + ".json", optional=True)
        _need(fallback == self._fallback_initial, "forbidden JSON fallback changed")
        wal_bytes = 0 if wal is None else wal[6]
        growth = max(0, current[6] - self._store_initial[6]) + wal_bytes
        _need(0 < current[6] <= ATTEMPT_BYTES and wal_bytes <= MAX_WAL_BYTES
              and growth <= GROWTH_BYTES, "external DB/WAL size or growth bound exceeded")
        _need(self._lock_fd is not None and _identity(os.fstat(self._lock_fd)) == self._lock_identity
              and _leaf(LOCK) == self._lock_identity, "original writer-lock descriptor substituted")
        return {"database_bytes": current[6], "wal_bytes": wal_bytes,
                "growth_plus_wal_bytes": growth, "fallback_JSON_unchanged": True,
                "database_physical_identity_unchanged": True}

    def _audit(self, event, args):
        if not self._opened or self._finished:
            return
        if event == "subprocess.Popen":
            _need(not self._closing and args[0] == "git" and type(args[1]) in (list, tuple)
                  and tuple(args[1]) in self._git_commands, "only frozen read-only Git argv may execute")
            self._git_call_count += 1
        elif event.startswith("socket.") or event in {"os.system", "os.fork", "os.forkpty", "os.posix_spawn", "os.exec"}:
            raise RegistrationResourceError("network or unselected process execution refused")

    def __enter__(self):
        _need(not self._opened and self._owner is None, "registration resources can enter only once")
        self._inputs()
        name = "ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_resources"
        host = importlib.import_module(name)
        expected = self.cwd / "ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py"
        _need(Path(host.__file__).absolute() == expected and str(expected) in self._request["source_sha256"],
              "native daemon resource owner origin differs")
        self._host = host
        process = host._process(self._owner_pid)
        _need(process is not None and process["group_pid"] == self._owner_pid,
              "outer launcher must create this actual owner process group")
        self._owner_birth = process["birth"]
        self._group(drained=True)
        parent = _path(STORE.parent, directory=True).stat()
        self._store_parent = (parent.st_dev, parent.st_ino)
        self._store_initial = _leaf(STORE)
        _need(0 < self._store_initial[6] <= ATTEMPT_BYTES and _leaf(str(STORE) + ".wal", optional=True) is None,
              "bounded quiescent canonical database required")
        self._fallback_initial = _leaf(str(STORE) + ".json", optional=True)
        request = self._request
        owner = host.DaemonResourceReservation(request["ledger_path"], roots=request["roots"],
            storage_bytes=request["storage_bytes"], memory_mb=request["memory_mb"], cpu_slots=1,
            child_process_slots=1, timeout_seconds=request["admission_timeout_seconds"], ledger_lock_timeout_seconds=60,
            scheduler_state_path=request["scheduler_state_path"],
            expected_scheduler_policy_sha256=request["expected_scheduler_policy_sha256"],
            require_existing_ledger=True)
        self._owner = self._original_owner = owner
        owner._attempt = host._root_identity(self.directory)
        owner.__enter__()
        self._native_lease = owner._lease
        self._native_scheduler = owner._lease._scheduler
        self._started = time.monotonic()
        try:
            fd = os.open(LOCK, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            self._lock_fd = fd
            info = os.fstat(fd)
            _need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size == 0
                  and stat.S_IMODE(info.st_mode) == 0o600 and info.st_uid == os.getuid(),
                  "zero-byte owned0600 shared writer lock required")
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._lock_identity = _identity(info)
            self._opened = True
            sys.addaudithook(self._audit)
            self.guard()
            owner.check_usage(self.directory)
            owner._update(registration_profile=PROFILE, resource_request_sha256=self.request_sha256,
                owner_birth=self._owner_birth, native_lease_id=self._native_lease.lease_id,
                scheduler_state_path=request["scheduler_state_path"],
                scheduler_policy_sha256=request["expected_scheduler_policy_sha256"],
                external_store_update_explicit=True, external_store_in_named_root_census=False,
                attempt_byte_limit=ATTEMPT_BYTES, external_growth_reserve_bytes=GROWTH_BYTES)
            self._watchdog = threading.Thread(target=self._watch, name="metadata-registration-guard", daemon=True)
            self._watchdog.start()
            return self
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise

    def _watch(self):
        while not self._stop.wait(2):
            try:
                self.guard()
            except BaseException as error:
                self._fault = type(error).__name__
                return

    def guard(self):
        with self._mutex:
            _need(self._opened and not self._finished and self._owner is self._original_owner,
                  "original live metadata scope required")
            _need(self._fault is None, "metadata watchdog refused further work")
            _need(time.monotonic() - self._started <= self._request["timeout_seconds"],
                  "metadata operation deadline exceeded")
            self._inputs()
            _need(type(self._owner) is self._host.DaemonResourceReservation
                  and self._owner._lease is self._native_lease
                  and self._native_lease._scheduler is self._native_scheduler
                  and not self._owner.cancelled and self._owner.heartbeat(), "native metadata grant lost")
            lease = self._owner._lease
            _need(lease is not None and lease.owner_pid == self._owner_pid
                  and lease.parent_lease_id is None and lease.cpu_slots == 1
                  and lease.memory_mb == self._request["memory_mb"]
                  and lease.child_process_slots == 1 and not lease.requires_gpu,
                  "original native root envelope changed")
            group = self._group()
            persistent = self._store()
            size = self._host._inventory([self.directory], strict=True)["apparent_bytes"]
            _need(size <= ATTEMPT_BYTES and size + persistent["growth_plus_wal_bytes"] <= self._request["storage_bytes"],
                  "owned evidence/external growth budget exceeded")
            self._last_usage = {"attempt_bytes": size, **persistent,
                "owner_group_rss_bytes": group["rss_bytes"], "owner_group_live_processes": group["live_processes"],
                "checked_at": time.time(), "enforcement": "cooperative_sampled_not_kernel_quota"}
            self._inputs()

    def assert_writable_store(self, store):
        _need((type(store) is str or isinstance(store, Path)) and Path(store) == STORE,
              "only the canonical declared database is writable")
        self.guard()

    def snapshot(self):
        return {"schema": "model-manager-metadata-registration-resource-observation/v1", "profile": PROFILE,
            "attempt_directory": str(self.directory), "request_sha256": self.request_sha256,
            "native_admitted": self._opened, "finalized": self._finished,
            "native_resource_mapping": "hammer_lean/canonical_trainer",
            "purpose": "metadata_registration_no_training", "attempt_storage_bytes": ATTEMPT_BYTES,
            "admission_wait_seconds": ADMISSION_TIMEOUT_SECONDS,
            "admission_wait_is_configured_bound": True,
            "conservative_external_growth_reserve_bytes": GROWTH_BYTES,
            "total_storage_reservation_bytes": ATTEMPT_BYTES + GROWTH_BYTES,
            "external_store_in_named_root_census": False,
            "persistent_store": copy.deepcopy(self._request["persistent_store"]),
            "sampled_usage": copy.deepcopy(self._last_usage), "readonly_Git_calls_observed": self._git_call_count,
            "readonly_Git_births_observed": len(self._git_births), "watchdog_refusal": self._fault,
            "process_scope": "actual_owner_process_group_including_owner_once",
            "native_host_child_attachment": None, "observation_is_capability": False,
            "kernel_containment": False, "runtime_ready": False, "teacher_qualified": False,
            "model_loaded": False, "training_executed": False, "proof_authority": False}

    receipt = snapshot

    def _inventory(self):
        rows, total = [], 0
        paths = sorted(self.directory.rglob("*"))
        _need(len(paths) <= MAX_FILES, "durable artifact inventory exceeds bound")
        for path in paths:
            _path(path, directory=path.is_dir())
            if path.is_dir():
                continue
            if path.name == "registration-resource-durability.json" and path.parent == self.directory:
                continue
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
            try:
                before = os.fstat(fd)
                _need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, "regular durable artifact required")
                total += before.st_size
                _need(total <= ATTEMPT_BYTES, "durable evidence exceeds bound")
                digest, count = hashlib.sha256(), 0
                while True:
                    block = os.read(fd, 1024 ** 2)
                    if not block:
                        break
                    count += len(block)
                    _need(count <= before.st_size, "durable artifact grew")
                    digest.update(block)
                os.fsync(fd)
                _need(count == before.st_size and _identity(os.fstat(fd)) == _identity(before)
                      and _identity(path.lstat()) == _identity(before), "durable artifact changed")
                rows.append({"path":path.relative_to(self.directory).as_posix(), "bytes":count,
                             "sha256":digest.hexdigest()})
            finally:
                os.close(fd)
        for directory in [self.directory, *(p for p in paths if p.is_dir())]:
            fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        return rows

    def seal(self, result_path):
        self.guard()
        self._group(drained=True)
        result = _path(result_path)
        _need(self.directory in result.parents and self._sealed is None, "one owned registration result seal required")
        self._closing = True
        # This is an explicit persistent-store operation, separate from the
        # owned evidence inventory. The driver has already closed its genuine
        # writer/readback connections before handing its result to this seal.
        for spelling in (str(STORE), str(STORE) + ".wal"):
            before = _leaf(spelling, optional=spelling.endswith(".wal"))
            if before is not None:
                fd = os.open(spelling, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
                try:
                    _need(_identity(os.fstat(fd)) == before, "persistent-store fsync descriptor differs")
                    os.fsync(fd)
                    _need(_identity(os.fstat(fd)) == before and _leaf(spelling) == before,
                          "persistent store changed during durability check")
                finally:
                    os.close(fd)
        parent_fd = os.open(STORE.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        rows = self._inventory()
        _need(result.relative_to(self.directory).as_posix() in {r["path"] for r in rows}, "result missing from durable inventory")
        payload = {"schema":"model-manager-metadata-registration-durability/v1", "files":rows,
                   "request_sha256":self.request_sha256, "resource_observation":self.snapshot()}
        raw = _wire(payload) + b"\n"
        _need(sum(r["bytes"] for r in rows) + len(raw) <= ATTEMPT_BYTES, "durability receipt exceeds owned budget")
        path = self.directory / "registration-resource-durability.json"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            with os.fdopen(fd, "wb", closefd=False) as stream:
                stream.write(raw); stream.flush(); os.fsync(fd)
        finally:
            os.close(fd)
        parent_fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        pin = {"path":str(path), "bytes":len(raw), "sha256":hashlib.sha256(raw).hexdigest()}
        self._sealed = (rows, pin)
        self.guard()
        self._group(drained=True)
        return copy.deepcopy(pin)

    def finalize(self, *, artifacts_durable=False):
        _need(artifacts_durable is True and self._sealed is not None, "explicit sealed durability required")
        self.guard()
        self._group(drained=True)
        rows, pin = self._sealed
        _need(self._inventory() == rows, "sealed evidence changed")
        _read(pin["path"], maximum=8 * 1024 ** 2, digest=pin["sha256"])
        self.guard()
        self._group(drained=True)
        self._stop.set()
        if self._watchdog is not None:
            self._watchdog.join(timeout=5)
            _need(not self._watchdog.is_alive(), "metadata watchdog did not drain")
        _need(self._owner._child is None, "in-process registration must not invent a native child attachment")
        self._owner.finalize(self.directory, artifacts_durable=True)
        self._finished = True
        self._unlock()
        return self.snapshot()

    def _unlock(self):
        if self._lock_fd is not None:
            fd, self._lock_fd = self._lock_fd, None
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def __exit__(self, exc_type, exc, traceback):
        self._stop.set()
        if self._watchdog is not None:
            self._watchdog.join(timeout=5)
            if self._watchdog.is_alive():
                # Do not race a still-running native guard with ledger updates,
                # lease release or writer-lock removal. The outer launcher must
                # drain/stop its own process group; this claim stays charged.
                self._fault = "metadata_watchdog_not_drained"
                if exc_type is None:
                    raise RegistrationResourceError("metadata watchdog did not drain during cleanup")
                return False
        if self._owner is not None and not self._finished:
            drained = False
            try:
                self._group(drained=True)
                drained = True
                self._owner._retain("metadata_registration_failed" if exc_type else "explicit_durable_finalize_required")
            finally:
                # The base owner's _child is intentionally None. Do not use
                # base __exit__: its child check would miss our actual group.
                if drained:
                    if self._owner._lease is not None:
                        self._owner._lease.release()
                    self._unlock()
        return False
