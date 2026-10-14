"""Read-only F15 predicates: conserve historical bodies and charge every current claim."""
import ast
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import stat

F=Path(__file__).resolve().parent
LEDGER=Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/federal-corpus-audits/owned-daemon-resource-control/disk-reservations.json')
SCHEDULER=Path('/tmp/ipfs-datasets-resource-scheduler-1000.json')
POLICY=F/'resource-observation-policy-v01.json'
POLICY_PIN=dict(path=str(POLICY),bytes=7483,sha256='ffe18e9590520124be6620358723bb108ca40d14c436f8a544f658241401e184')
POLICY_CANONICAL_SHA256='6969c63ebb9fb22da9fe7ce1ccce112f0d05530accdfa3f3d8d237a060b210a8'
COUNTED_ROOT_METADATA=[
    {'device':66306,'inode':66764317,'path':'/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs'},
    {'device':66306,'inode':58092485,'path':'/home/barberb/lift_coding/external/ipfs_datasets/workspace/todo-queues'},
    {'device':66306,'inode':51016937,'path':'/home/barberb/lift_coding/external/ipfs_datasets/docs/implementation/reports/evidence'},
    {'device':66306,'inode':524344,'path':'/tmp/pytest-of-barberb'}]
KERNEL_PIN={'path':'/home/barberb/lift_coding/artifacts/legal-conditions-recall-20261014-01/conditions_balanced_resource_protocol_v01.py','bytes':13965,'sha256':'265d96839054a16d4c4ab0f2550dc69948263a87566e9337a429b3ddb02f69f0'}

# Exact previously qualified ASTs; no old phase main or resource module is imported.
_raw=Path(KERNEL_PIN['path']).read_bytes()
if len(_raw)!=KERNEL_PIN['bytes'] or hashlib.sha256(_raw).hexdigest()!=KERNEL_PIN['sha256']:
    raise ValueError('exact inherited metadata/census source required')
_names={'require','canonical','digest','Metadata','census_helpers'}
_nodes=[n for n in ast.parse(_raw).body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in _names]
if len(_nodes)!=len(_names):raise ValueError('closed inherited pure kernel set required')
exec(compile(ast.Module(body=_nodes,type_ignores=[]),KERNEL_PIN['path'],'exec'),globals())


def full_descriptor(value,path=None):
    return type(value) is dict and set(value)=={'path','bytes','sha256'} and type(value['path']) is str \
        and Path(value['path']).is_absolute() and type(value['bytes']) is int and 0<value['bytes']<=16*1024*1024 \
        and type(value['sha256']) is str and len(value['sha256'])==64 \
        and all(c in '0123456789abcdef' for c in value['sha256']) and (path is None or value['path']==str(path))


def qualify_policy(policy):
    require(type(policy) is dict and digest(policy)==POLICY_CANONICAL_SHA256
        and policy['schema']=='actor-refinement-resource-observation-policy/v1' and policy['phase_root']==str(F)
        and policy['global_cap_bytes']==145000000000 and policy['future_own_output_bound_bytes']==200000000
        and policy['historical_record_count']==539 and policy['current_record_count_assumed'] is False
        and policy['current_full_claim_bytes_assumed'] is False,'exact closed observation policy required')
    return policy


def prior_hashes(policy,baseline,terminal,reconciliation):
    hashes=dict(baseline['baseline_ledger']['record_body_hashes']);claim=terminal['only_new_own_claim']
    require(baseline['schema']=='conditions-balanced-resource-baseline/v1' and baseline['passed'] is True and baseline['findings']==[]
        and terminal['schema']=='conditions-balanced-terminal-resource-audit/v1' and terminal['passed'] is True and terminal['findings']==[]
        and terminal['baseline']==policy['prior_baseline'] and len(hashes)==terminal['opening_record_count']==terminal['preserved_prior_record_count']==538
        and digest(hashes)==terminal['prior_record_body_hash_map_sha256'] and terminal['all_prior_record_bodies_unchanged'] is True,
        'qualified complete F14 baseline and terminal custody required')
    require(claim['reservation_id'] not in hashes and claim['status']=='released' and claim['storage_bytes']==200000000,
        'one authenticated released F14 claim required')
    hashes[claim['reservation_id']]=claim['record_body_sha256']
    require(len(hashes)==terminal['closing_record_count']==policy['historical_record_count']==539
        and digest(hashes)==terminal['closing_record_body_hash_map_sha256']==policy['historical_record_body_hash_map_sha256']
        and terminal['closing_record_status_counts']==policy['historical_record_status_counts']
        and terminal['closing_full_nonreleased_claim_bytes']==policy['historical_full_nonreleased_claim_bytes'],
        'authenticated historical539 map required; historical totals are not current assumptions')
    require(reconciliation['schema']=='conditions-balanced-root-identity-reconciliation/v1' and reconciliation['passed'] is True
        and reconciliation['findings']==[] and reconciliation['all538_record_bodies_unchanged'] is True
        and reconciliation['native_strict_read_after_passed'] is True and reconciliation['cap_changed'] is False
        and reconciliation['cap_bytes']==145000000000 and reconciliation['roots_after']==policy['counted_root_metadata']
        and terminal['counted_root_metadata']==policy['counted_root_metadata']
        and terminal['root_identity_reconciliation']==policy['prior_root_identity_reconciliation'],
        'same previously qualified four physical roots required; no new identity rebind authorized')
    return hashes


