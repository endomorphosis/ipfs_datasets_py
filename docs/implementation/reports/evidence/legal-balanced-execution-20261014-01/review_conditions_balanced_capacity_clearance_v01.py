"""Require current538 conservation and conservative full-run storage headroom before any claim or model."""
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
OUTPUT=F/'capacity-clearance-v01.json'
INPUTS=F/'capacity-clearance-inputs-v01.json'
QUALIFICATION=F/'capacity-clearance-source-independent-review-v01.json'


def main():
    p.require(sys.argv[1:]==[] and not os.path.lexists(OUTPUT),'exclusive argument-free capacity clearance required')
    m=p.Metadata(OUTPUT);sys.addaudithook(m.audit);own=m.pin(Path(__file__).resolve())
    approval=m.read(QUALIFICATION)
    p.require(approval['schema']=='conditions-balanced-capacity-clearance-source-independent-review/v1' and approval['passed'] is True
        and approval['findings']==[] and approval['observer']==own,'exact independent capacity-clearance source qualification required')
    for path,expected in approval['artifacts'].items():m.pin(path,dict(path=path,**{k:expected[k] for k in ('bytes','sha256')}))
    inputs=m.read(INPUTS);contract_pin=inputs['contract']
    p.require(p.full_descriptor(contract_pin,p.CONTRACT),'exact full F14 contract descriptor required')
    contract=p.qualify_contract(m.read(p.CONTRACT,contract_pin));rebind,rebind_summary=p.qualify_rebind(m,contract)
    p.require(set(inputs)=={'schema','contract','baseline','sample_receipt','check','sampler_qualification','bridge_qualification'}
        and inputs['schema']=='conditions-balanced-capacity-clearance-inputs/v1' and inputs['contract']==contract_pin,'closed root-approved input manifest required')
    expected_baseline=inputs['baseline']
    p.require(p.full_descriptor(expected_baseline,F/'resource-baseline-v01.json'),'actual qualified F14 baseline full descriptor required')
    p.require(inputs['baseline']==expected_baseline,'exact immutable original baseline required')
    original=m.read(expected_baseline['path'],expected_baseline);p.qualify_execution_baseline(original)
    p.require(original['schema']=='conditions-balanced-resource-baseline/v1' and original['passed'] is True and original['findings']==[]
        and original['baseline_ledger']['record_count']==538 and original['baseline_ledger']['record_body_hash_map_sha256']==contract['prior_record_body_hash_map_sha256'],
        'qualified conserved538 original baseline required')
    baseline=m.read(contract['prior_baseline']['path'],contract['prior_baseline']);terminal=m.read(contract['prior_terminal']['path'],contract['prior_terminal'])
    hashes=p.prior_hashes(contract,baseline,terminal)
    for key in ('prior_final','prior_HF_actual'):m.pin(contract[key]['path'],contract[key])
    receipt,ledger,state=p.snapshot(m,inputs['sample_receipt'],'opening',contract)
    p.require(inputs['sample_receipt']!=original['private_sample_receipt'] and inputs['check']!=original['fresh_metadata_check'],'one fresh opening/check required after immutable actual baseline')
    status=p.qualify_ledger(contract,ledger,hashes)
    p.require(status['record_body_hashes']==original['baseline_ledger']['record_body_hashes'],'all original538 bodies must still be exact')
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
    future_bound=requested
    free=min(shutil.disk_usage(root).free for root in roots)
    native_charged=inventory['apparent_bytes']+claims+requested
    full_run_charged=native_charged+future_bound
    required_free=claims+requested+future_bound
    fits=full_run_charged<=contract['global_cap_bytes'] and free>=required_free
    value=dict(schema='conditions-balanced-capacity-clearance/v1',passed=fits,
        findings=[] if fits else ['conservative full-run storage headroom refused before any claim or model'],
        cell=contract['cell'],attempt_name=contract['attempt_name'],observer=own,source_qualification=m.pin(QUALIFICATION),
        input_manifest=m.pin(INPUTS),resource_contract=contract_pin,root_identity_reconciliation=contract['root_identity_reconciliation'],
        root_identity_reconciliation_summary=rebind_summary,baseline=expected_baseline,
        observed_at_utc=datetime.now(timezone.utc).isoformat(),private_sample_receipt=inputs['sample_receipt'],fresh_metadata_check=inputs['check'],
        ledger_record_count=status['record_count'],record_status_counts=status['record_status_counts'],
        prior_record_body_hash_map_sha256=status['record_body_hash_map_sha256'],all538_prior_record_bodies_unchanged=True,
        observed_apparent_bytes=inventory['apparent_bytes'],outstanding_full_reservations_bytes=claims,additional_requested_bytes=requested,
        future_own_output_bound_bytes=future_bound,native_charged_bytes=native_charged,full_run_charged_bound_bytes=full_run_charged,
        limit_bytes=contract['global_cap_bytes'],minimum_filesystem_free_bytes=free,required_filesystem_free_bound_bytes=required_free,
        full_run_apparent_headroom_bytes=contract['global_cap_bytes']-full_run_charged,
        full_run_physical_headroom_bytes=free-required_free,full_run_capacity_fits=fits,
        native_capacity_fits=native_charged<=contract['global_cap_bytes'] and free>=claims+requested,
        inventory=inventory,per_root_inventory=per_root,counted_root_metadata=contract['counted_root_metadata'],run_root_identity=contract['run_root_identity'],
        scheduler_observation=scheduler,all_ten_resource_producer_pins_unchanged=True,
        qualified_local_guardian=contract['guardian'],adapted_sampler=contract['sampler'],sampler_source_qualification=inputs['sampler_qualification'],
        resource_bridge_source_qualification=inputs['bridge_qualification'],existing_baseline_modified=False,new_baseline_created=False,
        model_started=False,reservation_acquired=False,resource_API_calls=0,shared_state_modified=False,
        global_endpoint_body_reads=0,checkpoint_JSON_parses=0,private_record_bodies_published=False,
        continuous_coverage_claimed=False,admission_guaranteed=False,
        future_output_bound_is_an_additional_claim=False,cap_or_claim_budget_changed=False,
        artifacts={path:descriptor for path,descriptor in m.reads.items() if 'private-runtime-snapshots' not in Path(path).parts})
    print(m.write(value))

if __name__=='__main__':main()
