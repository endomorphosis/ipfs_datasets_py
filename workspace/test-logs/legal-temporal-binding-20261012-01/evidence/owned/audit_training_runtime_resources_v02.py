"""Read-only audit of terminal guardian evidence; no model or checkpoint restore."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.abc
import importlib.util
import json
import math
import os
from pathlib import Path
import stat
import sys
from types import ModuleType, SimpleNamespace

F = Path(__file__).resolve().parent
P = Path('/home/barberb/lift_coding/external/ipfs_datasets')
ATTEMPT = P/'workspace/test-logs/legal-trigger-readout-pilot-20261007-01/temporal-role-contrast-20261012-02'
PRIOR_ATTEMPT = ATTEMPT.with_name('temporal-role-contrast-20261011-01')
PREVIOUS_ATTEMPT = ATTEMPT.with_name('temporal-role-contrast-20261012-01')
PROTOCOL = F/'runtime-resource-audit-procedure-v04.json'
OUTPUT = F/'training-runtime-resource-audit-v02.json'
MAX_JSON_BYTES = 16*1024*1024

class DenyModels(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'torch','numpy','transformers','sentence_transformers'}:
            raise AssertionError('Numerical/model imports prohibited: '+fullname)
        return None

sys.meta_path.insert(0, DenyModels()); sys.dont_write_bytecode = True

def audit(event, args):
    if event.startswith(('subprocess.','socket.')) or event in {'os.system','os.fork','os.posix_spawn','os.kill','os.killpg'}:
        raise AssertionError('Read-only observer refuses process/network operation: '+event)
    if event == 'fcntl.flock':
        raise AssertionError('Read-only observer refuses locks')
    if event == 'open':
        path, mode, flags = args
        write = isinstance(mode,str) and any(c in mode for c in 'wax+')
        write |= isinstance(flags,int) and bool(flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
        if write and (not isinstance(path,(str,bytes,os.PathLike)) or Path(os.fsdecode(path)).absolute() != OUTPUT):
            raise AssertionError('Only the exclusive owned audit receipt may be written')

sys.addaudithook(audit)

def require(value,message):
    if not value: raise ValueError(message)

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()

def digest(value): return hashlib.sha256(canonical(value)).hexdigest()

def pin(path):
    path=Path(path); require(path.is_absolute(),'absolute artifact required')
    for part in (*reversed(path.parents),path):
        info=part.lstat();require(not stat.S_ISLNK(info.st_mode),'symlink artifact refused')
        require(stat.S_ISDIR(info.st_mode) if part != path else stat.S_ISREG(info.st_mode),'ordinary artifact required')
    with path.open('rb') as stream:
        before=os.fstat(stream.fileno());hashed=hashlib.sha256();size=0
        for block in iter(lambda:stream.read(1024*1024),b''):hashed.update(block);size+=len(block)
        after=os.fstat(stream.fileno())
    current=path.lstat();identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    require(identity(before)==identity(after)==identity(current),'artifact changed during hash')
    return dict(path=str(path),bytes=size,sha256=hashed.hexdigest())

def strict_json(content):
    require(len(content)<=MAX_JSON_BYTES,'bounded JSON required')
    def unique(pairs):
        value={}
        for k,v in pairs:require(k not in value,'duplicate JSON field');value[k]=v
        return value
    def reject(value):raise ValueError('nonfinite JSON: '+value)
    value=json.loads(content,object_pairs_hook=unique,parse_constant=reject)
    def finite(item):
        if isinstance(item,float):require(math.isfinite(item),'nonfinite parsed number')
        elif isinstance(item,dict):
            for v in item.values():finite(v)
        elif isinstance(item,list):
            for v in item:finite(v)
    finite(value);return value

def read(path):
    require(pin(path)['bytes']<=MAX_JSON_BYTES,'bounded JSON required')
    return strict_json(Path(path).read_bytes())

def lines(path):
    require(pin(path)['bytes']<=MAX_JSON_BYTES,'bounded JSONL required')
    values=[strict_json(line.encode()) for line in path.read_text().splitlines() if line]
    require(len(values)<=2048,'bounded observations required')
    return values

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module;spec.loader.exec_module(module);return module

def inventory(root):
    require(root.is_dir() and not root.is_symlink(),'ordinary terminal attempt root required')
    rows={}
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(),'symlink in terminal attempt refused')
        if path.is_dir():continue
        require(len(rows)<1024,'bounded terminal artifacts required')
        rows[str(path.relative_to(root))]=pin(path)
    return rows

def same_pin(actual,expected):
    return all(actual[k]==expected[k] for k in ('bytes','sha256'))

def main():
    procedure=read(PROTOCOL); require(pin(Path(__file__))['sha256']==procedure['helper_sha256'],'audit helper differs')
    require(procedure['attempt_directory']==str(ATTEMPT),'exact fresh attempt required')
    for path,expected in procedure['opening_artifacts'].items():require(same_pin(pin(Path(path)),expected),'prepared input drift: '+path)
    baseline=read(F/'storage-resource-endpoints-post-migration-v01.json')
    old_hashes=baseline['record_body_hashes']; require(len(old_hashes)==511,'exact old 511 baseline required')
    prior_hashes=procedure['prior_512_body_hashes']
    require(len(prior_hashes)==512 and all(prior_hashes[k]==v for k,v in old_hashes.items()),'exact prior512 baseline required')
    guardian_path=F/'run_scope_guardian.py'; guardian=load('readonly_terminal_guardian',guardian_path)
    for path,expected in guardian.CLOSURE.items():require(pin(path)['sha256']==expected,'historical resource producer drift')
    for name in ('ipfs_datasets_py','ipfs_datasets_py.optimizers','ipfs_datasets_py.optimizers.logic_theorem_optimizer'):
        module=ModuleType(name);module.__path__=[str(guardian.SOURCE.joinpath(*name.split('.')))];sys.modules[name]=module
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import resource_scheduler as scheduler
    resources=load('ipfs_datasets_py.optimizers.logic_theorem_optimizer.readonly_terminal_owner',guardian.OWNER)
    def denied(*args,**kwargs):raise AssertionError('Observer refuses clients, claims, locks, writes and releases')
    resources.get_global_resource_scheduler=denied
    for method in ('__init__','__enter__','_locked','_write','_update','_retain','release','finalize'):
        setattr(resources.DaemonResourceReservation,method,denied)
    require(guardian.RESOURCES==procedure['resources'],'unchanged exact resource envelope required')
    artifacts=inventory(ATTEMPT); require('guardian-exit.json' in artifacts,'terminal guardian receipt required')
    prior=inventory(PRIOR_ATTEMPT)
    require(prior==procedure['prior_failed_attempt_files'],'old failed attempt changed')
    previous=inventory(PREVIOUS_ATTEMPT)
    require(previous==procedure['previous_failed_attempt_files'],'20261012 failed attempt changed')
    terminal=read(ATTEMPT/'guardian-exit.json'); child_exit=read(ATTEMPT/'child-exit.json')
    pre=read(ATTEMPT/'pre-admission.json'); plan=read(F/'experiment-plan-v01.json')
    for field,path in [('plan',F/'experiment-plan-v01.json'),('runner',F/'run_temporal_contrast_pilot.py'),('guardian',guardian_path)]:
        require(same_pin(pre[field],pin(path)),'pre-admission source binding differs: '+field)
    require(pre['review']['path']==str(F/'training-protocol-independent-review-v02.json')
            and pin(Path(pre['review']['path']))==pre['review'],'exact retry02 concrete training review changed')
    training_review=read(Path(pre['review']['path']))
    require(training_review['phase']=='training' and training_review['passed'] is True and training_review['findings']==[]
            and training_review['fresh_resource_endpoints']['new_attempt_path']==str(ATTEMPT),'retry02 training authority differs')
    compatibility_path=Path(procedure['actual_compatibility']['path'])
    require(pin(compatibility_path)==procedure['actual_compatibility']
            and training_review['artifacts'][str(compatibility_path)]=={k:pin(compatibility_path)[k] for k in ('bytes','sha256')},
            'exact retry02 compatibility review binding differs')
    require(pre['compatibility']['resources']==procedure['resources'],'pre-admission envelope differs')
    require(pre['compatibility']['shared_config']==baseline['scheduler_config'],'shared config differs')
    ledger_before=pin(guardian.LEDGER); ledger=read(guardian.LEDGER)
    require(ledger['limit_bytes']==145_000_000_000 and ledger['roots']==baseline['root_identities'],'ledger cap/scope changed')
    require([resources._root_identity(root) for root in guardian.ROOTS]==ledger['roots'],'actual root identity differs')
    record_hashes={key:digest(row) for key,row in ledger['reservations'].items()}
    changed_old=[key for key,expected in old_hashes.items() if record_hashes.get(key)!=expected]
    require(not changed_old,'old reservation bodies changed')
    require(all(record_hashes.get(k)==v for k,v in prior_hashes.items()),'prior512 bodies changed')
    require(resources.DaemonResourceReservation._read(SimpleNamespace(ledger_path=guardian.LEDGER,
            root_identities=ledger['roots']))==ledger,'ordinary owner ledger reader differs')
    success=terminal['returncode']==0
    final_path=ATTEMPT/('resources-final.json' if success else 'resources-final-failure.json')
    final=read(final_path)
    snapshot=final['owner'] if success else final['resources']
    own_id=snapshot['reservation_id'];own_record=ledger['reservations'].get(own_id)
    require(own_id not in prior_hashes,'owned fresh reservation collides with prior claim')
    if own_record is not None:
        require(own_record['storage_bytes']==200_000_000 and own_record['memory_mb']==1536
                and own_record['cpu_slots']==2 and own_record['child_process_slots']==1,'owned ledger envelope differs')
        require(own_record['status'] in {'retained','released','reserved','active'},'owned status invalid')
        require(digest(own_record)==digest(snapshot['record']),'terminal owned record differs from ledger')
    else:require(snapshot.get('record') is None,'terminal record missing from ledger')
    child_created=(ATTEMPT/'child-identity.json').is_file()
    identity=read(ATTEMPT/'child-identity.json') if child_created else None
    current_group=resources._group_usage(identity)
    require(current_group['live_processes']==0,'terminal owned child group still alive')
    require(child_exit['leader_reaped'] is True,'owned leader not reaped')
    if child_created:
        require(own_record is not None and own_record['child']==identity,'child identity not bound to owned record')
        require(own_record['attempt_directory']==resources._root_identity(ATTEMPT),'owned attempt identity differs')
    schedule_state=None;lease_id=None;lease_observations=[];rss_summary=None;rss_events=[]
    if (ATTEMPT/'lease-binding.json').is_file():
        binding=read(ATTEMPT/'lease-binding.json');lease_id=binding['own_fields']['lease_id']
        require(binding['capability_persisted'] is False,'lease capability persisted')
        for key,expected in [('cpu_slots',2),('memory_mb',1536),('child_process_slots',1)]:
            require(binding['own_fields'][key]==expected,'bound lease envelope differs')
        state_path=Path(binding['state_path']);state_before=pin(state_path);schedule_state=read(state_path)
        require(schedule_state['config']==baseline['scheduler_config'],'closing scheduler config differs')
        require(lease_id not in schedule_state['leases'],'owned scheduler lease still present')
        lease_observations=lines(ATTEMPT/'lease-observations.jsonl')
        if success:
            observed=[e for e in lease_observations if e.get('schema')=='guardian-owned-lease-observation/v1']
            require(observed and not any(e.get('schema')=='guardian-owned-lease-watchdog-failure/v1' for e in lease_observations),'successful run has failed lease evidence')
            require(all(e.get('healthy') is True and e.get('configuration_matches') is True
                        and e.get('continuous_coverage_claimed') is False for e in observed),'unhealthy lease evidence')
            require(any(e['stage']=='pre_spawn' for e in observed) and any(e['stage']=='post_spawn' for e in observed)
                    and any(e['stage']=='pre_finalize' for e in observed),'missing recorded lease stages')
            require(observed[-1]['stage']=='post_finalize' and observed[-1]['expected']=='absent'
                    and observed[-1]['lease_present'] is False,'lease release observation missing')
            require(all(e.get('observation_gap_seconds',0)<=5 for e in observed if e['stage'] in {'monitor','post_spawn'}),'lease sampled gap exceeded')
        state_after=pin(state_path);require(state_after==state_before,'scheduler bytes changed during audit')
    else:state_before=state_after=None
    if (ATTEMPT/'group-rss-summary.json').is_file():
        rss_summary=read(ATTEMPT/'group-rss-summary.json');rss_events=lines(ATTEMPT/'group-rss-observations.jsonl')
        require(rss_summary['identity']==identity and rss_summary['memory_limit_bytes']==1536*1024*1024,'RSS identity/envelope differs')
        if success:
            events=[e for e in rss_events if e.get('schema')=='guardian-owned-group-rss-observation/v1']
            require(rss_summary['failure'] is None and len(events)==len(rss_events),'successful RSS monitor failed')
            counts=dict(Counter(e['phase'] for e in events))
            for phase in ('gated','model','post_model'):
                phase_rows=[e for e in events if e['phase']==phase]
                peak=max((e['group_rss_bytes'] for e in phase_rows),default=0)
                require(counts.get(phase,0)==rss_summary['sample_counts_by_phase'][phase]
                        and peak==rss_summary['sampled_peaks_by_phase'][phase],'RSS counters or peak differ')
            require(all(e['identity']==identity and e['memory_limit_bytes']==1536*1024*1024
                        and e['group_rss_bytes']<=1536*1024*1024 and e['sampled_only'] is True
                        and e['kernel_hard_cap'] is False for e in events),'RSS observation violates envelope')
            require(rss_summary['model_phase_sample_count']>0 and rss_summary['sampled_peak_only'] is True
                    and rss_summary['absolute_peak_measured'] is False and rss_summary['continuous_coverage_claimed'] is False,'RSS qualification claims differ')
            require(rss_summary['model_phase_wall_seconds']<=300,'recorded model phase exceeds deadline')
            require(terminal['sampled_model_phase_peak_rss_bytes']==rss_summary['sampled_model_phase_peak_rss_bytes'],'guardian sampled peak differs')
    summary_path=ATTEMPT/'results/summary.json'; summary=read(summary_path) if summary_path.is_file() else None
    child_failure_path=ATTEMPT/'results/child-failure.json';child_failure=read(child_failure_path) if child_failure_path.is_file() else None
    primary_failure=read(ATTEMPT/'failure-primary.json') if not success else None
    failed_before_model_gate=bool(not success and primary_failure.get('model_started') is False
        and not (ATTEMPT/'results').exists() and artifacts.get('child.log',{}).get('bytes')==0
        and rss_summary is not None and rss_summary['model_phase_sample_count']==0
        and rss_summary['model_gate_permitted_at_monotonic'] is None)
    recorded_returned_updates=None;unknown_partial_updates=False
    if summary is not None:
        require(summary['status']=='completed' and summary['actual_new_updates']==64,'completed result count differs')
        require(len(summary['arms'])==2 and {a['name'] for a in summary['arms']}=={'control','contrast'},'completed arms differ')
        for arm in summary['arms']:
            require(arm['actual_new_updates']==32,'completed arm update count differs')
            for field in ('checkpoint','training'):
                path=Path(arm[field]['path']);require(path.parent==ATTEMPT/'results','arm artifact escapes results')
                require(pin(path)==arm[field],'saved result artifact differs')
            training=read(Path(arm['training']['path']))
            require(training['optimizer_steps']==32 and training['stopped_reason']=='step_limit','completed training report differs')
        require(summary['actual_encoder_calls']==0 and summary['latent_enabled'] is False
                and summary['trained_dimensions']==[384] and summary['semantic_accuracy'] is None
                and summary['legal_fidelity_qualified'] is False and summary['Lake_executed'] is False,'result scope claims differ')
        recorded_returned_updates=64
    elif child_failure is not None:
        recorded_returned_updates=child_failure['completed_updates']
        unknown_partial_updates=bool(child_failure['in_progress_arm_updates_unknown'])
    elif not child_created or failed_before_model_gate:recorded_returned_updates=0
    else:unknown_partial_updates=True
    if success:
        require(child_created and child_exit['returncode']==0 and summary is not None,'successful guardian lacks completed child evidence')
        require(child_exit['launch_through_reap_wall_seconds']<=300,'gated child launch/reap deadline exceeded')
        require(terminal['artifacts_durable'] is True and terminal['resource_reservation_released'] is True,'successful durability/release flags differ')
        require(own_record['status']=='released' and own_record['artifacts_durable_asserted'] is True,'successful own record not released')
        require(own_record['attempt_exceeded_reservation'] is False and own_record['final_total_charged_bytes']<=200_000_000,'released attempt exceeded reservation')
        cleanup=read(ATTEMPT/'owned-group-final.json');require(cleanup['leader_reaped'] is True and cleanup['live_group_processes']==0,'successful cleanup evidence differs')
        require(final['continuous_lease_coverage_claimed'] is False and final['lease_absent']['lease_present'] is False,'successful final lease evidence differs')
        require(terminal['model_phase_peak_is_sampled'] is True and terminal['kernel_hard_memory_cap'] is False,'guardian enforcement claims differ')
    attempt_bytes=sum(row['bytes'] for row in artifacts.values())
    require(attempt_bytes<=200_000_000,'actual terminal attempt bytes exceed 200MB envelope')
    closing_artifacts=inventory(ATTEMPT);require(closing_artifacts==artifacts,'attempt bytes changed during audit')
    require(inventory(PRIOR_ATTEMPT)==prior,'prior failed attempt changed during audit')
    require(inventory(PREVIOUS_ATTEMPT)==previous,'20261012 failed attempt changed during audit')
    require([resources._root_identity(root) for root in guardian.ROOTS]==ledger['roots'],'root identity changed during audit')
    ledger_after=pin(guardian.LEDGER);require(ledger_after==ledger_before,'ledger changed during audit')
    for path,expected in procedure['opening_artifacts'].items():require(same_pin(pin(Path(path)),expected),'closing prepared artifact drift')
    result=dict(schema='temporal-binding-training-runtime-resource-audit/v1',passed=True,findings=[],
        observed_at_utc=datetime.now(timezone.utc).isoformat(),helper=pin(Path(__file__)),procedure=pin(PROTOCOL),
        physical_attempt=str(ATTEMPT),artifacts=artifacts,prior_failed_attempt_files=prior,
        previous_failed_attempt_files=previous,exact_retry02_training_review=pre['review'],
        exact_retry02_compatibility=procedure['actual_compatibility'],
        outcome='completed' if success else 'failed_or_refused',guardian_returncode=terminal['returncode'],
        child_created=child_created,child_identity=identity,child_returncode=child_exit['returncode'],
        failed_before_model_gate=failed_before_model_gate,
        actual_model_calls_known_zero=failed_before_model_gate or not child_created,
        current_owned_group=current_group,leader_reaped=True,
        recorded_returned_prefix_updates=recorded_returned_updates,
        total_actual_updates_known_from_complete_summary=summary is not None,
        in_progress_or_unreported_partial_updates_unknown=unknown_partial_updates,
        update_evidence_scope='Recorded completed child summary and returned arm training reports; no new numerical replay or optimizer-update tracing',
        ledger_before=ledger_before,ledger_after=ledger_after,old_record_count=511,
        old_511_record_bodies_unchanged=True,all_prior_512_record_bodies_unchanged=True,
        released_c6_claim_body_unchanged=True,prior_record_count=512,owned_reservation_id=own_id,
        owned_record_present=own_record is not None,owned_record_status=None if own_record is None else own_record['status'],
        owned_record_body_sha256=None if own_record is None else record_hashes[own_id],
        other_new_reservation_ids=sorted(set(record_hashes)-set(prior_hashes)-{own_id}),
        resources=guardian.RESOURCES,attempt_terminal_bytes=attempt_bytes,
        finalized_accounting_excludes_later_terminal_receipts=success,
        final_reserved_attempt_bytes=None if not success else own_record['final_attempt_bytes'],
        lease_id=lease_id,owned_lease_absent_at_observation=lease_id is not None,
        scheduler_before=state_before,scheduler_after=state_after,
        scheduler_endpoint_bytes_unchanged=state_before==state_after if state_before else None,
        lease_observation_count=len(lease_observations),group_RSS_observation_count=len(rss_events),
        sampled_model_phase_peak_rss_bytes=None if rss_summary is None else rss_summary['sampled_model_phase_peak_rss_bytes'],
        model_phase_wall_seconds=None if rss_summary is None else rss_summary['model_phase_wall_seconds'],
        guardian_elapsed_seconds=terminal['elapsed_seconds'],
        child_launch_through_reap_wall_seconds=child_exit.get('launch_through_reap_wall_seconds'),
        artifacts_durable_asserted=terminal.get('artifacts_durable',False),
        runtime_completed_and_released_qualified=success,
        sampled_peak_only=True,absolute_peak_measured=False,kernel_hard_cap=False,continuous_custody_claimed=False,
        audit_model_calls=0,audit_optimizer_updates=0,audit_scheduler_clients=0,audit_locks_acquired=0,
        audit_claims_modified=False,audit_limits_modified=False,audit_checkpoint_restore=False,
        HF_mutation=False,Lake_executed_by_audit=False,semantic_accuracy=None,
        full_local_migration_backups_published=False)
    with OUTPUT.open('x') as stream:
        json.dump(result,stream,sort_keys=True,indent=2,allow_nan=False);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    print(json.dumps({k:result[k] for k in ('passed','outcome','recorded_returned_prefix_updates','in_progress_or_unreported_partial_updates_unknown','owned_record_status','attempt_terminal_bytes','sampled_model_phase_peak_rss_bytes')},sort_keys=True))

if __name__=='__main__':main()