def qualify_ledger(policy,ledger,hashes):
    require(type(ledger) is dict and set(ledger)=={'schema','roots','limit_bytes','reservations'}
        and ledger['schema']=='daemon-resource-reservations-v1' and type(ledger['limit_bytes']) is int
        and ledger['limit_bytes']==policy['global_cap_bytes'] and ledger['roots']==policy['counted_root_metadata'],
        'unchanged native schema/cap/four physical roots required')
    bodies=ledger['reservations']
    require(type(bodies) is dict and len(hashes)<=len(bodies)<=policy['limits']['max_records']
        and all(type(k) is str and type(v) is dict for k,v in bodies.items()),'bounded complete current reservation map required')
    actual={key:digest(body) for key,body in bodies.items()}
    require(all(actual.get(key)==value for key,value in hashes.items()),'every historical record body must remain exact')
    require(all(body.get('reservation_id')==key and body.get('status') in {'released','retained','active','reserved'}
        and type(body.get('storage_bytes')) is int and body['storage_bytes']>=0 for key,body in bodies.items()),
        'every current record must have a typed status and full storage claim')
    for preserved in policy['required_preserved_claims']:
        body=bodies[preserved['reservation_id']]
        require(body['status']==preserved['status'] and body['storage_bytes']==preserved['storage_bytes'],
            'historical N7 retained/N8 released claims must remain exact')
    extra={key:body for key,body in bodies.items() if key not in hashes}
    statuses=dict(Counter(body['status'] for body in bodies.values()))
    claims=sum(body['storage_bytes'] for body in bodies.values() if body['status']!='released')
    return dict(record_count=len(actual),record_body_hashes=actual,record_body_hash_map_sha256=digest(actual),
        record_status_counts=statuses,full_nonreleased_claim_bytes=claims,all_prior_record_bodies_unchanged=True,
        preserved_prior_record_count=len(hashes),historical_record_body_hash_map_sha256=digest(hashes),
        additional_current_record_count=len(extra),additional_current_record_status_counts=dict(Counter(body['status'] for body in extra.values())),
        additional_current_full_nonreleased_claim_bytes=sum(body['storage_bytes'] for body in extra.values() if body['status']!='released'),
        additional_current_record_body_hashes={key:actual[key] for key in extra},
        additional_current_record_body_hash_map_sha256=digest({key:actual[key] for key in extra}))


def snapshot(metadata,descriptor,policy):
    require(full_descriptor(descriptor),'full private receipt descriptor required')
    path=Path(descriptor['path'])
    require(path.name=='snapshot-receipt-v01.json' and path.parent.parent==F/'private-runtime-snapshots','exact owned F15 private receipt required')
    metadata.private.add(path);metadata.allow(path);receipt=metadata.read(path,descriptor)
    require(receipt['schema']=='actor-refinement-private-endpoints/v1' and receipt['role']=='opening' and receipt['cell'] is None
        and type(receipt['index']) is int and 1<=receipt['index']<=99
        and path.parent.name=='opening-v'+str(receipt['index']).zfill(2),'true opening sample identity required')
    for directory in (path.parent.parent,path.parent):
        require(directory.resolve(strict=True)==directory and not directory.is_symlink()
            and stat.S_IMODE(directory.stat().st_mode)==0o700,'physical private700 sample directories required')
    values=[]
    for name,endpoint in (('ledger',LEDGER),('scheduler',SCHEDULER)):
        target=Path(receipt[name]['path'])
        require(full_descriptor(receipt[name],target) and target==path.parent/(name+'.json')
            and receipt['source_'+name]['path']==str(endpoint)
            and all(receipt[name][key]==receipt['source_'+name][key] for key in ('bytes','sha256')),
            'authenticated endpoint-copy identity required')
        require(name!='ledger' or receipt[name]['bytes']<=policy['limits']['max_ledger_bytes'],'bounded ledger before parsing required')
        require(stat.S_IMODE(target.stat().st_mode)==0o400,'private400 endpoint copy required')
        metadata.private.add(target);values.append(metadata.read(target,receipt[name]))
    require(stat.S_IMODE(path.stat().st_mode)==0o400,'private400 receipt required')
    return receipt,*values


