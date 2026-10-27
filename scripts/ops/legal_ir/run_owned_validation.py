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
    if value.get('schema') not in ('owned-validation-request/v1', 'owned-validation-request/v2'):
        raise ValueError('unsupported validation request')
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


LIFECYCLE_SCHEMA = 'owned-validation-source-custody-lifecycle/v1'
_LIFECYCLE_EVENTS = {'owner_open_attempted', 'owner_open_returned',
    'child_launch_attempted', 'child_created', 'barrier_release_attempted',
    'barrier_released', 'owner_exit_handling_completed'}
_TIMEOUT_FIELDS = {'schema', 'decision_scope', 'cycle_wall_time', 'cycle_monotonic_time',
    'deadline_monotonic', 'elapsed_seconds', 'clock_scope', 'waiter_id', 'sequence',
    'request_id', 'lane', 'lane_truncated', 'parent_lease_id', 'timed_out',
    'can_grant_now', 'externally_cancelled', 'parent_cancelled', 'proof_safety_enabled',
    'exact_blocking_predicate', 'exact_blocking_cause'}


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
        storage={'status': reservation['status'], 'cleanup_error': reservation.get('cleanup_error'),
            'release_authorized': False})



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
             ('owned-validation-request/v1', 'owned-validation-request/v2'))
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
    source_guard(value)
    script = str(Path(__file__).resolve())
    if value['source_sha256'].get(script) != hashlib.sha256(snapshot(script,4*1024*1024)).hexdigest():
        raise ValueError('launcher source must be explicitly pinned')
    # Resolve the source tree from this script, before importing the package.
    # Never reuse a package imported from the editable HACC installation.
    if 'ipfs_datasets_py' in sys.modules:
        raise RuntimeError('run owned validation in a fresh process')
    sys.path.insert(0,str(ROOT))
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.validation_run_resources import ValidationResourceReservation
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
        owner.open()
        lifecycle_events['owner_open_returned'] = True
        deadline = time.monotonic()+value['timeout_seconds']
        def guard():
            if snapshot(args.request) != raw:
                raise RuntimeError('validation request changed')
            source_guard(value)
            if cancelled.is_set():
                raise RuntimeError('validation cancelled: '+repr(errors))
            if time.monotonic()>=deadline:
                raise TimeoutError('validation deadline exceeded')
        def watch():
            while not finished.wait(.1):
                try:
                    guard()
                    # Strictly local sampling stays responsive while the owner
                    # performs a separately serialized fresh global census.
                    owner.check_limits(full=False)
                except BaseException as error:
                    errors.append(type(error).__name__+': '+str(error))
                    cancelled.set()
                    return
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
                umask=0o077 if value['schema']=='owned-validation-request/v2' else -1)
            lifecycle_events['child_created'] = True
            identity = host._process(child.pid)
            if identity is None:
                raise RuntimeError('validation child exited before attachment')
            birth = identity['birth']
            owner.attach_child(child.pid)
            guard()
            if errors or not owner.heartbeat() or owner.cancelled:
                raise RuntimeError('native validation lease lost during attachment')
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
        finished.set()
        monitor.join(timeout=5)
        guard()
        if monitor.is_alive() or errors:
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
        outcome.update(completed=False,error_type=type(error).__name__,error=str(error),
            elapsed_seconds=time.monotonic()-started,watchdog_errors=list(errors),
            received_signals=list(interrupted))
        raise
    finally:
        finished.set()
        if monitor is not None:
            monitor.join(timeout=5)
        cleanup_error = None
        try:
            if child is not None and birth is not None:
                stop_and_reap(child,birth,owner)
        except BaseException as error:
            cleanup_error = error
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
        finally:
            for number,handler in previous.items():
                signal.signal(number,handler)
        if cleanup_error is not None:
            raise cleanup_error


if __name__ == '__main__':
    raise SystemExit(main())
