"""Freeze one source-only conditions-presence repair plan from exact trained N10 bytes."""
import argparse
import importlib
import importlib.abc
import importlib.util
import os
from pathlib import Path
import sys

F=Path(__file__).resolve().parent
N10=F.parent/'legal-actor-features-20261013-01'
sys.dont_write_bytecode=True

class NoNumerical(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] in {'torch','numpy','transformers','sentence_transformers','huggingface_hub'}:
            raise AssertionError('Numerical/SDK import prohibited in preparation')
        return None

def audit(event,args):
    if event.startswith(('subprocess.','socket.','os.exec','os.spawn')) or event in ('os.system','os.fork','fcntl.flock'):
        raise AssertionError('Process/network/resource operations prohibited in preparation')
    if event=='open' and isinstance(args[0],(str,bytes)):
        path,mode,flags=Path(os.fsdecode(args[0])).absolute(),args[1],args[2]
        if 'private-runtime-snapshots' in path.parts or path.name in {'disk-reservations.json','resources-start.json','resources-final.json','ipfs-datasets-resource-scheduler-1000.json'}:
            raise AssertionError('Private/global bodies prohibited in preparation')
        writing=isinstance(mode,str) and any(c in mode for c in 'wax+')
        writing|=isinstance(flags,int) and bool(flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
        if writing and (path!=F/'conditions-presence-ce-plan-v01.json' or not bool(flags&os.O_EXCL)):
            raise AssertionError('Only exclusive new owned plan write allowed')

sys.meta_path.insert(0,NoNumerical());sys.addaudithook(audit)
spec=importlib.util.spec_from_file_location('conditions_presence_plan_runner',F/'run_conditions_presence_v01.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
_read=runner.read

def metadata(path,expected=None):
    runner.require('checkpoint' not in Path(path).name and 'reference-packet' not in Path(path).name,'Checkpoint/reference JSON parsing prohibited in preparation')
    return _read(path,expected)

runner.read=metadata

def qualify_baseline(baseline):
    b=baseline['baseline_ledger']
    runner.require(baseline['schema']=='conditions-presence-resource-baseline/v1' and baseline['passed'] is True and baseline['findings']==[]
        and b['record_count']==b['preserved_prior_record_count']==537 and b['all_prior_record_bodies_unchanged'] is True
        and b['additional_current_records']==[] and b['record_status_counts']=={'released':436,'retained':101}
        and b['full_nonreleased_claim_bytes']==44381777216 and len(b['record_body_hashes'])==537
        and runner.digest(b['record_body_hashes'])==b['record_body_hash_map_sha256']=='b6c4327768a8fc4f4e076b8485eda367c3e837046b76027afc9cf4d3a3127799',
        'Qualified conserved537-record opening baseline required')
    runner.require(baseline['observer']['path']==str(F/'review_conditions_presence_resource_baseline_v02.py')
        and baseline['fresh_metadata_check']['path']==str(F/'guardian-check-v01.json'),'Exact actual observer/fresh-check descriptors required')
    return b

def prepare():
    artifacts={}
    def bind(path,expected=None):
        value=runner.pin(Path(path));runner.require(expected is None or value==expected,'Expected raw descriptor differs')
        brief={k:value[k] for k in ('bytes','sha256')}
        runner.require(value['path'] not in artifacts or artifacts[value['path']]==brief,'Raw artifact identity conflict')
        runner.require(value['path'] not in runner.READ_PINS or runner.READ_PINS[value['path']]==value,'Parsed/bound custody differs')
        artifacts[value['path']]=brief;return value
    final_pin=bind(N10/'final-integration-independent-review-v01.json')
    runner.require(final_pin['bytes']==28326 and final_pin['sha256']=='c78ab9d0f3c4cd033418c0573d4b745920538faf5ef43ec691db95fbb82b621f','Exact completed N10 final anchor required')
    final=metadata(final_pin['path'],final_pin)
    hub_pin=bind(N10/'hf-publication-actual-independent-review-v01.json')
    runner.require(hub_pin['bytes']==95022 and hub_pin['sha256']=='904640da11829ac5a9dd6ae7c1a770860c217653b3c82089020850a81276c536','Exact N10 Hub anchor required')
    hub=metadata(hub_pin['path'],hub_pin)
    runner.require(final['schema']=='actor-features-final-integration-independent-review/v1' and final['passed'] is True and final['findings']==[]
        and hub['passed'] is True and hub['findings']==[] and final['Hub_revision']==hub['revision']=='f91692a0a695d91b793a00936dd525fbe2bafcac'
        and final['artifacts'][hub_pin['path']]=={k:hub_pin[k] for k in ('bytes','sha256')},'Qualified N10 final/Hub join required')
    old_plan_pin=bind(N10/'actor-features-ce-plan-v02.json')
    runner.require(old_plan_pin['bytes']==46558 and old_plan_pin['sha256']=='f433954ab6e9f26510096f308e879cac1b027bf33aa94a5df7bf765045e555fc'
        and hub['artifacts'][str(N10/'hf-verified-download-v01'/hub['release_prefix']/'evidence'/Path(old_plan_pin['path']).name)]=={k:old_plan_pin[k] for k in ('bytes','sha256')},'Frozen N10 plan must join qualified publication')
    old_plan=metadata(old_plan_pin['path'],old_plan_pin)
    freeze_pin=bind(N10/'actor-features-output-freeze-v01.json')
    runner.require(freeze_pin['bytes']==21187 and freeze_pin['sha256']=='56abf07cfc80b79ef7eb48a0f0579310ae8f555e15cc9c49d1f6fe23bd687e2a','Exact frozen N10 outputs anchor required')
    freeze=metadata(freeze_pin['path'],freeze_pin)
    runner.require(freeze['all_outputs_frozen'] is True and freeze['plan']==old_plan_pin and len(freeze['results'])==62,'Full N10 freeze/plan closure required')
    summary_pin=bind(freeze['summary']['path'],freeze['summary']);summary=metadata(summary_pin['path'],summary_pin)
    runner.require(summary['schema']=='actor-features-cell-results/v1' and summary['status']=='completed' and summary['actual_new_updates']==32
        and summary['final_model_state_sha256']==runner.SOURCE_STATE_SHA,'Exact trained N10 source state required')
    source_checkpoint=bind(summary['checkpoint']['path'],summary['checkpoint'])
    runner.require(source_checkpoint['sha256']==runner.SOURCE_SHA and source_checkpoint['bytes']==6464267
        and freeze['results'][source_checkpoint['path']]=={k:source_checkpoint[k] for k in ('bytes','sha256')},'Opaque trained N10 checkpoint must join full freeze')
    owners={}
    runner.require(old_plan['schema']=='actor-features-cell-plan/v1' and len(old_plan['source_owner_pins'])==37,'Retained37 source owners required')
    for name,descriptor in old_plan['source_owner_pins'].items():
        new=bind(F/'datasets'/Path(descriptor['path']).relative_to(N10/'datasets'))
        runner.require(all(new[k]==descriptor[k] for k in ('bytes','sha256')),'Retained N10 source owner differs')
        owners[name]=new
    retained_pin=bind(F/'retained-source-owners-v01.json');retained_review=metadata(retained_pin['path'],retained_pin)
    runner.require(retained_review['passed'] is True and retained_review['findings']==[] and retained_review['all_retained37_identical_to_trained_N10'] is True
        and retained_review['source_owner_pins']==owners,'Root retained37 source custody required')
    prefix='ipfs_datasets_py.optimizers.logic_theorem_optimizer.'
    candidate=F/'datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_conditions_presence.py'
    candidate_test=F/'datasets/tests/unit/optimizers/logic_theorem_optimizer/test_legal_span_conditions_presence_contracts.py'
    owners[prefix+'legal_span_conditions_presence']=bind(candidate)
    trainer_pin=bind(F/'trainer-source-independent-review-v01.json');trainer=metadata(trainer_pin['path'],trainer_pin)
    runner.require(trainer['passed'] is True and trainer['findings']==[],'Clean N11 trainer source qualification required')
    for path in (candidate,candidate_test,F/'training-design-v01.json'):
        descriptor=bind(path);runner.require(trainer['artifacts'][str(path)] in (descriptor,{k:descriptor[k] for k in ('bytes','sha256')}),'Trainer review must bind exact model/test/design')
    references={name:{view:summary['diagnostics'][name][view] for view in ('raw','joint')} for name in runner.PANELS}
    references['training168']={view:summary['final_training_capture'][view] for view in ('raw','joint')}
    for pair in references.values():
        for descriptor in pair.values():
            bind(descriptor['path'],descriptor)
            runner.require(freeze['results'][descriptor['path']]=={k:descriptor[k] for k in ('bytes','sha256')},'All632 trained N10 score references must join frozen inventory')
    data_pin=bind(old_plan['data_export']['path'],old_plan['data_export']);data=metadata(data_pin['path'],data_pin)
    fresh_pin=bind(old_plan['fresh_source_export']['path'],old_plan['fresh_source_export']);fresh=metadata(fresh_pin['path'],fresh_pin)
    legacy=runner.legacy_runner();retained=legacy.prior_runner();helper=retained.helpers()
    sys.meta_path.insert(0,helper.NoEncoder());helper.bootstrap(F/'datasets')
    for name in ('legal_span_formula','legal_span_continuation','legal_span_split_features','legal_span_conditions_presence'):
        importlib.import_module(prefix+name)
    importlib.import_module('ipfs_datasets_py.logic.legal_ir.joint_span_selection')
    importlib.import_module('ipfs_datasets_py.logic.formalization.autoencoder.retained_span_score_capture')
    loaded=retained.owner_origins(dict(source_owner_pins=owners))
    required={prefix+name for name in ('legal_span_formula','legal_span_continuation','legal_span_targeted_loss','legal_span_split_features','legal_span_actor_boundary','legal_span_actor_features','legal_span_conditions_presence')}
    runner.require(len(loaded)==15 and len(required)==7 and required<=set(loaded)<=set(owners) and all(loaded[n]==owners[n] for n in loaded),'Exact actual15 loaded/seven mandatory source subset required')
    for path in (Path(__file__).resolve(),F/'run_conditions_presence_v01.py',F/'run_scope_guardian_v02.py',runner.LEGACY_RUNNER,legacy.PRIOR_RUNNER,retained.HELPER,
        F/'evaluation-contract-v01.json',F/'training-design-v01.json',F/'resource-protocol-contract-v01.json',F/'resource-baseline-v01.json'):
        bind(path)
    baseline_pin=bind(F/'resource-baseline-v01.json');baseline=metadata(baseline_pin['path'],baseline_pin);qualify_baseline(baseline)
    for key in ('observer','source_qualification','fresh_metadata_check','resource_contract','sampler_source_qualification','resource_bridge_source_qualification'):
        descriptor=baseline[key];bind(descriptor['path'],descriptor)
    for key in ('library_pin','ctypes_util_pin','cuda_pathfinder_pin'):
        descriptor=old_plan['ctypes_dl_resolution'][key];bind(descriptor['path'],descriptor)
    forbidden=list(old_plan['forbidden_reference_paths'])+[str(F/name) for name in ('diagnose_conditions_presence_oracle_v01.py','conditions-presence-oracle-diagnostic-v01.json','parent-conditions-presence-baseline-v01.json')]
    smoke_pin=bind(F/'conditions-presence-bootstrap-smoke-controls-v01.json');smoke=metadata(smoke_pin['path'],smoke_pin)
    runner.require(smoke['passed'] is True and smoke['findings']==[] and smoke['runner']==bind(F/'run_conditions_presence_v01.py')
        and smoke['loaded_owner_count']==15 and smoke['mandatory_loaded_owner_count']==7 and smoke['all38_raw_source_owner_pins_closed'] is True
        and smoke['exact_production_bootstrap_used'] is True and smoke['loaded_owners']==loaded,'Actual source-only production-bootstrap smoke required')
    bind(smoke['controls_source']['path'],smoke['controls_source'])
    peer_pin=bind(F/'runner-preparer-source-independent-review-v01.json');peer=metadata(peer_pin['path'],peer_pin)
    runner.require(peer['schema']=='conditions-presence-runner-preparer-source-independent-review/v1' and peer['passed'] is True and peer['findings']==[],'Exact independent recipe source qualification required')
    for path in (Path(__file__).resolve(),F/'run_conditions_presence_v01.py',F/'conditions_presence_bootstrap_smoke_controls_v01.py',F/'conditions-presence-bootstrap-smoke-controls-v01.json'):
        descriptor=bind(path);runner.require(peer['artifacts'][str(path)] in (descriptor,{k:descriptor[k] for k in ('bytes','sha256')}),'Peer review must bind exact recipe/smoke sources and actual receipt')
    plan=dict(schema='conditions-presence-cell-plan/v1',package_root=str(F/'datasets'),runner_path=str(F/'run_conditions_presence_v01.py'),guardian_path=str(F/'run_scope_guardian_v02.py'),
        attempt_name=runner.ATTEMPT,cell=runner.CELL,source_owner_pins=owners,artifacts=artifacts,data_export=data_pin,fresh_source_export=fresh_pin,source_checkpoint=source_checkpoint,
        source_model_state_sha256=runner.SOURCE_STATE_SHA,context_contract=old_plan['context_contract'],training_manifest_sha256=runner.digest(data['training_rows']),legacy_prefix_sha256=runner.digest(data['training_rows'][:96]),
        source_reference_panels=references,ctypes_dl_resolution=old_plan['ctypes_dl_resolution'],forbidden_reference_paths=forbidden,
        resource_contract=dict(cpu_slots=2,rss_mib=1536,child_slots=1,storage_bytes=200000000,deadline_seconds=300),training_seconds=32,
        diagnostic_panels=[dict(name=n,count=runner.COUNTS[n]) for n in runner.PANELS],evaluation_contract=runner.pin(F/'evaluation-contract-v01.json'),proposal=runner.pin(F/'training-design-v01.json'),
        configured_dimension=384,latent_enabled=False,default_promotion=False,Lake_executed=False,expected_loaded_owner_count=len(loaded))
    runner.validate_plan(plan);runner.validate_sources(plan,data,fresh,helper,legacy)
    runner.require(not (runner.RUN_ROOT/runner.ATTEMPT).exists(),'Immutable attempt already exists')
    schedule=retained.schedule(data['training_rows']);runner.require(len(schedule['batch_indices'])==32 and sum(map(len,schedule['batch_indices']))==384,'Exact inherited32/384 schedule required')
    for path,expected in artifacts.items():runner.require({k:runner.pin(Path(path))[k] for k in ('bytes','sha256')}==expected,'Closing admitted input drift')
    for mapping in (runner.READ_PINS,legacy.READ_PINS):
        for path,expected in mapping.items():runner.require(runner.pin(Path(path))==expected,'Closing consumed metadata drift')
    runner.require(not any(name.split('.')[0] in {'torch','numpy','transformers','sentence_transformers','huggingface_hub'} for name in sys.modules),'Unexpected numerical/SDK import')
    print(runner.write(F/'conditions-presence-ce-plan-v01.json',plan))

if __name__=='__main__':
    argparse.ArgumentParser(description=__doc__).parse_args();prepare()
