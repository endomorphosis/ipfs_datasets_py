"""Exact literal-port proofs and pure descriptor joins, never collection main."""
import ast
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
sys.dont_write_bytecode=True
F=Path(__file__).resolve().parent
def pin(path):
    raw=path.read_bytes();return dict(path=str(path),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
spec=importlib.util.spec_from_file_location('collection_pure_controls',F/'collect_actor_refinement_opening_v01.py')
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
cases=[]
def check(name,fn,refuses=False):
    try:fn()
    except ValueError:
        if not refuses:raise
    else:
        if refuses:raise AssertionError(name+' accepted')
    cases.append(dict(name=name,passed=True,expected_refusal=refuses))
a=dict(bytes=51,sha256='a'*64);b=dict(bytes=63,sha256='b'*64)
current=dict(disk_ledger=a,shared_state=b,lease_count=3,waiter_count=2)
receipt=dict(ledger=a,scheduler=b)
check('both exact endpoint joins pass with nonidle occupancy',lambda:c.s.require(all(x['exact_match'] for x in c.endpoint_matches(current,receipt).values()),'pair'))
different=copy.deepcopy(receipt);different['ledger']['sha256']='c'*64
check('ledger mismatch is classified',lambda:c.s.require(not c.endpoint_matches(current,different)['ledger']['exact_match']
    and c.endpoint_matches(current,different)['scheduler']['exact_match'],'ledger'))
different=copy.deepcopy(receipt);different['scheduler']['sha256']='c'*64
check('scheduler churn mismatch is classified',lambda:c.s.require(c.endpoint_matches(current,different)['ledger']['exact_match']
    and not c.endpoint_matches(current,different)['scheduler']['exact_match'],'scheduler'))
different=copy.deepcopy(receipt);different['scheduler']['bytes']+=1
check('same hash different byte count is refused',lambda:c.s.require(not c.endpoint_matches(current,different)['scheduler']['exact_match'],'bytes'))
different=copy.deepcopy(receipt);different['ledger']['bytes']=True
check('boolean endpoint size is refused',lambda:c.endpoint_matches(current,different),True)
different=copy.deepcopy(receipt);different['scheduler']['sha256']='short'
check('malformed endpoint digest is refused',lambda:c.endpoint_matches(current,different),True)
protocol=(F/'actor_refinement_resource_protocol_v01.py').read_bytes()
for a,b in [(b'review_actor_refinement_resource_baseline_v01.py',b'review_actor_refinement_resource_baseline_v02.py'),
    (b'resource-observer-source-independent-review-v01.json',b'resource-observer-source-independent-review-v02.json'),
    (b'resource-baseline-inputs-v01.json',b'resource-baseline-inputs-v02.json')]:protocol=protocol.replace(a,b)
check('protocolV02 exactly three custody filename substitutions',lambda:c.s.require(protocol==(F/'actor_refinement_resource_protocol_v02.py').read_bytes(),'protocol diff'))
observer=(F/'review_actor_refinement_resource_baseline_v01.py').read_bytes()
for a,b in [(b'actor_refinement_resource_protocol_v01.py',b'actor_refinement_resource_protocol_v02.py'),
    (b'resource-observer-source-independent-review-v01.json',b'resource-observer-source-independent-review-v02.json'),
    (b'resource-baseline-inputs-v01.json',b'resource-baseline-inputs-v02.json')]:observer=observer.replace(a,b)
check('observerV02 only protocol/input/sourcegate path substitutions',lambda:c.s.require(observer==(F/'review_actor_refinement_resource_baseline_v02.py').read_bytes(),'observer diff'))
tree=ast.parse((F/'collect_actor_refinement_opening_v01.py').read_bytes());main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
loops=[n for n in ast.walk(main) if isinstance(n,ast.For) and isinstance(n.target,ast.Name) and n.target.id=='index']
check('collection bound exactly indices2,3,4',lambda:c.s.require(len(loops)==1 and ast.literal_eval(loops[0].iter)==(2,3,4),'loop bound'))
runs=[n for n in ast.walk(main) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and isinstance(n.func.value,ast.Name)
    and n.func.value.id=='subprocess' and n.func.attr=='run']
check('exactly two bounded child call sites',lambda:c.s.require(len(runs)==2 and all(any(k.arg=='timeout' and ast.literal_eval(k.value)==15 for k in n.keywords) for n in runs),'child bound'))
prior=pin(F/'actor-refinement-resource-author-controls-v01.json')
v=dict(schema='actor-refinement-resource-collection-author-controls/v1',passed=True,findings=[],control_count=len(cases),controls=cases,
 source=pin(Path(__file__).resolve()),collector=pin(F/'collect_actor_refinement_opening_v01.py'),
 observer=pin(F/'review_actor_refinement_resource_baseline_v02.py'),protocol=pin(F/'actor_refinement_resource_protocol_v02.py'),
 inherited25_controls=prior,inherited_controls_rerun=False,collector_main_calls=0,observer_main_calls=0,
 guardian_calls=0,sampler_calls=0,private_body_reads=0,actual_censuses=0,resource_API_calls=0,numerical_imports=0,model_calls=0)
out=F/'actor-refinement-collection-author-controls-v01.json'
with out.open('x') as f:json.dump(v,f,sort_keys=True,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
out.chmod(0o444);print(json.dumps(pin(out),sort_keys=True))
