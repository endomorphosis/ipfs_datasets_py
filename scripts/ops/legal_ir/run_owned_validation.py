#!/usr/bin/env python3
"""Run explicit trusted checks with one native validation and storage owner.

This sampled process-group profile is not a filesystem quota or containment of
arbitrary descendants. It never grants semantic or Lean admission.
"""
from __future__ import annotations

import argparse
import hashlib
import json
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


def snapshot(path, maximum=1024*1024):
    path = Path(path)
    for parent in (path.parent, *path.parent.parents):
        if not stat.S_ISDIR(parent.lstat().st_mode):
            raise ValueError('input directory is missing or aliased')
    with os.fdopen(os.open(path, os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK), 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 < before.st_size <= maximum:
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
        if hashlib.sha256(snapshot(path, 4*1024*1024)).hexdigest() != digest:
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


def stop_and_reap(child, birth):
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
    interrupted = []
    def on_signal(number,frame):
        interrupted.append(number)
        cancelled.set()
    previous = {number:signal.signal(number,on_signal) for number in (signal.SIGTERM,signal.SIGINT)}
    started = time.monotonic()
    outcome = dict(schema='owned-validation-result/v1',request_sha256=args.expected_request_sha256,
        executed_checks=[],returncode=None,completed=False,admitted=False,Lean_admitted=False,
        resource_scope='cooperative_isolated_process_group_and_owned_attempt',
        model_weights_downloaded=False,authority_granted=False)
    try:
        owner.open()
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
            child = subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),
                '--request',str(args.request),'--expected-request-sha256',args.expected_request_sha256,'--_child'],
                cwd=value['cwd'],env=dict(owner.environment(dict(os.environ)),
                    PYTHONPATH=os.pathsep.join([str(ROOT),value['cwd'],site.getusersitepackages()]),
                    PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1',
                    IPFS_DATASETS_PY_MINIMAL_IMPORTS='1',IPFS_DATASETS_AUTO_INSTALL='0',
                    IPFS_AUTO_INSTALL='false',TRANSFORMERS_OFFLINE='1'),stdin=subprocess.PIPE,
                stdout=out,stderr=err,start_new_session=True)
            identity = host._process(child.pid)
            if identity is None:
                raise RuntimeError('validation child exited before attachment')
            birth = identity['birth']
            owner.attach_child(child.pid)
            guard()
            if errors or not owner.heartbeat() or owner.cancelled:
                raise RuntimeError('native validation lease lost during attachment')
            child.stdin.write(b'1')
            child.stdin.flush()
            child.stdin.close()
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
        stop_and_reap(child,birth)
        finished.set()
        monitor.join(timeout=5)
        guard()
        if monitor.is_alive() or errors:
            raise RuntimeError('validation watchdog did not finish cleanly')
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
                stop_and_reap(child,birth)
        except BaseException as error:
            cleanup_error = error
        try:
            if owner._entered and owner.to_dict()['status'] != 'released':
                failure_path=Path(owner.output_layout['logs'])/'failure.json'
                if failure_path.parent.is_dir() and not failure_path.exists():
                    immutable_json(failure_path,outcome)
                owner.__exit__(type(cleanup_error) if cleanup_error else RuntimeError,
                    cleanup_error or RuntimeError(outcome.get('error','validation did not finalize')),None)
        finally:
            for number,handler in previous.items():
                signal.signal(number,handler)
        if cleanup_error is not None:
            raise cleanup_error


if __name__ == '__main__':
    raise SystemExit(main())
