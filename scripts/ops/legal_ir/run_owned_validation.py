#!/usr/bin/env python3
"""Run explicit trusted checks with one native validation and storage owner.

This sampled process-group profile is not a filesystem quota or containment of
arbitrary descendants. It never grants semantic or Lean admission.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import site
import stat
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[3]
STARTUP_CLOCK_REQUEST_SCHEMA = 'owned-validation-request/v6'
STARTUP_CLOCK_PROFILE = {'schema':'owned-validation-startup-clock/v1',
    'admission_seconds':180,'productive_seconds':180,'total_seconds':420}


def snapshot(path, maximum=1024*1024, *, allow_empty=False):
    if type(allow_empty) is not bool:
        raise ValueError('allow_empty must be an exact bool')
    minimum = 0 if allow_empty else 1
    path = Path(path)
    for parent in (path.parent, *path.parent.parents):
        if not stat.S_ISDIR(parent.lstat().st_mode):
            raise ValueError('input directory is missing or aliased')
    with os.fdopen(os.open(path, os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK), 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not minimum <= before.st_size <= maximum:
            raise ValueError('bounded unaliased regular input required')
        raw = stream.read(maximum+1)
        after = os.fstat(stream.fileno())
    identity = lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    if len(raw) != before.st_size or identity(before) != identity(after) or identity(after) != identity(path.lstat()):
        raise ValueError('input changed while reading')
    return raw


def request(path, digest):
    raw = snapshot(path)
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('request hash differs')
    value = json.loads(raw)
    if value.get('schema') not in ('owned-validation-request/v1', 'owned-validation-request/v2', 'owned-validation-request/v4', 'owned-validation-request/v5', STARTUP_CLOCK_REQUEST_SCHEMA):
        raise ValueError('unsupported validation request')
    if value["schema"] == STARTUP_CLOCK_REQUEST_SCHEMA and not _startup_clock_no_child_request_shape(value, raw):
        raise ValueError("closed startup-clock request differs")
    return value, raw


def source_guard(value):
    pins = value['source_sha256']
    if type(pins) is not dict or not pins:
        raise ValueError('explicit validation source pins required')
    for path, digest in pins.items():
        if hashlib.sha256(snapshot(path, 4*1024*1024, allow_empty=True)).hexdigest() != digest:
            raise ValueError('validation source changed: '+path)


def immutable_json(path, value):
    raw = json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode()+b'\n'
    descriptor = os.open(path, os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    parent = os.open(Path(path).parent, os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)


def report_capacity_refusal(error, *, stage="owner.open"):
    """Best-effort aggregate diagnostic; stage grants no lifecycle authority."""
    try:
        if type(stage) is not str or stage not in ("owner.open", "post_owner_open"):
            return False
        message = 'storage reservation capacity exceeded'
        if (type(error).__name__ != 'DaemonResourceError'
                or type(error.args) is not tuple or len(error.args) != 1
                or type(error.args[0]) is not str
                or error.args != (message,) or str(error) != message):
            return False
        observation = error.capacity_observation
        integer_fields = ('observed_apparent_bytes', 'outstanding_full_reservations_bytes',
            'additional_requested_bytes', 'charged_bytes', 'limit_bytes',
            'minimum_filesystem_free_bytes', 'storage_capacity_deficit_bytes',
            'filesystem_free_deficit_bytes')
        boolean_fields = ('storage_capacity_exceeded', 'filesystem_free_insufficient')
        if (type(observation) is not dict
                or any(type(key) is not str for key in observation)
                or set(observation) != {'schema', 'scope', *integer_fields, *boolean_fields}
                or type(observation['schema']) is not str
                or observation['schema'] != 'daemon-resource-capacity-observation/v1'
                or type(observation['scope']) is not str
                or observation['scope'] != 'named_roots_only_apparent_bytes'
                or any(type(observation[key]) is not int
                       or not 0 <= observation[key] < 2**63 for key in integer_fields)
                or any(type(observation[key]) is not bool for key in boolean_fields)):
            return False
        requested = (observation['outstanding_full_reservations_bytes']
                     + observation['additional_requested_bytes'])
        charged = observation['observed_apparent_bytes'] + requested
        storage_deficit = max(0, charged - observation['limit_bytes'])
        filesystem_deficit = max(0, requested - observation['minimum_filesystem_free_bytes'])
        if (observation['charged_bytes'] != charged
                or observation['storage_capacity_deficit_bytes'] != storage_deficit
                or observation['filesystem_free_deficit_bytes'] != filesystem_deficit
                or observation['storage_capacity_exceeded'] is not (storage_deficit > 0)
                or observation['filesystem_free_insufficient'] is not (filesystem_deficit > 0)
                or not (storage_deficit > 0 or filesystem_deficit > 0)):
            return False
        raw = json.dumps(dict(schema='owned-validation-capacity-refusal/v1',
            stage=stage, error_type='DaemonResourceError', error=message,
            observation=observation), sort_keys=True, separators=(',', ':'),
            ensure_ascii=True, allow_nan=False) + '\n'
        if len(raw.encode('utf-8')) > 4096:
            return False
        written = sys.stderr.write(raw)
        return type(written) is int and written == len(raw)
    except BaseException:
        return False


LIFECYCLE_SCHEMA = 'owned-validation-source-custody-lifecycle/v1'
_LIFECYCLE_EVENTS = {'owner_open_attempted', 'owner_open_returned',
    'child_launch_attempted', 'child_created', 'barrier_release_attempted',
    'barrier_released', 'owner_exit_handling_completed'}
_TIMEOUT_FIELDS = {'schema', 'decision_scope', 'cycle_wall_time', 'cycle_monotonic_time',
    'deadline_monotonic', 'elapsed_seconds', 'clock_scope', 'waiter_id', 'sequence',
    'request_id', 'lane', 'lane_truncated', 'parent_lease_id', 'timed_out',
    'can_grant_now', 'externally_cancelled', 'parent_cancelled', 'proof_safety_enabled',
    'exact_blocking_predicate', 'exact_blocking_cause'}


def _ordinary_scratch_no_child_request_shape(value, raw):
    """Pure exact V5 gate; projection reuses only V4 common-field shape checks."""
    try:
        if (type(value) is not dict or value.get('schema') != 'owned-validation-request/v5'
                or type(value.get('ordinary_scratch_profile')) is not dict
                or value['ordinary_scratch_profile'] != {
                    'schema': 'owned-validation-ordinary-scratch-live/v1'}):
            return False
        def pairs(items):
            result = {}
            for key, item in items:
                if key in result:
                    raise ValueError('duplicate ordinary scratch request field')
                result[key] = item
            return result
        def nonfinite(_):
            raise ValueError('nonfinite ordinary scratch request')
        if json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite) != value:
            return False
        projected = dict(value)
        projected.pop('ordinary_scratch_profile')
        projected['schema'] = 'owned-validation-request/v4'
        # An extra caller V4 field is rejected, never overwritten by projection.
        if 'live_inventory_profile' in projected:
            return False
        projected['live_inventory_profile'] = {
            'schema': 'owned-validation-live-census/v1', 'max_complete_resamples': 1}
        return _live_no_child_request_shape(projected,
            json.dumps(projected, sort_keys=True, allow_nan=False).encode())
    except BaseException:
        return False


def _no_grant_timeout_decision(decision, request_id):
    """Recognize only the existing scheduler's actual no-grant timeout branch."""
    return (type(decision) is dict and set(decision) == _TIMEOUT_FIELDS
        and decision['schema'] == 'resource-lease-timeout-decision@1'
        and decision['decision_scope'] == 'actual_terminal_timeout_branch'
        and decision['clock_scope'] == 'acquire_process_local_monotonic_clock'
        and decision['request_id'] == request_id
        and decision['lane'] == 'validation' and decision['lane_truncated'] is False
        and decision['parent_lease_id'] is None
        and decision['timed_out'] is True and decision['can_grant_now'] is False
        and decision['externally_cancelled'] is False and decision['parent_cancelled'] is False
        and type(decision['proof_safety_enabled']) is bool
        and type(decision['sequence']) is int and decision['sequence'] >= 0
        and type(decision['waiter_id']) is str and len(decision['waiter_id']) == 32
        and all(character in '0123456789abcdef' for character in decision['waiter_id'])
        and all(type(decision[key]) in (int, float) and math.isfinite(decision[key])
                for key in ('cycle_wall_time', 'cycle_monotonic_time', 'deadline_monotonic', 'elapsed_seconds'))
        and decision['cycle_monotonic_time'] >= decision['deadline_monotonic']
        and decision['elapsed_seconds'] >= 0
        and decision['exact_blocking_predicate'] is None and decision['exact_blocking_cause'] is None)



_LIFECYCLE_OWNER_NAMES = ('validation_run_resources.py', 'autoencoder_daemon_resources.py',
    'resource_scheduler.py', 'existing_resource_scheduler.py', 'proof_resource_safety.py')


def _lifecycle_source_guard(value):
    """Pin the actual timeout emitter and original validation/storage owners."""
    pins = value['source_sha256']
    directory = ROOT/'ipfs_datasets_py/optimizers/logic_theorem_optimizer'
    required = [str(Path(__file__).resolve()), *(str(directory/name) for name in _LIFECYCLE_OWNER_NAMES)]
    if type(pins) is not dict or any(type(pins.get(path)) is not str for path in required):
        raise ValueError('explicit original lifecycle owner source pins required')
    source_guard(value)


