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
import sys
import time
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
    def __init__(self, config, policy, expected_digest, parents, *, inspection_only=False):
        _need(type(inspection_only) is bool, "inspection_only must be an explicit bool")
        self._inspection_only = inspection_only
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
    def _locked_state(self, *, persist=True, allow_reconfigure=False, strict_existing=False):
        if self._inspection_only:
            _need(not persist and not allow_reconfigure,
                  "inspection-only scheduler facade cannot mutate or reconfigure state")
            strict_existing = True
        if strict_existing:
            _need(not persist and not allow_reconfigure,
                  "lease inspection requires an existing nonpersistent read")
        with native._resource_thread_lock(self._thread_lock):
            _need(_parents(self.state_path) == self._parents, "native scheduler directory identity changed")
            _need(all(hashlib.sha256(path.read_bytes()).hexdigest() == digest
                      for path, digest in self._sources.items()), "native scheduler producer source changed")
            # Read before opening the lock so missing state never creates a
            # directory or lock. Read again while holding the native lock.
            _read(self.state_path, require_current=False)
            flags = os.O_NOFOLLOW | os.O_NONBLOCK
            flags |= os.O_RDONLY if strict_existing else os.O_CREAT | os.O_RDWR
            descriptor = os.open(self.lock_path, flags, 0o600)
            try:
                info = os.fstat(descriptor)
                _need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "unaliased native scheduler lock required")
                _need(native.fcntl is not None, "native process-safe locking unavailable")
                native._resource_file_lock(descriptor)
                current = self.lock_path.lstat()
                _need((current.st_dev, current.st_ino) == (info.st_dev, info.st_ino)
                      and stat.S_ISREG(current.st_mode) and current.st_nlink == 1
                      and _parents(self.state_path) == self._parents, "native lock or directory identity changed")
                raw, state = _read(self.state_path)
                self._validate_state_configuration(state, allow_reconfigure=False)
                yield state
                if not persist:
                    return
                self._validate_state_configuration(state, allow_reconfigure=False)
                self._persist_locked_state(raw, state)
            finally:
                os.close(descriptor)

    def _persist_locked_state(self, raw, state):
        """Persist under the caller-held native lock after policy validation."""
        _need(not self._inspection_only, "inspection-only scheduler facade cannot persist state")
        current_raw, _ = _read(self.state_path)
        _need(current_raw == raw, "native state changed outside its sibling lock")
        _need(_parents(self.state_path) == self._parents, "native scheduler directory identity changed")
        _need(all(hashlib.sha256(path.read_bytes()).hexdigest() == digest
                  for path, digest in self._sources.items()), "native scheduler producer source changed")
        encoded = json.dumps(state, sort_keys=True, separators=(",", ":"), allow_nan=False)
        _need(len(encoded.encode("utf-8")) <= MAX_STATE_BYTES, "native scheduler state exceeds bound")
        if encoded == raw:
            return
        temporary = self.state_path.with_name(f".{self.state_path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        try:
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


def open_existing_scheduler(state_path, expected_policy_sha256, *, inspection_only=False):
    """Open exactly the selected existing native policy; never grant a lease.

    Both arguments are scalar identities. All persisted typed configuration
    comes from the existing state. Nonpersisted native operational settings
    retain their normal dataclass defaults; no host/profile defaults are used
    to replace stored capacities or safety policy. No global cache is changed.
    inspection_only=True also requires an existing sibling lock and refuses
    all persistent operations on the returned facade. Caller deadline scopes
    still bound opening/locking; filesystem IO is not hard realtime bounded.
    """
    _need(type(inspection_only) is bool, "inspection_only must be an explicit bool")
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
    return _PinnedGlobalResourceScheduler(config, policy, expected_policy_sha256, parents,
        inspection_only=inspection_only)


def _native_capacity_host(config):
    """Observe only the selected native default producer, with scoped pins."""
    proof_source = Path(native.__file__).with_name("proof_resource_safety.py")
    sampler = config.proof_resource_sampler
    producer = sys.modules.get(native.ProofHostResources.__module__)
    _need(sampler is native.collect_proof_host_resources
          and Path(sampler.__code__.co_filename).resolve() == proof_source.resolve()
          and producer is not None and Path(producer.__file__).resolve() == proof_source.resolve(),
          "native capacity telemetry producer differs from selected source")
    _need(not proof_source.is_symlink(), "native proof telemetry source is aliased")
    digest = hashlib.sha256(proof_source.read_bytes()).hexdigest()
    try:
        host = sampler()
    except Exception as error:
        raise ExistingResourceSchedulerError("native capacity telemetry unknown") from error
    _need(hashlib.sha256(proof_source.read_bytes()).hexdigest() == digest,
          "native proof telemetry source changed")
    return host, digest


def expand_idle_process_capacity(state_path, expected_policy_sha256, total_child_process_slots, *, apply=False):
    """Explicit administrative expansion; never used by worker admission.

    The default is a read-only plan. Applying requires an entirely idle existing
    scheduler, known native PID headroom and healthy native proof telemetry.
    Only the child-process capacity changes. History, reservations, pressure
    thresholds and every other policy field are preserved. Old policy bindings
    subsequently refuse; callers must deliberately bind a new facade/spec.
    """
    _need(type(apply) is bool, "apply must be an explicit bool")
    _need(type(total_child_process_slots) is int and total_child_process_slots > 0,
          "positive integer process capacity required")
    facade = open_existing_scheduler(state_path, expected_policy_sha256)
    with facade._locked_state(persist=False) as state:
        previous = deepcopy(state)
        raw, observed = _read(facade.state_path)
        _need(observed == state, "native capacity snapshot changed")
        policy = deepcopy(state["config"])
        _need(total_child_process_slots > policy["total_child_process_slots"], "capacity must strictly increase")
        policy["total_child_process_slots"] = total_child_process_slots
        try:
            config = native.ResourceSchedulerConfig(state_path=facade.state_path, **deepcopy(policy))
            config.validate()
        except (TypeError, ValueError) as error:
            raise ExistingResourceSchedulerError("expanded native typed configuration is invalid") from error
        _need(config.persisted_dict() == policy, "expanded policy cannot be normalized")
        preserved = {key: value for key, value in state.items() if key != "config"}
        report = dict(schema="native-idle-process-capacity-plan/v1", applied=False,
            previous_policy_sha256=expected_policy_sha256, next_policy_sha256=policy_sha256(policy),
            previous_process_slots=state["config"]["total_child_process_slots"],
            requested_process_slots=total_child_process_slots, next_policy=policy,
            preserved_control_sha256=policy_sha256(preserved),
            lease_count=len(state["leases"]), waiter_count=len(state["waiters"]),
            status="held_native_activity", admitted=False, qualified=False)
        backoff = state.get("proof_backoff", {})
        _need(type(backoff) is dict, "native proof backoff shape invalid")
        if backoff:
            until = backoff.get("until")
            _need(type(until) in (int, float) and math.isfinite(until) and until >= 0,
                  "native proof backoff deadline invalid")
        active_backoff = bool(backoff) and backoff["until"] > time.time()
        if state["leases"] or state["waiters"] or state.get("proof_recovery") or active_backoff:
            _need(not apply, "idle scheduler required; leases, waiters or pressure state remain")
            return report
        host, proof_digest = _native_capacity_host(facade.config)
        proof_source = Path(native.__file__).with_name("proof_resource_safety.py")
        facade._sources[proof_source] = proof_digest
        _need(isinstance(host, native.ProofHostResources), "native proof host observation required")
        _need(host.available_pid_tasks is not None, "known native PID headroom required")
        demand = native.PROOF_PID_HEADROOM_TASKS + native.PROOF_PID_TASKS_PER_PROCESS*total_child_process_slots
        _need(host.available_pid_tasks >= demand, "native PID headroom insufficient for expanded capacity")
        _need(host.available_memory_mb >= facade.config.proof_memory_headroom_mb,
              "native memory headroom insufficient")
        for observed, threshold in (
            (host.memory_stall_percent, facade.config.proof_memory_stall_percent),
            (host.cpu_stall_percent, facade.config.proof_cpu_stall_percent),
            (host.io_stall_percent, facade.config.proof_io_stall_percent),
        ):
            _need(observed < threshold, "native proof pressure holds capacity expansion")
        _need(_read(facade.state_path)[0] == raw, "native capacity state changed outside lock")
        report.update(status="ready_explicit_policy_rebind", pid_tasks_required=demand,
            available_pid_tasks=host.available_pid_tasks, available_memory_mb=host.available_memory_mb,
            pressure=dict(memory_full=host.memory_stall_percent, cpu_some=host.cpu_stall_percent,
                          io_full=host.io_stall_percent), proof_source_sha256=proof_digest)
        if apply:
            successor = deepcopy(previous)
            successor["config"] = policy
            _need({key: value for key, value in successor.items() if key != "config"} == preserved,
                  "native control history must remain unchanged")
            facade._persist_locked_state(raw, successor)
            report.update(applied=True, status="applied_requires_explicit_policy_rebind")
        return report


def expand_idle_cpu_pressure_headroom(state_path, expected_policy_sha256, proof_cpu_stall_percent, *, apply=False):
    """Explicit bounded operator change to an idle scheduler's CPU PSI gate.

    This changes only the CPU stall threshold, never capacities or allocation.
    Unlike ordinary admission, this administrative operation evaluates CPU PSI
    against the requested threshold so an old CPU refusal cannot prevent an
    explicitly authorized increase. Memory, IO, PID and proof-safety checks
    remain in force. All existing nonconfiguration state is preserved exactly.
    """
    _need(type(apply) is bool, "apply must be an explicit bool")
    _need(type(proof_cpu_stall_percent) in (int, float)
          and 0 < proof_cpu_stall_percent <= 75 and math.isfinite(proof_cpu_stall_percent),
          "finite plain CPU stall threshold in (0, 75] required")
    requested = float(proof_cpu_stall_percent)
    facade = open_existing_scheduler(state_path, expected_policy_sha256)
    with facade._locked_state(persist=False) as state:
        previous = deepcopy(state)
        raw, observed = _read(facade.state_path)
        _need(observed == state, "native CPU policy snapshot changed")
        policy = deepcopy(state["config"])
        _need(policy["proof_safety_enabled"] is True, "native proof safety must remain enabled")
        _need(policy["proof_resource_profile"] is None, "named proof profiles cannot be changed by this operator")
        _need(requested > policy["proof_cpu_stall_percent"], "CPU stall threshold must strictly increase")
        policy["proof_cpu_stall_percent"] = requested
        try:
            config = native.ResourceSchedulerConfig(state_path=facade.state_path, **deepcopy(policy))
            config.validate()
        except (TypeError, ValueError) as error:
            raise ExistingResourceSchedulerError("expanded native CPU policy is invalid") from error
        _need(config.persisted_dict() == policy, "expanded CPU policy cannot be normalized")
        _need({key: value for key, value in policy.items() if key != "proof_cpu_stall_percent"}
              == {key: value for key, value in state["config"].items() if key != "proof_cpu_stall_percent"},
              "only the CPU stall threshold may change")
        preserved = {key: value for key, value in state.items() if key != "config"}
        report = dict(schema="native-idle-cpu-pressure-headroom-plan/v1", applied=False,
            previous_policy_sha256=expected_policy_sha256, next_policy_sha256=policy_sha256(policy),
            previous_cpu_stall_percent=state["config"]["proof_cpu_stall_percent"],
            requested_cpu_stall_percent=requested, next_policy=policy,
            changed_policy_fields=["proof_cpu_stall_percent"],
            preserved_control_sha256=policy_sha256(preserved),
            lease_count=len(state["leases"]), waiter_count=len(state["waiters"]),
            status="held_native_activity", admitted=False, qualified=False,
            resource_allocation_performed=False)
        backoff = state.get("proof_backoff", {})
        _need(type(backoff) is dict, "native proof backoff shape invalid")
        if backoff:
            until = backoff.get("until")
            _need(type(until) in (int, float) and math.isfinite(until) and until >= 0,
                  "native proof backoff deadline invalid")
        active_backoff = bool(backoff) and backoff["until"] > time.time()
        if state["leases"] or state["waiters"] or state.get("proof_recovery") or active_backoff:
            _need(not apply, "idle scheduler required; leases, waiters or pressure state remain")
            return report
        host, proof_digest = _native_capacity_host(facade.config)
        proof_source = Path(native.__file__).with_name("proof_resource_safety.py")
        facade._sources[proof_source] = proof_digest
        _need(isinstance(host, native.ProofHostResources), "native proof host observation required")
        _need(host.available_pid_tasks is not None, "known native PID headroom required")
        demand = (native.PROOF_PID_HEADROOM_TASKS
                  + native.PROOF_PID_TASKS_PER_PROCESS * policy["total_child_process_slots"])
        _need(host.available_pid_tasks >= demand, "native PID headroom insufficient for CPU policy expansion")
        _need(host.available_memory_mb >= facade.config.proof_memory_headroom_mb,
              "native memory headroom insufficient")
        for observed, threshold in (
            (host.memory_stall_percent, facade.config.proof_memory_stall_percent),
            (host.cpu_stall_percent, requested),
            (host.io_stall_percent, facade.config.proof_io_stall_percent),
        ):
            _need(observed < threshold, "native proof pressure holds CPU policy expansion")
        _need(_read(facade.state_path)[0] == raw, "native CPU policy state changed outside lock")
        report.update(status="ready_explicit_policy_rebind", pid_tasks_required=demand,
            available_pid_tasks=host.available_pid_tasks, available_memory_mb=host.available_memory_mb,
            pressure=dict(memory_full=host.memory_stall_percent, cpu_some=host.cpu_stall_percent,
                          io_full=host.io_stall_percent), proof_source_sha256=proof_digest)
        if apply:
            successor = deepcopy(previous)
            successor["config"] = policy
            _need({key: value for key, value in successor.items() if key != "config"} == preserved,
                  "native control history must remain unchanged")
            facade._persist_locked_state(raw, successor)
            report.update(applied=True, status="applied_requires_explicit_policy_rebind")
        return report


__all__ = ["open_existing_scheduler", "expand_idle_process_capacity", "expand_idle_cpu_pressure_headroom",
           "policy_sha256", "ExistingResourceSchedulerError"]
