"""One explicitly gated, lock-held roots-only ledger-envelope migration; no reservation or scheduler admission."""
import copy
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
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
OUTPUT=F/'root-identity-reconciliation-v01.json'
QUALIFICATION=F/'root-identity-reconciliation-source-independent-review-v01.json'
EXECUTION_GATE=F/'root-identity-reconciliation-execution-approval-v01.json'


def main():
    r.require(sys.argv[1:]==[] and not os.path.lexists(OUTPUT),'exclusive argument-free reconciliation required')
    m=r.p.Metadata(OUTPUT);own=m.pin(Path(__file__).resolve());m.pin(HELPER,HELPER_PIN)
    q=m.read(QUALIFICATION)
    r.require(q['schema']=='conditions-balanced-root-identity-reconciliation-source-independent-review/v1'
        and q['passed'] is True and q['findings']==[] and q['observer']==own,'exact independently qualified mutation source required')
    for path,expected in q['artifacts'].items():m.pin(path,dict(path=path,**{key:expected[key] for key in ('bytes','sha256')}))
    gate=m.read(EXECUTION_GATE)
    r.require(gate['schema']=='conditions-balanced-root-identity-reconciliation-execution-approval/v1'
        and gate['passed'] is True and gate['findings']==[] and gate['observer']==own and gate['source_qualification']==m.pin(QUALIFICATION)
        and gate['authorize_roots_only_identity_rebind'] is True
        and all(gate[key] is False for key in ('claim_mutation_authorized','cap_increase_authorized','outputs_deletion_authorized','scheduler_mutation_authorized')),
        'root must bind exact concrete preflight after independent source review')
    preflight=m.read(gate['preflight']['path'],gate['preflight'])
    r.require(gate['preflight']['path']==str(F/'root-identity-preflight-v01.json')
        and preflight['schema']=='conditions-balanced-root-identity-preflight/v1' and preflight['passed'] is True and preflight['findings']==[]
        and preflight['migration_plan_concrete'] is True and preflight['migration_authorized'] is preflight['migration_executed'] is False
        and preflight['prior_baseline']==r.BASELINE_PIN and preflight['historical_resource_contract']==r.p.CONTRACT_PIN
        and preflight['qualified_resource_owner']==r.OWNER_PIN and preflight['helper']==HELPER_PIN
        and preflight['all538_prior_record_bodies_unchanged'] is True and preflight['ledger_record_count']==538
        and preflight['full_nonreleased_claim_bytes']==44381777216,'exact actual read-only538 preflight required')
    source_q=m.read(preflight['source_qualification']['path'],preflight['source_qualification'])
    r.require(source_q['schema']=='conditions-balanced-root-identity-preflight-source-independent-review/v1'
        and source_q['passed'] is True and source_q['findings']==[] and source_q['observer']==preflight['observer'],'actual preflight source gate differs')
    m.pin(preflight['observer']['path'],preflight['observer'])
    contract,effective,baseline,hashes=r.prior_context(m)
    current,_=r.physical_roots(m,contract)
    r.require(current==preflight['physical_roots']==preflight['expected_roots_after']
        and preflight['record_body_hash_map_sha256']==r.digest(hashes)
        and preflight['historical_roots']==contract['counted_root_metadata'],'physical roots and old map must match approved actual preflight')
    native=r.native_owner(m)
    owner=native.DaemonResourceReservation(r.LEDGER,roots=[row['path'] for row in current],storage_bytes=200000000,
        memory_mb=1536,cpu_slots=2,child_process_slots=1,timeout_seconds=0,ledger_lock_timeout_seconds=60)
    backup=None;writes=0
    m.fence()
    with owner._locked():
        raw,before,opening_pin=r.read_locked_raw(native,owner)
        r.require(opening_pin==preflight['expected_live_ledger_before'] and before['roots']==preflight['ledger_roots_before'],
            'same-lock exact preflight ledger bytes and root envelope required')
        status,needed=r.qualify_ledger_roots(contract,before,hashes,current)
        r.require(needed is preflight['migration_needed'] and r.physical_roots(m,contract)[0]==current,'same-lock root plan drift')
        after=copy.deepcopy(before);after['roots']=copy.deepcopy(current)
        r.qualify_transition(before,after,contract,hashes,current)
        if needed:
            backup=r.durable_backup(raw)
            m.fence()
            raw_again,value_again,pin_again=r.read_locked_raw(native,owner)
            r.require(raw_again==raw and value_again==before and pin_again==opening_pin,'exact locked ledger drift before native atomic write')
            r.require(r.physical_roots(m,contract)[0]==current,'root drift before native atomic write')
            owner._write(after);writes=1
        verified=owner._read()
        closing_status=r.qualify_transition(before,verified,contract,hashes,current)
        closing_raw,closing_value,closing_pin=r.read_locked_raw(native,owner)
        r.require(closing_value==verified==after and r.physical_roots(m,contract)[0]==current,'native strict read-after and physical roots must agree')
    value=dict(schema='conditions-balanced-root-identity-reconciliation/v1',passed=True,findings=[],observer=own,source_qualification=m.pin(QUALIFICATION),
        execution_approval=m.pin(EXECUTION_GATE),preflight=gate['preflight'],helper=HELPER_PIN,prior_baseline=r.BASELINE_PIN,
        historical_resource_contract=r.p.CONTRACT_PIN,qualified_resource_owner=r.OWNER_PIN,observed_at_utc=datetime.now(timezone.utc).isoformat(),
        roots_before=before['roots'],roots_after=current,temporary_root_metadata=preflight['temporary_root_metadata'],
        ledger_before=opening_pin,ledger_after=closing_pin,private_exact_before_backup=backup,
        root_identity_changed=needed,atomic_native_ledger_writes=writes,native_strict_read_after_passed=True,
        opening_record_count=status['record_count'],closing_record_count=closing_status['record_count'],
        record_status_counts=closing_status['record_status_counts'],record_body_hash_map_sha256=closing_status['record_body_hash_map_sha256'],
        all538_record_bodies_unchanged=True,all_three_persistent_root_identities_unchanged=True,full_nonreleased_claim_bytes=44381777216,
        cap_bytes=145000000000,cap_changed=False,claim_status_changes=0,claims_created=0,claims_released=0,outputs_deleted=False,
        scheduler_configuration_changed=False,scheduler_occupancy_changed=False,resource_reservation_enter_called=False,
        scheduler_admission_called=False,original_owner_private_attributes_modified=False,global_classes_or_modules_patched=False,
        native_function_and_class_AST_preserved=True,scheduler_binding_disabled_fail_closed=True,
        current_root_created=False,model_started=False,checkpoint_JSON_parses=0,actual_tree_censuses=0,
        training_authorized=False,fresh_postwrite_capacity_observation_required=True,private_record_bodies_published=False,
        artifacts={path:descriptor for path,descriptor in m.reads.items() if 'private-runtime-snapshots' not in Path(path).parts})
    print(m.write(value))

if __name__=='__main__':main()
