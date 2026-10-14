"""Explicitly authorize exactly one audited own N8 claim through the retained recovery API.

The original API function AST is unchanged. A local native-owner subclass adds
same-lock full536 opening and535-other transition checks. No global class/module
is patched, owner identity is not forged, and no original owner release or
scheduler admission is invoked. Main needs a root-written exact execution gate.
"""
import ast
import copy
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import stat
import sys
from types import SimpleNamespace

F=Path(__file__).resolve().parent
RUN=Path('/home/barberb/lift_coding/external/ipfs_datasets/workspace/test-logs/legal-trigger-readout-pilot-20261007-01')
ATTEMPT=RUN/'actor-boundary-20261013-actor-boundary-ce-01'
LEDGER=RUN.parent/'federal-corpus-audits/owned-daemon-resource-control/disk-reservations.json'
ROOTS=(RUN.parent,RUN.parent.parent/'todo-queues',RUN.parent.parent.parent/'docs/implementation/reports/evidence',Path('/tmp/pytest-of-barberb'))
TARGET='893d4ed80ab3497f95b1490080e3caa3'
TARGET_SHA='63cbb539d211fa47bf9a19d9b50c45dd4f2f4f8075d3d27b7597466c5174386c'
OWNER=RUN.parent/'native4096-four-width-20261004/resource-cap/autoencoder_daemon_resources.py'
RECOVERY=RUN.parent/'ui-modal-coverage-20261002/validation-source-r2/ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_resource_recovery.py'
GUARDIAN=F/'run_scope_guardian_v02.py'
BASELINE=dict(path=str(F/'resource-baseline-v01.json'),bytes=77873,sha256='0d9930ff9831f0fb135439a066f0345e2fa3e9720a8827f74366253016b4f8f2')
OWNER_PIN=dict(path=str(OWNER),bytes=36724,sha256='b00d2752ba852fe73760bba4fbd51b0e845742c3527642606a2a77ed9f8f5e2c')
RECOVERY_PIN=dict(path=str(RECOVERY),bytes=6230,sha256='5d36b28b4bda7cba91fbbe146cf2e3752f06f3e3adb6c92772788466ef701aa7')
GUARDIAN_PIN=dict(path=str(GUARDIAN),bytes=38449,sha256='b4811b7b24f584d5cb0f7c921451a234a3e0d84b2d7507e015426e258134c2db')
PREFLIGHT_PIN=dict(path=str(F/'actor-features-retained-claim-preflight-v01.json'),bytes=20562,sha256='13ccb471de2de244a3e8cc5f8d2cd1c617579c52ec499121355d4a9906a10850')
QUALIFICATION=F/'retained-claim-reconciliation-source-independent-review-v01.json'
EXECUTION_GATE=F/'retained-claim-reconciliation-execution-approval-v01.json'
OUTPUT=F/'actor-features-retained-claim-reconciliation-v01.json'
READS={}
sys.dont_write_bytecode=True


