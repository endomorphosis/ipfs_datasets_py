"""Administrative capacity changes on private native scheduler metadata."""
from copy import deepcopy
import importlib.util
import hashlib
import json
import os
import time
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import existing_resource_scheduler as existing
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as native


@pytest.fixture
def private(tmp_path, monkeypatch):
    path = tmp_path/'native.json'
    scheduler = native.GlobalResourceScheduler(native.ResourceSchedulerConfig(
        state_path=path, total_cpu_slots=4, total_memory_mb=4096,
        total_child_process_slots=4, lane_reservations={'validation':{'cpu_slots':1,'memory_mb':0}},
        proof_safety_enabled=True, proof_memory_headroom_mb=512, auto_renew_leases=False))
    state = json.loads(path.read_bytes())
    state['next_sequence'] = 99
    state['metrics']['acquisitions_total'] = 37
    state['last_proof_refusal'] = {'historical':True, 'reason':'retained-private-history'}
    state['retained_extension'] = {'task_history':['never-reset'], 'opaque_budget':17}
    path.write_text(json.dumps(state, indent=2)+'\n')
    expected = existing.policy_sha256(state['config'])
    real_factory = existing.open_existing_scheduler
    sample = native.ProofHostResources(8, 8192, 8192, pid_task_limit=500, available_pid_tasks=400)
    settings = {'sample':lambda:sample}
    def private_factory(*args):
        facade = real_factory(*args)
        facade.config.auto_renew_leases = False
        return facade
    monkeypatch.setattr(existing, 'open_existing_scheduler', private_factory)
    # Private host observations only; the production helper additionally pins
    # the exact native default sampler and its declaring source.
    monkeypatch.setattr(existing, '_native_capacity_host', lambda config:(settings['sample'](), hashlib.sha256(Path(native.__file__).with_name('proof_resource_safety.py').read_bytes()).hexdigest()))
    return path, expected, state, settings, real_factory


def test_read_only_plan_preserves_all_native_bytes_and_installs_no_facade(private):
    path, expected, state, _, _ = private
    before = path.read_bytes()
    globals_before = dict(native._GLOBAL_SCHEDULERS)
    report = existing.expand_idle_process_capacity(path, expected, 8)
    assert report['status'] == 'ready_explicit_policy_rebind'
    assert not report['applied'] and not report['admitted'] and not report['qualified']
    assert report['next_policy'] == dict(state['config'], total_child_process_slots=8)
    assert report['next_policy_sha256'] == existing.policy_sha256(report['next_policy'])
    assert path.read_bytes() == before
    assert native._GLOBAL_SCHEDULERS == globals_before


def test_expansion_retains_all_history_and_rejects_old_binding(private):
    path, expected, state, _, real_factory = private
    stale = real_factory(path, expected)
    globals_before = dict(native._GLOBAL_SCHEDULERS)
    report = existing.expand_idle_process_capacity(path, expected, 8, apply=True)
    after = json.loads(path.read_bytes())
    assert report['applied'] and report['status'] == 'applied_requires_explicit_policy_rebind'
    assert after == dict(state, config=dict(state['config'], total_child_process_slots=8))
    assert report['preserved_control_sha256'] == existing.policy_sha256({key:value for key,value in after.items() if key!='config'})
    with pytest.raises(existing.ExistingResourceSchedulerError, match='policy changed'):
        stale.active_leases()
    with pytest.raises(existing.ExistingResourceSchedulerError, match='exact stored'):
        real_factory(path, expected)
    fresh = real_factory(path, report['next_policy_sha256'])
    assert fresh.config.persisted_dict() == after['config']
    assert fresh.active_leases() == []
    assert native._GLOBAL_SCHEDULERS == globals_before


