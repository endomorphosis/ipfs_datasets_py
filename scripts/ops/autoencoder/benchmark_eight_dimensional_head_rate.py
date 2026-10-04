#!/usr/bin/env python3
"""Matched8D head-rate continuation; source encoders and selection stay fixed."""
import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

AUTO='ipfs_datasets_py/logic/formalization/autoencoder/'
PREFIX='ipfs_datasets_py.logic.formalization.autoencoder.'
HELPER=AUTO+'eight_dimensional_head_rate_experiment.py'
PARENT_RUNNER='scripts/ops/autoencoder/benchmark_object_auxiliary_continuation.py'
ARMS=[dict(name='head-rate10-baseline',non_action_learning_rate_multiplier=10.),
      dict(name='head-rate2-candidate',non_action_learning_rate_multiplier=2.)]
FALSE=dict(qualified=False,admitted=False,proof_authority=False,checkpoint_promoted=False,formalized=False,
    roundtrip_ok=False,source_semantics_verified=False,convergence_proven=False,lake_executed=False,
    native_validation_executed=False,fresh_holdout=False,historical_linguistic_teacher_modified=False)
FIXED=dict(schema='eight-dimensional-head-rate-plan/v1',dimensions=[8],seed=1729,arms=ARMS,fit_count=2,
    parent='R9/8-source-head-lr10-1729/last-attempt',fresh_optimizer=True,exact_optimizer_resume=False,
    learning_rate=.001,epochs_per_stage=10,optimizer_steps=170,row_presentations=1220,
    target_token_presentations=112920,count_presentations=1220,source_value_presentations=12800,
    balanced_counts={'1':305,'2':305,'4':305,'8':305},cardinality_weight=.25,source_value_weight=.25,
    action_contrastive_weight=.05,generated_boundary_weight=.05,boundary_site_policy='first_last',boundary_retry=True,
    full_vocabulary_size=32,context_tokens=512,max_target_tokens=512,temperature=0,
    encoder_executed=False,downloads_performed=False,preprocessing_refitted=False,architecture_changed=False,
    optimizer_groups_unchanged=True,head_rate_scaled_weight_decay=True,selection_unchanged=True,
    additional_sources=False,additional_losses=False,source_representation='historical_linguistic_feature_hash8;not_semantic_embeddings',
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
        for k,v in FIXED.items()),'fixed8D optimizer recipe differs')


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
    spec=importlib.util.spec_from_file_location('_eight_head_rate_parent',root/PARENT_RUNNER)
    owner=importlib.util.module_from_spec(spec);spec.loader.exec_module(owner)
    previous=SimpleNamespace(**vars(args));previous.extension_root=root
    previous.manifest=Path(manifest['parent_manifest']);previous.plan=Path(manifest['parent_plan'])
    ctx=owner.load_context(previous);owner.source_inventory(previous,ctx)
    old=package_inventory()
    helper=ctx['helpers'].extension(args.extension_root,HELPER,PREFIX+'eight_dimensional_head_rate_experiment',manifest['extensions'])
    require(helper.ARMS==ARMS,'helper arm inventory differs')
    ctx.update(rate_manifest=manifest,rate_plan=plan,rate_parent=owner,rate_helper=helper,rate_old_inventory=old,
        rate_manifest_sha256=sha(args.manifest),rate_plan_sha256=sha(args.plan))
    return ctx


def source_inventory(args,ctx):
    inventory=package_inventory();allowed=dict(ctx['rate_old_inventory'])
    allowed.update({str((args.extension_root/rel).resolve()):h for rel,h in ctx['rate_manifest']['extensions'].items()})
    for path,value in inventory.items():require(allowed.get(path)==value,'unregistered source mutation: '+path)
    return inventory