def require(value,message):
    if not value:raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def pin(path,expected=None):
    path=Path(path)
    require(path.is_absolute() and path.resolve(strict=True)==path and not path.is_symlink(),'physical absolute file required')
    require('private-runtime-snapshots' not in path.parts and path!=LEDGER and 'checkpoint' not in path.name and 'reference-packet' not in path.name,'only public source/metadata hashing allowed')
    before=path.stat();require(stat.S_ISREG(before.st_mode) and 0<before.st_size<=16*1024*1024,'bounded regular metadata/source required')
    raw=path.read_bytes();after=path.stat();identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    require(identity(before)==identity(after) and len(raw)==before.st_size,'raw artifact drift')
    value=dict(path=str(path),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    require(expected is None or expected==value,'raw expected identity differs')
    require(str(path) not in READS or READS[str(path)]==value,'previous consumed raw identity drift');READS[str(path)]=value
    return value


def read(path,expected=None):
    identity=pin(path,expected);raw=Path(path).read_bytes()
    require(len(raw)==identity['bytes'] and hashlib.sha256(raw).hexdigest()==identity['sha256'],'consumed bytes differ')
    def pairs(items):
        value={}
        for key,item in items:require(key not in value,'duplicate JSON key');value[key]=item
        return value
    def finite(raw):
        value=float(raw);require(math.isfinite(value),'nonfinite JSON number');return value
    value=json.loads(raw,object_pairs_hook=pairs,parse_float=finite,parse_constant=lambda value:(_ for _ in ()).throw(ValueError('nonfinite JSON')))
    pin(path,identity);return value


def qualify_opening(ledger,baseline,preflight):
    prior=baseline['baseline_ledger'];bodies=ledger['reservations']
    require(set(ledger)=={'schema','roots','limit_bytes','reservations'} and ledger['schema']=='daemon-resource-reservations-v1'
        and ledger['roots']==baseline['counted_root_metadata'] and ledger['limit_bytes']==145000000000,'same-lock ledger schema/roots/cap differ')
    hashes={key:digest(row) for key,row in bodies.items()}
    require(len(bodies)==536 and hashes==prior['record_body_hashes'] and digest(hashes)==preflight['ledger_conservation']['record_body_hash_map_sha256']
        and digest(bodies[TARGET])==TARGET_SHA and bodies[TARGET]['status']=='retained','same-lock all536 preflight body identities must remain exact')
    others={key:row for key,row in bodies.items() if key!=TARGET}
    require(len(others)==535 and digest(others)==preflight['ledger_conservation']['other_reservations_sha256'],'same-lock all535 other records must match preflight')


def qualify_transition(before,after,preflight,reconciler_pid):
    require(set(after)==set(before)=={'schema','roots','limit_bytes','reservations'}
        and all(after[key]==before[key] for key in ('schema','roots','limit_bytes')),'only reservation record transition allowed')
    a,b=before['reservations'],after['reservations']
    require(set(a)==set(b) and len(b)==536 and all(b[key]==a[key] for key in a if key!=TARGET),'all535 other reservation bodies must remain exact')
    old,new=a[TARGET],b[TARGET]
    require(digest(old)==TARGET_SHA and old['status']=='retained' and old['storage_bytes']==200000000,'only authenticated retained own N8 claim may reconcile')
    allowed={'status','artifacts_durable_asserted','released_at','final_accounting','final_attempt_bytes',
        'final_external_charged_bytes','final_total_charged_bytes','attempt_exceeded_reservation','explicit_reconciliation'}
    require(set(new)==set(old)|allowed and all(new[key]==old[key] for key in old if key not in allowed),'unexpected target field mutation or removal')
    recovery=new['explicit_reconciliation'];expected_keys={'schema','reservation_id','previous_record_sha256','original_owner_pid',
        'reconciled_by_pid','artifacts','other_reservations_sha256','full_claim_accounting','final_accounting','outputs_deleted','automatic_expiry','admitted'}
    require(type(recovery) is dict and set(recovery)==expected_keys
        and recovery['schema']=='explicit-retained-reservation-reconciliation/v1' and recovery['reservation_id']==TARGET
        and recovery['previous_record_sha256']==TARGET_SHA and recovery['original_owner_pid']==old['owner_pid']
        and recovery['reconciled_by_pid']==reconciler_pid and recovery['artifacts']==preflight['durable_artifact_inventory']
        and recovery['other_reservations_sha256']==preflight['ledger_conservation']['other_reservations_sha256']
        and recovery['outputs_deleted'] is recovery['automatic_expiry'] is recovery['admitted'] is False,
        'exact original administrative recovery metadata required')
    accounting=recovery['full_claim_accounting'];final=recovery['final_accounting']
    require(set(accounting)=={'observed_apparent_bytes','outstanding_full_reservations_bytes','additional_requested_bytes','charged_bytes',
        'limit_bytes','minimum_filesystem_free_bytes','scope','inventory'} and accounting['scope']=='named_roots_only_apparent_bytes',
        'original full-claim accounting envelope differs')
    require(all(type(accounting[key]) is int and accounting[key]>=0 for key in ('observed_apparent_bytes','outstanding_full_reservations_bytes',
        'additional_requested_bytes','charged_bytes','limit_bytes','minimum_filesystem_free_bytes'))
        and accounting['outstanding_full_reservations_bytes']==44581777216 and accounting['additional_requested_bytes']==0
        and accounting['limit_bytes']==145000000000 and accounting['charged_bytes']==accounting['observed_apparent_bytes']+44581777216
        and accounting['charged_bytes']<=145000000000 and accounting['minimum_filesystem_free_bytes']>=44581777216
        and accounting['inventory']['apparent_bytes']==accounting['observed_apparent_bytes'],
        'full own200M must remain charged through the fresh before-write census')
    projected=copy.deepcopy(accounting);projected['outstanding_full_reservations_bytes']-=200000000;projected['charged_bytes']-=200000000
    require(final==projected and new['final_accounting']==final,'retained API final accounting must be identified as its exact arithmetic projection')
    attempt_bytes=sum(row['bytes'] for row in preflight['durable_artifact_inventory'])
    require(new['status']=='released' and new['artifacts_durable_asserted'] is True
        and type(new['released_at']) in (int,float) and math.isfinite(new['released_at']) and new['released_at']>0
        and new['final_attempt_bytes']==new['final_total_charged_bytes']==attempt_bytes<=200000000
        and new['final_external_charged_bytes']==0 and new['attempt_exceeded_reservation'] is False,
        'exact durable original-API target closeout required')
    return dict(reservation_id=TARGET,previous_record_body_sha256=TARGET_SHA,record_body_sha256=digest(new),status='released',storage_bytes=200000000,
        unchanged_other_record_count=535,all_other535_record_bodies_unchanged=True,
        other_record_body_hash_map_sha256=digest({key:digest(row) for key,row in b.items() if key!=TARGET}),
        closing_record_body_hash_map_sha256=digest({key:digest(row) for key,row in b.items()}),closing_record_count=536,
        final_accounting_is_API_arithmetic_projection=True,actual_postwrite_census_claimed=False)


def load_recovery(native_owner,local_owner):
    """Bind the retained module's unchanged functions to the qualified local owner facade."""
    pin(RECOVERY,RECOVERY_PIN);tree=ast.parse(RECOVERY.read_bytes())
    imports=[node for node in tree.body if isinstance(node,ast.ImportFrom) and node.level==1]
    require(len(imports)==1 and imports[0].module is None and [(a.name,a.asname) for a in imports[0].names]==[('autoencoder_daemon_resources','resources')],
        'exact retained relative owner import required')
    nodes=[node for node in tree.body if node not in imports]
    scope=dict(__name__='qualified_actor_features_retained_recovery',__file__=str(RECOVERY),
        resources=SimpleNamespace(**{**vars(native_owner),'DaemonResourceReservation':local_owner}))
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(RECOVERY),'exec'),scope)
    return scope['reconcile_retained_reservation']


