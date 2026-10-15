"""Qualify exact current538 copied bodies and one bounded pre-admission metadata census."""
from datetime import datetime,timezone
import importlib.util
import os
from pathlib import Path
import shutil
import sys

F=Path(__file__).resolve().parent
sys.dont_write_bytecode=True
spec=importlib.util.spec_from_file_location('conditions_resource_protocol',F/'conditions_balanced_resource_protocol_v01.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
OUTPUT=F/'resource-baseline-v01.json'
INPUTS=F/'resource-baseline-inputs-v01.json'
QUALIFICATION=F/'resource-observer-source-independent-review-v01.json'


def main():
    p.require(sys.argv[1:]==[] and not os.path.lexists(OUTPUT),'exclusive argument-free baseline required')
    m=p.Metadata(OUTPUT);sys.addaudithook(m.audit);own=m.pin(Path(__file__).resolve())
    approval=m.read(QUALIFICATION)
    p.require(approval['schema']=='conditions-balanced-resource-observer-source-independent-review/v1' and approval['passed'] is True
        and approval['findings']==[] and approval['observer']==own,'exact independent baseline source qualification required')
    for path,expected in approval['artifacts'].items():m.pin(path,dict(path=path,**{k:expected[k] for k in ('bytes','sha256')}))
    inputs=m.read(INPUTS);contract_pin=inputs['contract']
    p.require(p.full_descriptor(contract_pin,p.CONTRACT),'exact full F14 contract descriptor required')
    contract=p.qualify_contract(m.read(p.CONTRACT,contract_pin));rebind,rebind_summary=p.qualify_rebind(m,contract)
    p.require(set(inputs)=={'schema','contract','sample_receipt','check','sampler_qualification','bridge_qualification'}
        and inputs['schema']=='conditions-balanced-resource-baseline-inputs/v1' and inputs['contract']==contract_pin,'closed root-approved input manifest required')
    baseline=m.read(contract['prior_baseline']['path'],contract['prior_baseline']);terminal=m.read(contract['prior_terminal']['path'],contract['prior_terminal'])
    hashes=p.prior_hashes(contract,baseline,terminal)
    for key in ('prior_final','prior_HF_actual'):m.pin(contract[key]['path'],contract[key])
    receipt,ledger,state=p.snapshot(m,inputs['sample_receipt'],'opening',contract)
    status=p.qualify_ledger(contract,ledger,hashes)
    check=m.read(inputs['check']['path'],inputs['check']);scheduler=p.qualify_check(contract,check,receipt,state)
    q=m.read(inputs['sampler_qualification']['path'],inputs['sampler_qualification'])
    p.require(q['schema']=='conditions-balanced-sampler-source-independent-review/v1' and q['passed'] is True and q['findings']==[]
        and q['sampler']==contract['sampler'],'exact qualified sampler required')
    bridge=m.read(inputs['bridge_qualification']['path'],inputs['bridge_qualification'])
    p.require(bridge['passed'] is True and bridge['findings']==[],'same qualified bytecopy resource bridge required')
    m.pin(contract['guardian']['path'],contract['guardian']);m.pin(contract['sampler']['path'],contract['sampler'])
    for path,brief in contract['resource_producer_pins'].items():
        pin=m.pin(path,dict(path=path,**brief));p.require(check['producers'][path]==pin,'fixed ten raw producer pins must match actual check')
    helpers=p.census_helpers(m,contract);roots=[Path(row['path']) for row in contract['counted_root_metadata']]
    p.require([helpers['_root_identity'](root) for root in roots]==contract['counted_root_metadata']
        and helpers['_root_identity'](Path(contract['run_root']))==contract['run_root_identity'],'named root identities changed')
    per_root=[]
    for root in roots:
        item=helpers['_inventory']([root]);per_root.append(dict(path=str(root),**item))
        p.require(sum(row['entry_count'] for row in per_root)<=contract['limits']['max_inventory_entries'],'combined fourroot2M inventory bound exceeded')
    inventory={key:sum(row[key] for row in per_root) for key in ('apparent_bytes','entry_count','symlink_count','special_file_count')}
    p.require([helpers['_root_identity'](root) for root in roots]==contract['counted_root_metadata'],'closing counted-root identity changed')
    claims=status['full_nonreleased_claim_bytes'];requested=contract['resources']['storage_bytes']
    free=min(shutil.disk_usage(root).free for root in roots);charged=inventory['apparent_bytes']+claims+requested
    if charged>contract['global_cap_bytes'] or free<claims+requested:
        m.output=F/'capacity-refusal-v01.json'
        p.require(not os.path.lexists(m.output),'exclusive capacity refusal receipt required')
        refusal=dict(schema='conditions-balanced-capacity-refusal/v1',passed=False,findings=['actual storage capacity predicate refused before any claim or model'],
            observer=own,source_qualification=m.pin(QUALIFICATION),input_manifest=m.pin(INPUTS),resource_contract=contract_pin,root_identity_reconciliation=contract['root_identity_reconciliation'],
        root_identity_reconciliation_summary=rebind_summary,
            private_sample_receipt=inputs['sample_receipt'],fresh_metadata_check=inputs['check'],
            observed_apparent_bytes=inventory['apparent_bytes'],outstanding_full_reservations_bytes=claims,additional_requested_bytes=requested,
            charged_bytes=charged,limit_bytes=contract['global_cap_bytes'],minimum_filesystem_free_bytes=free,
            apparent_capacity_headroom_bytes=contract['global_cap_bytes']-charged,physical_capacity_headroom_bytes=free-claims-requested,
            apparent_capacity_exceeded=charged>contract['global_cap_bytes'],physical_capacity_insufficient=free<claims+requested,
            inventory=inventory,per_root_inventory=per_root,all538_prior_record_bodies_unchanged=True,
            prior_record_body_hash_map_sha256=status['record_body_hash_map_sha256'],all_ten_resource_producer_pins_unchanged=True,
            model_started=False,reservation_acquired=False,resource_API_calls=0,shared_state_modified=False,baseline_created=False,
            private_record_bodies_published=False,artifacts={path:descriptor for path,descriptor in m.reads.items() if 'private-runtime-snapshots' not in Path(path).parts})
        print(m.write(refusal));return

    status.update(schema=ledger['schema'],limit_bytes=ledger['limit_bytes'],path=receipt['ledger']['path'],bytes=receipt['ledger']['bytes'],sha256=receipt['ledger']['sha256'])
    value=dict(schema='conditions-balanced-resource-baseline/v1',passed=True,findings=[],observer=own,source_qualification=m.pin(QUALIFICATION),
        input_manifest=m.pin(INPUTS),resource_contract=contract_pin,root_identity_reconciliation=contract['root_identity_reconciliation'],
        root_identity_reconciliation_summary=rebind_summary,observed_at_utc=datetime.now(timezone.utc).isoformat(),
        baseline_ledger=status,counted_root_metadata=contract['counted_root_metadata'],run_root_identity=contract['run_root_identity'],
        private_sample_receipt=inputs['sample_receipt'],fresh_metadata_check=inputs['check'],scheduler_observation=scheduler,
        adapted_sampler=contract['sampler'],sampler_source_qualification=inputs['sampler_qualification'],qualified_local_guardian=contract['guardian'],
        resource_bridge_source_qualification=inputs['bridge_qualification'],
        preadmission_full_claim_census=dict(inventory=inventory,per_root_inventory=per_root,observed_apparent_bytes=inventory['apparent_bytes'],outstanding_full_reservations_bytes=claims,
            additional_requested_bytes=requested,charged_bytes=charged,minimum_filesystem_free_bytes=free,limit_bytes=contract['global_cap_bytes'],admission_guaranteed=False),
        prior_baseline=contract['prior_baseline'],prior_terminal=contract['prior_terminal'],sampled_coexistence=True,continuous_coverage_claimed=False,
        artifacts={path:descriptor for path,descriptor in m.reads.items() if 'private-runtime-snapshots' not in Path(path).parts},
        global_endpoint_body_reads=0,resource_API_calls=0,model_calls=0,checkpoint_JSON_parses=0,shared_state_modified=False,claim_reconciliations=0,
        full_record_bodies_published=False,semantic_accuracy=None,default_promotion=False)
    print(m.write(value))

if __name__=='__main__':main()
