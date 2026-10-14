"""Read-only preflight for explicit reconciliation of one authenticated own N8 retained claim.

Uses only qualified opening-v03 copies and the exact old zero-update attempt.
Compiles unchanged read-only owner/recovery functions; no reservation class,
scheduler client, resource mutation, release, cleanup or model is constructed.
Artifact fsync supplies durability without deleting or rewriting outputs.
"""
import ast
from collections import Counter
from datetime import datetime,timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import sys
from types import SimpleNamespace

F=Path(__file__).resolve().parent
F8=F.parent/'legal-actor-boundary-20261013-01'
RUN=Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01')
ATTEMPT=RUN/'actor-boundary-20261013-actor-boundary-ce-01'
OWNER=RUN.parent/'native4096-four-width-20261004/resource-cap/autoencoder_daemon_resources.py'
RECOVERY=RUN.parent/'ui-modal-coverage-20261002/validation-source-r2/ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_resource_recovery.py'
LEDGER=RUN.parent/'federal-corpus-audits/owned-daemon-resource-control/disk-reservations.json'
SCHEDULER=Path('/tmp/ipfs-datasets-resource-scheduler-1000.json')
ROOTS=(RUN.parent,RUN.parent.parent/'todo-queues',RUN.parent.parent.parent/'docs/implementation/reports/evidence',Path('/tmp/pytest-of-barberb'))
TARGET='893d4ed80ab3497f95b1490080e3caa3'
TARGET_SHA='63cbb539d211fa47bf9a19d9b50c45dd4f2f4f8075d3d27b7597466c5174386c'
BASELINE=dict(path=str(F/'resource-baseline-v01.json'),bytes=77873,sha256='0d9930ff9831f0fb135439a066f0345e2fa3e9720a8827f74366253016b4f8f2')
SAMPLE=dict(path=str(F/'private-runtime-snapshots/opening-v03/snapshot-receipt-v01.json'),bytes=1414,sha256='39208e04adc755fd23da03c29d3307752914ccb1b29b06ea37f24b2eb49bcab6')
OWNER_PIN=dict(path=str(OWNER),bytes=36724,sha256='b00d2752ba852fe73760bba4fbd51b0e845742c3527642606a2a77ed9f8f5e2c')
RECOVERY_PIN=dict(path=str(RECOVERY),bytes=6230,sha256='5d36b28b4bda7cba91fbbe146cf2e3752f06f3e3adb6c92772788466ef701aa7')
ZERO=dict(path=str(F8/'actor-zero-update-recovery-v01.json'),bytes=3807,sha256='3ab4fd1ba42eeb8fe86c15d8c460824213a950e4805c897f1778cd3bbfff6916')
FINAL=dict(path=str(F8/'final-integration-independent-review-v01.json'),bytes=287372,sha256='b478dbc9a2964b88cbaef40d36380fbad4c761ff3828dea44052be6bd5807eec')
QUALIFICATION=F/'retained-claim-preflight-source-independent-review-v02.json'
OUTPUT=F/'actor-features-retained-claim-preflight-v01.json'
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
            require('private-runtime-snapshots' not in target.parts or target in PRIVATE or target==Path(SAMPLE['path']),'only authenticated opening3 private ledger copy permitted')
        writing=isinstance(mode,str) and any(c in mode for c in 'wax+')
        writing|=isinstance(flags,int) and bool(flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
        require(not writing or target==OUTPUT and bool(flags&os.O_EXCL),'only exclusive own diagnostic write permitted')
    if event in {'os.chmod','os.chown','os.truncate','os.utime','os.link','os.symlink'}:
        require(event=='os.chmod' and Path(args[0]).absolute()==OUTPUT and args[1]==0o444,'only own diagnostic freeze permitted')


def pure_resource_helpers():
    """Exact authenticated functions only; production imports/class constructors are omitted."""
    pin(OWNER,OWNER_PIN);pin(RECOVERY,RECOVERY_PIN)
    owner=ast.parse(OWNER.read_bytes())
    names={'_integer','_external_charges','_safe_path','_checked_path','_root_identity',
        '_inventory_descendant','_inventory_entry_disappeared','_inventory','_process','_group_usage'}
    nodes=[n for n in owner.body if isinstance(n,ast.FunctionDef) and n.name in names]
    error=next(n for n in owner.body if isinstance(n,ast.ClassDef) and n.name=='DaemonResourceError')
    require(len(nodes)==len(names) and len(error.body)==1 and isinstance(error.body[0],ast.Expr),'exact read-only owner helper closure required')
    ns=dict(Path=Path,os=os,stat=stat,MAX_STORAGE_BYTES=145000000000,MAX_INVENTORY_ENTRIES=2000000,
        MAX_EXTERNAL_CHARGES=128,_CHARGE_KEY=re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:@+-]{0,127}\Z'))
    exec(compile(ast.Module(body=[error,*nodes],type_ignores=[]),str(OWNER),'exec'),ns)
    recovery=ast.parse(RECOVERY.read_bytes())
    durable=next(n for n in recovery.body if isinstance(n,ast.FunctionDef) and n.name=='_durable_inventory')
    scope=dict(resources=SimpleNamespace(**{name:ns[name] for name in (*names,'DaemonResourceError')}),
        hashlib=hashlib,os=os,stat=stat)
    exec(compile(ast.Module(body=[durable],type_ignores=[]),str(RECOVERY),'exec'),scope)
    return ns,scope['_durable_inventory']


def qualify_ledger(ledger,baseline):
    prior=baseline['baseline_ledger'];bodies=ledger['reservations']
    require(baseline['schema']=='actor-features-resource-baseline/v1' and baseline['passed'] is True and baseline['findings']==[]
        and prior['record_count']==536 and len(prior['record_body_hashes'])==536
        and digest(prior['record_body_hashes'])==prior['record_body_hash_map_sha256'],'qualified opening536 baseline required')
    require(type(ledger) is dict and set(ledger)=={'schema','roots','limit_bytes','reservations'}
        and ledger['schema']=='daemon-resource-reservations-v1' and ledger['limit_bytes']==145000000000
        and ledger['roots']==baseline['counted_root_metadata'] and len(ledger['roots'])==4,'same exact ledger roots/schema/cap required')
    require(type(bodies) is dict and len(bodies)==536 and {key:digest(row) for key,row in bodies.items()}==prior['record_body_hashes'],
        'all536 current record bodies must match authenticated opening')
    require(type(bodies[TARGET]) is dict and digest(bodies[TARGET])==TARGET_SHA
        and bodies[TARGET]['reservation_id']==TARGET and bodies[TARGET]['status']=='retained' and bodies[TARGET]['storage_bytes']==200000000,
        'exact own N8 retained200M claim required')
    statuses=dict(Counter(row['status'] for row in bodies.values()))
    claims=sum(row['storage_bytes'] for row in bodies.values() if row['status']!='released')
    require(statuses=={'released':434,'retained':102} and claims==44581777216,'historical status/fullclaim conservation required')
    others={key:row for key,row in bodies.items() if key!=TARGET}
    return bodies[TARGET],claims,dict(record_count=536,all_previous536_record_bodies_unchanged=True,
        record_body_hash_map_sha256=digest(prior['record_body_hashes']),record_status_counts=statuses,
        full_nonreleased_claim_bytes=claims,other_reservations_sha256=digest(others),other_record_count=len(others),
        other_record_body_hash_map_sha256=digest({key:digest(row) for key,row in others.items()}),full_record_bodies_published=False)


def qualify_zero_evidence(zero,final,record):
    require(zero['schema']=='actor-boundary-zero-update-recovery/v1' and zero['passed'] is True and zero['findings']==[]
        and zero['failed_attempt']==str(ATTEMPT) and zero['failed_stage']=='preflight'
        and zero['in_progress_updates_unknown'] is False and zero['model_or_numeric_replay_executed'] is False
        and all(zero[key]==0 for key in ('model_forwards','inference_source_forwards','encoder_forwards','optimizer_updates','captured_output_files'))
        and zero['retained_claim']==dict(reservation_id=TARGET,record_body_sha256=TARGET_SHA,status='retained',storage_bytes=200000000),
        'qualified old preflight zero-work claim required')
    copy_path=F8/'datasets/docs/implementation/reports/evidence/legal-actor-boundary-20261013-01/actor-zero-update-recovery-v01.json'
    require(final['schema']=='actor-boundary-final-integration-independent-review/v1' and final['passed'] is True and final['findings']==[]
        and all(final['artifacts'][str(copy_path)][key]==ZERO[key] for key in ('bytes','sha256')),'published N8 final must bind exact zero-work receipt bytes')
    evidence=zero['failed_public_evidence']
    require(evidence['failed_child_failure']['path']==str(ATTEMPT/'results/child-failure.json')
        and evidence['failed_child_identity']['path']==str(ATTEMPT/'child-identity.json')
        and evidence['failed_guardian']['path']==str(ATTEMPT/'guardian-exit.json')
        and evidence['failed_pre_admission']['path']==str(ATTEMPT/'pre-admission.json'),'exact old failed public source paths required')
    child=read(evidence['failed_child_failure']['path'],evidence['failed_child_failure'])
    identity=read(evidence['failed_child_identity']['path'],evidence['failed_child_identity'])
    guardian=read(evidence['failed_guardian']['path'],evidence['failed_guardian'])
    pre=read(evidence['failed_pre_admission']['path'],evidence['failed_pre_admission'])
    require(child['stage']=='preflight' and child['completed_updates']==0 and child['in_progress_updates_unknown'] is False
        and pre['plan']==evidence['failed_plan'] and pre['runner']==evidence['failed_runner']
        and pre['review']==evidence['failed_training_review'],'old failed public source/plan/zero-update joins required')
    for name in ('failed_plan','failed_runner','failed_training_review'):
        pin(evidence[name]['path'],evidence[name])
    require({p.name for p in (ATTEMPT/'results').iterdir()}=={'child-failure.json'},'sole preflight failure output required')
    cached=guardian['resources']
    require(cached['reservation_id']==TARGET and digest(cached['record'])==TARGET_SHA
        and guardian['returncode']==1 and guardian['cleanup']['leader_reaped'] is True
        and guardian['cleanup']['live_group_processes']==0,'old failed guardian must bind the exact retained claim and cleanup')
    children=[record.get('child'),*record.get('prior_children',())]
    require(identity in children,'historical child identity must belong to the retained own claim')
    lease=cached['resource_lease']
    require(type(lease) is dict and type(lease['lease_id']) is str and re.fullmatch('[0-9a-f]{32}',lease['lease_id']),
        'public old own scheduler lease identity required')
    return lease['lease_id']


def stopped(record,helpers):
    require(type(record['owner_pid']) is int and record['owner_pid']>0,'valid original own owner PID required')
    require(helpers['_process'](record['owner_pid']) is None,'original owner PID exists; PID reuse also blocks administrative reconciliation')
    children=[record.get('child'),*record.get('prior_children',())]
    require(len(children)<=17,'bounded original child history required')
    for child in children:
        if child is not None:
            require(type(child) is dict and type(child.get('pid')) is int and child['pid']>0 and type(child.get('birth')) is str,
                'valid own recorded child identity required')
        require(helpers['_group_usage'](child)['live_processes']==0,'a recorded own child process group remains alive')
    return dict(original_owner_PID_absent=True,reused_owner_PID_accepted=False,recorded_child_group_count=sum(child is not None for child in children),
        all_recorded_child_groups_dead=True,process_signal_calls=0)


def scheduler_absence(state,baseline,lease_id,owner_pid):
    require(type(state) is dict and state['config']==baseline['scheduler_observation']['config']
        and type(state['leases']) is dict and type(state['waiters']) is dict
        and all(type(key) is str and type(row) is dict for name in ('leases','waiters') for key,row in state[name].items()),
        'same config and typed copied lease/waiter maps required')
    require(lease_id not in state['leases'] and all(row.get('lease_id')!=lease_id and row.get('parent_lease_id')!=lease_id
        and row.get('owner_pid')!=owner_pid and row.get('request_id')!='daemon:'+TARGET
        for name in ('leases','waiters') for row in state[name].values()),'old own scheduler lease or pending request remains present')
    return dict(own_scheduler_lease_absent=True,own_scheduler_waiter_absent=True,
        scheduler_lease_count=len(state['leases']),scheduler_waiter_count=len(state['waiters']),foreign_IDs_or_bodies_published=False)


def main():
    require(sys.argv[1:]==[] and not os.path.lexists(OUTPUT),'exclusive argument-free preflight required')
    sys.addaudithook(audit);own=pin(Path(__file__).resolve());qualification=read(QUALIFICATION)
    require(qualification['schema']=='actor-features-retained-claim-preflight-source-independent-review/v1'
        and qualification['passed'] is True and qualification['findings']==[] and qualification['observer']==own,'exact source qualification required before private/process/attempt observation')
    for path,expected in qualification.get('artifacts',{}).items():
        require(all(pin(path)[key]==expected[key] for key in ('bytes','sha256')),'qualified source drift')
    baseline=read(BASELINE['path'],BASELINE);zero=read(ZERO['path'],ZERO);final=read(FINAL['path'],FINAL)
    receipt=read(SAMPLE['path'],SAMPLE)
    require(receipt['schema']=='actor-features-private-endpoints/v1' and receipt['role']=='opening' and receipt['cell'] is None and receipt['index']==3,
        'exact source-qualified opening3 receipt required')
    for name,endpoint in (('ledger',LEDGER),('scheduler',SCHEDULER)):
        require(receipt[name]['path']==str(F/'private-runtime-snapshots/opening-v03'/(name+'.json'))
            and receipt['source_'+name]['path']==str(endpoint)
            and all(receipt[name][key]==receipt['source_'+name][key] for key in ('bytes','sha256')),'exact private copy/source descriptor required')
        PRIVATE.add(Path(receipt[name]['path']))
    ledger=read(receipt['ledger']['path'],receipt['ledger']);state=read(receipt['scheduler']['path'],receipt['scheduler'])
    record,claims,conservation=qualify_ledger(ledger,baseline)
    lease_id=qualify_zero_evidence(zero,final,record);absence=scheduler_absence(state,baseline,lease_id,record['owner_pid'])
    helpers,durable=pure_resource_helpers()
    require(not helpers['_external_charges'](record),'external charges require a separate recovery protocol')
    attempt_identity=helpers['_root_identity'](ATTEMPT)
    require(record.get('attempt_directory')==attempt_identity,'exact original attempt identity required')
    processes=stopped(record,helpers);inventory=durable(ATTEMPT)
    require(inventory and sum(row['bytes'] for row in inventory)<=record['storage_bytes'],'nonempty durable artifact inventory within own original claim required')
    census=helpers['_inventory'](ROOTS)
    require([helpers['_root_identity'](root) for root in ROOTS]==ledger['roots'],'counted-root identities must match authenticated ledger')
    free=min(shutil.disk_usage(root).free for root in ROOTS);charged=census['apparent_bytes']+claims
    require(charged<=145000000000 and free>=claims,'existing API full-claim-charged before-write census must fit unchanged cap and physical availability')
    stopped(record,helpers)
    require(helpers['_root_identity'](ATTEMPT)==attempt_identity and durable(ATTEMPT)==inventory,'own attempt inventory changed during fullclaim census')
    for path,expected in list(READS.items()):pin(path,expected)
    result=dict(schema='actor-features-retained-claim-preflight/v1',passed=True,findings=[],observer=own,source_qualification=pin(QUALIFICATION),
        baseline=BASELINE,private_sample_receipt=SAMPLE,N8_zero_work_receipt=ZERO,N8_final_integration=FINAL,
        observed_at_utc=datetime.now(timezone.utc).isoformat(),retained_claim=dict(reservation_id=TARGET,record_body_sha256=TARGET_SHA,status='retained',storage_bytes=200000000),
        ledger_conservation=conservation,process_observation=processes,scheduler_observation=absence,
        actual_attempt_identity=attempt_identity,durable_artifact_inventory=inventory,durable_artifact_inventory_sha256=digest(inventory),
        attempt_bytes=sum(row['bytes'] for row in inventory),full_claim_charged_census=dict(inventory=census,observed_apparent_bytes=census['apparent_bytes'],
            outstanding_full_reservations_bytes=claims,additional_requested_bytes=0,charged_bytes=charged,limit_bytes=145000000000,
            minimum_filesystem_free_bytes=free),
        prospective_new200M_request_headroom_bytes=145000000000-(census['apparent_bytes']+claims-200000000+200000000),
        recovery_call=dict(ledger_path=str(LEDGER),roots=[str(root) for root in ROOTS],reservation_id=TARGET,
            expected_record_sha256=TARGET_SHA,attempt_directory=str(ATTEMPT),expected_artifacts=inventory,artifacts_durable=True),
        recovery_API=RECOVERY_PIN,qualified_current_resource_owner=OWNER_PIN,original_function_AST_preserved=True,
        recovery_plan_concrete=True,recovery_authorized=False,recovery_executed=False,claim_status_changes=0,claims_released=0,
        outputs_deleted=False,cap_changes=0,N7_claim_reconciliation_proposed=False,resource_reservation_class_constructed=False,
        scheduler_client_constructed=False,resource_API_calls=0,model_or_encoder_calls=0,checkpoint_JSON_parses=0,
        live_global_body_reads=0,copied_private_endpoint_JSON_parses=2,foreign_record_bodies_published=False,artifacts=READS,
        limitations=['Read-only preflight with exact old-output fsync; no global resource write or release is authorized by this receipt.',
            'PID/group observations and the copied scheduler are sampled; retained administrative API repeats liveness and accounting under its inherited ledger lock.',
            'Only administrative closeout of the named own N8 failed claim is proposed; N7 and every other535 record must remain unchanged.'])
    with OUTPUT.open('x') as out:json.dump(result,out,indent=2,sort_keys=True,allow_nan=False);out.write('\n')
    OUTPUT.chmod(0o444);print(json.dumps(pin(OUTPUT)))

if __name__=='__main__':main()
