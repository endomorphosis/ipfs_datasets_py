"""Independent detached public-policy/synthetic predicates; no collector/observer main."""
import ast
from collections import Counter
import copy
import hashlib
import json
import os
from pathlib import Path

F=Path(__file__).resolve().parent
PROTOCOL=F/'actor_context_ranking_resource_protocol_v03.py'
COLLECTOR=F/'collect_actor_context_ranking_opening_v03.py'
OBSERVER=F/'review_actor_context_ranking_resource_baseline_v03.py'
POLICY=F/'resource-observation-policy-v02.json'
def pin(path):
 path=Path(path);raw=path.read_bytes();return dict(path=str(path),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
pins=[(PROTOCOL,21090,'5df6178fc35cf2a521501af6ff87b0f629bda92c37226f4534e4946759073c68'),
 (COLLECTOR,9710,'dcd2ad3af6227acc7fa2a88fcc086d0367a6cf36e270e60d6bc82e9a99259e66'),
 (OBSERVER,7875,'21c20974cf9f5f55331f63ebe3e26d7e5a5a249e976b858f2d4c88fa051a9549'),
 (POLICY,8590,'9d8ea86843bba3d6d9a22717d2be330ff549a38f5c43466912fa90dc8852c996')]
for p,n,h in pins:assert (pin(p)['bytes'],pin(p)['sha256'])==(n,h)
tree=ast.parse(PROTOCOL.read_bytes())
names={'full_descriptor','qualify_policy','qualify_ledger','qualify_check','capacity','qualify_baseline'}
nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
assert {n.name for n in nodes}==names
constants={'F','LEDGER','SCHEDULER','POLICY','POLICY_PIN','POLICY_CANONICAL_SHA256','COUNTED_ROOT_METADATA','KERNEL_PIN','NAMESPACE_BOOTSTRAP_PIN'}
assignments=[n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in constants for t in n.targets)]
def require(ok,message):
 if not ok:raise ValueError(message)
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
ns=dict(__file__=str(PROTOCOL),Path=Path,require=require,digest=digest,Counter=Counter)
exec(compile(ast.Module(body=assignments+nodes,type_ignores=[]),'detached-current-resource-predicates','exec'),ns)
policy=json.loads(POLICY.read_bytes());cases=[]
def check(name,fn,reject=False):
 try:fn()
 except (ValueError,KeyError,TypeError):
  if not reject:raise
 else:
  if reject:raise AssertionError('Synthetic refusal accepted: '+name)
 cases.append(dict(name=name,passed=True,expected_refusal=reject))
check('exact canonical current policy',lambda:ns['qualify_policy'](policy))
for key,value in [('global_cap_bytes',145000000001),('future_own_output_bound_bytes',0),('historical_record_count',539),('current_record_count_assumed',True)]:
 bad=copy.deepcopy(policy);bad[key]=value
 check('policy mutation '+key,lambda bad=bad:ns['qualify_policy'](bad),True)
state=dict(schema_version='legal-ir-global-resource-scheduler-v1',config=copy.deepcopy(policy['scheduler_config']),leases={'foreign':{}},waiters={'foreign-waiter':{}})
receipt={n:dict(bytes=123,sha256=h*64) for n,h in [('ledger','a'),('scheduler','b')]}
status=dict(full_nonreleased_claim_bytes=37)
checked=dict(schema='scope-pilot-resource-compatibility/v1',passed=True,findings=[],resources=policy['resources'],disk_limit_bytes=145000000000,
 outstanding_full_reservations_bytes=37,shared_config=state['config'],lease_count=1,waiter_count=1,
 model_started=False,reservation_acquired=False,scheduler_client_constructed=False,shared_state_modified=False,admission_guaranteed=False,
 disk_ledger=receipt['ledger'],shared_state=receipt['scheduler'],
 producers={p:dict(path=p,**v) for p,v in policy['resource_producer_pins'].items()},namespace_bootstrap_source=policy['namespace_bootstrap_source'])
check('nonidle current config and all eleven exact sources pass',lambda:require(ns['qualify_check'](policy,checked,receipt,state,status)['lease_count']==1,'occupancy'))
for mutate in [lambda v:v.pop('namespace_bootstrap_source'),lambda v:v['namespace_bootstrap_source'].update(sha256='0'*64),
 lambda v:v.update(lease_count=0),lambda v:v['producers'][next(iter(v['producers']))].update(sha256='0'*64),lambda v:v.update(outstanding_full_reservations_bytes=0)]:
 bad=copy.deepcopy(checked);mutate(bad)
 check('check source/occupancy/charge mutation '+str(len(cases)),lambda bad=bad:ns['qualify_check'](policy,bad,receipt,state,status),True)
