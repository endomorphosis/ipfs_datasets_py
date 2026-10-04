"""Controlled real Python fallback admission under synthetic external pressure.

All evaluations use the actual bounded evaluator and real private scheduler.
Native tools, installers, the shared pool and real host-pressure sampling are
denied. The concurrent pair checks accounting, not CPU parallel speedup.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import traceback
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT.parent/'ipfs_accelerate'), str(ROOT)]
import bench_hyper_fallback_validation as fixtures


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True)+'\n')


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def pins():
    relative = ['benchmarks/bench_hyper_python_admission.py',
        'ipfs_datasets_py/logic/backends/python_admission.py',
        'ipfs_datasets_py/logic/backends/hyperproperties/adapters.py',
        'ipfs_datasets_py/logic/backends/hyperproperties/execution_v2.py',
        'ipfs_datasets_py/logic/backends/installers/hyperproperty.py',
        'ipfs_datasets_py/logic/software_verification/hyperproperties.py',
        'ipfs_datasets_py/logic/backends/smt/operation_budget.py',
        'ipfs_datasets_py/optimizers/logic_theorem_optimizer/resource_scheduler.py',
        'ipfs_datasets_py/optimizers/logic_theorem_optimizer/proof_resource_safety.py',
        'tests/unit/logic/backends/test_hyper_python_admission.py',
        'tests/unit/logic/backends/_python_admission_fixtures.py']
    return {**fixtures.pins(), **{str(ROOT/path): sha(ROOT/path) for path in relative}}


class Environment:
    def __init__(self, directory):
        self.directory = directory
        self.stack = ExitStack()
        self.forbidden = []
        self.acquired = []
        self.samples = []

    def __enter__(self):
        from ipfs_datasets_py.logic.backends import process, python_admission as admission
        from ipfs_datasets_py.logic.backends.hyperproperties import adapters
        from ipfs_datasets_py.logic.backends.installers import hyperproperty as installer
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as schedulers
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
        self.healthy = ProofHostResources(8, 8192, 8192, pid_task_limit=8192, available_pid_tasks=8192)
        self.current = self.healthy
        def sample():
            self.samples.append({'available_memory_mb': self.current.available_memory_mb,
                                 'cpu_stall_percent': self.current.cpu_stall_percent})
            return self.current
        self.owner = schedulers.GlobalResourceScheduler(schedulers.ResourceSchedulerConfig.for_proof_host(
            state_path=self.directory/'private-pool.json', proof_resource_sampler=sample,
            total_cpu_slots=4, total_memory_mb=1024, total_child_process_slots=16,
            lane_reservations={}, proof_memory_headroom_mb=64, proof_backoff_seconds=.01,
            poll_interval_seconds=.002, auto_renew_leases=False))
        acquire = self.owner.acquire
        def observed(*args, **kwargs):
            lease = acquire(*args, **kwargs)
            self.acquired.append(lease)
            require((lease.cpu_slots, lease.memory_mb, lease.child_process_slots)==(1,128,0),
                    'Python profile differs from1CPU/128MiB/0process')
            return lease
        self.stack.enter_context(patch.object(self.owner, 'acquire', observed))
        def deny(name):
            def blocked(*args, **kwargs):
                self.forbidden.append(name)
                raise AssertionError('controlled admission forbids '+name)
            return blocked
        self.stack.enter_context(patch.object(subprocess, 'Popen', deny('native Popen')))
        self.stack.enter_context(patch.object(os, 'system', deny('os.system')))
        self.stack.enter_context(patch.object(process.SubprocessExecutor, 'execute', deny('native executor')))
        self.stack.enter_context(patch.object(process.BoundedToolRunner, '_write_inputs', staticmethod(deny('workspace'))))
        self.stack.enter_context(patch.object(installer, '_ensure_tool', deny('installer entry')))
        self.stack.enter_context(patch.object(schedulers, 'get_global_resource_scheduler', deny('shared scheduler')))
        self.stack.enter_context(patch.object(admission, 'get_global_resource_scheduler', deny('implicit scheduler')))
        self.stack.enter_context(patch.dict(adapters.HyperpropertyBackend.__init__.__kwdefaults__, {'which': lambda name: None}))
        self.before = self.owner.snapshot()
        return self

    def __exit__(self, *args):
        self.after = self.owner.snapshot()
        self.stack.__exit__(*args)
        require(not self.forbidden, 'a forbidden host route was attempted')
        require(self.after['active_lease_count']==self.after['waiting_request_count']==0, 'private work leaked')
        require(all(lease.released for lease in self.acquired), 'Python reservation remains active')


def run_evaluation(environment, provider, label, *, cancellation=None, hold=None):
    from ipfs_datasets_py.logic.backends import python_admission as admission
    from ipfs_datasets_py.logic.backends.hyperproperties import execution_v2 as v2
    from ipfs_datasets_py.logic.backends.smt.operation_budget import current_proof_operation
    from ipfs_datasets_py.logic.software_verification.hyperproperties import HyperpropertyIR
    request = fixtures.request(provider, 'violated', label)
    request = replace(request, bounds=replace(request.bounds, timeout_ms=4000))
    row = {'case': label, 'provider': provider, 'status': 'running', 'evaluations': []}
    started = time.monotonic()
    def observe(frame, event, value):
        if event=='call' and frame.f_code is HyperpropertyIR.evaluate_bounded_noninterference.__code__:
            snapshot = environment.owner.snapshot()
            require(snapshot['active_lease_count'] >= 1 and current_proof_operation() is not None,
                    'evaluation lacks actual admission or operation')
            row['evaluations'].append({'allocated': snapshot['allocated'],
                'allocated_process_slots': snapshot['allocated_child_process_slots'],
                'active_roots': snapshot['active_root_lease_count']})
            if hold is not None and len(row['evaluations'])==1:
                hold(snapshot)
    try:
        require(sys.getprofile() is None, 'unexpected profiler')
        with admission.python_admission_context(scheduler=environment.owner):
            sys.setprofile(observe)
            try:
                result = v2.HyperExecutionEngineV2().execute(request, cancellation=cancellation)
            finally:
                sys.setprofile(None)
        require(result.disposition.value=='violated' and not result.is_proved and not result.hyperproperty_established,
                'fallback acquired incorrect authority')
        require(len(row['evaluations'])>=2, 'private result applicability was not reevaluated')
        row.update(status='passed', result=result.to_dict())
    except BaseException as error:
        row.update(status='stopped' if isinstance(error, Exception) and type(error).__name__ in
                   {'ProofOperationCancelled','ProofOperationTimeout'} else 'failed',
                   exception=type(error).__name__)
        if row['status']=='failed': row['error']=traceback.format_exc()
    finally:
        sys.setprofile(None)
        row.update(elapsed_seconds=time.monotonic()-started, ambient_restored=current_proof_operation() is None)
        fixtures.assert_private_absent(row)
    return row


def wait_for_queue(environment):
    deadline = time.monotonic()+1.0
    while time.monotonic()<deadline:
        snap = environment.owner.snapshot()
        if snap['waiting_request_count']:
            require(snap['active_lease_count']==0 and not environment.acquired, 'queued evaluation already admitted')
            return snap
        time.sleep(.002)
    raise AssertionError('controlled request never reached admission queue')


def pressure_case(directory, provider, cancel):
    directory.mkdir(); signal = threading.Event(); result = {}
    with Environment(directory) as environment:
        environment.current = replace(environment.healthy, available_memory_mb=0)
        worker = threading.Thread(target=lambda: result.update(row=run_evaluation(environment, provider,
            provider+(':cancel' if cancel else ':recover'), cancellation=signal)))
        worker.start()
        try:
            queued = wait_for_queue(environment)
            if cancel: signal.set()
            else: environment.current = environment.healthy
            worker.join(3)
            require(not worker.is_alive(), 'bounded worker did not finish')
        finally:
            signal.set(); environment.current=environment.healthy; worker.join(3)
        row = result['row']
        require(row['status']==('stopped' if cancel else 'passed'), 'unexpected pressure outcome')
        if cancel: require(row['exception']=='ProofOperationCancelled' and not row['evaluations'], 'queue cancel evaluated')
        row['queued_snapshot']=queued
    row.update(private_before=environment.before, private_after=environment.after,
        leases=[{**lease.to_dict(), 'released':lease.released} for lease in environment.acquired], forbidden_attempts=environment.forbidden)
    return row


def concurrent_cases(directory):
    directory.mkdir(); entered=threading.Barrier(2, timeout=2); arrived=threading.Event(); release=threading.Event(); rows={}
    with Environment(directory) as environment:
        def hold(snapshot):
            entered.wait()
            arrived.set()
            require(release.wait(2), 'concurrent release timed out')
        workers=[threading.Thread(target=lambda provider=provider: rows.update({provider:run_evaluation(
            environment, provider, provider+':concurrent', hold=hold)})) for provider in ('hyperltl','autohyper')]
        for worker in workers: worker.start()
        try:
            require(arrived.wait(1), 'both evaluations did not enter under admission')
            # Both admitted evaluations remain held after the barrier opens.
            overlap=environment.owner.snapshot()
            require(overlap['allocated']=={'cpu_slots':2,'memory_mb':256}, 'concurrent reservations did not overlap')
            require(overlap['allocated_child_process_slots']==0, 'Python work claimed process slots')
        finally:
            release.set()
            for worker in workers: worker.join(3)
        require(all(not worker.is_alive() for worker in workers), 'concurrent worker leaked')
        require(len(rows)==2 and all(row['status']=='passed' for row in rows.values()), 'concurrent evaluation failed')
    for row in rows.values():
        row.update(overlap=overlap, private_after=environment.after, forbidden_attempts=environment.forbidden,
                   all_owned_leases_released=all(lease.released for lease in environment.acquired))
    return list(rows.values())


def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--output-dir',type=Path,required=True)
    directory=parser.parse_args().output_dir.resolve(); directory.mkdir(parents=True,exist_ok=False)
    result={'schema':'hyper-python-admission-controlled@1','status':'running','cases':[],
        'source_pins_before':pins(),'native_launches':0,'shared_pool_accesses':0,
        'scope':{'real_private_scheduler':True,'actual_bounded_evaluator':True,'synthetic_pressure':True,
                 'hard_memory_containment':False,'active_pressure_pause':False,'scaling_claim':False}}
    started=time.monotonic()
    try:
        for provider in ('hyperltl','autohyper','mchyper'):
            for cancel in (False,True):
                row=pressure_case(directory/(provider+('-cancel' if cancel else '-recover')),provider,cancel)
                result['cases'].append(row);write(directory/'partial.json',result)
        result['cases'].extend(concurrent_cases(directory/'concurrent'))
        result['source_pins_after']=pins()
        result['checks']={'all8_cases':len(result['cases'])==8,
            'five_successful_api_cases':sum(row['status']=='passed' for row in result['cases'])==5,
            'three_queued_cancellations':sum(row['status']=='stopped' for row in result['cases'])==3,
            'all_private_owners_drained':all(row['private_after']['active_lease_count']==row['private_after']['waiting_request_count']==0 for row in result['cases']),
            'ambient_restored':all(row['ambient_restored'] for row in result['cases']),
            'host_routes_denied':all(not row['forbidden_attempts'] for row in result['cases']),
            'sources_stable':result['source_pins_before']==result['source_pins_after']}
        require(all(result['checks'].values()),'controlled admission checks failed')
        result['status']='passed_controlled'
    except BaseException:
        result.update(status='failed',error=traceback.format_exc(),source_pins_after=pins())
    finally:
        result['elapsed_seconds']=time.monotonic()-started
        fixtures.assert_private_absent(result);write(directory/'result.json',result)
    print(json.dumps({'status':result['status'],'cases':len(result['cases']),'seconds':result['elapsed_seconds']}))
    return 0 if result['status']=='passed_controlled' else 1


if __name__=='__main__':
    raise SystemExit(main())
