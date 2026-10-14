"""Read-only, source-qualified copied-ledger conservation and named-root metadata census.

No production module or resource client is imported. Only the authenticated new
opening-v02 copied ledger body is parsed. The single census reads file metadata,
counts apparent bytes with the historical owner's pathname semantics, and emits
aggregate inode duplication plus the top20 immediate child directories.
"""
import ast
from collections import Counter
from datetime import datetime,timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import stat
import sys
import time

F=Path(__file__).resolve().parent
RUN=Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01')
FAILED=RUN/'actor-features-20261013-actor-features-ce-01'
OWNER=RUN.parent/'native4096-four-width-20261004/resource-cap/autoencoder_daemon_resources.py'
LEDGER=RUN.parent/'federal-corpus-audits/owned-daemon-resource-control/disk-reservations.json'
SCHEDULER=Path('/tmp/ipfs-datasets-resource-scheduler-1000.json')
ROOTS=(RUN.parent,RUN.parent.parent/'todo-queues',RUN.parent.parent.parent/'docs/implementation/reports/evidence',Path('/tmp/pytest-of-barberb'))
BASELINE=dict(path=str(F/'resource-baseline-v01.json'),bytes=77873,sha256='0d9930ff9831f0fb135439a066f0345e2fa3e9720a8827f74366253016b4f8f2')
SAMPLE=dict(path=str(F/'private-runtime-snapshots/opening-v02/snapshot-receipt-v01.json'),bytes=1414,sha256='453462b6446895b159e156e89f47beedfd1703959360e8bdb011e651b4f22bf0')
OWNER_PIN=dict(path=str(OWNER),bytes=36724,sha256='b00d2752ba852fe73760bba4fbd51b0e845742c3527642606a2a77ed9f8f5e2c')
QUALIFICATION=F/'storage-diagnostic-source-independent-review-v01.json'
OUTPUT=F/'actor-features-storage-diagnostic-v01.json'
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
            require('private-runtime-snapshots' not in target.parts or target in PRIVATE or target==Path(SAMPLE['path']),'only authenticated opening2 private ledger copy permitted')
        writing=isinstance(mode,str) and any(c in mode for c in 'wax+')
        writing|=isinstance(flags,int) and bool(flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
        require(not writing or target==OUTPUT and bool(flags&os.O_EXCL),'only exclusive own diagnostic write permitted')
    if event in {'os.chmod','os.chown','os.truncate','os.utime','os.link','os.symlink'}:
        require(event=='os.chmod' and Path(args[0]).absolute()==OUTPUT and args[1]==0o444,'only own diagnostic freeze permitted')


def owner_guards():
    """Compile only exact authenticated read-only metadata guards, never the resource class."""
    pin(OWNER,OWNER_PIN);tree=ast.parse(OWNER.read_bytes())
    names={'_safe_path','_checked_path','_root_identity','_inventory_descendant','_inventory_entry_disappeared'}
    nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
    error=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='DaemonResourceError')
    require(len(nodes)==len(names) and len(error.body)==1 and isinstance(error.body[0],ast.Expr),'exact source-only metadata guard closure required')
    ns=dict(Path=Path,os=os,stat=stat)
    exec(compile(ast.Module(body=[error,*nodes],type_ignores=[]),str(OWNER),'exec'),ns)
    return ns