@pytest.mark.parametrize('activity', ['leases','waiters','proof_recovery','proof_backoff'])
def test_native_activity_is_retained_and_never_recovered_or_bypassed(private, activity):
    path, expected, state, _, _ = private
    state = deepcopy(state)
    if activity == 'proof_recovery' and 'proof_recovery_enabled' in state['config']:
        state['config']['proof_recovery_enabled'] = True
        expected = existing.policy_sha256(state['config'])
    state[activity] = {'retained': {'owner_pid':os.getpid(), 'lane':'validation',
        'cpu_slots':1, 'memory_mb':64, 'child_process_slots':1}} if activity in {'leases','waiters'} else ({'phase':'settling','healthy_samples':0,'next_sample_at':time.time()+60,
        'next_grant_at':0.0,'grants_remaining':state['config'].get('proof_recovery_grants',4)}
        if activity == 'proof_recovery' else {'until':time.time()+60,'reason':'private-active-backoff'})
    path.write_text(json.dumps(state))
    before = path.read_bytes()
    report = existing.expand_idle_process_capacity(path, expected, 8)
    assert report['status'] == 'held_native_activity' and not report['applied']
    with pytest.raises(existing.ExistingResourceSchedulerError, match='idle scheduler required'):
        existing.expand_idle_process_capacity(path, expected, 8, apply=True)
    assert path.read_bytes() == before


@pytest.mark.parametrize('slots', [True,False,0,-1,4,3,1.5,'8'])
def test_expansion_cannot_lower_capacity_or_accept_untyped_values(private, slots):
    path, expected, _, _, _ = private
    before = path.read_bytes()
    with pytest.raises(existing.ExistingResourceSchedulerError):
        existing.expand_idle_process_capacity(path, expected, slots, apply=True)
    assert path.read_bytes() == before


@pytest.mark.parametrize('mode', ['unknown_pid','pid_shortage','memory_shortage','memory_pressure','cpu_pressure','io_pressure','unknown','invalid_type'])
def test_live_native_telemetry_refuses_unsafe_expansion_without_writes(private, mode):
    path, expected, _, settings, _ = private
    arguments = dict(cpu_slots=8,total_memory_mb=8192,available_memory_mb=8192,
        pid_task_limit=500,available_pid_tasks=400)
    if mode == 'unknown_pid': arguments.update(pid_task_limit=None,available_pid_tasks=None)
    if mode == 'pid_shortage': arguments['available_pid_tasks'] = 0
    if mode == 'memory_shortage': arguments['available_memory_mb'] = 511
    if mode == 'memory_pressure': arguments['memory_stall_percent'] = 2.0
    if mode == 'cpu_pressure': arguments['cpu_stall_percent'] = 50.0
    if mode == 'io_pressure': arguments['io_stall_percent'] = 10.0
    if mode == 'unknown':
        def fail(): raise existing.ExistingResourceSchedulerError('native capacity telemetry unknown')
        settings['sample'] = fail
    elif mode == 'invalid_type': settings['sample'] = lambda:dict(arguments)
    else: settings['sample'] = lambda:native.ProofHostResources(**arguments)
    before = path.read_bytes()
    with pytest.raises(existing.ExistingResourceSchedulerError):
        existing.expand_idle_process_capacity(path, expected, 8, apply=True)
    assert path.read_bytes() == before


def test_outside_lock_state_edit_during_observation_is_refused(private):
    path, expected, state, settings, _ = private
    changed = deepcopy(state)
    changed['retained_extension']['opaque_budget'] = 18
    def outside_writer():
        path.write_text(json.dumps(changed))
        return native.ProofHostResources(8,8192,8192,pid_task_limit=500,available_pid_tasks=400)
    settings['sample'] = outside_writer
    with pytest.raises(existing.ExistingResourceSchedulerError, match='outside lock'):
        existing.expand_idle_process_capacity(path, expected, 8, apply=True)
    assert json.loads(path.read_bytes()) == changed