def qualify_check(policy,check,receipt,state,status):
    require(check['schema']=='scope-pilot-resource-compatibility/v1' and check['passed'] is True and check['findings']==[]
        and check['resources']==policy['resources'] and check['disk_limit_bytes']==policy['global_cap_bytes']
        and check['outstanding_full_reservations_bytes']==status['full_nonreleased_claim_bytes']
        and check['shared_config']==state['config']==policy['scheduler_config']
        and digest(state['config'])==policy['scheduler_config_sha256']
        and type(state['leases']) is dict and type(state['waiters']) is dict
        and check['lease_count']==len(state['leases']) and check['waiter_count']==len(state['waiters'])
        and all(check[key] is False for key in ('model_started','reservation_acquired','scheduler_client_constructed','shared_state_modified','admission_guaranteed')),
        'exact current fullclaim/config/typed occupancy observation required; no idle assumption')
    for name,key in (('ledger','disk_ledger'),('scheduler','shared_state')):
        require(all(check[key][field]==receipt[name][field] for field in ('bytes','sha256')),
            'fresh guardian check must match actual copied endpoint bytes')
    require(set(check['producers'])==set(policy['resource_producer_pins']),'fixed ten producer paths required')
    for path,brief in policy['resource_producer_pins'].items():
        require(check['producers'][path]==dict(path=path,**brief),'exact ten producer raw descriptors required')
    return dict(schema_version=state['schema_version'],config=state['config'],config_sha256=digest(state['config']),
        lease_count=len(state['leases']),waiter_count=len(state['waiters']),sampled_coexistence=True,admission_guaranteed=False)


def capacity(policy,observed,claims,free):
    requested=policy['resources']['storage_bytes'];future=policy['future_own_output_bound_bytes'];cap=policy['global_cap_bytes']
    require(all(type(value) is int and value>=0 for value in (observed,claims,free,requested,future,cap)),'typed nonnegative fullclaim capacity values required')
    native=observed+claims+requested;full=native+future;required=claims+requested+future
    return dict(observed_apparent_bytes=observed,outstanding_full_reservations_bytes=claims,additional_requested_bytes=requested,
        future_own_output_bound_bytes=future,native_charged_bytes=native,full_run_charged_bound_bytes=full,
        minimum_filesystem_free_bytes=free,required_filesystem_free_bound_bytes=required,limit_bytes=cap,
        native_capacity_fits=native<=cap and free>=claims+requested,full_run_capacity_fits=full<=cap and free>=required,
        full_run_apparent_headroom_bytes=cap-full,full_run_physical_headroom_bytes=free-required,
        future_output_bound_is_an_additional_claim=False,cap_or_claim_budget_changed=False)