def inventory(roots,guards):
    """Historical _inventory traversal with additional aggregate-only metadata counters."""
    count,total,symlinks,special=0,0,0,0
    root_identity=guards['_root_identity'];descendant=guards['_inventory_descendant'];disappeared=guards['_inventory_entry_disappeared']
    identities=[root_identity(root) for root in roots]
    lexical={root['path']:(named,(*reversed(named.parents),named)) for root in identities for named in (Path(root['path']),)}
    pending=[(lexical[root['path']][0],root,None) for root in identities]
    per_root={root['path']:dict(apparent_bytes=0,entry_count=0,symlink_count=0,special_file_count=0,direct_nondirectory_apparent_bytes=0) for root in identities}
    buckets={};seen={};regular_count=unique_count=regular_bytes=unique_bytes=repeat_count=repeat_bytes=size_variants=0
    while pending:
        directory,root,bucket=pending.pop()
        directory=descendant(root,directory,lexical_root=lexical[root['path']])
        if directory is None:continue
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    count+=1;per_root[root['path']]['entry_count']+=1
                    if bucket is not None:buckets[bucket]['entry_count']+=1
                    require(count<=2000000,'historical global2M inventory entry bound exceeded')
                    try:info=entry.stat(follow_symlinks=False)
                    except FileNotFoundError:
                        if not disappeared(root,entry.path):raise
                        continue
                    if stat.S_ISLNK(info.st_mode):
                        symlinks+=1;per_root[root['path']]['symlink_count']+=1;amount=info.st_size
                    elif stat.S_ISDIR(info.st_mode):
                        child_bucket=bucket
                        if child_bucket is None:
                            child_bucket=str(Path(entry.path));buckets[child_bucket]=dict(path=child_bucket,name=entry.name,root=root['path'],apparent_bytes=0,entry_count=1)
                        pending.append((Path(entry.path),root,child_bucket));continue
                    elif stat.S_ISREG(info.st_mode):
                        amount=info.st_size;regular_count+=1;regular_bytes+=amount;key=(info.st_dev,info.st_ino)
                        if key in seen:
                            repeat_count+=1;repeat_bytes+=amount;size_variants+=seen[key]!=amount
                        else:seen[key]=amount;unique_count+=1;unique_bytes+=amount
                    else:
                        special+=1;per_root[root['path']]['special_file_count']+=1;amount=info.st_size
                    total+=amount;per_root[root['path']]['apparent_bytes']+=amount
                    if bucket is None:per_root[root['path']]['direct_nondirectory_apparent_bytes']+=amount
                    else:buckets[bucket]['apparent_bytes']+=amount
        except FileNotFoundError:
            if descendant(root,directory) is not None:raise
    require([root_identity(Path(root['path'])) for root in identities]==identities,'storage root identity changed')
    require(sum(row['apparent_bytes'] for row in per_root.values())==total
        and sum(row['apparent_bytes'] for row in buckets.values())+sum(row['direct_nondirectory_apparent_bytes'] for row in per_root.values())==total,'aggregate census conservation differs')
    return dict(apparent_bytes=total,entry_count=count,symlink_count=symlinks,special_file_count=special,
        counted_root_metadata=identities,per_root=[dict(path=path,**row) for path,row in per_root.items()],
        direct_child_directory_count=len(buckets),top20_direct_child_directories=sorted(buckets.values(),key=lambda row:(-row['apparent_bytes'],row['path']))[:20],
        regular_inode_observations=dict(regular_path_count=regular_count,regular_path_apparent_bytes=regular_bytes,
            unique_sampled_inode_count=unique_count,first_observed_unique_inode_bytes=unique_bytes,
            repeated_inode_path_count=repeat_count,repeated_inode_path_apparent_bytes=repeat_bytes,inode_size_variation_count=size_variants),
        file_contents_read=0,per_file_paths_published=False,continuous_snapshot_claimed=False)


def qualify_copied_ledger(ledger,baseline,failed_id):
    prior=baseline['baseline_ledger'];expected=prior['record_body_hashes']
    require(baseline['schema']=='actor-features-resource-baseline/v1' and baseline['passed'] is True and baseline['findings']==[]
        and prior['record_count']==len(expected)==536 and digest(expected)==prior['record_body_hash_map_sha256'],'exact qualified536 baseline map required')
    require(type(ledger) is dict and set(ledger)=={'schema','roots','limit_bytes','reservations'}
        and ledger['schema']=='daemon-resource-reservations-v1' and ledger['limit_bytes']==145000000000
        and ledger['roots']==baseline['counted_root_metadata'],'same ledger schema/cap/fourroot scope required')
    bodies=ledger['reservations'];require(type(bodies) is dict and len(bodies)==536 and failed_id not in bodies,'no new failed own claim may exist')
    require({key:digest(body) for key,body in bodies.items()}==expected,'all536 prior record bodies must remain exact')
    require(all(type(body) is dict and body.get('reservation_id')==key and body.get('status') in {'reserved','active','retained','released'}
        and type(body.get('storage_bytes')) is int and body['storage_bytes']>=0 for key,body in bodies.items()),'valid existing fullclaims required')
    statuses=dict(Counter(body['status'] for body in bodies.values()))
    claims=sum(body['storage_bytes'] for body in bodies.values() if body['status']!='released')
    require(statuses==prior['record_status_counts']=={'released':434,'retained':102}
        and claims==prior['full_nonreleased_claim_bytes']==44581777216,'prior statuses/fullclaims changed')
    return dict(record_count=536,record_status_counts=statuses,full_nonreleased_claim_bytes=claims,
        record_body_hash_map_sha256=digest(expected),all_previous536_record_bodies_unchanged=True,
        failed_own_reservation_id_absent=True,new_records=0,full_record_bodies_published=False)


