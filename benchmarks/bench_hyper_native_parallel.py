"""Bounded real Hyper parallel trials and separately labeled lease contention.

No host pressure is manufactured. Native phases use unchanged default managed
runners and the real shared scheduler/sampler. The capacity experiment uses a
small explicit parent envelope and no native work; it is not host PSI backoff.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from contextlib import ExitStack
from dataclasses import asdict, dataclass
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import threading
import time
import uuid
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
MIB=1024**2


@dataclass(frozen=True)
class Options:
    workers: int=2
    cases: int=10
    aggregate_seconds: float=120

    def __post_init__(self):
        if type(self.workers) is not int or not 1<=self.workers<=4:
            raise ValueError('workers must be an integer from 1 to 4')
        if type(self.cases) is not int or self.cases not in (5,10,15):
            raise ValueError('cases per phase must be 5, 10 or 15; at most 30 total')
        if isinstance(self.aggregate_seconds,bool) or not isinstance(self.aggregate_seconds,(int,float)) or not math.isfinite(self.aggregate_seconds) or not 5<=self.aggregate_seconds<=300:
            raise ValueError('aggregate_seconds must be finite, between 5 and 300')


def interval_metrics(intervals):
    events=[]
    for start,end in intervals:
        if not math.isfinite(start) or not math.isfinite(end) or end<start:
            raise ValueError('invalid observed interval')
        if end>start:
            events.extend(((start,1),(end,-1)))
    active=peak=0
    union=overlap=0.0
    previous=None
    for at,delta in sorted(events):
        if previous is not None:
            union+=(at-previous) if active else 0
            overlap+=(at-previous) if active>1 else 0
        active+=delta;peak=max(peak,active);previous=at
    return {'peak_launch_to_cleanup_intervals':peak,'union_seconds':union,'overlap_seconds':overlap,
            'scope':'observed launch-to-executor-cleanup intervals, not CPU utilization'}


def bounded_map(items,worker,*,workers,deadline,cancellation):
    """Join all workers on every path; cooperative native cleanup may outlive deadline."""
    if cancellation.is_set() or time.monotonic()>=deadline:
        cancellation.set()
        return [{'status':'cancelled_before_start'} for _ in items]
    records={}
    with ThreadPoolExecutor(max_workers=workers,thread_name_prefix='hyper-native') as pool:
        futures={pool.submit(worker,item):index for index,item in enumerate(items)}
        pending=set(futures)
        try:
            while pending:
                remaining=deadline-time.monotonic()
                if remaining<=0:
                    cancellation.set()
                    break
                done,pending=wait(pending,timeout=min(.05,remaining),return_when=FIRST_COMPLETED)
                for future in done:
                    index=futures[future]
                    try:
                        records[index]={'status':'passed','value':future.result()}
                    except Exception as error:
                        records[index]={'status':'stopped','exception_type':type(error).__name__,'error':str(error)}
                        cancellation.set()
                if cancellation.is_set():
                    break
        finally:
            if pending:
                cancellation.set()
            for future in pending:
                future.cancel()
            # Context-manager shutdown waits for real production cancellation
            # and tree cleanup. Never leave native tasks running in background.
    for future,index in futures.items():
        if index in records:
            continue
        if future.cancelled():
            records[index]={'status':'cancelled_before_start'}
        else:
            try:
                records[index]={'status':'passed','value':future.result()}
            except Exception as error:
                records[index]={'status':'stopped','exception_type':type(error).__name__,'error':str(error)}
    return [records[index] for index in range(len(items))]


def capacity_contention(owner,*,deadline,cancellation):
    """Actual child-capacity wait within a modest explicitly reserved envelope."""
    result={'status':'running','scope':'scheduler-only parent capacity contention; no native work or manufactured host pressure',
            'parent_request':{'cpu_slots':4,'memory_mb':1024,'child_process_slots':8}}
    config=owner.config
    if config.total_cpu_slots<8 or config.total_child_process_slots<16 or config.total_memory_mb<2048:
        result.update(status='skipped_insufficient_capacity',reason='parent envelope would exceed half a configured capacity')
        return result
    local=threading.Event()
    class Signal:
        def is_set(self):return local.is_set() or cancellation.is_set() or time.monotonic()>=deadline
    signal=Signal();held=[];all_owned=[];parent=None;thread=None;acquired=[];errors=[]
    token='hyper-capacity-'+uuid.uuid4().hex
    result['request_namespace']=token
    def owned_waiters():
        with owner._locked_state(persist=False) as state:
            return [{key:row[key] for key in ('waiter_id','request_id','parent_lease_id','owner_pid','cpu_slots','memory_mb','child_process_slots')}
                for row in state['waiters'].values() if row.get('owner_pid')==os.getpid()
                and row.get('request_id','').startswith(token)]
    remaining=lambda:max(0,min(5,deadline-time.monotonic()))
    try:
        parent=owner.acquire('validation',**result['parent_request'],timeout=remaining(),cancel_event=signal,
                             request_id=token+'-parent')
        all_owned.append(parent)
        result['parent_lease_id']=parent.lease_id
        for index in range(2):
            child=owner.acquire('validation',cpu_slots=2,memory_mb=512,child_process_slots=4,
                        parent_lease=parent,timeout=remaining(),cancel_event=signal,request_id=token+f'-held-{index}')
            held.append(child);all_owned.append(child)
        entered=threading.Event()
        def queued():
            entered.set()
            try:
                lease=owner.acquire('validation',cpu_slots=2,memory_mb=512,child_process_slots=4,
                    parent_lease=parent,timeout=remaining(),cancel_event=signal,request_id=token+'-waiter')
                all_owned.append(lease)
                acquired.append((lease,time.monotonic()))
            except Exception as error:
                errors.append((type(error).__name__,str(error)))
        thread=threading.Thread(target=queued,name='hyper-capacity-waiter')
        started=time.monotonic();thread.start();entered.wait(timeout=remaining())
        observed=False
        while thread.is_alive() and time.monotonic()<min(deadline,started+2):
            rows=owned_waiters()
            if any(row['request_id']==token+'-waiter' and row['parent_lease_id']==parent.lease_id for row in rows):
                result['owned_queued_waiters']=rows
                result['queued_snapshot']=owner.snapshot();observed=True;break
            local.wait(.01)
        if not observed:
            result.update(status='blocked_queue_not_observed',errors=errors)
            return result
        if acquired:raise AssertionError('child escaped the full parent envelope')
        result['released_at']=time.monotonic();held.pop().release()
        thread.join(timeout=remaining())
        if acquired:
            lease,at=acquired[0]
            if at<result['released_at']:raise AssertionError('child grant preceded capacity release')
            result.update(status='passed_capacity_contention',wait_seconds=lease.wait_seconds,
                granted_at=at,recovery_seconds=at-result['released_at'],child_lease_id=lease.lease_id)
        else:
            result.update(status='blocked_admission',errors=errors)
    except Exception as error:
        result.update(status='blocked_admission',exception_type=type(error).__name__,error=str(error))
    finally:
        local.set()
        if thread is not None:
            thread.join()
        for lease,_ in acquired:lease.release()
        for lease in reversed(held):lease.release()
        if parent is not None:parent.release()
        result['owned_leases_released']=all(lease.released for lease in all_owned)
        result['owned_lease_ids']=[lease.lease_id for lease in all_owned]
        result['waiter_thread_joined']=thread is None or not thread.is_alive()
        result['owned_waiters_remaining']=owned_waiters()
        if result['owned_waiters_remaining'] or not result['owned_leases_released']:
            result['status']='failed_owned_cleanup'
    return result


class ObservationList(list):
    def __init__(self):
        super().__init__();self.lock=threading.Lock()

    def append(self,item):
        with self.lock:super().append(item)

    def __iter__(self):
        with self.lock:return iter(tuple(super().__iter__()))


class LockedExitStack(ExitStack):
    def __init__(self):
        super().__init__();self.registration_lock=threading.RLock()

    def enter_context(self,context):
        with self.registration_lock:
            return super().enter_context(context)


def policy(owner):
    keys=('total_cpu_slots','total_memory_mb','total_child_process_slots','proof_safety_enabled',
          'proof_memory_headroom_mb','proof_memory_stall_percent','proof_cpu_stall_percent',
          'proof_io_stall_percent','proof_backoff_seconds')
    return {key:getattr(owner.config,key) for key in keys}


def require_real_owner(owner,sampler):
    if owner.config.proof_safety_enabled is not True or owner.config.proof_resource_sampler is not sampler:
        raise RuntimeError('native qualification requires actual host sampler and enabled proof safety')


def invoke_recorded(scope,operation,row):
    # Save an actual returned value before the operation scope's final gate;
    # an exit-time timeout still stops qualification and keeps diagnostics.
    with scope:
        outcome=operation()
        row['outcome']=outcome.to_dict()
        return outcome


def single_case_records(audit,case):
    records={}
    for name in ('admissions','invocations','launches','lifecycles'):
        selected=[row for row in getattr(audit,name) if row['case']==case]
        if len(selected)!=1:
            raise AssertionError('native case must have exactly one '+name)
        records[name]=selected[0]
    return records


def load_smoke():
    path=Path(__file__).with_name('bench_hyper_native_smoke.py')
    spec=importlib.util.spec_from_file_location('hyper_native_parallel_smoke_helpers',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def run(directory,install_root,options):
    smoke=load_smoke()
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import collect_proof_host_resources
    sources=tuple(sorted(set(smoke.source_inventory())|{Path(__file__).resolve(),
        ROOT/'tests/unit/logic/backends/test_hyper_native_parallel_benchmark.py'}))
    started=time.monotonic();deadline=started+options.aggregate_seconds;cancel=threading.Event()
    result={'status':'running','options':asdict(options),'install_root':str(install_root),
        'source_pins_before':smoke.pin(sources),'phases':{},'scope':{
            'real_native_default_runners':True,'actual_default_shared_scheduler':True,'actual_host_sampler':True,
            'synthetic_results_or_pressure':False,'manufactured_external_pressure':False,
            'capacity_contention_is_separate_custom_parent_envelope':True,'many_core_scaling_claim':False,
            'semantic_witness_reconstruction_qualified':False}}
    audit=None;samples=[];monitor_stop=threading.Event();monitor=None;observations=[]
    timer=threading.Timer(options.aggregate_seconds,cancel.set);timer.start()
    class ConcurrentAudit(smoke.NativeAudit):
        def __init__(self,directory):
            super().__init__(directory);self.stack=LockedExitStack()
            for name in ('admissions','invocations','launches','lifecycles','children','leases'):
                setattr(self,name,ObservationList())
    try:
        with ExitStack() as guards:
            def forbidden(*args,**kwargs):raise AssertionError('parallel native driver forbids installation/publication/download')
            for name in ('_ensure_tool','_download_verified_archive','_publish_managed_vendor_launcher','_replace_install_tree'):
                guards.enter_context(patch.object(smoke.hp,name,forbidden))
            for name in ('backend_for','run_engine_case'):
                guards.enter_context(patch.object(smoke.fixtures,name,forbidden))
            identities={}
            for engine in smoke.ENGINES:
                with smoke.installation_scope(operation_timeout_ms=max(1,int(min(60,deadline-time.monotonic())*1000))):
                    identity=smoke.hp._identity_from_disk(engine,install_root,
                        smoke.hp.pin_for_tool(engine,repo_root=smoke.ACCELERATE,lock_path=smoke.LOCK_PATH),vendor=True)
                smoke.require(identity is not None and identity.is_vendor_build and identity.is_upstream_build
                              and not identity.is_hermetic_engine,'valid installed upstream identity required')
                identities[engine]=identity
            result['identities']={key:value.to_dict() for key,value in identities.items()}
            specs={spec.case_id:spec for spec in smoke.fixtures.default_case_specs()}
            base=[('hyperltl',False),('autohyper',False),('autohyper',True),('mchyper',False),('mchyper',True)]
            matrix=[(*base[index%5],index) for index in range(options.cases)]
            with ConcurrentAudit(directory) as audit:
                require_real_owner(audit.owner,collect_proof_host_resources)
                result['scheduler_policy_before']=policy(audit.owner)
                host=collect_proof_host_resources();result['host_preflight']=asdict(host)
                needed=options.workers*512
                if host.available_memory_mb<audit.owner.config.proof_memory_headroom_mb+needed+512:
                    result['status']='blocked_host_headroom'
                elif options.workers*2>audit.owner.config.total_cpu_slots or options.workers*4>audit.owner.config.total_child_process_slots:
                    result['status']='blocked_configured_capacity'
                else:
                    phase_name=['initial']
                    def sample_roots():
                        while not monitor_stop.wait(.01):
                            live=[child.pid for child in tuple(audit.children) if child.poll() is None]
                            samples.append({'phase':phase_name[0],'at':time.monotonic(),'live_owned_root_pids':live})
                    monitor=threading.Thread(target=sample_roots,name='hyper-native-root-observer');monitor.start()
                    for phase,workers in (('sequential',1),('parallel',options.workers)):
                        phase_name[0]=phase
                        phase_started=time.monotonic()
                        def worker(item):
                            engine,violated,index=item
                            remaining=min(30,deadline-time.monotonic())
                            if remaining<=0 or cancel.is_set():raise TimeoutError('aggregate benchmark stopped')
                            case_id=f'{phase}-{index:02d}-{engine}';audit.local.case=case_id
                            audit.local.engine=engine;audit.local.executable=Path(identities[engine].executable).resolve()
                            backend=smoke.BACKENDS[engine](engine_identity=identities[engine])
                            smoke.require(type(backend._runner) is smoke.resource_admission.ResourceAdmittedToolRunner
                                          and backend._managed_runner,'default managed runner changed')
                            document=smoke.fixtures.materialize_document(specs['case:ni_violated' if violated else 'case:ni_holds'])
                            system=smoke.fixtures.vendor_system_model(engine,violated=violated)
                            bounds=smoke.ExecutionBounds(timeout_ms=30000,max_steps=64,max_memory_bytes=512*MIB,max_output_bytes=MIB)
                            expected='violated' if violated else 'satisfied'
                            row={'case':case_id,'engine':engine,'expected':expected,'document':document.to_dict(),
                                 'system_model':system,'bounds':bounds.to_dict()}
                            observations.append(row)
                            outcome=invoke_recorded(
                                smoke.proof_operation_scope(timeout_ms=max(1,int(remaining*1000)),cancellation=cancel),
                                lambda:backend.check(document,bounds=bounds,system_model=system,allow_fallback=False),row)
                            smoke.require(outcome.receipt.status.value==expected,'native verdict did not match fixture')
                            smoke.require(outcome.receipt.evidence_path is smoke.adapters.HyperEvidencePath.ENGINE
                                          and outcome.receipt.fallback_bounds is None and not outcome.receipt.authorizes_universal_proof,
                                          'native authority/path changed')
                            smoke.require(outcome.result.bounds==bounds and outcome.result.authority.value=='hyperproperty',
                                          'native result changed declared bounds or authority')
                            life=single_case_records(audit,case_id)['lifecycles']
                            smoke.require(life['returncode']==0 and life['workspace_cleaned'] and not any(life[key] for key in smoke.UNSAFE),
                                          'native verdict lacks clean complete lifecycle')
                            return row
                        rows=bounded_map(matrix,worker,workers=workers,deadline=deadline,cancellation=cancel)
                        result['phases'][phase]={'cases':rows,'elapsed_seconds':time.monotonic()-phase_started}
                        smoke.write(directory/'partial.json',result)
                        if any(row['status']!='passed' for row in rows):
                            result['status']='incomplete_native_phase';break
                    if all(name in result['phases'] and all(row['status']=='passed' for row in result['phases'][name]['cases']) for name in ('sequential','parallel')):
                        # Restore lease acquisition observer before scheduler-only
                        # child requests, whose dimensions intentionally differ.
                        result['status']='native_phases_passed'
            monitor_stop.set()
            if monitor is not None:monitor.join()
            if result['status']=='native_phases_passed':
                result['contention']=capacity_contention(audit.owner,deadline=deadline,cancellation=cancel)
                result['status']='passed_bounded_native_parallel' if result['contention']['status']=='passed_capacity_contention' else 'native_passed_contention_not_qualified'
            result['scheduler_policy_after']=policy(audit.owner)
            smoke.require(result['scheduler_policy_before']==result['scheduler_policy_after'],'scheduler policy changed')
            if deadline<=time.monotonic():
                result['status']='stopped_aggregate_deadline'
                return result
            result['identities_after']={}
            for engine in smoke.ENGINES:
                with smoke.installation_scope(operation_timeout_ms=max(1,int(min(60,deadline-time.monotonic())*1000))):
                    identity=smoke.hp._identity_from_disk(engine,install_root,
                        smoke.hp.pin_for_tool(engine,repo_root=smoke.ACCELERATE,lock_path=smoke.LOCK_PATH),vendor=True)
                smoke.require(identity is not None,'final identity audit failed')
                result['identities_after'][engine]=identity.to_dict()
            smoke.require(result['identities']==result['identities_after'],'native identity changed')
    except Exception as error:
        cancel.set();result.update(status='failed',exception_type=type(error).__name__,error=str(error))
    finally:
        timer.cancel();timer.join()
        monitor_stop.set()
        if monitor is not None:monitor.join()
        result.update(elapsed_seconds=time.monotonic()-started,source_pins_after=smoke.pin(sources),root_samples=samples,case_observations=observations)
        if audit is not None:
            result.update(admissions=audit.admissions,invocations=audit.invocations,native_launches=audit.launches,
                lifecycles=audit.lifecycles,cleanup=getattr(audit,'cleanup',{}),
                shared_before=getattr(audit,'before',None),shared_after=getattr(audit,'after',None))
            for phase,summary in result['phases'].items():
                inv={row['case']:row for row in audit.invocations if row['case'].startswith(phase+'-')}
                intervals=[(row['at'],inv[row['case']]['completed_at']) for row in audit.launches
                           if row['case'] in inv and 'completed_at' in inv[row['case']]]
                summary['transport_overlap']=interval_metrics(intervals)
                summary['peak_sampled_live_owned_roots']=max((len(row['live_owned_root_pids']) for row in samples if row['phase']==phase),default=0)
            if all(name in result['phases'] for name in ('sequential','parallel')):
                result['single_trial_elapsed_ratio']=result['phases']['sequential']['elapsed_seconds']/max(.000001,result['phases']['parallel']['elapsed_seconds'])
        result['checks']={'stable_sources':result['source_pins_before']==result['source_pins_after'],
            'native_owned_cleanup':bool(audit is not None and getattr(audit,'cleanup',None) and all(audit.cleanup.values())),
            'identities_unchanged':result.get('identities')==result.get('identities_after') and bool(result.get('identities'))}
        if result['status']=='passed_bounded_native_parallel' and not all(result['checks'].values()):result['status']='failed'
        smoke.write(directory/'result.json',result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install-root',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--workers',type=int,default=2)
    parser.add_argument('--cases',type=int,default=10)
    parser.add_argument('--aggregate-seconds',type=float,default=120)
    args=parser.parse_args();options=Options(args.workers,args.cases,args.aggregate_seconds)
    root=args.install_root.expanduser().resolve();directory=args.output_dir.expanduser().resolve()
    if not root.is_dir():parser.error('existing audited installation prefix required')
    directory.mkdir(parents=True,exist_ok=False)
    result=run(directory,root,options)
    print(json.dumps({key:result[key] for key in ('status','elapsed_seconds')}),flush=True)
    return 0 if result['status']=='passed_bounded_native_parallel' else 1


if __name__=='__main__':raise SystemExit(main())
