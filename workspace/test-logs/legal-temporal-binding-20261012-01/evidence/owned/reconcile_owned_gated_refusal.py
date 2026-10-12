"""Reviewed administrative reconciliation of only our retained gated-child claim.

Uses the existing reconcile_retained_reservation API, including its fresh census
with the full claim still charged. Never adopts the original owner, admits work,
changes a cap, or edits any other claim. Full ledger backups remain local.
"""
from contextlib import contextmanager
import hashlib
import importlib.abc
import importlib.util
import json
import math
import os
from pathlib import Path
import stat
import sys
import time
from types import ModuleType
import argparse

F=Path(__file__).resolve().parent
PROTOCOL=F/'owned-gated-refusal-reconciliation-protocol-v04.json'
OUT=F/'owned-gated-refusal-reconciliation-attempt-02'
OWN='c6ea2674cee9469494468d688a90ca4e'
WRITE_GATE=None
LEDGER=Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/federal-corpus-audits/owned-daemon-resource-control/disk-reservations.json')
sys.dont_write_bytecode=True
class DenyModels(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] in {'torch','numpy','transformers','sentence_transformers'}:
            raise AssertionError('Numerical/model import prohibited: '+fullname)
        return None
sys.meta_path.insert(0,DenyModels())
def require(x,message):
    if not x:raise ValueError(message)
def raw(x):return json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(x):return hashlib.sha256(raw(x)).hexdigest()
def ordinary(p,directory=False):
    p=Path(os.path.abspath(os.fspath(p)))
    for part in (*reversed(p.parents),p):
        i=part.lstat();require(not stat.S_ISLNK(i.st_mode),'symlink refused')
        require(stat.S_ISDIR(i.st_mode) if part!=p or directory else stat.S_ISREG(i.st_mode),'ordinary path required')
    return p
def pin(p):
    p=ordinary(p);before=p.stat();b=p.read_bytes();after=p.stat()
    ident=lambda i:(i.st_dev,i.st_ino,i.st_size,i.st_mtime_ns,i.st_ctime_ns)
    require(ident(before)==ident(after),'artifact changed while read')
    return dict(path=str(p),bytes=len(b),sha256=hashlib.sha256(b).hexdigest())
def read(p):
    require(pin(p)['bytes']<=16*1024*1024,'bounded JSON required')
    def unique(pairs):
        x={}
        for k,v in pairs:require(k not in x,'duplicate JSON field');x[k]=v
        return x
    def reject(value):raise ValueError('nonfinite JSON: '+value)
    x=json.loads(Path(p).read_bytes(),object_pairs_hook=unique,parse_constant=reject)
    def finite(v):
        if isinstance(v,float):require(math.isfinite(v),'nonfinite parsed number')
        elif isinstance(v,list):
            for i in v:finite(i)
        elif isinstance(v,dict):
            for i in v.values():finite(i)
    finite(x);return x
def load(name,p):
    spec=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
def sync_dir(p):
    fd=os.open(ordinary(p,True),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)
def save_bytes(p,b):
    require(p.parent==OUT,'receipt must stay in exclusive owned closeout')
    fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        WRITE_GATE.register(fd,p,'owned_output')
        with os.fdopen(fd,'wb') as s:s.write(b);s.flush();os.fsync(s.fileno())
    finally:
        WRITE_GATE.forget(fd)
        try:os.close(fd)
        except OSError:pass
    sync_dir(OUT);return pin(p)
def save(p,x):return save_bytes(p,json.dumps(x,sort_keys=True,indent=2,allow_nan=False).encode()+b'\n')
def source_fences(protocol,protocol_pin,review_path,review_pin):
    require(pin(Path(__file__))==protocol['helper'],'closeout helper drift')
    require(pin(PROTOCOL)==protocol_pin,'closeout protocol drift')
    require(pin(review_path)==review_pin,'closeout independent review drift')
    for p,expected in protocol['artifacts'].items():
        if p==protocol['ledger_before']['path']:continue
        require(pin(Path(p))==expected,'closeout source/evidence drift: '+p)
    scheduler_fence(protocol)
def scheduler_fence(protocol):
    state=read(Path(protocol['scheduler']['state']['path']))
    require(digest(state['config'])==protocol['scheduler']['config_sha256'],'scheduler configuration changed')
    require(protocol['scheduler']['owned_lease_id'] not in state['leases'],'owned lease reappeared')
def lock_fence(helper,protocol):
    require(pin(helper.lock_path)==protocol['lock']['artifact'],'existing stable lock bytes changed')
    st=helper.lock_path.lstat()
    require(dict(device=st.st_dev,inode=st.st_ino,nlink=st.st_nlink)==protocol['lock']['identity'],'stable lock identity changed')
