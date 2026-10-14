"""Qualify actual post-reconciliation536 records and a fresh full named-root census.

Only the qualified opening-v04 private copies are parsed. Exactly the approved
own N8 claim may differ from V01; all other535 bodies remain exact. The census
is an actual postwrite metadata observation, distinct from API projection.
"""
import ast
from collections import Counter
from datetime import datetime,timezone
import hashlib,json,math,os,shutil,stat,sys
from pathlib import Path

F=Path(__file__).resolve().parent
RUN=Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01')
LEDGER=RUN.parent/'federal-corpus-audits/owned-daemon-resource-control/disk-reservations.json'
SCHEDULER=Path('/tmp/ipfs-datasets-resource-scheduler-1000.json')
ROOTS=(RUN.parent,RUN.parent.parent/'todo-queues',RUN.parent.parent.parent/'docs/implementation/reports/evidence',Path('/tmp/pytest-of-barberb'))
OWNER=RUN.parent/'native4096-four-width-20261004/resource-cap/autoencoder_daemon_resources.py'
OWNER_PIN=dict(path=str(OWNER),bytes=36724,sha256='b00d2752ba852fe73760bba4fbd51b0e845742c3527642606a2a77ed9f8f5e2c')
BASELINE=dict(path=str(F/'resource-baseline-v01.json'),bytes=77873,sha256='0d9930ff9831f0fb135439a066f0345e2fa3e9720a8827f74366253016b4f8f2')
PREFLIGHT=dict(path=str(F/'actor-features-retained-claim-preflight-v01.json'),bytes=20562,sha256='13ccb471de2de244a3e8cc5f8d2cd1c617579c52ec499121355d4a9906a10850')
DIAGNOSTIC=dict(path=str(F/'actor-features-storage-diagnostic-v01.json'),bytes=19988,sha256='7e97f459a9187a401fa77213e67fd6be954080e86ce285dce95c20bf2378ffe8')
TARGET='893d4ed80ab3497f95b1490080e3caa3'
TARGET_SHA='63cbb539d211fa47bf9a19d9b50c45dd4f2f4f8075d3d27b7597466c5174386c'
N7='c3e6fbcf39d146cd85f12617d320b153'
INPUTS=F/'resource-baseline-inputs-v02.json'
QUALIFICATION=F/'resource-observer-source-independent-review-v02.json'
OUTPUT=F/'resource-baseline-v02.json'
SAMPLE=dict(path=str(F/'private-runtime-snapshots/opening-v04/snapshot-receipt-v01.json'))
PRIVATE=set()
READS={}
sys.dont_write_bytecode=True


