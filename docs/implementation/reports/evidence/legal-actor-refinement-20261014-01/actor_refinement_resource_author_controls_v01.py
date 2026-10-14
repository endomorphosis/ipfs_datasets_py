"""Pure synthetic resource predicates; public historical hash metadata only."""
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
spec=importlib.util.spec_from_file_location('resource_controls_subject',F/'actor_refinement_resource_protocol_v01.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
cases=[]
def pin(path):
    raw=Path(path).read_bytes();return dict(path=str(path),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
def check(name,fn,refuses=False):
    try:fn()
    except (ValueError,KeyError):
        if not refuses:raise
    else:
        if refuses:raise AssertionError('negative fixture accepted: '+name)
    cases.append(dict(name=name,passed=True,expected_refusal=refuses))
policy=json.loads((F/'resource-observation-policy-v01.json').read_bytes())
check('exact immutable policy',lambda:p.qualify_policy(policy))
bad=copy.deepcopy(policy);bad['global_cap_bytes']+=1
check('cap policy mutation refused',lambda:p.qualify_policy(bad),True)
baseline=json.loads(Path(policy['prior_baseline']['path']).read_bytes())
terminal=json.loads(Path(policy['prior_terminal']['path']).read_bytes())
rebind=json.loads(Path(policy['prior_root_identity_reconciliation']['path']).read_bytes())
history=p.prior_hashes(policy,baseline,terminal,rebind)
check('public historical539 digest',lambda:p.require(len(history)==539 and p.digest(history)==policy['historical_record_body_hash_map_sha256'],'history'))
small_policy=copy.deepcopy(policy);small_policy['required_preserved_claims']=[]
bodies={'prior':dict(reservation_id='prior',status='retained',storage_bytes=13)}
hashes={key:p.digest(value) for key,value in bodies.items()}
ledger=dict(schema='daemon-resource-reservations-v1',roots=policy['counted_root_metadata'],limit_bytes=145000000000,reservations=copy.deepcopy(bodies))
ledger['reservations']['concurrent-active']=dict(reservation_id='concurrent-active',status='active',storage_bytes=71)
ledger['reservations']['concurrent-released']=dict(reservation_id='concurrent-released',status='released',storage_bytes=97)
result=p.qualify_ledger(small_policy,ledger,hashes)
check('all current nonreleased claims charged',lambda:p.require(result['record_count']==3 and result['full_nonreleased_claim_bytes']==84
    and result['additional_current_record_count']==2 and result['additional_current_full_nonreleased_claim_bytes']==71,'all claims'))
bad=copy.deepcopy(ledger);bad['reservations']['prior']['storage_bytes']=12
check('changed historical body refused',lambda:p.qualify_ledger(small_policy,bad,hashes),True)
bad=copy.deepcopy(ledger);bad['reservations']['concurrent-active']['storage_bytes']=True
check('boolean claim refused',lambda:p.qualify_ledger(small_policy,bad,hashes),True)
bad=copy.deepcopy(ledger);bad['reservations']['concurrent-active']['status']='unknown'
check('unknown current status refused',lambda:p.qualify_ledger(small_policy,bad,hashes),True)
check('apparent fullrun boundary fits',lambda:p.require(p.capacity(policy,144600000000,0,400000000)['full_run_capacity_fits'],'boundary'))
check('one byte apparent excess refuses',lambda:p.require(not p.capacity(policy,144600000001,0,400000000)['full_run_capacity_fits'],'excess'))
check('native fit does not imply fullrun fit',lambda:p.require(p.capacity(policy,144700000000,0,400000000)['native_capacity_fits']
    and not p.capacity(policy,144700000000,0,400000000)['full_run_capacity_fits'],'future bound'))
check('one byte physical shortage refuses',lambda:p.require(not p.capacity(policy,0,7,400000006)['full_run_capacity_fits'],'physical'))

def fake(name):return dict(path=str(F/name),bytes=1,sha256='0'*64)
extra_id='synthetic-concurrent-record';extra_hash='1'*64
actual=dict(history);actual[extra_id]=extra_hash
status=dict(schema='daemon-resource-reservations-v1',limit_bytes=145000000000,record_count=540,record_body_hashes=actual,
    record_body_hash_map_sha256=p.digest(actual),historical_record_body_hash_map_sha256=p.digest(history),
    record_status_counts={'released':438,'retained':101,'reserved':1},full_nonreleased_claim_bytes=44381777223,
    all_prior_record_bodies_unchanged=True,preserved_prior_record_count=539,additional_current_record_count=1,
    additional_current_record_status_counts={'reserved':1},additional_current_full_nonreleased_claim_bytes=7,
    additional_current_record_body_hashes={extra_id:extra_hash},additional_current_record_body_hash_map_sha256=p.digest({extra_id:extra_hash}))
fixture=dict(schema='actor-refinement-resource-baseline/v1',passed=True,findings=[],observation_policy=p.POLICY_PIN,
    observer=pin(F/'review_actor_refinement_resource_baseline_v01.py'),source_qualification=fake('resource-observer-source-independent-review-v01.json'),
    input_manifest=fake('resource-baseline-inputs-v01.json'),sampler_source_qualification=fake('sampler-source-independent-review-v01.json'),
    resource_bridge_source_qualification=fake('resource-bridge-source-independent-review-v01.json'),fresh_metadata_check=fake('guardian-check-v01.json'),
    private_sample_receipt=fake('private-runtime-snapshots/opening-v01/snapshot-receipt-v01.json'),
    baseline_ledger=status,historical_record_count=539,all_historical_record_bodies_unchanged=True,
    historical_record_body_hash_map_sha256=p.digest(history),counted_root_metadata=policy['counted_root_metadata'],
    scheduler_observation=dict(config=policy['scheduler_config'],config_sha256=policy['scheduler_config_sha256'],lease_count=2,waiter_count=1,
        sampled_coexistence=True,admission_guaranteed=False),
    current_record_count_assumed=False,current_full_claim_bytes_assumed=False,model_started=False,reservation_acquired=False,
    admission_guaranteed=False,continuous_coverage_claimed=False,shared_state_modified=False,full_record_bodies_published=False,
    default_promotion=False,training_authorized=False,root_identity_rebinds=0,claim_reconciliations=0,global_endpoint_body_reads=0,
    resource_API_calls=0,model_calls=0,checkpoint_JSON_parses=0)
fixture['artifacts']={item['path']:item for item in [fixture[key] for key in ('observer','source_qualification','input_manifest',
    'sampler_source_qualification','resource_bridge_source_qualification','fresh_metadata_check')]+[p.POLICY_PIN,p.KERNEL_PIN]}
per_root=[dict(path=row['path'],apparent_bytes=1,entry_count=1,symlink_count=0,special_file_count=0) for row in policy['counted_root_metadata']]
fixture['preadmission_full_claim_census']=dict(inventory=dict(apparent_bytes=4,entry_count=4,symlink_count=0,special_file_count=0),
    per_root_inventory=per_root,**p.capacity(policy,4,status['full_nonreleased_claim_bytes'],10**12))
check('public pure dynamic540 nonidle baseline passes',lambda:p.qualify_baseline(fixture))
def mutate(path,value):
    bad=copy.deepcopy(fixture);target=bad
    for key in path[:-1]:target=target[key]
    target[path[-1]]=value
    return lambda:p.qualify_baseline(bad)
check('public historical hash tampering refused',mutate(['baseline_ledger','record_body_hashes',next(iter(history))],'2'*64),True)
check('public uncharged additional claim refused',mutate(['baseline_ledger','full_nonreleased_claim_bytes'],44381777216),True)
check('public boolean count refused',mutate(['baseline_ledger','record_count'],True),True)
roots=copy.deepcopy(policy['counted_root_metadata']);roots[-1]['inode']+=1
check('public physical root change refused',mutate(['counted_root_metadata'],roots),True)
check('public numerical authorization flag refused',mutate(['training_authorized'],True),True)
check('public false pass refused',mutate(['passed'],False),True)
bad=copy.deepcopy(fixture);private=fake('private-runtime-snapshots/opening-v01/ledger.json');bad['artifacts'][private['path']]=private
check('private body artifact admission refused',lambda:p.qualify_baseline(bad),True)
bad=copy.deepcopy(fixture);bad['scheduler_observation']['config']['total_cpu_slots']=5
check('scheduler configuration mutation refused',lambda:p.qualify_baseline(bad),True)
bad=copy.deepcopy(fixture);bad['preadmission_full_claim_census'].update(p.capacity(policy,144700000000-44381777223,44381777223,10**12))
check('public native-only fit refused',lambda:p.qualify_baseline(bad),True)

old=Path('/home/barberb/lift_coding/artifacts/legal-balanced-execution-20261014-01')
for name in ('run_scope_guardian_v02.py','adopt_shared_scheduler_actor_ranking_v02.py','owned_lease_watchdog_actor_ranking_v02.py'):
    check('exact inherited bridge '+name,lambda name=name:p.require((F/name).read_bytes()==(old/name).read_bytes(),'bridge changed'))
check('sampler only four phase label substitutions',lambda:p.require((F/'sample_actor_refinement_private_resources_v01.py').read_bytes()
    ==(old/'sample_conditions_balanced_private_resources_v01.py').read_bytes().replace(b'conditions-balanced',b'actor-refinement'),'sampler drift'))
source=pin(Path(__file__).resolve());out=F/'actor-refinement-resource-author-controls-v01.json'
value=dict(schema='actor-refinement-resource-author-controls/v1',passed=True,findings=[],control_count=len(cases),controls=cases,
    observer=pin(F/'review_actor_refinement_resource_baseline_v01.py'),protocol=pin(F/'actor_refinement_resource_protocol_v01.py'),
    policy=p.POLICY_PIN,source=source,kernel=p.KERNEL_PIN,model_calls=0,numerical_imports=0,private_body_reads=0,
    resource_API_calls=0,actual_censuses=0,actual_baseline_main_calls=0,synthetic_fixture_gate_descriptors_are_not_actual_approvals=True)
with out.open('x') as f:json.dump(value,f,indent=2,sort_keys=True);f.write('\n');f.flush();os.fsync(f.fileno())
out.chmod(0o444);print(json.dumps(pin(out),sort_keys=True))
