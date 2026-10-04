#!/usr/bin/env python3
"""Two preregistered 384D/768D continuations of authenticated selected states.

The historical R10 runner and all numerical producers remain frozen. This driver
restores its selected LR.001 endpoints, resets optimizer state, and uses a fixed
initial LR.0001 with the unchanged plateau scheduler. No new cohort is selected
on or read here. Previously exposed development panels keep their original gate.
"""
import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import time
from types import SimpleNamespace

PARENT_RUNNER='scripts/ops/autoencoder/benchmark_formula_checkpoint_continuation.py'
RUNNER='scripts/ops/autoencoder/benchmark_selected_checkpoint_continuation.py'
ENDPOINTS={str(d):dict(arm=f'{d}-continue-lr001-1729',role='selected') for d in (384,768)}
ARM=dict(name='continue-lr0001',learning_rate=.0001)
FALSE=dict(qualified=False,admitted=False,proof_authority=False,source_semantics_verified=False,
    checkpoint_promoted=False,convergence_proven=False,fresh_holdout=False,fresh_authored_holdout=False,
    lake_executed=False,native_validation_executed=False,formalized=False,roundtrip_ok=False)
FIXED=dict(schema='selected-checkpoint-continuation-plan/v1',dimensions=[384,768],seed=1729,
    endpoints=ENDPOINTS,arm=ARM,fit_count=2,epochs_per_stage=10,optimizer_steps_per_fit=170,
    row_presentations=1220,count_presentations=1220,valid_target_token_presentations=112920,
    source_value_presentations=12800,balanced_counts={'1':305,'2':305,'4':305,'8':305},
    fresh_optimizer=True,fresh_scheduler=True,exact_optimizer_resume=False,initial_learning_rate=.0001,
    inherited_plateau_scheduler_unchanged=True,non_action_learning_rate_multiplier=10.,
    architecture_changed=False,preprocessing_refitted=False,selection_unchanged=True,
    source_value_weight=.25,cardinality_weight=.25,action_contrastive_weight=.05,generated_boundary_weight=.05,
    generated_boundary_site_policy='first_last',strict_boundary_retry=True,boundary_atol=2e-5,boundary_rtol=2e-5,
    auxiliary384='used113_modality.05_independent',auxiliary768=None,auxiliary_presentations384=1020,
    fixed_encoder_context_tokens=512,fixed_decoder_output_limit=512,temperature=0,batch_size=8,vocabulary_size=32,
    max_seconds_per_fit=180,max_seconds_per_postfit=30,max_seconds_entire_run=900,
    memory_bytes_per_fit=1073741824,workers=1,encoder_executed=False,downloads_performed=False,
    historical_linguistic_teacher_modified=False,bridge_names=[],legal_ir_evaluate_provers=False,
    metric_disk_cache_used=False,new_cohort_read=False,new_cohort_used_for_selection=False,
    exposed_style_aggregate_already_observed_before_preregistration=True,recipe_not_tuned_from_style_results=True)


def require(value,message):
    if not value:raise ValueError(message)


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
    return h.hexdigest()


def bound(manifest,path,expected=None):
    path=Path(path).resolve();wanted=manifest['inputs'].get(str(path));require(wanted is not None and
        (expected is None or expected==wanted),'unbound selected-continuation input: '+str(path))
    raw=path.read_bytes();require(hashlib.sha256(raw).hexdigest()==wanted,'bound input changed');return json.loads(raw)


def validate_plan(plan):
    require(type(plan) is dict and all(type(plan.get(k)) is type(v) and
        json.dumps(plan[k],sort_keys=True,allow_nan=False)==json.dumps(v,sort_keys=True,allow_nan=False)
        for k,v in FIXED.items()),'selected continuation recipe differs')