def train_candidate(lane,model,arm):
    require(arm in ARMS,'registered head-rate arm required')
    return lane['owners']['long_span_source_value_training'].train(model,lane['rows']['train'],lane['rows']['validation'],
        training_references=lane['references']['train'],validation_references=lane['references']['validation'],
        codec=lane['donor']['codec'],input_transform=lane['donor']['input_transform'],lineage=lane['lineage'],
        validate_rule=lane['validate_rule'],validator_id=lane['validator_id'],curriculum=lane['stages'],
        strategy='semantic_fields',cardinality_weight=.25,count_exposure='balanced_all',source_value_weight=.25,
        source_contexts=lane['source_contexts'],action_contrastive_weight=.05,generated_boundary_weight=.05,
        generated_boundary_site_policy='first_last',generated_boundary_retry_on_mismatch=True,
        generated_source_margin_weight=0.,generated_source_margin_replay=False,
        non_action_learning_rate_multiplier=arm['non_action_learning_rate_multiplier'],
        config=dict(seed=1729,max_seconds=180,max_target_tokens=512,batch_size=8,learning_rate=.001,
            max_optimizer_steps=1000,patience=0,validation_interval=4,alpha=0.,max_memory_bytes=1073741824))


def validate_report(lane,report,arm,parent_sha):
    require(report['stopped_reason']=='epochs_completed' and report['optimizer_steps']==170 and report['row_presentations']==1220
        and report['valid_target_token_presentations']==112920 and report['count_training_row_presentations']==1220
        and report['source_value_presentations']==12800 and report['count_training_presentations_by_class']==FIXED['balanced_counts'],'unequal or incomplete training work')
    require(report['initial_weights_sha256']==parent_sha and report['optimizer_resumable'] is False
        and report['config']['learning_rate']==.001 and report['non_action_learning_rate_multiplier']==arm['non_action_learning_rate_multiplier'],'parent/optimizer differs')
    require(all(report[k] is False for k in ('qualified','admitted','proof_authority','convergence_proven','lake_executed')),'authority changed')
    for update in report['committed_updates']:
        lane['parent_runner'].validate_boundary_retry_receipt(update['generated_boundary'])
        rates=update['optimizer_group_learning_rates']
        require(set(rates)=={'base','non_action_head'} and rates['non_action_head']==rates['base']*arm['non_action_learning_rate_multiplier'],'two-group proportional rates differ')
    require(not any(k.startswith('auxiliary_source_') for k in report),'an additional loss was enabled')


