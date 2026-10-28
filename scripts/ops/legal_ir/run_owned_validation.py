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
    if value.get('schema') != 'owned-validation-request/v1':
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


def report_capacity_refusal(error):
    """Best-effort aggregate diagnostic from the original refusal snapshot."""
    try:
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
            stage='owner.open', error_type='DaemonResourceError', error=message,
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
        need(type(value) is dict and value.get('schema') == 'owned-validation-request/v1')
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
    owner = ValidationResourceReservation(args.resource_ledger,roots=[row['path'] for row in ledger['roots']],
        attempt_directory=value['attempt_directory'],storage_bytes=value['storage_bytes'],
        memory_mb=value['memory_mb'],cpu_slots=value['cpu_slots'],child_process_slots=value['child_process_slots'],
        scheduler_state_path=value['scheduler_state_path'],
        expected_scheduler_policy_sha256=value['expected_scheduler_policy_sha256'],
        validation_manifest_path=args.request,frozen_validation_manifest_sha256=args.expected_request_sha256,
        timeout_seconds=value['timeout_seconds'])
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
        try:
            owner.open()
        except host.DaemonResourceError as error:
            report_capacity_refusal(error)
            raise
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
                stdout=out,stderr=err,start_new_session=True)
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
_TRAINER_DAEMON_SHA256 = '0cf17951048015d4ce01817c0bfdd74394a161cd5e7999b01a29f18f358e666a'


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
    _trainer_need(type(value['mode']) is str and value['mode'] in ('native_probe', 'paired_fit')
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
    return _validate_trainer_request(_trainer_decode(raw)), raw


def _trainer_source_guard(value):
    if value['schema'] == TRAINER_V2_REQUEST_SCHEMA and value['mode'] == 'paired_fit':
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
    _trainer_need(sys.flags.isolated and sys.flags.no_site and ready_fd >= 3 and release_fd >= 3
        and ready_fd != release_fd and owner_pid > 0, 'isolated trainer bootstrap descriptors required')
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
        argv = [sys.executable, '-I', '-S', str(Path(__file__).resolve()),
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


if __name__ == '__main__':
    raise SystemExit(entrypoint())
