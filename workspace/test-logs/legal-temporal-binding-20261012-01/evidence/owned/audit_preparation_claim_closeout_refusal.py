"""Read-only failed administrative closeout audit and actual still-charged census."""
from datetime import datetime, timezone
import hashlib
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
from types import ModuleType, SimpleNamespace

F=Path(__file__).resolve().parent
OWN_ID='0350dfb651f943178d7b1cbc2113443e'
sys.dont_write_bytecode=True
class DenyModels(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] in {'torch','numpy','transformers','sentence_transformers'}:
            raise AssertionError('Numerical/model import prohibited: '+fullname)
        return None
sys.meta_path.insert(0,DenyModels())
def audit(event,args):
    if event.startswith(('socket.','subprocess.')) or event in {'os.system','os.fork','os.posix_spawn','os.kill','os.killpg','fcntl.flock'}:
        raise AssertionError('Read-only census refuses process/network/lock operations')
    if event=='open':
        path,mode,flags=args;write=isinstance(mode,str) and any(c in mode for c in 'wax+')
        write|=isinstance(flags,int) and bool(flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
        if write and (not isinstance(path,(str,bytes,os.PathLike)) or Path(os.fsdecode(path)).absolute().parent!=F):
            raise AssertionError('Only owned census receipts may be written')
sys.addaudithook(audit)
def pin(p):
    p=Path(p);b=p.read_bytes();return dict(path=str(p),bytes=len(b),sha256=hashlib.sha256(b).hexdigest())
def raw(x):return json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(x):return hashlib.sha256(raw(x)).hexdigest()
def read(p):return json.loads(Path(p).read_bytes())
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
def write(path,x):
    with path.open('x') as s:json.dump(x,s,sort_keys=True,indent=2,allow_nan=False);s.write('\n');s.flush();os.fsync(s.fileno())
def main():
    started=datetime.now(timezone.utc).isoformat()
    baseline=read(F/'storage-resource-endpoints-post-migration-v01.json')
    terminal=read(F/'training-runtime-resource-audit-v02.json')
    protocol_path=F/'owned-preparation-refusal-reconciliation-protocol-v01.json'
    protocol=read(protocol_path);attempt=F/'owned-preparation-refusal-reconciliation-attempt-01'
    failure=read(attempt/'failure-primary.json')
    assert failure['error_type']=='DaemonResourceError' and failure['message']=='storage reservation capacity exceeded'
    assert failure['observed_byte_class']=='exact_before' and failure['automatic_retry'] is False and failure['automatic_rollback'] is False
    assert {p.name for p in attempt.iterdir()}=={'attempt-started.json','failure-primary.json','ledger-before.local.json','ledger-observed-after-failure.local.json'}
    for key in ('helper',):assert pin(Path(protocol[key]['path']))==protocol[key]
    for p,expected in protocol['artifacts'].items():assert pin(p)==expected
    before_content=(attempt/'ledger-before.local.json').read_bytes()
    assert before_content==(attempt/'ledger-observed-after-failure.local.json').read_bytes()
    assert hashlib.sha256(before_content).hexdigest()==protocol['ledger_before']['sha256']
    assert failure['observed_ledger']==protocol['ledger_before']
    assert (F/'owned-preparation-claim-reconciliation-execution-v01.log').is_file()
    assert terminal['passed'] and terminal['owned_reservation_id']==OWN_ID and terminal['owned_record_status']=='retained'
    assert terminal['recorded_returned_prefix_updates']==0 and terminal['in_progress_or_unreported_partial_updates_unknown'] is False
    g=load('readonly_failure_census_guardian',F/'run_scope_guardian.py')
    current_guardian=pin(F/'run_scope_guardian.py')
    assert all(current_guardian[k]==baseline['guardian'][k] for k in ('bytes','sha256'))
    for p,sha in g.CLOSURE.items():assert pin(p)['sha256']==sha
    for name in ('ipfs_datasets_py','ipfs_datasets_py.optimizers','ipfs_datasets_py.optimizers.logic_theorem_optimizer'):
        m=ModuleType(name);m.__path__=[str(g.SOURCE.joinpath(*name.split('.')))];sys.modules[name]=m
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler
    owner=load('ipfs_datasets_py.optimizers.logic_theorem_optimizer.readonly_failure_census_owner',g.OWNER)
    def deny(*args,**kwargs):raise AssertionError('Reservation/client/mutation prohibited')
    owner.get_global_resource_scheduler=deny
    for name in ('__init__','__enter__','_locked','_write','release','finalize'):setattr(owner.DaemonResourceReservation,name,deny)
    before=pin(g.LEDGER);roots=[owner._root_identity(root) for root in g.ROOTS]
    probe=SimpleNamespace(ledger_path=g.LEDGER,_entered=False,root_identities=roots)
    ledger=owner.DaemonResourceReservation._read(probe)
    hashes={key:digest(row) for key,row in ledger['reservations'].items()}
    assert all(hashes.get(key)==sha for key,sha in baseline['record_body_hashes'].items())
    assert {k:v for k,v in hashes.items() if k!=OWN_ID}==protocol['prior_512_body_hashes']
    assert len(hashes)==513 and g.LEDGER.read_bytes()==before_content
    assert ledger['limit_bytes']==145_000_000_000 and roots==protocol['roots']
    assert sum(r['status']=='retained' for r in ledger['reservations'].values())==102
    assert sum(r['status']=='released' for r in ledger['reservations'].values())==411
    assert owner._process(643818) is None
    assert hashes[OWN_ID]==terminal['owned_record_body_sha256']
    state_path=Path(baseline['scheduler_before']['path']);state_before=pin(state_path);state=read(state_path)
    assert state['config']==baseline['scheduler_config'] and terminal['lease_id'] not in state['leases']
    identity=terminal['child_identity'];group=owner._group_usage(identity);assert group['live_processes']==0
    inventory=owner._inventory(g.ROOTS)
    outstanding=sum(row['storage_bytes'] for row in ledger['reservations'].values() if row['status']!='released')
    charged=inventory['apparent_bytes']+outstanding
    free=min(shutil.disk_usage(root).free for root in g.ROOTS)
    assert pin(g.LEDGER)==before==protocol['ledger_before'] and roots==[owner._root_identity(root) for root in g.ROOTS]
    assert outstanding==48_381_777_216
    for p,expected in protocol['artifacts'].items():assert pin(p)==expected
    state_after=pin(state_path);state2=read(state_path)
    assert state_after==state_before and state2['config']==state['config'] and terminal['lease_id'] not in state2['leases']
    assert owner._process(643818) is None
    current_group=owner._group_usage(identity);assert current_group['live_processes']==0
    eligible=charged<=owner.MAX_STORAGE_BYTES and free>=outstanding
    receipt=dict(schema='temporal-binding-administrative-closeout-refusal-readonly-census/v1',passed=True,findings=[],
        observed_at_start_utc=started,observed_at_end_utc=datetime.now(timezone.utc).isoformat(),
        helper=pin(Path(__file__)),baseline=pin(F/'storage-resource-endpoints-post-migration-v01.json'),
        terminal_runtime_audit=pin(F/'training-runtime-resource-audit-v02.json'),
        actual_closeout_failure=pin(attempt/'failure-primary.json'),actual_failed_closeout_unmodified=True,
        failed_closeout_ledger_byte_class='exact_before',full_local_before_observed_current_bytes_equal=True,
        all_prior_512_body_hashes=protocol['prior_512_body_hashes'],all_prior512_bodies_unchanged=True,
        previous_c6_released_record_body_unchanged=True,original_owner_absent=True,
        actual_existing_API_refused_full_claim_capacity_before_mutation=True,normal_API_called_by_observer=False,
        ledger_before=before,ledger_after=pin(g.LEDGER),record_count=len(hashes),
        old_511_record_body_hashes=baseline['record_body_hashes'],old_511_bodies_unchanged=True,
        owned_new_record_id=OWN_ID,owned_new_record_body_sha256=hashes[OWN_ID],
        owned_new_record_status=ledger['reservations'][OWN_ID]['status'],
        inventory=inventory,actual_outstanding_full_reservations_bytes=outstanding,
        additional_requested_bytes=0,own_retained200MB_already_charged_once=True,charged_bytes=charged,limit_bytes=owner.MAX_STORAGE_BYTES,
        current_charged_headroom_bytes=owner.MAX_STORAGE_BYTES-charged,
        prospective_separate_new_request_bytes=200_000_000,
        prospective_charge_with_existing_own_claim_still_retained=charged+200_000_000,
        prospective_extra200MB_not_in_actual_charged_census=True,
        observed_over_limit_bytes=max(0,charged-owner.MAX_STORAGE_BYTES),
        physical_free_bytes=free,full_still_charged_reconciliation_arithmetic_eligible_at_observation=eligible,
        own_claim_bytes=ledger['reservations'][OWN_ID]['storage_bytes'],
        arithmetic_after_hypothetical_own_release=charged-ledger['reservations'][OWN_ID]['storage_bytes'],
        hypothetical_release_performed=False,hypothetical_release_is_not_API_authority=True,
        scheduler_before=state_before,scheduler_after=state_after,
        scheduler_endpoint_bytes_unchanged=state_before==state_after,
        shared_config_unchanged=True,owned_lease_absent=True,current_owned_group=current_group,
        resource_producers=baseline['producers'],claims_modified=False,limits_modified=False,
        locks_acquired=0,scheduler_clients=0,reservations_constructed=0,model_calls=0,optimizer_updates=0,
        full_local_ledger_backup_bodies_published=False,continuous_custody_claimed=False)
    out=F/'storage-census-after-closeout-refusal-v02.json';write(out,receipt)
    print(json.dumps({k:receipt[k] for k in ('passed','charged_bytes','observed_over_limit_bytes','actual_outstanding_full_reservations_bytes','current_charged_headroom_bytes','full_still_charged_reconciliation_arithmetic_eligible_at_observation')},sort_keys=True))
if __name__=='__main__':main()
