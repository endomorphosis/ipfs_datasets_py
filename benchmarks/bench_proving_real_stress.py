"""Bounded real competing-load qualification; never exhaust host resources.

CPU pressure is measured from competitors' Linux scheduling wait counters.
Memory pressure is measured from competitor RSS inside a 1 GiB experiment
budget. Neither scenario invents telemetry or saturates the whole machine.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from ipfs_datasets_py.logic.backends.process import _process_tree_resident_bytes
from ipfs_datasets_py.logic.hammers.models import HammerPolicy
from ipfs_datasets_py.logic.hammers.policy import PortfolioPolicy
from ipfs_datasets_py.logic.hammers.portfolio import PortfolioAttemptSpec, SolverPortfolio, run_bounded_solver_process
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import collect_proof_host_resources
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import GlobalResourceScheduler, ResourceSchedulerConfig

_spec = importlib.util.spec_from_file_location('proving_benchmark', Path(__file__).with_name('bench_resource_aware_proving.py'))
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)

_WORKER = '''import os,resource,sys,time
resource.setrlimit(resource.RLIMIT_AS,(1024**3,1024**3))
resource.setrlimit(resource.RLIMIT_CPU,(20,20))
os.nice(19)
os.sched_setaffinity(0,{int(sys.argv[2])})
allocation=bytearray(int(sys.argv[1])*1024**2)
print("ready",flush=True)
deadline=time.monotonic()+20
while time.monotonic()<deadline:
 if allocation: time.sleep(.02)
 else: sum(i*i for i in range(10000))
'''


def spawn_competitor(memory_mb=0):
    host = collect_proof_host_resources()
    if host.available_memory_mb < max(4096, memory_mb * 4):
        raise RuntimeError('insufficient live memory headroom for bounded stress')
    cpu = max(os.sched_getaffinity(0))
    process = subprocess.Popen([sys.executable, '-u', '-c', _WORKER, str(memory_mb), str(cpu)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    # The allocation is bounded; a subprocess-level deadline also limits CPU use.
    import select
    if not select.select([process.stdout], [], [], 8)[0] or process.stdout.readline().strip() != 'ready':
        process.kill(); process.wait()
        raise RuntimeError('competing worker did not become ready')
    return process


def stop_competitor(process):
    if process.poll() is None:
        process.terminate()
        try: process.wait(timeout=2)
        except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=2)
    process.stdout.close(); process.stderr.close()


def run_real_pressure(path: Path, solver: str, kind: str):
    workers = []
    try:
        for _ in range(3 if kind == 'cpu' else 1):
            workers.append(spawn_competitor(768 if kind == 'memory' else 0))
        time.sleep(.4)  # Accumulate actual scheduling wait, not injected PSI.
        peak = {'rss_mb': 0, 'cpu_wait_percent': 0.0}
        def sample():
            host = collect_proof_host_resources()
            rss = sum(_process_tree_resident_bytes(p.pid) for p in workers if p.poll() is None) // 1024**2
            peak['rss_mb'] = max(peak['rss_mb'], rss)
            if kind == 'memory':
                return replace(host, total_memory_mb=min(host.total_memory_mb, 1024),
                               available_memory_mb=min(host.available_memory_mb, max(0, 1024-rss)))
            execution = waiting = 0
            for process in workers:
                try:
                    values = (Path('/proc')/str(process.pid)/'schedstat').read_text().split()
                    execution += int(values[0]); waiting += int(values[1])
                except (OSError, IndexError, ValueError): pass
            pressure = 100.0 * waiting / max(1, execution + waiting)
            peak['cpu_wait_percent'] = max(peak['cpu_wait_percent'], pressure)
            return replace(host, cpu_stall_percent=max(host.cpu_stall_percent, pressure))
        scheduler = GlobalResourceScheduler(ResourceSchedulerConfig.for_proof_host(
            state_path=path, proof_resource_sampler=sample, total_cpu_slots=4,
            total_child_process_slots=8, lane_reservations={}))
        launches = []
        launch_wall_times = []
        def runner(*args, **kwargs):
            launches.append(time.monotonic())
            launch_wall_times.append(time.time())
            return run_bounded_solver_process(*args, **kwargs)
        portfolio = SolverPortfolio(PortfolioPolicy(hammer_policy=HammerPolicy(
            allowed_solvers=[solver], timeout_seconds=5, memory_mb=256)),
            resource_scheduler=scheduler, process_runner=runner, resource_wait_timeout_seconds=15)
        translation, expected = base.pigeonhole(0)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(portfolio.run, 'real-pressure', [PortfolioAttemptSpec(translation=translation, solver_name=solver)])
            try:
                deadline = time.monotonic() + 8
                while not scheduler.snapshot()['proof_backoff'] and not future.done() and time.monotonic() < deadline:
                    time.sleep(.05)
                backoff = scheduler.snapshot()['proof_backoff']
                if not backoff or launches:
                    raise AssertionError(f'real {kind} pressure failed to block admission; readings={peak}')
            finally:
                for process in workers: stop_competitor(process)
            cleared = time.monotonic()
            result = future.result(timeout=15)
        assert result.attempts[0].verdict.value == expected and len(launches)==1
        recovery = launches[0] - cleared
        # Cooldown begins at the scheduler observation, before worker teardown.
        # Freeing a large allocation can take time, so compare the actual stored
        # deadline rather than requiring a new cooldown after wait() returns.
        assert launch_wall_times[0] >= backoff["until"] - .01
        cooldown_observed = launch_wall_times[0] - (backoff["until"] - scheduler.config.proof_backoff_seconds)
        snapshot = scheduler.snapshot()
        assert snapshot['active_lease_count']==snapshot['waiting_request_count']==0
        return {'kind':kind, 'source':'actual competitor RSS in 1 GiB budget' if kind=='memory' else 'actual competitor Linux schedstat wait',
                'peak_external_rss_mb':peak['rss_mb'], 'peak_cpu_wait_percent':peak['cpu_wait_percent'],
                'backoff_reason':backoff['reason'], 'launches_during_pressure':0,
                'recovery_seconds':recovery, 'cooldown_observed_seconds':cooldown_observed, 'verdict':expected, 'leases_remaining':0}
    finally:
        for process in workers:
            if process.poll() is None: stop_competitor(process)


def run_competing_batch(path: Path, solvers: list[str], jobs=16):
    worker = spawn_competitor(256)
    cpu_workers=[]
    try:
        for _ in range(2): cpu_workers.append(spawn_competitor())
        scheduler = GlobalResourceScheduler(ResourceSchedulerConfig.for_proof_host(
            state_path=path, total_cpu_slots=4, total_child_process_slots=8, lane_reservations={}))
        trial = base.run_trial(scheduler, solvers, workers=4, jobs=jobs)
        assert trial['peak_reserved_cpu_slots'] <= 4
        assert trial['peak_reserved_memory_mb'] <= scheduler.config.total_memory_mb
        trial['external_load']={'memory_allocation_mb':256,'cpu_workers':2,'cpu_affinity_width':1,'nice':19}
        return trial
    finally:
        stop_competitor(worker)
        for process in cpu_workers: stop_competitor(process)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args(); args.out.mkdir(parents=True,exist_ok=True)
    solvers=[name for name in ('z3','cvc5') if shutil.which(name)]
    if not solvers: parser.error('requires a real SMT solver')
    report={'pressure':[run_real_pressure(args.out/f'{kind}.json',solvers[0],kind) for kind in ('memory','cpu')],
            'competing_batch':run_competing_batch(args.out/'batch.json',solvers),
            'scope':'real bounded external workers; experiment memory budget and CPU scheduling counters, not host saturation'}
    (args.out/'stress.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__': main()