def _source_custody_witness(owner, reservation, value, request_raw, request_path,
        request_pin, events, failure, *, exit_handling_completed):
    """Report original post-exit control flow; retained storage is independent."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as host
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import LeaseTimeoutError
    producer = str(Path(__file__).resolve())
    guards = {'request_unchanged': False, 'source_pins_unchanged': False,
              'owner_identity_unchanged': False, 'errors': []}
    for name, check in (
            ('request_unchanged', lambda: snapshot(request_path) == request_raw),
            ('source_pins_unchanged', lambda: _lifecycle_source_guard(value) is None),
            ('owner_identity_unchanged', lambda: host._process(os.getpid()) is not None
                and all(host._process(os.getpid())[key] == owner._owner_identity[key]
                        for key in ('pid', 'birth')))):
        try:
            guards[name] = check() is True
        except BaseException as error:
            guards['errors'].append(name + ': ' + type(error).__name__)
    decision = getattr(failure, 'timeout_decision', None)
    exact_timeout = type(failure) is LeaseTimeoutError
    request_id = 'validation:' + owner.reservation_id
    native_status = ('acquired' if owner._lease is not None else
        'not_acquired_terminal_timeout' if exact_timeout and _no_grant_timeout_decision(decision, request_id)
        else 'unknown')
    storage = dict(status=reservation['status'], cleanup_error=reservation.get('cleanup_error'),
        release_authorized=False)
    if 'cleanup_failure_observations' in reservation:
        # Optional extension only for actual new-owner cleanup failures.
        # This is diagnostic DATA; it never changes storage-release authority.
        storage.update(cleanup_failure_observations=json.loads(json.dumps(
            reservation['cleanup_failure_observations'], allow_nan=False)),
            cleanup_failure_observation_overflow=reservation['cleanup_failure_observation_overflow'])
    return dict(schema=LIFECYCLE_SCHEMA, request_sha256=request_pin,
        producer={'path': producer, 'sha256': hashlib.sha256(snapshot(producer, 4*1024*1024)).hexdigest()},
        owner={'pid': owner._owner_identity['pid'], 'birth': owner._owner_identity['birth']},
        reservation_id=owner.reservation_id, resource_request_id=request_id,
        ledger_path=str(owner.ledger_path),
        scheduler={'state_path': value['scheduler_state_path'],
            'policy_sha256': value['expected_scheduler_policy_sha256'],
            'lane': 'validation', 'workload': 'canonical_validation'},
        attempt_directory=value['attempt_directory'], outputs=value['outputs'],
        budgets={key: value[key] for key in ('cpu_slots', 'memory_mb', 'child_process_slots', 'storage_bytes')},
        process_scope=value['process_scope'],
        events=dict(events, owner_exit_handling_completed=exit_handling_completed),
        owner_child_attached=owner._child is not None,
        native_grant={'status': native_status, 'exact_native_timeout': exact_timeout,
            'timeout_decision': decision if exact_timeout else None},
        source_guards=guards,
        storage=storage)



PRE_GRANT_CAPACITY_REFUSAL_SCHEMA = 'owned-validation-pre-grant-capacity-refusal/v1'
PRE_GRANT_LOCK_REFUSAL_SCHEMA = 'owned-validation-pre-grant-ledger-lock-refusal/v1'
PRE_GRANT_LEDGER_BOUND_REFUSAL_SCHEMA = 'owned-validation-pre-grant-ledger-byte-refusal/v1'

_PRE_GRANT_EVENTS = _LIFECYCLE_EVENTS - {'owner_exit_handling_completed'}

_CAPACITY_NUMBERS = {'observed_apparent_bytes', 'outstanding_full_reservations_bytes',
    'additional_requested_bytes', 'charged_bytes', 'limit_bytes', 'minimum_filesystem_free_bytes'}

def _capacity_refusal_observation(value, requested_bytes):
    """Accept only the original aggregate capacity snapshot, never an error string."""
    fields = _CAPACITY_NUMBERS | {'schema', 'scope', 'storage_capacity_exceeded',
        'filesystem_free_insufficient', 'storage_capacity_deficit_bytes', 'filesystem_free_deficit_bytes'}
    if (type(value) is not dict or set(value) != fields
            or value['schema'] != 'daemon-resource-capacity-observation/v1'
            or value['scope'] != 'named_roots_only_apparent_bytes'
            or type(requested_bytes) is not int or requested_bytes <= 0
            or any(type(value[key]) is not int or value[key] < 0 for key in
                   _CAPACITY_NUMBERS | {'storage_capacity_deficit_bytes', 'filesystem_free_deficit_bytes'})
            or value['additional_requested_bytes'] != requested_bytes or value['limit_bytes'] <= 0):
        return False
    observed, outstanding, additional = (value[key] for key in
        ('observed_apparent_bytes', 'outstanding_full_reservations_bytes', 'additional_requested_bytes'))
    over = value['charged_bytes'] > value['limit_bytes']
    short = value['minimum_filesystem_free_bytes'] < outstanding + additional
    return (value['charged_bytes'] == observed + outstanding + additional
        and type(value['storage_capacity_exceeded']) is bool
        and type(value['filesystem_free_insufficient']) is bool
        and value['storage_capacity_exceeded'] is over
        and value['filesystem_free_insufficient'] is short and (over or short)
        and value['storage_capacity_deficit_bytes'] == max(0, value['charged_bytes'] - value['limit_bytes'])
        and value['filesystem_free_deficit_bytes'] == max(0, outstanding + additional - value['minimum_filesystem_free_bytes']))

def _pre_grant_capacity_refusal_terminal(owner, value, request_raw, request_path,
        request_pin, resource_ledger, events, failure, outcome):
    """Authenticate the actual open/account refusal before any record or native grant.

    A caller must still genuinely reap this CLI and durably capture stdout.
    No output directory, claim, cleanup, retry or admission is created here.
    """
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as host
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.validation_run_resources import ValidationResourceReservation
    if (type(owner) is not ValidationResourceReservation
            or type(failure) is not host.DaemonResourceError
            or str(failure) != 'storage reservation capacity exceeded'
            or owner._entered or owner._opened or owner._record is not None
            or owner._lease is not None or owner._child is not None
            or type(events) is not dict or set(events) != _PRE_GRANT_EVENTS
            or any(type(flag) is not bool for flag in events.values())
            or events != {key: key == 'owner_open_attempted' for key in _PRE_GRANT_EVENTS}):
        return None
    # Exact original frames prove _account raised before __enter__ could write
    # a record or call _acquire_native_lease. A copied/message-only exception,
    # including one raised after an uncertain write, cannot provide this proof.
    validation_module = sys.modules.get(ValidationResourceReservation.__module__)
    expected_host = ROOT/'ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py'
    expected_validation = expected_host.with_name('validation_run_resources.py')
    if (Path(host.__file__).resolve() != expected_host or validation_module is None
            or Path(validation_module.__file__).resolve() != expected_validation):
        return None
    functions = ((ValidationResourceReservation.open, validation_module, expected_validation),
        (host.DaemonResourceReservation.__enter__, host, expected_host),
        (host.DaemonResourceReservation._account, host, expected_host))
    if any(fn.__globals__ is not module.__dict__ or fn.__code__.co_filename != str(path)
           for fn, module, path in functions):
        return None
    required = {fn.__code__ for fn, _, _ in functions}
    frames, trace = set(), failure.__traceback__
    while trace is not None:
        if any(trace.tb_frame.f_code is fn.__code__ and trace.tb_frame.f_globals is module.__dict__
               for fn, module, _ in functions):
            frames.add(trace.tb_frame.f_code)
        trace = trace.tb_next
    capacity = failure.capacity_observation
    if not required <= frames or not _capacity_refusal_observation(capacity, value['storage_bytes']):
        return None
    reservation = owner.to_dict()
    if (reservation['status'] != 'not_entered' or reservation['record'] is not None
            or reservation['resource_lease'] is not None or reservation.get('cleanup_error') is not None
            or capacity['limit_bytes'] != reservation['storage_limit_bytes']
            or capacity['limit_bytes'] != host.MAX_STORAGE_BYTES):
        return None
    identity = host._process(os.getpid())
    if identity is None or any(identity[key] != owner._owner_identity[key] for key in ('pid', 'birth')):
        return None
    if snapshot(request_path) != request_raw:
        return None
    _lifecycle_source_guard(value)
    producer = str(Path(__file__).resolve())
    witness = dict(schema=PRE_GRANT_CAPACITY_REFUSAL_SCHEMA,
        stage='owner_open_capacity_refused_before_record', request_sha256=request_pin,
        producer={'path': producer, 'sha256': value['source_sha256'].get(producer)},
        owner={key: identity[key] for key in ('pid', 'birth')}, ledger_path=str(resource_ledger),
        events=dict(events), owner_state={'entered': False, 'opened': False,
            'record_created': False, 'native_lease_created': False, 'child_attached': False},
        capacity_observation=capacity, native_grant={'status': 'not_requested_capacity_refusal'},
        storage={'status': 'not_entered', 'release_authorized': False},
        source_guards={'request_unchanged': True, 'source_pins_unchanged': True,
            'owner_identity_unchanged': True, 'errors': []})
    return dict(schema='owned-validation-failure-terminal/v1', request_sha256=request_pin,
        completed=False, admitted=False, Lean_admitted=False, failure=outcome,
        reservation=reservation, process_cleanup_error=None, owner_exit_error=None,
        source_custody_lifecycle=witness)

def _startup_clock_no_child_request_shape(value, raw):
    """Pure strict v6 shape gate before any Path, owner import or filesystem IO.

    This supports only the explicit native-timeout no-grant classifier below.
    It neither admits a workload nor calls the stateful SDK constructor/parser.
    The current pinned SDK decoder and validator identities are checked later.
    """
    fields = {'schema', 'argv', 'cwd', 'selected_checks', 'source_sha256',
        'timeout_seconds', 'storage_bytes', 'memory_mb', 'cpu_slots',
        'child_process_slots', 'attempt_directory', 'outputs',
        'declared_external_writable_paths', 'process_scope', 'scheduler_state_path',
        'expected_scheduler_policy_sha256', 'roots', 'live_inventory_profile', 'startup_clock_profile'}
    if type(value) is not dict or set(value) != fields or value.get('schema') != STARTUP_CLOCK_REQUEST_SCHEMA:
        return False
    def pairs(items):
        result = {}
        for name, item in items:
            if name in result:
                raise ValueError('duplicate live request field')
            result[name] = item
        return result
    def nonfinite(_):
        raise ValueError('nonfinite live request JSON')
    if json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite) != value:
        return False
    def absolute(item):
        return (type(item) is str and 0 < len(item.encode('utf-8')) <= 4096
            and item.startswith('/') and '\x00' not in item
            and (item == '/' or all(part not in ('', '.', '..') for part in item[1:].split('/'))))
    def digest(item):
        return (type(item) is str and len(item) == 64
            and all(letter in '0123456789abcdef' for letter in item))
    profile = value['live_inventory_profile']
    if not (type(profile) is dict and set(profile) == {'schema', 'max_complete_resamples'}
            and profile['schema'] == 'owned-validation-live-census/v1'
            and type(profile['max_complete_resamples']) is int and profile['max_complete_resamples'] == 1):
        return False
    clock = value['startup_clock_profile']
    if not (type(clock) is dict and set(clock) == set(STARTUP_CLOCK_PROFILE)
            and type(clock.get('schema')) is str
            and all(type(clock.get(key)) is int for key in ('admission_seconds','productive_seconds','total_seconds'))
            and clock == STARTUP_CLOCK_PROFILE and type(value['timeout_seconds']) is int
            and value['timeout_seconds'] == 180):
        return False
    for key in ('argv', 'selected_checks'):
        items = value[key]
        if not (type(items) is list and 0 < len(items) <= 256
                and all(type(item) is str and item.strip() and len(item) <= 8192 and '\x00' not in item
                        for item in items)):
            return False
    if len(set(value['selected_checks'])) != len(value['selected_checks']):
        return False
    if not all(absolute(value[key]) for key in ('cwd', 'attempt_directory', 'scheduler_state_path')):
        return False
    roots = value['roots']
    if not (type(roots) is list and 0 < len(roots) <= 64 and all(absolute(item) for item in roots)):
        return False
    def below(path, root):
        return path != root and path.startswith(root.rstrip('/') + '/')
    if any(left == right or below(left, right) or below(right, left)
           for index, left in enumerate(roots) for right in roots[:index]):
        return False
    attempt = value['attempt_directory']
    if not any(below(attempt, root) for root in roots):
        return False
    if not (type(value['outputs']) is dict and value['outputs'] == {
            name: attempt + '/' + name for name in ('pytest', 'tmp', 'cache', 'db', 'exports', 'logs')}
            and type(value['declared_external_writable_paths']) is list
            and value['declared_external_writable_paths'] == []
            and value['process_scope'] == 'sampled_birth_bound_descendants'):
        return False
    if not (all(type(value[key]) is int and value[key] > 0
                for key in ('storage_bytes', 'memory_mb', 'cpu_slots', 'child_process_slots'))
            and value['storage_bytes'] <= 220_000_000_000
            and type(value['timeout_seconds']) in (int, float)
            and math.isfinite(value['timeout_seconds']) and 0 < value['timeout_seconds'] <= 3600
            and digest(value['expected_scheduler_policy_sha256'])):
        return False
    sources = value['source_sha256']
    required = [__file__, *(str(ROOT) + '/ipfs_datasets_py/optimizers/logic_theorem_optimizer/' + name
                             for name in _LIFECYCLE_OWNER_NAMES)]
    return (type(sources) is dict and 0 < len(sources) <= 256
        and all(absolute(path) and digest(pin) for path, pin in sources.items())
        and all(path in sources for path in required))


def _startup_clock_no_child_observation(value, reservation, expected_request_sha256, need):
    """Phase DATA cannot replace actual no-child/native/source predicates."""
    clock = reservation.get('startup_clock_profile')
    fields = {'schema','request_sha256','profile','clock_scope','admission_started_monotonic',
        'admission_deadline_monotonic','productive_started_monotonic','productive_deadline_monotonic',
        'total_deadline_monotonic','attachment_attempted','attachment_verified','attached_child',
        'original_owner','original_native_lease_id','source_or_storage_release_authorized'}
    need(type(clock) is dict and set(clock) == fields
        and clock['schema'] == 'owned-validation-startup-clock-observation/v1'
        and clock['request_sha256'] == expected_request_sha256
        and type(clock['profile']) is dict and set(clock['profile']) == set(STARTUP_CLOCK_PROFILE)
        and type(clock['profile']['schema']) is str
        and all(type(clock['profile'][key]) is int for key in ('admission_seconds','productive_seconds','total_seconds'))
        and clock['profile'] == value['startup_clock_profile'] == STARTUP_CLOCK_PROFILE
        and clock['clock_scope'] == 'original_owner_process_monotonic'
        and clock['productive_started_monotonic'] is clock['productive_deadline_monotonic'] is None
        and clock['attachment_attempted'] is clock['attachment_verified'] is False
        and clock['attached_child'] is None and clock['source_or_storage_release_authorized'] is False
        and type(clock['original_owner']) is dict
        and type(clock['original_owner'].get('pid')) is int and clock['original_owner']['pid'] > 0
        and type(clock['original_owner'].get('birth')) is str and clock['original_owner']['birth'].isdecimal())
    started = clock['admission_started_monotonic']
    need((started is None and clock['admission_deadline_monotonic'] is clock['total_deadline_monotonic'] is None)
        or (type(started) in (int,float) and math.isfinite(started) and started > 0
            and clock['admission_deadline_monotonic'] == started + 180
            and clock['total_deadline_monotonic'] == started + 420))
    lease = reservation.get('resource_lease')
    need(clock['original_native_lease_id'] == (None if lease is None else lease['lease_id']))
    if reservation.get('record') is not None:
        row = reservation['record'];need(type(clock['original_owner']) is dict
            and clock['original_owner'].get('pid') == row['owner_pid'])
        if 'owner_birth' in row:need(clock['original_owner'].get('birth') == row['owner_birth'])
    return clock


def _live_no_child_request_shape(value, raw):
    """Pure strict v4 shape gate before any Path, owner import or filesystem IO.

    This supports only the explicit native-timeout no-grant classifier below.
    It neither admits a workload nor calls the stateful SDK constructor/parser.
    The current pinned SDK decoder and validator identities are checked later.
    """
    fields = {'schema', 'argv', 'cwd', 'selected_checks', 'source_sha256',
        'timeout_seconds', 'storage_bytes', 'memory_mb', 'cpu_slots',
        'child_process_slots', 'attempt_directory', 'outputs',
        'declared_external_writable_paths', 'process_scope', 'scheduler_state_path',
        'expected_scheduler_policy_sha256', 'roots', 'live_inventory_profile'}
    if type(value) is not dict or set(value) != fields or value.get('schema') != 'owned-validation-request/v4':
        return False
    def pairs(items):
        result = {}
        for name, item in items:
            if name in result:
                raise ValueError('duplicate live request field')
            result[name] = item
        return result
    def nonfinite(_):
        raise ValueError('nonfinite live request JSON')
    if json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite) != value:
        return False
    def absolute(item):
        return (type(item) is str and 0 < len(item.encode('utf-8')) <= 4096
            and item.startswith('/') and '\x00' not in item
            and (item == '/' or all(part not in ('', '.', '..') for part in item[1:].split('/'))))
    def digest(item):
        return (type(item) is str and len(item) == 64
            and all(letter in '0123456789abcdef' for letter in item))
    profile = value['live_inventory_profile']
    if not (type(profile) is dict and set(profile) == {'schema', 'max_complete_resamples'}
            and profile['schema'] == 'owned-validation-live-census/v1'
            and type(profile['max_complete_resamples']) is int and profile['max_complete_resamples'] == 1):
        return False
    for key in ('argv', 'selected_checks'):
        items = value[key]
        if not (type(items) is list and 0 < len(items) <= 256
                and all(type(item) is str and item.strip() and len(item) <= 8192 and '\x00' not in item
                        for item in items)):
            return False
    if len(set(value['selected_checks'])) != len(value['selected_checks']):
        return False
    if not all(absolute(value[key]) for key in ('cwd', 'attempt_directory', 'scheduler_state_path')):
        return False
    roots = value['roots']
    if not (type(roots) is list and 0 < len(roots) <= 64 and all(absolute(item) for item in roots)):
        return False
    def below(path, root):
        return path != root and path.startswith(root.rstrip('/') + '/')
    if any(left == right or below(left, right) or below(right, left)
           for index, left in enumerate(roots) for right in roots[:index]):
        return False
    attempt = value['attempt_directory']
    if not any(below(attempt, root) for root in roots):
        return False
    if not (type(value['outputs']) is dict and value['outputs'] == {
            name: attempt + '/' + name for name in ('pytest', 'tmp', 'cache', 'db', 'exports', 'logs')}
            and type(value['declared_external_writable_paths']) is list
            and value['declared_external_writable_paths'] == []
            and value['process_scope'] == 'sampled_birth_bound_descendants'):
        return False
    if not (all(type(value[key]) is int and value[key] > 0
                for key in ('storage_bytes', 'memory_mb', 'cpu_slots', 'child_process_slots'))
            and value['storage_bytes'] <= 220_000_000_000
            and type(value['timeout_seconds']) in (int, float)
            and math.isfinite(value['timeout_seconds']) and 0 < value['timeout_seconds'] <= 3600
            and digest(value['expected_scheduler_policy_sha256'])):
        return False
    sources = value['source_sha256']
    required = [__file__, *(str(ROOT) + '/ipfs_datasets_py/optimizers/logic_theorem_optimizer/' + name
                             for name in _LIFECYCLE_OWNER_NAMES)]
    return (type(sources) is dict and 0 < len(sources) <= 256
        and all(absolute(path) and digest(pin) for path, pin in sources.items())
        and all(path in sources for path in required))


PRE_OWNER_REFUSAL_SCHEMA = 'owned-validation-pre-owner-refusal/v1'
_PRE_OWNER_EVENTS = _LIFECYCLE_EVENTS | {'owner_construction_attempted', 'owner_construction_returned'}


def _pre_owner_refusal_terminal(value, request_raw, request_path, request_pin,
        resource_ledger, failure):
    """Report only the fixed constructor branch before owner.open is reachable.

    Construction validates metadata and opens the existing policy read-only;
    the original owner acquires native/storage custody only in open(). This
    certificate grants no cleanup, admission, storage release or test credit.
    """
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as host
    identity = host._process(os.getpid())
    if identity is None:
        raise RuntimeError('original pre-owner process identity unavailable')
    owner = {key: identity[key] for key in ('pid', 'birth')}
    guards = {'request_unchanged': False, 'source_pins_unchanged': False,
              'owner_identity_unchanged': False, 'errors': []}
    for name, check in (
            ('request_unchanged', lambda: snapshot(request_path) == request_raw),
            ('source_pins_unchanged', lambda: _lifecycle_source_guard(value) is None),
            ('owner_identity_unchanged', lambda: host._process(os.getpid()) is not None
                and all(host._process(os.getpid())[key] == owner[key] for key in ('pid', 'birth')))):
        try:
            guards[name] = check() is True
        except BaseException as error:
            guards['errors'].append(name + ': ' + type(error).__name__)
    producer = str(Path(__file__).resolve())
    witness = dict(schema=PRE_OWNER_REFUSAL_SCHEMA, request_sha256=request_pin,
        producer={'path': producer, 'sha256': value['source_sha256'].get(producer)},
        owner=owner, ledger_path=str(resource_ledger), stage='owner_construction_refused',
        events={key: key == 'owner_construction_attempted' for key in _PRE_OWNER_EVENTS},
        native_grant={'status': 'not_requested'},
        storage={'status': 'not_requested', 'release_authorized': False}, source_guards=guards)
    return dict(schema='owned-validation-failure-terminal/v1', request_sha256=request_pin,
        completed=False, admitted=False, Lean_admitted=False, reservation={},
        process_cleanup_error=None, owner_exit_error=None, source_custody_lifecycle=witness,
        failure=dict(error_type=type(failure).__name__, error=str(failure)[:8192],
            completed=False, executed_checks=[], returncode=None, admitted=False,
            Lean_admitted=False, authority_granted=False, model_weights_downloaded=False))


def _complete_preentry_terminal_shape(terminal, request_pin):
    """Pure full-envelope gate; a schema/header alone grants no Path/import IO."""
    fields = {'schema','request_sha256','completed','admitted','Lean_admitted','failure',
              'reservation','process_cleanup_error','owner_exit_error','source_custody_lifecycle'}
    if (type(terminal) is not dict or set(terminal) != fields
            or terminal.get('schema') != 'owned-validation-failure-terminal/v1'
            or terminal.get('request_sha256') != request_pin
            or any(terminal.get(k) is not False for k in ('completed','admitted','Lean_admitted'))
            or terminal['process_cleanup_error'] is not None or terminal['owner_exit_error'] is not None):
        return False
    witness, reservation = terminal['source_custody_lifecycle'], terminal['reservation']
    if type(witness) is not dict or type(reservation) is not dict or type(terminal['failure']) is not dict:
        return False
    kind = witness.get('schema')
    observation = ('capacity_observation' if kind == PRE_GRANT_CAPACITY_REFUSAL_SCHEMA else
                   'lock_observation' if kind == PRE_GRANT_LOCK_REFUSAL_SCHEMA else
                   'ledger_write_bound_observation' if kind == PRE_GRANT_LEDGER_BOUND_REFUSAL_SCHEMA else
                   'entry_refusal_observation' if kind == PRE_RESOURCE_ENTRY_REFUSAL_SCHEMA else None)
    return (observation is not None and set(witness) == {'schema','stage','request_sha256','producer',
        'owner','ledger_path','events','owner_state',observation,'native_grant','storage','source_guards'}
        and witness.get('request_sha256') == request_pin
        and type(witness.get(observation)) is dict
        and reservation.get('status') == 'not_entered' and reservation.get('record') is None
        and reservation.get('resource_lease') is None and reservation.get('process_observation') is None)


def _lock_refusal_observation(value, ledger_path):
    fields = {'schema','stage','lock_path','opened_lock_identity','configured_lock_timeout_seconds',
              'started_monotonic','deadline_monotonic','observed_monotonic','lock_acquired','holder_identity_established'}
    if (type(value) is not dict or set(value) != fields
            or value['schema'] != 'daemon-resource-ledger-lock-timeout/v1'
            or value['stage'] != 'exclusive_acquire_before_yield'
            or value['lock_path'] != str(ledger_path)+'.lock'
            or value['lock_acquired'] is not False or value['holder_identity_established'] is not False):
        return False
    info = value['opened_lock_identity']
    keys = {'st_dev','st_ino','st_mode','st_uid','st_gid','st_nlink','st_size','st_mtime_ns','st_ctime_ns'}
    if (type(info) is not dict or set(info) != keys
            or any(type(x) is not int or x < 0 for x in info.values())
            or not stat.S_ISREG(info['st_mode']) or info['st_nlink'] != 1 or info['st_ino'] <= 0):
        return False
    keys = ('configured_lock_timeout_seconds','started_monotonic','deadline_monotonic','observed_monotonic')
    return (all(type(value[k]) in (int,float) and math.isfinite(value[k]) and value[k] >= 0 for k in keys)
        and value['configured_lock_timeout_seconds'] <= 60
        and value['started_monotonic'] <= value['deadline_monotonic'] <= value['observed_monotonic']
        and value['deadline_monotonic'] <= value['started_monotonic'] + value['configured_lock_timeout_seconds'])


def _live_no_native_sdk_receipt(value, request_raw, expected_request_sha256, reservation, need):
    if value['schema'] == 'owned-validation-request/v5':
        return _ordinary_scratch_no_native_sdk_receipt(value, request_raw, expected_request_sha256, reservation, need)
    if value['schema'] == STARTUP_CLOCK_REQUEST_SCHEMA:
        need(_startup_clock_no_child_request_shape(value, request_raw))
        _startup_clock_no_child_observation(value, reservation, expected_request_sha256, need)
    # Match the existing v2 source-verified parser pattern without
    # constructing an owner or entering native/storage custody.
    import importlib.util
    for package_name in ('ipfs_datasets_py', 'ipfs_datasets_py.optimizers',
            'ipfs_datasets_py.optimizers.logic_theorem_optimizer'):
        package = sys.modules.get(package_name)
        need(package is not None and list(getattr(package, '__path__', [])) ==
             [str(ROOT/package_name.replace('.', '/'))])
    parser_name = 'ipfs_datasets_py.optimizers.logic_theorem_optimizer.validation_run_resources'
    parser_path = ROOT/'ipfs_datasets_py/optimizers/logic_theorem_optimizer/validation_run_resources.py'
    parser_spec = importlib.util.find_spec(parser_name)
    need(parser_spec is not None and parser_spec.origin == str(parser_path))
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import validation_run_resources as sdk
    need(sdk is sys.modules[parser_name] and sdk.__file__ == str(parser_path)
         and sdk.__spec__.origin == str(parser_path)
         and sdk.LIVE_REQUEST_SCHEMA == 'owned-validation-request/v4'
         and sdk.LIVE_INVENTORY_SCHEMA == 'owned-validation-live-census/v1'
         and sdk.TRACKED_SCOPE == 'sampled_birth_bound_descendants'
         and sdk.MAX_SOURCE_PINS == 256 and type(sdk.MAX_SOURCE_PINS) is int
         and sdk.OUTPUT_NAMES == ('pytest', 'tmp', 'cache', 'db', 'exports', 'logs'))
    if value['schema'] == STARTUP_CLOCK_REQUEST_SCHEMA:
        need(sdk.STARTUP_CLOCK_REQUEST_SCHEMA == STARTUP_CLOCK_REQUEST_SCHEMA
             and sdk.STARTUP_CLOCK_PROFILE == value['startup_clock_profile'])
    decoder, validator = sdk._decode, sdk.ValidationResourceReservation._validate_request
    need(decoder.__module__ == parser_name and validator.__module__ == parser_name
         and decoder.__code__.co_filename == validator.__code__.co_filename == str(parser_path)
         and decoder.__globals__ is vars(sdk) and validator.__globals__ is vars(sdk))
    host_path = ROOT/'ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py'
    need(sdk.host.__file__ == str(host_path)
         and sdk.host._json_pairs.__code__.co_filename == str(host_path)
         and decoder(request_raw) == value)
    profile = value['live_inventory_profile']
    observation = reservation.get('live_inventory_profile')
    need(type(observation) is dict and set(observation) == {
        'schema', 'max_complete_resamples', 'request_sha256',
        'complete_resamples_observed', 'live_exception_active', 'resample_limit_scope'}
        and type(observation['schema']) is str and type(observation['request_sha256']) is str
        and type(observation['resample_limit_scope']) is str
        and type(observation['max_complete_resamples']) is int
        and type(observation['complete_resamples_observed']) is int
        and observation['live_exception_active'] is False
        and observation == {'schema': profile['schema'], 'max_complete_resamples': 1,
            'request_sha256': expected_request_sha256, 'complete_resamples_observed': 0,
            'live_exception_active': False, 'resample_limit_scope': 'per_logical_live_census'})


def _ordinary_scratch_no_native_sdk_receipt(value, request_raw, expected_request_sha256, reservation, need):
    # Match the existing v2 source-verified parser pattern without
    # constructing an owner or entering native/storage custody.
    import importlib.util
    for package_name in ('ipfs_datasets_py', 'ipfs_datasets_py.optimizers',
            'ipfs_datasets_py.optimizers.logic_theorem_optimizer'):
        package = sys.modules.get(package_name)
        need(package is not None and list(getattr(package, '__path__', [])) ==
             [str(ROOT/package_name.replace('.', '/'))])
    parser_name = 'ipfs_datasets_py.optimizers.logic_theorem_optimizer.validation_run_resources'
    parser_path = ROOT/'ipfs_datasets_py/optimizers/logic_theorem_optimizer/validation_run_resources.py'
    parser_spec = importlib.util.find_spec(parser_name)
    need(parser_spec is not None and parser_spec.origin == str(parser_path))
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import validation_run_resources as sdk
    need(sdk is sys.modules[parser_name] and sdk.__file__ == str(parser_path)
         and sdk.__spec__.origin == str(parser_path)
         and sdk.ORDINARY_SCRATCH_REQUEST_SCHEMA == 'owned-validation-request/v5'
         and sdk.ORDINARY_SCRATCH_PROFILE_SCHEMA == 'owned-validation-ordinary-scratch-live/v1'
         and sdk.TRACKED_SCOPE == 'sampled_birth_bound_descendants'
         and sdk.MAX_SOURCE_PINS == 256 and type(sdk.MAX_SOURCE_PINS) is int
         and sdk.OUTPUT_NAMES == ('pytest', 'tmp', 'cache', 'db', 'exports', 'logs'))
    decoder, validator = sdk._decode, sdk.ValidationResourceReservation._validate_request
    need(decoder.__module__ == parser_name and validator.__module__ == parser_name
         and decoder.__code__.co_filename == validator.__code__.co_filename == str(parser_path)
         and decoder.__globals__ is vars(sdk) and validator.__globals__ is vars(sdk))
    host_path = ROOT/'ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py'
    need(sdk.host.__file__ == str(host_path)
         and sdk.host._json_pairs.__code__.co_filename == str(host_path)
         and decoder(request_raw) == value)
    profile = value['ordinary_scratch_profile']
    observation = reservation.get('ordinary_scratch_profile')
    need(type(observation) is dict and set(observation) == {
        'schema', 'request_sha256', 'ordinary_absences_observed',
        'live_exception_active', 'unseen_leaf_ownership_attested', 'whole_census_resampling'}
        and type(observation['schema']) is str and type(observation['request_sha256']) is str
        and type(observation['ordinary_absences_observed']) is int
        and observation['live_exception_active'] is False
        and observation['unseen_leaf_ownership_attested'] is False
        and observation['whole_census_resampling'] is False
        and observation == {'schema': profile['schema'], 'request_sha256': expected_request_sha256,
            'ordinary_absences_observed': 0, 'live_exception_active': False,
            'unseen_leaf_ownership_attested': False, 'whole_census_resampling': False})


def _pre_grant_lock_refusal_terminal(owner, value, request_raw, request_path,
        request_pin, resource_ledger, events, failure, outcome):
    """Authenticate the actual opening-lock refusal before any record or native grant.

    A caller must still genuinely reap this CLI and durably capture stdout.
    No output directory, claim, cleanup, retry or admission is created here.
    """
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as host
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.validation_run_resources import ValidationResourceReservation
    if (type(owner) is not ValidationResourceReservation
            or type(failure) is not host.DaemonResourceError
            or str(failure) != 'disk ledger lock unavailable'
            or owner._entered is not False or owner._opened is not False or owner._record is not None
            or owner._lease is not None or owner._child is not None
            or type(events) is not dict or set(events) != _PRE_GRANT_EVENTS
            or any(type(flag) is not bool for flag in events.values())
            or events != {key: key == 'owner_open_attempted' for key in _PRE_GRANT_EVENTS}):
        return None
    # Exact original self/error frames prove the opening _locked timeout
    # preceded yield, record publication and native admission. A copied exception,
    # including one raised after an uncertain write, cannot provide this proof.
    validation_module = sys.modules.get(ValidationResourceReservation.__module__)
    expected_host = ROOT/'ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py'
    expected_validation = expected_host.with_name('validation_run_resources.py')
    if (Path(host.__file__).resolve() != expected_host or validation_module is None
            or Path(validation_module.__file__).resolve() != expected_validation):
        return None
    locked = getattr(host.DaemonResourceReservation._locked, '__wrapped__', None)
    if locked is None:
        return None
    functions = ((ValidationResourceReservation.open, validation_module, expected_validation),
        (host.DaemonResourceReservation.__enter__, host, expected_host), (locked, host, expected_host))
    if any(fn.__globals__ is not module.__dict__ or fn.__code__.co_filename != str(path)
           for fn, module, path in functions):
        return None
    frames, trace = {}, failure.__traceback__
    while trace is not None:
        for fn, module, _ in functions:
            if (trace.tb_frame.f_code is fn.__code__ and trace.tb_frame.f_globals is module.__dict__
                    and trace.tb_frame.f_locals.get('self') is owner):
                frames[fn.__code__] = trace.tb_frame
        trace = trace.tb_next
    if set(frames) != {fn.__code__ for fn, _, _ in functions}:
        return None
    locals_ = frames[locked.__code__].f_locals
    if locals_.get('error') is not failure or locals_.get('lock_acquired') is not False:
        return None
    info = locals_.get('info')
    if type(info) is not os.stat_result:
        return None
    observation = failure.lock_observation
    expected = dict(schema='daemon-resource-ledger-lock-timeout/v1',stage='exclusive_acquire_before_yield',
        lock_path=str(owner.lock_path),opened_lock_identity={key:getattr(info,key) for key in
            ('st_dev','st_ino','st_mode','st_uid','st_gid','st_nlink','st_size','st_mtime_ns','st_ctime_ns')},
        configured_lock_timeout_seconds=owner.ledger_lock_timeout_seconds,
        started_monotonic=locals_.get('lock_started'),deadline_monotonic=locals_.get('deadline'),
        observed_monotonic=locals_.get('observed_at'),lock_acquired=False,holder_identity_established=False)
    if observation != expected or not _lock_refusal_observation(observation, resource_ledger):
        return None
    reservation = owner.to_dict()
    if (reservation['status'] != 'not_entered' or reservation['record'] is not None
            or reservation['resource_lease'] is not None or reservation.get('cleanup_error') is not None):
        return None
    identity = host._process(os.getpid())
    if identity is None or any(identity[key] != owner._owner_identity[key] for key in ('pid', 'birth')):
        return None
    if snapshot(request_path) != request_raw:
        return None
    _lifecycle_source_guard(value)
    producer = str(Path(__file__).resolve())
    witness = dict(schema=PRE_GRANT_LOCK_REFUSAL_SCHEMA,
        stage='owner_open_ledger_lock_refused_before_record', request_sha256=request_pin,
        producer={'path': producer, 'sha256': value['source_sha256'].get(producer)},
        owner={key: identity[key] for key in ('pid', 'birth')}, ledger_path=str(resource_ledger),
        events=dict(events), owner_state={'entered': False, 'opened': False,
            'record_created': False, 'native_lease_created': False, 'child_attached': False},
        lock_observation=observation, native_grant={'status': 'not_requested_lock_timeout'},
        storage={'status': 'not_entered', 'release_authorized': False},
        source_guards={'request_unchanged': True, 'source_pins_unchanged': True,
            'owner_identity_unchanged': True, 'errors': []})
    return dict(schema='owned-validation-failure-terminal/v1', request_sha256=request_pin,
        completed=False, admitted=False, Lean_admitted=False, failure=outcome,
        reservation=reservation, process_cleanup_error=None, owner_exit_error=None,
        source_custody_lifecycle=witness)


def _ledger_bound_refusal_observation(value, maximum_bytes):
    fields = {'schema', 'serialized_bytes', 'maximum_bytes', 'excess_bytes', 'write_started'}
    return (type(value) is dict and set(value) == fields
        and value['schema'] == 'daemon-resource-ledger-write-bound/v1'
        and all(type(value[key]) is int and 0 < value[key] < 2**63
                for key in ('serialized_bytes', 'maximum_bytes', 'excess_bytes'))
        and value['maximum_bytes'] == maximum_bytes
        and value['serialized_bytes'] > maximum_bytes
        and value['excess_bytes'] == value['serialized_bytes'] - maximum_bytes
        and value['write_started'] is False)


def _pre_grant_ledger_bound_refusal_terminal(owner, value, request_raw, request_path,
        request_pin, resource_ledger, events, failure, outcome):
    """Authenticate the original first-write size refusal before publication."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as host
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.validation_run_resources import ValidationResourceReservation
    if (type(owner) is not ValidationResourceReservation
            or type(failure) is not host.DaemonResourceError
            or failure.args != ('disk ledger byte bound exceeded',)
            or owner._entered is not False or owner._opened is not False or owner._record is not None
            or owner._lease is not None or owner._child is not None
            or type(events) is not dict or set(events) != _PRE_GRANT_EVENTS
            or any(type(flag) is not bool for flag in events.values())
            or events != {key: key == 'owner_open_attempted' for key in _PRE_GRANT_EVENTS}):
        return None
    validation_module = sys.modules.get(ValidationResourceReservation.__module__)
    expected_host = ROOT/'ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py'
    expected_validation = expected_host.with_name('validation_run_resources.py')
    if (Path(host.__file__).resolve() != expected_host or validation_module is None
            or Path(validation_module.__file__).resolve() != expected_validation):
        return None
    enter, write = host.DaemonResourceReservation.__enter__, host.DaemonResourceReservation._write
    functions = ((ValidationResourceReservation.open, validation_module, expected_validation),
        (enter, host, expected_host), (write, host, expected_host))
    if any(fn.__globals__ is not module.__dict__ or fn.__code__.co_filename != str(path)
           for fn, module, path in functions):
        return None
    frames, trace = {}, failure.__traceback__
    while trace is not None:
        for fn, module, _ in functions:
            if (trace.tb_frame.f_code is fn.__code__ and trace.tb_frame.f_globals is module.__dict__
                    and trace.tb_frame.f_locals.get('self') is owner):
                frames[fn.__code__] = trace.tb_frame
        trace = trace.tb_next
    if set(frames) != {fn.__code__ for fn, _, _ in functions}:
        return None
    write_locals, enter_locals = frames[write.__code__].f_locals, frames[enter.__code__].f_locals
    raw, ledger, record = (write_locals.get('raw'), enter_locals.get('ledger'), enter_locals.get('record'))
    if (write_locals.get('error') is not failure or 'temporary' in write_locals
            or type(raw) is not bytes or type(ledger) is not dict or type(record) is not dict
            or write_locals.get('value') is not ledger
            or type(ledger.get('reservations')) is not dict
            or ledger['reservations'].get(owner.reservation_id) is not record
            or record.get('status') != 'reserved'
            or raw != (json.dumps(ledger, sort_keys=True, separators=(',', ':'),
                                 allow_nan=False) + '\n').encode()):
        return None
    observation = failure.ledger_write_bound_observation
    expected = dict(schema='daemon-resource-ledger-write-bound/v1',
        serialized_bytes=len(raw), maximum_bytes=host.MAX_LEDGER_BYTES,
        excess_bytes=len(raw) - host.MAX_LEDGER_BYTES, write_started=False)
    if observation != expected or not _ledger_bound_refusal_observation(observation, host.MAX_LEDGER_BYTES):
        return None
    reservation = owner.to_dict()
    if (reservation['status'] != 'not_entered' or reservation['record'] is not None
            or reservation['resource_lease'] is not None or reservation.get('cleanup_error') is not None):
        return None
    identity = host._process(os.getpid())
    if identity is None or any(identity[key] != owner._owner_identity[key] for key in ('pid', 'birth')):
        return None
    if snapshot(request_path) != request_raw:
        return None
    _lifecycle_source_guard(value)
    producer = str(Path(__file__).resolve())
    witness = dict(schema=PRE_GRANT_LEDGER_BOUND_REFUSAL_SCHEMA,
        stage='owner_open_ledger_bytes_refused_before_record', request_sha256=request_pin,
        producer={'path': producer, 'sha256': value['source_sha256'].get(producer)},
        owner={key: identity[key] for key in ('pid', 'birth')}, ledger_path=str(resource_ledger),
        events=dict(events), owner_state={'entered': False, 'opened': False,
            'record_created': False, 'native_lease_created': False, 'child_attached': False},
        ledger_write_bound_observation=observation,
        native_grant={'status': 'not_requested_ledger_byte_refusal'},
        storage={'status': 'not_entered', 'release_authorized': False},
        source_guards={'request_unchanged': True, 'source_pins_unchanged': True,
            'owner_identity_unchanged': True, 'errors': []})
    return dict(schema='owned-validation-failure-terminal/v1', request_sha256=request_pin,
        completed=False, admitted=False, Lean_admitted=False, failure=outcome,
        reservation=reservation, process_cleanup_error=None, owner_exit_error=None,
        source_custody_lifecycle=witness)



