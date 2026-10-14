#!/usr/bin/env python3
"""Sealed adoption/watchdog AST guards on fake clients and synthetic dictionaries."""
import ast
import copy
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT=Path(__file__).resolve().parent
ADOPTION=ROOT/'adopt_shared_scheduler_actor_ranking_v03.py'
WATCHDOG=ROOT/'owned_lease_watchdog_actor_ranking_v03.py'
PINS={ADOPTION:(18825,'573941d4c9dc69445a74b973e2b7966c66a1aa0b220fc31fc4c6335adc86b93b'),
 WATCHDOG:(27360,'af2847920a5bb184f0e9801e7eabe1eea68029085fc1f1730d8cd682a662ff4b')}
TREES={}
for path,expected in PINS.items():
 raw=path.read_bytes();assert (len(raw),hashlib.sha256(raw).hexdigest())==expected
 TREES[path]=ast.parse(raw)

def detached(tree,names,namespace,constants=()):
 nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
 assert {n.name for n in nodes}==set(names)
 assert not any(isinstance(n,(ast.Import,ast.ImportFrom)) for f in nodes for n in ast.walk(f))
 assignments=[n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in constants for t in n.targets)]
 exec(compile(ast.Module(body=assignments+nodes,type_ignores=[]),'detached-bridge-guards','exec'),namespace)
 return namespace

N=detached(TREES[ADOPTION],{'require','raw','digest','validated_config','exact_existing_client',
 '_validate_recovery_state','_validate_historical_proof_refusal'},
 dict(deepcopy=copy.deepcopy,hashlib=hashlib,json=json,math=math,Path=Path),
 ('INTEGER_KEYS','OPTIONAL_INTEGER_KEYS','PERCENT_KEYS','OPTIONAL_PERCENT_KEYS','BOOLEAN_KEYS','PERSISTED_KEYS',
 'STATE_REQUIRED_KEYS','STATE_OPTIONAL_KEYS','EXPECTED_CONFIG','EXPECTED_CONFIG_SHA256','STATE_PATH'))
class WatchError(RuntimeError):
 def __init__(self,code,observation=None):self.code=code;self.observation=observation

W=detached(TREES[WATCHDOG],{'_raw','_digest','_require','_finite','_validate_recovery_state',
 '_validate_historical_proof_refusal','owned_subtree_row_count'},
 dict(deepcopy=copy.deepcopy,hashlib=hashlib,json=json,math=math,LeaseWatchdogError=WatchError),
 ('SCHEMA','SCHEDULER_SCHEMA','STATE_KEYS','OWN_FIELDS'))
observe=next(n for n in TREES[WATCHDOG].body if isinstance(n,ast.FunctionDef) and n.name=='observe_lease')
block=next(n for n in observe.body if isinstance(n,ast.Try)).body
start=next(i for i,n in enumerate(block) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
 and any(isinstance(c,ast.Constant) and c.value=='scheduler_schema_changed' for c in ast.walk(n)))
body=block[start:]
assert isinstance(body[-1],ast.Return)
assert not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)
 and isinstance(n.func.value,ast.Name) and n.func.value.id in {'os','fcntl'} for b in body for n in ast.walk(b))
function=ast.FunctionDef(name='postread_observation',args=ast.arguments(posonlyargs=[],
 args=[ast.arg(arg=k) for k in ('state','binding','expected','event','started')],kwonlyargs=[],kw_defaults=[],defaults=[]),
 body=body,decorator_list=[])
W.update(time=SimpleNamespace(time=lambda:100.,monotonic=lambda:1.),hmac=hmac)
exec(compile(ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[])),
 'watchdog-exact-postread-guards-no-I-O','exec'),W)

class Config:
 def __init__(self,**kwargs):self.state_path=kwargs.pop('state_path');self.value=copy.deepcopy(kwargs);self.validated=False
 def validate(self):self.validated=True
 def persisted_dict(self):return copy.deepcopy(self.value)

class Parent:
 state=None;allow_permissions=[];new_calls=0
 def __init__(self,config):
  self.config=config
  self._validate_state_configuration(self.state,allow_reconfigure=True)
 def _validate_state_configuration(self,state,*,allow_reconfigure=False):
  Parent.allow_permissions.append(allow_reconfigure)
  if allow_reconfigure:raise AssertionError('unexpected reset permission')
  return 'parent-validation'
 def _new_state(self):Parent.new_calls+=1;raise AssertionError('parent initializer called')

LANES=(SimpleNamespace(value='validation'),SimpleNamespace(value='trainer'))
SCHEDULER=SimpleNamespace(RESOURCE_SCHEDULER_SCHEMA_VERSION='legal-ir-global-resource-scheduler-v1',
 ResourceSchedulerConfig=Config,ResourceLane=LANES,GlobalResourceScheduler=Parent,ResourceConfigurationError=ValueError)

def state():
 return dict(schema_version=SCHEDULER.RESOURCE_SCHEDULER_SCHEMA_VERSION,config=copy.deepcopy(N['EXPECTED_CONFIG']),
  leases={'foreign':dict(parent_lease_id=None,opaque='unchanged')},waiters={'foreign-waiter':dict(opaque='unchanged')},
  metrics=dict(counter=7),next_sequence=18,proof_backoff={})