bad=copy.deepcopy(receipt);bad['scheduler']['sha256']='0'*64
check('matching ledger cannot hide scheduler race',lambda:ns['qualify_check'](policy,checked,bad,state,status),True)
small=copy.deepcopy(policy);small['required_preserved_claims']=[]
body=dict(reservation_id='historical',status='retained',storage_bytes=19);history={'historical':digest(body)}
ledger=dict(schema='daemon-resource-reservations-v1',roots=policy['counted_root_metadata'],limit_bytes=145000000000,
 reservations={'historical':body,'active':dict(reservation_id='active',status='active',storage_bytes=23),
 'reserved':dict(reservation_id='reserved',status='reserved',storage_bytes=29),'released':dict(reservation_id='released',status='released',storage_bytes=31)})
check('every current full active retained reserved charge included',lambda:require(ns['qualify_ledger'](small,ledger,history)['full_nonreleased_claim_bytes']==71,'fullcharge'))
for mutate in [lambda v:v['reservations']['historical'].update(status='released'),lambda v:v['reservations'].pop('historical'),
 lambda v:v['reservations']['active'].update(storage_bytes=True),lambda v:v['reservations']['active'].update(storage_bytes=23.),
 lambda v:v['reservations']['active'].update(status='unknown')]:
 bad=copy.deepcopy(ledger);mutate(bad)
 check('ledger conservation/typed claim mutation '+str(len(cases)),lambda bad=bad:ns['qualify_ledger'](small,bad,history),True)
for observed,claims,free,expected in [(144600000000,0,400000000,True),(144600000001,0,400000000,False),(0,71,400000070,False)]:
 check('full capacity exact boundary '+str((observed,claims,free)),lambda o=observed,c=claims,f=free,e=expected:require(ns['capacity'](policy,o,c,f)['full_run_capacity_fits'] is e,'boundary'))
check('boolean capacity count refused',lambda:ns['capacity'](policy,True,0,10**12),True)
# Isolate the actual new admission statement; this is not a fabricated baseline.
baseline=next(n for n in nodes if n.name=='qualify_baseline')
guard=next(n for n in baseline.body if isinstance(n,ast.Expr) and any(isinstance(c,ast.Constant) and c.value=='All eleven actual resource sources including the namespace bootstrap must be admitted' for c in ast.walk(n)))
admission=ast.FunctionDef(name='bootstrap_admission',args=ast.arguments(posonlyargs=[],args=[ast.arg(arg='baseline')],kwonlyargs=[],kw_defaults=[],defaults=[]),body=[guard],decorator_list=[])
exec(compile(ast.fix_missing_locations(ast.Module(body=[admission],type_ignores=[])),'exact-bootstrap-admission-guard','exec'),ns)
fixture=dict(namespace_bootstrap_source=policy['namespace_bootstrap_source'],artifacts={policy['namespace_bootstrap_source']['path']:policy['namespace_bootstrap_source']})
check('eleventh source explicitly admitted',lambda:ns['bootstrap_admission'](fixture))
for mutate in [lambda b:b['artifacts'].clear(),lambda b:b['namespace_bootstrap_source'].update(sha256='0'*64)]:
 bad=copy.deepcopy(fixture);mutate(bad)
 check('eleventh admission mutation '+str(len(cases)),lambda bad=bad:ns['bootstrap_admission'](bad),True)