PRE_RESOURCE_ENTRY_REFUSAL_SCHEMA = 'owned-validation-pre-resource-entry-refusal/v1'


def _resource_entry_refusal_observation(value):
    fields = {'schema', 'boundary', 'error_type', 'error', 'owner_constructed',
              'live_trace_verified', 'initial_ledger_returned',
              'record_construction_reached', 'native_acquire_reached'}
    return (type(value) is dict and set(value) == fields
        and value['schema'] == 'owned-validation-initial-ledger-read-refusal/v1'
        and value['boundary'] == 'initial_ledger_read'
        and value['error_type'] == 'DaemonResourceError'
        and type(value['error']) is str and 0 < len(value['error']) <= 1024
        and all(type(value[key]) is bool for key in
            ('owner_constructed', 'live_trace_verified', 'initial_ledger_returned',
             'record_construction_reached', 'native_acquire_reached'))
        and value['owner_constructed'] is True and value['live_trace_verified'] is True
        and value['initial_ledger_returned'] is False
        and value['record_construction_reached'] is False
        and value['native_acquire_reached'] is False)


def _pre_resource_entry_refusal_terminal(owner, value, request_raw, request_path,
        request_pin, resource_ledger, events, failure, outcome):
    """Observe a constructed owner's actual first-read refusal, never a constructor fiction."""
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as host
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.validation_run_resources import ValidationResourceReservation
    if (value.get('schema') not in ('owned-validation-request/v1', 'owned-validation-request/v5')
            or type(owner) is not ValidationResourceReservation
            or type(failure) is not host.DaemonResourceError
            or type(failure.args) is not tuple or len(failure.args) != 1
            or type(failure.args[0]) is not str or not 0 < len(failure.args[0]) <= 1024
            or str(failure) != failure.args[0]
            or owner._entered is not False or owner._opened is not False
            or owner._record is not None or owner._lease is not None or owner._child is not None
            or owner._opening is not False or owner._started is not None
            or type(events) is not dict or set(events) != _PRE_GRANT_EVENTS
            or any(type(flag) is not bool for flag in events.values())
            or events != {key: key == 'owner_open_attempted' for key in _PRE_GRANT_EVENTS}):
        return None
    validation_module = sys.modules.get(ValidationResourceReservation.__module__)
    expected_host = ROOT/'ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py'
    expected_validation = expected_host.with_name('validation_run_resources.py')
    if (Path(host.__file__).resolve() != expected_host or validation_module is None
            or Path(validation_module.__file__).resolve() != expected_validation):
        return None
    enter, initial_read = host.DaemonResourceReservation.__enter__, host.DaemonResourceReservation._read
    functions = ((ValidationResourceReservation.open, validation_module, expected_validation),
        (enter, host, expected_host),
        (ValidationResourceReservation._read, validation_module, expected_validation),
        (initial_read, host, expected_host))
    if any(fn.__globals__ is not module.__dict__ or fn.__code__.co_filename != str(path)
           for fn, module, path in functions):
        return None
    frames, trace, last = {}, failure.__traceback__, None
    while trace is not None:
        last = trace
        for fn, module, _ in functions:
            if (trace.tb_frame.f_code is fn.__code__ and trace.tb_frame.f_globals is module.__dict__
                    and trace.tb_frame.f_locals.get('self') is owner):
                if fn.__code__ in frames:
                    return None
                frames[fn.__code__] = trace.tb_frame
        trace = trace.tb_next
    if (set(frames) != {fn.__code__ for fn, _, _ in functions}
            or last is None or last.tb_frame.f_code is not initial_read.__code__):
        return None
    # The first read has not returned: no ledger or record local can exist yet.
    # A read from uncertain first-write/cleanup code cannot reuse this boundary.
    entry_locals = frames[enter.__code__].f_locals
    if 'ledger' in entry_locals or 'record' in entry_locals:
        return None
    observation = dict(schema='owned-validation-initial-ledger-read-refusal/v1',
        boundary='initial_ledger_read', error_type='DaemonResourceError', error=str(failure),
        owner_constructed=True, live_trace_verified=True, initial_ledger_returned=False,
        record_construction_reached=False, native_acquire_reached=False)
    if not _resource_entry_refusal_observation(observation):
        return None
    reservation = owner.to_dict()
    if (reservation.get('status') != 'not_entered' or reservation.get('record') is not None
            or reservation.get('resource_lease') is not None
            or reservation.get('process_observation') is not None
            or reservation.get('cleanup_error') is not None):
        return None
    identity = host._process(os.getpid())
    if (identity is None or any(identity[key] != owner._owner_identity[key] for key in ('pid', 'birth'))
            or snapshot(request_path) != request_raw):
        return None
    if value['schema'] == 'owned-validation-request/v1':
        # Recheck the same constructed owner's original request/attempt before
        # exposing the V1 first-read no-grant terminal to its Source custodian.
        if (owner.request != value or owner.request_sha256 != request_pin
                or owner.request_path != Path(request_path)
                or owner.ledger_path != Path(resource_ledger)):
            return None
        owner._guard_inputs()
    _lifecycle_source_guard(value)
    producer = str(Path(__file__).resolve())
    witness = dict(schema=PRE_RESOURCE_ENTRY_REFUSAL_SCHEMA,
        stage='owner_open_initial_ledger_read_refused_before_record',
        request_sha256=request_pin,
        producer={'path': producer, 'sha256': value['source_sha256'].get(producer)},
        owner={key: identity[key] for key in ('pid', 'birth')},
        ledger_path=str(resource_ledger), events=dict(events),
        owner_state={'constructed': True, 'entered': owner._entered, 'opened': owner._opened,
            'record_created': owner._record is not None, 'native_lease_created': owner._lease is not None,
            'child_attached': owner._child is not None},
        entry_refusal_observation=observation,
        native_grant={'status': 'not_requested_before_resource_entry'},
        storage={'status': 'not_entered', 'release_authorized': False},
        source_guards={'request_unchanged': True, 'source_pins_unchanged': True,
            'owner_identity_unchanged': True, 'errors': []})
    return dict(schema='owned-validation-failure-terminal/v1', request_sha256=request_pin,
        completed=False, admitted=False, Lean_admitted=False, failure=outcome,
        reservation=reservation, process_cleanup_error=None, owner_exit_error=None,
        source_custody_lifecycle=witness)


def classify_owned_validation_source_custody(terminal, request_raw, *,
        expected_request_sha256, owner_pid, owner_birth, returncode, expected_resource_ledger):
    """Prove only explicit original no-child/no-native source-custody closure.

    An observed original CLI exit is a caller prerequisite. This classifier
    neither releases storage nor substitutes for admitted native cleanup. Any
    missing, mismatched, aliased or changed evidence returns an unknown verdict.
    """
    unknown = dict(verdict='requires_original_native_cleanup', source_custody_closed=False,
                   storage_release_authorized=False)
    try:
        def need(condition):
            if not condition:
                raise ValueError('unproven original no-child lifecycle')
        need(type(request_raw) is bytes and 0 < len(request_raw) <= 1024*1024
             and type(expected_request_sha256) is str
             and hashlib.sha256(request_raw).hexdigest() == expected_request_sha256)
        value = json.loads(request_raw)
        need(type(value) is dict and value.get('schema') in
             ('owned-validation-request/v1', 'owned-validation-request/v2', 'owned-validation-request/v4', 'owned-validation-request/v5', STARTUP_CLOCK_REQUEST_SCHEMA))
        live = value['schema'] in ('owned-validation-request/v4', 'owned-validation-request/v5', STARTUP_CLOCK_REQUEST_SCHEMA)
        if live:
            need((_startup_clock_no_child_request_shape(value, request_raw)
                  if value['schema'] == STARTUP_CLOCK_REQUEST_SCHEMA else
                  _ordinary_scratch_no_child_request_shape(value, request_raw)
                  if value['schema'] == 'owned-validation-request/v5'
                  else _live_no_child_request_shape(value, request_raw))
                 and type(terminal) is dict
                 and type(terminal.get('source_custody_lifecycle')) is dict
                 and (terminal['source_custody_lifecycle'].get('schema') == LIFECYCLE_SCHEMA
                      or _complete_preentry_terminal_shape(terminal, expected_request_sha256)))
        need(type(expected_resource_ledger) is str and Path(expected_resource_ledger).is_absolute()
             and str(Path(expected_resource_ledger).resolve(strict=True)) == expected_resource_ledger)
        ledger_info = Path(expected_resource_ledger).lstat()
        need(stat.S_ISREG(ledger_info.st_mode) and ledger_info.st_nlink == 1)
        need(all(stat.S_ISDIR(parent.lstat().st_mode) for parent in
                 (Path(expected_resource_ledger).parent, *Path(expected_resource_ledger).parent.parents)))
        need(type(owner_pid) is int and owner_pid > 0 and type(owner_birth) is str and owner_birth.isdecimal()
             and type(returncode) is int and returncode != 0)
        need(type(terminal) is dict and set(terminal) == {'schema', 'request_sha256', 'completed',
            'admitted', 'Lean_admitted', 'failure', 'reservation', 'process_cleanup_error',
            'owner_exit_error', 'source_custody_lifecycle'})
        need(terminal['schema'] == 'owned-validation-failure-terminal/v1'
             and terminal['request_sha256'] == expected_request_sha256
             and all(terminal[key] is False for key in ('completed', 'admitted', 'Lean_admitted'))
             and terminal['process_cleanup_error'] is None and terminal['owner_exit_error'] is None)
        failure, reservation, witness = terminal['failure'], terminal['reservation'], terminal['source_custody_lifecycle']
        if value['schema'] == STARTUP_CLOCK_REQUEST_SCHEMA and reservation:
            phase_owner = reservation['startup_clock_profile']['original_owner']
            need(type(phase_owner) is dict and type(phase_owner.get('pid')) is int
                 and phase_owner.get('pid') == owner_pid and phase_owner.get('birth') == owner_birth)
        if type(witness) is dict and witness.get('schema') == PRE_RESOURCE_ENTRY_REFUSAL_SCHEMA:
            need(value['schema'] in ('owned-validation-request/v1', 'owned-validation-request/v5')
                 and returncode == 1)
            need(set(witness) == {'schema', 'stage', 'request_sha256', 'producer', 'owner',
                'ledger_path', 'events', 'owner_state', 'entry_refusal_observation',
                'native_grant', 'storage', 'source_guards'})
            need(witness['stage'] == 'owner_open_initial_ledger_read_refused_before_record'
                and witness['request_sha256'] == expected_request_sha256
                and witness['owner'] == {'pid': owner_pid, 'birth': owner_birth}
                and witness['ledger_path'] == expected_resource_ledger)
            producer = str(Path(__file__).resolve())
            producer_pin = value['source_sha256'].get(producer)
            need(type(producer_pin) is str
                and witness['producer'] == {'path': producer, 'sha256': producer_pin}
                and hashlib.sha256(snapshot(producer, 4*1024*1024)).hexdigest() == producer_pin)
            _lifecycle_source_guard(value)
            if live:
                _live_no_native_sdk_receipt(value, request_raw, expected_request_sha256, reservation, need)
            observation = witness['entry_refusal_observation']
            need(_resource_entry_refusal_observation(observation))
            need(type(failure) is dict and failure.get('schema') == 'owned-validation-result/v1'
                and failure.get('request_sha256') == expected_request_sha256
                and failure.get('error_type') == 'DaemonResourceError'
                and failure.get('error') == observation['error']
                and failure.get('executed_checks') == [] and failure.get('returncode') is None
                and failure.get('watchdog_errors') == [] and failure.get('received_signals') == []
                and all(failure.get(key) is False for key in ('completed', 'admitted', 'Lean_admitted',
                    'authority_granted', 'model_weights_downloaded')))
            need(type(reservation) is dict and reservation.get('schema') == 'daemon-resource-reservations-v1'
                and reservation.get('status') == 'not_entered' and reservation.get('record') is None
                and reservation.get('resource_lease') is None and reservation.get('cleanup_error') is None
                and reservation.get('process_observation') is None
                and reservation.get('ledger_path') == expected_resource_ledger
                and reservation.get('scheduler_lane') == 'validation'
                and reservation.get('workload') == 'canonical_validation')
            need(witness['owner_state'] == {'constructed': True, 'entered': False, 'opened': False,
                'record_created': False, 'native_lease_created': False, 'child_attached': False}
                and all(type(flag) is bool for flag in witness['owner_state'].values()))
            need(type(witness['events']) is dict and set(witness['events']) == _PRE_GRANT_EVENTS
                and all(type(flag) is bool for flag in witness['events'].values())
                and witness['events'] == {key: key == 'owner_open_attempted' for key in _PRE_GRANT_EVENTS})
            need(witness['native_grant'] == {'status': 'not_requested_before_resource_entry'}
                and witness['storage'] == {'status': 'not_entered', 'release_authorized': False}
                and witness['source_guards'] == {'request_unchanged': True, 'source_pins_unchanged': True,
                    'owner_identity_unchanged': True, 'errors': []}
                and all(type(witness['source_guards'][key]) is bool for key in
                    ('request_unchanged', 'source_pins_unchanged', 'owner_identity_unchanged')))
            return dict(verdict='proven_original_no_child_no_native_grant', source_custody_closed=True,
                        storage_release_authorized=False)
        if type(witness) is dict and witness.get('schema') == PRE_GRANT_CAPACITY_REFUSAL_SCHEMA:
            from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as host
            need(set(witness) == {'schema', 'stage', 'request_sha256', 'producer', 'owner',
                'ledger_path', 'events', 'owner_state', 'capacity_observation', 'native_grant',
                'storage', 'source_guards'})
            need(witness['stage'] == 'owner_open_capacity_refused_before_record'
                and witness['request_sha256'] == expected_request_sha256
                and witness['owner'] == {'pid': owner_pid, 'birth': owner_birth}
                and witness['ledger_path'] == expected_resource_ledger)
            producer = str(Path(__file__).resolve())
            producer_pin = value['source_sha256'].get(producer)
            need(type(producer_pin) is str
                and witness['producer'] == {'path': producer, 'sha256': producer_pin}
                and hashlib.sha256(snapshot(producer, 4*1024*1024)).hexdigest() == producer_pin)
            _lifecycle_source_guard(value)
            if live:
                _live_no_native_sdk_receipt(value, request_raw, expected_request_sha256, reservation, need)
            need(type(failure) is dict and failure.get('schema') == 'owned-validation-result/v1'
                and failure.get('request_sha256') == expected_request_sha256
                and failure.get('error_type') == 'DaemonResourceError'
                and failure.get('error') == 'storage reservation capacity exceeded'
                and failure.get('executed_checks') == [] and failure.get('returncode') is None
                and failure.get('watchdog_errors') == [] and failure.get('received_signals') == []
                and all(failure.get(key) is False for key in ('completed', 'admitted', 'Lean_admitted',
                    'authority_granted', 'model_weights_downloaded')))
            need(type(reservation) is dict and reservation.get('schema') == 'daemon-resource-reservations-v1'
                and reservation.get('status') == 'not_entered' and reservation['record'] is None
                and reservation['resource_lease'] is None and reservation['cleanup_error'] is None
                and reservation.get('ledger_path') == expected_resource_ledger
                and reservation.get('scheduler_lane') == 'validation'
                and reservation.get('workload') == 'canonical_validation'
                and reservation.get('process_observation') is None)
            need(witness['owner_state'] == {'entered': False, 'opened': False,
                'record_created': False, 'native_lease_created': False, 'child_attached': False}
                and all(type(flag) is bool for flag in witness['owner_state'].values()))
            need(type(witness['events']) is dict and set(witness['events']) == _PRE_GRANT_EVENTS
                and all(type(flag) is bool for flag in witness['events'].values())
                and witness['events'] == {key: key == 'owner_open_attempted' for key in _PRE_GRANT_EVENTS})
            need(_capacity_refusal_observation(witness['capacity_observation'], value['storage_bytes'])
                and witness['capacity_observation']['limit_bytes'] == reservation['storage_limit_bytes']
                and witness['capacity_observation']['limit_bytes'] == host.MAX_STORAGE_BYTES)
            need(witness['native_grant'] == {'status': 'not_requested_capacity_refusal'}
                and witness['storage'] == {'status': 'not_entered', 'release_authorized': False}
                and witness['storage']['release_authorized'] is False
                and witness['source_guards'] == {'request_unchanged': True, 'source_pins_unchanged': True,
                    'owner_identity_unchanged': True, 'errors': []}
                and all(type(witness['source_guards'][key]) is bool for key in
                    ('request_unchanged', 'source_pins_unchanged', 'owner_identity_unchanged')))
            return dict(verdict='proven_original_no_child_no_native_grant', source_custody_closed=True,
                        storage_release_authorized=False)
        if type(witness) is dict and witness.get('schema') == PRE_GRANT_LOCK_REFUSAL_SCHEMA:
            from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as host
            need(set(witness) == {'schema', 'stage', 'request_sha256', 'producer', 'owner',
                'ledger_path', 'events', 'owner_state', 'lock_observation', 'native_grant',
                'storage', 'source_guards'})
            need(witness['stage'] == 'owner_open_ledger_lock_refused_before_record'
                and witness['request_sha256'] == expected_request_sha256
                and witness['owner'] == {'pid': owner_pid, 'birth': owner_birth}
                and witness['ledger_path'] == expected_resource_ledger)
            producer = str(Path(__file__).resolve())
            producer_pin = value['source_sha256'].get(producer)
            need(type(producer_pin) is str
                and witness['producer'] == {'path': producer, 'sha256': producer_pin}
                and hashlib.sha256(snapshot(producer, 4*1024*1024)).hexdigest() == producer_pin)
            _lifecycle_source_guard(value)
            if live:
                _live_no_native_sdk_receipt(value, request_raw, expected_request_sha256, reservation, need)
            need(type(failure) is dict and failure.get('schema') == 'owned-validation-result/v1'
                and failure.get('request_sha256') == expected_request_sha256
                and failure.get('error_type') == 'DaemonResourceError'
                and failure.get('error') == 'disk ledger lock unavailable'
                and failure.get('executed_checks') == [] and failure.get('returncode') is None
                and failure.get('watchdog_errors') == [] and failure.get('received_signals') == []
                and all(failure.get(key) is False for key in ('completed', 'admitted', 'Lean_admitted',
                    'authority_granted', 'model_weights_downloaded')))
            need(type(reservation) is dict and reservation.get('schema') == 'daemon-resource-reservations-v1'
                and reservation.get('status') == 'not_entered' and reservation['record'] is None
                and reservation['resource_lease'] is None and reservation['cleanup_error'] is None
                and reservation.get('ledger_path') == expected_resource_ledger
                and reservation.get('scheduler_lane') == 'validation'
                and reservation.get('workload') == 'canonical_validation'
                and reservation.get('process_observation') is None)
            need(witness['owner_state'] == {'entered': False, 'opened': False,
                'record_created': False, 'native_lease_created': False, 'child_attached': False}
                and all(type(flag) is bool for flag in witness['owner_state'].values()))
            need(type(witness['events']) is dict and set(witness['events']) == _PRE_GRANT_EVENTS
                and all(type(flag) is bool for flag in witness['events'].values())
                and witness['events'] == {key: key == 'owner_open_attempted' for key in _PRE_GRANT_EVENTS})
            need(_lock_refusal_observation(witness['lock_observation'], expected_resource_ledger))
            need(witness['native_grant'] == {'status': 'not_requested_lock_timeout'}
                and witness['storage'] == {'status': 'not_entered', 'release_authorized': False}
                and witness['storage']['release_authorized'] is False
                and witness['source_guards'] == {'request_unchanged': True, 'source_pins_unchanged': True,
                    'owner_identity_unchanged': True, 'errors': []}
                and all(type(witness['source_guards'][key]) is bool for key in
                    ('request_unchanged', 'source_pins_unchanged', 'owner_identity_unchanged')))
            return dict(verdict='proven_original_no_child_no_native_grant', source_custody_closed=True,
                        storage_release_authorized=False)
        if type(witness) is dict and witness.get('schema') == PRE_GRANT_LEDGER_BOUND_REFUSAL_SCHEMA:
            from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as host
            need(set(witness) == {'schema', 'stage', 'request_sha256', 'producer', 'owner',
                'ledger_path', 'events', 'owner_state', 'ledger_write_bound_observation', 'native_grant',
                'storage', 'source_guards'})
            need(witness['stage'] == 'owner_open_ledger_bytes_refused_before_record'
                and witness['request_sha256'] == expected_request_sha256
                and witness['owner'] == {'pid': owner_pid, 'birth': owner_birth}
                and witness['ledger_path'] == expected_resource_ledger)
            producer = str(Path(__file__).resolve())
            producer_pin = value['source_sha256'].get(producer)
            need(type(producer_pin) is str
                and witness['producer'] == {'path': producer, 'sha256': producer_pin}
                and hashlib.sha256(snapshot(producer, 4*1024*1024)).hexdigest() == producer_pin)
            _lifecycle_source_guard(value)
            if live:
                _live_no_native_sdk_receipt(value, request_raw, expected_request_sha256, reservation, need)
            need(type(failure) is dict and failure.get('schema') == 'owned-validation-result/v1'
                and failure.get('request_sha256') == expected_request_sha256
                and failure.get('error_type') == 'DaemonResourceError'
                and failure.get('error') == 'disk ledger byte bound exceeded'
                and failure.get('executed_checks') == [] and failure.get('returncode') is None
                and failure.get('watchdog_errors') == [] and failure.get('received_signals') == []
                and all(failure.get(key) is False for key in ('completed', 'admitted', 'Lean_admitted',
                    'authority_granted', 'model_weights_downloaded')))
            need(type(reservation) is dict and reservation.get('schema') == 'daemon-resource-reservations-v1'
                and reservation.get('status') == 'not_entered' and reservation['record'] is None
                and reservation['resource_lease'] is None and reservation['cleanup_error'] is None
                and reservation.get('ledger_path') == expected_resource_ledger
                and reservation.get('scheduler_lane') == 'validation'
                and reservation.get('workload') == 'canonical_validation'
                and reservation.get('process_observation') is None)
            need(witness['owner_state'] == {'entered': False, 'opened': False,
                'record_created': False, 'native_lease_created': False, 'child_attached': False}
                and all(type(flag) is bool for flag in witness['owner_state'].values()))
            need(type(witness['events']) is dict and set(witness['events']) == _PRE_GRANT_EVENTS
                and all(type(flag) is bool for flag in witness['events'].values())
                and witness['events'] == {key: key == 'owner_open_attempted' for key in _PRE_GRANT_EVENTS})
            need(_ledger_bound_refusal_observation(witness['ledger_write_bound_observation'], host.MAX_LEDGER_BYTES))
            need(witness['native_grant'] == {'status': 'not_requested_ledger_byte_refusal'}
                and witness['storage'] == {'status': 'not_entered', 'release_authorized': False}
                and witness['storage']['release_authorized'] is False
                and witness['source_guards'] == {'request_unchanged': True, 'source_pins_unchanged': True,
                    'owner_identity_unchanged': True, 'errors': []}
                and all(type(witness['source_guards'][key]) is bool for key in
                    ('request_unchanged', 'source_pins_unchanged', 'owner_identity_unchanged')))
            return dict(verdict='proven_original_no_child_no_native_grant', source_custody_closed=True,
                        storage_release_authorized=False)
        if type(witness) is dict and witness.get('schema') == PRE_OWNER_REFUSAL_SCHEMA:
            # The invalid request is intentionally not revalidated as an admitted
            # v1/v2 workload. The pinned producer proves the earlier constructor
            # refusal, where no owner.open or child launch was attempted.
            need(reservation == {} and type(reservation) is dict)
            need(set(witness) == {'schema', 'request_sha256', 'producer', 'owner', 'ledger_path',
                'stage', 'events', 'native_grant', 'storage', 'source_guards'})
            need(witness['request_sha256'] == expected_request_sha256
                and witness['owner'] == {'pid': owner_pid, 'birth': owner_birth}
                and type(witness['owner']['pid']) is int
                and witness['ledger_path'] == expected_resource_ledger
                and witness['stage'] == 'owner_construction_refused')
            producer = str(Path(__file__).resolve())
            producer_pin = value['source_sha256'].get(producer)
            need(type(producer_pin) is str
                and witness['producer'] == {'path': producer, 'sha256': producer_pin}
                and hashlib.sha256(snapshot(producer, 4*1024*1024)).hexdigest() == producer_pin)
            _lifecycle_source_guard(value)
            need(type(failure) is dict and set(failure) == {'error_type', 'error', 'completed',
                'executed_checks', 'returncode', 'admitted', 'Lean_admitted', 'authority_granted',
                'model_weights_downloaded'}
                and type(failure['error_type']) is str and failure['error_type'].isidentifier()
                and len(failure['error_type']) <= 128 and type(failure['error']) is str
                and len(failure['error']) <= 8192 and failure['executed_checks'] == []
                and failure['returncode'] is None
                and all(failure[key] is False for key in ('completed', 'admitted', 'Lean_admitted',
                    'authority_granted', 'model_weights_downloaded')))
            events = witness['events']
            need(type(events) is dict and set(events) == _PRE_OWNER_EVENTS
                and all(type(flag) is bool for flag in events.values())
                and events['owner_construction_attempted'] is True
                and all(events[key] is False for key in _PRE_OWNER_EVENTS - {'owner_construction_attempted'}))
            need(witness['native_grant'] == {'status': 'not_requested'}
                and witness['storage'] == {'status': 'not_requested', 'release_authorized': False}
                and witness['storage']['release_authorized'] is False
                and witness['source_guards'] == {'request_unchanged': True, 'source_pins_unchanged': True,
                    'owner_identity_unchanged': True, 'errors': []}
                and all(type(witness['source_guards'][key]) is bool for key in
                    ('request_unchanged', 'source_pins_unchanged', 'owner_identity_unchanged')))
            return dict(verdict='proven_original_no_child_no_native_grant', source_custody_closed=True,
                        storage_release_authorized=False)
        need(type(failure) is dict and failure.get('error_type') == 'LeaseTimeoutError'
             and failure.get('request_sha256') == expected_request_sha256
             and failure.get('completed') is False and failure.get('executed_checks') == []
             and failure.get('returncode') is None
             and all(failure.get(key) is False for key in
                 ('admitted', 'Lean_admitted', 'authority_granted', 'model_weights_downloaded')))
        need(type(witness) is dict and set(witness) == {'schema', 'request_sha256', 'producer', 'owner',
            'reservation_id', 'resource_request_id', 'ledger_path', 'scheduler', 'attempt_directory', 'outputs',
            'budgets', 'process_scope', 'events', 'owner_child_attached', 'native_grant', 'source_guards', 'storage'})
        need(witness['schema'] == LIFECYCLE_SCHEMA and witness['request_sha256'] == expected_request_sha256
             and witness['owner'] == {'pid': owner_pid, 'birth': owner_birth}
             and type(witness['owner']['pid']) is int)
        producer = str(Path(__file__).resolve())
        producer_pin = value['source_sha256'].get(producer)
        need(type(producer_pin) is str and witness['producer'] == {'path': producer, 'sha256': producer_pin}
             and hashlib.sha256(snapshot(producer, 4*1024*1024)).hexdigest() == producer_pin)
        # Independently recheck all original pinned sources at verification.
        _lifecycle_source_guard(value)
        if value['schema'] == 'owned-validation-request/v2':
            import importlib.util
            for package_name in ('ipfs_datasets_py', 'ipfs_datasets_py.optimizers',
                    'ipfs_datasets_py.optimizers.logic_theorem_optimizer'):
                package = sys.modules.get(package_name)
                need(package is not None and list(getattr(package, '__path__', [])) ==
                     [str(ROOT/package_name.replace('.', '/'))])
            parser_name = 'ipfs_datasets_py.optimizers.logic_theorem_optimizer.validation_run_resources'
            parser_path = ROOT/'ipfs_datasets_py/optimizers/logic_theorem_optimizer/validation_run_resources.py'
            parser_spec = importlib.util.find_spec(parser_name)
            need(parser_spec is not None and parser_spec.origin == str(parser_path))
            from ipfs_datasets_py.optimizers.logic_theorem_optimizer.validation_run_resources import (
                _parse_physical_fixture_profile, PHYSICAL_FIXTURE_SCHEMA)
            need(sys.modules[parser_name].__file__ == str(parser_path)
                 and _parse_physical_fixture_profile.__code__.co_filename == str(parser_path))
            need(set(value) == {'schema', 'argv', 'cwd', 'selected_checks', 'source_sha256',
                'timeout_seconds', 'storage_bytes', 'memory_mb', 'cpu_slots',
                'child_process_slots', 'attempt_directory', 'outputs',
                'declared_external_writable_paths', 'process_scope', 'scheduler_state_path',
                'expected_scheduler_policy_sha256', 'roots', 'physical_fixture_profile'})
            for field in ('argv', 'selected_checks'):
                need(type(value[field]) is list and 0 < len(value[field]) <= 256
                     and all(type(item) is str and item.strip() and len(item) <= 8192
                             and '\x00' not in item for item in value[field]))
            need(len(set(value['selected_checks'])) == len(value['selected_checks'])
                 and type(value['attempt_directory']) is str
                 and Path(value['attempt_directory']).is_absolute())
            profile, cases, entries = _parse_physical_fixture_profile(
                value, Path(value['attempt_directory']))
            observation = reservation.get('physical_fixture_profile')
            need(type(observation) is dict and set(observation) == {'schema', 'request_sha256',
                 'root', 'case_count', 'entry_count', 'live_special_file_window'}
                 and type(observation['case_count']) is int
                 and type(observation['entry_count']) is int
                 and observation['live_special_file_window'] is False)
            need(observation == {
                'schema': PHYSICAL_FIXTURE_SCHEMA, 'request_sha256': expected_request_sha256,
                'root': profile['root'], 'case_count': len(cases), 'entry_count': len(entries),
                'live_special_file_window': False})
        if live:
            _live_no_native_sdk_receipt(value, request_raw, expected_request_sha256, reservation, need)
            need(returncode == 1 and failure.get('watchdog_errors') == []
                 and failure.get('received_signals') == []
                 and reservation.get('status') == 'retained'
                 and type(reservation.get('record')) is dict
                 and reservation['record'].get('retention_reason') == 'scheduler_admission_failed'
                 and reservation.get('cleanup_error') is None)
        need(witness['source_guards'] == {'request_unchanged': True, 'source_pins_unchanged': True,
             'owner_identity_unchanged': True, 'errors': []}
             and all(type(witness['source_guards'][key]) is bool for key in
                 ('request_unchanged', 'source_pins_unchanged', 'owner_identity_unchanged')))
        events = witness['events']
        need(type(events) is dict and set(events) == _LIFECYCLE_EVENTS
             and all(type(flag) is bool for flag in events.values())
             and events['owner_open_attempted'] is True and events['owner_exit_handling_completed'] is True
             and all(events[key] is False for key in _LIFECYCLE_EVENTS -
                 {'owner_open_attempted', 'owner_exit_handling_completed'})
             and witness['owner_child_attached'] is False)
        record = reservation['record']
        need(type(record) is dict and reservation['reservation_id'] == record['reservation_id'] == witness['reservation_id']
             and type(witness['reservation_id']) is str and witness['reservation_id']
             and record['owner_pid'] == owner_pid and type(record['owner_pid']) is int
             and record.get('child') is None and record.get('prior_children') == []
             and reservation.get('resource_lease') is None
             and reservation.get('process_observation') is None
             and reservation['ledger_path'] == witness['ledger_path'] == expected_resource_ledger)
        need(witness['resource_request_id'] == 'validation:' + witness['reservation_id']
             and witness['scheduler'] == {'state_path': value['scheduler_state_path'],
                'policy_sha256': value['expected_scheduler_policy_sha256'],
                'lane': 'validation', 'workload': 'canonical_validation'}
             and reservation['scheduler_lane'] == record['scheduler_lane'] == 'validation'
             and reservation['workload'] == record['workload'] == 'canonical_validation')
        need(witness['attempt_directory'] == value['attempt_directory'] == record['attempt_directory']['path']
             and witness['outputs'] == value['outputs'] and witness['process_scope'] == value['process_scope']
             and value['process_scope'] == 'sampled_birth_bound_descendants')
        need(type(witness['budgets']) is dict and set(witness['budgets']) ==
             {'cpu_slots', 'memory_mb', 'child_process_slots', 'storage_bytes'}
             and all(type(witness['budgets'][key]) is int and type(value[key]) is int
                     and type(record[key]) is int and witness['budgets'][key] == value[key] == record[key]
                     for key in witness['budgets']))
        grant = witness['native_grant']
        need(type(grant) is dict and set(grant) == {'status', 'exact_native_timeout', 'timeout_decision'}
             and grant['status'] == 'not_acquired_terminal_timeout' and grant['exact_native_timeout'] is True
             and _no_grant_timeout_decision(grant['timeout_decision'], witness['resource_request_id']))
        need(witness['storage'] == {'status': reservation['status'],
            'cleanup_error': reservation.get('cleanup_error'), 'release_authorized': False}
            and witness['storage']['release_authorized'] is False
            and reservation['status'] == record['status']
            and record['status'] in ('reserved', 'retained') and record['artifacts_durable_asserted'] is False)
        return dict(verdict='proven_original_no_child_no_native_grant', source_custody_closed=True,
                    storage_release_authorized=False)
    except BaseException:
        return unknown