def execute(args):
    started=time.monotonic();ctx=load_context(args);save=ctx['helpers'].save;before=source_inventory(args,ctx)
    args.output.mkdir(parents=True);save(args.output/'sealed-recipe.json',dict(plan=ctx['rate_plan'],manifest=ctx['rate_manifest'],**FALSE))
    lane=ctx['rate_parent'].prepare_lane(ctx);parent=ctx['parent_runs']['8'];choice=ctx['object_parent'].ENDPOINTS['8'];ref=parent['states'][choice['role']]
    parent_state=bound_json(ctx['rate_manifest'],ref['path'],ref['sha256'])
    diagnosis=ctx['rate_helper'].diagnose_source_geometry(lane['source_contexts'],parent_state['model_state'],input_transform=parent_state['input_transform'])
    save(args.output/'source-geometry.json',diagnosis)
    for name,value in [('preprocessing',lane['preparation']),('source-contexts',lane['source_contexts']),('training-rows',lane['rows'])]:save(args.output/'8'/(name+'.json'),value)
    runs=[];baseline_report=None
    for arm in ARMS:
        require(time.monotonic()-started<900,'trial deadline');ctx['rate_helper'].multiplier(arm);folder=args.output/arm['name']
        model=ctx['object_parent'].restore_model(lane,ref,parent['recipe'],choice['role'])
        initial=lane['clause_runner'].evaluate(lane,model,'validation','conditioned')
        old=bound_json(ctx['rate_manifest'],parent['postfit'][choice['role']]['validation']['path'],parent['postfit'][choice['role']]['validation']['sha256'])
        require(initial['predictions']==old['predictions'],'initial checkpoint predictions differ');save(folder/'parent-validation.json',initial)
        if args.phase=='preflight':
            runs.append(dict(arm=arm['name'],initial_predictions_equal=True,parent_tensor_sha256=ref['tensor_sha256']));continue
        states={'initial':lane['native_runner'].save_state(lane,model,arm,'initial',False,folder/'initial-state.json')}
        fit_start=time.monotonic();result=train_candidate(lane,model,arm);seconds=time.monotonic()-fit_start
        report=result['report'];training_ref=save(folder/'training.json',report);validate_report(lane,report,arm,ref['tensor_sha256'])
        if arm is ARMS[0]:
            baseline_report=report
            old_report=bound_json(ctx['rate_manifest'],ctx['rate_manifest']['baseline_training'])
            require(report['selected_weights_sha256']==old_report['selected_weights_sha256'] and
                report['last_complete_attempt_weights_sha256']==old_report['last_complete_attempt_weights_sha256'],'historical baseline tensor replay differs')
        else:
            for key in ('committed_decoder_batch_ids_sha256','committed_count_batch_ids_sha256'):
                require(report[key]==baseline_report[key],'paired source exposure differs')
            require([u['decoder_row_ids'] for u in report['committed_updates']]==[u['decoder_row_ids'] for u in baseline_report['committed_updates']],'paired decoder batches differ')
        panels={}
        for role,state,predictions in [('selected',result['state_dict'],result['predictions']),('last-attempt',result['last_complete_attempt_state_dict'],result['last_complete_attempt_predictions'])]:
            require(state is not None,'complete endpoint missing');lane['native_runner'].validate_wrapper_state(lane,state);model.load_state_dict(state,strict=True)
            expected=report['selected_weights_sha256'] if role=='selected' else report['last_complete_attempt_weights_sha256']
            require(lane['core'].tensor_digest(model)==expected,'endpoint hash differs')
            states[role]=lane['native_runner'].save_state(lane,model,arm,role,role=='selected' or report['last_complete_attempt_is_selected'],folder/(role+'-state.json'))
            compact=lane['continuation_runner'].evaluate_original_panels(lane,model,predictions,folder/role)
            require(set(compact)=={'training','validation','zero-condition','source-shuffle','cross-length-shuffle',
                'context-only-shuffle','context-reverse','context-rotate','recurrent-residual-off'},'complete nine-control inventory required')
            panels[role]={label:dict(path=str(folder/role/('evaluation-'+label+'.json')),sha256=sha(folder/role/('evaluation-'+label+'.json')),
                numerical=panel['numerical'],fidelity=panel['source_fidelity']) for label,panel in compact.items()}
        record=dict(arm=arm['name'],dimension=8,seed=1729,recipe=arm,parent_endpoint=choice,parent_state=ref,states=states,training_ref=training_ref,
            postfit=panels,budget_completed=True,fresh_optimizer=True,exact_optimizer_resume=False,training_call_elapsed_seconds=seconds,**FALSE)
        entry=save(folder/'summary.json',record);runs.append(dict(arm=arm['name'],summary_path=entry['path'],summary_sha256=entry['sha256']))
        print(json.dumps(dict(arm=arm['name'],steps=report['optimizer_steps'],selected_epoch=report['selected_epoch'],final_exact=report['last_complete_attempt']['fidelity']['metrics']['ordered_exact'],fit_seconds=seconds)),flush=True)
    after=source_inventory(args,ctx);require(before==after,'package source set changed')
    for path,wanted in ctx['rate_manifest']['inputs'].items():require(sha(path)==wanted,'sealed input changed')
    for rel,wanted in ctx['rate_manifest']['extensions'].items():require(sha(args.extension_root/rel)==wanted,'extension changed')
    require(sha(args.manifest)==ctx['rate_manifest_sha256'] and sha(args.plan)==ctx['rate_plan_sha256'],'run seal changed')
    require(time.monotonic()-started<900,'trial deadline exceeded before summary')
    summary=dict(schema='eight-dimensional-head-rate-comparison/v1',complete=len(runs)==2,phase=args.phase,runs=runs,
        source_dependencies=after,elapsed_seconds=time.monotonic()-started,**FALSE)
    save(args.output/'summary.json',summary);return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('dependency-root','extension-root','manifest','plan','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--phase',choices=['preflight','training'],required=True);execute(parser.parse_args())
if __name__=='__main__':main()
