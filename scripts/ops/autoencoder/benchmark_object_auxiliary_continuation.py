#!/usr/bin/env python3
"""Matched source-field supervision from one fixed8D formula-sidecar checkpoint."""
import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
import traceback
from types import SimpleNamespace

AUTO='ipfs_datasets_py/logic/formalization/autoencoder/'
PREFIX='ipfs_datasets_py.logic.formalization.autoencoder.'
PARENT_RUNNER='scripts/ops/autoencoder/benchmark_formula_checkpoint_continuation.py'
HELPER=AUTO+'source_object_auxiliary_training.py'
TRAINER=AUTO+'long_span_source_value_training.py'
FALSE=dict(qualified=False,admitted=False,proof_authority=False,checkpoint_promoted=False,formalized=False,
    roundtrip_ok=False,source_semantics_verified=False,convergence_proven=False,lake_executed=False,
    native_validation_executed=False,fresh_holdout=False,historical_linguistic_teacher_modified=False)
ARMS=[dict(name='no-auxiliary',field=None,weight=0.),dict(name='modality-matched',field='modality',weight=.05),
      dict(name='object-matched',field='object',weight=.05)]
FIXED=dict(schema='object-auxiliary-continuation-plan/v1',dimensions=[8],seed=1729,arms=ARMS,fit_count=3,
    parent='R9/8-source-head-lr10-1729/last-attempt',fresh_optimizer=True,exact_optimizer_resume=False,
    learning_rate=.001,non_action_learning_rate_multiplier=10.,epochs_per_stage=10,optimizer_steps=170,
    row_presentations=1220,target_token_presentations=112920,count_presentations=1220,source_value_presentations=12800,
    balanced_counts={'1':305,'2':305,'4':305,'8':305},cardinality_weight=.25,source_value_weight=.25,
    action_contrastive_weight=.05,generated_boundary_weight=.05,boundary_site_policy='first_last',
    boundary_retry=True,replay_atol=2e-5,replay_rtol=2e-5,auxiliary_batch_size=6,auxiliary_presentations=1020,
    auxiliary_sampling='existing_independent_modality_style_strata',same_auxiliary_source_indices=True,
    additional_training_sources=False,additional_training_labels=False,auxiliary_used_for_selection=False,
    full_vocabulary_size=32,context_tokens=512,max_target_tokens=512,temperature=0,
    encoder_executed=False,downloads_performed=False,preprocessing_refitted=False,architecture_changed=False,
    source_representation='nonsemantic_linguistic_feature_hash8;not_historical_teacher',selection_unchanged=True,
    max_seconds_per_fit=180,max_seconds_entire_run=900,memory_bytes_per_fit=1073741824,
    historical_linguistic_teacher_modified=False,bridge_names=[],legal_ir_evaluate_provers=False,metric_disk_cache_used=False)

def require(value,message):
    if not value:raise ValueError(message)

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1048576),b''):h.update(block)
    return h.hexdigest()

def bound_json(manifest,path,expected=None):
    path=Path(path).resolve();raw=path.read_bytes();wanted=manifest['inputs'].get(str(path))
    require(wanted is not None and (expected is None or wanted==expected) and hashlib.sha256(raw).hexdigest()==wanted,'unbound or changed input: '+str(path))
    return json.loads(raw)

def validate_plan(plan):
    require(type(plan) is dict and all(type(plan.get(k)) is type(v) and json.dumps(plan[k],sort_keys=True,allow_nan=False)==json.dumps(v,sort_keys=True,allow_nan=False)
        for k,v in FIXED.items()),'fixed matched-object recipe differs')

def package_inventory():
    result={}
    for name,module in list(sys.modules.items()):
        if name!='ipfs_datasets_py' and not name.startswith('ipfs_datasets_py.'):continue
        path=getattr(module,'__file__',None)
        if path:result[str(Path(path).resolve())]=sha(path)
    return result

