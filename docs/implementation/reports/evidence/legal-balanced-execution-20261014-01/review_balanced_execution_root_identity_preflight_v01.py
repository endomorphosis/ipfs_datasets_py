"""Read-only copied-state proof for a legitimate temporary-root identity rebind."""
from datetime import datetime,timezone
import hashlib
import importlib.util
import os
from pathlib import Path
import sys

F=Path(__file__).resolve().parent
HELPER=F/'balanced_execution_root_identity_v01.py'
HELPER_PIN=dict(path=str(HELPER),bytes=11831,sha256='a0ecd10daaac94605c07146307a89a6a63f526826f018b59cce15f86a898efc5')
sys.dont_write_bytecode=True
_raw=HELPER.read_bytes()
if len(_raw)!=HELPER_PIN['bytes'] or hashlib.sha256(_raw).hexdigest()!=HELPER_PIN['sha256']:raise ValueError('exact reviewed root identity helper required')
_spec=importlib.util.spec_from_file_location('qualified_balanced_root_identity',HELPER)
r=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(r)
OUTPUT=F/'root-identity-preflight-v01.json'
INPUTS=F/'root-identity-preflight-inputs-v01.json'
QUALIFICATION=F/'root-identity-preflight-source-independent-review-v01.json'


def main():
    r.require(sys.argv[1:]==[] and not os.path.lexists(OUTPUT),'exclusive argument-free preflight required')
    m=r.p.Metadata(OUTPUT);sys.addaudithook(m.audit)
    own=m.pin(Path(__file__).resolve());m.pin(HELPER,HELPER_PIN)
    q=m.read(QUALIFICATION)
    r.require(q['schema']=='conditions-balanced-root-identity-preflight-source-independent-review/v1'
        and q['passed'] is True and q['findings']==[] and q['observer']==own,'exact independent preflight source qualification required')
    for path,expected in q['artifacts'].items():m.pin(path,dict(path=path,**{key:expected[key] for key in ('bytes','sha256')}))
    inputs=m.read(INPUTS);ctx=r.qualify_opening(m,inputs)
    current=ctx['current'];status=ctx['status'];receipt=ctx['receipt']
    r.require(r.physical_roots(m,ctx['contract'])[0]==current,'stable current root identity required at preflight close')
    value=dict(schema='conditions-balanced-root-identity-preflight/v1',passed=True,findings=[],observer=own,source_qualification=m.pin(QUALIFICATION),
        helper=HELPER_PIN,input_manifest=m.pin(INPUTS),observed_at_utc=datetime.now(timezone.utc).isoformat(),historical_resource_contract=r.p.CONTRACT_PIN,
        prior_baseline=r.BASELINE_PIN,private_sample_receipt=inputs['sample_receipt'],fresh_metadata_check=inputs['check'],
        sampler_source_qualification=inputs['sampler_qualification'],resource_bridge_source_qualification=inputs['bridge_qualification'],
        historical_roots=ctx['contract']['counted_root_metadata'],ledger_roots_before=ctx['ledger']['roots'],physical_roots=current,
        temporary_root_metadata=ctx['temporary'],expected_roots_after=current,migration_needed=ctx['needed'],
        expected_live_ledger_before=dict(path=str(r.LEDGER),bytes=receipt['ledger']['bytes'],sha256=receipt['ledger']['sha256']),
        ledger_record_count=status['record_count'],record_status_counts=status['record_status_counts'],
        record_body_hash_map_sha256=status['record_body_hash_map_sha256'],full_nonreleased_claim_bytes=status['full_nonreleased_claim_bytes'],
        all538_prior_record_bodies_unchanged=True,all_three_persistent_root_identities_unchanged=True,
        scheduler_observation=ctx['scheduler'],qualified_resource_owner=r.OWNER_PIN,
        migration_plan_concrete=True,migration_authorized=False,migration_executed=False,
        proposed_mutation='only top-level ledger.roots temporary directory identity' if ctx['needed'] else 'no ledger mutation; root metadata already current',
        private_before_backup_required=True,lock_held_full538_fence_required=True,atomic_native_write_required=True,
        cap_bytes=145000000000,cap_changed=False,claim_status_changes=0,claims_created=0,outputs_deleted=False,
        current_root_created=False,scheduler_configuration_changed=False,scheduler_occupancy_changed=False,
        model_started=False,reservation_acquired=False,resource_API_calls=0,global_endpoint_body_reads=0,
        copied_endpoint_bodies_read=2,actual_tree_censuses=0,checkpoint_JSON_parses=0,training_authorized=False,
        private_record_bodies_published=False,continuous_coverage_claimed=False,admission_guaranteed=False,
        artifacts={path:descriptor for path,descriptor in m.reads.items() if 'private-runtime-snapshots' not in Path(path).parts})
    print(m.write(value))

if __name__=='__main__':main()