def require(value,message):
    if not value:raise ValueError(message)

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def pin(path,expected=None):
    path=Path(path)
    require(path.is_absolute() and path.resolve(strict=True)==path and not path.is_symlink(),'physical absolute file required')
    require(path not in (LEDGER,SCHEDULER) and ('private-runtime-snapshots' not in path.parts or path in PRIVATE or path==Path(SAMPLE['path'])),'unqualified private/global body prohibited')
    require('checkpoint' not in path.name and 'reference-packet' not in path.name,'model/reference body prohibited')
    before=path.stat();require(stat.S_ISREG(before.st_mode) and 0<before.st_size<=16*1024*1024,'bounded ordinary metadata/source required')
    raw=path.read_bytes();after=path.stat()
    identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    require(identity(before)==identity(after) and len(raw)==before.st_size,'source read drift')
    value=dict(path=str(path),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    require(expected is None or value==expected,'raw identity differs')
    require(str(path) not in READS or READS[str(path)]==value,'consumed raw identity drift')
    READS[str(path)]=value
    return value

def read(path,expected=None):
    captured=pin(path,expected);raw=Path(path).read_bytes()
    require(len(raw)==captured['bytes'] and hashlib.sha256(raw).hexdigest()==captured['sha256'],'consumed bytes differ')
    def pairs(items):
        value={}
        for key,item in items:require(key not in value,'duplicate JSON key');value[key]=item
        return value
    def finite(raw):
        value=float(raw);require(math.isfinite(value),'nonfinite JSON');return value
    value=json.loads(raw,object_pairs_hook=pairs,parse_float=finite,
        parse_constant=lambda v:(_ for _ in ()).throw(ValueError('nonfinite JSON')))
    pin(path,captured);return value

def audit(event,args):
    if event=='import' and args[0].split('.')[0] in {'ipfs_datasets_py','torch','numpy','transformers','huggingface_hub'}:
        raise ValueError('production/numerical/SDK import prohibited')
    if event.startswith(('subprocess.','socket.','os.exec','os.spawn')) or event in {
        'os.system','os.fork','os.posix_spawn','os.kill','os.killpg','fcntl.flock','os.mkdir','os.remove','os.rmdir','os.rename','os.replace','os.unlink'}:
        raise ValueError('process/network/lock/shared mutation prohibited')
    if event=='open':
        name,mode,flags=args;target=Path(os.fsdecode(name)).absolute() if isinstance(name,(str,bytes,os.PathLike)) else None
        require(target not in (LEDGER,SCHEDULER),'live global bodies prohibited')
        if target is not None:
            require('checkpoint' not in target.name and 'reference-packet' not in target.name,'model/reference body prohibited')
            require('private-runtime-snapshots' not in target.parts or target in PRIVATE or target==Path(SAMPLE['path']),'only authenticated opening4 private endpoints permitted')
        writing=isinstance(mode,str) and any(c in mode for c in 'wax+')
        writing|=isinstance(flags,int) and bool(flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
        require(not writing or target==OUTPUT and bool(flags&os.O_EXCL),'only exclusive own diagnostic write permitted')
    if event in {'os.chmod','os.chown','os.truncate','os.utime','os.link','os.symlink'}:
        require(event=='os.chmod' and Path(args[0]).absolute()==OUTPUT and args[1]==0o444,'only own diagnostic freeze permitted')


def qualify_reconciled_ledger(ledger,prior,reconciliation,preflight):
    original=prior['baseline_ledger']['record_body_hashes'];bodies=ledger['reservations']
    require(prior['schema']=='actor-features-resource-baseline/v1' and prior['passed'] is True and prior['findings']==[]
        and len(original)==536 and digest(original)==prior['baseline_ledger']['record_body_hash_map_sha256'], 'authenticated old536 map required')
    require(type(ledger) is dict and set(ledger)=={'schema','roots','limit_bytes','reservations'}
        and ledger['schema']=='daemon-resource-reservations-v1' and type(ledger['limit_bytes']) is int and ledger['limit_bytes']==145000000000
        and ledger['roots']==prior['counted_root_metadata'],'same postrecovery global schema/roots/cap required')
    transition=reconciliation['target_transition']
    require(reconciliation['schema']=='actor-features-retained-claim-reconciliation/v1' and reconciliation['passed'] is True
        and reconciliation['findings']==[] and reconciliation['preflight']==PREFLIGHT and reconciliation['prior_baseline']==BASELINE
        and reconciliation['claims_explicitly_reconciled']==1 and reconciliation['all_other535_record_bodies_unchanged'] is True
        and reconciliation['N7_claim_status_changed'] is False and reconciliation['outputs_deleted'] is False and reconciliation['cap_changes']==0
        and transition['reservation_id']==TARGET and transition['previous_record_body_sha256']==original[TARGET]==TARGET_SHA
        and transition['status']=='released' and transition['storage_bytes']==200000000,'exact qualified own N8 reconciliation required')
    require(type(bodies) is dict and set(bodies)==set(original) and len(bodies)==536,'same536 record key set required')
    hashes={key:digest(body) for key,body in bodies.items()};expected=dict(original);expected[TARGET]=transition['record_body_sha256']
    require(hashes==expected and hashes[TARGET]!=TARGET_SHA and digest(hashes)==transition['closing_record_body_hash_map_sha256']
        and all(hashes[key]==original[key] for key in original if key!=TARGET),'only approved own N8 body may change; all535 other hashes exact')
    record=bodies[TARGET]
    require(record['reservation_id']==TARGET and record['status']=='released' and record['storage_bytes']==200000000
        and record['artifacts_durable_asserted'] is True and record['explicit_reconciliation']==reconciliation['retained_API_recovery']
        and record['explicit_reconciliation']['artifacts']==preflight['durable_artifact_inventory']
        and record['explicit_reconciliation']['previous_record_sha256']==TARGET_SHA
        and record['explicit_reconciliation']['outputs_deleted'] is False and record['explicit_reconciliation']['automatic_expiry'] is False,
        'actual closing target must carry exact retained API durable closeout')
    others={key:body for key,body in bodies.items() if key!=TARGET}
    require(digest(others)==preflight['ledger_conservation']['other_reservations_sha256']
        and bodies[N7]['status']=='retained' and bodies[N7]['storage_bytes']==200000000,'all535 other bodies and failed N7 retainedclaim unchanged')
    statuses=dict(Counter(body['status'] for body in bodies.values()))
    require(all(type(body['storage_bytes']) is int and body['storage_bytes']>=0 for body in bodies.values()),'integer fullclaims required')
    claims=sum(body['storage_bytes'] for body in bodies.values() if body['status']!='released')
    require(statuses=={'released':435,'retained':101} and claims==44381777216,'actual postrecovery statuses/fullclaims differ')
    return dict(schema=ledger['schema'],limit_bytes=145000000000,record_count=536,previous_record_count=536,
        record_body_hashes=hashes,record_body_hash_map_sha256=digest(hashes),record_status_counts=statuses,
        full_nonreleased_claim_bytes=claims,unchanged_other_record_count=535,all_other535_record_bodies_unchanged=True,
        only_reconciled_prior_claim=dict(reservation_id=TARGET,previous_record_body_sha256=TARGET_SHA,
            record_body_sha256=hashes[TARGET],status='released',storage_bytes=200000000),
        failed_N7_claim_retained_and_fully_charged=True,failed_N8_claim_explicitly_reconciled=True,
        additional_current_records=[],full_record_bodies_published=False)


def inventory_helpers():
    pin(OWNER,OWNER_PIN);tree=ast.parse(OWNER.read_bytes())
    names={'_safe_path','_checked_path','_root_identity','_inventory_descendant','_inventory_entry_disappeared','_inventory'}
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
    error=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='DaemonResourceError')
    require(len(nodes)==len(names) and len(error.body)==1 and isinstance(error.body[0],ast.Expr),'exact source-only census helper closure required')
    ns=dict(Path=Path,os=os,stat=stat,MAX_INVENTORY_ENTRIES=2000000)
    exec(compile(ast.Module(body=[error,*nodes],type_ignores=[]),str(OWNER),'exec'),ns)
    return ns


def main():
    require(sys.argv[1:]==[] and not os.path.lexists(OUTPUT),'exclusive argument-free actual baseline required')
    sys.addaudithook(audit);own=pin(Path(__file__).resolve());qualification=read(QUALIFICATION)
    require(qualification['schema']=='actor-features-resource-observer-source-independent-review/v1'
        and qualification['passed'] is True and qualification['findings']==[] and qualification['observer']==own,'exact baselineV02 source qualification required')
    for path,expected in qualification.get('artifacts',{}).items():
        require(all(pin(path)[key]==expected[key] for key in ('bytes','sha256')),'qualified source drift')
    inputs=read(INPUTS)
    keys={'schema','prior_baseline','explicit_reconciliation','recovery_preflight','sample_receipt','check','sampler','sampler_qualification','guardian','bridge_qualification'}
    require(type(inputs) is dict and set(inputs)==keys and inputs['schema']=='actor-features-resource-baseline-inputs/v2'
        and inputs['prior_baseline']==BASELINE and inputs['recovery_preflight']==PREFLIGHT
        and inputs['explicit_reconciliation']['path']==str(F/'actor-features-retained-claim-reconciliation-v01.json')
        and inputs['sample_receipt']['path']==SAMPLE['path'],'exact root-approved postreconciliation input manifest required')
    prior=read(BASELINE['path'],BASELINE);preflight=read(PREFLIGHT['path'],PREFLIGHT)
    reconciliation=read(inputs['explicit_reconciliation']['path'],inputs['explicit_reconciliation'])
    api_review=read(reconciliation['source_qualification']['path'],reconciliation['source_qualification'])
    require(api_review['schema']=='actor-features-retained-claim-reconciliation-source-independent-review/v1'
        and api_review['passed'] is True and api_review['findings']==[] and api_review['observer']==reconciliation['observer'],
        'exact independent retained API wrapper qualification must join')
    pin(reconciliation['observer']['path'],reconciliation['observer'])
    for path,expected in api_review.get('artifacts',{}).items():
        require(all(pin(path)[key]==expected[key] for key in ('bytes','sha256')),'qualified administrative source/control drift')
    approval=read(reconciliation['execution_approval']['path'],reconciliation['execution_approval'])
    require(approval['schema']=='actor-features-retained-claim-reconciliation-execution-approval/v1'
        and approval['passed'] is True and approval['findings']==[] and approval['observer']==reconciliation['observer'] and approval['preflight']==PREFLIGHT
        and approval['source_qualification']==reconciliation['source_qualification']
        and approval['authorize_exact_one_own_N8_claim_reconciliation'] is True,'exact root one-own-claim execution approval must join')
    receipt=read(inputs['sample_receipt']['path'],inputs['sample_receipt'])
    require(receipt['schema']=='actor-features-private-endpoints/v1' and receipt['role']=='opening' and receipt['cell'] is None and receipt['index']==4,'actual opening4 snapshot required')
    for name,endpoint in (('ledger',LEDGER),('scheduler',SCHEDULER)):
        require(receipt[name]['path']==str(F/'private-runtime-snapshots/opening-v04'/(name+'.json'))
            and receipt['source_'+name]['path']==str(endpoint)
            and all(receipt[name][key]==receipt['source_'+name][key] for key in ('bytes','sha256')),'exact copied endpoint identities required')
        PRIVATE.add(Path(receipt[name]['path']))
    ledger=read(receipt['ledger']['path'],receipt['ledger']);state=read(receipt['scheduler']['path'],receipt['scheduler'])
    status=qualify_reconciled_ledger(ledger,prior,reconciliation,preflight)
    check=read(inputs['check']['path'],inputs['check']);sampler_review=read(inputs['sampler_qualification']['path'],inputs['sampler_qualification'])
    require(inputs['guardian']==prior['qualified_local_guardian'] and inputs['sampler']['path']==str(F/'sample_actor_features_private_resources_v02.py')
        and sampler_review['schema']=='actor-features-sampler-source-independent-review/v1' and sampler_review['passed'] is True
        and sampler_review['findings']==[] and sampler_review['sampler']==inputs['sampler'],'qualified unchangedguardian/newsampler required')
    for key in ('sampler','guardian'):pin(inputs[key]['path'],inputs[key])
    bridge=read(inputs['bridge_qualification']['path'],inputs['bridge_qualification'])
    require(bridge['schema']=='actor-features-resource-bridge-source-independent-review/v1' and bridge['passed'] is True and bridge['findings']==[]
        and inputs['bridge_qualification']==prior['resource_bridge_source_qualification'],'same retained qualified resource bridge required')
    require(check['schema']=='scope-pilot-resource-compatibility/v1' and check['passed'] is True and check['findings']==[]
        and check['model_started'] is check['reservation_acquired'] is check['scheduler_client_constructed'] is False
        and check['disk_limit_bytes']==145000000000 and check['outstanding_full_reservations_bytes']==44381777216
        and check['resources']==prior['scheduler_observation']['resource_contract']
        and check['shared_config']==prior['scheduler_observation']['config']==state['config']
        and type(state['leases']) is dict and type(state['waiters']) is dict
        and check['lease_count']==len(state['leases']) and check['waiter_count']==len(state['waiters']),'same contemporaneous postwrite compatibility/config/occupancy required')
    for name,key,endpoint in (('ledger','disk_ledger',LEDGER),('scheduler','shared_state',SCHEDULER)):
        require(check[key]['path']==str(endpoint) and all(check[key][field]==receipt[name][field] for field in ('bytes','sha256')),
            'fresh metadata check must join exact copied endpoint bytes')
    # Literal ten-path closure is inherited; selecting producers by path prefix is prohibited.
    old_source=F/'review_actor_features_resource_baseline_v01.py'
    pin(old_source,dict(path=str(old_source),bytes=25392,sha256='b94fd04af4717cc99d36d5eb9778d9e6d7e4377acbc7dd1c6ae5dc73be2f987e'))
    import importlib.util
    spec=importlib.util.spec_from_file_location('qualified_old_actor_features_baseline',old_source)
    old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    require(set(check['producers'])==set(old.RESOURCE_PRODUCER_PINS) and len(check['producers'])==10,'same exact ten resource producer paths required')
    for path,brief in old.RESOURCE_PRODUCER_PINS.items():
        value=pin(path)
        require(all(value[key]==brief[key] for key in ('bytes','sha256')) and value==check['producers'][path],'raw resource producer source changed')
    diagnostic=read(DIAGNOSTIC['path'],DIAGNOSTIC)
    require(diagnostic['passed'] is True and diagnostic['findings']==[] and diagnostic['failure']['model_started'] is False
        and diagnostic['failure']['child_created'] is False and diagnostic['failure']['optimizer_updates']==0,'preserved N10 failed prechild zero-work evidence required')
    failed=RUN/'actor-features-20261013-actor-features-ce-01'
    failed_names={'pre-admission.json','failure-primary.json','resources-final-failure.json','child-exit.json','guardian-exit.json'}
    require({path.name for path in failed.iterdir()}==failed_names,'failed attempt01 five-file inventory must remain unchanged')
    for name in sorted(failed_names):pin(failed/name,diagnostic['artifacts'][str(failed/name)])
    helpers=inventory_helpers();census=helpers['_inventory'](ROOTS)
    require([helpers['_root_identity'](root) for root in ROOTS]==ledger['roots'],'postwrite census must use same four rooted identities')
    claims=status['full_nonreleased_claim_bytes'];free=min(shutil.disk_usage(root).free for root in ROOTS)
    charged=census['apparent_bytes']+claims+200000000
    require(charged<=145000000000 and free>=claims+200000000,'fresh actual postwrite capacity must fit unchanged own200M request')
    status.update(path=receipt['ledger']['path'],bytes=receipt['ledger']['bytes'],sha256=receipt['ledger']['sha256'])
    for path,expected in list(READS.items()):pin(path,expected)
    value=dict(schema='actor-features-resource-baseline/v2',passed=True,findings=[],observer=own,source_qualification=pin(QUALIFICATION),input_manifest=pin(INPUTS),
        observed_at_utc=datetime.now(timezone.utc).isoformat(),prior_baseline=BASELINE,explicit_reconciliation=inputs['explicit_reconciliation'],recovery_preflight=PREFLIGHT,
        baseline_ledger=status,counted_root_metadata=ledger['roots'],run_root_identity=helpers['_root_identity'](RUN),
        private_sample_receipt=inputs['sample_receipt'],adapted_sampler=inputs['sampler'],sampler_source_qualification=inputs['sampler_qualification'],
        qualified_local_guardian=inputs['guardian'],resource_bridge_source_qualification=inputs['bridge_qualification'],fresh_metadata_check=inputs['check'],
        scheduler_observation=dict(path=str(SCHEDULER),bytes=receipt['scheduler']['bytes'],sha256=receipt['scheduler']['sha256'],
            schema_version=state.get('schema_version'),config=state['config'],config_sha256=digest(state['config']),resource_contract=prior['scheduler_observation']['resource_contract'],
            lease_count=len(state['leases']),waiter_count=len(state['waiters']),sampled_coexistence=True,admission_guaranteed=False),
        actual_postwrite_full_claim_census=dict(inventory=census,observed_apparent_bytes=census['apparent_bytes'],outstanding_full_reservations_bytes=claims,
            additional_requested_bytes=200000000,charged_bytes=charged,limit_bytes=145000000000,minimum_filesystem_free_bytes=free,
            full_capacity_headroom_bytes=145000000000-charged,actual_postwrite_observation=True,API_arithmetic_projection_used=False,admission_guaranteed=False),
        failed_attempt01_evidence_preserved=True,failed_attempt01_no_child_or_model=True,
        foreign_transient_storage_drop_also_observed=True,own_claim_closeout_alone_caused_capacity_recovery_claimed=False,
        sampled_coexistence=True,execution_approval=False,continuous_coverage_claimed=False,
        artifacts={path:entry for path,entry in READS.items() if 'private-runtime-snapshots' not in Path(path).parts},
        live_global_body_reads=0,copied_private_endpoint_JSON_parses=2,resource_API_calls=0,shared_state_modified=False,
        claim_status_changes=0,model_calls=0,checkpoint_JSON_parses=0,semantic_accuracy=None,default_promotion=False,
        limitations=['Actual postwrite copied-state and metadata census establish536 current bodies; full foreign bodies remain private.',
            'OldV01 body preservation applies to535 other claims; the one named N8 claim now has an explicit authorized administrative closeout.',
            'Capacity is sampled and reflects independent transient-tree change as well as the own200M closeout; actual guardian admission remains authoritative.'])
    with OUTPUT.open('x') as out:json.dump(value,out,indent=2,sort_keys=True,allow_nan=False);out.write('\n')
    OUTPUT.chmod(0o444);print(json.dumps(pin(OUTPUT)))

if __name__=='__main__':main()