def refusal():
 return dict(schema='proof-resource-admission-refusal@1',historical=True,decision_cycle_at=1.,gate='envelope',
  reason='proof_pid_headroom',waiter_id='known',sequence=2,request_id='request',lane='trainer',parent_lease_id=None,
  sample=dict(cpu_slots=16,total_memory_mb=99688,available_memory_mb=80000,memory_stall_percent=0.,cpu_stall_percent=0.,
   io_stall_percent=0.,pid_task_limit=100,available_pid_tasks=47),
  sample_contract='max-host-visible-cgroup-avg10; memory/full,cpu/some,io/full; optional-psi-zero-fallback',
  thresholds=dict(memory_stall_percent=2.,cpu_stall_percent=50.,io_stall_percent=10.),proof_memory_headroom_mb=24922,
  demand=dict(root_reserved_memory_mb=0,additional_memory_mb=1536,root_reserved_process_slots=0,additional_process_slots=1,pid_tasks_required=48),
  backoff_until=3.,error_type=None)

def binding():
 return SimpleNamespace(config=copy.deepcopy(N['EXPECTED_CONFIG']),lease_id='own-root',
  lease_key='synthetic-capability',own_fields=dict(lease_id='own-root',owner_pid=123,acquired_at=10.))

def observe_state(value,expected='absent'):
 b=binding();event=dict(expected_config_sha256=W['_digest'](b.config))
 return W['postread_observation'](value,b,expected,event,0.)