def _no_child_native_closed_profile(terminal, request_raw, *, request_version,
        expected_request_sha256, owner_pid, owner_birth, returncode, expected_resource_ledger):
    """Shared finite bindings; each public profile selects original request bytes.

    V5 binds SDK-open post-grant deadline or ledger-lock failure DATA with exact zero process samples.
    No request or terminal projection is used to establish either profile.
    """
    def need(condition):
        if not condition:
            raise ValueError('unproven original acquired no-child lifecycle')
    def pairs(items):
        result = {}
        for key, item in items:
            need(key not in result)
            result[key] = item
        return result
    def nonfinite(_):
        raise ValueError('nonfinite original request')
    def absolute(item):
        return (type(item) is str and 0 < len(item.encode()) <= 4096
            and item.startswith('/') and '\x00' not in item
            and (item == '/' or all(part not in ('', '.', '..') for part in item[1:].split('/'))))
    def digest(item):
        return (type(item) is str and len(item) == 64
            and all(character in '0123456789abcdef' for character in item))
    def identifier(item):
        return type(item) is str and len(item) == 32 and digest(item + item)
    def zero_process_observation(item):
        # Exact pre-child sampled DATA, never an absence proof by itself.
        if (type(item) is not dict or set(item) != {'scope', 'group_rss',
                'live_processes', 'rss_bytes', 'observed_identities',
                'out_of_group_live_identities', 'tracking_error'}):
            return False
        group = item['group_rss']
        return (type(item['scope']) is str and item['scope'] == 'sampled_birth_bound_descendants'
            and type(group) is dict and set(group) == {'available', 'live_processes', 'rss_bytes'}
            and group['available'] is True
            and all(type(group[key]) is int and group[key] == 0 for key in ('live_processes', 'rss_bytes'))
            and all(type(item[key]) is int and item[key] == 0 for key in ('live_processes', 'rss_bytes'))
            and type(item['observed_identities']) is list and item['observed_identities'] == []
            and type(item['out_of_group_live_identities']) is list and item['out_of_group_live_identities'] == []
            and type(item['tracking_error']) is str and item['tracking_error'] == '')
    need(type(request_raw) is bytes and 0 < len(request_raw) <= 1024*1024
        and digest(expected_request_sha256)
        and hashlib.sha256(request_raw).hexdigest() == expected_request_sha256
        and type(owner_pid) is int and owner_pid > 0
        and type(owner_birth) is str and owner_birth.isdecimal()
        and type(returncode) is int and returncode == 1 and absolute(expected_resource_ledger))
    need(request_version in ('v1', 'v5', 'v6'))
    value = json.loads(request_raw, object_pairs_hook=pairs, parse_constant=nonfinite)
    fields = {'schema', 'argv', 'cwd', 'selected_checks', 'source_sha256',
        'timeout_seconds', 'storage_bytes', 'memory_mb', 'cpu_slots',
        'child_process_slots', 'attempt_directory', 'outputs', 'declared_external_writable_paths',
        'process_scope', 'scheduler_state_path', 'expected_scheduler_policy_sha256', 'roots'}
    if request_version == 'v5':
        fields.add('ordinary_scratch_profile')
        need(_ordinary_scratch_no_child_request_shape(value, request_raw))
    if request_version == 'v6':
        fields.update(('live_inventory_profile','startup_clock_profile'))
        need(_startup_clock_no_child_request_shape(value, request_raw))
    if request_version in ('v5','v6'):
        remaining_nodes = 65536
        def finite_json(item, depth=0):
            nonlocal remaining_nodes
            remaining_nodes -= 1
            need(depth <= 32 and remaining_nodes >= 0)
            if item is None or type(item) in (str, bool, int):
                return
            if type(item) is float:
                need(math.isfinite(item)); return
            if type(item) is list:
                need(len(item) <= 16384)
                for entry in item: finite_json(entry, depth+1)
                return
            need(type(item) is dict and len(item) <= 16384
                and all(type(key) is str for key in item))
            for entry in item.values(): finite_json(entry, depth+1)
        finite_json(terminal)
        need(len(json.dumps(terminal, sort_keys=True, allow_nan=False).encode()) <= 1024*1024)
    need(type(value) is dict and set(value) == fields
        and value['schema'] == 'owned-validation-request/' + request_version
        and value['process_scope'] == 'sampled_birth_bound_descendants'
        and value['declared_external_writable_paths'] == []
        and absolute(value['cwd']) and absolute(value['attempt_directory'])
        and absolute(value['scheduler_state_path']) and digest(value['expected_scheduler_policy_sha256']))
    for field in ('argv', 'selected_checks'):
        need(type(value[field]) is list and 0 < len(value[field]) <= 256
            and all(type(item) is str and item.strip() and len(item) <= 8192
                and '\x00' not in item for item in value[field]))
    need(len(set(value['selected_checks'])) == len(value['selected_checks'])
        and type(value['roots']) is list and 0 < len(value['roots']) <= (64 if request_version in ('v5','v6') else 16)
        and len(set(value['roots'])) == len(value['roots']) and all(absolute(item) for item in value['roots'])
        and type(value['source_sha256']) is dict and 0 < len(value['source_sha256']) <= 256
        and all(absolute(path) and digest(pin) for path, pin in value['source_sha256'].items()))
    budgets = ('cpu_slots', 'memory_mb', 'child_process_slots', 'storage_bytes')
    need(all(type(value[key]) is int and 0 < value[key] < 2**63 for key in budgets)
        and ((request_version == 'v1' and type(value['timeout_seconds']) is int
              and 0 < value['timeout_seconds'] < 2**63)
            or (request_version == 'v5' and type(value['timeout_seconds']) in (int, float)
                and math.isfinite(value['timeout_seconds']) and 0 < value['timeout_seconds'] <= 3600)
            or (request_version == 'v6' and type(value['timeout_seconds']) is int and value['timeout_seconds'] == 180))
        and type(value['outputs']) is dict and set(value['outputs']) == {'pytest', 'tmp', 'cache', 'db', 'exports', 'logs'}
        and all(path == value['attempt_directory'] + '/' + name for name, path in value['outputs'].items()))
    need(type(terminal) is dict and set(terminal) == {'schema', 'request_sha256', 'completed',
        'admitted', 'Lean_admitted', 'failure', 'reservation', 'process_cleanup_error',
        'owner_exit_error', 'source_custody_lifecycle'}
        and terminal['schema'] == 'owned-validation-failure-terminal/v1'
        and terminal['request_sha256'] == expected_request_sha256
        and all(terminal[key] is False for key in ('completed', 'admitted', 'Lean_admitted'))
        and terminal['process_cleanup_error'] is None and terminal['owner_exit_error'] is None)
    failure, reservation, witness = (terminal[key] for key in
        ('failure', 'reservation', 'source_custody_lifecycle'))
    need(type(failure) is dict and set(failure) == {'schema', 'request_sha256', 'executed_checks',
        'returncode', 'completed', 'admitted', 'Lean_admitted', 'resource_scope', 'model_weights_downloaded',
        'authority_granted', 'error_type', 'error', 'elapsed_seconds', 'watchdog_errors',
        'received_signals', 'process_observation', 'process_cleanup_error'}
        and failure['schema'] == 'owned-validation-result/v1'
        and failure['request_sha256'] == expected_request_sha256
        and failure['executed_checks'] == [] and failure['returncode'] is None
        and failure['watchdog_errors'] == [] and failure['received_signals'] == []
        and failure['process_cleanup_error'] is None
        and failure['resource_scope'] == 'cooperative_sampled_birth_bound_descendants_and_owned_attempt'
        and type(failure['elapsed_seconds']) in (int, float) and math.isfinite(failure['elapsed_seconds'])
        and all(failure[key] is False for key in ('completed', 'admitted', 'Lean_admitted',
            'authority_granted', 'model_weights_downloaded')))
    # Keep the original admission-deadline profile distinct from a stopped
    # post-grant owner-open ledger-lock refusal before that original deadline.
    deadline_profile = (request_version == 'v1'
        and failure['error_type'] == 'ResourceAdmissionDeadlineError'
        and failure['error'] == 'original absolute resource operation deadline expired'
        and failure['process_observation'] is None
        and failure['elapsed_seconds'] >= value['timeout_seconds'])
    postgrant_lock_profile = (request_version in ('v1', 'v5')
        and type(failure['error_type']) is str
        and failure['error_type'] == 'DaemonResourceError'
        and type(failure['error']) is str and failure['error'] == 'disk ledger lock unavailable'
        and 0 < failure['elapsed_seconds'] < value['timeout_seconds']
        and zero_process_observation(failure['process_observation']))
    ordinary_deadline_profile = (request_version in ('v5','v6')
        and type(failure['error_type']) is str
        and failure['error_type'] == 'ResourceAdmissionDeadlineError'
        and type(failure['error']) is str
        and failure['error'] == 'original absolute resource operation deadline expired'
        and value['timeout_seconds'] <= failure['elapsed_seconds'] < 2**63
        and zero_process_observation(failure['process_observation']))
    need(deadline_profile or postgrant_lock_profile or ordinary_deadline_profile)
    need(type(witness) is dict and set(witness) == {'schema', 'request_sha256', 'producer', 'owner',
        'reservation_id', 'resource_request_id', 'ledger_path', 'scheduler', 'attempt_directory',
        'outputs', 'budgets', 'process_scope', 'events', 'owner_child_attached', 'native_grant',
        'source_guards', 'storage'} and witness['schema'] == LIFECYCLE_SCHEMA
        and witness['request_sha256'] == expected_request_sha256
        and witness['owner'] == {'pid': owner_pid, 'birth': owner_birth}
        and type(witness['owner']['pid']) is int
        and type(witness['events']) is dict and set(witness['events']) == _LIFECYCLE_EVENTS
        and all(type(flag) is bool for flag in witness['events'].values())
        and witness['events'] == {key: key in ('owner_open_attempted', 'owner_exit_handling_completed')
            for key in _LIFECYCLE_EVENTS} and witness['owner_child_attached'] is False
        and witness['native_grant'] == {'status': 'acquired', 'exact_native_timeout': False, 'timeout_decision': None}
        and witness['native_grant']['exact_native_timeout'] is False
        and witness['source_guards'] == {'request_unchanged': True, 'source_pins_unchanged': True,
            'owner_identity_unchanged': True, 'errors': []}
        and all(witness['source_guards'][key] is True for key in
            ('request_unchanged', 'source_pins_unchanged', 'owner_identity_unchanged')))
    need(type(reservation) is dict and set(reservation) == {'schema', 'ledger_path', 'reservation_id',
        'status', 'record', 'resource_lease', 'process_observation', 'cleanup_error', 'roots',
        'scheduler_lane', 'workload', 'storage_limit_bytes', 'enforcement'}
            | ({'ordinary_scratch_profile'} if request_version == 'v5' else
               {'live_inventory_profile','startup_clock_profile'} if request_version == 'v6' else set())
        and reservation['schema'] == 'daemon-resource-reservations-v1'
        and reservation['status'] == 'retained' and reservation['cleanup_error'] is None
        and ((deadline_profile and reservation['process_observation'] is None)
            or ((postgrant_lock_profile or ordinary_deadline_profile) and zero_process_observation(reservation['process_observation'])))
        and reservation['enforcement'] == 'cooperative_admission_and_polled_usage_not_kernel_quota')
    row, lease = reservation['record'], reservation['resource_lease']
    need(type(row) is dict and set(row) == {'reservation_id', 'status', 'owner_pid', 'storage_bytes',
        'memory_mb', 'cpu_slots', 'child_process_slots', 'external_charges', 'created_at',
        'prior_children', 'child', 'artifacts_durable_asserted', 'scheduler_lane', 'workload',
        'attempt_directory', 'last_usage', 'retention_reason'}
        and row['reservation_id'] == reservation['reservation_id'] == witness['reservation_id']
        and identifier(row['reservation_id'])
        and row['status'] == 'retained'
        and ((deadline_profile and row['retention_reason'] == 'scheduler_admission_failed')
            or ((postgrant_lock_profile or ordinary_deadline_profile) and row['retention_reason'] == 'context_failed'))
        and type(row['owner_pid']) is int and row['owner_pid'] == owner_pid
        and row['child'] is None and row['prior_children'] == [] and row['external_charges'] == {}
        and row['artifacts_durable_asserted'] is False
        and type(row['created_at']) in (int, float) and math.isfinite(row['created_at']) and row['created_at'] > 0
        and row['scheduler_lane'] == reservation['scheduler_lane'] == 'validation'
        and row['workload'] == reservation['workload'] == 'canonical_validation'
        and reservation['ledger_path'] == witness['ledger_path'] == expected_resource_ledger
        and type(row['attempt_directory']) is dict and set(row['attempt_directory']) == {'device', 'inode', 'path'}
        and all(type(row['attempt_directory'][key]) is int and row['attempt_directory'][key] > 0
            for key in ('device', 'inode'))
        and row['attempt_directory']['path'] == witness['attempt_directory'] == value['attempt_directory']
        and witness['outputs'] == value['outputs'] and witness['process_scope'] == value['process_scope']
        and type(witness['budgets']) is dict and set(witness['budgets']) == set(budgets)
        and all(type(row[key]) is int and type(witness['budgets'][key]) is int
            and row[key] == witness['budgets'][key] == value[key] for key in budgets)
        and witness['storage'] == {'status': 'retained', 'cleanup_error': None, 'release_authorized': False}
        and witness['storage']['release_authorized'] is False)
    usage = row['last_usage']
    numbers = {'additional_requested_bytes', 'charged_bytes', 'limit_bytes',
        'minimum_filesystem_free_bytes', 'observed_apparent_bytes', 'outstanding_full_reservations_bytes'}
    need(type(usage) is dict and set(usage) == numbers | {'inventory', 'scope'}
        and usage['scope'] == 'named_roots_only_apparent_bytes'
        and all(type(usage[key]) is int and 0 <= usage[key] < 2**63 for key in numbers)
        and usage['additional_requested_bytes'] == value['storage_bytes']
        and usage['charged_bytes'] == usage['observed_apparent_bytes']
            + usage['outstanding_full_reservations_bytes'] + usage['additional_requested_bytes']
        and usage['limit_bytes'] == reservation['storage_limit_bytes']
        and type(usage['inventory']) is dict and set(usage['inventory']) ==
            {'apparent_bytes', 'entry_count', 'special_file_count', 'symlink_count'}
        and all(type(item) is int and 0 <= item < 2**63 for item in usage['inventory'].values())
        and usage['inventory']['apparent_bytes'] == usage['observed_apparent_bytes'])
    need(type(lease) is dict and set(lease) == {'lease_id', 'lane', 'owner_pid', 'parent_lease_id',
        'cpu_slots', 'memory_mb', 'child_process_slots', 'gpu_memory_mb', 'unified_memory_mb',
        'requires_gpu', 'acquired_at', 'wait_seconds', 'released', 'cancelled'}
        and identifier(lease['lease_id']) and lease['lane'] == 'validation'
        and type(lease['owner_pid']) is int and lease['owner_pid'] == owner_pid
        and lease['parent_lease_id'] is None and lease['released'] is True and lease['cancelled'] is True
        and lease['requires_gpu'] is False
        and all(type(lease[key]) is int and lease[key] == 0 for key in ('gpu_memory_mb', 'unified_memory_mb'))
        and all(type(lease[key]) is int and lease[key] == value[key]
            for key in ('cpu_slots', 'memory_mb', 'child_process_slots'))
        and all(type(lease[key]) in (int, float) and math.isfinite(lease[key]) and lease[key] >= 0
            for key in ('acquired_at', 'wait_seconds'))
        and lease['acquired_at'] >= row['created_at']
        and witness['resource_request_id'] == 'validation:' + row['reservation_id']
        and witness['scheduler'] == {'state_path': value['scheduler_state_path'],
            'policy_sha256': value['expected_scheduler_policy_sha256'], 'lane': 'validation',
            'workload': 'canonical_validation'})
    if request_version == 'v5':
        scratch = reservation['ordinary_scratch_profile']
        need(type(scratch) is dict and set(scratch) == {'schema', 'request_sha256',
            'ordinary_absences_observed', 'live_exception_active', 'unseen_leaf_ownership_attested',
            'whole_census_resampling'}
            and scratch['schema'] == 'owned-validation-ordinary-scratch-live/v1'
            and scratch['request_sha256'] == expected_request_sha256
            and type(scratch['ordinary_absences_observed']) is int
            and scratch['ordinary_absences_observed'] == 0
            and all(scratch[key] is False for key in ('live_exception_active',
                'unseen_leaf_ownership_attested', 'whole_census_resampling')))
    if request_version == 'v6':
        _live_no_native_sdk_receipt(value, request_raw, expected_request_sha256, reservation, need)
        clock = _startup_clock_no_child_observation(value, reservation, expected_request_sha256, need)
        need(clock['original_owner'].get('pid') == owner_pid
             and clock['original_owner'].get('birth') == owner_birth)
    return value, witness, reservation, row, lease