def qualify_baseline(baseline):
    """Pure public-receipt guard for preparation and before any runner side effect."""
    require(type(baseline) is dict and baseline['schema']=='actor-refinement-resource-baseline/v1'
        and baseline['passed'] is True and baseline['findings']==[] and baseline['observation_policy']==POLICY_PIN,
        'passed source-qualified actual F15 baseline required')
    for key,path in (('observer',F/'review_actor_refinement_resource_baseline_v02.py'),
                     ('source_qualification',F/'resource-observer-source-independent-review-v02.json'),
                     ('input_manifest',F/'resource-baseline-inputs-v02.json'),
                     ('sampler_source_qualification',F/'sampler-source-independent-review-v01.json'),
                     ('resource_bridge_source_qualification',F/'resource-bridge-source-independent-review-v01.json')):
        item=baseline[key]
        require(full_descriptor(item,path) and baseline['artifacts'].get(item['path'])==item,
            'exact admitted observer/sourcegate/input custody required')
    require(baseline['artifacts'].get(str(POLICY))==POLICY_PIN
        and baseline['artifacts'].get(KERNEL_PIN['path'])==KERNEL_PIN
        and full_descriptor(baseline['fresh_metadata_check'])
        and Path(baseline['fresh_metadata_check']['path']).parent==F
        and baseline['artifacts'].get(baseline['fresh_metadata_check']['path'])==baseline['fresh_metadata_check'],
        'exact public policy/kernel/freshcheck artifact joins required')
    receipt=baseline['private_sample_receipt']
    require(full_descriptor(receipt) and Path(receipt['path']).name=='snapshot-receipt-v01.json'
        and Path(receipt['path']).parent.parent==F/'private-runtime-snapshots'
        and Path(receipt['path']).parent.name.startswith('opening-v'),
        'actual owned private receipt descriptor required without body access')
    require(all('private-runtime-snapshots' not in Path(path).parts and 'private-root-identity-rebind-v01' not in Path(path).parts
        for path in baseline['artifacts']),'private bodies excluded from admitted public artifacts')
    ledger=baseline['baseline_ledger'];actual=ledger['record_body_hashes'];extra=ledger['additional_current_record_body_hashes']
    valid_hash=lambda value:type(value) is str and len(value)==64 and all(c in '0123456789abcdef' for c in value)
    require(type(actual) is dict and type(extra) is dict and 539<=len(actual)<=4096
        and all(type(key) is str and valid_hash(value) for key,value in actual.items())
        and all(actual.get(key)==value for key,value in extra.items()),'typed complete current hash map and additional subset required')
    historical={key:value for key,value in actual.items() if key not in extra}
    require(len(historical)==539 and digest(historical)=='7d4b36d39ab787fac9dcfee03fe71b1bd833c039778e4810b0a2c4eeaf477c1e'
        and ledger['historical_record_body_hash_map_sha256']==digest(historical)
        and ledger['record_body_hash_map_sha256']==digest(actual) and ledger['additional_current_record_body_hash_map_sha256']==digest(extra)
        and type(ledger['record_count']) is int and ledger['record_count']==len(actual)
        and type(ledger['additional_current_record_count']) is int and ledger['additional_current_record_count']==len(extra)
        and ledger['preserved_prior_record_count']==539 and ledger['all_prior_record_bodies_unchanged'] is True
        and baseline['historical_record_count']==539 and baseline['all_historical_record_bodies_unchanged'] is True
        and baseline['historical_record_body_hash_map_sha256']==digest(historical),
        'all exact known539 bodies must be conserved independently of additional current records')
    statuses=ledger['record_status_counts'];extra_statuses=ledger['additional_current_record_status_counts']
    require(type(statuses) is dict and type(extra_statuses) is dict
        and all(key in {'released','retained','active','reserved'} and type(value) is int and value>0 for key,value in statuses.items())
        and all(key in {'released','retained','active','reserved'} and type(value) is int and value>0 for key,value in extra_statuses.items())
        and sum(statuses.values())==len(actual) and sum(extra_statuses.values())==len(extra)
        and statuses==dict(Counter({'released':438,'retained':101})+Counter(extra_statuses)),
        'typed actual aggregate status counts must include every historical and additional record')
    claims=ledger['full_nonreleased_claim_bytes'];extra_claims=ledger['additional_current_full_nonreleased_claim_bytes']
    require(type(claims) is int and type(extra_claims) is int and extra_claims>=0 and claims==44381777216+extra_claims
        and ledger['schema']=='daemon-resource-reservations-v1' and ledger['limit_bytes']==145000000000,
        'all current full nonreleased claims must be charged; historical charge cannot disappear')
    cap=baseline['preadmission_full_claim_census']
    observed=cap['observed_apparent_bytes'];free=cap['minimum_filesystem_free_bytes']
    required=capacity(dict(resources=dict(storage_bytes=200000000),future_own_output_bound_bytes=200000000,
        global_cap_bytes=145000000000),observed,claims,free)
    require(all(cap[key]==value for key,value in required.items()) and cap['full_run_capacity_fits'] is True,
        'actual fullclaim plus200M request plus200M future bound must fit before training')
    inventory=cap['inventory'];per_root=cap['per_root_inventory'];roots=baseline['counted_root_metadata']
    require(roots==COUNTED_ROOT_METADATA and type(per_root) is list and len(per_root)==4
        and [row['path'] for row in per_root]==[row['path'] for row in roots]
        and all(type(row[key]) is int and row[key]>=0 for row in per_root for key in ('apparent_bytes','entry_count','symlink_count','special_file_count'))
        and all(inventory[key]==sum(row[key] for row in per_root) for key in ('apparent_bytes','entry_count','symlink_count','special_file_count'))
        and inventory['apparent_bytes']==observed and inventory['entry_count']<=2000000,
        'complete bounded four-root aggregate census arithmetic required')
    scheduler=baseline['scheduler_observation']
    require(scheduler['config_sha256']==digest(scheduler['config'])=='76d10cc42015c9e4cbdad0fabd6a64f706320e14a8fb507f16262d42dd1d5856'
        and all(type(scheduler[key]) is int and scheduler[key]>=0 for key in ('lease_count','waiter_count'))
        and scheduler['sampled_coexistence'] is True and scheduler['admission_guaranteed'] is False,
        'same scheduler config and truthful current typed occupancy required')
    require(all(baseline[key] is False for key in ('current_record_count_assumed','current_full_claim_bytes_assumed','model_started',
        'reservation_acquired','admission_guaranteed','continuous_coverage_claimed','shared_state_modified','full_record_bodies_published',
        'default_promotion','training_authorized'))
        and all(baseline[key]==0 for key in ('root_identity_rebinds','claim_reconciliations','global_endpoint_body_reads',
            'resource_API_calls','model_calls','checkpoint_JSON_parses')),'read-only observation cannot authorize an admission or numerical run')
    return ledger
