"""One source-qualified copied-state observation and exact bounded native census."""
from datetime import datetime,timezone
import importlib.util
import os
from pathlib import Path
import shutil
import sys

F=Path(__file__).resolve().parent
sys.dont_write_bytecode=True
spec=importlib.util.spec_from_file_location('actor_refinement_resource_protocol',F/'actor_refinement_resource_protocol_v01.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
OUTPUT=F/'resource-baseline-v01.json'
REFUSAL=F/'capacity-refusal-v01.json'
INPUTS=F/'resource-baseline-inputs-v01.json'
QUALIFICATION=F/'resource-observer-source-independent-review-v01.json'


def main():
    p.require(sys.argv[1:]==[] and not any(os.path.lexists(path) for path in (OUTPUT,REFUSAL)),
        'argument-free exclusive single baseline/capacity-refusal observation required')
    m=p.Metadata(OUTPUT);sys.addaudithook(m.audit);own=m.pin(Path(__file__).resolve())
    approval=m.read(QUALIFICATION)
    p.require(approval['schema']=='actor-refinement-resource-observer-source-independent-review/v1'
        and approval['passed'] is True and approval['findings']==[] and approval['observer']==own,
        'exact independent observer source qualification required before private-copy parsing')
    for path,item in approval['artifacts'].items():m.pin(path,dict(path=path,**{key:item[key] for key in ('bytes','sha256')}))
    p.require(approval['protocol']==m.pin(F/'actor_refinement_resource_protocol_v01.py')
        and approval['policy']==p.POLICY_PIN,'qualified protocol/policy source closure required')
    inputs=m.read(INPUTS)
    p.require(set(inputs)=={'schema','policy','sample_receipt','check','sampler_qualification','bridge_qualification'}
        and inputs['schema']=='actor-refinement-resource-baseline-inputs/v1' and inputs['policy']==p.POLICY_PIN,
        'closed root-approved actual observation inputs required')
    for key,path in (('sample_receipt',None),('check',None),('sampler_qualification',F/'sampler-source-independent-review-v01.json'),
                     ('bridge_qualification',F/'resource-bridge-source-independent-review-v01.json')):
        p.require(p.full_descriptor(inputs[key],path),'full exact input descriptor required')
    policy=p.qualify_policy(m.read(p.POLICY,p.POLICY_PIN));m.pin(p.KERNEL_PIN['path'],p.KERNEL_PIN)
    baseline=m.read(policy['prior_baseline']['path'],policy['prior_baseline'])
    terminal=m.read(policy['prior_terminal']['path'],policy['prior_terminal'])
    reconciliation=m.read(policy['prior_root_identity_reconciliation']['path'],policy['prior_root_identity_reconciliation'])
    hashes=p.prior_hashes(policy,baseline,terminal,reconciliation)
    q=m.read(inputs['sampler_qualification']['path'],inputs['sampler_qualification'])
    p.require(q['schema']=='actor-refinement-sampler-source-independent-review/v1' and q['passed'] is True
        and q['findings']==[] and q['sampler']==policy['sampler'],'exact qualified sampler required')
    bridge=m.read(inputs['bridge_qualification']['path'],inputs['bridge_qualification'])
    p.require(bridge['schema']=='actor-refinement-resource-bridge-source-independent-review/v1'
        and bridge['passed'] is True and bridge['findings']==[] and bridge['guardian']==policy['guardian'],
        'exact immutable qualified guardian/helper bridge required')
    m.pin(policy['guardian']['path'],policy['guardian']);m.pin(policy['sampler']['path'],policy['sampler'])
    for path,item in policy['resource_producer_pins'].items():m.pin(path,dict(path=path,**item))
    receipt,ledger,state=p.snapshot(m,inputs['sample_receipt'],policy)
    status=p.qualify_ledger(policy,ledger,hashes)
    check=m.read(inputs['check']['path'],inputs['check']);scheduler=p.qualify_check(policy,check,receipt,state,status)
    helpers=p.census_helpers(m,policy);roots=[Path(row['path']) for row in policy['counted_root_metadata']]
    p.require([helpers['_root_identity'](root) for root in roots]==policy['counted_root_metadata']
        and helpers['_root_identity'](Path(policy['run_root']))==policy['run_root_identity'],
        'all four named current physical root identities and run root must remain exact')
    per_root=[]
    for root in roots:
        per_root.append(dict(path=str(root),**helpers['_inventory']([root])))
        p.require(sum(row['entry_count'] for row in per_root)<=policy['limits']['max_inventory_entries'],'combined fourroot2M census bound exceeded')
    inventory={key:sum(row[key] for row in per_root) for key in ('apparent_bytes','entry_count','symlink_count','special_file_count')}
    p.require([helpers['_root_identity'](root) for root in roots]==policy['counted_root_metadata']
        and helpers['_root_identity'](Path(policy['run_root']))==policy['run_root_identity'],'closing physical root identity changed')
    free=min(shutil.disk_usage(root).free for root in roots)
    cap=p.capacity(policy,inventory['apparent_bytes'],status['full_nonreleased_claim_bytes'],free)
    fits=cap['full_run_capacity_fits']
    if not fits:m.output=REFUSAL
    status.update(schema=ledger['schema'],limit_bytes=ledger['limit_bytes'],**receipt['ledger'])
    value=dict(schema='actor-refinement-resource-baseline/v1' if fits else 'actor-refinement-capacity-refusal/v1',
        passed=fits,findings=[] if fits else ['full-run actual fullclaim storage bound refused before any new claim or model'],
        observer=own,source_qualification=m.pin(QUALIFICATION),input_manifest=m.pin(INPUTS),observation_policy=p.POLICY_PIN,
        observed_at_utc=datetime.now(timezone.utc).isoformat(),baseline_ledger=status,
        historical_record_count=len(hashes),all_historical_record_bodies_unchanged=True,
        historical_record_body_hash_map_sha256=p.digest(hashes),current_record_count_assumed=False,current_full_claim_bytes_assumed=False,
        counted_root_metadata=policy['counted_root_metadata'],run_root_identity=policy['run_root_identity'],
        private_sample_receipt=inputs['sample_receipt'],fresh_metadata_check=inputs['check'],scheduler_observation=scheduler,
        adapted_sampler=policy['sampler'],sampler_source_qualification=inputs['sampler_qualification'],
        qualified_local_guardian=policy['guardian'],resource_bridge_source_qualification=inputs['bridge_qualification'],
        preadmission_full_claim_census=dict(inventory=inventory,per_root_inventory=per_root,**cap),
        prior_baseline=policy['prior_baseline'],prior_terminal=policy['prior_terminal'],
        prior_root_identity_reconciliation=policy['prior_root_identity_reconciliation'],
        artifacts={path:item for path,item in m.reads.items() if 'private-runtime-snapshots' not in Path(path).parts},
        model_started=False,reservation_acquired=False,admission_guaranteed=False,sampled_coexistence=True,
        continuous_coverage_claimed=False,shared_state_modified=False,root_identity_rebinds=0,claim_reconciliations=0,
        global_endpoint_body_reads=0,resource_API_calls=0,model_calls=0,checkpoint_JSON_parses=0,
        full_record_bodies_published=False,semantic_accuracy=None,default_promotion=False,training_authorized=False)
    print(m.write(value))


if __name__=='__main__':main()
