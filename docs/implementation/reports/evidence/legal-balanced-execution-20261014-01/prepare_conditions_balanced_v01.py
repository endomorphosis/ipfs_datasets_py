"""Freeze one source-only conditions-balanced repair plan from exact trained N10 bytes."""
import argparse
import importlib
import importlib.abc
import importlib.util
import os
from pathlib import Path
import sys

F=Path(__file__).resolve().parent
N10=F.parent/'legal-actor-features-20261013-01'
N11=F.parent/'legal-head-repair-20261014-01'
N12=F.parent/'legal-conditions-recall-20261014-01'
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
        if writing and (path!=F/'conditions-balanced-ce-plan-v01.json' or not bool(flags&os.O_EXCL)):
            raise AssertionError('Only exclusive new owned plan write allowed')

sys.meta_path.insert(0,NoNumerical());sys.addaudithook(audit)
spec=importlib.util.spec_from_file_location('conditions_balanced_plan_runner',F/'run_conditions_balanced_v01.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
_read=runner.read

def metadata(path,expected=None):
    runner.require('checkpoint' not in Path(path).name and 'reference-packet' not in Path(path).name,'Checkpoint/reference JSON parsing prohibited in preparation')
    return _read(path,expected)

runner.read=metadata

def qualify_baseline(baseline):
    return runner.resource_protocol().qualify_execution_baseline(baseline)


def prepare():
    artifacts={}
    def bind(path,expected=None):
        value=runner.pin(Path(path));runner.require(expected is None or value==expected,'Expected raw descriptor differs')
        brief={k:value[k] for k in ('bytes','sha256')}
        runner.require(value['path'] not in artifacts or artifacts[value['path']]==brief,'Raw artifact identity conflict')
        runner.require(value['path'] not in runner.READ_PINS or runner.READ_PINS[value['path']]==value,'Parsed/bound custody differs')
        artifacts[value['path']]=brief;return value
    completion_pin=bind(N11/'completion-review-v01.json');completion=metadata(completion_pin['path'],completion_pin)
    runner.require(completion['schema']=='conditions-presence-completion-review/v1' and completion['passed'] is True and completion['findings']==[],'Qualified completed N11 lineage required')
    final_pin=bind(N11/'final-integration-independent-review-v01.json')
    runner.require(completion['artifacts'][final_pin['path']]=={k:final_pin[k] for k in ('bytes','sha256')},'N11 final anchor must join completion receipt')
    final=metadata(final_pin['path'],final_pin)
    hub_pin=bind(N11/'hf-publication-actual-independent-review-v01.json')
    runner.require(completion['artifacts'][hub_pin['path']]=={k:hub_pin[k] for k in ('bytes','sha256')},'N11 publication anchor must join completion receipt')
    hub=metadata(hub_pin['path'],hub_pin)
    runner.require(final['schema']=='conditions-presence-final-integration-independent-review/v1' and final['passed'] is True and final['findings']==[]
        and hub['passed'] is True and hub['findings']==[] and final['HF_revision']==hub['revision']=='702caba2da183f9d98a0ffd12f1240243167aab2',
        'Qualified immutable N11 final/Hub join required')
    old_plan_pin=bind(N11/'conditions-presence-ce-plan-v01.json')
    runner.require(old_plan_pin['bytes']==52960 and old_plan_pin['sha256']=='83768d40f403a2e67a4fbfc61cf83f5c52cabd9b1a27a5ee3d51d891c6c6c25c'
        and hub['artifacts'][old_plan_pin['path']]=={k:old_plan_pin[k] for k in ('bytes','sha256')},'Retained N11 source recipe must join qualified publication')
    old_plan=metadata(old_plan_pin['path'],old_plan_pin)
    donor_plan_pin=bind(N10/'actor-features-ce-plan-v02.json')
    runner.require(donor_plan_pin['bytes']==46558 and donor_plan_pin['sha256']=='f433954ab6e9f26510096f308e879cac1b027bf33aa94a5df7bf765045e555fc','Exact N10 donor recipe required')
    freeze_pin=bind(N10/'actor-features-output-freeze-v01.json')
    runner.require(freeze_pin['bytes']==21187 and freeze_pin['sha256']=='56abf07cfc80b79ef7eb48a0f0579310ae8f555e15cc9c49d1f6fe23bd687e2a','Exact frozen N10 outputs anchor required')
    freeze=metadata(freeze_pin['path'],freeze_pin)
    runner.require(freeze['all_outputs_frozen'] is True and freeze['plan']==donor_plan_pin and len(freeze['results'])==62,'Full N10 freeze/plan closure required')
    summary_pin=bind(freeze['summary']['path'],freeze['summary']);summary=metadata(summary_pin['path'],summary_pin)
    runner.require(summary['schema']=='actor-features-cell-results/v1' and summary['status']=='completed' and summary['actual_new_updates']==32
        and summary['final_model_state_sha256']==runner.SOURCE_STATE_SHA,'Exact trained N10 source state required')
    source_checkpoint=bind(summary['checkpoint']['path'],summary['checkpoint'])
    runner.require(source_checkpoint['sha256']==runner.SOURCE_SHA and source_checkpoint['bytes']==6464267
        and freeze['results'][source_checkpoint['path']]=={k:source_checkpoint[k] for k in ('bytes','sha256')},'Opaque trained N10 checkpoint must join full freeze')
    owners={}
    runner.require(old_plan['schema']=='conditions-presence-cell-plan/v1' and len(old_plan['source_owner_pins'])==38,'Retained38 source owners required')
    for name,descriptor in old_plan['source_owner_pins'].items():
        new=bind(F/'datasets'/Path(descriptor['path']).relative_to(N11/'datasets'))
        runner.require(all(new[k]==descriptor[k] for k in ('bytes','sha256')),'Retained N11 source owner differs')
        owners[name]=new
    intake_pin=bind(N11/'continuation-main-intake-v01.json')
    runner.require(intake_pin['bytes']==149664 and intake_pin['sha256']=='3b8c56934ce39cf9a46d4df41d8656663695626f70ca499c84aea55d300f4b82','Exact upstream/38-owner preservation intake required')
    intake=metadata(intake_pin['path'],intake_pin)
    runner.require(intake['passed'] is True and intake['findings']==[] and intake['all38_prior_model_owners_unchanged'] is True,'Prior38-owner source preservation must be qualified')
    prefix='ipfs_datasets_py.optimizers.logic_theorem_optimizer.'
    candidate=F/'datasets/ipfs_datasets_py/optimizers/logic_theorem_optimizer/legal_span_conditions_balanced.py'
    candidate_test=F/'datasets/tests/unit/optimizers/logic_theorem_optimizer/test_legal_span_conditions_balanced_contracts.py'
    owners[prefix+'legal_span_conditions_balanced']=bind(candidate)
    original_plan_pin=bind(N12/'conditions-balanced-ce-plan-v01.json',dict(path=str(N12/'conditions-balanced-ce-plan-v01.json'),bytes=60156,sha256='77da735e19194c40acdf073f9646eb8363b4acccd8535f079aef75cf57d3899a'))
    original_plan=metadata(original_plan_pin['path'],original_plan_pin)
    runner.require(original_plan['schema']=='conditions-balanced-cell-plan/v1' and set(original_plan['source_owner_pins'])==set(owners)
        and all(all(owners[name][key]==descriptor[key] for key in ('bytes','sha256')) for name,descriptor in original_plan['source_owner_pins'].items()),'All39 original prepared model owners must remain byte-identical after relocation')
    trainer_pin=bind(N12/'trainer-source-independent-review-v01.json');trainer=metadata(trainer_pin['path'],trainer_pin)
    runner.require(trainer['schema']=='conditions-balanced-trainer-source-independent-review/v1' and trainer['passed'] is True and trainer['findings']==[],'Original qualified fixed balanced trainer required')
    for path in (candidate,candidate_test,F/'training-design-v01.json'):
        descriptor=bind(path);original_path=N12/path.relative_to(F);original=bind(original_path)
        runner.require(all(descriptor[key]==original[key] for key in ('bytes','sha256'))
            and trainer['artifacts'][str(original_path)] in (original,{k:original[k] for k in ('bytes','sha256')}),'Original trainer and exact relocated model/test/design bytes must join')
    contract_pin=bind(F/'evaluation-contract-v01.json');original_contract=bind(N12/'evaluation-contract-v01.json')
    runner.require(all(contract_pin[key]==original_contract[key] for key in ('bytes','sha256')),'Scientific evaluation contract must remain byte-identical')
    relocation_pin=bind(F/'trainer-relocation-source-independent-review-v01.json');relocation=metadata(relocation_pin['path'],relocation_pin)
    runner.require(relocation['schema']=='conditions-balanced-trainer-relocation-source-independent-review/v1'
        and relocation['passed'] is True and relocation['findings']==[] and relocation['original_trainer_review']==trainer_pin
        and relocation['source_owner_pins']==owners,'Exact original trainer and relocated39-owner source qualification required')
    for path in (candidate,candidate_test,F/'training-design-v01.json',F/'evaluation-contract-v01.json',Path(trainer_pin['path'])):
        descriptor=bind(path);runner.require(relocation['artifacts'][str(path)] in (descriptor,{k:descriptor[k] for k in ('bytes','sha256')}),'Relocation qualification must authenticate source/science and original trainer gate')
    references={name:{view:summary['diagnostics'][name][view] for view in ('raw','joint')} for name in runner.PANELS}
    references['training168']={view:summary['final_training_capture'][view] for view in ('raw','joint')}
    for pair in references.values():
        for descriptor in pair.values():
            bind(descriptor['path'],descriptor)
            runner.require(freeze['results'][descriptor['path']]=={k:descriptor[k] for k in ('bytes','sha256')},'All632 trained N10 score references must join frozen inventory')
    runner.require(old_plan['source_checkpoint']==source_checkpoint and old_plan['source_model_state_sha256']==runner.SOURCE_STATE_SHA and old_plan['source_reference_panels']==references,'Isolated loss comparison must reuse the exact N10 donor and all632 saved references')
    data_pin=bind(old_plan['data_export']['path'],old_plan['data_export']);data=metadata(data_pin['path'],data_pin)
    fresh_pin=bind(old_plan['fresh_source_export']['path'],old_plan['fresh_source_export']);fresh=metadata(fresh_pin['path'],fresh_pin)
    legacy=runner.legacy_runner();retained=legacy.prior_runner();helper=retained.helpers()
    sys.meta_path.insert(0,helper.NoEncoder());helper.bootstrap(F/'datasets')
    for name in ('legal_span_formula','legal_span_continuation','legal_span_split_features','legal_span_conditions_balanced'):
        importlib.import_module(prefix+name)
    importlib.import_module('ipfs_datasets_py.logic.legal_ir.joint_span_selection')
    importlib.import_module('ipfs_datasets_py.logic.formalization.autoencoder.retained_span_score_capture')
    loaded=retained.owner_origins(dict(source_owner_pins=owners))
    required={prefix+name for name in ('legal_span_formula','legal_span_continuation','legal_span_targeted_loss','legal_span_split_features','legal_span_actor_boundary','legal_span_actor_features','legal_span_conditions_balanced')}
    runner.require(len(loaded)==15 and len(required)==7 and required<=set(loaded)<=set(owners) and all(loaded[n]==owners[n] for n in loaded),'Exact actual15 loaded/seven mandatory source subset required')
    for path in (Path(__file__).resolve(),F/'run_conditions_balanced_v01.py',F/'run_scope_guardian_v02.py',runner.LEGACY_RUNNER,legacy.PRIOR_RUNNER,retained.HELPER,
        F/'evaluation-contract-v01.json',F/'training-design-v01.json',F/'resource-protocol-contract-v01.json',F/'resource-baseline-v01.json',F/'conditions_balanced_resource_protocol_v01.py'):
        bind(path)
    baseline_pin=bind(F/'resource-baseline-v01.json');baseline=metadata(baseline_pin['path'],baseline_pin);qualify_baseline(baseline)
    for key in ('observer','source_qualification','fresh_metadata_check','resource_contract','sampler_source_qualification','resource_bridge_source_qualification'):
        descriptor=baseline[key];bind(descriptor['path'],descriptor)
    baseline_gate=metadata(baseline['source_qualification']['path'],baseline['source_qualification'])
    runner.require(baseline_gate['schema']=='conditions-balanced-resource-observer-source-independent-review/v1'
        and baseline_gate['passed'] is True and baseline_gate['findings']==[] and baseline_gate['observer']==baseline['observer'],
        'Exact actual baseline observer source qualification required')
    for path,approved in baseline_gate['artifacts'].items():
        bind(path,dict(path=path,**{k:approved[k] for k in ('bytes','sha256')}))
    clearance_pin=bind(F/'capacity-clearance-v01.json');clearance=metadata(clearance_pin['path'],clearance_pin)
    runner.qualify_capacity_clearance(clearance,for_training=False)
    for key in ('observer','source_qualification','input_manifest','resource_contract','baseline','fresh_metadata_check'):
        descriptor=clearance[key];bind(descriptor['path'],descriptor)
    clearance_inputs=metadata(clearance['input_manifest']['path'],clearance['input_manifest'])
    runner.require(clearance_inputs['schema']=='conditions-balanced-capacity-clearance-inputs/v1'
        and clearance_inputs['baseline']==baseline_pin and clearance_inputs['contract']==clearance['resource_contract']
        and clearance_inputs['sample_receipt']==clearance['private_sample_receipt'] and clearance_inputs['check']==clearance['fresh_metadata_check']
        and clearance_inputs['sampler_qualification']==clearance['sampler_source_qualification']
        and clearance_inputs['bridge_qualification']==clearance['resource_bridge_source_qualification'],
        'Actual clearance must bind exact baseline/fresh copied endpoint and producer qualification descriptors')
    clearance_gate=metadata(clearance['source_qualification']['path'],clearance['source_qualification'])
    runner.require(clearance_gate['schema']=='conditions-balanced-capacity-clearance-source-independent-review/v1'
        and clearance_gate['passed'] is True and clearance_gate['findings']==[] and clearance_gate['observer']==clearance['observer'],
        'Exact independent clearance observer source qualification required')
    for path,approved in clearance_gate['artifacts'].items():
        bind(path,dict(path=path,**{k:approved[k] for k in ('bytes','sha256')}))
    for key in ('library_pin','ctypes_util_pin','cuda_pathfinder_pin'):
        descriptor=old_plan['ctypes_dl_resolution'][key];bind(descriptor['path'],descriptor)
    forbidden=list(old_plan['forbidden_reference_paths'])+[str(N12/name) for name in ('diagnose_conditions_balanced_oracle_v01.py','conditions-balanced-oracle-diagnostic-v01.json','parent-conditions-balanced-baseline-v01.json')]+[str(N11/name) for name in ('conditions-presence-result-analysis-v01.json','conditions-presence-independent-recount-v01.json','conditions-presence-output-freeze-v01.json','conditions-presence-ce-runtime-review-v01.json')]+[str(F/name) for name in ('diagnose_conditions_balanced_oracle_v01.py','conditions-balanced-oracle-diagnostic-v01.json','parent-conditions-balanced-baseline-v01.json')]
    smoke_pin=bind(F/'conditions-balanced-bootstrap-smoke-controls-v01.json');smoke=metadata(smoke_pin['path'],smoke_pin)
    runner.require(smoke['passed'] is True and smoke['findings']==[] and smoke['runner']==bind(F/'run_conditions_balanced_v01.py')
        and smoke['loaded_owner_count']==15 and smoke['mandatory_loaded_owner_count']==7 and smoke['all39_raw_source_owner_pins_closed'] is True
        and smoke['exact_production_bootstrap_used'] is True and smoke['loaded_owners']==loaded,'Actual source-only production-bootstrap smoke required')
    bind(smoke['controls_source']['path'],smoke['controls_source'])
    peer_pin=bind(F/'runner-preparer-source-independent-review-v01.json');peer=metadata(peer_pin['path'],peer_pin)
    runner.require(peer['schema']=='conditions-balanced-runner-preparer-source-independent-review/v1' and peer['passed'] is True and peer['findings']==[],'Exact independent recipe source qualification required')
    for path in (Path(__file__).resolve(),F/'run_conditions_balanced_v01.py',F/'conditions_balanced_bootstrap_smoke_controls_v01.py',F/'conditions-balanced-bootstrap-smoke-controls-v01.json'):
        descriptor=bind(path);runner.require(peer['artifacts'][str(path)] in (descriptor,{k:descriptor[k] for k in ('bytes','sha256')}),'Peer review must bind exact recipe/smoke sources and actual receipt')
    plan=dict(schema='conditions-balanced-cell-plan/v1',package_root=str(F/'datasets'),runner_path=str(F/'run_conditions_balanced_v01.py'),guardian_path=str(F/'run_scope_guardian_v02.py'),
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
    print(runner.write(F/'conditions-balanced-ce-plan-v01.json',plan))

if __name__=='__main__':
    argparse.ArgumentParser(description=__doc__).parse_args();prepare()
