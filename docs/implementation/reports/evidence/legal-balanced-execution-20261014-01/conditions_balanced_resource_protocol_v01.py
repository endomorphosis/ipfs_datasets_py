"""F14 resource metadata predicates with explicit roots-only reconciliation provenance."""
import copy
import hashlib
import importlib.util
from pathlib import Path
import sys
import stat

F=Path(__file__).resolve().parent
HELPER=F/'balanced_execution_root_identity_v01.py'
HELPER_PIN=dict(path=str(HELPER),bytes=11831,sha256='a0ecd10daaac94605c07146307a89a6a63f526826f018b59cce15f86a898efc5')
sys.dont_write_bytecode=True
_raw=HELPER.read_bytes()
if len(_raw)!=HELPER_PIN['bytes'] or hashlib.sha256(_raw).hexdigest()!=HELPER_PIN['sha256']:raise ValueError('exact root identity helper source required')
_spec=importlib.util.spec_from_file_location('qualified_f14_resource_identity',HELPER)
r=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(r)
p=r.p
require=p.require
digest=p.digest
Metadata=p.Metadata
LEDGER=p.LEDGER
SCHEDULER=p.SCHEDULER
CONTRACT=F/'resource-protocol-contract-v01.json'
INVARIANT_KEYS=('admission_guaranteed', 'attempt_name', 'baseline_filename', 'body_change_authorized', 'cell', 'claim_reconciliation_authorized', 'continuous_coverage_claimed', 'expected_closing_record_count', 'expected_closing_record_status_counts', 'foreign_mutation_authorized', 'global_cap_bytes', 'limits', 'max_new_claims', 'plan_filename', 'prior_HF_actual', 'prior_baseline', 'prior_final', 'prior_full_nonreleased_claim_bytes', 'prior_record_body_hash_map_sha256', 'prior_record_count', 'prior_record_status_counts', 'prior_terminal', 'required_preserved_claims', 'resources', 'review_schema', 'run_root', 'run_root_identity', 'scheduler_config', 'scheduler_config_sha256', 'schema', 'terminal_inputs_filename', 'terminal_output_filename', 'training_review_filename')
INVARIANT_SHA256='14250339b8bc7b2ce0f191950d7a5d92121285e266f9c48973159856ce529ba1'
HISTORICAL_ROOTS=[{'device': 66306, 'inode': 66764317, 'path': '/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs'}, {'device': 66306, 'inode': 58092485, 'path': '/home/barberb/lift_coding/external/ipfs_datasets/workspace/todo-queues'}, {'device': 66306, 'inode': 51016937, 'path': '/home/barberb/lift_coding/external/ipfs_datasets/docs/implementation/reports/evidence'}, {'device': 66306, 'inode': 524352, 'path': '/tmp/pytest-of-barberb'}]
PRODUCER_PINS={'/home/barberb/lift_coding/artifacts/legal-balanced-execution-20261014-01/adopt_shared_scheduler_actor_ranking_v02.py': {'bytes': 15101, 'sha256': '526aa9fa55d955eb92dba37053af2dfdf01f7dd8335cd309cb36770988bab0b7'}, '/home/barberb/lift_coding/artifacts/legal-balanced-execution-20261014-01/owned_lease_watchdog_actor_ranking_v02.py': {'bytes': 24435, 'sha256': '6355884b6737c5b0e5cd1a128ad70a09fcf304f27bbf32492a15d8dbe070b032'}, '/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/decoder-normative-wording-r2-20261006/lazy_scheduler_adoption.py': {'bytes': 1345, 'sha256': '42f31d8da1eb5b44274ca0b8c8180cd78bc083dfd0e93438e61f38223929d84a'}, '/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/native4096-four-width-20261004/resource-cap/autoencoder_daemon_resources.py': {'bytes': 36724, 'sha256': 'b00d2752ba852fe73760bba4fbd51b0e845742c3527642606a2a77ed9f8f5e2c'}, '/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/ui-modal-coverage-20261002/validation-source-r2/ipfs_datasets_py/__init__.py': {'bytes': 56829, 'sha256': 'f258f8eada774251feacd8e2ee2048efe56c89a8ee88efd50e4271ea41d43dc9'}, '/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/ui-modal-coverage-20261002/validation-source-r2/ipfs_datasets_py/optimizers/__init__.py': {'bytes': 957, 'sha256': 'a12bab3724da07be67b447719ace42fc1f480cb5635581f320a99a372f02f450'}, '/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/ui-modal-coverage-20261002/validation-source-r2/ipfs_datasets_py/optimizers/logic_theorem_optimizer/__init__.py': {'bytes': 69336, 'sha256': '9d693fa576f00dc36899faad75ef3044c437e2bfec5c62306f7031236725bb0e'}, '/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/ui-modal-coverage-20261002/validation-source-r2/ipfs_datasets_py/optimizers/logic_theorem_optimizer/proof_resource_safety.py': {'bytes': 4534, 'sha256': '23569b40b44d9130c30c62be564d58908a509fb1f40c6377e89f2fc1e3c799c5'}, '/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/ui-modal-coverage-20261002/validation-source-r2/ipfs_datasets_py/optimizers/logic_theorem_optimizer/resource_scheduler.py': {'bytes': 82754, 'sha256': 'a418e84f70ed8509ba0518feea69e7a8c27865139f83b6c81349eefdfd5893a4'}, '/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/ui-modal-coverage-20261002/validation-source-r2/ipfs_datasets_py/optimizers/logic_theorem_optimizer/runtime_telemetry.py': {'bytes': 53075, 'sha256': '542f705867b93fcb138a117e1f5c97a144ad6635dc92c37bc5034eee5065ef63'}}
GUARDIAN_PIN={'bytes': 38449, 'path': '/home/barberb/lift_coding/artifacts/legal-balanced-execution-20261014-01/run_scope_guardian_v02.py', 'sha256': 'b4811b7b24f584d5cb0f7c921451a234a3e0d84b2d7507e015426e258134c2db'}
SAMPLER_PIN={'bytes': 6681, 'path': '/home/barberb/lift_coding/artifacts/legal-balanced-execution-20261014-01/sample_conditions_balanced_private_resources_v01.py', 'sha256': 'ba8990d2c7ccc5461d98269ac09a3f920d17b490e82021e71d474096daa6847f'}