def load_context(args):
    manifest=json.loads(args.manifest.read_bytes());plan=json.loads(args.plan.read_bytes());validate_plan(plan)
    require(sha(args.plan)==manifest['plan_sha256'] and plan['input_sha256']==manifest['inputs'],'plan seal differs')
    for path,wanted in manifest['inputs'].items():require(sha(path)==wanted,'sealed input changed')
    for rel,wanted in manifest['extensions'].items():require(sha(args.extension_root/rel)==wanted,'frozen extension changed')
    parent=bound_json(manifest,manifest['parent_manifest']);bound_json(manifest,manifest['parent_plan'])
    root=Path(manifest['parent_extension_root']);require(sha(root/PARENT_RUNNER)==parent['extensions'][PARENT_RUNNER],'parent runner changed')
    spec=importlib.util.spec_from_file_location('_object_auxiliary_parent',root/PARENT_RUNNER)
    owner=importlib.util.module_from_spec(spec);spec.loader.exec_module(owner)
    previous=SimpleNamespace(**vars(args),**{})
    previous.extension_root=root;previous.manifest=Path(manifest['parent_manifest']);previous.plan=Path(manifest['parent_plan'])
    ctx=owner.load_context(previous)
    ctx['comparison_owner'].source_inventory(ctx['comparison_parent_args'],ctx)
    old=package_inventory();package=sys.modules[PREFIX[:-1]]
    helper=ctx['helpers'].extension(args.extension_root,HELPER,PREFIX+'source_object_auxiliary_training',manifest['extensions'])
    setattr(package,'source_object_auxiliary_training',helper)
    trainer=ctx['helpers'].extension(args.extension_root,TRAINER,PREFIX+'_object_auxiliary_training_owner',manifest['extensions'])
    ctx['owners']['long_span_source_value_training']=trainer
    ctx.update(object_manifest=manifest,object_plan=plan,object_parent=owner,object_old_inventory=old,
        object_manifest_sha256=sha(args.manifest),object_plan_sha256=sha(args.plan),object_helper=helper)
    return ctx

def source_inventory(args,ctx):
    inventory=package_inventory();allowed=dict(ctx['object_old_inventory'])
    allowed.update({str((args.extension_root/rel).resolve()):h for rel,h in ctx['object_manifest']['extensions'].items()})
    for path,value in inventory.items():require(allowed.get(path)==value,'unregistered source mutation: '+path)
    return inventory

def prepare_lane(ctx):
    lane=ctx['object_parent'].prepare_lane(ctx,8)
    bank=bound_json(ctx['object_manifest'],ctx['object_manifest']['auxiliary_bank'])
    ctx['object_helper'].validate_training_binding(bank,lane['rows']['train'],lane['rows']['validation'],
        source_contexts=lane['source_contexts'],codec=lane['donor']['codec'],deadline=time.monotonic()+30)
    require(bank['bank_kind']=='used113' and bank['dimension']==8 and bank['selected_rows']==113,'exact actual8D training bank required')
    lane['auxiliary_bank']=bank;return lane

def train_candidate(lane,model,arm):
    require(arm in ARMS,'unregistered field arm');extra={}
    if arm['field']:
        extra['auxiliary_source_'+arm['field']+'_bank']=lane['auxiliary_bank']
        extra['auxiliary_source_'+arm['field']+'_weight']=arm['weight']
    return lane['owners']['long_span_source_value_training'].train(model,lane['rows']['train'],lane['rows']['validation'],
        training_references=lane['references']['train'],validation_references=lane['references']['validation'],
        codec=lane['donor']['codec'],input_transform=lane['donor']['input_transform'],lineage=lane['lineage'],
        validate_rule=lane['validate_rule'],validator_id=lane['validator_id'],curriculum=lane['stages'],
        strategy='semantic_fields',cardinality_weight=.25,count_exposure='balanced_all',source_value_weight=.25,
        source_contexts=lane['source_contexts'],action_contrastive_weight=.05,generated_boundary_weight=.05,
        generated_boundary_site_policy='first_last',generated_boundary_retry_on_mismatch=True,
        generated_source_margin_weight=0.,generated_source_margin_replay=False,non_action_learning_rate_multiplier=10.,
        config=dict(seed=1729,max_seconds=180,max_target_tokens=512,batch_size=8,learning_rate=.001,
            max_optimizer_steps=1000,patience=0,validation_interval=4,alpha=0.,max_memory_bytes=1073741824),**extra)

