"""Observe actual own-claim closure, then run one of two fresh strict censuses."""
import argparse
from datetime import datetime,timezone
import hashlib
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
from types import ModuleType,SimpleNamespace

F=Path(__file__).resolve().parent
COMP=F/'owned-preparation-refusal-reconciliation-attempt-01/completion.json'
OWN='0350dfb651f943178d7b1cbc2113443e'
sys.dont_write_bytecode=True
class DenyModels(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] in {'torch','numpy','transformers','sentence_transformers'}:
            raise AssertionError('Numerical/model import prohibited: '+fullname)
        return None
sys.meta_path.insert(0,DenyModels())
def audit(event,args):
    if event.startswith(('socket.','subprocess.')) or event in {'os.system','os.fork','os.posix_spawn','os.kill','os.killpg','fcntl.flock'}:
        raise AssertionError('Read-only closeout observer refuses process/network/lock operation')
    if event=='open':
        path,mode,flags=args;write=isinstance(mode,str) and any(c in mode for c in 'wax+')
        write|=isinstance(flags,int) and bool(flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
        if write and (not isinstance(path,(str,bytes,os.PathLike)) or Path(os.fsdecode(path)).absolute().parent!=F):
            raise AssertionError('Only owned observation receipts may be written')
sys.addaudithook(audit)
def require(x,message):
    if not x:raise ValueError(message)
def raw(x):return json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(x):return hashlib.sha256(raw(x)).hexdigest()
def pin(p):
    p=Path(p);require(p.is_file() and not p.is_symlink(),'ordinary observation artifact required')
    before=p.stat();b=p.read_bytes();after=p.stat()
    ident=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    require(ident(before)==ident(after),'artifact changed during read')
    return dict(path=str(p),bytes=len(b),sha256=hashlib.sha256(b).hexdigest())
def read(p):return json.loads(Path(p).read_bytes())
def write(p,x):
    with p.open('x') as s:json.dump(x,s,sort_keys=True,indent=2,allow_nan=False);s.write('\n');s.flush();os.fsync(s.fileno())
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--scan',type=int,choices=(3,4),required=True);args=ap.parse_args()
    started=datetime.now(timezone.utc).isoformat();completion=read(COMP)
    require(completion['complete'] is True and completion['own_claim_released'] is True
            and completion['reservation_id']==OWN and completion['own_released_bytes']==200_000_000,'actual own closure required')
    for field in ('helper','protocol','independent_review'):require(pin(Path(completion[field]['path']))==completion[field],'closeout source/review changed')
    protocol=read(Path(completion['protocol']['path']));before_path=Path(completion['before_local_backup']['path'])
    planned_path=Path(completion['planned_after_local_backup']['path']);after_path=Path(completion['after_local_backup']['path'])
    for field,path in [('before_local_backup',before_path),('planned_after_local_backup',planned_path),('after_local_backup',after_path)]:
        require(pin(path)==completion[field],'local backup changed')
    before_content=before_path.read_bytes();after_content=after_path.read_bytes()
    require(after_content==planned_path.read_bytes(),'planned and actual after bytes differ')
    before=read(before_path);after=read(after_path)
    require(raw(before)+b'\n'==before_content and raw(after)+b'\n'==after_content,'canonical local backups required')
    require(all(completion['before'][k]==pin(before_path)[k] for k in ('bytes','sha256')),'original backup differs from admitted endpoint')
    require({k:v for k,v in before.items() if k!='reservations'}=={k:v for k,v in after.items() if k!='reservations'},'cap/schema/roots changed')
    old_hashes=protocol['prior_512_body_hashes']
    require({k:digest(v) for k,v in after['reservations'].items() if k!=OWN}==old_hashes,'prior512 bodies changed')
    require({k:v for k,v in before['reservations'].items() if k!=OWN}=={k:v for k,v in after['reservations'].items() if k!=OWN},'foreign claims changed')
    require(len(before['reservations'])==len(after['reservations'])==513,'record count changed')
    old_statuses={state:sum(row['status']==state for key,row in after['reservations'].items() if key!=OWN)
                  for state in ('retained','released','active','reserved')}
    require(old_statuses==dict(retained=101,released=411,active=0,reserved=0),'old retained/released census differs')
    require(digest(before['reservations'][OWN])==protocol['own_record_body_sha256'],'original own claim differs')
    own=after['reservations'][OWN];event=own['explicit_reconciliation']
    require(own['status']=='released' and own['artifacts_durable_asserted'] is True and own['final_attempt_bytes']==61141
            and own['final_external_charged_bytes']==0 and own['final_total_charged_bytes']==61141,'own released accounting differs')
    require(event['schema']=='explicit-retained-reservation-reconciliation/v1' and event['reservation_id']==OWN
            and event['previous_record_sha256']==protocol['own_record_body_sha256']
            and event['original_owner_pid']==643818 and event['artifacts']==protocol['expected_artifacts']
            and event['outputs_deleted'] is False and event['automatic_expiry'] is False and event['admitted'] is False,'normal exact recovery event differs')
    require(event['other_reservations_sha256']==digest({k:v for k,v in before['reservations'].items() if k!=OWN}),'other-record recovery digest differs')
    full=event['full_claim_accounting'];final=event['final_accounting']
    require(full['charged_bytes']<=145_000_000_000 and full['outstanding_full_reservations_bytes']==48_381_777_216
            and final['charged_bytes']==full['charged_bytes']-200_000_000
            and final['outstanding_full_reservations_bytes']==48_181_777_216,'API still-charged/final arithmetic differs')
    for p,expected in protocol['artifacts'].items():
        if p==protocol['ledger_before']['path']:continue
        require(pin(Path(p))==expected,'preserved source/evidence drift: '+p)
    ledger_path=Path(completion['after']['path']);ledger_before=pin(ledger_path)
    require(ledger_before==completion['after'] and ledger_path.read_bytes()==after_content,'live closing ledger differs')
    baseline=read(F/'storage-resource-endpoints-post-migration-v01.json')
    runtime=read(F/'training-runtime-resource-audit-v02.json')
    g=load('readonly_retry_census_guardian',F/'run_scope_guardian.py')
    for p,sha in g.CLOSURE.items():require(pin(p)['sha256']==sha,'resource source drift')
    for name in ('ipfs_datasets_py','ipfs_datasets_py.optimizers','ipfs_datasets_py.optimizers.logic_theorem_optimizer'):
        m=ModuleType(name);m.__path__=[str(g.SOURCE.joinpath(*name.split('.')))];sys.modules[name]=m
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler
    resources=load('ipfs_datasets_py.optimizers.logic_theorem_optimizer.readonly_retry_census_owner',g.OWNER)
    def denied(*args,**kwargs):raise AssertionError('Observer refuses reservations/clients/mutations')
    resources.get_global_resource_scheduler=denied
    for name in ('__init__','__enter__','_locked','_write','release','finalize'):setattr(resources.DaemonResourceReservation,name,denied)
    roots=[resources._root_identity(root) for root in g.ROOTS]
    require(roots==protocol['roots']==after['roots'],'actual named roots changed')
    probe=SimpleNamespace(ledger_path=ledger_path,_entered=False,root_identities=roots)
    require(resources.DaemonResourceReservation._read(probe)==after,'ordinary owner ledger reader differs')
    require(resources._process(643818) is None,'original owner PID present')
    group=resources._group_usage(runtime['child_identity']);require(group['live_processes']==0,'old owned child group alive')
    state_path=Path(protocol['scheduler']['state']['path']);state_before=pin(state_path);state=read(state_path)
    require(state['config']==baseline['scheduler_config'] and runtime['lease_id'] not in state['leases'],'scheduler config or own lease changed')
    if args.scan==4:
        first=read(F/'retry-storage-census-03.json')
        require(first['passed'] and first['requested_storage_fits_at_observation'],'first strict census must pass')
        require(first['ledger_after']==ledger_before and first['scheduler_after']==state_before
                and first['root_identities']==roots,'endpoints changed between strict censuses')
        require(first['helper']==pin(Path(__file__)),'census helper changed between scans')
    inventory=resources._inventory(g.ROOTS)
    outstanding=sum(row['storage_bytes'] for row in after['reservations'].values() if row['status']!='released')
    require(outstanding==48_181_777_216,'old outstanding full claims differ')
    requested=200_000_000;charged=inventory['apparent_bytes']+outstanding+requested
    free=min(shutil.disk_usage(root).free for root in g.ROOTS)
    require(pin(ledger_path)==ledger_before and roots==[resources._root_identity(root) for root in g.ROOTS],'ledger/root endpoints changed during census')
    state_after=pin(state_path);require(state_before==state_after,'scheduler endpoint changed during census')
    for field in ('helper','protocol','independent_review'):
        require(pin(Path(completion[field]['path']))==completion[field],'closeout source/review changed during census')
    for p,expected in protocol['artifacts'].items():
        if p==protocol['ledger_before']['path']:continue
        require(pin(Path(p))==expected,'source/evidence endpoint changed during census: '+p)
    require(resources._process(643818) is None and resources._group_usage(runtime['child_identity'])['live_processes']==0,
            'original owner or owned child group present after census')
    fits=charged<=145_000_000_000 and free>=outstanding+requested
    output=dict(schema='owned-closeout-strict-retry-storage-census/v1',passed=True,findings=[],scan=args.scan,
        observed_at_start_utc=started,observed_at_end_utc=datetime.now(timezone.utc).isoformat(),helper=pin(Path(__file__)),
        closeout_completion=pin(COMP),closeout_independent_review=completion['independent_review'],
        ledger_before=ledger_before,ledger_after=pin(ledger_path),scheduler_before=state_before,scheduler_after=state_after,
        root_identities=roots,all_prior_512_claim_bodies_unchanged=True,all_old_511_claim_bodies_unchanged=True,previous_c6_released_body_unchanged=True,exact_own_claim_released=True,
        prior_512_status_counts=old_statuses,all_101_old_retained_claims_charged_in_full=True,
        owned_released_record_body_sha256=digest(own),record_count=513,
        private_before_planned_actual_canonical_ledger_backups_equal=True,
        immutable_failed_attempt_15_file_bytes=61141,failed_attempt_files=protocol['expected_artifacts'],
        inventory=inventory,outstanding_full_reservations_bytes=outstanding,
        requested_storage_bytes=requested,requested200MB_charged_once=True,charged_bytes=charged,
        storage_limit_bytes=145_000_000_000,requested_storage_fits_at_observation=fits,
        remaining_charged_headroom_bytes=145_000_000_000-charged,minimum_filesystem_free_bytes=free,
        actual_admission_performed=False,admission_guaranteed=False,model_calls=0,optimizer_updates=0,
        locks_acquired=0,clients_constructed=0,reservations_constructed=0,
        claims_modified=False,limits_modified=False,full_local_backup_bodies_published=False,continuous_custody_claimed=False)
    write(F/f'retry-storage-census-{args.scan:02d}.json',output)
    if args.scan==3:
        write(F/'owned-preparation-claim-closeout-postaudit-v01.json',dict(schema='owned-preparation-refusal-closeout-postaudit/v1',passed=True,findings=[],
            actual_completion=pin(COMP),canonical_local_before_planned_actual_backups_verified=True,
            exact_only_own_record_changed=True,all_prior_512_body_hashes=old_hashes,all_old_511_body_hashes=baseline["record_body_hashes"],
            owned_released_record_body_sha256=digest(own),cap_unchanged=True,roots_unchanged=True,
            source_bytes_unchanged=True,failed15_file_manifest_unchanged=True,
            original_owner_absent=True,old_child_group_absent=True,old_owned_lease_absent=True,
            normal_existing_reconciliation_API_event_verified=True,full_still_charged_census_verified=True,
            model_calls=0,optimizer_updates=0,observer_claim_changes=0,observer_locks=0,
            observer_admission=False,full_local_ledger_backups_private=True,first_census=pin(F/'retry-storage-census-03.json')))
    print(json.dumps({k:output[k] for k in ('scan','passed','requested_storage_fits_at_observation','charged_bytes','remaining_charged_headroom_bytes')},sort_keys=True))
if __name__=='__main__':main()