def full_descriptor(value,path=None):
    return type(value) is dict and set(value)=={'path','bytes','sha256'} and type(value['path']) is str and Path(value['path']).is_absolute() \
        and type(value['bytes']) is int and 0<value['bytes']<=16*1024*1024 and type(value['sha256']) is str and len(value['sha256'])==64 \
        and all(ch in '0123456789abcdef' for ch in value['sha256']) and (path is None or value['path']==str(path))


def current_root_metadata(roots):
    require(type(roots) is list and len(roots)==4 and roots[:3]==HISTORICAL_ROOTS[:3]
        and type(roots[3]) is dict and set(roots[3])=={'path','device','inode'}
        and roots[3]['path']==HISTORICAL_ROOTS[3]['path'] and roots[3]['device']==HISTORICAL_ROOTS[3]['device']
        and type(roots[3]['inode']) is int and roots[3]['inode']>0,'same four named roots and three persistent physical identities required')
    return roots


def qualify_reconciliation(proof):
    require(proof['schema']=='conditions-balanced-root-identity-reconciliation/v1' and proof['passed'] is True and proof['findings']==[]
        and proof['prior_baseline']==r.BASELINE_PIN and proof['historical_resource_contract']==p.CONTRACT_PIN
        and proof['qualified_resource_owner']==r.OWNER_PIN and proof['helper']==HELPER_PIN
        and full_descriptor(proof['observer'],F/'reconcile_balanced_execution_root_identity_v01.py')
        and proof['opening_record_count']==proof['closing_record_count']==538
        and proof['record_status_counts']=={'released':437,'retained':101}
        and proof['record_body_hash_map_sha256']=='b3c68c6a50aa564532be42134e3d803a2ee25ecf48ff1f55034dcaa6ce032df3'
        and proof['all538_record_bodies_unchanged'] is proof['all_three_persistent_root_identities_unchanged'] is proof['native_strict_read_after_passed'] is True
        and proof['full_nonreleased_claim_bytes']==44381777216 and proof['cap_bytes']==145000000000
        and proof['native_function_and_class_AST_preserved'] is proof['scheduler_binding_disabled_fail_closed'] is proof['fresh_postwrite_capacity_observation_required'] is True,
        'concrete unchanged538 native strict-read-after reconciliation required')
    current_root_metadata(proof['roots_after'])
    temporary=proof['temporary_root_metadata']
    require({key:temporary[key] for key in ('path','device','inode')}==proof['roots_after'][3]
        and temporary['uid']==1000 and temporary['mode']=='0o700','qualified real temporary root metadata required')
    require(proof['roots_before'] in (HISTORICAL_ROOTS,proof['roots_after'])
        and type(proof['root_identity_changed']) is bool and proof['root_identity_changed']==(proof['roots_before']!=proof['roots_after'])
        and proof['atomic_native_ledger_writes']==int(proof['root_identity_changed'])
        and all(proof[key] is False for key in ('cap_changed','outputs_deleted','scheduler_configuration_changed','scheduler_occupancy_changed',
            'resource_reservation_enter_called','scheduler_admission_called','original_owner_private_attributes_modified',
            'global_classes_or_modules_patched','current_root_created','model_started','training_authorized'))
        and all(proof[key]==0 for key in ('claim_status_changes','claims_created','claims_released','checkpoint_JSON_parses','actual_tree_censuses')),
        'only roots identity bookkeeping and no claim/scheduler/model mutation allowed')
    if proof['root_identity_changed']:
        backup=proof['private_exact_before_backup']
        require(backup['path']==str(F/'private-root-identity-rebind-v01/ledger-before.json')
            and all(backup[key]==proof['ledger_before'][key] for key in ('bytes','sha256'))
            and backup['mode']=='0o400' and backup['file_fsynced'] is backup['directory_fsynced'] is True,
            'exact private durable before-ledger backup required')
    else:require(proof['private_exact_before_backup'] is None,'no rewrite or backup claimed for already-current roots')
    for key,name in (('source_qualification','root-identity-reconciliation-source-independent-review-v01.json'),
                     ('execution_approval','root-identity-reconciliation-execution-approval-v01.json'),('preflight','root-identity-preflight-v01.json')):
        require(full_descriptor(proof[key],F/name),'exact F14 reconciliation custody descriptors required')
    return {key:proof[key] for key in ('root_identity_changed','atomic_native_ledger_writes','native_strict_read_after_passed',
        'all538_record_bodies_unchanged','record_body_hash_map_sha256','full_nonreleased_claim_bytes','roots_after','cap_bytes','cap_changed')}