def validate_report(lane,report,arm,parent_sha):
    require(report['stopped_reason']=='epochs_completed' and report['optimizer_steps']==170 and report['row_presentations']==1220
        and report['valid_target_token_presentations']==112920 and report['count_training_row_presentations']==1220
        and report['source_value_presentations']==12800 and report['count_training_presentations_by_class']==FIXED['balanced_counts'],'unequal or incomplete training work')
    require(report['initial_weights_sha256']==parent_sha and report['optimizer_resumable'] is False
        and report['config']['learning_rate']==.001 and report['non_action_learning_rate_multiplier']==10.,'parent/optimizer differs')
    require(all(report[k] is False for k in ('qualified','admitted','proof_authority','convergence_proven','lake_executed')),'authority changed')
    for update in report['committed_updates']:lane['parent_runner'].validate_boundary_retry_receipt(update['generated_boundary'])
    for field in ('modality','object'):
        prefix='auxiliary_source_'+field
        if arm['field']==field:
            require(report[prefix+'_weight']==.05 and report[prefix+'_committed_updates']==170
                and report[prefix+'_presentations']==1020 and report[prefix+'_used_for_selection'] is False,'auxiliary work differs')
            for i,update in enumerate(report['committed_updates']):
                item=update[prefix];r=item['receipt']
                require(item['zero_based_committed_step']==i and r['committed_step']==i and r['full_vocabulary_size']==32
                    and r['batch_size']==6 and r['loss_field']==field and r['encoder_forward_calls']==r['recurrent_forward_calls']==0,
                    'source-only full-vocabulary objective differs')
        else:require(not any(k.startswith(prefix) for k in report),'unrequested auxiliary enabled')