def load_context(args):
    manifest=json.loads(args.manifest.read_bytes());plan=json.loads(args.plan.read_bytes());validate_plan(plan)
    require(sha(args.plan)==manifest['plan_sha256'] and plan['input_sha256']==manifest['inputs'],'sealed plan differs')
    for path,wanted in manifest['inputs'].items():require(sha(path)==wanted,'sealed input changed: '+path)
    for relative,wanted in manifest['extensions'].items():require(sha(args.extension_root/relative)==wanted,'frozen selected runner changed')
    parent=bound(manifest,manifest['parent_manifest']);bound(manifest,manifest['parent_plan'])
    root=Path(manifest['parent_extension_root']);require(sha(manifest['parent_plan'])==parent['plan_sha256'],'parent plan seal differs')
    for relative,wanted in parent['extensions'].items():require(sha(root/relative)==wanted,'parent frozen source changed')
    require(str((root/PARENT_RUNNER).resolve()) in manifest['inputs'],'parent runner must be explicitly bound')
    spec=importlib.util.spec_from_file_location('_selected_parent_continuation',root/PARENT_RUNNER)
    runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    previous=SimpleNamespace(**vars(args));previous.extension_root=root;previous.manifest=Path(manifest['parent_manifest']);previous.plan=Path(manifest['parent_plan'])
    ctx=runner.load_context(previous)
    require(set(manifest['endpoint_summaries'])==set(ENDPOINTS),'exact two selected parents required')
    runs={}
    for width,choice in ENDPOINTS.items():
        run=bound(manifest,manifest['endpoint_summaries'][width]);report=bound(manifest,run['training_ref']['path'],run['training_ref']['sha256'])
        require(run['arm']==choice['arm'] and run['dimension']==int(width) and run['seed']==1729 and run['budget_completed'], 'parent fit identity differs')
        require(run['recipe']==dict(name='continue-lr001',learning_rate=.001),'parent initial learning rate differs')
        require(report['optimizer_steps']==170 and report['stopped_reason']=='epochs_completed','complete R10 parent required')
        ref=run['states']['selected'];bound(manifest,ref['path'],ref['sha256'])
        bound(manifest,run['postfit']['selected']['validation']['path'],run['postfit']['selected']['validation']['sha256'])
        runs[width]=run
    ctx.update(selected_manifest=manifest,selected_plan=plan,selected_runner=runner,selected_parents=runs)
    return ctx


def prepare_lane(ctx,dimension):
    require(dimension in FIXED['dimensions'],'unsupported continuation dimension')
    lane=ctx['selected_runner'].prepare_lane(ctx,dimension)
    # Preparation still uses exactly the authenticated R10→R9 training inputs.
    # Only state/report authentication gains the new outer manifest afterwards.
    lane['continuation_manifest']=ctx['selected_manifest']
    lane['selected_runner']=ctx['selected_runner']
    return lane


def restore_endpoint(lane,run,role):
    require(role in ('selected','last-attempt'),'closed endpoint role required')
    return lane['selected_runner'].restore_model(lane,run['states'][role],run['recipe'],role)