def qualify_contract(contract):
    mutable={'phase_root','guardian','sampler','resource_producer_pins','counted_root_metadata'}
    extra={'historical_resource_contract','historical_baseline','root_identity_reconciliation'}
    require(set(contract)==set(INVARIANT_KEYS)|mutable|extra and digest({key:contract[key] for key in INVARIANT_KEYS})==INVARIANT_SHA256
        and contract['phase_root']==str(F) and contract['guardian']==GUARDIAN_PIN and contract['sampler']==SAMPLER_PIN
        and contract['resource_producer_pins']==PRODUCER_PINS
        and contract['historical_resource_contract']==p.CONTRACT_PIN and contract['historical_baseline']==r.BASELINE_PIN
        and full_descriptor(contract['root_identity_reconciliation'],F/'root-identity-reconciliation-v01.json'),
        'closed unchanged resource contract plus exact F14 root identity provenance required')
    current_root_metadata(contract['counted_root_metadata']);return contract


def qualify_rebind(metadata,contract):
    descriptor=contract['root_identity_reconciliation']
    proof=metadata.read(descriptor['path'],descriptor);summary=qualify_reconciliation(proof)
    require(proof['roots_after']==contract['counted_root_metadata'],'contract must name actual reconciled physical roots')
    for key,schema in (('source_qualification','conditions-balanced-root-identity-reconciliation-source-independent-review/v1'),
                       ('execution_approval','conditions-balanced-root-identity-reconciliation-execution-approval/v1'),
                       ('preflight','conditions-balanced-root-identity-preflight/v1')):
        item=proof[key];value=metadata.read(item['path'],item)
        require(value['schema']==schema and value['passed'] is True and value['findings']==[],'all concrete root identity custody gates must pass')
        if key=='source_qualification':
            require(value['observer']==proof['observer'],'exact mutation source custody required')
            for path,item in value['artifacts'].items():metadata.pin(path,dict(path=path,**{field:item[field] for field in ('bytes','sha256')}))
        if key=='execution_approval':require(value['observer']==proof['observer'] and value['preflight']==proof['preflight']
            and value['source_qualification']==proof['source_qualification'] and value['authorize_roots_only_identity_rebind'] is True
            and all(value[field] is False for field in ('claim_mutation_authorized','cap_increase_authorized','outputs_deletion_authorized','scheduler_mutation_authorized')),
            'exact concrete roots-only execution approval required')
        if key=='preflight':
            require(value['physical_roots']==proof['roots_after'] and value['ledger_roots_before']==proof['roots_before']
                and value['qualified_resource_owner']==r.OWNER_PIN and value['helper']==HELPER_PIN
                and value['record_body_hash_map_sha256']==proof['record_body_hash_map_sha256'] and value['all538_prior_record_bodies_unchanged'] is True,
                'actual copied-state root and fullmap preflight must match reconciliation')
            item=value['source_qualification'];q=metadata.read(item['path'],item)
            require(q['schema']=='conditions-balanced-root-identity-preflight-source-independent-review/v1' and q['passed'] is True and q['findings']==[]
                and q['observer']==value['observer'],'exact qualified copied-state preflight source required')
            metadata.pin(value['observer']['path'],value['observer'])
            for path,item in q['artifacts'].items():metadata.pin(path,dict(path=path,**{field:item[field] for field in ('bytes','sha256')}))
    metadata.pin(proof['observer']['path'],proof['observer'])
    return proof,summary