def test_cli_defaults_to_planning_and_requires_explicit_apply(private, capsys):
    path, expected, _, _, _ = private
    root = Path(existing.__file__).resolve().parents[3]
    script = root/'scripts/ops/legal_ir/plan_span_ingest_capacity.py'
    spec = importlib.util.spec_from_file_location('private_capacity_cli',script)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    before = path.read_bytes()
    arguments = ['--scheduler-state',str(path),'--expected-policy-sha256',expected,'--process-slots','8']
    assert cli.main(arguments) == 0
    assert json.loads(capsys.readouterr().out)['applied'] is False
    assert path.read_bytes() == before
    assert cli.main(arguments+['--apply']) == 0
    assert json.loads(capsys.readouterr().out)['applied'] is True


@pytest.mark.parametrize('apply', ['true',1,None])
def test_apply_flag_requires_actual_boolean(private, apply):
    path, expected, _, _, _ = private
    before = path.read_bytes()
    with pytest.raises(existing.ExistingResourceSchedulerError, match='explicit bool'):
        existing.expand_idle_process_capacity(path, expected, 8, apply=apply)
    assert path.read_bytes() == before


def test_expired_backoff_history_is_preserved_during_expansion(private):
    path, expected, state, _, _ = private
    state = deepcopy(state)
    state['proof_backoff'] = {'until':1.0, 'reason':'retained-expired-pressure'}
    path.write_text(json.dumps(state))
    report = existing.expand_idle_process_capacity(path, expected, 8, apply=True)
    assert report['applied']
    assert json.loads(path.read_bytes())['proof_backoff'] == state['proof_backoff']


@pytest.mark.parametrize('backoff',[[], {'reason':'missing-deadline'}, {'until':True}, {'until':-1}])
def test_malformed_backoff_cannot_authorize_expansion(private, backoff):
    path, expected, state, _, _ = private
    state = deepcopy(state)
    state['proof_backoff'] = backoff
    path.write_text(json.dumps(state))
    before = path.read_bytes()
    with pytest.raises(existing.ExistingResourceSchedulerError, match='backoff'):
        existing.expand_idle_process_capacity(path, expected, 8, apply=True)
    assert path.read_bytes() == before


def test_custom_sampler_cannot_pose_as_selected_native_default(tmp_path):
    config = native.ResourceSchedulerConfig(state_path=tmp_path/'unused.json')
    config.proof_resource_sampler = lambda:native.ProofHostResources(8,8192,8192)
    with pytest.raises(existing.ExistingResourceSchedulerError, match='producer differs'):
        existing._native_capacity_host(config)
    assert not config.state_path.exists()


def test_expansion_enables_real_native_five_process_request_only_after_explicit_rebind(private):
    path, expected, _, settings, real_factory = private
    old = real_factory(path, expected)
    old.config.auto_renew_leases = False
    with pytest.raises((native.ResourceConfigurationError, native.ResourceUnavailableError), match='process.*capacity'):
        old.acquire(native.ResourceLane.HAMMER_LEAN, cpu_slots=2, memory_mb=1792,
                    child_process_slots=5, timeout=0)
    report = existing.expand_idle_process_capacity(path, expected, 8, apply=True)
    assert json.loads(path.read_bytes())['leases'] == {}
    fresh = real_factory(path, report['next_policy_sha256'])
    fresh.config.auto_renew_leases = False
    fresh.config.proof_resource_sampler = settings['sample']
    lease = fresh.acquire(native.ResourceLane.HAMMER_LEAN, cpu_slots=2, memory_mb=1792,
                          child_process_slots=5, timeout=0, request_id='private-worker-floor')
    try:
        assert lease.child_process_slots == 5
        assert len(fresh.active_leases()) == 1
    finally:
        assert lease.release()
    assert fresh.active_leases() == []


def test_atomic_replace_failure_preserves_previous_policy_and_history(private, monkeypatch):
    path, expected, _, _, _ = private
    before = path.read_bytes()
    def failed_replace(*args): raise OSError('private atomic replacement failure')
    monkeypatch.setattr(existing.os,'replace',failed_replace)
    with pytest.raises(OSError, match='atomic replacement failure'):
        existing.expand_idle_process_capacity(path, expected, 8, apply=True)
    assert path.read_bytes() == before
    assert not list(path.parent.glob('.native.json.*.tmp'))
