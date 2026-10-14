"""Open one existing native scheduler with an exact immutable policy binding.

No global facade is installed, no missing state is initialized, and no policy
is normalized or reconfigured. Admission remains native scheduler admission.
The strict facade uses the native sibling lock and atomic persistence domain.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import uuid

from . import resource_scheduler as native

MAX_STATE_BYTES = 8 * 1024 * 1024


class ExistingResourceSchedulerError(native.SchedulerStateError):
    """The selected existing native control metadata cannot be trusted."""


def _need(condition, message):
    if not condition:
        raise ExistingResourceSchedulerError(message)


def policy_sha256(policy):
    """Digest exactly the stored policy, without filling omitted fields."""
    return hashlib.sha256(json.dumps(policy, sort_keys=True, separators=(",", ":"),
        allow_nan=False).encode("utf-8")).hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _need(key not in result, "duplicate native scheduler JSON field")
        result[key] = value
    return result


def _finite_float(value):
    number = float(value)
    _need(math.isfinite(number), "nonfinite native state")
    return number


def _parents(path):
    """Capture existing directory identities; never follow a symlink/mkdir."""
    result = []
    for parent in reversed((path.parent, *path.parent.parents)):
        info = parent.lstat()
        _need(stat.S_ISDIR(info.st_mode), "existing native scheduler directory required")
        result.append((str(parent), info.st_dev, info.st_ino))
    return tuple(result)


def _read(path, *, require_current=True):
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(path, flags), "rb") as stream:
        before = os.fstat(stream.fileno())
        _need(stat.S_ISREG(before.st_mode) and (before.st_nlink == 1 or (not require_current and before.st_nlink == 0))
              and 0 < before.st_size <= MAX_STATE_BYTES, "bounded unaliased existing native state required")
        raw = stream.read(MAX_STATE_BYTES + 1)
        after = os.fstat(stream.fileno())
    # A native atomic rename can unlink a complete old advisory snapshot and
    # change its ctime. Only the locked read must still name the current inode.
    identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
                            info.st_ctime_ns if require_current else None)
    _need(len(raw) == before.st_size and identity(before) == identity(after), "native state changed while reading")
    if require_current:
        _need(identity(path.lstat()) == identity(after), "native state was replaced while reading")
    try:
        state = json.loads(raw, object_pairs_hook=_pairs, parse_float=_finite_float,
            parse_constant=lambda _: (_ for _ in ()).throw(ExistingResourceSchedulerError("nonfinite native state")))
    except (ValueError, UnicodeError) as error:
        raise ExistingResourceSchedulerError("corrupt native scheduler JSON") from error
    _need(type(state) is dict and type(state.get("config")) is dict, "existing native policy required")
    _need(state.get("schema_version") == native.RESOURCE_SCHEDULER_SCHEMA_VERSION
          and type(state.get("next_sequence")) is int and state["next_sequence"] >= 1
          and all(type(state.get(name)) is dict for name in ("leases", "waiters", "metrics")),
          "existing native control state is malformed")
    for name in ("leases", "waiters"):
        for identity, record in state[name].items():
            _need(type(identity) is str and identity and type(record) is dict
                  and type(record.get("owner_pid")) is int and record["owner_pid"] > 0
                  and type(record.get("lane")) is str and record["lane"], "invalid native lease or waiter record")
            for field in ("cpu_slots", "memory_mb"):
                _need(type(record.get(field)) is int and record[field] >= (1 if field == "cpu_slots" else 0),
                      "invalid native resource envelope")
            for field in ("gpu_memory_mb", "unified_memory_mb", "child_process_slots"):
                _need(type(record.get(field, 0)) is int and record.get(field, 0) >= 0,
                      "invalid native resource envelope")
    return raw.decode("utf-8").strip(), state


class _PinnedGlobalResourceScheduler(native.GlobalResourceScheduler):
    def __init__(self, config, policy, expected_digest, parents):
        # Native __init__ may create parents/reconfigure idle state. Initialize
        # only its facade fields, then enter the same native lock domain.
        self.config = config
        self.config.validate()
        self.state_path = Path(config.state_path)
        self.lock_path = self.state_path.with_name(self.state_path.name + ".lock")
        self._thread_lock = native._path_lock(self.state_path)
        self._policy = deepcopy(policy)
        self._policy_sha256 = expected_digest
        self._parents = parents
        origin = Path(native.__file__)
        _need(origin.resolve() == Path(__file__).with_name("resource_scheduler.py").resolve()
              and not origin.is_symlink(), "native scheduler source escaped its producer tree")
        self._sources = {path: hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in (origin, Path(__file__))}
        with self._locked_state(persist=False):
            pass

    def _new_state(self):
        raise ExistingResourceSchedulerError("selected native scheduler disappeared or is empty")

    def _validate_state_configuration(self, state, *, allow_reconfigure=False):
        stored = deepcopy(state.get("config"))
        _need(stored == self._policy and policy_sha256(stored) == self._policy_sha256,
              "selected native scheduler policy changed")
        # Explicitly refuse reconfiguration even when an inherited method asks
        # for it. Native recovery validation is retained without normalization.
        super()._validate_state_configuration(state, allow_reconfigure=False)
        state["config"] = stored

    @contextmanager
    def _locked_state(self, *, persist=True, allow_reconfigure=False):
        with self._thread_lock:
            _need(_parents(self.state_path) == self._parents, "native scheduler directory identity changed")
            _need(all(hashlib.sha256(path.read_bytes()).hexdigest() == digest
                      for path, digest in self._sources.items()), "native scheduler producer source changed")
            # Read before opening the lock so missing state never creates a
            # directory or lock. Read again while holding the native lock.
            _read(self.state_path, require_current=False)
            descriptor = os.open(self.lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
            temporary = None
            try:
                info = os.fstat(descriptor)
                _need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "unaliased native scheduler lock required")
                _need(native.fcntl is not None, "native process-safe locking unavailable")
                native.fcntl.flock(descriptor, native.fcntl.LOCK_EX)
                current = self.lock_path.lstat()
                _need((current.st_dev, current.st_ino) == (info.st_dev, info.st_ino)
                      and _parents(self.state_path) == self._parents, "native lock or directory identity changed")
                raw, state = _read(self.state_path)
                self._validate_state_configuration(state, allow_reconfigure=False)
                yield state
                if not persist:
                    return
                current_raw, _ = _read(self.state_path)
                _need(current_raw == raw, "native state changed outside its sibling lock")
                self._validate_state_configuration(state, allow_reconfigure=False)
                _need(_parents(self.state_path) == self._parents, "native scheduler directory identity changed")
                _need(all(hashlib.sha256(path.read_bytes()).hexdigest() == digest
                          for path, digest in self._sources.items()), "native scheduler producer source changed")
                encoded = json.dumps(state, sort_keys=True, separators=(",", ":"), allow_nan=False)
                _need(len(encoded.encode("utf-8")) <= MAX_STATE_BYTES, "native scheduler state exceeds bound")
                if encoded == raw:
                    return
                temporary = self.state_path.with_name(f".{self.state_path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
                with temporary.open("x", encoding="utf-8") as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.state_path)
                temporary = None
                directory = os.open(self.state_path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
                os.close(descriptor)


def open_existing_scheduler(state_path, expected_policy_sha256):
    """Open exactly the selected existing native policy; never grant a lease.

    Both arguments are scalar identities. All persisted typed configuration
    comes from the existing state. Nonpersisted native operational settings
    retain their normal dataclass defaults; no host/profile defaults are used
    to replace stored capacities or safety policy. No global cache is changed.
    """
    _need(isinstance(state_path, (str, Path)) and str(state_path), "explicit native state path required")
    _need(type(expected_policy_sha256) is str and re.fullmatch(r"[0-9a-f]{64}", expected_policy_sha256),
          "exact native policy SHA256 required")
    path = Path(os.path.abspath(os.path.expanduser(str(state_path))))
    parents = _parents(path)
    _, state = _read(path, require_current=False)
    policy = state["config"]
    _need(policy_sha256(policy) == expected_policy_sha256, "exact stored native policy required")
    _need(policy.get("proof_safety_enabled") is True, "native proof safety must remain enabled")
    try:
        config = native.ResourceSchedulerConfig(state_path=path, **deepcopy(policy))
        config.validate()
    except (TypeError, ValueError) as error:
        raise ExistingResourceSchedulerError("stored native typed configuration is invalid") from error
    # The pinned native producer defines its own closed inventory. An older
    # producer can accept its exact smaller schema; this producer rejects
    # omissions rather than populating newer policy fields into older state.
    _need(config.persisted_dict() == policy, "stored native policy cannot be normalized")
    return _PinnedGlobalResourceScheduler(config, policy, expected_policy_sha256, parents)


__all__ = ["open_existing_scheduler", "policy_sha256", "ExistingResourceSchedulerError"]