def snapshot(metadata,descriptor,role,contract):
    path=Path(descriptor['path'])
    require(path.name=='snapshot-receipt-v01.json' and path.parent.parent==F/'private-runtime-snapshots','exact owned F14 private receipt required')
    metadata.private.add(path);metadata.allow(path);receipt=metadata.read(path,descriptor)
    require(receipt['schema']=='conditions-balanced-private-endpoints/v1' and receipt['role']==role
        and (receipt['cell'] is None if role=='opening' else receipt['cell']==contract['cell'])
        and type(receipt['index']) is int and 1<=receipt['index']<=99,'exact phase/role/index required')
    label=role+('' if role=='opening' else '-'+contract['cell'])+'-v'+str(receipt['index']).zfill(2)
    require(path.parent.name==label,'true sample role directory required')
    for directory in (path.parent.parent,path.parent):
        require(directory.resolve(strict=True)==directory and not directory.is_symlink() and stat.S_IMODE(directory.stat().st_mode)==0o700,'private700 directories required')
    values=[]
    for name,endpoint in (('ledger',LEDGER),('scheduler',SCHEDULER)):
        target=Path(receipt[name]['path'])
        require(target==path.parent/(name+'.json') and receipt['source_'+name]['path']==str(endpoint)
            and all(receipt[name][key]==receipt['source_'+name][key] for key in ('bytes','sha256')),'exact copied endpoint bytes required')
        require(stat.S_IMODE(target.stat().st_mode)==0o400,'private400 copy required')
        metadata.private.add(target);values.append(metadata.read(target,receipt[name]))
    require(stat.S_IMODE(path.stat().st_mode)==0o400,'private400 receipt required')
    return receipt,*values


prior_hashes=p.prior_hashes
qualify_ledger=p.qualify_ledger
qualify_check=p.qualify_check
census_helpers=p.census_helpers


def check_receipt_custody(value,kind):
    names={'baseline':('review_conditions_balanced_resource_baseline_v01.py','resource-observer-source-independent-review-v01.json'),
        'clearance':('review_conditions_balanced_capacity_clearance_v01.py','capacity-clearance-source-independent-review-v01.json')}
    observer,gate=names[kind]
    require(full_descriptor(value['observer'],F/observer) and full_descriptor(value['source_qualification'],F/gate)
        and full_descriptor(value['resource_contract'],CONTRACT)
        and full_descriptor(value['fresh_metadata_check'])
        and full_descriptor(value['sampler_source_qualification'],F/'sampler-source-independent-review-v01.json')
        and full_descriptor(value['resource_bridge_source_qualification'],F/'resource-bridge-source-independent-review-v01.json'),
        'exact admitted F14 observer/qualification/contract/check custody required')
    proof=value['root_identity_reconciliation'];summary=value['root_identity_reconciliation_summary']
    require(full_descriptor(proof,F/'root-identity-reconciliation-v01.json') and value['artifacts'].get(proof['path'])==proof
        and set(summary)=={'root_identity_changed','atomic_native_ledger_writes','native_strict_read_after_passed','all538_record_bodies_unchanged',
            'record_body_hash_map_sha256','full_nonreleased_claim_bytes','roots_after','cap_bytes','cap_changed'}
        and summary['native_strict_read_after_passed'] is summary['all538_record_bodies_unchanged'] is True
        and summary['record_body_hash_map_sha256']=='b3c68c6a50aa564532be42134e3d803a2ee25ecf48ff1f55034dcaa6ce032df3'
        and summary['full_nonreleased_claim_bytes']==44381777216 and summary['cap_bytes']==145000000000 and summary['cap_changed'] is False
        and type(summary['root_identity_changed']) is bool and summary['atomic_native_ledger_writes']==int(summary['root_identity_changed']),
        'actual roots-only reconciliation proof must join public receipt artifacts')
    current_root_metadata(summary['roots_after']);return summary