def main():
    require(sys.argv[1:]==[] and not os.path.lexists(OUTPUT) and type(PREFLIGHT_PIN) is dict,'exact sealed actual preflight and exclusive new receipt required')
    own=pin(Path(__file__).resolve());qualification=read(QUALIFICATION)
    require(qualification['schema']=='actor-features-retained-claim-reconciliation-source-independent-review/v1'
        and qualification['passed'] is True and qualification['findings']==[] and qualification['observer']==own,'exact independent mutation source qualification required')
    for path,expected in qualification.get('artifacts',{}).items():
        require(all(pin(path)[key]==expected[key] for key in ('bytes','sha256')),'independent source qualification drift')
    baseline=read(BASELINE['path'],BASELINE);preflight=read(PREFLIGHT_PIN['path'],PREFLIGHT_PIN)
    require(preflight['schema']=='actor-features-retained-claim-preflight/v1' and preflight['passed'] is True and preflight['findings']==[]
        and preflight['recovery_plan_concrete'] is True and preflight['recovery_authorized'] is False and preflight['recovery_executed'] is False
        and preflight['baseline']==BASELINE and preflight['qualified_current_resource_owner']==OWNER_PIN and preflight['recovery_API']==RECOVERY_PIN,
        'exact root-reviewable read-only actual preflight required')
    expected_call=dict(ledger_path=str(LEDGER),roots=[str(root) for root in ROOTS],reservation_id=TARGET,
        expected_record_sha256=TARGET_SHA,attempt_directory=str(ATTEMPT),expected_artifacts=preflight['durable_artifact_inventory'],artifacts_durable=True)
    require(preflight['recovery_call']==expected_call,'one literal own-claim administrative call required')
    gate=read(EXECUTION_GATE)
    require(gate['schema']=='actor-features-retained-claim-reconciliation-execution-approval/v1' and gate['passed'] is True and gate['findings']==[]
        and gate['observer']==own and gate['source_qualification']==pin(QUALIFICATION) and gate['preflight']==PREFLIGHT_PIN
        and gate['recovery_call_sha256']==digest(expected_call) and gate['authorize_exact_one_own_N8_claim_reconciliation'] is True
        and gate['foreign_reconciliation_authorized'] is False and gate['cap_increase_authorized'] is False and gate['outputs_deletion_authorized'] is False,
        'root must approve the concrete exact preflight/call after independent source review')
    pin(GUARDIAN,GUARDIAN_PIN);pin(OWNER,OWNER_PIN);pin(RECOVERY,RECOVERY_PIN)
    for path,expected in list(READS.items()):pin(path,expected)
    spec=importlib.util.spec_from_file_location('qualified_actor_features_recovery_guardian',GUARDIAN)
    guardian=importlib.util.module_from_spec(spec);spec.loader.exec_module(guardian)
    native_owner,*_,compatibility=guardian.closure_and_configuration()
    require(Path(native_owner.__file__).resolve()==OWNER and native_owner.MAX_STORAGE_BYTES==145000000000
        and compatibility['passed'] is True and compatibility['findings']==[] and compatibility['reservation_acquired'] is False
        and compatibility['scheduler_client_constructed'] is False,'exact unchanged qualifiednative145B owner required')
    result={}
    class ExactOwnClaimOwner(native_owner.DaemonResourceReservation):
        def _read(self):
            value=super()._read();qualify_opening(value,baseline,preflight)
            self._actor_recovery_before=copy.deepcopy(value)
            return value
        def _write(self,value):
            require(not result and hasattr(self,'_actor_recovery_before'),'exact one same-lock authenticated API write required')
            transition=qualify_transition(self._actor_recovery_before,value,preflight,os.getpid())
            super()._write(value);result.update(transition)
    reconcile=load_recovery(native_owner,ExactOwnClaimOwner)
    recovery=reconcile(LEDGER,roots=ROOTS,reservation_id=TARGET,expected_record_sha256=TARGET_SHA,
        attempt_directory=ATTEMPT,expected_artifacts=expected_call['expected_artifacts'],artifacts_durable=True)
    require(result and recovery['reservation_id']==TARGET,'exact one durable retained-API write must complete')
    value=dict(schema='actor-features-retained-claim-reconciliation/v1',passed=True,findings=[],observer=own,
        source_qualification=pin(QUALIFICATION),execution_approval=pin(EXECUTION_GATE),preflight=PREFLIGHT_PIN,prior_baseline=BASELINE,
        observed_at_utc=datetime.now(timezone.utc).isoformat(),recovery_API=RECOVERY_PIN,qualified_resource_owner=OWNER_PIN,
        target_transition=result,retained_API_recovery=recovery,all_other535_record_bodies_unchanged=True,
        claims_explicitly_reconciled=1,resource_API_calls=1,administrative_helper_constructed=True,
        original_function_AST_preserved=True,local_facade_same_lock_checks=True,global_classes_or_modules_patched=False,
        original_owner_identity_forged=False,owner_release_called=False,resource_reservation_enter_called=False,
        scheduler_admission_called=False,model_or_encoder_calls=0,checkpoint_JSON_parses=0,
        outputs_deleted=False,automatic_expiry=False,cap_changes=0,N7_claim_status_changed=False,
        actual_postwrite_census_performed=False,API_final_accounting_is_projection=True,artifacts=READS,
        limitations=['The retained API fsyncs its exact selected-record ledger transition; a separately qualified fresh copied-state baseline must verify actual closing536 and actual postwrite named-root accounting.',
            'The API final_accounting field is an arithmetic projection of its before-write census, not an independent postwrite observation.'])
    with OUTPUT.open('x') as out:json.dump(value,out,indent=2,sort_keys=True,allow_nan=False);out.write('\n')
    OUTPUT.chmod(0o444);print(json.dumps(pin(OUTPUT)))

if __name__=='__main__':main()
