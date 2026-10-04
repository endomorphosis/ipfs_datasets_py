"""Driver mechanics only: no solvers, subprocesses, network or shared scheduler."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

_PATH=Path(__file__).resolve().parents[4]/'benchmarks/bench_hyper_native_parallel.py'
_SPEC=importlib.util.spec_from_file_location('test_native_parallel_driver',_PATH)
bench=importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name]=bench
_SPEC.loader.exec_module(bench)


@pytest.fixture(autouse=True)
def no_native(monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError('unit fixture attempted native/shared execution')
    monkeypatch.setattr(subprocess,'Popen',forbidden)
    monkeypatch.setattr(bench,'load_smoke',forbidden)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as rs
    monkeypatch.setattr(rs,'get_global_resource_scheduler',forbidden)


@pytest.mark.parametrize('kwargs',[
    {'workers':0},{'workers':5},{'workers':True},{'workers':1.5},
    {'cases':0},{'cases':16},{'cases':30},{'cases':True},
    {'aggregate_seconds':0},{'aggregate_seconds':301},{'aggregate_seconds':float('inf')},
    {'aggregate_seconds':float('nan')},{'aggregate_seconds':True},
])
def test_options_reject_unbounded_or_ambiguous_work(kwargs):
    with pytest.raises(ValueError):bench.Options(**kwargs)


@pytest.mark.parametrize('workers',[1,2,4])
@pytest.mark.parametrize('cases',[5,10,15])
def test_finite_options(workers,cases):
    value=bench.Options(workers,cases,30)
    assert value.cases*2<=30 and value.workers<=4


def test_overlap_distinguishes_touching_from_concurrent_intervals():
    touching=bench.interval_metrics([(0,1),(1,2)])
    overlapping=bench.interval_metrics([(0,2),(1,3),(1.5,2.5)])
    assert touching['peak_launch_to_cleanup_intervals']==1 and touching['overlap_seconds']==0
    assert overlapping['peak_launch_to_cleanup_intervals']==3
    assert overlapping['union_seconds']==3 and overlapping['overlap_seconds']==1.5


@pytest.mark.parametrize('intervals',[[(2,1)],[(0,float('inf'))],[(float('nan'),1)]])
def test_invalid_metrics_fail_closed(intervals):
    with pytest.raises(ValueError):bench.interval_metrics(intervals)


def test_map_keeps_input_order_despite_completion_order():
    first=threading.Event();cancel=threading.Event()
    def worker(value):
        if value==0:assert first.wait(1)
        else:first.set()
        return value
    rows=bench.bounded_map([0,1],worker,workers=2,deadline=time.monotonic()+2,cancellation=cancel)
    assert [row['value'] for row in rows]==[0,1]
    assert not cancel.is_set()


def test_failure_cancels_cooperative_peer_and_joins_cleanup():
    peer_started=threading.Event();peer_drained=threading.Event();cancel=threading.Event()
    def worker(value):
        if value==0:
            assert peer_started.wait(1)
            raise ValueError('fixture failure')
        peer_started.set()
        try:assert cancel.wait(1)
        finally:peer_drained.set()
        raise RuntimeError('peer stopped')
    rows=bench.bounded_map([0,1],worker,workers=2,deadline=time.monotonic()+2,cancellation=cancel)
    assert peer_drained.is_set() and cancel.is_set()
    assert {row['exception_type'] for row in rows}=={'ValueError','RuntimeError'}


def test_expired_budget_submits_no_worker():
    called=[];cancel=threading.Event()
    rows=bench.bounded_map([1,2],called.append,workers=1,deadline=time.monotonic()-1,cancellation=cancel)
    assert called==[] and rows==[{'status':'cancelled_before_start'}]*2 and cancel.is_set()


def test_deadline_signals_and_drains_active_worker():
    drained=threading.Event();cancel=threading.Event()
    def worker(value):
        assert cancel.wait(1)
        drained.set();raise TimeoutError('cooperative stop')
    rows=bench.bounded_map([1],worker,workers=1,deadline=time.monotonic()+.03,cancellation=cancel)
    assert drained.is_set() and rows[0]['exception_type']=='TimeoutError'


@pytest.mark.parametrize('enabled,same',[(False,True),(True,False),(1,True)])
def test_native_claim_requires_enabled_real_sampler(enabled,same):
    actual=lambda:None
    owner=SimpleNamespace(config=SimpleNamespace(proof_safety_enabled=enabled,
                           proof_resource_sampler=actual if same else lambda:None))
    with pytest.raises(RuntimeError):bench.require_real_owner(owner,actual)


@pytest.fixture
def owner(tmp_path):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as rs
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.proof_resource_safety import ProofHostResources
    healthy=ProofHostResources(16,8192,8192,pid_task_limit=1024,available_pid_tasks=1024)
    return rs.GlobalResourceScheduler(rs.ResourceSchedulerConfig.for_proof_host(
        state_path=tmp_path/'private.json',total_cpu_slots=8,total_memory_mb=2048,total_child_process_slots=16,
        proof_resource_sampler=lambda:healthy,lane_reservations={},auto_renew_leases=False,
        proof_memory_headroom_mb=64,proof_backoff_seconds=.01,poll_interval_seconds=.002))


def test_actual_private_child_capacity_queues_recovers_and_drains(owner):
    result=bench.capacity_contention(owner,deadline=time.monotonic()+3,cancellation=threading.Event())
    assert result['status']=='passed_capacity_contention'
    assert result['queued_snapshot']['waiting_request_count']==1
    assert len(result['owned_lease_ids'])==4 and result['owned_leases_released'] and result['waiter_thread_joined']
    after=owner.snapshot()
    assert after['active_lease_count']==after['waiting_request_count']==0
    assert 'no native work' in result['scope']


def test_precancelled_contention_does_not_leak(owner):
    cancel=threading.Event();cancel.set()
    result=bench.capacity_contention(owner,deadline=time.monotonic()+2,cancellation=cancel)
    assert result['status']=='blocked_admission' and result['owned_leases_released']
    assert owner.snapshot()['active_lease_count']==owner.snapshot()['waiting_request_count']==0


def test_contention_never_reserves_more_than_half_configured_pool():
    class RefuseAcquire:
        config=SimpleNamespace(total_cpu_slots=4,total_child_process_slots=8,total_memory_mb=2048)
        def acquire(self,*args,**kwargs):raise AssertionError('must refuse before reserving')
    result=bench.capacity_contention(RefuseAcquire(),deadline=time.monotonic()+1,cancellation=threading.Event())
    assert result['status']=='skipped_insufficient_capacity'


def test_second_child_failure_releases_first_and_parent(owner,monkeypatch):
    actual=owner.acquire;calls=[]
    def acquire(*args,**kwargs):
        if len(calls)==2:raise RuntimeError('second child setup failed')
        lease=actual(*args,**kwargs);calls.append(lease);return lease
    monkeypatch.setattr(owner,'acquire',acquire)
    result=bench.capacity_contention(owner,deadline=time.monotonic()+2,cancellation=threading.Event())
    assert result['status']=='blocked_admission' and all(lease.released for lease in calls)
    assert owner.snapshot()['active_lease_count']==owner.snapshot()['waiting_request_count']==0


def test_concurrent_observer_registration_restores_every_context():
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import contextmanager
    entered=[];closed=[];lock=threading.Lock()
    @contextmanager
    def context(value):
        with lock:entered.append(value)
        try:yield value
        finally:
            with lock:closed.append(value)
    with bench.LockedExitStack() as stack:
        with ThreadPoolExecutor(max_workers=4) as pool:
            assert sorted(pool.map(lambda value:stack.enter_context(context(value)),range(16)))==list(range(16))
    assert sorted(entered)==sorted(closed)==list(range(16))


def test_observation_iteration_is_detached_from_later_appends():
    rows=bench.ObservationList();rows.append('first')
    snapshot=iter(rows);rows.append('second')
    assert list(snapshot)==['first'] and list(rows)==['first','second']


def test_returned_observation_survives_scope_exit_interruption():
    from contextlib import contextmanager
    @contextmanager
    def stopped_scope():
        yield
        raise TimeoutError('final operation gate')
    # This is a unit-only value, never used in native qualification.
    value=SimpleNamespace(to_dict=lambda:{'unit_observation':True})
    row={}
    with pytest.raises(TimeoutError,match='final operation gate'):
        bench.invoke_recorded(stopped_scope(),lambda:value,row)
    assert row=={'outcome':{'unit_observation':True}}


@pytest.mark.parametrize('name',['admissions','invocations','launches','lifecycles'])
@pytest.mark.parametrize('count',[0,2])
def test_native_case_rejects_missing_or_extra_lifecycle_phase(name,count):
    audit=SimpleNamespace(**{key:[{'case':'owned'}] for key in ('admissions','invocations','launches','lifecycles')})
    setattr(audit,name,[{'case':'owned'}]*count)
    with pytest.raises(AssertionError,match='exactly one'):
        bench.single_case_records(audit,'owned')


def test_native_case_cardinality_ignores_other_concurrent_cases():
    audit=SimpleNamespace(**{key:[{'case':'owned'},{'case':'peer'}] for key in ('admissions','invocations','launches','lifecycles')})
    assert all(row['case']=='owned' for row in bench.single_case_records(audit,'owned').values())