def qualify_execution_baseline(baseline):
    require(baseline['schema']=='conditions-balanced-resource-baseline/v1' and baseline['passed'] is True and baseline['findings']==[],
        'passed concrete F14 execution baseline required')
    summary=check_receipt_custody(baseline,'baseline');ledger=baseline['baseline_ledger']
    require(ledger['schema']=='daemon-resource-reservations-v1' and ledger['record_count']==538
        and type(ledger['record_body_hashes']) is dict and len(ledger['record_body_hashes'])==538
        and digest(ledger['record_body_hashes'])==ledger['record_body_hash_map_sha256']==summary['record_body_hash_map_sha256']
        and ledger['record_status_counts']=={'released':437,'retained':101} and ledger['full_nonreleased_claim_bytes']==44381777216
        and ledger['limit_bytes']==145000000000 and ledger['all_prior_record_bodies_unchanged'] is True
        and ledger['preserved_prior_record_count']==538 and ledger['additional_current_records']==[]
        and baseline['counted_root_metadata']==summary['roots_after'],'exact conserved538 baseline and current physical roots required')
    census=baseline['preadmission_full_claim_census']
    require(census['outstanding_full_reservations_bytes']==44381777216 and census['additional_requested_bytes']==200000000
        and census['charged_bytes']==census['observed_apparent_bytes']+44381777216+200000000<=145000000000
        and census['minimum_filesystem_free_bytes']>=44381777216+200000000 and census['limit_bytes']==145000000000,
        'actual original fullclaim capacity predicate required')
    require(all(baseline[key]==0 for key in ('global_endpoint_body_reads','resource_API_calls','model_calls','checkpoint_JSON_parses','claim_reconciliations'))
        and baseline['shared_state_modified'] is False,'baseline must be a read-only copied-state observation')
    return ledger


def qualify_capacity_clearance(clearance,*,for_training):
    require(type(for_training) is bool and clearance['schema']=='conditions-balanced-capacity-clearance/v1','typed F14 capacity receipt required')
    summary=check_receipt_custody(clearance,'clearance')
    require(clearance['ledger_record_count']==538 and clearance['record_status_counts']=={'released':437,'retained':101}
        and clearance['prior_record_body_hash_map_sha256']==summary['record_body_hash_map_sha256']
        and clearance['all538_prior_record_bodies_unchanged'] is True and full_descriptor(clearance['baseline'],F/'resource-baseline-v01.json')
        and full_descriptor(clearance['input_manifest'],F/'capacity-clearance-inputs-v01.json'),'actual conserved538 clearance custody required')
    observed=clearance['observed_apparent_bytes'];claims=clearance['outstanding_full_reservations_bytes'];requested=clearance['additional_requested_bytes'];future=clearance['future_own_output_bound_bytes']
    free=clearance['minimum_filesystem_free_bytes']
    require(all(type(value) is int and value>=0 for value in (observed,claims,requested,future,free))
        and claims==44381777216 and requested==future==200000000 and clearance['limit_bytes']==145000000000
        and clearance['native_charged_bytes']==observed+claims+requested
        and clearance['full_run_charged_bound_bytes']==observed+claims+requested+future
        and clearance['required_filesystem_free_bound_bytes']==claims+requested+future
        and clearance['full_run_apparent_headroom_bytes']==145000000000-observed-claims-requested-future
        and clearance['full_run_physical_headroom_bytes']==free-claims-requested-future,'unchanged fullrun arithmetic required')
    fits=observed+claims+requested+future<=145000000000 and free>=claims+requested+future
    require(clearance['full_run_capacity_fits'] is clearance['passed'] is fits
        and clearance['native_capacity_fits'] is (observed+claims+requested<=145000000000 and free>=claims+requested)
        and (clearance['findings']==[] if fits else bool(clearance['findings']))
        and all(clearance[key] is False for key in ('model_started','reservation_acquired','shared_state_modified','admission_guaranteed',
            'future_output_bound_is_an_additional_claim','cap_or_claim_budget_changed'))
        and clearance['resource_API_calls']==clearance['global_endpoint_body_reads']==clearance['checkpoint_JSON_parses']==0,
        'truthful read-only fullrun capacity result required')
    require(not for_training or fits,'fresh fullrun storage capacity refused before any model or claim')
    return clearance