def failure_metadata():
    names={'pre-admission.json','failure-primary.json','resources-final-failure.json','child-exit.json','guardian-exit.json'}
    require({p.name for p in FAILED.iterdir()}==names and all(p.is_file() and not p.is_symlink() for p in FAILED.iterdir()),'exact five-file prechild failure inventory required')
    pre=read(FAILED/'pre-admission.json');failure=read(FAILED/'failure-primary.json');final=read(FAILED/'resources-final-failure.json')
    child=read(FAILED/'child-exit.json');terminal=read(FAILED/'guardian-exit.json')
    require(pre['guardian']==pin(F/'run_scope_guardian_v02.py') and pre['runner']==pin(F/'run_actor_features_v01.py')
        and pre['plan']==pin(F/'actor-features-ce-plan-v01.json'),'failed attempt source/plan custody differs')
    require(failure['model_started'] is False and failure['child_identity'] is None and child['child_created'] is False
        and child['returncode'] is None and child['leader_reaped'] is True and terminal['returncode']==1 and terminal['child_returncode'] is None,'prechild/no-model failure evidence required')
    snapshots=[failure['resources'],final['resources'],terminal['resources']]
    rid=snapshots[0]['reservation_id']
    require(type(rid) is str and len(rid)==32 and all(c in '0123456789abcdef' for c in rid)
        and all(row['reservation_id']==rid and row['record'] is None and row['resource_lease'] is None
            and row['scheduler_state_read'] is False for row in snapshots),'cached owner has no persisted record or acquired lease')
    frames=failure['error']['traceback_frames']
    require(failure['error']['error_type']=='DaemonResourceError' and any(row['file']==str(OWNER) and row['function']=='_account' and row['line']==399 for row in frames)
        and any(row['file']==str(OWNER) and row['function']=='__enter__' for row in frames),'authenticated owner account refusal frames required')
    return rid,dict(failed_attempt_path=str(FAILED),model_started=False,child_created=False,optimizer_updates=0,
        failure_in_owner_account_before_ledger_write=True,cached_owner_record_is_null=True,cached_owner_lease_is_null=True,
        guardian_generic_retention_flag_is_not_a_claim_existence_witness=True)


def main():
    require(sys.argv[1:]==[] and not os.path.lexists(OUTPUT),'exclusive argument-free diagnostic required')
    sys.addaudithook(audit);own=pin(Path(__file__).resolve())
    qualification=read(QUALIFICATION)
    require(qualification['schema']=='actor-features-storage-diagnostic-source-independent-review/v1'
        and qualification['passed'] is True and qualification['findings']==[] and qualification['observer']==own,'exact independent diagnostic source qualification required')
    for path,expected in qualification.get('artifacts',{}).items():
        require(all(pin(path)[key]==expected[key] for key in ('bytes','sha256')),'qualified source drift')
    baseline=read(BASELINE['path'],BASELINE);receipt=read(SAMPLE['path'],SAMPLE)
    require(receipt['schema']=='actor-features-private-endpoints/v1' and receipt['role']=='opening' and receipt['cell'] is None and receipt['index']==2
        and receipt['ledger']['path']==str(F/'private-runtime-snapshots/opening-v02/ledger.json')
        and receipt['source_ledger']['path']==str(LEDGER)
        and all(receipt['ledger'][key]==receipt['source_ledger'][key] for key in ('bytes','sha256')),'exact qualified opening2 copied ledger required')
    PRIVATE.add(Path(receipt['ledger']['path']))
    rid,failure=failure_metadata();ledger=read(receipt['ledger']['path'],receipt['ledger'])
    conservation=qualify_copied_ledger(ledger,baseline,rid)
    guards=owner_guards();start=time.monotonic();census=inventory(ROOTS,guards)
    require(census['counted_root_metadata']==ledger['roots'],'actual named-root metadata differs from conserved ledger')
    outstanding=conservation['full_nonreleased_claim_bytes'];requested=200000000
    free=min(shutil.disk_usage(root).free for root in ROOTS);charged=census['apparent_bytes']+outstanding+requested
    storage=dict(observed_apparent_bytes=census['apparent_bytes'],outstanding_full_reservations_bytes=outstanding,
        additional_requested_bytes=requested,charged_bytes=charged,limit_bytes=145000000000,minimum_filesystem_free_bytes=free,
        apparent_capacity_exceeded=charged>145000000000,physical_fullclaims_capacity_insufficient=free<outstanding+requested,
        apparent_capacity_headroom_bytes=145000000000-charged,physical_capacity_headroom_bytes=free-outstanding-requested,
        both_storage_predicates_pass=charged<=145000000000 and free>=outstanding+requested,admission_guaranteed=False)
    for path,expected in list(READS.items()):pin(path,expected)
    result=dict(schema='actor-features-storage-diagnostic/v1',passed=True,findings=[],observer=own,
        source_qualification=pin(QUALIFICATION),baseline=BASELINE,private_sample_receipt=SAMPLE,
        observed_at_utc=datetime.now(timezone.utc).isoformat(),elapsed_census_seconds=time.monotonic()-start,
        failure=failure,ledger_conservation=conservation,census=census,storage=storage,artifacts=READS,
        private_global_body_reads=0,copied_private_ledger_body_reads=1,copied_scheduler_body_reads=0,
        resource_API_calls=0,resource_owner_constructed=False,model_or_encoder_calls=0,checkpoint_JSON_parses=0,
        shared_state_modified=False,claim_releases=0,claim_transfers=0,cap_changes=0,cleanup_performed=False,retry_authorized=False,
        limitations=['Metadata census and physical availability are sampled, with historical shared-root churn semantics.',
            'Repeated inode observations may include concurrent inode reuse or file growth; no deduplicated cap or quota is substituted.',
            'Top20 paths are immediate child directories of fixed public named roots; no per-file paths or contents are emitted.'])
    with OUTPUT.open('x') as out:json.dump(result,out,indent=2,sort_keys=True,allow_nan=False);out.write('\n')
    OUTPUT.chmod(0o444);print(json.dumps(pin(OUTPUT)))

if __name__=='__main__':main()