# Exact source derivation evidence; observer pins the eleventh source before private parsing.
main=next(n for n in ast.parse(OBSERVER.read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='main')
rendered=[ast.unparse(n) for n in main.body]
check('observer pins namespace before snapshot',lambda:require(next(i for i,s in enumerate(rendered) if 'm.pin(namespace_pin' in s)<next(i for i,s in enumerate(rendered) if 'p.snapshot(' in s),'pin ordering'))
loop=next(n for n in ast.walk(next(n for n in ast.parse(COLLECTOR.read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='main')) if isinstance(n,ast.For) and isinstance(n.target,ast.Name) and n.target.id=='index')
check('fixed exclusive pair indices3,4,5',lambda:require(ast.literal_eval(loop.iter)==(3,4,5),'indices'))
endpoint=next(n for n in ast.parse(COLLECTOR.read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='endpoint_matches')
ens=dict(s=type('PureRequire',(),{'require':staticmethod(require)}))
exec(compile(ast.Module(body=[endpoint],type_ignores=[]),'actual-collector-comparison','exec'),ens)
check('collector requires both endpoint identities',lambda:require(all(r['exact_match'] for r in ens['endpoint_matches'](checked,receipt).values()),'both endpoints'))
changed_receipt=dict(receipt,scheduler=dict(bytes=124,sha256='b'*64))
check('collector exposes scheduler byte mismatch',lambda:require(not all(r['exact_match'] for r in ens['endpoint_matches'](checked,changed_receipt).values()),'mismatch'))
snapshot=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='snapshot')
sample_guard=next(n for n in snapshot.body if isinstance(n,ast.Expr) and any(isinstance(c,ast.Constant) and c.value=='true opening sample identity required' for c in ast.walk(n)))
receipt_guard=next(n for n in baseline.body if isinstance(n,ast.Expr) and any(isinstance(c,ast.Constant) and c.value=='actual owned private receipt descriptor required without body access' for c in ast.walk(n)))
def execute_guard(node,**values):
 local=dict(ns,**values);exec(compile(ast.Module(body=[node],type_ignores=[]),'exact-opening-identity-guard','exec'),local)
for index in (3,4,5):
 path=F/'private-runtime-snapshots'/('opening-v'+str(index).zfill(2))/'snapshot-receipt-v01.json'
 receipt=dict(schema='actor-context-ranking-private-endpoints/v1',role='opening',cell=None,index=index)
 descriptor=dict(path=str(path),bytes=1,sha256='0'*64)
 check('copied-state opening index '+str(index),lambda path=path,r=receipt:execute_guard(sample_guard,path=path,receipt=r))
 check('public opening receipt '+str(index),lambda r=descriptor:execute_guard(receipt_guard,receipt=r))
for index in (1,2,6,True,3.):
 path=F/'private-runtime-snapshots'/('opening-v'+str(index).zfill(2))/'snapshot-receipt-v01.json'
 receipt=dict(schema='actor-context-ranking-private-endpoints/v1',role='opening',cell=None,index=index)
 check('diagnostic/out-of-scope/wrongtype opening index '+str(index),lambda path=path,r=receipt:execute_guard(sample_guard,path=path,receipt=r),True)
for label in ('opening-v01','opening-v02','opening-v06','opening-v003','opening-v3'):
 descriptor=dict(path=str(F/'private-runtime-snapshots'/label/'snapshot-receipt-v01.json'),bytes=1,sha256='0'*64)
 check('public noncollection opening path '+label,lambda r=descriptor:execute_guard(receipt_guard,receipt=r),True)
for path,raw_name,length in [(COLLECTOR,'_raw',6692),(OBSERVER,'_protocol_raw',21090)]:
 source_tree=ast.parse(path.read_bytes())
 guard=next(n for n in source_tree.body if isinstance(n,ast.If) and any(isinstance(c,ast.Name) and c.id==raw_name for c in ast.walk(n)))
 source_raw=(F/'sample_actor_context_ranking_private_resources_v01.py' if path==COLLECTOR else PROTOCOL).read_bytes()
 local=dict(hashlib=hashlib,SAMPLER_SHA256='ad9d0bffaf611957590d44f89aa2e3a3cf484943119e1459f7523ba3c152aff2')
 def raw_guard(value,node=guard,name=raw_name,base=local):
  execute=dict(base);execute[name]=value;exec(compile(ast.Module(body=[node],type_ignores=[]),'actual-preexec-source-pin-guard','exec'),execute)
 check(path.name+' exact source guard',lambda v=source_raw:raw_guard(v))
 changed=bytearray(source_raw);changed[-1]^=1
 check(path.name+' source hash drift before compile',lambda v=bytes(changed):raw_guard(v),True)
 calls=[n for n in ast.walk(source_tree) if isinstance(n,ast.Call)]
 require(not any(isinstance(n.func,ast.Attribute) and n.func.attr in {'exec_module','spec_from_file_location'} for n in calls),'bytecode loader route remains')
 compile_call=next(n for n in calls if isinstance(n.func,ast.Name) and n.func.id=='compile')
 check(path.name+' compile exact pinned raw bytes',lambda call=compile_call,name=raw_name:require(isinstance(call.args[0],ast.Name) and call.args[0].id==name and any(k.arg=='dont_inherit' and k.value.value is True for k in call.keywords),'raw compile route'))
value=dict(schema='actor-context-ranking-current-resource-ports-independent-controls/v1',passed=True,findings=[],control_count=len(cases),controls=cases,
 artifacts={str(p):dict(bytes=n,sha256=h) for p,n,h in pins},source=pin(Path(__file__).resolve()),
 actual_collector_or_observer_mains=0,production_or_resource_module_imports=0,private_body_reads=0,resource_API_calls=0,
 actual_censuses=0,live_proc_reads=0,model_calls=0,claims=0,synthetic_baseline_approvals_created=False)
out=F/'current-resource-ports-independent-controls-v02.json';data=(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()
fd=os.open(out,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o444)
with os.fdopen(fd,'wb') as stream:stream.write(data)
print(json.dumps(pin(out)))
