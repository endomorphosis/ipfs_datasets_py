#!/usr/bin/env python3
"""Actual scheduler definitions on synthetic state, without module imports/probes."""
import ast
import copy
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
import uuid

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/resource_scheduler.py'
EXPECTED = (111009, '75fc31a79031ba941fb81570419e0c630c67363d77aafc97979a156cd02248a4')
OUTPUT = ROOT / 'current-scheduler-independent-detached-controls-v02.json'
raw = SOURCE.read_bytes()
assert (len(raw), hashlib.sha256(raw).hexdigest()) == EXPECTED
tree = ast.parse(raw)
methods = {
    '_descendants', '_prune_released_locked', '_recover_stale_locked', '_root_usage',
    '_can_grant', '_validate_recovery_state', '_record_pressure', '_recovery_ready',
    '_observe_recovery', '_consume_recovery_grant', 'release', 'renew', 'is_cancelled',
    '_validate_state_configuration',
}
native = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'GlobalResourceScheduler')
nodes = [n for n in native.body if isinstance(n, ast.FunctionDef) and n.name in methods]
assert {n.name for n in nodes} == methods and not any(
    isinstance(n, (ast.Import, ast.ImportFrom)) for f in nodes for n in ast.walk(f))
global_names = {'_normalise_boot_id', '_owner_alive_once'}
globals_nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in global_names]
config = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ResourceSchedulerConfig')
config_nodes = [n for n in config.body if isinstance(n, ast.FunctionDef) and n.name in {'validate', 'persisted_dict'}]

def fake_alive(pid, marker):
    owner_calls.append((pid, marker))
    return owner_liveness.get(pid, True)

owner_calls = []
owner_liveness = {}
clock = SimpleNamespace(time=lambda: 100.)
namespace = dict(math=math, uuid=uuid, time=clock, deepcopy=copy.deepcopy,
    RESOURCE_SCHEDULER_SCHEMA_VERSION='legal-ir-global-resource-scheduler-v1',
    LOCAL_BENCHMARK_PROOF_PROFILE='local-benchmark@1', PROOF_PID_HEADROOM_TASKS=32,
    PROOF_PID_TASKS_PER_PROCESS=16, ProofPressureSources=type('NoSources', (), {}),
    ResourceLane=SimpleNamespace(VALIDATION=SimpleNamespace(value='validation')),
    SchedulerStateError=ValueError, ResourceConfigurationError=ValueError,
    LeaseNotFoundError=ValueError, _owner_is_alive=fake_alive,
    _owner_boot_id=lambda: '12345678-1234-1234-1234-123456789abc')
module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0),
    *globals_nodes,
    ast.ClassDef(name='SelectedScheduler', bases=[], keywords=[], body=nodes, decorator_list=[]),
    ast.ClassDef(name='SelectedConfig', bases=[], keywords=[], body=config_nodes, decorator_list=[])], type_ignores=[])
exec(compile(ast.fix_missing_locations(module), str(SOURCE)+'#synthetic-only', 'exec'), namespace)
Selected = namespace['SelectedScheduler']
SelectedConfig = namespace['SelectedConfig']

class FakeScheduler(Selected):
    def __init__(self):
        self.host = SimpleNamespace(available_memory_mb=100000, available_pid_tasks=1000,
            memory_stall_percent=0., cpu_stall_percent=0., io_stall_percent=0.)
        self.samples = 0
        self.state_path = '/synthetic/never-opened-scheduler.json'
        def sampler():
            self.samples += 1
            if isinstance(self.host, Exception): raise self.host
            return self.host
        self.config = SimpleNamespace(proof_safety_enabled=True, proof_recovery_enabled=False,
            proof_memory_headroom_mb=1000, proof_memory_stall_percent=2.,
            proof_cpu_stall_percent=50., proof_io_stall_percent=10.,
            proof_backoff_seconds=2., proof_recovery_samples=2,
            proof_recovery_interval_seconds=.25, proof_recovery_grants=4,
            proof_resource_sampler=sampler)
        self.state = dict(leases={}, waiters={}, metrics=dict(recoveries_total=0,
            recovered_leases_total=0, cancellations_total=0, releases_total=0))
        self.refusals = []
    @contextmanager
    def _locked_state(self, **kwargs): yield self.state
    def _record_proof_refusal(self, state, waiter, **kwargs): self.refusals.append(kwargs)
    def _pressure_allows(self, waiter, **kwargs): return True, ''
    def _root_can_grant(self, state, waiter, **kwargs): return True
    def _child_can_grant(self, state, waiter): return True

def waiter(parent=None, slots=1, memory=1536):
    return dict(parent_lease_id=parent, child_process_slots=slots, memory_mb=memory, lane='training')

def lease(name, parent=None, pid=1, expires=200., slots=1):
    return dict(lease_id=name, lease_key='authority-'+name, parent_lease_id=parent,
        owner_pid=pid, owner_birth_marker='birth', expires_at=expires, lane='training',
        cpu_slots=2, memory_mb=1536, child_process_slots=slots, cancelled=False)