def _no_child_native_closed_profile_v1(terminal, request_raw, *,
        expected_request_sha256, owner_pid, owner_birth, returncode, expected_resource_ledger):
    """Preserve the original explicit v1 pre-child acquired-and-closed gate."""
    return _no_child_native_closed_profile(terminal, request_raw, request_version='v1',
        expected_request_sha256=expected_request_sha256, owner_pid=owner_pid,
        owner_birth=owner_birth, returncode=returncode, expected_resource_ledger=expected_resource_ledger)


def _no_child_native_closed_profile_v5(terminal, request_raw, *,
        expected_request_sha256, owner_pid, owner_birth, returncode, expected_resource_ledger):
    """Bind original V5 SDK-open deadline or ledger-lock DATA without normalization."""
    return _no_child_native_closed_profile(terminal, request_raw, request_version='v5',
        expected_request_sha256=expected_request_sha256, owner_pid=owner_pid,
        owner_birth=owner_birth, returncode=returncode, expected_resource_ledger=expected_resource_ledger)


def inspect_owned_validation_no_child_native_closed_v1(terminal, request_raw, *,
        expected_request_sha256, owner_pid, owner_birth, returncode, expected_resource_ledger,
        cleanup_timeout_seconds=5):
    """Observe explicit v1 closure after the original caller genuinely waits.

    Source READ remains held; no grant, state write or storage release occurs.
    """
    return _inspect_owned_validation_no_child_native_closed(terminal, request_raw,
        profile=_no_child_native_closed_profile_v1, expected_request_sha256=expected_request_sha256,
        owner_pid=owner_pid, owner_birth=owner_birth, returncode=returncode,
        expected_resource_ledger=expected_resource_ledger, cleanup_timeout_seconds=cleanup_timeout_seconds)


def inspect_owned_validation_no_child_native_closed_v5(terminal, request_raw, *,
        expected_request_sha256, owner_pid, owner_birth, returncode, expected_resource_ledger,
        cleanup_timeout_seconds=5):
    """Observe exact acquired-no-child V5 closure after a genuine original wait.

    Only the original Source-held Popen caller may use this observation to close
    its reads. It neither qualifies a vanished caller nor releases retained
    storage. Original bytes and typed zero-sample deadline/ledger-lock evidence stay intact.
    Current PID/root/row/source and locked Native checks are shared with v1.
    """
    return _inspect_owned_validation_no_child_native_closed(terminal, request_raw,
        profile=_no_child_native_closed_profile_v5, expected_request_sha256=expected_request_sha256,
        owner_pid=owner_pid, owner_birth=owner_birth, returncode=returncode,
        expected_resource_ledger=expected_resource_ledger, cleanup_timeout_seconds=cleanup_timeout_seconds)



def wait_and_inspect_owned_validation_no_child_native_closed_v5(process, terminal, request_raw, *,
        expected_request_sha256, owner_birth, expected_resource_ledger,
        original_wait_deadline_monotonic):
    """Future original Source-held caller integration; never closes Source here.

    Call with the original Popen and its original absolute wait cutoff before
    the productive observed-identity-count branch. This performs the genuine
    wait itself, then observes only explicit V5 no-child Native closure. An
    exhausted cutoff, failed binding or uncertain wait remains unknown, without
    signals, retries, replacement owners, state writes or storage release.
    A vanished historical caller cannot be reconstructed with this function.
    """
    unknown = dict(verdict='requires_original_native_cleanup', source_custody_closed=False,
                   storage_release_authorized=False)
    try:
        if (type(process) is not subprocess.Popen
                or type(original_wait_deadline_monotonic) not in (int, float)
                or not math.isfinite(original_wait_deadline_monotonic)):
            return unknown
        original_remaining = original_wait_deadline_monotonic - time.monotonic()
        if not 0 < original_remaining <= 3600:
            return unknown
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as native
        previous = native.resource_operation_deadline()
        end = original_wait_deadline_monotonic
        if previous is not None:
            end = min(end, previous.native_deadline_monotonic)
        # Waiting is cleanup too: it must honor an earlier existing parent
        # lifetime before Popen.wait starts, without renewing either clock.
        remaining = end - time.monotonic()
        if remaining <= 0:
            return unknown
        returncode = process.wait(timeout=remaining)
        remaining = end - time.monotonic()
        if type(returncode) is not int or returncode != 1 or remaining <= 0:
            return unknown
        value, _, _, _, _ = _no_child_native_closed_profile_v5(terminal, request_raw,
            expected_request_sha256=expected_request_sha256, owner_pid=process.pid,
            owner_birth=owner_birth, returncode=returncode,
            expected_resource_ledger=expected_resource_ledger)
        _lifecycle_source_guard(value)
        remaining = end - time.monotonic()
        if remaining <= 0:
            return unknown
        with native.resource_cleanup_deadline(native_deadline_monotonic=end):
            verdict = inspect_owned_validation_no_child_native_closed_v5(terminal, request_raw,
                expected_request_sha256=expected_request_sha256, owner_pid=process.pid,
                owner_birth=owner_birth, returncode=returncode,
                expected_resource_ledger=expected_resource_ledger,
                cleanup_timeout_seconds=min(5, remaining))
            if time.monotonic() >= end:
                return unknown
            return verdict
    except BaseException:
        return unknown


def _inspect_owned_validation_no_child_native_closed(terminal, request_raw, *, profile,
        expected_request_sha256, owner_pid, owner_birth, returncode, expected_resource_ledger,
        cleanup_timeout_seconds):
    """Shared current absence observation, with no authority from sampled DATA."""
    unknown = dict(verdict='requires_original_native_cleanup', source_custody_closed=False,
                   storage_release_authorized=False)
    try:
        def need(condition):
            if not condition:
                raise ValueError('unproven current no-child native closure')
        need(type(cleanup_timeout_seconds) in (int, float) and math.isfinite(cleanup_timeout_seconds)
            and 0 < cleanup_timeout_seconds <= 10)
        value, witness, reservation, row, lease = profile(terminal,
            request_raw, expected_request_sha256=expected_request_sha256, owner_pid=owner_pid,
            owner_birth=owner_birth, returncode=returncode, expected_resource_ledger=expected_resource_ledger)
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as host
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import existing_resource_scheduler as existing
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as native
        end = time.monotonic() + cleanup_timeout_seconds
        previous = native.resource_operation_deadline()
        if previous is not None:
            end = min(end, previous.native_deadline_monotonic)
        with native.resource_cleanup_deadline(native_deadline_monotonic=end):
            producer = str(Path(__file__).resolve())
            need(witness['producer'] == {'path': producer, 'sha256': value['source_sha256'].get(producer)})
            _lifecycle_source_guard(value)
            if profile is _no_child_native_closed_profile_v5:
                # Reuse only the existing SDK decoder/origin and ordinary
                # diagnostic authentication; it supplies no Native-absence fact.
                _ordinary_scratch_no_native_sdk_receipt(value, request_raw,
                    expected_request_sha256, reservation, need)
            if profile is _no_child_native_closed_profile_v6:
                _live_no_native_sdk_receipt(value, request_raw, expected_request_sha256, reservation, need)
            directory = Path(value['attempt_directory'])
            def stopped():
                native._check_resource_operation_deadline()
                need(host._process(owner_pid) is None)
                need(host._root_identity(directory) == row['attempt_directory'])
                with os.scandir(directory) as entries:
                    need(next(entries, None) is None)
                need(host._root_identity(directory) == row['attempt_directory'])
                ledger = json.loads(snapshot(expected_resource_ledger, 16*1024*1024), object_pairs_hook=host._json_pairs)
                need(type(ledger) is dict and set(ledger) == {'schema', 'roots', 'limit_bytes', 'reservations'}
                    and ledger['schema'] == host.SCHEMA
                    and type(ledger['limit_bytes']) is int
                    and ledger['limit_bytes'] == reservation['storage_limit_bytes'] == host.MAX_STORAGE_BYTES
                    and json.dumps(ledger['roots'], sort_keys=True, allow_nan=False) ==
                        json.dumps(reservation['roots'], sort_keys=True, allow_nan=False)
                    and json.dumps(ledger['roots'], sort_keys=True, allow_nan=False) ==
                        json.dumps([host._root_identity(Path(path)) for path in value['roots']], sort_keys=True)
                    and type(ledger['reservations']) is dict
                    and json.dumps(ledger['reservations'].get(row['reservation_id']), sort_keys=True, allow_nan=False) ==
                        json.dumps(row, sort_keys=True, allow_nan=False))
                _lifecycle_source_guard(value)
                native._check_resource_operation_deadline()
            stopped()
            scheduler = existing.open_existing_scheduler(value['scheduler_state_path'],
                value['expected_scheduler_policy_sha256'], inspection_only=True)
            observed = scheduler.inspect_lease(lease['lease_id'], expected_request_id=witness['resource_request_id'],
                expected_lane='validation', expected_owner_pid=owner_pid, expected_owner_birth_marker=owner_birth,
                bounded_lock_timeout=min(1, cleanup_timeout_seconds))
            need(observed.get('status') == 'absent' and type(observed.get('descendant_count')) is int
                and observed['descendant_count'] == 0)
            with scheduler._locked_state(persist=False, strict_existing=True) as state:
                for kind in ('leases', 'waiters'):
                    entries = state.get(kind)
                    need(type(entries) is dict and len(entries) <= 16384)
                    for key, item in entries.items():
                        native._check_resource_operation_deadline()
                        need(type(key) is str and type(item) is dict
                            and key != lease['lease_id'] and item.get('lease_id') != lease['lease_id']
                            and item.get('parent_lease_id') != lease['lease_id']
                            and item.get('request_id') != witness['resource_request_id'])
                stopped()
            return dict(verdict='proven_original_no_child_native_closed', source_custody_closed=True,
                        storage_release_authorized=False)
    except BaseException:
        return unknown



def _productive_cleanup_diagnostic_v1(reservation, expected_resource_ledger):
    """Validate serialized diagnostic DATA, without attesting an unseen cause."""
    if (reservation['cleanup_failure_observation_overflow'] is not False
            or type(reservation['cleanup_failure_observations']) is not list
            or len(reservation['cleanup_failure_observations']) != 1):
        return False
    diagnostic = reservation['cleanup_failure_observations'][0]
    kinds = {'DaemonResourceError':'daemon_resource_error',
        'ResourceAdmissionDeadlineError':'resource_deadline','OSError':'os_error','RuntimeError':'unknown_error'}
    if (type(diagnostic) is not dict or set(diagnostic) != {'schema','stage','error_kind','reason_code',
            'lock_observation_status','lock_observation'}
            or diagnostic['schema'] != 'owned-resource-cleanup-failure/v1'
            or diagnostic['stage'] != 'failure_retention'
            or diagnostic['error_kind'] != kinds.get(reservation['cleanup_error'])):
        return False
    status, offered = diagnostic['lock_observation_status'], diagnostic['lock_observation']
    if status in ('absent','rejected'):
        return diagnostic['reason_code'] == 'unclassified' and offered is None
    if (status != 'accepted' or diagnostic['reason_code'] != 'ledger_lock_unavailable'
            or diagnostic['error_kind'] != 'daemon_resource_error'
            or type(offered) is not dict or set(offered) != {'schema','stage','lock_path',
                'opened_lock_identity','configured_lock_timeout_seconds','started_monotonic',
                'deadline_monotonic','observed_monotonic','lock_acquired','holder_identity_established'}
            or offered['schema'] != 'daemon-resource-ledger-lock-timeout/v1'
            or offered['stage'] != 'exclusive_acquire_before_yield'
            or offered['lock_path'] != expected_resource_ledger+'.lock'
            or offered['lock_acquired'] is not False or offered['holder_identity_established'] is not False):
        return False
    identity = offered['opened_lock_identity']
    if (type(identity) is not dict or set(identity) != {'st_dev','st_ino','st_mode','st_uid','st_gid',
            'st_nlink','st_size','st_mtime_ns','st_ctime_ns'}
            or not all(type(item) is int and 0 <= item < 2**63 for item in identity.values())
            or identity['st_dev'] <= 0 or identity['st_ino'] <= 0 or not stat.S_ISREG(identity['st_mode'])
            or identity['st_nlink'] != 1 or identity['st_uid'] != os.geteuid()):
        return False
    fields = ('configured_lock_timeout_seconds','started_monotonic','deadline_monotonic','observed_monotonic')
    if not all(type(offered[key]) in (int,float) and math.isfinite(offered[key])
            and 0 <= offered[key] < 2**63 for key in fields):
        return False
    timeout,started,deadline,observed = (offered[key] for key in fields)
    return timeout <= 60 and started <= deadline <= observed and deadline-started <= timeout+1e-6


def _attached_native_closed_profile_v1(terminal, request_raw, *,
        expected_request_sha256, owner_pid, owner_birth, returncode, expected_resource_ledger, cleanup_profile=None):
    """Closed V5 attached-child bindings; no mutation or cleanup authority.

    The default is the unchanged productive ACTIVE profile. The explicit
    cancelled-retained and failed-retained profiles use their exact shapes; neither
    projects a retained frame into the ACTIVE or no-child profiles. Genuine
    original wait and current Native/process absence remain caller/inspector
    prerequisites, independently of any qualified worker report.
    """
    def need(condition):
        if not condition:
            raise ValueError('unproven original productive lifecycle')
    need(cleanup_profile is None or
        (type(cleanup_profile) is str and cleanup_profile in ('cancelled_retained_v5', 'failed_retained_v5')))
    cancelled = cleanup_profile == 'cancelled_retained_v5'
    retained = cleanup_profile is not None
    retained_status = 'retained' if retained else 'active'
    remaining_nodes = 65536
    def exact_json(item, depth=0):
        nonlocal remaining_nodes
        remaining_nodes -= 1
        need(depth <= 32 and remaining_nodes >= 0)
        if item is None or type(item) in (str, bool, int):
            return
        if type(item) is float:
            need(math.isfinite(item));return
        if type(item) is list:
            need(len(item) <= 16384)
            for entry in item: exact_json(entry, depth+1)
            return
        need(type(item) is dict and len(item) <= 16384
            and all(type(key) is str for key in item))
        for entry in item.values(): exact_json(entry, depth+1)
    def digest(item):
        return type(item) is str and len(item) == 64 and all(c in '0123456789abcdef' for c in item)
    def identifier(item):
        return type(item) is str and len(item) == 32 and digest(item+item)
    def integer(item):
        return type(item) is int and 0 < item < 2**63
    def same(left, right):
        return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)
    need(type(request_raw) is bytes and 0 < len(request_raw) <= 1024*1024
        and digest(expected_request_sha256) and hashlib.sha256(request_raw).hexdigest() == expected_request_sha256
        and integer(owner_pid) and type(owner_birth) is str and owner_birth.isdecimal()
        and type(returncode) is int and returncode == 1
        and type(expected_resource_ledger) is str and Path(expected_resource_ledger).is_absolute())
    value = json.loads(request_raw)
    need(_ordinary_scratch_no_child_request_shape(value, request_raw))
    if retained:
        budgets = {'cpu_slots':1, 'memory_mb':1536, 'child_process_slots':4,
            'storage_bytes':16777216, 'timeout_seconds':300}
        need(all(type(value[key]) is int and value[key] == expected
            for key, expected in budgets.items()))
    exact_json(terminal)
    need(len(json.dumps(terminal, sort_keys=True, allow_nan=False).encode()) <= 1024*1024
        and type(terminal) is dict and set(terminal) == {'schema','request_sha256','completed',
            'admitted','Lean_admitted','failure','reservation','process_cleanup_error','owner_exit_error',
            'source_custody_lifecycle'}
        and terminal['schema'] == 'owned-validation-failure-terminal/v1'
        and terminal['request_sha256'] == expected_request_sha256
        and all(terminal[key] is False for key in ('completed','admitted','Lean_admitted'))
        and terminal['process_cleanup_error'] is None and terminal['owner_exit_error'] is None)
    failure, reservation, witness = (terminal[key] for key in ('failure','reservation','source_custody_lifecycle'))
    need(type(failure) is dict and set(failure) == {'schema','request_sha256','executed_checks',
        'returncode','completed','admitted','Lean_admitted','resource_scope','model_weights_downloaded',
        'authority_granted','error_type','error','elapsed_seconds','watchdog_errors','received_signals',
        'process_observation','process_cleanup_error'}
        and failure['schema'] == 'owned-validation-result/v1'
        and failure['request_sha256'] == expected_request_sha256
        and failure['error_type'] == 'RuntimeError'
        and ((failure['executed_checks'] == [] and failure['returncode'] is None
              and failure['error'] == 'validation cancelled: []'
              and type(failure['received_signals']) is list
              and len(failure['received_signals']) == 1
              and type(failure['received_signals'][0]) is int
              and failure['received_signals'][0] == 15)
             if cancelled else
             (same(failure['executed_checks'], value['selected_checks'])
              and type(failure['returncode']) is int and failure['returncode'] != 0
              and failure['error'] == 'validation command failed with returncode '+str(failure['returncode'])
              and failure['received_signals'] == []))
        and all(failure[key] is False for key in ('completed','admitted','Lean_admitted',
            'authority_granted','model_weights_downloaded'))
        and failure['watchdog_errors'] == []
        and failure['process_cleanup_error'] is None
        and type(failure['elapsed_seconds']) in (int,float) and math.isfinite(failure['elapsed_seconds'])
        and 0 <= failure['elapsed_seconds'] < 2**63
        and failure['resource_scope'] == 'cooperative_sampled_birth_bound_descendants_and_owned_attempt')
    reservation_fields = {'schema','ledger_path','reservation_id','status','record',
        'resource_lease','process_observation','cleanup_error','roots','scheduler_lane',
        'workload','storage_limit_bytes','enforcement','ordinary_scratch_profile'}
    if not retained:
        reservation_fields |= {'cleanup_failure_observations','cleanup_failure_observation_overflow'}
    need(type(reservation) is dict and set(reservation) == reservation_fields
        and reservation['schema'] == 'daemon-resource-reservations-v1'
        and reservation['status'] == retained_status
        and (reservation['cleanup_error'] is None if retained else
             reservation['cleanup_error'] in
             ('DaemonResourceError','ResourceAdmissionDeadlineError','OSError','RuntimeError'))
        and reservation['ledger_path'] == expected_resource_ledger
        and reservation['scheduler_lane'] == 'validation' and reservation['workload'] == 'canonical_validation'
        and type(reservation['storage_limit_bytes']) is int and reservation['storage_limit_bytes'] > 0
        and reservation['enforcement'] == 'cooperative_admission_and_polled_usage_not_kernel_quota'
        and (retained or reservation['cleanup_failure_observation_overflow'] is False))
    diagnostics = None
    if not retained:
        diagnostics = reservation['cleanup_failure_observations']
        need(type(diagnostics) is list and len(diagnostics) == 1)
        diagnostic = diagnostics[0]
        need(type(diagnostic) is dict and set(diagnostic) == {'schema','stage','error_kind','reason_code',
            'lock_observation_status','lock_observation'}
            and diagnostic['schema'] == 'owned-resource-cleanup-failure/v1'
            and diagnostic['stage'] == 'failure_retention'
            and diagnostic['error_kind'] in ('resource_deadline','daemon_resource_error','os_error','unknown_error')
            and diagnostic['reason_code'] in ('unclassified','ledger_lock_unavailable')
            and diagnostic['lock_observation_status'] in ('absent','rejected','accepted')
            and _productive_cleanup_diagnostic_v1(reservation, expected_resource_ledger))
    need(type(witness) is dict and set(witness) == {'schema','request_sha256','producer','owner',
        'reservation_id','resource_request_id','ledger_path','scheduler','attempt_directory','outputs',
        'budgets','process_scope','events','owner_child_attached','native_grant','source_guards','storage'}
        and witness['schema'] == LIFECYCLE_SCHEMA and witness['request_sha256'] == expected_request_sha256
        and witness['owner'] == {'pid':owner_pid,'birth':owner_birth}
        and type(witness['owner']['pid']) is int and witness['owner_child_attached'] is True
        and type(witness['events']) is dict and set(witness['events']) == _LIFECYCLE_EVENTS
        and all(flag is True for flag in witness['events'].values())
        and witness['native_grant'] == {'status':'acquired','exact_native_timeout':False,'timeout_decision':None}
        and witness['native_grant']['exact_native_timeout'] is False
        and witness['source_guards'] == {'request_unchanged':True,'source_pins_unchanged':True,
            'owner_identity_unchanged':True,'errors':[]}
        and all(witness['source_guards'][key] is True for key in
            ('request_unchanged','source_pins_unchanged','owner_identity_unchanged'))
        and witness['ledger_path'] == expected_resource_ledger)
    producer = str(Path(__file__).resolve())
    need(witness['producer'] == {'path':producer,'sha256':value['source_sha256'].get(producer)}
        and digest(value['source_sha256'].get(producer)))
    row, lease, observation = (reservation[key] for key in ('record','resource_lease','process_observation'))
    row_fields = {'reservation_id','status','owner_pid','storage_bytes','memory_mb','cpu_slots',
        'child_process_slots','external_charges','created_at','prior_children','child',
        'artifacts_durable_asserted','scheduler_lane','workload','attempt_directory','last_usage',
        'native_lease_id','outputs','owner_birth','process_scope','scheduler_policy_sha256',
        'scheduler_state_path','validation_request_sha256'}
    if retained:
        row_fields.add('retention_reason')
    need(type(row) is dict and set(row) == row_fields
        and identifier(row['reservation_id'])
        and row['reservation_id'] == reservation['reservation_id'] == witness['reservation_id']
        and row['status'] == retained_status
        and (not retained or row['retention_reason'] == 'context_failed')
        and row['owner_pid'] == owner_pid and type(row['owner_pid']) is int
        and row['owner_birth'] == owner_birth and row['artifacts_durable_asserted'] is False
        and row['prior_children'] == [] and row['external_charges'] == {}
        and row['process_scope'] == witness['process_scope'] == value['process_scope']
        and row['scheduler_lane'] == 'validation' and row['workload'] == 'canonical_validation'
        and row['scheduler_state_path'] == value['scheduler_state_path']
        and row['scheduler_policy_sha256'] == value['expected_scheduler_policy_sha256']
        and row['validation_request_sha256'] == expected_request_sha256
        and type(row['attempt_directory']) is dict and set(row['attempt_directory']) == {'path','device','inode'}
        and row['attempt_directory']['path'] == witness['attempt_directory'] == value['attempt_directory']
        and all(integer(row['attempt_directory'][key]) for key in ('device','inode'))
        and type(row['child']) is dict and set(row['child']) == {'pid','birth'}
        and integer(row['child']['pid']) and row['child']['pid'] != owner_pid
        and type(row['child']['birth']) is str and row['child']['birth'].isdecimal()
        and type(row['last_usage']) is dict
        and type(row['created_at']) in (int,float) and math.isfinite(row['created_at']) and row['created_at'] > 0
        and same(row['outputs'], value['outputs']) and same(witness['outputs'],value['outputs']))
    budgets = ('cpu_slots','memory_mb','child_process_slots','storage_bytes')
    need(type(witness['budgets']) is dict and set(witness['budgets']) == set(budgets)
        and all(integer(row[key]) and type(witness['budgets'][key]) is int
            and row[key] == witness['budgets'][key] == value[key] for key in budgets)
        and witness['scheduler'] == {'state_path':value['scheduler_state_path'],
            'policy_sha256':value['expected_scheduler_policy_sha256'],'lane':'validation','workload':'canonical_validation'}
        and witness['resource_request_id'] == 'validation:'+row['reservation_id']
        and same(witness['storage'],
            {'status':'retained','cleanup_error':None,'release_authorized':False} if retained else
            {'status':'active','cleanup_error':reservation['cleanup_error'],
             'release_authorized':False,'cleanup_failure_observations':diagnostics,
             'cleanup_failure_observation_overflow':False}))
    need(type(lease) is dict and set(lease) == {'lease_id','lane','owner_pid','parent_lease_id',
        'cpu_slots','memory_mb','child_process_slots','gpu_memory_mb','unified_memory_mb','requires_gpu',
        'acquired_at','wait_seconds','released','cancelled'}
        and identifier(lease['lease_id']) and lease['lease_id'] == row['native_lease_id']
        and lease['lane'] == 'validation' and type(lease['owner_pid']) is int and lease['owner_pid'] == owner_pid
        and lease['parent_lease_id'] is None and lease['released'] is True and lease['cancelled'] is True
        and lease['requires_gpu'] is False
        and all(type(lease[key]) is int and lease[key] == 0 for key in ('gpu_memory_mb','unified_memory_mb'))
        and all(type(lease[key]) is int and lease[key] == value[key]
            for key in ('cpu_slots','memory_mb','child_process_slots'))
        and all(type(lease[key]) in (int,float) and math.isfinite(lease[key]) and lease[key] >= 0
            for key in ('acquired_at','wait_seconds')) and lease['acquired_at'] >= row['created_at'])
    need(type(observation) is dict and set(observation) == {'scope','group_rss','live_processes',
        'rss_bytes','observed_identities','out_of_group_live_identities','tracking_error'}
        and observation['scope'] == 'sampled_birth_bound_descendants'
        and type(observation['group_rss']) is dict and set(observation['group_rss']) ==
            {'available','live_processes','rss_bytes'} and observation['group_rss']['available'] is True
        and all(type(item[key]) is int and item[key] == 0 for item in
            (observation, observation['group_rss']) for key in ('live_processes','rss_bytes'))
        and observation['out_of_group_live_identities'] == [] and observation['tracking_error'] == ''
        and same(observation,failure['process_observation']))
    identities = observation['observed_identities']
    need(type(identities) is list and 0 < len(identities) <= 4096)
    by_pid = {}
    for identity in identities:
        need(type(identity) is dict and set(identity) == {'pid','birth_ticks','parent_pid',
            'process_group_id','session_id'} and all(integer(item) for item in identity.values())
            and identity['pid'] not in by_pid and identity['pid'] != owner_pid)
        by_pid[identity['pid']] = identity
    child = by_pid.get(row['child']['pid'])
    need(type(child) is dict and str(child['birth_ticks']) == row['child']['birth']
        and child['parent_pid'] == owner_pid
        and child['process_group_id'] == child['session_id'] == child['pid'])
    for identity in identities:
        seen, cursor = set(), identity['pid']
        while cursor != owner_pid:
            need(cursor in by_pid and cursor not in seen)
            seen.add(cursor);cursor = by_pid[cursor]['parent_pid']
    scratch = reservation['ordinary_scratch_profile']
    need(type(scratch) is dict and set(scratch) == {'schema','request_sha256','ordinary_absences_observed',
        'live_exception_active','unseen_leaf_ownership_attested','whole_census_resampling'}
        and scratch['schema'] == 'owned-validation-ordinary-scratch-live/v1'
        and scratch['request_sha256'] == expected_request_sha256
        and type(scratch['ordinary_absences_observed']) is int and 0 <= scratch['ordinary_absences_observed'] < 2**63
        and all(scratch[key] is False for key in
            ('live_exception_active','unseen_leaf_ownership_attested','whole_census_resampling')))
    return value, witness, reservation, row, lease


