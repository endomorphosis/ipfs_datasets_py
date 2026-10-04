"""Fresh authenticated lease polls with durable renewal only when due.

This separate helper uses the unchanged scheduler's locks and durable writer.
It neither recovers reservations nor renews a parent. Every poll authenticates
current shared state and checks the complete live ancestry; no successful poll
or file revision is reused as authority. Owners must independently bind this
helper and its immutable snapshot identities against replacement.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import inspect
import math
import os
from pathlib import Path
import threading
import time

from . import resource_scheduler as resources


SCHEDULER_SHA256 = 'f156511991e33d3b4ba523c3c5080ea30d0a53ad8a4dbcccea0487432679a9aa'
MAX_ANCESTORS = 4096
MAX_METADATA_NODES = 8192
_LEASE = resources.ResourceLease
_SCHEDULER = resources.GlobalResourceScheduler
_CONFIG = resources.ResourceSchedulerConfig
_LOCKED_STATE = _SCHEDULER._locked_state
_OWNER_BOOT = resources._owner_boot_id
_OWNER_ALIVE = resources._owner_alive_once
_GETPID = os.getpid
_GETIDENT = threading.get_ident
_TIME = time.time
_ISFINITE = math.isfinite
_COPYSIGN = math.copysign
_PATH_TYPE = type(Path('.'))
_LOCK_TYPE = type(threading.RLock())
_LEASE_FIELDS = ('lease_id', 'lease_key', 'lane', 'cpu_slots', 'memory_mb', 'gpu_memory_mb',
                 'unified_memory_mb', 'child_process_slots', 'requires_gpu', 'parent_lease_id',
                 'owner_pid', 'acquired_at', 'wait_seconds')
_MUTABLE_RECORD_FIELDS = frozenset(('heartbeat_at', 'expires_at', 'cancelled', 'release_requested'))
_EXTERNAL_CONFIG_FIELDS = ('resource_pressure_sampler', 'proof_resource_sampler', 'state_path')


def _source_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


_SOURCE_AT_IMPORT = _source_sha256(__file__)
if _source_sha256(resources.__file__) != SCHEDULER_SHA256:
    raise ValueError('authenticated heartbeat requires the pinned scheduler source')
if resources.fcntl is None:
    raise ValueError('authenticated heartbeat requires the existing POSIX file lock')
_DEPENDENCIES = tuple((module, _source_sha256(module.__file__)) for module in (
    resources, inspect.getmodule(resources.collect_resource_snapshot),
    inspect.getmodule(resources.collect_proof_host_resources)))


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _fingerprint(value):
    if isinstance(value, (staticmethod, classmethod)):
        value = value.__func__
    if isinstance(value, property):
        value = value.fget
    value = getattr(value, '__func__', value)
    functions, seen = [], set()
    while inspect.isfunction(value):
        _require(id(value) not in seen and len(functions) < 16, 'bounded acyclic callable binding required')
        seen.add(id(value))
        functions.append((value, value.__code__, value.__defaults__, value.__kwdefaults__,
                          tuple((name, type(item), item) for name, item in value.__kwdefaults__.items())
                          if value.__kwdefaults__ else ()))
        value = getattr(value, '__wrapped__', None)
    return tuple(functions)


def _same_callable(value, expected):
    observed = _fingerprint(value)
    return (len(observed) == len(expected) and all(
        left[0] is right[0] and left[1] is right[1] and left[2] is right[2]
        and left[3] is right[3] and left[4] == right[4]
        for left, right in zip(observed, expected)))


def _implementation_check():
    _require(_source_sha256(__file__) == _SOURCE_AT_IMPORT
             and all(_source_sha256(module.__file__) == digest for module, digest in _DEPENDENCIES),
             'authenticated heartbeat or dependency source changed')
    _require(all(globals().get(name) is expected for name, expected in _ALIASES)
             and all(_same_callable(globals().get(name), expected) for name, expected in _OWN_FUNCTIONS),
             'authenticated heartbeat helper binding changed')
    _require(resources.ResourceLease is _LEASE and resources.GlobalResourceScheduler is _SCHEDULER
             and resources.ResourceSchedulerConfig is _CONFIG
             and all(getattr(module, name) is function and _same_callable(function, expected)
                     for module, name, function, expected in _DEPENDENCY_FUNCTIONS)
             and all(_same_callable(owner.__dict__.get(name), expected)
                     for owner, name, expected in _METHODS),
             'authenticated heartbeat scheduler/class/method binding changed')
    _require(all(getattr(owner, name) is expected for owner, name, expected in _PRIMITIVES),
             'authenticated heartbeat scheduler primitive binding changed')
    _require(all(_same_callable(getattr(owner, name), expected)
                 for owner, name, expected in _PRIMITIVE_FUNCTIONS),
             'authenticated heartbeat scheduler primitive code/default binding changed')
    _require(all(getattr(resources, name) is expected for name, expected in _SCHEDULER_ALIASES),
             'authenticated heartbeat scheduler dependency binding changed')
    _require(all(set(vars(owner)) == {name for name, _ in names}
                 and all(vars(owner)[name] is value for name, value in names)
                 for owner, names in _CLASS_NAMESPACES),
             'authenticated heartbeat class namespace binding changed')


def inference_implementation():
    _implementation_check()
    return {'schema': 'authenticated-lease-heartbeat-implementation/v1',
            'source_sha256': _SOURCE_AT_IMPORT, 'scheduler_source_sha256': SCHEDULER_SHA256,
            'comparison': 'fresh_locked_authenticated_lease_and_complete_current_ancestry',
            'nondue_state_lock_persist': False, 'renewal_fraction_default': 1 / 3,
            'renewal_fraction_maximum': .5, 'max_ancestors': MAX_ANCESTORS,
            'due_policy': 'shared_heartbeat_at_plus_fixed_initial_TTL_times_fraction',
            'due_writer_reauthenticates_and_rechecks_expiry_cancellation_ancestry_and_cadence': True,
            'helper_mutation_scope': 'own_lease_heartbeat_at_and_expires_at_only',
            'inherited_writer_configuration_validation_retained': True,
            'writer_durability': 'unchanged_scheduler_file_fsync_replace_directory_fsync',
            'unrelated_recovery_performed': False, 'parent_renewal_or_release_performed': False,
            'live_reservations_pruned_or_freed': False, 'existing_auto_heartbeat_modified': False,
            'check_return': 'renewed_bool_false_is_a_valid_nondue_poll_refusals_raise',
            'success_or_revision_cached': False, 'performance_qualified': False,
            'proof_authority': False, 'execution_attestation': False, 'production_qualified': False}


def _freeze_metadata(value, budget=None, depth=0):
    if budget is None:
        budget = [MAX_METADATA_NODES]
    budget[0] -= 1
    _require(budget[0] >= 0 and depth <= 64, 'bounded ordinary lease metadata required')
    kind = type(value)
    if kind is dict:
        _require(all(type(key) is str for key in value), 'ordinary string metadata keys required')
        return dict, tuple((key, _freeze_metadata(value[key], budget, depth + 1)) for key in sorted(value))
    if kind in (list, tuple):
        return kind, tuple(_freeze_metadata(item, budget, depth + 1) for item in value)
    _require(kind in (type(None), bool, int, float, str)
             and (kind is not float or _ISFINITE(value)), 'finite builtin lease metadata required')
    # Retain exact numeric type and the sign of a zero in configuration data.
    if kind is float and value == 0:
        return float, value, _COPYSIGN(1, value)
    return kind, value


def _lease_binding(lease):
    values = tuple(getattr(lease, name) for name in _LEASE_FIELDS)
    _require(type(values[0]) is str and 0 < len(values[0]) <= 1024
             and type(values[1]) is str and 0 < len(values[1]) <= 1024,
             'nonempty exact lease ID and key required')
    _require(type(lease.owner_pid) is int and lease.owner_pid == _GETPID()
             and type(lease._released) is bool and lease._released is False,
             'live lease must belong to this process')
    return _freeze_metadata(values)


def _configuration(scheduler):
    config = scheduler.config
    _require(type(config) is _CONFIG and type(config.lease_ttl_seconds) in (int, float)
             and _ISFINITE(config.lease_ttl_seconds) and config.lease_ttl_seconds > 0,
             'exact scheduler configuration with finite positive TTL required')
    _require(all(_same_callable(getattr(config, name), expected) for name, expected in _CONFIG_METHODS),
             'authenticated heartbeat configuration instance method binding changed')
    _require(type(config.state_path) in (str, _PATH_TYPE) and type(config.lane_reservations) is dict,
             'ordinary scheduler paths and lane reservations required')
    # Validate raw values before persisted_dict normalizes reservations. An
    # exact facade must not admit an exotic nested conversion callback here.
    ordinary = {name: value for name, value in vars(config).items()
                if name not in _EXTERNAL_CONFIG_FIELDS and name != 'lane_reservations'}
    ordinary['lane_reservations'] = {
        name: vars(value) if type(value) is resources.LaneReservation else value
        for name, value in config.lane_reservations.items()}
    _freeze_metadata(ordinary)
    return _freeze_metadata({'persisted': config.persisted_dict(),
        'state_path': str(config.state_path), 'lease_ttl_seconds': config.lease_ttl_seconds,
        'resolved_state_path': str(scheduler.state_path), 'lock_path': str(scheduler.lock_path),
        'poll_interval_seconds': config.poll_interval_seconds, 'auto_renew_leases': config.auto_renew_leases})


def _scheduler_binding(scheduler):
    _require(type(scheduler.state_path) is _PATH_TYPE and type(scheduler.lock_path) is _PATH_TYPE
             and type(scheduler._thread_lock) is _LOCK_TYPE,
             'exact scheduler path and thread lock objects required')
    return (scheduler.config, scheduler.state_path, scheduler.lock_path, scheduler._thread_lock,
            *(getattr(scheduler.config, name) for name in _EXTERNAL_CONFIG_FIELDS))


def _object_check(lease, scheduler, lease_binding, scheduler_binding, config_binding):
    _require(type(lease) is _LEASE and type(scheduler) is _SCHEDULER and lease._scheduler is scheduler
             and _lease_binding(lease) == lease_binding,
             'authenticated heartbeat lease object or immutable binding changed')
    actual = _scheduler_binding(scheduler)
    _require(len(actual) == len(scheduler_binding) and all(left is right for left, right in zip(actual, scheduler_binding))
             and _configuration(scheduler) == config_binding,
             'authenticated heartbeat scheduler/configuration binding changed')
    _require(all(_same_callable(getattr(scheduler, name), expected) for name, expected in _RESOLVED_METHODS),
             'authenticated heartbeat scheduler instance method binding changed')
    _require(all(_same_callable(getattr(scheduler.config, name), expected) for name, expected in _CONFIG_METHODS),
             'authenticated heartbeat configuration instance method binding changed')


def _record_binding(record):
    return _freeze_metadata({name: value for name, value in record.items() if name not in _MUTABLE_RECORD_FIELDS})


def _validate_locked(lease, scheduler, state, *, expected_ancestry=None):
    _require(type(state) is dict and type(state.get('leases')) is dict, 'ordinary shared lease state required')
    identifier, key = lease.lease_id, lease.lease_key
    record = state['leases'].get(identifier)
    if record is None:
        raise resources.LeaseNotFoundError('authenticated lease no longer exists')
    if type(record) is not dict or type(record.get('lease_key')) is not str or record.get('lease_key') != key:
        raise resources.LeaseNotFoundError('lease authority does not match')
    for name in _LEASE_FIELDS:
        expected = getattr(lease, name)
        actual = record.get(name, 0 if name in ('gpu_memory_mb', 'unified_memory_mb', 'child_process_slots')
                            else False if name == 'requires_gpu' else 0.0 if name == 'wait_seconds' else None)
        _require(_freeze_metadata(actual) == _freeze_metadata(expected), 'shared owner lease metadata differs')
    now = _TIME()
    _require(type(now) in (float, int) and _ISFINITE(now), 'finite wall clock required')
    seen, ancestry, observations = set(), [], {}
    current_boot = _OWNER_BOOT()
    while record is not None:
        _require(len(ancestry) < MAX_ANCESTORS, 'bounded lease ancestry required')
        _require(type(record) is dict and type(record.get('lease_id')) is str
                 and record['lease_id'] == identifier and type(record.get('lease_key')) is str
                 and bool(record['lease_key']), 'ordinary exact ancestor ID/key required')
        if identifier in seen:
            raise resources.LeaseCancelledError('lease ancestry cycle is cancelled')
        seen.add(identifier)
        expires = record.get('expires_at', 0.0)
        _require(type(expires) in (int, float) and _ISFINITE(expires), 'finite ancestor expiry required')
        if (expires <= now or not _OWNER_ALIVE(record, observations, current_boot=current_boot)
                or record.get('cancelled') or record.get('release_requested')):
            raise resources.LeaseCancelledError('lease or ancestor is expired, cancelled, released or dead')
        ancestry.append((identifier, _record_binding(record)))
        parent = record.get('parent_lease_id')
        if not parent:
            break
        _require(type(parent) is str, 'ordinary ancestor parent ID required')
        identifier = parent
        record = state['leases'].get(parent)
    if record is None:
        raise resources.LeaseCancelledError('lease ancestor is missing')
    ancestry = tuple(ancestry)
    _require(expected_ancestry is None or ancestry == expected_ancestry,
             'immutable lease ancestry metadata changed')
    return state['leases'][lease.lease_id], ancestry, now


def _due(record, now, interval):
    heartbeat = record.get('heartbeat_at')
    _require(type(heartbeat) in (int, float) and _ISFINITE(heartbeat), 'finite shared heartbeat required')
    return now - heartbeat >= interval


class _NoRenewalNeeded(Exception):
    """Abort the writer context without persistence after a cadence race."""


@dataclass(frozen=True, slots=True, init=False, repr=False)
class AuthenticatedLeaseHeartbeat:
    """Owned exact-object authority with immutable initial metadata anchors."""
    _lease: object
    _scheduler: object
    _lease_binding: tuple
    _scheduler_binding: tuple
    _config_binding: tuple
    _ancestry: tuple
    _renewal_fraction: float
    _interval: float
    _process: int
    _thread: int

    def __init__(self, lease, *, renewal_fraction=1 / 3):
        _CHECK_AT_IMPORT()
        _require(type(lease) is _LEASE and type(lease._scheduler) is _SCHEDULER,
                 'exact ResourceLease and GlobalResourceScheduler required')
        _require(type(renewal_fraction) is float and _ISFINITE(renewal_fraction) and 0 < renewal_fraction <= .5,
                 'finite plain-float renewal fraction in (0, .5] required')
        scheduler = lease._scheduler
        lease_binding, scheduler_binding = _lease_binding(lease), _scheduler_binding(scheduler)
        config_binding = _configuration(scheduler)
        interval = float(scheduler.config.lease_ttl_seconds) * renewal_fraction
        _require(_ISFINITE(interval) and interval > 0, 'finite positive renewal interval required')
        _object_check(lease, scheduler, lease_binding, scheduler_binding, config_binding)
        with _LOCKED_STATE(scheduler, persist=False) as state:
            _, ancestry, _ = _validate_locked(lease, scheduler, state)
        # No later poll accepts an uninitialized/None anchor or lazily admits
        # a replacement. Session owners retain independent identities too.
        for name, value in (('_lease', lease), ('_scheduler', scheduler), ('_lease_binding', lease_binding),
                            ('_scheduler_binding', scheduler_binding), ('_config_binding', config_binding),
                            ('_ancestry', ancestry), ('_renewal_fraction', renewal_fraction), ('_interval', interval),
                            ('_process', _GETPID()), ('_thread', _GETIDENT())):
            object.__setattr__(self, name, value)

    @property
    def inference_implementation(self):
        return _IMPLEMENTATION_AT_IMPORT()

    def _object_check(self):
        _CHECK_AT_IMPORT()
        _require(type(self) is AuthenticatedLeaseHeartbeat and type(self._process) is int
                 and _GETPID() == self._process and type(self._thread) is int
                 and _GETIDENT() == self._thread and type(self._ancestry) is tuple and self._ancestry
                 and type(self._lease_binding) is tuple and type(self._scheduler_binding) is tuple
                 and type(self._config_binding) is tuple and type(self._renewal_fraction) is float
                 and _ISFINITE(self._renewal_fraction) and 0 < self._renewal_fraction <= .5
                 and type(self._interval) is float and _ISFINITE(self._interval) and self._interval > 0
                 and self._interval == float(self._scheduler.config.lease_ttl_seconds) * self._renewal_fraction,
                 'authenticated heartbeat owner or snapshot binding changed')
        _object_check(self._lease, self._scheduler, self._lease_binding, self._scheduler_binding, self._config_binding)

    def _read_current(self):
        with _LOCKED_STATE(self._scheduler, persist=False) as state:
            record, _, now = _validate_locked(self._lease, self._scheduler, state, expected_ancestry=self._ancestry)
            due = _due(record, now, self._interval)
        return due

    def check(self):
        """Return whether renewed; a valid nondue poll returns False."""
        self._object_check()
        if not self._read_current():
            return False
        # Release the read lock first. The writer independently authenticates
        # all state after any cancellation, expiry or peer-heartbeat race.
        self._object_check()
        try:
            with _LOCKED_STATE(self._scheduler) as state:
                record, _, now = _validate_locked(self._lease, self._scheduler, state,
                                                  expected_ancestry=self._ancestry)
                if not _due(record, now, self._interval):
                    raise _NoRenewalNeeded
                record['heartbeat_at'] = now
                record['expires_at'] = now + self._scheduler.config.lease_ttl_seconds
        except _NoRenewalNeeded:
            return False
        return True


_IMPLEMENTATION_AT_IMPORT = inference_implementation
_CHECK_AT_IMPORT = _implementation_check
_OWN_FUNCTIONS = tuple((name, _fingerprint(value)) for name, value in list(globals().items())
                       if inspect.isfunction(value) and value.__module__ == __name__)
_ALIASES = tuple((name, globals()[name]) for name in ('resources', '_LEASE', '_SCHEDULER', '_CONFIG',
    '_LOCKED_STATE', '_OWNER_BOOT', '_OWNER_ALIVE', '_GETPID', '_GETIDENT', '_TIME', '_ISFINITE', '_COPYSIGN',
    '_PATH_TYPE', '_LOCK_TYPE',
    '_LEASE_FIELDS', '_MUTABLE_RECORD_FIELDS', '_EXTERNAL_CONFIG_FIELDS', '_IMPLEMENTATION_AT_IMPORT', '_CHECK_AT_IMPORT',
    'AuthenticatedLeaseHeartbeat', '_NoRenewalNeeded', 'SCHEDULER_SHA256', 'MAX_ANCESTORS', 'MAX_METADATA_NODES'))
_DEPENDENCY_FUNCTIONS = tuple((module, name, value, _fingerprint(value))
    for module, _ in _DEPENDENCIES for name, value in vars(module).items()
    if inspect.isfunction(value) and value.__module__ == module.__name__)
_METHODS = tuple((owner, name, _fingerprint(value))
    for owner in (_LEASE, _SCHEDULER, _CONFIG, resources.LaneReservation, AuthenticatedLeaseHeartbeat)
    for name, value in vars(owner).items() if _fingerprint(value))
_RESOLVED_METHODS = tuple((name, _fingerprint(getattr(_SCHEDULER, name))) for name in (
    '_locked_state', '_validate_state_configuration', '_new_state', '_recover_stale_locked'))
_CONFIG_METHODS = tuple((name, _fingerprint(getattr(_CONFIG, name))) for name in (
    'persisted_dict', 'reservations'))
_PRIMITIVES = tuple((owner, name, getattr(owner, name)) for owner, names in (
    (os, ('fsync', 'replace', 'open', 'close', 'kill', 'getpid')),
    (time, ('time',)), (threading, ('get_ident',)),
    (Path, ('open', 'read_bytes', 'read_text', '__new__', '__str__', 'with_name', 'unlink', 'name', 'parent')),
    (_PATH_TYPE, ('open', 'read_bytes', 'read_text', '__getattribute__', '__str__', 'with_name', 'unlink', 'name', 'parent')),
    (hashlib, ('sha256',)), (math, ('isfinite', 'copysign')),
    (resources.json, ('loads', 'dumps')), (resources.fcntl, ('flock', 'LOCK_EX', 'LOCK_UN')),
    (resources.uuid, ('UUID', 'uuid4')), (resources.uuid.UUID, ('__init__', '__str__')),
    (_LEASE, ('__getattribute__',)), (_SCHEDULER, ('__getattribute__',)),
    (_CONFIG, ('__getattribute__',)), (AuthenticatedLeaseHeartbeat, ('__getattribute__',)),
) for name in names)
_PRIMITIVE_FUNCTIONS = tuple((owner, name, _fingerprint(value))
                            for owner, name, value in _PRIMITIVES if _fingerprint(value))
_SCHEDULER_ALIASES = tuple((name, getattr(resources, name)) for name in (
    'os', 'time', 'json', 'threading', 'Path', 'fcntl', 'uuid', 'math', 'contextmanager',
    'ResourceLease', 'GlobalResourceScheduler', 'ResourceSchedulerConfig', 'LaneReservation',
    'RESOURCE_SCHEDULER_SCHEMA_VERSION', 'LeaseCancelledError', 'LeaseNotFoundError', 'SchedulerStateError',
    'ResourceConfigurationError'))
_CLASS_NAMESPACES = tuple((owner, tuple(vars(owner).items())) for owner in (
    _LEASE, _SCHEDULER, _CONFIG, resources.LaneReservation, AuthenticatedLeaseHeartbeat))


__all__ = ['AuthenticatedLeaseHeartbeat', 'inference_implementation']