def others_hashes(ledger):return {k:digest(v) for k,v in ledger['reservations'].items() if k!=OWN}
def validate_before(ledger,protocol):
    require(set(ledger)=={'schema','roots','limit_bytes','reservations'} and ledger['schema']=='daemon-resource-reservations-v1','closed ledger required')
    require(ledger['limit_bytes']==145_000_000_000 and ledger['roots']==protocol['roots'],'unchanged cap/roots required')
    rows=ledger['reservations'];require(len(rows)==512 and set(rows)==set(protocol['old_511_body_hashes'])|{OWN},'exact current 512 records required')
    require(others_hashes(ledger)==protocol['old_511_body_hashes'],'another claim body changed')
    r=rows[OWN];require(digest(r)==protocol['own_record_body_sha256'],'exact own retained body changed')
    require(r['status']=='retained' and r['owner_pid']==3850209 and r['storage_bytes']==200_000_000
            and r['memory_mb']==1536 and r['cpu_slots']==2 and r['child_process_slots']==1,'own claim identity/envelope differs')
    require(r['child']==dict(pid=3855138,birth='78423735') and r['prior_children']==[]
            and r['external_charges']=={} and r['attempt_directory']==protocol['attempt_identity'],'exact gated claim required')
    require(sum(v['status']=='retained' for v in rows.values())==102 and sum(v['status']=='released' for v in rows.values())==410,'status counts drift')
    require(not any(v['status'] in {'active','reserved'} for v in rows.values()),'live reservations prevent concrete closeout')

