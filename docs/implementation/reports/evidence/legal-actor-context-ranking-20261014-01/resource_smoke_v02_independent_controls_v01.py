"""Real stdlib _create_fn, synthetic namespace, extracted guards; no resource imports."""
import ast
import dataclasses
import hashlib
import importlib.abc
import json
import os
from pathlib import Path
import stat
import sys
import types

F=Path(__file__).resolve().parent
SOURCE=F/'capture_actor_context_ranking_resource_import_smoke_v02.py'
raw=SOURCE.read_bytes();assert (len(raw),hashlib.sha256(raw).hexdigest())==(35640,'cd5f7e479c6bff9e00089c98503cbd0a79d18c566e4e8d64269767a54eafc4b7')
tree=ast.parse(raw)
names={'SmokeRefusal','require','raw_source','checked_create_fn','definition_only_dataclass_text','Guard'}
nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in names]
NS=dict(importlib=importlib,Path=Path,stat=stat,sys=sys,os=os,types=types,hashlib=hashlib,ast=ast,
 ROOT=F,HELPER=F/'bootstrap_actor_context_ranking_resources_v02.py',OUTPUT=F/'resource-bootstrap-import-smoke-v02.json',
 DATACLASSES=Path('/usr/lib/python3.12/dataclasses.py'),FIXED={Path('/usr/lib/python3.12/dataclasses.py'):(61753,'0e449d55d6206b0022f541ba32be88fafc934ff71d9aa65f31f101ca6147f2ae')},
 GENERATED_METHOD_NAMES=frozenset({'__init__','__repr__','__eq__','__hash__','__setattr__','__delattr__'}),
 PACKAGES=('ipfs_datasets_py',),MODULES={'_independent_synthetic_resource':'/synthetic/resource.py'},BANNED_ROOTS=frozenset({'torch','numpy'}))
exec(compile(ast.Module(body=nodes,type_ignores=[]),'detached-V02-resource-smoke-guards','exec'),NS)
Guard=NS['Guard'];Refusal=NS['SmokeRefusal'];methods=NS['definition_only_dataclass_text']
stdlib_globals,stdlib_code=NS['checked_create_fn']()
def guard():
 g=Guard.__new__(Guard);g.allowed={};g.classes={};g.resource_paths={'/synthetic/resource.py'}
 g.dataclasses=str(NS['DATACLASSES']);g.dataclasses_globals=stdlib_globals;g.create_fn_code=stdlib_code
 g.bootstrap_calls=0;g.resource_module_calls={};g.resource_class_calls={};g.forbidden_events=[]
 g.dataclass_function_factories=0;g.dataclass_definition_modules=0;g.dataclass_methods_defined=0
 g.pending_dataclass_definitions={};g.dataclass_definition_proofs=[];g.refused_frames=[]
 return g
cases=[]
def require(ok,message):
 if not ok:raise AssertionError(message)
def check(name,fn,reject=False):
 try:fn()
 except (Refusal,SyntaxError):
  if not reject:raise
 else:
  if reject:raise AssertionError('Adversarial fixture accepted: '+name)
 cases.append(dict(name=name,passed=True,expected_refusal=reject))
fake=types.ModuleType('_independent_synthetic_resource');fake.__file__='/synthetic/resource.py'
require(fake.__name__ not in sys.modules,'fresh fake namespace')
sys.modules[fake.__name__]=fake
try:
 def guarded_definition():
  g=guard();profile=g.profile;sys.setprofile(profile)
  try:
   method=dataclasses._create_fn('__init__',['self','x'],['self.x=x'],globals=fake.__dict__,locals={})
   require(sys.getprofile() is profile,'profile unexpectedly disabled')
  finally:sys.setprofile(None)
  require(g.dataclass_definition_modules==g.dataclass_function_factories==g.dataclass_methods_defined==1,'one complete definition/factory chain')
  require(not g.pending_dataclass_definitions and not g.forbidden_events,'completed clean scaffolding')
  return g,method
 good,method=guarded_definition()
 check('real pinned stdlib module and factory definitions accepted without method call',lambda:require(len(good.dataclass_definition_proofs)==1,'proof'))
 touches=[];fake.__dict__['forbidden_probe']=lambda:touches.append('called')
 g=guard();profile=g.profile;sys.setprofile(profile)
 try:
  uncalled=dataclasses._create_fn('__init__',['self'],['forbidden_probe()'],globals=fake.__dict__,locals={})
 finally:sys.setprofile(None)
 def blocked_native_method():
  profile=g.profile;sys.setprofile(profile)
  try:uncalled(object())
  finally:sys.setprofile(None)
 check('real generated native method call refused before body',blocked_native_method,True)
 require(touches==[],'method probe unexpectedly ran')
 text='def __create_fn__():\n def __init__(self):\n  forbidden_probe()\n return __init__\n'
 def blocked_direct_exec():
  g=guard();ns={};profile=g.profile;sys.setprofile(profile)
  try:exec(compile(text,'<string>','exec'),fake.__dict__,ns)
  finally:sys.setprofile(None)
 check('same definition text outside authenticated stdlib caller refused',blocked_direct_exec,True)
 require(touches==[],'direct definition probe unexpectedly ran')
finally:
 sys.setprofile(None);del sys.modules[fake.__name__]
check('safe definition shape compiles without executing nested native method',lambda:methods(text,'__init__',[]))
for name,text in [
 ('module side effect',"forbidden_probe()\ndef __create_fn__():\n def __init__(self): pass\n return __init__"),
 ('outer decorator',"@forbidden_probe()\ndef __create_fn__():\n def __init__(self): pass\n return __init__"),
 ('outer default',"def __create_fn__(x=forbidden_probe()):\n def __init__(self): pass\n return __init__"),
 ('inner default',"def __create_fn__():\n def __init__(self,x=forbidden_probe()): pass\n return __init__"),
 ('inner annotation',"def __create_fn__():\n def __init__(self,x:forbidden_probe()): pass\n return __init__"),
 ('factory extra statement',"def __create_fn__():\n def __init__(self): pass\n forbidden_probe()\n return __init__"),
 ('wrong returned function',"def __create_fn__():\n def __init__(self): pass\n return forbidden_probe")]:
 check('definition-only rejection '+name,lambda t=text:methods(t,'__init__',[]),True)
text='def __create_fn__():\n def acquire(self): pass\n return acquire'
check('native API method cannot become generated exception',lambda:methods(text,'acquire',[]),True)
text='def __create_fn__(x):\n def __init__(self): pass\n return __init__'
check('factory local-name signature mismatch refuses',lambda:methods(text,'__init__',[]),True)
def pin(path):
 data=Path(path).read_bytes();return dict(path=str(path),bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
value=dict(schema='actor-context-ranking-resource-smoke-V02-independent-controls/v1',passed=True,findings=[],control_count=len(cases),controls=cases,
 source=pin(Path(__file__).resolve()),producer=pin(SOURCE),dataclasses_source=pin(NS['DATACLASSES']),
 actual_stdlib_create_fn_called=True,synthetic_namespace_only=True,native_method_probe_touches=touches,
 actual_resource_module_imports=0,actual_smoke_main_calls=0,resource_API_calls=0,private_body_reads=0,sampler_calls=0,model_calls=0,
 inherited_audit_controls_reused_from='resource-import-smoke-independent-controls-v01.json')
out=F/'resource-smoke-v02-independent-controls-v01.json';data=(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()
fd=os.open(out,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o444)
with os.fdopen(fd,'wb') as stream:stream.write(data)
print(json.dumps(pin(out)))