def execute(args):
    started=time.monotonic();ctx=load_context(args);deadline=started+FIXED['max_seconds_entire_run'];save=ctx['helpers'].save
    require(not args.output.exists(),'fresh selected-continuation output required');args.output.mkdir(parents=True)
    inventory=lambda:ctx['comparison_owner'].source_inventory(ctx['comparison_parent_args'],ctx)
    before=inventory();save(args.output/'sealed-recipe.json',dict(plan=ctx['selected_plan'],manifest=ctx['selected_manifest'],**FALSE));runs=[]
    for dimension in FIXED['dimensions']:
        require(time.monotonic()<deadline,'selected continuation deadline expired')
        lane=prepare_lane(ctx,dimension);parent=ctx['selected_parents'][str(dimension)];ref=parent['states']['selected']
        name=f'{dimension}-selected-followup-lr0001-1729';folder=args.output/name
        for label,value in [('preprocessing',lane['preparation']),('source-contexts',lane['source_contexts']),('training-rows',lane['rows'])]:save(args.output/str(dimension)/(label+'.json'),value)
        model=restore_endpoint(lane,parent,'selected');require(lane['core'].tensor_digest(model)==ref['tensor_sha256'],'exact selected tensor parity required')
        initial=lane['clause_runner'].evaluate(lane,model,'validation','conditioned')
        old=bound(ctx['selected_manifest'],parent['postfit']['selected']['validation']['path'],parent['postfit']['selected']['validation']['sha256'])
        require(initial['predictions']==old['predictions'],'selected parent generated predictions differ')
        initial_ref=save(folder/'parent-validation.json',initial)
        parity=dict(parent_tensor_sha256=ref['tensor_sha256'],restored_tensor_sha256=lane['core'].tensor_digest(model),
                    predictions_equal=True,rows=len(initial['predictions']),parent_prediction_ref=parent['postfit']['selected']['validation'],restored_prediction_ref=initial_ref)
        if args.phase=='preflight':runs.append(dict(arm=name,dimension=dimension,initial_parity=parity));del model;continue
        states={'initial':lane['native_runner'].save_state(lane,model,ARM,'initial',False,folder/'initial-state.json')}
        fit_started=time.monotonic();value=lane['selected_runner'].train_candidate(lane,model,deepcopy(ARM));fit_seconds=time.monotonic()-fit_started
        report=value['report'];report_ref=save(folder/'training.json',report)
        lane['selected_runner'].validate_report(lane,report,ARM,ref['tensor_sha256'])
        panels={}
        for role,state,predictions in [('selected',value['state_dict'],value['predictions']),('last-attempt',value['last_complete_attempt_state_dict'],value['last_complete_attempt_predictions'])]:
            require(state is not None,'complete selected continuation endpoint required');lane['native_runner'].validate_wrapper_state(lane,state);model.load_state_dict(state,strict=True)
            expected=report['selected_weights_sha256'] if role=='selected' else report['last_complete_attempt_weights_sha256']
            require(lane['core'].tensor_digest(model)==expected,'saved endpoint tensor differs')
            states[role]=lane['native_runner'].save_state(lane,model,ARM,role,role=='selected' or report['last_complete_attempt_is_selected'],folder/(role+'-state.json'))
            compact=lane['continuation_runner'].evaluate_original_panels(lane,model,predictions,folder/role)
            require(len(compact)==9,'all inherited controls required')
            panels[role]={label:dict(path=str(folder/role/('evaluation-'+label+'.json')),sha256=sha(folder/role/('evaluation-'+label+'.json')),numerical=p['numerical'],fidelity=p['source_fidelity']) for label,p in compact.items()}
        record=dict(arm=name,dimension=dimension,seed=1729,recipe=deepcopy(ARM),parent_endpoint=ENDPOINTS[str(dimension)],parent_state=ref,
            initial_parity=parity,states=states,training_ref=report_ref,postfit=panels,budget_completed=True,fresh_optimizer=True,fresh_scheduler=True,
            exact_optimizer_resume=False,parent_optimizer_state_restored=False,training_call_elapsed_seconds=fit_seconds,
            training_rows_per_second=report['row_presentations']/fit_seconds,**FALSE)
        saved=save(folder/'summary.json',record);runs.append(dict(arm=name,summary_path=saved['path'],summary_sha256=saved['sha256']))
        print(json.dumps(dict(arm=name,steps=report['optimizer_steps'],selected_epoch=report['selected_epoch'],final_exact=report['last_complete_attempt']['fidelity']['metrics']['ordered_exact'],fit_seconds=fit_seconds)),flush=True)
        del model,value,report,compact,initial,old,lane
    after=inventory();require(all(after.get(k)==v for k,v in before.items()),'loaded numerical source changed')
    for path,wanted in ctx['selected_manifest']['inputs'].items():require(sha(path)==wanted,'bound input changed during fit')
    for relative,wanted in ctx['selected_manifest']['extensions'].items():require(sha(args.extension_root/relative)==wanted,'frozen runner changed during fit')
    require(time.monotonic()<deadline,'selected continuation deadline exceeded')
    summary=dict(schema='selected-checkpoint-continuation-comparison/v1',complete=len(runs)==2,phase=args.phase,runs=runs,
        source_dependencies=after,dimensions_actually_trained=FIXED['dimensions'] if args.phase=='training' else [],
        elapsed_seconds=time.monotonic()-started,**FALSE)
    save(args.output/'summary.json',summary);return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('dependency-root','extension-root','manifest','plan','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--phase',choices=['preflight','training'],required=True);execute(parser.parse_args())
if __name__=='__main__':main()