def _productive_native_closed_profile_v1(terminal, request_raw, *,
        expected_request_sha256, owner_pid, owner_birth, returncode, expected_resource_ledger):
    """Preserve the original strict ACTIVE productive-failure profile."""
    return _attached_native_closed_profile_v1(terminal, request_raw,
        expected_request_sha256=expected_request_sha256, owner_pid=owner_pid,
        owner_birth=owner_birth, returncode=returncode,
        expected_resource_ledger=expected_resource_ledger)


def _cancelled_retained_native_closed_profile_v5(terminal, request_raw, *,
        expected_request_sha256, owner_pid, owner_birth, returncode, expected_resource_ledger):
    """Strict cancelled RETAINED V5 bindings, without worker/test qualification.

    No qualified worker report is needed or granted. Empty reported checks do
    not establish whether any underlying calls started. This gate alone proves
    neither genuine wait nor current Native/process/Source closure.
    """
    return _attached_native_closed_profile_v1(terminal, request_raw,
        expected_request_sha256=expected_request_sha256, owner_pid=owner_pid,
        owner_birth=owner_birth, returncode=returncode,
        expected_resource_ledger=expected_resource_ledger,
        cleanup_profile='cancelled_retained_v5')


def _failed_retained_native_closed_profile_v5(terminal, request_raw, *,
        expected_request_sha256, owner_pid, owner_birth, returncode, expected_resource_ledger):
    """Strict completed-command RETAINED bindings, without report qualification.

    Reported selected checks are the CLI's command metadata, not observed test
    counts. Missing or present worker output supplies no acceptance or claim
    about which underlying calls began. Genuine wait and current closure are
    separate caller/inspector prerequisites; this parser supplies neither.
    """
    return _attached_native_closed_profile_v1(terminal, request_raw,
        expected_request_sha256=expected_request_sha256, owner_pid=owner_pid,
        owner_birth=owner_birth, returncode=returncode,
        expected_resource_ledger=expected_resource_ledger,
        cleanup_profile='failed_retained_v5')


def inspect_owned_validation_productive_native_closed_v1(terminal, request_raw, *,
        expected_request_sha256, owner_pid, owner_birth, returncode, expected_resource_ledger,
        original_wait_deadline_monotonic, cleanup_profile=None):
    """Inspect original sampled closure; storage remains ACTIVE or RETAINED.

    Caller prerequisites: genuine original Popen/wait, the same fixed original
    absolute cutoff (at most420s for the legacy ACTIVE path or360s for explicit
    RETAINED cleanup), and original Source READs held through this
    call and final source checks. Existing stable no-follow snapshots read only the
    selected row; unrelated foreign rows may advance between observations.
    No lock file, grant, retry, deadline, disk claim, census or fsync is created.
    Unknown wait/process/native/source/own-row facts retain Source custody.
    """
    unknown = dict(verdict='requires_original_native_cleanup', source_custody_closed=False,
                   storage_release_authorized=False)
    try:
        def need(condition):
            if not condition: raise ValueError('unproven productive native closure')
        need(cleanup_profile is None or
            (type(cleanup_profile) is str and cleanup_profile in ('cancelled_retained_v5', 'failed_retained_v5')))
        retained = cleanup_profile is not None
        observed_start = time.monotonic()
        need(type(original_wait_deadline_monotonic) in (int,float)
            and math.isfinite(original_wait_deadline_monotonic)
            and observed_start < original_wait_deadline_monotonic
            <= observed_start+(360 if retained else 420))
        binding = (_cancelled_retained_native_closed_profile_v5 if cleanup_profile == 'cancelled_retained_v5'
            else _failed_retained_native_closed_profile_v5 if cleanup_profile == 'failed_retained_v5'
            else _productive_native_closed_profile_v1)
        value, witness, reservation, row, lease = binding(terminal,
            request_raw, expected_request_sha256=expected_request_sha256, owner_pid=owner_pid,
            owner_birth=owner_birth, returncode=returncode, expected_resource_ledger=expected_resource_ledger)
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as host
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_resource_recovery as recovery
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as native
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import existing_resource_scheduler as existing
        directory = ROOT/'ipfs_datasets_py/optimizers/logic_theorem_optimizer'
        required = [str(directory/'autoencoder_resource_recovery.py'), str(ROOT/'ipfs_datasets_py/logic/backends/process.py')]
        need(all(type(value['source_sha256'].get(path)) is str for path in required)
            and recovery.resources is host and host.native_deadlines is native and existing.native is native)
        for module, name, functions in ((host,'autoencoder_daemon_resources.py',('_process','_group_usage','_root_identity','_json_pairs')),
                (recovery,'autoencoder_resource_recovery.py',('_sampled_open_scheduler','_sampled_stopped',
                    '_sampled_processes_stopped','_sampled_scheduler_absence','_sampled_scheduler_observation')),
                (existing,'existing_resource_scheduler.py',('open_existing_scheduler',))):
            path = str(directory/name)
            need(module.__file__ == path and module.__spec__.origin == path)
            for name in functions:
                function = getattr(module,name)
                function = getattr(function,'__wrapped__',function)
                need(function.__code__.co_filename == path and function.__globals__ is vars(module))
        end = original_wait_deadline_monotonic
        prior = native.resource_operation_deadline()
        if prior is not None: end = min(end,prior.native_deadline_monotonic)
        with native.resource_cleanup_deadline(native_deadline_monotonic=end):
            def current_own_row():
                native._check_resource_operation_deadline()
                def nonfinite(_): raise ValueError('nonfinite current disk ledger')
                need(Path(expected_resource_ledger).lstat().st_uid == os.geteuid())
                ledger = json.loads(snapshot(expected_resource_ledger,16*1024*1024),
                    object_pairs_hook=host._json_pairs,parse_constant=nonfinite)
                need(Path(expected_resource_ledger).lstat().st_uid == os.geteuid())
                roots = [host._root_identity(Path(path)) for path in value['roots']]
                need(type(ledger) is dict and set(ledger) == {'schema','roots','limit_bytes','reservations'}
                    and ledger['schema'] == host.SCHEMA
                    and type(ledger['limit_bytes']) is int
                    and ledger['limit_bytes'] == reservation['storage_limit_bytes'] == host.MAX_STORAGE_BYTES
                    and json.dumps(ledger['roots'],sort_keys=True,allow_nan=False)
                        == json.dumps(reservation['roots'],sort_keys=True,allow_nan=False)
                        == json.dumps(roots,sort_keys=True,allow_nan=False)
                    and type(ledger['reservations']) is dict and len(ledger['reservations']) <= host.MAX_RESERVATIONS
                    and json.dumps(ledger['reservations'].get(row['reservation_id']),sort_keys=True,allow_nan=False)
                        == json.dumps(row,sort_keys=True,allow_nan=False)
                    and host._root_identity(Path(value['attempt_directory'])) == row['attempt_directory'])
                native._check_resource_operation_deadline()
            _lifecycle_source_guard(value)
            current_own_row()
            profile = {'request':value,'record':row,'observation':reservation['process_observation']}
            recovery._sampled_open_scheduler(profile)
            scheduler = profile['scheduler']
            need(type(scheduler) is existing._PinnedGlobalResourceScheduler and scheduler._inspection_only is True
                and scheduler.state_path == Path(value['scheduler_state_path'])
                and scheduler._policy_sha256 == value['expected_scheduler_policy_sha256'])
            for method_name, owner_class, owner_module in (
                    ('inspect_lease',native.GlobalResourceScheduler,native),
                    ('_locked_state',existing._PinnedGlobalResourceScheduler,existing)):
                method = getattr(scheduler,method_name)
                expected = getattr(owner_class,method_name)
                need(method.__self__ is scheduler and method.__func__ is expected)
                function = getattr(expected,'__wrapped__',expected)
                need(function.__globals__ is vars(owner_module)
                    and function.__code__.co_filename == str(directory/Path(owner_module.__file__).name))
            recovery._sampled_stopped(profile)
            current_own_row()
            with recovery._sampled_scheduler_absence(profile):
                recovery._sampled_processes_stopped(profile)
                current_own_row()
                _lifecycle_source_guard(value)
                recovery._sampled_processes_stopped(profile)
                current_own_row()
                native._check_resource_operation_deadline()
            return dict(verdict=('proven_original_cancelled_retained_native_closed'
                if cleanup_profile == 'cancelled_retained_v5' else 'proven_original_failed_retained_native_closed'
                if cleanup_profile == 'failed_retained_v5' else 'proven_original_productive_native_closed_storage_separate'),
                source_custody_closed=True,storage_release_authorized=False)
    except BaseException:
        return unknown



def child_main(path, digest):
    value, raw = request(path,digest)
    # This child has no productive writes or imports before its actual native
    # owner attaches the isolated PID/birth and refreshes custody after scanning.
    if sys.stdin.buffer.read(1) != b'1':
        raise ValueError('native validation startup barrier was not released')
    if snapshot(path) != raw:
        raise ValueError('validation request changed at startup barrier')
    source_guard(value)
    if str(Path.cwd()) != value['cwd']:
        raise ValueError('validation working directory differs')
    os.execvpe(value['argv'][0], value['argv'], dict(os.environ))


def _stop_original_group(child, birth):
    if child is None:
        return
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as host
    current = host._process(child.pid)
    if current is not None and current['birth'] != birth:
        raise RuntimeError('validation child PID was reused; refusing signal')
    identity = dict(pid=child.pid,birth=birth)
    for number in (signal.SIGTERM, signal.SIGKILL):
        if not host._group_usage(identity)['live_processes']:
            break
        try:
            os.killpg(child.pid,number)
        except ProcessLookupError:
            pass
        until = time.monotonic()+3
        while time.monotonic()<until:
            child.poll()
            if not host._group_usage(identity)['live_processes']:
                break
            time.sleep(.05)
    child.wait(timeout=5)
    if host._group_usage(identity)['live_processes']:
        raise RuntimeError('validation group is still alive after cleanup')


def stop_and_reap(child, birth, owner=None):
    """Drain the original group and this owner's explicit descendant scope."""
    errors = []
    if owner is not None and owner.tracks_descendants:
        try:
            # Capture before SIGTERM can reparent nested Lake/Lean sessions.
            owner.observe_processes()
        except BaseException as error:
            errors.append("observe descendants: " + type(error).__name__ + ": " + str(error))
    try:
        _stop_original_group(child, birth)
    except BaseException as error:
        errors.append("stop original group: " + type(error).__name__ + ": " + str(error))
    if owner is not None and owner.tracks_descendants:
        try:
            owner.drain_tracked_descendants()
        except BaseException as error:
            errors.append("drain descendants: " + type(error).__name__ + ": " + str(error))
    if errors:
        raise RuntimeError("owned validation process cleanup unresolved: " + "; ".join(errors))


def _validation_watchdog_shutdown_observation(monitor, finished, state, *,
        request_sha256, phase, owner=None, observer_stop=None):
    """Bounded diagnostic only: no locals, closure proof or resource authority."""
    now = time.monotonic()
    stage, started = state.get('phase', ('unknown', now))
    observation = {
        'schema': 'owned-validation-watchdog-shutdown-observation/v1',
        'request_sha256': request_sha256, 'phase': phase,
        'finished_event_set': finished.is_set(), 'join_timeout_seconds': 5,
        'monitor_alive': monitor.is_alive(), 'monitor_ident': monitor.ident,
        'monitor_native_id': monitor.native_id,
        'observed_at_monotonic': now, 'stage': stage,
        'stage_elapsed_seconds': max(0.0, now - started),
        'stack': [], 'stack_truncated': False,
        'scope': 'local_watcher_observation_only', 'authority_granted': False,
    }
    if observer_stop is not None:
        observation['sdk_observation'] = owner._local_observation_diagnostic(observer_stop)
    frame = sys._current_frames().get(monitor.ident)
    try:
        while frame is not None and len(observation['stack']) < 16:
            code = frame.f_code
            observation['stack'].append({
                'file': code.co_filename.replace('\x00', '')[:512],
                'function': code.co_qualname.replace('\x00', '')[:128],
                'line': frame.f_lineno})
            frame = frame.f_back
        observation['stack_truncated'] = frame is not None
    finally:
        del frame
    return observation


def _report_validation_watchdog_shutdown(monitor, finished, state, *,
        request_sha256, phase, owner=None, observer_stop=None):
    # Diagnostic publication cannot replace an original resource exception or
    # change the existing stdout terminal's closed record schema.
    try:
        value = _validation_watchdog_shutdown_observation(monitor, finished, state,
            request_sha256=request_sha256, phase=phase, owner=owner, observer_stop=observer_stop)
        print(json.dumps(value, sort_keys=True, allow_nan=False), file=sys.stderr, flush=True)
    except BaseException:
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request',required=True,type=Path)
    parser.add_argument('--expected-request-sha256',required=True)
    parser.add_argument('--resource-ledger',type=Path)
    parser.add_argument('--_child',action='store_true',help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args._child:
        child_main(args.request,args.expected_request_sha256)
        return 0
    if args.resource_ledger is None:
        parser.error('--resource-ledger is required for native ownership')
    value, raw = request(args.request,args.expected_request_sha256)
    if value['schema'] in ('owned-validation-request/v5', STARTUP_CLOCK_REQUEST_SCHEMA):
        _lifecycle_source_guard(value)
    else:
        source_guard(value)
        script = str(Path(__file__).resolve())
        if value['source_sha256'].get(script) != hashlib.sha256(snapshot(script,4*1024*1024)).hexdigest():
            raise ValueError('launcher source must be explicitly pinned')
    # Resolve the source tree from this script, before importing the package.
    # Never reuse a package imported from the editable HACC installation.
    if 'ipfs_datasets_py' in sys.modules:
        raise RuntimeError('run owned validation in a fresh process')
    sys.path.insert(0,str(ROOT))
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.validation_run_resources import (
        ValidationResourceReservation, LocalValidationObservationStopped)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as host
    if Path(host.__file__).resolve() != ROOT/'ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_daemon_resources.py':
        raise RuntimeError('different native resource tree loaded')
    ledger = json.loads(snapshot(args.resource_ledger,16*1024*1024))
    try:
        owner = ValidationResourceReservation(args.resource_ledger,roots=[row['path'] for row in ledger['roots']],
            attempt_directory=value['attempt_directory'],storage_bytes=value['storage_bytes'],
            memory_mb=value['memory_mb'],cpu_slots=value['cpu_slots'],child_process_slots=value['child_process_slots'],
            scheduler_state_path=value['scheduler_state_path'],
            expected_scheduler_policy_sha256=value['expected_scheduler_policy_sha256'],
            validation_manifest_path=args.request,frozen_validation_manifest_sha256=args.expected_request_sha256,
            timeout_seconds=value['timeout_seconds'])
    except BaseException as error:
        # This branch precedes owner.open, signal handlers and every child path.
        # Keep the original exception/exit while publishing bounded typed facts.
        try:
            print(json.dumps(_pre_owner_refusal_terminal(value, raw, args.request,
                args.expected_request_sha256, args.resource_ledger, error)), flush=True)
        except BaseException as reporting_error:
            try:
                print('Failed to report original validation pre-owner refusal: ' +
                    type(reporting_error).__name__, file=sys.stderr, flush=True)
            except BaseException:
                pass
        raise
    cancelled = threading.Event()
    errors = []
    finished = threading.Event()
    child = birth = monitor = None
    failure = None
    observer_stop = None
    watchdog_state = {'phase': ('not_started', time.monotonic())}
    watchdog_stop_error = None
    lifecycle_events = dict(owner_open_attempted=False, owner_open_returned=False,
        child_launch_attempted=False, child_created=False,
        barrier_release_attempted=False, barrier_released=False)
    interrupted = []
    def on_signal(number,frame):
        interrupted.append(number)
        cancelled.set()
    previous = {number:signal.signal(number,on_signal) for number in (signal.SIGTERM,signal.SIGINT)}
    started = time.monotonic()
    outcome = dict(schema='owned-validation-result/v1',request_sha256=args.expected_request_sha256,
        executed_checks=[],returncode=None,completed=False,admitted=False,Lean_admitted=False,
        resource_scope=('cooperative_isolated_process_group_and_owned_attempt'
                        if not owner.tracks_descendants else
                        'cooperative_sampled_birth_bound_descendants_and_owned_attempt'),
        model_weights_downloaded=False,authority_granted=False)
    try:
        lifecycle_events['owner_open_attempted'] = True
        try:
            owner.open()
        except host.DaemonResourceError as error:
            report_capacity_refusal(error)
            raise
        lifecycle_events['owner_open_returned'] = True
        startup_clock = value['schema'] == STARTUP_CLOCK_REQUEST_SCHEMA
        deadline = (owner.startup_clock_observation()['admission_deadline_monotonic']
                    if startup_clock else time.monotonic()+value['timeout_seconds'])
        if value['schema'] == 'owned-validation-request/v5':
            observer_stop = owner._new_local_observation_stop(finished)
        def guard():
            if snapshot(args.request) != raw:
                raise RuntimeError('validation request changed')
            source_guard(value)
            if cancelled.is_set():
                raise RuntimeError('validation cancelled: '+repr(errors))
            if startup_clock:
                clock = owner.startup_clock_observation()
                active_deadline = (clock['admission_deadline_monotonic'] if clock['productive_started_monotonic'] is None
                                   else clock['productive_deadline_monotonic'])
                if time.monotonic() >= min(active_deadline, clock['total_deadline_monotonic']):
                    raise TimeoutError('validation startup admission deadline exceeded'
                        if clock['productive_started_monotonic'] is None else 'validation deadline exceeded')
                owner.guard()
            elif time.monotonic()>=deadline:
                raise TimeoutError('validation deadline exceeded')
        def watch():
            try:
                while not finished.wait(.1):
                    watchdog_state['phase'] = ('source_guard', time.monotonic())
                    guard()
                    # Strictly local sampling stays responsive while the owner
                    # performs a separately serialized fresh global census.
                    watchdog_state['phase'] = ('local_limits', time.monotonic())
                    if observer_stop is None:
                        owner.check_limits(full=False)
                    else:
                        owner.check_limits(full=False, _observer_stop=observer_stop)
                    watchdog_state['phase'] = ('waiting_finished', time.monotonic())
                if observer_stop is not None:
                    # A very short child may finish between observations. It
                    # still requires the owner's real zero-process barrier.
                    owner._check_local_observation_stop(observer_stop)
            except LocalValidationObservationStopped as error:
                try:
                    if observer_stop is None:
                        raise RuntimeError('unscoped local observation stop') from error
                    owner._accept_local_observation_stop(error, observer_stop)
                    watchdog_state['phase'] = ('stopped_after_zero_process_barrier', time.monotonic())
                except BaseException as refusal:
                    errors.append(type(refusal).__name__+': '+str(refusal))
                    cancelled.set()
            except BaseException as error:
                errors.append(type(error).__name__+': '+str(error))
                cancelled.set()
        monitor = threading.Thread(target=watch,name='owned-validation-local-watchdog',daemon=True)
        monitor.start()
        stdout = Path(owner.output_layout['logs'])/'stdout.log'
        stderr = Path(owner.output_layout['logs'])/'stderr.log'
        with stdout.open('xb') as out,stderr.open('xb') as err:
            guard()
            if not owner.heartbeat() or owner.cancelled:
                raise RuntimeError('native validation lease lost before launch')
            lifecycle_events['child_launch_attempted'] = True
            child = subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),
                '--request',str(args.request),'--expected-request-sha256',args.expected_request_sha256,'--_child'],
                cwd=value['cwd'],env=dict(owner.environment(dict(os.environ)),
                    PYTHONPATH=os.pathsep.join([str(ROOT),value['cwd'],site.getusersitepackages()]),
                    PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1',
                    IPFS_DATASETS_PY_MINIMAL_IMPORTS='1',IPFS_DATASETS_AUTO_INSTALL='0',
                    IPFS_AUTO_INSTALL='false',TRANSFORMERS_OFFLINE='1'),stdin=subprocess.PIPE,
                stdout=out,stderr=err,start_new_session=True,
                umask=0o077 if value['schema'] in ('owned-validation-request/v2', 'owned-validation-request/v5') else -1)
            lifecycle_events['child_created'] = True
            identity = host._process(child.pid)
            if identity is None:
                raise RuntimeError('validation child exited before attachment')
            birth = identity['birth']
            owner.attach_child(child.pid)
            guard()
            if errors or not owner.heartbeat() or owner.cancelled:
                raise RuntimeError('native validation lease lost during attachment')
            if startup_clock:
                owner.start_productive_work(child.pid, birth)
                owner.require_productive_work()
            lifecycle_events['barrier_release_attempted'] = True
            child.stdin.write(b'1')
            child.stdin.flush()
            child.stdin.close()
            lifecycle_events['barrier_released'] = True
            next_global = time.monotonic()+300
            next_renewal = time.monotonic()+1
            while child.poll() is None:
                guard()
                if errors:
                    raise RuntimeError('validation custody or resource watchdog refused')
                if time.monotonic()>=next_renewal:
                    if not owner.heartbeat() or owner.cancelled:
                        raise RuntimeError('native validation lease lost')
                    next_renewal = time.monotonic()+1
                if time.monotonic()>=next_global:
                    owner.check_limits(full=True)
                    next_global = time.monotonic()+300
                time.sleep(.1)
            guard()
            if errors:
                raise RuntimeError('validation resource watchdog refused: '+repr(errors))
            outcome.update(returncode=child.returncode,executed_checks=list(value['selected_checks']))
            if child.returncode != 0:
                raise RuntimeError('validation command failed with returncode '+str(child.returncode))
        stop_and_reap(child,birth,owner)
        if observer_stop is not None:
            owner._stop_local_observation(observer_stop)
        finished.set()
        monitor.join(timeout=5)
        guard()
        if monitor.is_alive() or errors:
            _report_validation_watchdog_shutdown(monitor, finished, watchdog_state,
                request_sha256=args.expected_request_sha256, phase='success_join',
                owner=owner, observer_stop=observer_stop)
            raise RuntimeError('validation watchdog did not finish cleanly')
        if owner.tracks_descendants:
            outcome["process_observation"] = owner.observe_processes()
        outcome.update(completed=True,elapsed_seconds=time.monotonic()-started)
        execution_path=Path(owner.output_layout['logs'])/'execution.json'
        immutable_json(execution_path,outcome)
        evidence=[str(path) for path in (stdout,stderr,execution_path) if path.stat().st_size>0]
        sealed_result=dict(schema='owned-validation-result/v1',request_sha256=args.expected_request_sha256,
            executed_checks=outcome['executed_checks'],returncode=outcome['returncode'],
            completed=True,evidence_paths=evidence)
        result_path = Path(owner.output_layout['logs'])/'result.json'
        immutable_json(result_path,sealed_result)
        owner.seal_results(result_path)
        final = owner.finalize(artifacts_durable=True)
        print(json.dumps(dict(result=str(result_path),reservation=final,admitted=False)))
        return 0
    except BaseException as error:
        failure = error
        if lifecycle_events['owner_open_returned'] is True:
            try:
                report_capacity_refusal(error, stage='post_owner_open')
            except BaseException:
                # Reporting cannot replace the original post-admission failure.
                pass
        outcome.update(completed=False,error_type=type(error).__name__,error=str(error),
            elapsed_seconds=time.monotonic()-started,watchdog_errors=list(errors),
            received_signals=list(interrupted))
        raise
    finally:
        # Legacy order stays unchanged. The explicit V5 observer must obtain
        # its real zero-process proof before setting the finished event.
        if observer_stop is None:
            finished.set()
            if monitor is not None:
                monitor.join(timeout=5)
        cleanup_error = None
        try:
            if child is not None and birth is not None:
                stop_and_reap(child,birth,owner)
        except BaseException as error:
            cleanup_error = error
        if observer_stop is not None:
            try:
                if cleanup_error is None:
                    owner._stop_local_observation(observer_stop)
            except BaseException as error:
                watchdog_stop_error = error
                if failure is not None:
                    failure.add_note('Local watcher shutdown remained unverified: ' +
                        type(error).__name__ + ': ' + str(error)[:1000])
            finally:
                finished.set()
            if monitor is not None:
                try:
                    monitor.join(timeout=5)
                except BaseException as error:
                    watchdog_stop_error = watchdog_stop_error or error
                    if failure is not None:
                        failure.add_note('Local watcher join failed: ' + type(error).__name__)
                if monitor.is_alive() or watchdog_stop_error is not None:
                    _report_validation_watchdog_shutdown(monitor, finished, watchdog_state,
                        request_sha256=args.expected_request_sha256, phase='finally_join',
                        owner=owner, observer_stop=observer_stop)
                    if failure is None and watchdog_stop_error is None:
                        watchdog_stop_error = RuntimeError('validation watchdog did not finish cleanly')
        try:
            if owner._entered and owner.to_dict()['status'] != 'released':
                if owner.tracks_descendants:
                    outcome['process_observation'] = owner.to_dict().get('process_observation')
                    outcome['process_cleanup_error'] = str(cleanup_error) if cleanup_error else None
                failure_path=Path(owner.output_layout['logs'])/'failure.json'
                if failure_path.parent.is_dir() and not failure_path.exists():
                    immutable_json(failure_path,outcome)
                exit_error = None
                try:
                    owner.__exit__(type(cleanup_error) if cleanup_error else RuntimeError,
                        cleanup_error or RuntimeError(outcome.get('error','validation did not finalize')),None)
                except BaseException as error:
                    exit_error = type(error).__name__ + ': ' + str(error)
                    if value['schema'] == 'owned-validation-request/v5' and failure is not None:
                        failure.add_note('Original validation owner exit also failed: ' + exit_error[:1000])
                    else:
                        raise
                finally:
                    if owner.tracks_descendants:
                        # Report the original owner's actual post-exit state.
                        # failure.json predates native release and cannot alone
                        # authorize the caller to close its outer source READ.
                        # Missing/failed terminal output remains unknown; never
                        # replace the original failure with a reporting error.
                        try:
                            reservation = owner.to_dict()
                            lifecycle = _source_custody_witness(owner, reservation, value, raw,
                                args.request, args.expected_request_sha256, lifecycle_events, failure,
                                exit_handling_completed=True)
                            print(json.dumps(dict(
                                schema='owned-validation-failure-terminal/v1',
                                request_sha256=args.expected_request_sha256,
                                completed=False, admitted=False, Lean_admitted=False,
                                failure=outcome, reservation=reservation,
                                source_custody_lifecycle=lifecycle,
                                process_cleanup_error=str(cleanup_error) if cleanup_error else None,
                                owner_exit_error=exit_error)), flush=True)
                        except BaseException as reporting_error:
                            try:
                                print('Failed to report original validation owner exit: ' +
                                    type(reporting_error).__name__, file=sys.stderr, flush=True)
                            except BaseException:
                                pass
            elif failure is not None:
                # open() can refuse capacity before the base owner enters. Its
                # exact original pre-record exception is not an unclosed child.
                # Every other pre-entered failure retains the unknown outcome.
                try:
                    terminal = _pre_grant_capacity_refusal_terminal(owner, value, raw,
                        args.request, args.expected_request_sha256, args.resource_ledger,
                        lifecycle_events, failure, outcome)
                    if terminal is None:
                        terminal = _pre_grant_lock_refusal_terminal(owner, value, raw,
                            args.request, args.expected_request_sha256, args.resource_ledger,
                            lifecycle_events, failure, outcome)
                    if terminal is None:
                        terminal = _pre_grant_ledger_bound_refusal_terminal(owner, value, raw,
                            args.request, args.expected_request_sha256, args.resource_ledger,
                            lifecycle_events, failure, outcome)
                    if terminal is None:
                        terminal = _pre_resource_entry_refusal_terminal(owner, value, raw,
                            args.request, args.expected_request_sha256, args.resource_ledger,
                            lifecycle_events, failure, outcome)
                    if terminal is not None:
                        print(json.dumps(terminal), flush=True)
                except BaseException as reporting_error:
                    try:
                        print('Failed to report original validation pre-grant refusal: ' +
                            type(reporting_error).__name__, file=sys.stderr, flush=True)
                    except BaseException:
                        pass
        finally:
            for number,handler in previous.items():
                signal.signal(number,handler)
        if cleanup_error is not None:
            if value['schema'] == 'owned-validation-request/v5' and failure is not None:
                failure.add_note('Original process cleanup also failed: ' +
                    type(cleanup_error).__name__ + ': ' + str(cleanup_error)[:1000])
            else:
                raise cleanup_error
        if watchdog_stop_error is not None and failure is None:
            raise watchdog_stop_error


