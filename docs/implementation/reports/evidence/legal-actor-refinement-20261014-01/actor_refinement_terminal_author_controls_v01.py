"""Dynamic closing/custody fixtures only; no terminal main or copied bodies."""
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
spec=importlib.util.spec_from_file_location('terminal_pure_fixture_subject',F/'audit_actor_refinement_terminal_resources_v01.py')
t=importlib.util.module_from_spec(spec);spec.loader.exec_module(t)
policy=json.loads((F/'resource-observation-policy-v01.json').read_bytes());policy['required_preserved_claims']=[]
cases=[]
def pin(path):
    raw=Path(path).read_bytes();return dict(path=str(path),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
def check(name,fn,refuses=False):
    try:fn()
    except (ValueError,KeyError):
        if not refuses:raise
    else:
        if refuses:raise AssertionError(name+' accepted')
    cases.append(dict(name=name,passed=True,expected_refusal=refuses))
prior=dict(reservation_id='baseline',status='retained',storage_bytes=19)
hashes={'baseline':t.p.digest(prior)}
closing=dict(schema='daemon-resource-reservations-v1',limit_bytes=145000000000,roots=policy['counted_root_metadata'],reservations={
    'baseline':prior,'own':dict(reservation_id='own',status='released',storage_bytes=200000000),
    'foreign':dict(reservation_id='foreign',status='active',storage_bytes=71)})
result=t.qualify_closing(policy,closing,hashes,'own')
check('dynamic baseline plusown plusforeign fullyaccounted',lambda:t.p.require(result['record_count']==3
    and result['preserved_prior_record_count']==1 and result['full_nonreleased_claim_bytes']==90
    and result['additional_concurrent_record_count']==1 and result['additional_concurrent_full_nonreleased_claim_bytes']==71,'dynamic'))
bad=copy.deepcopy(closing);bad['reservations']['baseline']['status']='released'
check('any baseline body status change refused',lambda:t.qualify_closing(policy,bad,hashes,'own'),True)
bad=copy.deepcopy(closing);del bad['reservations']['baseline']
check('any baseline record disappearance refused',lambda:t.qualify_closing(policy,bad,hashes,'own'),True)
bad=copy.deepcopy(closing);bad['reservations']['own']['status']='retained'
check('retained ownclaim refused',lambda:t.qualify_closing(policy,bad,hashes,'own'),True)
bad=copy.deepcopy(closing);bad['reservations']['own']['storage_bytes']=200000001
check('own budget drift refused',lambda:t.qualify_closing(policy,bad,hashes,'own'),True)
check('prior ownID reuse refused',lambda:t.qualify_closing(policy,closing,hashes,'baseline'),True)
bad=copy.deepcopy(closing);bad['reservations']['foreign']['storage_bytes']=True
check('boolean foreign claim refused',lambda:t.qualify_closing(policy,bad,hashes,'own'),True)
bad=copy.deepcopy(closing);bad['reservations']['foreign']['status']='released'
check('new released foreign record addsnocharge',lambda:t.p.require(t.qualify_closing(policy,bad,hashes,'own')['full_nonreleased_claim_bytes']==19,'released'))
def fake(path):return dict(path=str(path),bytes=1,sha256='0'*64)
plan_pin=fake(F/'actor-refinement-ce-plan-v01.json');review_pin=fake(F/'actor-refinement-ce-training-review-v01.json')
producers=dict(runner=pin(F/'run_actor_refinement_v03.py'),guardian=policy['guardian'])
plan=dict(schema='actor-refinement-cell-plan/v1',cell=policy['cell'],attempt_name=policy['attempt_name'],package_root=str(F/'datasets'),
    runner_path=producers['runner']['path'],guardian_path=producers['guardian']['path'],
    artifacts={item['path']:{key:item[key] for key in ('bytes','sha256')} for item in producers.values()})
review=dict(schema='actor-refinement-concrete-training-independent-review/v1',passed=True,findings=[],phase='training',
    plan_sha256=plan_pin['sha256'],package_root=plan['package_root'],run_root=policy['run_root'],artifacts={plan_pin['path']:plan_pin},
    runner_sha256=producers['runner']['sha256'],guardian_sha256=producers['guardian']['sha256'])
check('actualV03 custody andconcrete review schema',lambda:t.qualify_public_custody(policy,plan,review,plan_pin,review_pin,producers))
bad=copy.deepcopy(review);bad['schema']='actor-refinement-training-independent-review/v1'
check('stale nonconcrete review schema refused',lambda:t.qualify_public_custody(policy,plan,bad,plan_pin,review_pin,producers),True)
bad=copy.deepcopy(plan);bad['runner_path']=str(F/'run_actor_refinement_v02.py')
check('stale runnerV02 custody refused',lambda:t.qualify_public_custody(policy,bad,review,plan_pin,review_pin,producers),True)
own_source=ast.parse((F/'audit_actor_refinement_terminal_resources_v01.py').read_bytes())
old_source=ast.parse((F.parent/'legal-balanced-execution-20261014-01/audit_conditions_balanced_terminal_resources_v01.py').read_bytes())
select=lambda tree,name:next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
check('retained ownclaim lease RSS loader exact priorAST',lambda:t.p.require(ast.dump(select(own_source,'retained_helpers'),include_attributes=False)
    ==ast.dump(select(old_source,'retained_helpers'),include_attributes=False),'retainedAST'))
main=select(own_source,'main');calls={n.func.attr for n in ast.walk(main) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
check('terminal main containsno actual treecensus call',lambda:t.p.require('_inventory' not in calls,'census'))
out=F/'actor-refinement-terminal-author-controls-v01.json'
value=dict(schema='actor-refinement-terminal-resource-author-controls/v1',passed=True,findings=[],control_count=len(cases),controls=cases,
    observer=pin(F/'audit_actor_refinement_terminal_resources_v01.py'),protocol=pin(F/'actor_refinement_resource_protocol_v03.py'),
    source=pin(Path(__file__).resolve()),inherited_own_lease_RSS_helpers=t.OLD_HELPERS,inherited_controls_rerun=False,
    actual_terminal_main_calls=0,private_body_reads=0,actual_tree_censuses=0,resource_API_calls=0,model_calls=0,numerical_imports=0)
with out.open('x') as stream:json.dump(value,stream,sort_keys=True,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
out.chmod(0o444);print(json.dumps(pin(out),sort_keys=True))