class Controls(unittest.TestCase):
 def setUp(self):Parent.allow_permissions=[];Parent.new_calls=0;Parent.state=state()
 def test_exact24_config_roundtrip_without_dropping_or_mutating_fields(self):
  value=state();before=copy.deepcopy(value);config=N['validated_config'](SCHEDULER,value,N['STATE_PATH'])
  self.assertTrue(config.validated);self.assertEqual(config.persisted_dict(),before['config']);self.assertEqual(value,before)
  self.assertEqual(len(config.persisted_dict()),24)
 def test_config_missing_unknown_wrong_types_values_lanes_and_paths_refuse(self):
  for mutate in (lambda c:c.pop('proof_recovery_enabled'),lambda c:c.update(unknown=0),
   lambda c:c.update(total_cpu_slots=True),lambda c:c.update(total_cpu_slots=16.),
   lambda c:c.update(proof_memory_headroom_mb=2458),lambda c:c['lane_reservations']['validation'].update(cpu_slots=1)):
   value=state();mutate(value['config'])
   with self.assertRaises(ValueError):N['validated_config'](SCHEDULER,value,N['STATE_PATH'])
  with self.assertRaises(ValueError):N['validated_config'](SCHEDULER,state(),Path('/synthetic/other.json'))
 def test_constructor_forces_native_permission_false_and_preserves_foreign_state(self):
  before=copy.deepcopy(Parent.state);config=Config(**copy.deepcopy(N['EXPECTED_CONFIG']),state_path=N['STATE_PATH'])
  client=N['exact_existing_client'](SCHEDULER,config)
  self.assertEqual(Parent.allow_permissions,[False]);self.assertEqual(Parent.state,before)
  self.assertEqual(client._validate_state_configuration(Parent.state,allow_reconfigure=True),'parent-validation')
  self.assertEqual(Parent.allow_permissions,[False,False])
  with self.assertRaises(ValueError):client._new_state()
  self.assertEqual(Parent.new_calls,0)
 def test_every_locked_validation_rejects_mutated_config_and_unknown_state(self):
  config=Config(**copy.deepcopy(N['EXPECTED_CONFIG']),state_path=N['STATE_PATH'])
  client=N['exact_existing_client'](SCHEDULER,config)
  for mutate in (lambda s:s['config'].update(total_cpu_slots=4),lambda s:s.update(unknown={}),
   lambda s:s.update(next_sequence=True),lambda s:s.update(leases=[]),lambda s:s.update(proof_recovery={'phase':'paced'})):
   bad=state();mutate(bad)
   with self.assertRaises(ValueError):client._validate_state_configuration(bad,allow_reconfigure=True)
  self.assertEqual(Parent.allow_permissions,[False])
 def test_both_metadata_guards_preserve_valid_PID_refusal_and_reject_mutations(self):
  for ns in (N,W):
   value=refusal();before=copy.deepcopy(value);ns['_validate_historical_proof_refusal'](value);self.assertEqual(value,before)
   for mutate in (lambda v:v.update(unknown=0),lambda v:v.update(sequence=True),
    lambda v:v['sample'].update(available_pid_tasks=None),lambda v:v['sample'].update(available_pid_tasks=101),
    lambda v:v['demand'].update(pid_tasks_required=True),lambda v:v['thresholds'].update(cpu_stall_percent=float('inf'))):
    value=refusal();mutate(value)
    with self.assertRaises(ValueError):ns['_validate_historical_proof_refusal'](value)
 def test_closed_recovery_is_identical_in_adoption_and_watchdog(self):
  for phase,healthy,grants in [('settling',0,4),('paced',2,3)]:
   cfg=copy.deepcopy(N['EXPECTED_CONFIG']);cfg['proof_recovery_enabled']=True
   recovery=dict(phase=phase,healthy_samples=healthy,next_sample_at=3.,next_grant_at=0.,grants_remaining=grants)
   for ns in (N,W):
    ns['_validate_recovery_state'](dict(proof_recovery=recovery),cfg)
    for key,value in [('unknown',0),('healthy_samples',True),('grants_remaining',5),('next_grant_at',float('nan'))]:
     bad=dict(recovery);bad[key]=value
     with self.assertRaises(ValueError):ns['_validate_recovery_state'](dict(proof_recovery=bad),cfg)
  self.assertEqual(ast.dump(next(n for n in TREES[ADOPTION].body if isinstance(n,ast.FunctionDef) and n.name=='_validate_recovery_state'),include_attributes=False),
   ast.dump(next(n for n in TREES[WATCHDOG].body if isinstance(n,ast.FunctionDef) and n.name=='_validate_recovery_state'),include_attributes=False))
 def test_empty_own_subtree_with_foreign_records_is_valid_closeout(self):
  value=state();before=copy.deepcopy(value);event=observe_state(value)
  self.assertTrue(event['release_complete']);self.assertEqual(event['owned_subtree_remaining_row_count'],0)
  self.assertTrue(event['native_release_acknowledgement_is_not_absence']);self.assertEqual(value,before)
 def test_absent_root_with_direct_or_transitive_descendant_refuses(self):
  for leases in ({'child':dict(parent_lease_id='own-root')},
    {'child':dict(parent_lease_id='own-root'),'grandchild':dict(parent_lease_id='child')},
    {'own-root':dict(parent_lease_id=None)}):
   value=state();value['leases'].update(leases)
   with self.assertRaises(WatchError) as ctx:observe_state(value)
   self.assertEqual(ctx.exception.code,'owned_lease_release_deferred_or_descendants_present')
 def test_parent_graph_types_and_cycles_are_bounded(self):
  self.assertEqual(W['owned_subtree_row_count']({'a':dict(parent_lease_id='b'),'b':dict(parent_lease_id='a')},'a'),2)
  for leases in ({'a':None},{'a':dict(parent_lease_id=True)}):
   with self.assertRaises(WatchError):W['owned_subtree_row_count'](leases,'a')
 def test_present_own_identity_authority_cancel_expiry_release_requests_fail_closed(self):
  value=state();value['leases']['own-root']=dict(binding().own_fields,lease_key=binding().lease_key,heartbeat_at=90.,expires_at=110.,cancelled=False)
  self.assertTrue(observe_state(value,'present')['healthy'])
  for mutate in (lambda r:r.update(owner_pid=True),lambda r:r.update(lease_key='wrong'),
   lambda r:r.update(cancelled=True),lambda r:r.update(expires_at=99.),lambda r:r.update(release_requested=True),
   lambda r:r.update(release_requested=0),lambda r:r.update(heartbeat_at=float('inf'))):
   bad=copy.deepcopy(value);mutate(bad['leases']['own-root'])
   with self.assertRaises(WatchError):observe_state(bad,'present')
 def test_watchdog_config_and_current_metadata_refuse_without_leaking_records(self):
  for mutate in (lambda s:s['config'].update(total_cpu_slots=4),lambda s:s.update(unknown={}),
   lambda s:s.update(proof_recovery={'phase':'paced'}),lambda s:s.update(last_proof_refusal={'unknown':1})):
   bad=state();mutate(bad)
   with self.assertRaises(WatchError):observe_state(bad)
 def test_scope_no_imported_scheduler_and_no_global_cache_or_defaults_call(self):
  adoption=TREES[ADOPTION]
  names={n.func.attr for n in ast.walk(adoption) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
  self.assertNotIn('default_resource_scheduler_config',names)
  for n in ast.walk(adoption):
   if isinstance(n,ast.Assign):
    for target in n.targets:
     if isinstance(target,ast.Attribute) and target.attr=='get_global_resource_scheduler':
      self.assertEqual(ast.unparse(target.value),'resources')

if __name__=='__main__':
 result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(Controls))
 value=dict(schema='actor-context-ranking-current-bridge-independent-detached-controls/v1',passed=result.wasSuccessful(),
  tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),
  scope='AST guards and actual watchdog postread branch only; fake parent/config/state, no I/O',
  artifacts={str(p):dict(bytes=n,sha256=h) for p,(n,h) in PINS.items()},resource_module_imports=0,live_proc_reads=0,
  private_body_reads=0,file_or_lock_resource_IO=0,resource_API_calls=0,model_calls=0,network_calls=0)
 raw=(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()
 path=ROOT/'current-bridge-independent-detached-controls-v01.json';fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o444)
 with os.fdopen(fd,'wb') as stream:stream.write(raw)
 print(json.dumps(dict(path=str(path),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())))
 raise SystemExit(0 if result.wasSuccessful() else 1)