# The training branch is deliberately separate from validation manifests and
# their source-custody classifier. Both branches use the original native owners.
TRAINER_REQUEST_SCHEMA = 'owned-f18-conditions-training-request/v1'
TRAINER_V2_REQUEST_SCHEMA = 'owned-f18-conditions-training-request/v2'
TRAINER_READY_SCHEMA = 'owned-f18-conditions-training-ready/v1'
TRAINER_TERMINAL_SCHEMA = 'owned-f18-conditions-training-terminal/v1'
_TRAINER_FIELDS = {'schema', 'mode', 'cwd', 'attempt_directory', 'outputs', 'roots',
    'source_sha256', 'cpu_slots', 'memory_mb', 'storage_bytes', 'child_process_slots',
    'timeout_seconds', 'scheduler_state_path', 'expected_scheduler_policy_sha256',
    'process_scope', 'compute'}
_TRAINER_OUTPUTS = {'logs', 'exports', 'tmp', 'cache', 'pytest', 'db'}
_TRAINER_COMPUTE_FIELDS = {'input_descriptors', 'initial_parity', 'runtime_contract',
    'population_manifest', 'max_steps_per_arm', 'max_seconds_per_arm'}
_TRAINER_DIRECTORY = ROOT/'ipfs_datasets_py/optimizers/logic_theorem_optimizer'
_TRAINER_BOOTSTRAP = _TRAINER_DIRECTORY/'autoencoder_campaign_process_worker.py'
_TRAINER_NETWORK = _TRAINER_DIRECTORY/'autoencoder_daemon_invocation_worker.py'
_TRAINER_DAEMON_SHA256 = 'c99d78004e6ce6b8a861f15e2c0b7009bbb6f45a37a89daabc8894ac440b282d'


def _trainer_need(condition, message):
    if not condition:
        raise ValueError(message)


def _trainer_path(value):
    _trainer_need(type(value) is str and 0 < len(value) <= 4096
        and Path(value).is_absolute() and str(Path(value)) == value
        and '..' not in Path(value).parts, 'canonical absolute trainer path required')
    return Path(value)


def _trainer_digest(value):
    return type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _validate_trainer_request(value):
    _trainer_need(type(value) is dict and set(value) == _TRAINER_FIELDS
        and type(value['schema']) is str
        and value['schema'] in (TRAINER_REQUEST_SCHEMA, TRAINER_V2_REQUEST_SCHEMA),
        'closed F18 training request required')
    _trainer_need(type(value['mode']) is str and value['mode'] in ('native_probe', 'numerical_probe', 'paired_fit')
        and value['process_scope'] == 'isolated_process_group', 'closed trainer mode/process scope required')
    _trainer_need(_trainer_path(value['cwd']) == ROOT, 'trainer must use its selected source tree')
    attempt = _trainer_path(value['attempt_directory'])
    _trainer_path(value['scheduler_state_path'])
    _trainer_need(_trainer_digest(value['expected_scheduler_policy_sha256']), 'trainer scheduler policy pin required')
    _trainer_need(type(value['outputs']) is dict and set(value['outputs']) == _TRAINER_OUTPUTS
        and all(_trainer_path(path) == attempt/name for name, path in value['outputs'].items()),
        'exact owned trainer output layout required')
    roots = value['roots']
    _trainer_need(type(roots) is list and 1 <= len(roots) <= 64
        and all(type(x) is str for x in roots) and len(set(roots)) == len(roots), 'explicit trainer storage roots required')
    paths = [_trainer_path(x) for x in roots]
    _trainer_need(any(attempt != root and root in attempt.parents for root in paths)
        and not any(a == b or a in b.parents or b in a.parents
                    for i, a in enumerate(paths) for b in paths[:i]), 'trainer roots overlap or omit attempt')
    for key, maximum in (('cpu_slots', 32), ('memory_mb', 1048576),
                         ('child_process_slots', 8), ('storage_bytes', 50_000_000_000)):
        _trainer_need(type(value[key]) is int and 0 < value[key] <= maximum, 'invalid trainer '+key)
    _trainer_need(type(value['timeout_seconds']) in (int, float)
        and math.isfinite(value['timeout_seconds']) and 0 < value['timeout_seconds'] <= 300,
        'finite trainer timeout at most300 seconds required')
    pins = value['source_sha256']
    _trainer_need(type(pins) is dict and 1 <= len(pins) <= 256
        and all(type(path) is str and _trainer_digest(pin) for path, pin in pins.items()),
        'explicit trainer source pins required')
    for path in pins:
        _trainer_path(path)
    if value['mode'] == 'native_probe':
        _trainer_need(value['compute'] is None, 'native probe permits no payload or compute request')
    elif value['mode'] == 'numerical_probe':
        _trainer_need(value['schema'] == TRAINER_V2_REQUEST_SCHEMA,
            'numerical probe requires explicit v2 request')
        compute = value['compute']
        _trainer_need(type(compute) is dict and set(compute) == {'runtime_contract', 'synthetic_fixture'},
            'closed synthetic numerical probe references required')
        reference_paths = []
        for name, maximum in (('runtime_contract', 131072), ('synthetic_fixture', 2 * 1024 * 1024)):
            ref = compute[name]
            _trainer_need(type(ref) is dict and set(ref) == {'path', 'bytes', 'sha256'}
                and type(ref['bytes']) is int and 0 < ref['bytes'] <= maximum
                and _trainer_digest(ref['sha256']), 'bounded synthetic numerical probe reference required')
            path = _trainer_path(ref['path'])
            _trainer_need(path != attempt and attempt not in path.parents
                and str(path) not in pins,
                'numerical probe input must precede its owned attempt and be separate from source pins')
            reference_paths.append(path)
        _trainer_need(len(set(reference_paths)) == 2, 'distinct numerical probe references required')
    else:
        compute = value['compute']
        version2 = value['schema'] == TRAINER_V2_REQUEST_SCHEMA
        fields = _TRAINER_COMPUTE_FIELDS | ({'learning_rate'} if version2 else set())
        _trainer_need(type(compute) is dict and set(compute) == fields,
            'closed paired F18 compute request required')
        if version2:
            rate = compute['learning_rate']
            _trainer_need(type(rate) in (int, float) and 0 < rate <= sys.float_info.max,
                'explicit finite positive TRAIN learning_rate required')
        for name in ('input_descriptors', 'initial_parity', 'runtime_contract', 'population_manifest'):
            ref = compute[name]
            _trainer_need(type(ref) is dict and set(ref) == {'path', 'bytes', 'sha256'}
                and type(ref['bytes']) is int and 0 < ref['bytes'] <= 131072
                and _trainer_digest(ref['sha256']), 'bounded trainer metadata reference required')
            _trainer_path(ref['path'])
        _trainer_need(type(compute['max_steps_per_arm']) is int and compute['max_steps_per_arm'] == 32
            and type(compute['max_seconds_per_arm']) is int
            and compute['max_seconds_per_arm'] == 32, 'fixed paired32 update/time recipe required')
    return json.loads(json.dumps(value, allow_nan=False))


def _trainer_decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            _trainer_need(key not in result, 'duplicate trainer JSON key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
        parse_constant=lambda token: (_ for _ in ()).throw(ValueError('nonfinite trainer JSON')))


def trainer_request(path, digest):
    raw = snapshot(path)
    _trainer_need(_trainer_digest(digest) and hashlib.sha256(raw).hexdigest() == digest,
        'trainer request hash differs')
    value = _validate_trainer_request(_trainer_decode(raw))
    if value['mode'] == 'numerical_probe':
        _trainer_need(all(Path(ref['path']) != Path(path) for ref in value['compute'].values()),
            'numerical probe inputs must be separate from the trainer request')
    return value, raw


def _trainer_source_guard(value):
    if value['schema'] == TRAINER_V2_REQUEST_SCHEMA and value['mode'] in ('paired_fit', 'numerical_probe'):
        _trainer_need(all(str(_TRAINER_DIRECTORY/name) in value['source_sha256'] for name in (
            'legal_span_conditions_fullspan_training_v2.py',
            'legal_span_conditions_fullspan_optimizer_recipe_v1.py')),
            'explicit v2 numerical and recipe source pins required')
    required = [Path(__file__).resolve(), *(_TRAINER_DIRECTORY/name for name in (
        'autoencoder_daemon_resources.py', 'autoencoder_daemon_operation_journal.py',
        'autoencoder_daemon_invocation_contracts.py', 'resource_scheduler.py',
        'existing_resource_scheduler.py', 'proof_resource_safety.py',
        'autoencoder_campaign_process_worker.py', 'autoencoder_daemon_invocation_worker.py'))]
    _trainer_need(all(str(path) in value['source_sha256'] for path in required),
        'explicit original trainer lifecycle source pins required')
    _trainer_need(value['source_sha256'][str(_TRAINER_DIRECTORY/'autoencoder_daemon_resources.py')]
        == _TRAINER_DAEMON_SHA256, 'different original public trainer backend requires new qualification')
    source_guard(value)


def _trainer_bootstrap(value):
    # The original bootstrap is stdlib-only. No package ancestors or payloads
    # are imported before the irreversible network filter and compute barrier.
    import importlib.util
    before = snapshot(_TRAINER_BOOTSTRAP)
    _trainer_need(hashlib.sha256(before).hexdigest() == value['source_sha256'][str(_TRAINER_BOOTSTRAP)],
        'original trainer bootstrap changed')
    spec = importlib.util.spec_from_file_location('_f18_original_campaign_bootstrap', _TRAINER_BOOTSTRAP)
    _trainer_need(spec is not None and spec.loader is not None, 'original trainer bootstrap unavailable')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _trainer_need(snapshot(_TRAINER_BOOTSTRAP) == before, 'original trainer bootstrap changed during import')
    return module


def _trainer_ready(payload, *, identity, owner_pid, request_pin):
    _trainer_need(type(payload) is dict and set(payload) == {'schema', 'identity', 'owner_pid',
        'request_sha256', 'canonical_root', 'network_guard'}, 'closed trainer READY required')
    _trainer_need(type(payload['identity']) is dict and set(payload['identity']) == {'pid', 'group_pid', 'birth'}
        and all(type(payload['identity'][key]) is int for key in ('pid', 'group_pid'))
        and type(payload['identity']['birth']) is str
        and len(payload['identity']['birth']) <= 32 and payload['identity']['birth'].isascii()
        and payload['identity']['birth'].isdecimal() and int(payload['identity']['birth']) > 0
        and payload['identity'] == identity and identity['pid'] == identity['group_pid'] and identity['pid'] > 0
        and type(payload['owner_pid']) is int and payload['owner_pid'] == owner_pid
        and payload['schema'] == TRAINER_READY_SCHEMA and payload['request_sha256'] == request_pin
        and payload['canonical_root'] == str(ROOT)
        and type(payload['network_guard']) is dict
        and payload['network_guard'].get('socket_denial_verified') is True
        and payload['network_guard'] == {'mechanism': 'linux_seccomp', 'denied_syscalls': [
            'socket', 'connect', 'sendto', 'sendmsg', 'sendmmsg'], 'socket_denial_verified': True},
        'trainer READY identity/source/network evidence differs')
    return payload


def _trainer_record_start(journal, payload):
    _trainer_need(all(journal.get_metadata(key) is None for key in ('start', 'child', 'release_intent', 'released', 'terminal')),
        'existing trainer start or terminal requires explicit original recovery; no automatic retry')
    journal.set_metadata('start', payload)


def _trainer_child_main(path, digest, *, ready_fd, release_fd, owner_pid):
    _trainer_need(sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode
        and ready_fd >= 3 and release_fd >= 3 and ready_fd != release_fd and owner_pid > 0,
        'isolated bytecode-disabled trainer bootstrap descriptors required')
    _trainer_need(not any(name == 'ipfs_datasets_py' or name.startswith('ipfs_datasets_py.')
        for name in sys.modules), 'trainer package imported before offline bootstrap')
    value, raw = trainer_request(path, digest)
    _trainer_source_guard(value)
    bootstrap = _trainer_bootstrap(value)
    guard = bootstrap._network_denial(value['source_sha256'][str(_TRAINER_NETWORK)])
    identity = bootstrap._identity()
    _trainer_need(identity['pid'] == identity['group_pid'] and os.getppid() == owner_pid,
        'trainer child is not the actual owned isolated group')
    bootstrap._send_ready(ready_fd, {'schema': TRAINER_READY_SCHEMA, 'identity': identity,
        'owner_pid': owner_pid, 'request_sha256': digest, 'canonical_root': str(ROOT), 'network_guard': guard})
    os.close(ready_fd)
    bootstrap._await_release(release_fd, timeout_seconds=value['timeout_seconds'], owner_pid=owner_pid)
    watcher = threading.Thread(target=bootstrap._watch_owner,
        kwargs={'fd': release_fd, 'owner_pid': owner_pid, 'group_pid': identity['group_pid']}, daemon=True)
    watcher.start()
    _trainer_need(snapshot(path) == raw and Path.cwd() == ROOT, 'trainer request/cwd changed at release')
    _trainer_source_guard(value)
    if value['mode'] == 'native_probe':
        result = {'schema': 'f18-native-trainer-probe-result/v1', 'mode': 'native_probe',
            'completed': True, 'model_constructions': 0, 'checkpoint_payloads_opened': 0,
            'model_forwards': 0, 'gradient_calls': 0, 'optimizer_updates': 0,
            'admitted': False, 'formalized': False, 'promoted': False}
    else:
        bootstrap._configure_dependency_paths()
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_invocation_worker as worker
        _trainer_need(Path(worker.__file__).resolve() == _TRAINER_NETWORK, 'different fixed trainer worker imported')
        if value['mode'] == 'numerical_probe':
            result = worker.run_f18_numerical_probe(value, output_directory=Path(value['outputs']['exports']))
        else:
            result = worker.run_f18_paired_training(value, output_directory=Path(value['outputs']['exports']))
    _trainer_need(type(result) is dict and type(result.get('completed')) is bool
        and all(result.get(key) is False for key in ('admitted', 'formalized', 'promoted')),
        'fixed trainer result/authority differs')
    _trainer_need(snapshot(path) == raw, 'trainer request changed during compute')
    _trainer_source_guard(value)
    immutable_json(Path(value['outputs']['exports'])/'trainer-result.json', result)
    return 0 if result['completed'] else 4


def _trainer_supervise(owner, journal, value, raw, *, request_path, request_pin, host, deadline=None, cancelled=None):
    """One already-admitted original owner; no factory or retry is exposed."""
    deadline = time.monotonic()+value['timeout_seconds'] if deadline is None else deadline
    owner_identity = host._process(os.getpid())
    _trainer_need(owner_identity is not None, 'original trainer owner identity unavailable')
    events = dict(child_launch_attempted=False, child_created=False, ready_verified=False,
                  barrier_release_attempted=False, barrier_released=False)
    child = identity = None
    reader = ready_write = release_read = release_write = None
    ready_raw = b''
    stopped, errors = threading.Event(), []
    failure = cleanup_error = None
    returncode = None
    heartbeat_lock = threading.Lock()
    next_heartbeat = [0.0]
    def heartbeat(*, force=False):
        with heartbeat_lock:
            now = time.monotonic()
            if force or now >= next_heartbeat[0]:
                _trainer_need(owner.heartbeat(), 'original trainer lease lost')
                next_heartbeat[0] = time.monotonic()+1.0
    def guard(*, sources=False):
        if sources:
            _trainer_need(snapshot(request_path) == raw, 'trainer request changed')
            _trainer_source_guard(value)
        _trainer_need(time.monotonic() < deadline, 'trainer execution deadline exceeded')
        _trainer_need(not errors and not owner.cancelled
            and (cancelled is None or not cancelled.is_set()), 'original trainer custody cancelled: '+repr(errors))
    def watch():
        next_sources = 0.0
        while not stopped.wait(.2):
            try:
                now = time.monotonic()
                guard(sources=now >= next_sources)
                if now >= next_sources:
                    next_sources = time.monotonic()+1.0
                heartbeat()
                if identity is not None:
                    group = host._group_usage({'pid': identity['pid'], 'birth': identity['birth']})
                    _trainer_need(group.get('available') is True
                        and type(group['rss_bytes']) is int and type(group['live_processes']) is int
                        and group['rss_bytes'] <= value['memory_mb']*1024*1024
                        and group['live_processes'] <= value['child_process_slots'], 'trainer local process/RSS bound exceeded')
            except BaseException as error:
                errors.append(type(error).__name__+': '+str(error))
                return
    monitor = threading.Thread(target=watch, name='original-f18-trainer-local-watchdog', daemon=True)
    try:
        guard(sources=True)
        heartbeat(force=True)
        _trainer_record_start(journal, {'request_sha256': request_pin,
            'reservation_id': owner.reservation_id,
            'owner': {'pid': owner_identity['pid'], 'birth': owner_identity['birth']}})
        reader, ready_write = os.pipe()
        release_read, release_write = os.pipe()
        os.set_blocking(reader, False)
        argv = [sys.executable, '-I', '-S', '-B', str(Path(__file__).resolve()),
            '--trainer-request', str(request_path), '--expected-request-sha256', request_pin,
            '--_trainer-child', '--ready-fd', str(ready_write), '--release-fd', str(release_read),
            '--owner-pid', str(owner_identity['pid'])]
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', IPFS_DATASETS_PY_MINIMAL_IMPORTS='1',
            IPFS_DATASETS_AUTO_INSTALL='0', IPFS_AUTO_INSTALL='false', TRANSFORMERS_OFFLINE='1',
            HF_HUB_OFFLINE='1', CUDA_VISIBLE_DEVICES='', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1',
            OPENBLAS_NUM_THREADS='1', XDG_CACHE_HOME=value['outputs']['cache'],
            TMPDIR=value['outputs']['tmp'], TEMP=value['outputs']['tmp'], TMP=value['outputs']['tmp'])
        with (Path(value['outputs']['logs'])/'trainer.stdout').open('xb') as out, \
             (Path(value['outputs']['logs'])/'trainer.stderr').open('xb') as err:
            events['child_launch_attempted'] = True
            child = subprocess.Popen(argv, cwd=value['cwd'], env=environment, stdin=subprocess.DEVNULL,
                stdout=out, stderr=err, start_new_session=True, close_fds=True,
                pass_fds=(ready_write, release_read))
            events['child_created'] = True
            os.close(ready_write); ready_write = None
            os.close(release_read); release_read = None
            observed = host._process(child.pid)
            _trainer_need(observed is not None and observed['parent_pid'] == owner_identity['pid']
                and observed['group_pid'] == observed['pid'], 'actual owned trainer child identity required')
            identity = {key: observed[key] for key in ('pid', 'group_pid', 'birth')}
            monitor.start()
            # This is the unchanged original bind plus its fresh global census.
            # The child remains behind RUN throughout this potentially slow call.
            owner.check_usage(Path(value['attempt_directory']), child_pid=identity['pid'])
            while b'\n' not in ready_raw:
                guard()
                heartbeat()
                _trainer_need(child.poll() is None, 'trainer child exited before READY')
                try:
                    chunk = os.read(reader, 8193-len(ready_raw))
                except BlockingIOError:
                    time.sleep(.05)
                    continue
                _trainer_need(bool(chunk), 'trainer child closed READY before release')
                ready_raw += chunk
                _trainer_need(len(ready_raw) <= 8192, 'trainer READY exceeds bound')
            _trainer_need(ready_raw.count(b'\n') == 1 and ready_raw.endswith(b'\n'), 'trainer READY framing differs')
            ready = _trainer_ready(_trainer_decode(ready_raw), identity=identity,
                owner_pid=owner_identity['pid'], request_pin=request_pin)
            current = host._process(child.pid)
            _trainer_need(current is not None and current['parent_pid'] == owner_identity['pid']
                and {key: current[key] for key in identity} == identity, 'trainer child changed before RUN')
            events['ready_verified'] = True
            journal.set_metadata('child', {'identity': identity, 'bootstrap': ready})
            guard(sources=True)
            owner.check_usage(Path(value['attempt_directory']), child_pid=identity['pid'])
            guard(sources=True)
            heartbeat(force=True)
            journal.set_metadata('release_intent', {'request_sha256': request_pin, 'identity': identity})
            events['barrier_release_attempted'] = True
            _trainer_need(os.write(release_write, b'RUN\n') == 4, 'trainer RUN token was not fully written')
            events['barrier_released'] = True
            journal.set_metadata('released', {'request_sha256': request_pin, 'identity': identity})
            os.close(reader); reader = None
            # Retain release_write until the original child and group are reaped.
            # Closing it earlier would intentionally revoke the child watcher.
            while child.poll() is None:
                guard()
                heartbeat()
                time.sleep(.1)
            returncode = child.returncode
            _trainer_need(returncode == 0, 'fixed F18 trainer child failed: '+str(returncode))
            guard(sources=True)
    except BaseException as error:
        failure = {'error_type': type(error).__name__, 'error': str(error)[:4096]}
    finally:
        try:
            if child is not None and identity is None:
                # No RUN was possible. Revoke the retained pipe, then reap the
                # exact Popen child without signalling an unconfirmed identity.
                if release_write is not None:
                    os.close(release_write); release_write = None
                child.wait(timeout=5)
            else:
                stop_and_reap(child, identity['birth'] if identity is not None else None)
        except BaseException as error:
            cleanup_error = type(error).__name__+': '+str(error)
        stopped.set()
        if monitor.ident is not None:
            monitor.join(timeout=5)
            if monitor.is_alive():
                cleanup_error = cleanup_error or 'original trainer monitor did not stop'
        for fd in (reader, ready_write, release_read, release_write):
            if fd is not None:
                os.close(fd)
    try:
        group = host._group_usage({'pid': identity['pid'], 'birth': identity['birth']} if identity else None)
        if not _trainer_group_closed(group):
            cleanup_error = cleanup_error or 'original trainer group death unconfirmed'
    except BaseException as error:
        group = {'available': False, 'live_processes': None, 'rss_bytes': None}
        cleanup_error = cleanup_error or 'original group observation: '+type(error).__name__
    return {'schema': 'owned-f18-trainer-child-execution/v1', 'completed': failure is None and cleanup_error is None,
        'returncode': returncode, 'events': events, 'child_identity': identity, 'group_observation': group,
        'error': failure, 'process_cleanup_error': cleanup_error, 'monitor_errors': errors,
        'resource_scope': 'isolated_process_group', 'admitted': False, 'formalized': False, 'promoted': False}