def fake_config():
    c = SelectedConfig()
    values = dict(total_cpu_slots=16, total_memory_mb=99688, total_gpu_memory_mb=None,
        total_unified_memory_mb=None, total_child_process_slots=16, reserved_memory_mb=0,
        reserved_gpu_memory_mb=0, max_memory_percent=None, max_swap_percent=None,
        max_gpu_memory_percent=None, require_known_gpu_for_gpu_work=True,
        max_waiting_requests=256, proof_safety_enabled=True, proof_resource_profile=None,
        proof_memory_headroom_mb=24922, proof_memory_stall_percent=2.,
        proof_cpu_stall_percent=50., proof_io_stall_percent=10., proof_backoff_seconds=2.,
        proof_recovery_enabled=False, proof_recovery_samples=2,
        proof_recovery_interval_seconds=.25, proof_recovery_grants=4,
        lease_ttl_seconds=30., poll_interval_seconds=.05)
    c.__dict__.update(values)
    reservation = SimpleNamespace(cpu_slots=2, memory_mb=0,
        to_dict=lambda: dict(cpu_slots=2, memory_mb=0))
    c.reservations = lambda: dict(validation=reservation)
    return c

class Controls(unittest.TestCase):
    def setUp(self): owner_liveness.clear(); owner_calls.clear()
    def test_PID_boundary_with_recovery_disabled(self):
        s=FakeScheduler();s.host.available_pid_tasks=47
        self.assertFalse(s._can_grant(s.state,waiter()))
        self.assertEqual(s.refusals[-1]['reason'],'proof_pid_headroom')
        self.assertEqual(s.refusals[-1]['demand']['pid_tasks_required'],48)
        s=FakeScheduler();s.host.available_pid_tasks=48
        self.assertTrue(s._can_grant(s.state,waiter()))
    def test_reserved_root_slots_count_once_children_do_not_add_again(self):
        for parent,limit in [(None,80),('root',64)]:
            s=FakeScheduler();s.state['leases']['root']=lease('root',slots=2)
            s.state['leases']['child']=lease('child','root',slots=1)
            s.host.available_pid_tasks=limit-1
            self.assertFalse(s._can_grant(s.state,waiter(parent)))
            self.assertEqual(s.refusals[-1]['demand']['pid_tasks_required'],limit)
    def test_unknown_PID_is_not_fabricated(self):
        s=FakeScheduler();s.host.available_pid_tasks=None
        self.assertTrue(s._can_grant(s.state,waiter()))
        s=FakeScheduler();s.host.available_pid_tasks=0
        self.assertFalse(s._can_grant(s.state,waiter()))
    def test_memory_pressure_and_telemetry_exceptions_remain_native_refusals(self):
        for field,value,reason in [('available_memory_mb',2535,'proof_memory_headroom'),
            ('memory_stall_percent',2.,'proof_memory_stall'),
            ('cpu_stall_percent',50.,'proof_cpu_stall'),('io_stall_percent',10.,'proof_io_stall')]:
            s=FakeScheduler();setattr(s.host,field,value)
            self.assertFalse(s._can_grant(s.state,waiter()));self.assertEqual(s.refusals[-1]['reason'],reason)
        s=FakeScheduler();s.host=ValueError('synthetic finite control failure')
        self.assertFalse(s._can_grant(s.state,waiter()))
        self.assertEqual(s.refusals[-1]['reason'],'proof_resource_telemetry_unknown')
    def test_extra_root_memory_refusal_does_not_block_existing_drain(self):
        s=FakeScheduler();s.state['leases']['root']=lease('root');s.host.available_memory_mb=3000
        self.assertFalse(s._can_grant(s.state,waiter()))
        self.assertEqual(s.state['proof_backoff'],{})
        self.assertTrue(s._can_grant(s.state,waiter('root')))
    def test_release_acknowledgement_keeps_live_descendant_and_capacity(self):
        s=FakeScheduler();s.state['leases']={n:lease(n,p) for n,p in [('root',None),('child','root')]}
        self.assertTrue(s.release('root','authority-root'))
        self.assertEqual(set(s.state['leases']),{'root','child'})
        self.assertTrue(all(v['cancelled'] for v in s.state['leases'].values()))
        self.assertEqual(s._root_usage(s.state)[:2],(2,1536))
        self.assertFalse(s.renew('root','authority-root'))
        self.assertTrue(s.is_cancelled('child'))
        self.assertTrue(s.release('child','authority-child'))
        self.assertEqual(s.state['leases'],{})
        self.assertFalse(s.release('root','authority-root'))
    def test_expired_live_owner_remains_charged_until_explicit_release(self):
        s=FakeScheduler();s.state['leases']['root']=lease('root',expires=99.)
        self.assertEqual(s._recover_stale_locked(s.state,100.),[])
        self.assertTrue(s.state['leases']['root']['cancelled'])
        self.assertNotIn('release_requested',s.state['leases']['root'])
        self.assertEqual(s._root_usage(s.state)[1],1536)
    def test_dead_parent_cannot_reclaim_live_child(self):
        s=FakeScheduler();owner_liveness[1]=False;owner_liveness[2]=True
        s.state['leases']={'root':lease('root',pid=1),'child':lease('child','root',pid=2)}
        self.assertEqual(s._recover_stale_locked(s.state,100.),[])
        self.assertEqual(set(s.state['leases']),{'root','child'})
        owner_liveness[2]=False
        self.assertEqual(s._recover_stale_locked(s.state,100.),['child','root'])
    def test_boot_identity_and_per_operation_owner_cache(self):
        fn=namespace['_owner_alive_once'];boot='12345678-1234-1234-1234-123456789abc'
        row=dict(owner_pid=1,owner_birth_marker='birth',owner_boot_id=boot);cache={}
        self.assertTrue(fn(row,cache,current_boot=boot));self.assertTrue(fn(row,cache,current_boot=boot))
        self.assertEqual(owner_calls,[(1,'birth')])
        other='12345678-1234-1234-1234-123456789abd'
        self.assertFalse(fn(row,{},current_boot=other));self.assertEqual(len(owner_calls),1)
        row['owner_boot_id']='unknown';self.assertTrue(fn(row,{},current_boot=other))
    def test_parent_expiry_cancels_polling_child_without_write(self):
        s=FakeScheduler();s.state['leases']={'root':lease('root',expires=99.),'child':lease('child','root')}
        before=copy.deepcopy(s.state);self.assertTrue(s.is_cancelled('child'))
        self.assertEqual(s.state,before)
    def test_full24_native_config_roundtrip_and_new_field_types(self):
        c=fake_config();c.validate();self.assertEqual(len(c.persisted_dict()),24)
        for key,value in [('proof_recovery_enabled',1),('proof_recovery_samples',True),
            ('proof_recovery_grants',0),('proof_recovery_interval_seconds',float('inf')),
            ('proof_recovery_interval_seconds',True),('proof_resource_profile','unknown')]:
            c=fake_config();setattr(c,key,value)
            with self.assertRaises(ValueError):c.validate()
    def test_native_recovery_state_is_closed_and_typed(self):
        s=FakeScheduler();s.config.proof_recovery_enabled=True
        valid=dict(phase='settling',healthy_samples=0,next_sample_at=2.,next_grant_at=0.,grants_remaining=4)
        s._validate_recovery_state(dict(proof_recovery=valid))
        for key,value in [('unknown',1),('healthy_samples',True),('phase','unknown'),
            ('next_sample_at',float('nan')),('grants_remaining',5),('next_grant_at',1.)]:
            bad=dict(valid);bad[key]=value
            with self.assertRaises(ValueError):s._validate_recovery_state(dict(proof_recovery=bad))
        s.config.proof_recovery_enabled=False
        with self.assertRaises(ValueError):s._validate_recovery_state(dict(proof_recovery=valid))
    def test_configuration_reconfigure_false_cannot_reset_mismatch(self):
        s=FakeScheduler();s.config=fake_config();expected=s.config.persisted_dict()
        state=dict(schema_version=namespace['RESOURCE_SCHEDULER_SCHEMA_VERSION'],config=dict(expected))
        s._validate_state_configuration(state,allow_reconfigure=False)
        state['config']['total_cpu_slots']=4;before=copy.deepcopy(state)
        with self.assertRaises(ValueError):s._validate_state_configuration(state,allow_reconfigure=False)
        self.assertEqual(state,before)
        # Native upgrade defaults are deliberately permissive; bridge must first
        # require exact authenticated24 fields, not rely on this native branch.
        state['config']=dict(expected);del state['config']['proof_recovery_enabled']
        s._validate_state_configuration(state,allow_reconfigure=False)
        self.assertEqual(state['config'],expected)

if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(Controls))
    receipt=dict(schema='actor-context-ranking-current-scheduler-independent-detached-controls/v1',
        passed=result.wasSuccessful(),tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),
        source=dict(path=str(SOURCE),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()),
        scope='AST-extracted actual methods on synthetic state/telemetry; no complete module or resource calls',
        proof_or_scheduler_imports=0,live_proc_reads=0,private_body_reads=0,resource_API_calls=0,
        live_sampler_calls=0,model_calls=0,network_calls=0,bridge_qualified=False)
    encoded=(json.dumps(receipt,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()
    fd=os.open(OUTPUT,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o444)
    with os.fdopen(fd,'wb') as stream:stream.write(encoded)
    print(json.dumps(dict(path=str(OUTPUT),bytes=len(encoded),sha256=hashlib.sha256(encoded).hexdigest())))
    raise SystemExit(0 if result.wasSuccessful() else 1)
