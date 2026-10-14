"""Detached smoke denial/profile controls; no resource imports or actual profiling."""
import ast
import hashlib
import importlib.abc
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

F=Path(__file__).resolve().parent
SOURCE=F/'capture_actor_context_ranking_resource_import_smoke_v01.py'
raw=SOURCE.read_bytes();assert (len(raw),hashlib.sha256(raw).hexdigest())==(24004,'6b2da968b047405a4821b0fc59a87738f36db67f73e174977a90a0c9249b71a6')
tree=ast.parse(raw)
names={'SmokeRefusal','require','Guard'}
nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in names]
ns=dict(importlib=importlib,Path=Path,sys=sys,os=os,ROOT=F,HELPER=F/'bootstrap_actor_context_ranking_resources_v02.py',
 OUTPUT=F/'resource-bootstrap-import-smoke-v01.json',PACKAGES=('ipfs_datasets_py','ipfs_datasets_py.optimizers','ipfs_datasets_py.optimizers.logic_theorem_optimizer'))
for n in tree.body:
 if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='BANNED_ROOTS' for t in n.targets):
  exec(compile(ast.Module(body=[n],type_ignores=[]),'actual-banned-roots','exec'),ns)
ns['MODULES']={'ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler':'scheduler.py'}
exec(compile(ast.Module(body=nodes,type_ignores=[]),'detached-resource-smoke-guards','exec'),ns)
Guard=ns['Guard'];Refusal=ns['SmokeRefusal'];module=next(iter(ns['MODULES']))
def guard():
 g=Guard.__new__(Guard);g.readable={str(SOURCE)};g.allowed={};g.classes={};g.resource_paths={'/synthetic/resource.py'}
 g.stdlib=Path('/synthetic/stdlib');g.dataclasses='/synthetic/stdlib/dataclasses.py';g.zip_paths=set()
 g.phase='guarded_import';g.receipt_fd=None;g.receipt_creations=0;g.bootstrap_calls=0
 g.resource_module_calls={};g.resource_class_calls={};g.dataclass_function_factories=0;g.forbidden_events=[];g.audit_probes=0
 return g
cases=[]
def check(name,fn,reject=False):
 try:fn()
 except Refusal:
  if not reject:raise
 else:
  if reject:raise AssertionError('Forbidden synthetic action accepted: '+name)
 cases.append(dict(name=name,passed=True,expected_refusal=reject))
for name in ('torch','numpy','huggingface_hub','ipfs_datasets_py.router_deps','unqualified_package'):
 check('import refused '+name,lambda n=name:guard().find_spec(n),True)
check('stdlib import finder is passive',lambda:ns['require'](guard().find_spec('json') is None,'stdlib'))
for path in ('/proc/self/stat','/sys/fs/cgroup/memory.current','/tmp/ipfs-datasets-resource-scheduler-1000.json','relative.json'):
 check('endpoint/read refused '+path,lambda p=path:guard().audit('open',(p,'r',0)),True)
check('public pinned source read admitted',lambda:guard().audit('open',(str(SOURCE),'r',0)))
for event,args in [('os.scandir',(F,)),('os.listdir',(F,)),('socket.connect',()),('subprocess.Popen',()),('ctypes.dlopen',()),('os.mkdir',('/synthetic/new',)),('os.putenv',('X','Y'))]:
 check('mutating/process/census event '+event,lambda e=event,a=args:guard().audit(e,a),True)
flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL
check('receipt write prohibited during imports',lambda:guard().audit('open',(str(ns['OUTPUT']),'w',flags)),True)
g=guard();g.phase='receipt';g.audit('open',(str(ns['OUTPUT']),'w',flags))
check('second receipt creation refused',lambda:g.audit('open',(str(ns['OUTPUT']),'w',flags)),True)
check('unknown file descriptor refused',lambda:guard().audit('open',(7,'w',flags)),True)
def code(source,filename,name=None):
 value=compile(source,filename,'exec')
 return value if name is None else next(x for x in value.co_consts if isinstance(x,type(value)) and x.co_name==name)
def frame(value,mod=module,locals=None,caller=None):return SimpleNamespace(f_code=value,f_globals={'__name__':mod},f_locals=locals or {},f_back=caller)
native=code('pass','/synthetic/resource.py');g=guard();g.allowed[native]=('module',module)
check('one exact module frame admitted',lambda:g.profile(frame(native),'call',None))
check('module reexecution refused',lambda:g.profile(frame(native),'call',None),True)
g=guard();g.allowed[native]=('module',module)
check('same code wrong module refused',lambda:g.profile(frame(native,'wrong.module'),'call',None),True)
body=code('class A:\n pass','/synthetic/resource.py','A');g=guard();g.allowed[body]=('class',module);g.classes[body]='A'
check('class definition body admitted',lambda:g.profile(frame(body),'call',None))
check('class definition return identity admitted',lambda:g.profile(frame(body,locals={'__module__':module,'__qualname__':'A'}),'return',None))
g=guard();g.allowed[body]=('class',module);g.classes[body]='A'
check('class definition spoof refused',lambda:g.profile(frame(body,locals={'__module__':'wrong','__qualname__':'A'}),'return',None),True)
for name in ('__init__','collect_proof_host_resources','acquire','release'):
 value=code('def '+name+'():\n pass','/synthetic/resource.py',name)
 check('native constructor/method/sampler refused '+name,lambda c=value:guard().profile(frame(c),'call',None),True)
factory=code('def __create_fn__():\n pass','<string>','__create_fn__')
caller=code('def _create_fn():\n pass','/synthetic/stdlib/dataclasses.py','_create_fn');g=guard()
check('stdlib dataclass definition factory admitted',lambda:g.profile(frame(factory,caller=frame(caller,'dataclasses')),'call',None))
check('dataclass factory without trusted caller refused',lambda:guard().profile(frame(factory),'call',None),True)
def pin(path):
 data=Path(path).read_bytes();return dict(path=str(path),bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
value=dict(schema='actor-context-ranking-resource-import-smoke-independent-controls/v1',passed=True,findings=[],control_count=len(cases),controls=cases,
 source=pin(Path(__file__).resolve()),producer=pin(SOURCE),actual_resource_module_imports=0,actual_guard_or_profile_installations=0,
 actual_smoke_main_calls=0,private_body_reads=0,resource_API_calls=0,model_calls=0,network_calls=0,sampler_calls=0)
out=F/'resource-import-smoke-independent-controls-v01.json';data=(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()
fd=os.open(out,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o444)
with os.fdopen(fd,'wb') as stream:stream.write(data)
print(json.dumps(pin(out)))