def _trainer_group_closed(group):
    return (type(group) is dict and group.get('available') is True
        and type(group.get('live_processes')) is int and group['live_processes'] == 0
        and type(group.get('rss_bytes')) is int and group['rss_bytes'] == 0)


def _trainer_durable_tree(attempt):
    # Only owned regular artifacts are flushed. No source/data payload is opened.
    for directory, dirs, files in os.walk(attempt, topdown=False, followlinks=False):
        for name in (*dirs, *files):
            path = Path(directory)/name
            info = path.lstat()
            _trainer_need(stat.S_ISDIR(info.st_mode) or (stat.S_ISREG(info.st_mode) and info.st_nlink == 1),
                'trainer durability requires unaliased ordinary artifacts')
            if stat.S_ISREG(info.st_mode):
                fd = os.open(path, os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
                try:
                    observed = os.fstat(fd)
                    _trainer_need((observed.st_dev, observed.st_ino, observed.st_size, observed.st_mtime_ns)
                        == (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns), 'trainer artifact changed at durability')
                    os.fsync(fd)
                finally:
                    os.close(fd)
        fd = os.open(directory, os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def classify_owned_trainer_source_custody(terminal, request_raw, *, expected_request_sha256,
        owner_pid, owner_birth, returncode, expected_resource_ledger):
    """Read-only typed evidence, after caller-observed original CLI exit.

    Closure of native/source custody never authorizes release of retained storage.
    Unknown or incomplete evidence preserves the original cleanup requirement.
    """
    unknown = {'verdict': 'requires_original_trainer_cleanup', 'source_custody_closed': False,
               'storage_release_authorized': False}
    try:
        _trainer_need(type(request_raw) is bytes and _trainer_digest(expected_request_sha256)
            and hashlib.sha256(request_raw).hexdigest() == expected_request_sha256, 'trainer request evidence differs')
        value = _validate_trainer_request(_trainer_decode(request_raw))
        _trainer_source_guard(value)
        _trainer_need(type(terminal) is dict and terminal['schema'] == TRAINER_TERMINAL_SCHEMA
            and terminal['request_sha256'] == expected_request_sha256
            and terminal['resource_scope'] == 'isolated_process_group'
            and terminal['mode'] == value['mode']
            and terminal['owner'] == {'pid': owner_pid, 'birth': owner_birth}
            and type(terminal['owner']['pid']) is int
            and type(owner_pid) is int and owner_pid > 0 and type(owner_birth) is str and owner_birth.isdecimal()
            and type(returncode) is int and type(terminal['completed']) is bool
            and terminal['completed'] is (returncode == 0)
            and all(terminal.get(key) is False for key in ('admitted', 'Lean_admitted', 'formalized', 'promoted'))
            and terminal['owner_exit_handling_completed'] is True
            and terminal['process_cleanup_error'] is None and terminal['owner_exit_error'] is None
            and terminal['source_guards'] == {'request_unchanged': True, 'sources_unchanged': True}
            and all(type(flag) is bool for flag in terminal['source_guards'].values()),
            'original trainer terminal custody is incomplete')
        reservation = terminal['reservation']
        if terminal['owner_open_returned'] is False:
            # Only the pinned backend's inventory refusal before record/native
            # acquisition is proven here. Other __enter__ failures stay unknown.
            _trainer_need(returncode != 0 and terminal['completed'] is False
                and terminal.get('error') == {'error_type': 'DaemonResourceError',
                    'error': 'storage inventory entry bound exceeded'}
                and terminal['child_identity'] is None and terminal['events'] == {}
                and _trainer_group_closed(terminal['group_observation'])
                and type(reservation) is dict and reservation['status'] == 'not_entered'
                and reservation['record'] is None and reservation['resource_lease'] is None
                and reservation['cleanup_error'] is None
                and reservation['schema'] == 'daemon-resource-reservations-v1'
                and reservation['scheduler_lane'] == 'hammer_lean'
                and reservation['workload'] == 'canonical_trainer'
                and reservation['ledger_path'] == expected_resource_ledger
                and terminal['scheduler'] == {'state_path': value['scheduler_state_path'],
                    'policy_sha256': value['expected_scheduler_policy_sha256'],
                    'lane': 'hammer_lean', 'workload': 'canonical_trainer'},
                'original pre-entry inventory refusal is incomplete')
            rid = reservation['reservation_id']
            _trainer_need(type(rid) is str and len(rid) == 32
                and all(c in '0123456789abcdef' for c in rid)
                and terminal['resource_request_id'] == 'daemon:'+rid,
                'pre-entry reservation identity differs')
            ledger_path = _trainer_path(expected_resource_ledger)
            ledger = _trainer_decode(snapshot(ledger_path, 16*1024*1024))
            from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as host
            _trainer_need(Path(host.__file__).resolve() == _TRAINER_DIRECTORY/'autoencoder_daemon_resources.py',
                'different original storage metadata owner imported')
            _trainer_need(type(ledger) is dict and set(ledger) == {'schema', 'roots', 'limit_bytes', 'reservations'}
                and ledger.get('schema') == host.SCHEMA
                and type(ledger.get('reservations')) is dict and rid not in ledger['reservations']
                and ledger.get('roots') == reservation['roots']
                and [root['path'] for root in ledger['roots']] == value['roots']
                and type(ledger.get('limit_bytes')) is int
                and type(reservation.get('storage_limit_bytes')) is int
                and ledger['limit_bytes'] == reservation['storage_limit_bytes'] == host.MAX_STORAGE_BYTES
                and len(ledger['reservations']) <= host.MAX_RESERVATIONS,
                'pre-entry durable storage evidence differs')
            for key, record in ledger['reservations'].items():
                _trainer_need(type(record) is dict and record.get('reservation_id') == key
                    and record.get('status') in {'reserved', 'active', 'retained', 'released'},
                    'pre-entry durable reservation record differs')
                host._integer(record.get('storage_bytes'), 'ledger storage_bytes', maximum=host.MAX_STORAGE_BYTES)
                host._integer(record.get('owner_pid'), 'ledger owner_pid')
                if 'child_process_slots' in record:
                    host._integer(record['child_process_slots'], 'ledger child_process_slots')
                host._external_charges(record)
            _trainer_need(rid not in json.dumps(ledger['reservations'], ensure_ascii=True, sort_keys=True, allow_nan=False),
                'pre-entry identity appears in durable storage metadata')
            from ipfs_datasets_py.optimizers.logic_theorem_optimizer import existing_resource_scheduler as existing
            _trainer_need(Path(existing.__file__).resolve() == _TRAINER_DIRECTORY/'existing_resource_scheduler.py',
                'different original scheduler reader imported')
            scheduler_path = _trainer_path(value['scheduler_state_path'])
            parents = existing._parents(scheduler_path)
            _, scheduler = existing._read(scheduler_path)
            _trainer_need(existing._parents(scheduler_path) == parents
                and existing.policy_sha256(scheduler['config']) == value['expected_scheduler_policy_sha256']
                and scheduler['config'].get('proof_safety_enabled') is True
                and rid not in json.dumps(scheduler, ensure_ascii=True, sort_keys=True, allow_nan=False),
                'pre-entry request exists in durable native state or policy differs')
            return {'verdict': 'proven_original_trainer_preentry_inventory_refusal_source_closed',
                    'source_custody_closed': True, 'storage_release_authorized': False}
        _trainer_need(terminal['owner_open_returned'] is True, 'original trainer entry unproven')
        record, lease = reservation['record'], reservation['resource_lease']
        _trainer_need(type(record) is dict and type(lease) is dict and lease['released'] is True
            and lease['parent_lease_id'] is None
            and lease['lane'] == 'hammer_lean' and type(lease['owner_pid']) is int and lease['owner_pid'] == owner_pid
            and type(lease['lease_id']) is str and len(lease['lease_id']) == 32
            and type(record['owner_pid']) is int and record['owner_pid'] == owner_pid
            and type(record['reservation_id']) is str and len(record['reservation_id']) == 32
            and all(c in '0123456789abcdef' for c in record['reservation_id'])
            and reservation['reservation_id'] == record['reservation_id']
            and terminal['resource_request_id'] == 'daemon:'+record['reservation_id']
            and reservation['scheduler_lane'] == record['scheduler_lane'] == 'hammer_lean'
            and reservation['workload'] == record['workload'] == 'canonical_trainer'
            and reservation['ledger_path'] == expected_resource_ledger
            and terminal['scheduler'] == {'state_path': value['scheduler_state_path'],
                'policy_sha256': value['expected_scheduler_policy_sha256'],
                'lane': 'hammer_lean', 'workload': 'canonical_trainer'}
            and record['attempt_directory']['path'] == value['attempt_directory']
            and reservation['status'] == record['status'] and record['status'] in ('released', 'retained')
            and record['prior_children'] == []
            and all(type(lease[key]) is int and lease[key] == value[key]
                    for key in ('cpu_slots', 'memory_mb', 'child_process_slots')),
            'genuine original trainer/native binding differs')
        _trainer_path(expected_resource_ledger)
        ledger = Path(expected_resource_ledger).lstat()
        _trainer_need(stat.S_ISREG(ledger.st_mode) and ledger.st_nlink == 1
            and all(stat.S_ISDIR(p.lstat().st_mode) for p in Path(expected_resource_ledger).parents), 'trainer ledger alias')
        _trainer_need(all(type(record[key]) is int and record[key] == value[key] for key in
            ('cpu_slots', 'memory_mb', 'storage_bytes', 'child_process_slots')), 'trainer budget witness differs')
        child, group = terminal['child_identity'], terminal['group_observation']
        _trainer_need(_trainer_group_closed(group), 'trainer group cleanup unproven')
        if child is not None:
            _trainer_need(type(child) is dict and set(child) == {'pid', 'group_pid', 'birth'}
                and type(child['pid']) is int and child['pid'] > 0
                and type(child['group_pid']) is int and child['pid'] == child['group_pid']
                and type(child['birth']) is str and 0 < len(child['birth']) <= 32
                and child['birth'].isascii() and child['birth'].isdecimal() and int(child['birth']) > 0
                and record['child'] == {'pid': child['pid'], 'birth': child['birth']}, 'trainer child binding differs')
        else:
            _trainer_need(record.get('child') is None
                and terminal['events'].get('child_created', False) is False
                and terminal['events'].get('child_launch_attempted', False) is False, 'unreported trainer child')
        return {'verdict': 'proven_original_trainer_native_and_source_closed',
                'source_custody_closed': True, 'storage_release_authorized': False}
    except BaseException:
        return unknown


def trainer_main(argv=None):
    parser = argparse.ArgumentParser(description='Run one closed F18 operation with the original canonical trainer owner')
    parser.add_argument('--trainer-request', required=True, type=Path)
    parser.add_argument('--expected-request-sha256', required=True)
    parser.add_argument('--resource-ledger', type=Path)
    parser.add_argument('--_trainer-child', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--ready-fd', type=int, help=argparse.SUPPRESS)
    parser.add_argument('--release-fd', type=int, help=argparse.SUPPRESS)
    parser.add_argument('--owner-pid', type=int, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args._trainer_child:
        return _trainer_child_main(args.trainer_request, args.expected_request_sha256,
            ready_fd=args.ready_fd, release_fd=args.release_fd, owner_pid=args.owner_pid)
    if args.resource_ledger is None:
        parser.error('--resource-ledger is required for the original trainer owner')
    value, raw = trainer_request(args.trainer_request, args.expected_request_sha256)
    _trainer_source_guard(value)
    _trainer_need(not any(x is not None for x in (args.ready_fd, args.release_fd, args.owner_pid)),
        'trainer bootstrap descriptors are child-only')
    _trainer_need('ipfs_datasets_py' not in sys.modules, 'run original trainer in a fresh process')
    sys.path.insert(0, str(ROOT))
    os.environ.update(IPFS_DATASETS_PY_MINIMAL_IMPORTS='1', IPFS_DATASETS_AUTO_INSTALL='0', IPFS_AUTO_INSTALL='false')
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_resources as host
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_operation_journal import DurableDaemonOperationJournal
    _trainer_need(Path(host.__file__).resolve() == _TRAINER_DIRECTORY/'autoencoder_daemon_resources.py',
        'different original trainer source tree imported')
    ledger = json.loads(snapshot(args.resource_ledger, 16*1024*1024))
    _trainer_need([row['path'] for row in ledger['roots']] == value['roots'], 'trainer ledger roots differ')
    attempt = host._safe_path(value['attempt_directory'], directory=True)
    _trainer_need(not any(attempt.iterdir()), 'trainer attempt must already exist empty; prior attempts require recovery')
    owner_identity = host._process(os.getpid())
    _trainer_need(owner_identity is not None, 'original trainer owner identity unavailable')
    started = time.monotonic()
    owner = host.DaemonResourceReservation(args.resource_ledger, roots=value['roots'],
        storage_bytes=value['storage_bytes'], memory_mb=value['memory_mb'], cpu_slots=value['cpu_slots'],
        child_process_slots=value['child_process_slots'], timeout_seconds=value['timeout_seconds'],
        ledger_lock_timeout_seconds=5, scheduler_state_path=value['scheduler_state_path'],
        expected_scheduler_policy_sha256=value['expected_scheduler_policy_sha256'], require_existing_ledger=True)
    execution = dict(completed=False, returncode=None, events={}, child_identity=None,
        group_observation=host._group_usage(None), process_cleanup_error=None)
    failure = exit_error = None
    opened = exited = False
    journal = None
    guards = {'request_unchanged': False, 'sources_unchanged': False}
    cancelled = threading.Event()
    interrupted = []
    def on_signal(number, frame):
        interrupted.append(number)
        cancelled.set()
    previous = {number: signal.signal(number, on_signal) for number in (signal.SIGTERM, signal.SIGINT)}
    try:
        owner.__enter__(); opened = True
        _trainer_need(not cancelled.is_set() and time.monotonic() < started+value['timeout_seconds'],
            'trainer total deadline/cancellation during admission')
        for path in value['outputs'].values():
            Path(path).mkdir(mode=0o700)
        owner.check_usage(attempt)
        journal = DurableDaemonOperationJournal(Path(value['outputs']['logs'])/'trainer-journal.json', {
            'schema': TRAINER_REQUEST_SCHEMA, 'request_sha256': args.expected_request_sha256,
            'attempt_directory': str(attempt), 'resource_request_id': 'daemon:'+owner.reservation_id})
        execution = _trainer_supervise(owner, journal, value, raw, request_path=args.trainer_request,
            request_pin=args.expected_request_sha256, host=host, deadline=started+value['timeout_seconds'], cancelled=cancelled)
        journal.set_metadata('terminal', execution)
        _trainer_need(execution['completed'] is True, 'original trainer child execution failed')
        immutable_json(Path(value['outputs']['logs'])/'trainer-execution.json', execution)
        journal.close(); journal = None
        _trainer_need(snapshot(args.trainer_request) == raw, 'trainer request changed at closing')
        _trainer_source_guard(value)
        _trainer_durable_tree(attempt)
        owner.finalize(attempt, artifacts_durable=True)
    except BaseException as error:
        failure = {'error_type': type(error).__name__, 'error': str(error)[:4096]}
    finally:
        if journal is not None:
            try:
                journal.close()
            except BaseException as error:
                exit_error = 'journal close: '+type(error).__name__+': '+str(error)
        try:
            _trainer_need(execution['process_cleanup_error'] is None
                and _trainer_group_closed(execution['group_observation']),
                'trainer group cleanup unconfirmed; original recovery required')
            owner.__exit__(RuntimeError if failure else None, RuntimeError(str(failure)) if failure else None, None)
            exited = True
        except BaseException as error:
            exit_error = type(error).__name__+': '+str(error)
        try:
            guards['request_unchanged'] = snapshot(args.trainer_request) == raw
            _trainer_source_guard(value); guards['sources_unchanged'] = True
        except BaseException:
            pass
        for number, handler in previous.items():
            signal.signal(number, handler)
    terminal = {'schema': TRAINER_TERMINAL_SCHEMA, 'request_sha256': args.expected_request_sha256,
        'mode': value['mode'], 'completed': failure is None and exit_error is None and all(guards.values()),
        'resource_scope': 'isolated_process_group', 'resource_request_id': 'daemon:'+owner.reservation_id,
        'scheduler': {'state_path': value['scheduler_state_path'],
            'policy_sha256': value['expected_scheduler_policy_sha256'],
            'lane': 'hammer_lean', 'workload': 'canonical_trainer'},
        'owner': {'pid': owner_identity['pid'], 'birth': owner_identity['birth']},
        'owner_open_returned': opened, 'owner_exit_handling_completed': exited,
        'child_identity': execution['child_identity'], 'group_observation': execution['group_observation'],
        'events': execution['events'], 'process_cleanup_error': execution['process_cleanup_error'],
        'owner_exit_error': exit_error, 'source_guards': guards, 'reservation': owner.to_dict(),
        'error': failure, 'received_signals': interrupted, 'admitted': False, 'Lean_admitted': False, 'formalized': False, 'promoted': False}
    print(json.dumps(terminal, sort_keys=True), flush=True)
    return 0 if terminal['completed'] else 1


def entrypoint(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if '--trainer-request' in arguments or any(x.startswith('--trainer-request=') for x in arguments):
        return trainer_main(arguments)
    return main(arguments)



def classify_owned_validation_startup_clock_source_custody_v1(terminal, request_raw, **caller):
    """Explicit v6 no-grant/no-child selector; original bytes are never projected."""
    unknown = dict(verdict='requires_original_native_cleanup', source_custody_closed=False,
                   storage_release_authorized=False)
    try:
        value = json.loads(request_raw)
        if not _startup_clock_no_child_request_shape(value, request_raw):return unknown
        events = terminal['source_custody_lifecycle']['events']
        reservation = terminal.get('reservation')
        if reservation:
            observed_owner = reservation['startup_clock_profile']['original_owner']
            if observed_owner.get('pid') != caller.get('owner_pid') or observed_owner.get('birth') != caller.get('owner_birth'):
                return unknown
        if any(events.get(key) is True for key in ('child_launch_attempted','child_created','barrier_release_attempted','barrier_released')):
            return unknown
        return classify_owned_validation_source_custody(terminal, request_raw, **caller)
    except BaseException:return unknown


def _no_child_native_closed_profile_v6(terminal, request_raw, *,
        expected_request_sha256, owner_pid, owner_birth, returncode, expected_resource_ledger):
    """Only actual acquired-and-closed SDK admission before any child launch."""
    return _no_child_native_closed_profile(terminal, request_raw, request_version='v6',
        expected_request_sha256=expected_request_sha256, owner_pid=owner_pid,
        owner_birth=owner_birth, returncode=returncode, expected_resource_ledger=expected_resource_ledger)


def inspect_owned_validation_no_child_native_closed_v6(terminal, request_raw, *,
        expected_request_sha256, owner_pid, owner_birth, returncode, expected_resource_ledger,
        cleanup_timeout_seconds=5):
    """Versioned v6 selector over the unchanged real PID/row/locked Native inspector."""
    return _inspect_owned_validation_no_child_native_closed(terminal, request_raw,
        profile=_no_child_native_closed_profile_v6, expected_request_sha256=expected_request_sha256,
        owner_pid=owner_pid, owner_birth=owner_birth, returncode=returncode,
        expected_resource_ledger=expected_resource_ledger, cleanup_timeout_seconds=cleanup_timeout_seconds)



def wait_and_inspect_owned_validation_no_child_native_closed_v6(process, terminal, request_raw, *,
        expected_request_sha256, owner_birth, expected_resource_ledger,
        original_wait_deadline_monotonic):
    """Explicit v6 original Source-held caller integration; never closes Source here.

    Call with the original Popen and its original absolute wait cutoff before
    the productive observed-identity-count branch. This performs the genuine
    wait itself, then observes only explicit V6 no-child Native closure. An
    exhausted cutoff, failed binding or uncertain wait remains unknown, without
    signals, retries, replacement owners, state writes or storage release.
    A vanished historical caller cannot be reconstructed with this function.
    """
    unknown = dict(verdict='requires_original_native_cleanup', source_custody_closed=False,
                   storage_release_authorized=False)
    try:
        if (type(process) is not subprocess.Popen
                or type(original_wait_deadline_monotonic) not in (int, float)
                or not math.isfinite(original_wait_deadline_monotonic)):
            return unknown
        original_remaining = original_wait_deadline_monotonic - time.monotonic()
        if not 0 < original_remaining <= 420:
            return unknown
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as native
        previous = native.resource_operation_deadline()
        end = original_wait_deadline_monotonic
        if previous is not None:
            end = min(end, previous.native_deadline_monotonic)
        # Waiting is cleanup too: it must honor an earlier existing parent
        # lifetime before Popen.wait starts, without renewing either clock.
        remaining = end - time.monotonic()
        if remaining <= 0:
            return unknown
        returncode = process.wait(timeout=remaining)
        remaining = end - time.monotonic()
        if type(returncode) is not int or returncode != 1 or remaining <= 0:
            return unknown
        value, _, _, _, _ = _no_child_native_closed_profile_v6(terminal, request_raw,
            expected_request_sha256=expected_request_sha256, owner_pid=process.pid,
            owner_birth=owner_birth, returncode=returncode,
            expected_resource_ledger=expected_resource_ledger)
        _lifecycle_source_guard(value)
        remaining = end - time.monotonic()
        if remaining <= 0:
            return unknown
        with native.resource_cleanup_deadline(native_deadline_monotonic=end):
            verdict = inspect_owned_validation_no_child_native_closed_v6(terminal, request_raw,
                expected_request_sha256=expected_request_sha256, owner_pid=process.pid,
                owner_birth=owner_birth, returncode=returncode,
                expected_resource_ledger=expected_resource_ledger,
                cleanup_timeout_seconds=min(5, remaining))
            if time.monotonic() >= end:
                return unknown
            return verdict
    except BaseException:
        return unknown


if __name__ == '__main__':
    raise SystemExit(entrypoint())
