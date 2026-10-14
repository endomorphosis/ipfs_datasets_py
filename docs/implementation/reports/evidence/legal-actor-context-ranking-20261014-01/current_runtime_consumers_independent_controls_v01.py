"""Detached current reviewer/terminal/freezer guards; no real runtime inputs."""
import ast
from collections import Counter
import copy
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

F=Path(__file__).resolve().parent
FILES={'review_actor_context_ranking_training_plan_v03.py':(9570,'7de92b9619ea87738efdb3db9724f023a36fb27fb5ea8c1f4f3a5dbe8b4d50ea'),
 'audit_actor_context_ranking_terminal_resources_v04.py':(18940,'c29556a0bdd304933b8de5ba26d7162fdcae750e8e30009df5b6a134bf892aca'),
 'freeze_actor_context_ranking_outputs_v04.py':(20862,'d44331aa0dc7377a0cddcdd4eabfb060c1594b2e3c84e93463fbdebd2732c927')}
def pin(path):
 raw=Path(path).read_bytes();return dict(path=str(path),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
trees={}
for name,pair in FILES.items():
 value=pin(F/name);assert (value['bytes'],value['sha256'])==pair;trees[name]=ast.parse((F/name).read_bytes())
def require(ok,message):
 if not ok:raise ValueError(message)
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
ns=dict(Path=Path,F=F,Counter=Counter)
protocol=ast.parse((F/'actor_context_ranking_resource_protocol_v03.py').read_bytes())
ns.update(require=require,digest=digest)
nodes=[n for n in protocol.body if isinstance(n,ast.FunctionDef) and n.name=='qualify_ledger']
exec(compile(ast.Module(body=nodes,type_ignores=[]),'detached-current-ledger','exec'),ns)
p=SimpleNamespace(require=require,digest=digest,qualify_ledger=ns['qualify_ledger'])
terminal='audit_actor_context_ranking_terminal_resources_v04.py'
defs=[n for n in trees[terminal].body if isinstance(n,ast.FunctionDef) and n.name in {'qualify_closing','qualify_public_custody'}]
ns.update(p=p);exec(compile(ast.Module(body=defs,type_ignores=[]),'detached-terminal-custody','exec'),ns)
cases=[]
def check(name,fn,reject=False):
 try:fn()
 except (ValueError,KeyError,TypeError):
  if not reject:raise
 else:
  if reject:raise AssertionError('Synthetic mutation accepted: '+name)
 cases.append(dict(name=name,passed=True,expected_refusal=reject))
def fake(name):return dict(path=str(F/name),bytes=1,sha256='0'*64)
contract=dict(cell='actor-context-ranking-hinge',attempt_name='actor-context-ranking-20261014-actor-context-ranking-hinge-01',
 run_root='/synthetic/never-opened-root',guardian=pin(F/'run_scope_guardian_v04.py'),resources=dict(cpu_slots=2,memory_mb=1536,child_process_slots=1,storage_bytes=200000000))
producers=dict(runner=pin(F/'run_actor_context_ranking_v04.py'),guardian=contract['guardian'])
planpin=fake('actor-context-ranking-hinge-plan-v01.json');reviewpin=fake('actor-context-ranking-hinge-training-review-v01.json')
plan=dict(schema='actor-context-ranking-cell-plan/v1',cell=contract['cell'],attempt_name=contract['attempt_name'],package_root=str(F/'datasets'),
 runner_path=producers['runner']['path'],guardian_path=producers['guardian']['path'],artifacts={v['path']:{k:v[k] for k in ('bytes','sha256')} for v in producers.values()})
review=dict(schema='actor-context-ranking-concrete-training-independent-review/v1',passed=True,findings=[],phase='training',plan_sha256=planpin['sha256'],
 package_root=plan['package_root'],run_root=contract['run_root'],runner_sha256=producers['runner']['sha256'],guardian_sha256=producers['guardian']['sha256'],artifacts={planpin['path']:planpin})
pre=dict(plan=planpin,review=reviewpin,**producers)
command=dict(argv=['/synthetic/python',producers['runner']['path'],'--plan',planpin['path'],'--output',str(Path(contract['run_root'])/contract['attempt_name']/'results')],
 cwd=plan['package_root'],candidate_pythonpath=plan['package_root'],resources=contract['resources'],no_cuda=True,no_proof_workers=True,model_authority=False)
wrappers={'pre-admission.json':pre,'command.json':command}
def custody(pl=plan,rv=review,wr=wrappers):return ns['qualify_public_custody'](contract,pl,rv,planpin,reviewpin,producers,wr)
check('exact current V04 guarded command and review custody',custody)
for key,value in [('schema','actor-context-ranking-hingell-plan/v1'),('runner_path',str(F/'run_actor_context_ranking_v03.py')),('attempt_name','other')]:
 bad=copy.deepcopy(plan);bad[key]=value
 check('wrong plan '+key,lambda bad=bad:custody(pl=bad),True)
for key,value in [('schema','generic-review/v1'),('runner_sha256','1'*64),('guardian_sha256','1'*64)]:
 bad=copy.deepcopy(review);bad[key]=value
 check('wrong concrete review '+key,lambda bad=bad:custody(rv=bad),True)
bad=copy.deepcopy(wrappers);bad['command.json']['argv'][1]=str(F/'run_actor_context_ranking_v03.py')
check('old runner command cannot pass terminal custody',lambda:custody(wr=bad),True)
policy=json.loads((F/'resource-observation-policy-v02.json').read_bytes());small=copy.deepcopy(policy);small['required_preserved_claims']=[]
body=dict(reservation_id='baseline-extra',status='retained',storage_bytes=19);hashes={'baseline-extra':digest(body)}
ledger=dict(schema='daemon-resource-reservations-v1',roots=small['counted_root_metadata'],limit_bytes=145000000000,
 reservations={'baseline-extra':body,'own':dict(reservation_id='own',status='released',storage_bytes=200000000),
 'foreign-new':dict(reservation_id='foreign-new',status='active',storage_bytes=7)})
def closing(value):return ns['qualify_closing'](small,value,hashes,'own')
check('dynamic baseline plus own released claim and all concurrent fullcharges',lambda:require(closing(ledger)['record_count']==3 and closing(ledger)['full_nonreleased_claim_bytes']==26 and closing(ledger)['additional_concurrent_record_count']==1,'all dynamic records'))
for key,value in [('status','retained'),('storage_bytes',199999999)]:
 bad=copy.deepcopy(ledger);bad['reservations']['own'][key]=value
 check('wrong own '+key,lambda bad=bad:closing(bad),True)
bad=copy.deepcopy(ledger);bad['reservations']['baseline-extra']['status']='released'
check('changed dynamic baseline body refuses',lambda:closing(bad),True)
for name,tree in trees.items():
 candidates=[n for n in ast.walk(tree) if isinstance(n,ast.If) and any(isinstance(c,ast.Name) and c.id=='_checked_raw' for c in ast.walk(n))]
 guard=next(n for n in candidates if any(isinstance(c,ast.Raise) for c in ast.walk(n)))
 helper=F/('actor_context_ranking_resource_protocol_v03.py' if name==terminal else 'run_actor_context_ranking_v04.py')
 source=helper.read_bytes()
 def test_guard(raw,g=guard):exec(compile(ast.Module(body=[g],type_ignores=[]),'actual-source-preexec-pin','exec'),dict(_checked_raw=raw,hashlib=hashlib))
 check(name+' exact helper source passes preexec pin',lambda raw=source:test_guard(raw))
 bad=bytearray(source);bad[-1]^=1
 check(name+' changed helper rejected before execution',lambda raw=bytes(bad):test_guard(raw),True)
 calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call)]
 check(name+' no SourceFileLoader route',lambda calls=calls:require(not any(isinstance(c.func,ast.Attribute) and c.func.attr in {'exec_module','spec_from_file_location'} for c in calls),'loader'))
 compilecall=next(c for c in calls if isinstance(c.func,ast.Name) and c.func.id=='compile')
 check(name+' exact raw compile',lambda c=compilecall:require(isinstance(c.args[0],ast.Name) and c.args[0].id=='_checked_raw' and any(k.arg=='dont_inherit' and k.value.value is True for k in c.keywords),'raw compile'))
value=dict(schema='actor-context-ranking-current-runtime-consumers-independent-controls/v1',passed=True,findings=[],control_count=len(cases),controls=cases,
 source=pin(Path(__file__).resolve()),artifacts={str(F/n):dict(bytes=b,sha256=h) for n,(b,h) in FILES.items()},
 pure_AST_only=True,actual_runtime_or_plan_reads=0,actual_mains=0,private_body_reads=0,resource_API_calls=0,model_calls=0,checkpoint_JSON_parses=0,network_calls=0)
out=F/'current-runtime-consumers-independent-controls-v01.json';data=(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()
fd=os.open(out,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o444)
with os.fdopen(fd,'wb') as stream:stream.write(data)
print(json.dumps(pin(out)))
