"""Independent synthetic checks of F16 resource predicates; no observations."""
import ast
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode=True
F=Path(__file__).resolve().parent
OUTPUT=F/'resource-protocol-peer-controls-v01.json'
def pin(path):
    path=Path(path);raw=path.read_bytes()
    return dict(path=str(path),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
spec=importlib.util.spec_from_file_location('peer_reviewed_resource_predicates',F/'actor_context_ranking_resource_protocol_v01.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
policy=json.loads((F/'resource-observation-policy-v01.json').read_bytes())
p.qualify_policy(policy)
cases=[]
def check(name,fn,reject=False):
    try:fn()
    except (ValueError,KeyError):
        if not reject:raise
    else:
        if reject:raise AssertionError('Synthetic tampering accepted: '+name)
    cases.append(dict(name=name,passed=True,expected_refusal=reject))

state=dict(schema_version=1,config=copy.deepcopy(policy['scheduler_config']),leases={'a':{},'b':{}},waiters={'w':{}})
receipt={name:dict(bytes=123,sha256=('a' if name=='ledger' else 'b')*64) for name in ('ledger','scheduler')}
status=dict(full_nonreleased_claim_bytes=37)
checked=dict(schema='scope-pilot-resource-compatibility/v1',passed=True,findings=[],resources=policy['resources'],
    disk_limit_bytes=policy['global_cap_bytes'],outstanding_full_reservations_bytes=37,shared_config=state['config'],
    lease_count=2,waiter_count=1,model_started=False,reservation_acquired=False,scheduler_client_constructed=False,
    shared_state_modified=False,admission_guaranteed=False,disk_ledger=receipt['ledger'],shared_state=receipt['scheduler'],
    producers={path:dict(path=path,**brief) for path,brief in policy['resource_producer_pins'].items()})
check('nonidle sample retains true occupancy',lambda:p.require(p.qualify_check(policy,checked,receipt,state,status)['lease_count']==2,'occupancy'))
for name in ('ledger','scheduler'):
    bad=copy.deepcopy(receipt);bad[name]['sha256']='0'*64
    check(name+' byte identity mismatch rejected',lambda bad=bad:p.qualify_check(policy,checked,bad,state,status),True)
bad=copy.deepcopy(checked);bad['lease_count']=0
check('false idle declaration rejected',lambda:p.qualify_check(policy,bad,receipt,state,status),True)
bad=copy.deepcopy(checked);bad['producers'][next(iter(bad['producers']))]['sha256']='0'*64
check('same path forged producer identity rejected',lambda:p.qualify_check(policy,bad,receipt,state,status),True)

small=copy.deepcopy(policy);small['required_preserved_claims']=[]
body=dict(reservation_id='historical',status='retained',storage_bytes=19)
hashes={'historical':p.digest(body)}
ledger=dict(schema='daemon-resource-reservations-v1',roots=policy['counted_root_metadata'],limit_bytes=145000000000,
    reservations={'historical':body,'new-active':dict(reservation_id='new-active',status='active',storage_bytes=23),
        'new-reserved':dict(reservation_id='new-reserved',status='reserved',storage_bytes=29),
        'new-released':dict(reservation_id='new-released',status='released',storage_bytes=31)})
check('all active reserved retained full claims charged',lambda:p.require(p.qualify_ledger(small,ledger,hashes)['full_nonreleased_claim_bytes']==71,'full charge'))
bad=copy.deepcopy(ledger);bad['reservations']['historical']['status']='released'
check('foreign historical release rejected',lambda:p.qualify_ledger(small,bad,hashes),True)
bad=copy.deepcopy(ledger);del bad['reservations']['historical']
check('historical omission rejected',lambda:p.qualify_ledger(small,bad,hashes),True)
bad=copy.deepcopy(ledger);bad['reservations']['new-active']['storage_bytes']=23.0
check('floating point claim rejected',lambda:p.qualify_ledger(small,bad,hashes),True)
bad=copy.deepcopy(ledger);bad['reservations']['new-active']['reservation_id']='another'
check('reservation map identity mismatch rejected',lambda:p.qualify_ledger(small,bad,hashes),True)
check('future output charged beyond native admission',lambda:p.require(p.capacity(policy,144700000000,0,10**12)['native_capacity_fits']
    and not p.capacity(policy,144700000000,0,10**12)['full_run_capacity_fits'],'future bound'))
check('physical shortfall counts all claims and both bounds',lambda:p.require(not p.capacity(policy,0,71,400000070)['full_run_capacity_fits'],'physical bound'))

# Execute only the actual collector's pure endpoint comparison; never its imports/main.
source=F/'collect_actor_context_ranking_opening_v01.py'
node=next(n for n in ast.parse(source.read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='endpoint_matches')
ns=dict(s=p);exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),ns)
check('collector requires both endpoints exact',lambda:p.require(all(v['exact_match'] for v in ns['endpoint_matches'](checked,receipt).values()),'both matches'))
bad=copy.deepcopy(receipt);bad['scheduler']['sha256']='0'*64
check('matching ledger cannot hide changed scheduler',lambda:p.require(not all(v['exact_match'] for v in ns['endpoint_matches'](checked,bad).values()),'scheduler mismatch'))

for n in ('run_scope_guardian_v02.py','adopt_shared_scheduler_actor_ranking_v02.py','owned_lease_watchdog_actor_ranking_v02.py'):
    check('retained qualified bridge exact '+n,lambda n=n:p.require((F/n).read_bytes()==(F.parent/'legal-actor-refinement-20261014-01'/n).read_bytes(),'bridge drift'))
check('sampler exact phase and cell-only port',lambda:p.require((F/'sample_actor_context_ranking_private_resources_v01.py').read_bytes()==
    (F.parent/'legal-actor-refinement-20261014-01/sample_actor_refinement_private_resources_v01.py').read_bytes()
    .replace(b'actor-refinement-ce',b'actor-context-ranking-hinge').replace(b'actor-refinement',b'actor-context-ranking'),'sampler port drift'))
if any(n.split('.')[0] in {'torch','numpy','transformers','sentence_transformers','huggingface_hub','ipfs_datasets_py'} for n in sys.modules):
    raise AssertionError('Numerical/package import during synthetic controls')
value=dict(schema='actor-context-ranking-resource-protocol-peer-controls/v1',passed=True,findings=[],
    observed_at_utc=datetime.now(timezone.utc).isoformat(),source=pin(Path(__file__).resolve()),
    protocol=pin(F/'actor_context_ranking_resource_protocol_v01.py'),policy=pin(F/'resource-observation-policy-v01.json'),
    collector=pin(source),control_count=len(cases),controls=cases,independent_of_resource_source_author=True,
    synthetic_only=True,private_body_reads=0,resource_API_calls=0,actual_censuses=0,model_calls=0,numerical_imports=0,claims=0)
with OUTPUT.open('x') as out:json.dump(value,out,sort_keys=True,indent=2);out.write('\n');out.flush();os.fsync(out.fileno())
OUTPUT.chmod(0o444);print(json.dumps(pin(OUTPUT)))