def execute(args):
    started=time.monotonic();ctx=load_context(args);save=ctx['helpers'].save;before=source_inventory(args,ctx)
    args.output.mkdir(parents=True);save(args.output/'sealed-recipe.json',dict(plan=ctx['object_plan'],manifest=ctx['object_manifest'],**FALSE))
    lane=prepare_lane(ctx);parent=ctx['parent_runs']['8'];choice=ctx['object_parent'].ENDPOINTS['8'];ref=parent['states'][choice['role']]
    for name,value in [('preprocessing',lane['preparation']),('source-contexts',lane['source_contexts']),('training-rows',lane['rows']),('auxiliary-bank',lane['auxiliary_bank'])]:save(args.output/'8'/(name+'.json'),value)
    runs=[];indices=None
    for arm in ARMS:
        require(time.monotonic()-started<900,'trial deadline');folder=args.output/arm['name']
        model=ctx['object_parent'].restore_model(lane,ref,parent['recipe'],choice['role'])
        initial=lane['clause_runner'].evaluate(lane,model,'validation','conditioned')
        old=bound_json(ctx['object_manifest'],parent['postfit'][choice['role']]['validation']['path'],parent['postfit'][choice['role']]['validation']['sha256'])
        require(initial['predictions']==old['predictions'],'initial checkpoint predictions differ');save(folder/'parent-validation.json',initial)
        if args.phase=='preflight':
            # Exercise real auxiliary cache/source binding without an optimizer.
            helper=lane['object_helper'] if arm['field']=='object' else lane['owners']['source_modality_auxiliary_training']
            if arm['field']:
                cache=helper.prepare_tensor_cache(lane['core']._torch(),model,lane['auxiliary_bank'],codec=lane['donor']['codec'],input_transform=lane['donor']['input_transform'],seed=1729,deadline=time.monotonic()+30,max_optimizer_steps=170)
                current=[list(helper.select_indices(cache,i)) for i in range(170)]
                if indices is not None:require(current==indices,'auxiliary source exposure differs')
                indices=current;save(folder/'cache-receipt.json',cache.receipt)
            runs.append(dict(arm=arm['name'],initial_predictions_equal=True,parent_tensor_sha256=ref['tensor_sha256']));continue
        states={'initial':lane['native_runner'].save_state(lane,model,arm,'initial',False,folder/'initial-state.json')}
        fit_start=time.monotonic()
        try:result=train_candidate(lane,model,arm)
        except Exception as error:
            save(folder/'failure.json',dict(exception_type=type(error).__name__,message_omitted=True,
                traceback_frames=[dict(file=f.filename,line=f.lineno,function=f.name) for f in traceback.extract_tb(error.__traceback__)],
                caller_tensor_unchanged=lane['core'].tensor_digest(model)==ref['tensor_sha256'],**FALSE));raise
        seconds=time.monotonic()-fit_start;report=result['report'];training_ref=save(folder/'training.json',report);validate_report(lane,report,arm,ref['tensor_sha256'])
        if arm['field']:
            current=[u['auxiliary_source_'+arm['field']]['receipt']['row_ids'] for u in report['committed_updates']]
            if indices is not None:require(current==indices,'auxiliary per-step exposure differs')
            indices=current
        panels={}
        for role,state,predictions in [('selected',result['state_dict'],result['predictions']),('last-attempt',result['last_complete_attempt_state_dict'],result['last_complete_attempt_predictions'])]:
            require(state is not None,'complete endpoint missing');lane['native_runner'].validate_wrapper_state(lane,state);model.load_state_dict(state,strict=True)
            expected=report['selected_weights_sha256'] if role=='selected' else report['last_complete_attempt_weights_sha256']
            require(lane['core'].tensor_digest(model)==expected,'endpoint hash differs')
            states[role]=lane['native_runner'].save_state(lane,model,arm,role,role=='selected' or report['last_complete_attempt_is_selected'],folder/(role+'-state.json'))
            compact=lane['continuation_runner'].evaluate_original_panels(lane,model,predictions,folder/role)
            panels[role]={label:dict(path=str(folder/role/('evaluation-'+label+'.json')),sha256=sha(folder/role/('evaluation-'+label+'.json')),
                numerical=panel['numerical'],fidelity=panel['source_fidelity']) for label,panel in compact.items()}
        record=dict(arm=arm['name'],dimension=8,seed=1729,recipe=arm,parent_endpoint=choice,parent_state=ref,states=states,training_ref=training_ref,
            postfit=panels,budget_completed=True,fresh_optimizer=True,exact_optimizer_resume=False,training_call_elapsed_seconds=seconds,**FALSE)
        entry=save(folder/'summary.json',record);runs.append(dict(arm=arm['name'],summary_path=entry['path'],summary_sha256=entry['sha256']))
        print(json.dumps(dict(arm=arm['name'],steps=report['optimizer_steps'],selected_epoch=report['selected_epoch'],final_exact=report['last_complete_attempt']['fidelity']['metrics']['ordered_exact'],fit_seconds=seconds)),flush=True)
    after=source_inventory(args,ctx);require(before==after,'package source set changed')
    for path,wanted in ctx['object_manifest']['inputs'].items():require(sha(path)==wanted,'sealed input changed')
    for rel,wanted in ctx['object_manifest']['extensions'].items():require(sha(args.extension_root/rel)==wanted,'extension changed')
    require(sha(args.manifest)==ctx['object_manifest_sha256'] and sha(args.plan)==ctx['object_plan_sha256'],'run seal changed')
    summary=dict(schema='object-auxiliary-continuation-comparison/v1',complete=len(runs)==3,phase=args.phase,runs=runs,source_dependencies=after,
        matched_auxiliary_source_sequence_sha256=None if indices is None else lane['core'].digest(indices),elapsed_seconds=time.monotonic()-started,**FALSE)
    save(args.output/'summary.json',summary);return summary

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('dependency-root','extension-root','manifest','plan','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--phase',choices=['preflight','training'],required=True);execute(parser.parse_args())
if __name__=='__main__':main()