def main():
    global WRITE_GATE
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--apply',action='store_true');ap.add_argument('--review',type=Path)
    args=ap.parse_args();protocol=read(PROTOCOL);protocol_pin=pin(PROTOCOL)
    require(protocol['schema']=='owned-gated-refusal-reconciliation-protocol/v1' and protocol['reservation_id']==OWN,'exact own protocol required')
    require(pin(Path(__file__))==protocol['helper'],'authenticated closeout helper required')
    for p,expected in protocol['artifacts'].items():require(pin(Path(p))==expected,'prepared binding differs: '+p)
    require(not OUT.exists(),'one-shot closeout attempt already exists')
    review_pin=None
    if args.review:
        review=read(args.review);review_pin=pin(args.review)
        require(review.get('passed') is True and review.get('findings')==[] and review.get('phase')=='owned-claim-reconciliation','clean concrete own-claim review required')
        require(review.get('helper_sha256')==protocol['helper']['sha256'] and review.get('protocol_sha256')==protocol_pin['sha256']
                and review.get('reservation_id')==OWN and review.get('output_directory')==str(OUT),'review bindings differ')
        require(review.get('expected_ledger_sha256')==protocol['ledger_before']['sha256'],'review ledger endpoint differs')
        required={str(Path(__file__)),str(PROTOCOL),*protocol['artifacts'].keys()}
        require(required<=set(review.get('artifacts',{})),'complete reviewed artifact bindings required')
        for p,expected in review['artifacts'].items():
            actual=pin(Path(p));require(actual['bytes']==expected['bytes'] and actual['sha256']==expected['sha256'],'reviewed artifact drift')
    require(not args.apply or review_pin is not None,'apply requires independent concrete review')
    gate_module=load('owned_closeout_write_gate',Path(protocol['write_gate']['path']))
    require(pin(Path(gate_module.__file__))==protocol['write_gate'],'write gate source changed after authenticated import')
    require(pin(Path(gate_module.tempfile.__file__))==protocol['stdlib_tempfile'],'imported tempfile source outside authenticated fixture runtime')
    WRITE_GATE=gate_module.ReviewedWriteGate(OUT,LEDGER,
        (protocol['lock']['identity']['device'],protocol['lock']['identity']['inode']),
        (protocol['ledger_parent_identity']['device'],protocol['ledger_parent_identity']['inode']))
    sys.addaudithook(WRITE_GATE.audit)
    g=load('owned_refusal_recovery_guardian',Path(protocol['guardian']['path']))
    require(pin(Path(g.__file__))==protocol['guardian'],'guardian changed after authenticated import')
    for p,sha in g.CLOSURE.items():require(pin(p)['sha256']==sha,'resource closure drift')
    for name in ('ipfs_datasets_py','ipfs_datasets_py.optimizers','ipfs_datasets_py.optimizers.logic_theorem_optimizer'):
        require(name not in sys.modules,'fresh inert namespace required');m=ModuleType(name);m.__path__=[str(g.SOURCE.joinpath(*name.split('.')))];sys.modules[name]=m
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler
    resources=load('ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_daemon_resources',g.OWNER)
    setattr(sys.modules['ipfs_datasets_py.optimizers.logic_theorem_optimizer'],'autoencoder_daemon_resources',resources)
    def denied(*args,**kwargs):raise AssertionError('Closeout never admits work, acquires leases or adopts original owner')
    resources.get_global_resource_scheduler=denied;resources.DaemonResourceReservation.__enter__=denied
    recovery=load('ipfs_datasets_py.optimizers.logic_theorem_optimizer.owned_refusal_recovery',Path(protocol['recovery_api']['path']))
    require(recovery.resources is resources,'API resource authority differs')
    ledger_path=Path(protocol['ledger_before']['path']);before_bytes=ledger_path.read_bytes();before=read(ledger_path)
    require(ledger_path==LEDGER,'exact shared ledger required')
    require(pin(ledger_path)==protocol['ledger_before'],'fresh original ledger bytes differ');validate_before(before,protocol)
    attempt=Path(protocol['attempt_identity']['path']);require(resources._root_identity(attempt)==protocol['attempt_identity'],'failed attempt replaced')
    require(resources._process(before['reservations'][OWN]['owner_pid']) is None,'original owner PID still exists or reused')
    require(resources._group_usage(before['reservations'][OWN]['child'])['live_processes']==0,'owned child group alive')
    require([resources._root_identity(Path(r['path'])) for r in protocol['roots']]==protocol['roots'],'actual ledger roots drift')
    scheduler_fence(protocol)
    if not args.apply:
        print(json.dumps(dict(schema='owned-claim-reconciliation-preflight/v1',passed=True,mutation_performed=False,
            reservation_id=OWN,helper=protocol['helper'],protocol=protocol_pin,review=review_pin,
            actual_original_owner_absent=True,actual_child_group_absent=True,
            census_still_required_by_API=True,artifacts_not_yet_fsynced_by_API=True),sort_keys=True));return
    OUT.mkdir(mode=0o700);sync_dir(F)
    WRITE_GATE.arm()
    save(OUT/'attempt-started.json',dict(schema='owned-claim-reconciliation-attempt/v1',helper=protocol['helper'],protocol=protocol_pin,
        review=review_pin,reservation_id=OWN,full_local_ledger_backups_excluded_from_publication=True,
        original_owner_adopted=False,training_started=False,leases_acquired=0))
    original_lock=resources.DaemonResourceReservation._locked
    original_write=resources.DaemonResourceReservation._write
    writes=[];stage='API_invocation';pre_backup=None;proposed_backup=None
    @contextmanager
    def fenced_lock(helper):
        nonlocal stage,pre_backup
        with original_lock(helper):
            stage='locked_source_and_ledger_fences'
            source_fences(protocol,protocol_pin,args.review,review_pin)
            lock_fence(helper,protocol)
            require(helper._record is None and helper._lease is None and not helper._entered,'administrative helper must not reserve')
            require(pin(ledger_path)==protocol['ledger_before'] and ledger_path.read_bytes()==before_bytes,'ledger changed under lock')
            validate_before(helper._read(),protocol)
            pre_backup=save_bytes(OUT/'ledger-before.local.json',before_bytes)
            yield
    def fenced_write(helper,proposed):
        nonlocal stage,proposed_backup
        stage='API_proposed_write_validation'
        require(not writes,'exactly one API ledger write allowed');source_fences(protocol,protocol_pin,args.review,review_pin)
        require(pin(ledger_path)==protocol['ledger_before'],'original ledger changed before API write')
        require({k:v for k,v in proposed.items() if k!='reservations'}=={k:v for k,v in before.items() if k!='reservations'},'cap/schema/roots changed')
        require(others_hashes(proposed)==protocol['old_511_body_hashes'] and set(proposed['reservations'])==set(before['reservations']),'foreign claims changed')
        new=proposed['reservations'][OWN];old=before['reservations'][OWN]
        changed={k for k in set(old)|set(new) if old.get(k)!=new.get(k)}
        allowed={'status','artifacts_durable_asserted','released_at','final_accounting','final_attempt_bytes','final_external_charged_bytes','final_total_charged_bytes','attempt_exceeded_reservation','explicit_reconciliation'}
        require(changed<=allowed and new['status']=='released' and new['artifacts_durable_asserted'] is True,'unexpected own fields changed')
        require(new['final_attempt_bytes']==53_597 and new['final_external_charged_bytes']==0 and new['final_total_charged_bytes']==53_597
                and new['attempt_exceeded_reservation'] is False,'exact immutable failed attempt accounting differs')
        event=new['explicit_reconciliation'];require(event['schema']=='explicit-retained-reservation-reconciliation/v1'
                and event['reservation_id']==OWN and event['previous_record_sha256']==protocol['own_record_body_sha256']
                and event['artifacts']==protocol['expected_artifacts'] and event['outputs_deleted'] is False
                and event['automatic_expiry'] is False and event['admitted'] is False,'existing API recovery evidence differs')
        require(event['full_claim_accounting']['outstanding_full_reservations_bytes']==48_381_777_216
                and event['full_claim_accounting']['charged_bytes']<=145_000_000_000,'full still-charged census required')
        proposed_backup=save_bytes(OUT/'ledger-after-planned.local.json',raw(proposed)+b'\n')
        save(OUT/'planned-mutation.json',dict(schema='owned-claim-planned-closeout/v1',reservation_id=OWN,
            before=pre_backup,planned_after=proposed_backup,record_count=512,old_511_body_hashes=protocol['old_511_body_hashes'],
            full_claim_accounting=event['full_claim_accounting'],cap_changed=False,other_claims_changed=False,
            failed_attempt_outputs_modified=False,original_owner_adopted=False,local_ledger_copies_private=True))
        helper._verify_owner_roots();source_fences(protocol,protocol_pin,args.review,review_pin)
        lock_fence(helper,protocol)
        stage='atomic_existing_owner_API_write'
        with WRITE_GATE.atomic_writer():original_write(helper,proposed)
        writes.append(digest(proposed))
        stage='postwrite_readback';helper._verify_owner_roots();source_fences(protocol,protocol_pin,args.review,review_pin)
        lock_fence(helper,protocol)
        require(helper._read()==proposed and ledger_path.read_bytes()==raw(proposed)+b'\n','postwrite API readback differs')
    resources.DaemonResourceReservation._locked=fenced_lock;resources.DaemonResourceReservation._write=fenced_write
    try:
        event=recovery.reconcile_retained_reservation(ledger_path,roots=[r['path'] for r in protocol['roots']],
            reservation_id=OWN,expected_record_sha256=protocol['own_record_body_sha256'],attempt_directory=attempt,
            expected_artifacts=protocol['expected_artifacts'],artifacts_durable=True)
        require(len(writes)==1,'normal API did not perform exactly one closeout write')
        current=read(ledger_path);require(digest(current)==writes[0],'closing ledger differs after API released lock')
        require(others_hashes(current)==protocol['old_511_body_hashes'],'old claims differ after closeout')
        source_fences(protocol,protocol_pin,args.review,review_pin)
        actual_after=save_bytes(OUT/'ledger-after.local.json',ledger_path.read_bytes())
        final=save(OUT/'completion.json',dict(schema='owned-gated-refusal-reconciliation-result/v1',complete=True,
            helper=protocol['helper'],protocol=protocol_pin,independent_review=review_pin,reservation_id=OWN,
            before=protocol['ledger_before'],after=pin(ledger_path),before_local_backup=pre_backup,
            planned_after_local_backup=proposed_backup,after_local_backup=actual_after,
            normal_existing_reconciliation_API_used=True,existing_lock_and_atomic_writer_used=True,
            all_old_511_claim_bodies_unchanged=True,record_count_before=512,record_count_after=512,
            only_own_claim_changed=True,own_claim_released=True,own_released_bytes=200_000_000,
            durable_failed_attempt_bytes=53_597,full_claim_accounting=event['full_claim_accounting'],final_accounting=event['final_accounting'],
            original_owner_adopted=False,cap_changed=False,source_files_modified=False,outputs_deleted=False,
            model_calls=0,optimizer_updates=0,training_started=False,leases_acquired=0,
            failed_attempt_immutable=True,no_automatic_retry=True,local_full_ledger_backups_excluded_from_publication=True))
        print(json.dumps(final,sort_keys=True))
    except BaseException as error:
        try:
            failure=dict(schema='owned-claim-closeout-failure/v1',stage=stage,error_type=type(error).__name__,
                message=str(error)[:2048],observed_byte_class='unavailable',
                original_failure_preserved=True,automatic_rollback=False,automatic_retry=False,
                authority_to_overwrite_observed_parallel_bytes=False,recovery_requires_fresh_independent_review=True,
                training_started=False,model_calls=0,leases_acquired=0,local_ledger_backups_private=True)
            try:
                observed=pin(ledger_path)
                failure['observed_ledger']=observed
                failure['observed_byte_class']=('exact_before' if observed['sha256']==protocol['ledger_before']['sha256'] else
                    'exact_planned_after' if proposed_backup is not None and observed['sha256']==proposed_backup['sha256'] else
                    'different_bytes_preserved')
                failure['observed_local_backup']=save_bytes(OUT/'ledger-observed-after-failure.local.json',ledger_path.read_bytes())
            except BaseException as observation_error:
                failure['endpoint_observation_or_backup_error']=dict(type=type(observation_error).__name__,message=str(observation_error)[:1024])
            save(OUT/'failure-primary.json',failure)
        except BaseException as receipt_error:
            try:error.add_note('Closeout failure receipt also failed: '+type(receipt_error).__name__+': '+str(receipt_error)[:1024])
            except BaseException:pass
        raise
    finally:
        resources.DaemonResourceReservation._locked=original_lock;resources.DaemonResourceReservation._write=original_write
if __name__=='__main__':main()
