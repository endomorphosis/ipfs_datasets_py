#!/usr/bin/env python3
"""Fixed same-geometry formula-sidecar continuation with fresh AdamW/scheduler.

This is not exact optimizer resume. R6 is previously exposed postfit regression,
and all predictions are durable before its reference documents are opened.
"""
import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import time
import traceback
from types import SimpleNamespace

PARENT_RUNNER='scripts/ops/autoencoder/benchmark_multidimension_modality_training.py'
FALSE=dict(qualified=False,admitted=False,proof_authority=False,source_semantics_verified=False,
    checkpoint_promoted=False,convergence_proven=False,fresh_holdout=False,fresh_authored_holdout=False,
    lake_executed=False,native_validation_executed=False,formalized=False,roundtrip_ok=False)
ENDPOINTS={'8':dict(arm='8-source-head-lr10-1729',role='last-attempt'),
    '384':dict(arm='384-aux-used113-1729',role='selected'),
    '768':dict(arm='768-source-head-lr10-1729',role='last-attempt')}
ARMS=[dict(name='continue-lr0001',learning_rate=.0001),dict(name='continue-lr001',learning_rate=.001)]
ROLES=['selected','last-attempt']
FIXED=dict(schema='formula-checkpoint-continuation-plan/v1',dimensions=[8,384,768],seed_order=[1729],
    endpoints=ENDPOINTS,arms=ARMS,fit_count=6,epochs_per_stage=10,optimizer_steps_per_fit=170,
    row_presentations=1220,count_presentations=1220,valid_target_token_presentations=112920,
    source_value_presentations=12800,balanced_counts={'1':305,'2':305,'4':305,'8':305},
    fresh_optimizer=True,fresh_scheduler=True,exact_optimizer_resume=False,
    architecture_changed=False,preprocessing_refitted=False,selection_unchanged=True,
    losses_inherited_by_width={'8':'baseline','384':'aux-used113_weight.05','768':'baseline'},
    non_action_learning_rate_multiplier=10.,cardinality_weight=.25,source_value_weight=.25,
    action_contrastive_weight=.05,generated_boundary_weight=.05,generated_boundary_site_policy='first_last',
    strict_boundary_retry_all_continuations=True,boundary_replay_atol=2e-5,boundary_replay_rtol=2e-5,
    auxiliary_sampler='independent',auxiliary_presentations384=1020,
    fixed_encoder_context_tokens=512,fixed_decoder_output_limit=512,temperature=0,batch_size=8,
    full_vocabulary_size=32,historical_linguistic_teacher_modified=False,
    max_seconds_per_fit=180,max_seconds_per_postfit=30,max_seconds_entire_run=1800,
    memory_bytes_per_fit=1073741824,workers=1,encoder_executed=False,downloads_performed=False,
    bridge_names=[],legal_ir_evaluate_provers=False,metric_disk_cache_used=False,
    exposed_r6_panel_count=12,exposed_r6_used_for_selection=False,all_exposed_predictions_before_reference_load=True)


def require(value,message):
    if not value:raise ValueError(message)


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1048576),b''):h.update(block)
    return h.hexdigest()


def bound_json(manifest,path,expected=None):
    path=Path(path).resolve();wanted=manifest['inputs'].get(str(path));require(wanted is not None and
        (expected is None or expected==wanted),'unbound artifact: '+str(path))
    raw=path.read_bytes();require(hashlib.sha256(raw).hexdigest()==wanted,'sealed artifact differs: '+str(path));return json.loads(raw)


def validate_plan(plan):
    require(type(plan) is dict and all(type(plan.get(k)) is type(v) and
        json.dumps(plan[k],sort_keys=True,allow_nan=False)==json.dumps(v,sort_keys=True,allow_nan=False)
        for k,v in FIXED.items()),'fixed continuation recipe differs')


def jobs():return [(d,deepcopy(a)) for d in FIXED['dimensions'] for a in ARMS]


def load_context(args):
    manifest=json.loads(args.manifest.read_bytes());plan=json.loads(args.plan.read_bytes());validate_plan(plan)
    require(sha(args.plan)==manifest['plan_sha256'] and plan['input_sha256']==manifest['inputs'],'continuation seal differs')
    for path,wanted in manifest['inputs'].items():require(sha(path)==wanted,'sealed input changed')
    for relative,wanted in manifest['extensions'].items():require(sha(args.extension_root/relative)==wanted,'frozen runner changed')
    parent=bound_json(manifest,manifest['parent_manifest']);bound_json(manifest,manifest['parent_plan'])
    root=Path(manifest['parent_extension_root']);require(sha(manifest['parent_plan'])==parent['plan_sha256'],'parent plan differs')
    for relative,wanted in parent['extensions'].items():require(sha(root/relative)==wanted,'parent runner changed')
    spec=importlib.util.spec_from_file_location('_continuation_parent_runner',root/PARENT_RUNNER)
    runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    previous=SimpleNamespace(**vars(args));previous.extension_root=root
    previous.manifest=Path(manifest['parent_manifest']);previous.plan=Path(manifest['parent_plan'])
    ctx=runner.load_context(previous)
    require(set(manifest['endpoint_summaries'])==set(ENDPOINTS),'all three explicit parent endpoints required')
    runs={}
    for d,choice in ENDPOINTS.items():
        run=bound_json(manifest,manifest['endpoint_summaries'][d])
        require(run['arm']==choice['arm'] and run['dimension']==int(d) and run['seed']==1729
            and run['budget_completed'] is True,'parent endpoint identity differs')
        report=bound_json(manifest,run['training_ref']['path'],run['training_ref']['sha256'])
        require(report['optimizer_steps']==340 and report['stopped_reason']=='epochs_completed','complete parent fit required')
        expected=runner.ARMS[1] if d=='384' else runner.ARMS[0]
        require(run['recipe']==expected,'parent loss recipe differs')
        ref=run['states'][choice['role']];bound_json(manifest,ref['path'],ref['sha256']);runs[d]=run
    ctx.update(continuation_manifest=manifest,continuation_plan=plan,continuation_runner=runner,parent_runs=runs)
    return ctx


def prepare_lane(ctx,dimension):
    lane=ctx['native_runner'].prepare_dimension(ctx,dimension);manifest=ctx['continuation_manifest']
    folder=Path(manifest['parent_results'])/str(dimension)
    for name,value in [('preprocessing',lane['preparation']),('source-contexts',lane['source_contexts']),('training-rows',lane['rows'])]:
        require(bound_json(manifest,folder/(name+'.json'))==value,'parent preprocessing or source cohort differs')
    lane['stages']=[dict(stage,epochs=10) for stage in lane['stages']]
    require(sum(((len(s['training_ids'])+7)//8)*s['epochs'] for s in lane['stages'])==170,'continuation curriculum budget differs')
    if dimension==384:
        bank=bound_json(manifest,folder/'auxiliary-bank.json')
        lane['owners']['source_modality_auxiliary_training'].validate_training_binding(bank,lane['rows']['train'],lane['rows']['validation'],
            source_contexts=lane['source_contexts'],codec=lane['donor']['codec'],deadline=time.monotonic()+30)
        lane['modality_banks']={'used113':bank}
    return lane


def restore_model(lane,ref,recipe,role):
    state=bound_json(lane['continuation_manifest'],ref['path'],ref['sha256'])
    require(state.get('schema')=='private-native-dimension-source-state/v1' and state.get('dimension')==lane['dimension']
        and state.get('role')==role and state.get('recipe')==recipe and state.get('codec')==lane['donor']['codec']
        and state.get('input_transform')==lane['donor']['input_transform']
        and state.get('weights_sha256')==lane['core'].digest(state['model_state']) and state.get('tensor_sha256')==ref['tensor_sha256']
        and state.get('optimizer_resumable') is False and all(state.get(k) is False for k in ('qualified','admitted','proof_authority','checkpoint_promoted')),
        'parent state/geometry/authority differs')
    model=lane['continuation_runner'].bind_candidate(lane,lane['continuation_runner'].ARMS[0],1729)
    require(model.describe()==state['architecture'],'saved architecture differs')
    values=lane['clause_runner'].restored_tensors(lane,state['model_state'],model.state_dict())
    lane['native_runner'].validate_wrapper_state(lane,values);model.load_state_dict(values,strict=True)
    require(lane['core'].tensor_digest(model)==ref['tensor_sha256'],'restored parent tensor digest differs')
    return model


def train_candidate(lane,model,arm):
    require(arm in ARMS,'unregistered continuation LR')
    auxiliary={} if lane['dimension']!=384 else dict(auxiliary_source_modality_bank=lane['modality_banks']['used113'],auxiliary_source_modality_weight=.05)
    return lane['owners']['long_span_source_value_training'].train(model,lane['rows']['train'],lane['rows']['validation'],
        training_references=lane['references']['train'],validation_references=lane['references']['validation'],
        codec=lane['donor']['codec'],input_transform=lane['donor']['input_transform'],lineage=lane['lineage'],
        validate_rule=lane['validate_rule'],validator_id=lane['validator_id'],curriculum=lane['stages'],
        strategy='semantic_fields',cardinality_weight=.25,count_exposure='balanced_all',source_value_weight=.25,
        source_contexts=lane['source_contexts'],action_contrastive_weight=.05,generated_boundary_weight=.05,
        generated_boundary_site_policy='first_last',generated_boundary_retry_on_mismatch=True,
        generated_source_margin_weight=0.,generated_source_margin_replay=False,non_action_learning_rate_multiplier=10.,
        config=dict(seed=1729,max_seconds=180,max_target_tokens=512,batch_size=8,learning_rate=arm['learning_rate'],
            max_optimizer_steps=1000,patience=0,validation_interval=4,alpha=0.,max_memory_bytes=1073741824),**auxiliary)


def validate_report(lane,report,arm,parent_sha):
    require(report['stopped_reason']=='epochs_completed' and report['optimizer_steps']==170
        and report['row_presentations']==1220 and report['valid_target_token_presentations']==112920
        and report['count_training_row_presentations']==1220 and report['source_value_presentations']==12800
        and report['count_training_presentations_by_class']==FIXED['balanced_counts'],'continuation work incomplete or unequal')
    require(report['initial_weights_sha256']==parent_sha and report['optimizer_resumable'] is False
        and report['optimizer_instance_count']==1 and report['optimizer_reinitialized_between_stages'] is False
        and report['config']['learning_rate']==arm['learning_rate'] and report['non_action_learning_rate_multiplier']==10.,'parent/fresh optimizer configuration differs')
    require(all(report[k] is False for k in ('qualified','admitted','proof_authority','convergence_proven','lake_executed')),
        'training acquired qualification authority')
    require(report.get('generated_boundary_retry_on_mismatch') is True and report.get('generated_boundary_retry_tolerance_changed') is False,
        'strict replay policy differs')
    for update in report['committed_updates']:lane['parent_runner'].validate_boundary_retry_receipt(update['generated_boundary'])
    if lane['dimension']==384:
        require(report['auxiliary_source_modality_weight']==.05 and report['auxiliary_source_modality_presentations']==1020
            and report['auxiliary_source_modality_committed_updates']==170 and report['auxiliary_source_modality_used_for_selection'] is False,
            'inherited auxiliary work differs')
    else:require(not any(k.startswith('auxiliary_source_modality_') for k in report),'baseline gained an auxiliary loss')


def execute(args):
    started=time.monotonic();deadline=started+1800;ctx=load_context(args);save=ctx['helpers'].save
    inventory=lambda:ctx['comparison_owner'].source_inventory(ctx['comparison_parent_args'],ctx)
    before=inventory();args.output.mkdir(parents=True);save(args.output/'sealed-recipe.json',dict(plan=ctx['continuation_plan'],manifest=ctx['continuation_manifest'],**FALSE))
    runs=[];lanes={}
    for dimension in FIXED['dimensions']:
        lane=prepare_lane(ctx,dimension);lanes[dimension]=lane;parent=ctx['parent_runs'][str(dimension)];choice=ENDPOINTS[str(dimension)]
        parent_ref=parent['states'][choice['role']]
        for name,value in [('preprocessing',lane['preparation']),('source-contexts',lane['source_contexts']),('training-rows',lane['rows'])]:save(args.output/str(dimension)/(name+'.json'),value)
        for arm in ARMS:
            require(time.monotonic()<deadline,'continuation deadline exceeded');name=f'{dimension}-{arm["name"]}-1729';folder=args.output/name
            model=restore_model(lane,parent_ref,parent['recipe'],choice['role'])
            initial=lane['clause_runner'].evaluate(lane,model,'validation','conditioned')
            old=bound_json(ctx['continuation_manifest'],parent['postfit'][choice['role']]['validation']['path'],parent['postfit'][choice['role']]['validation']['sha256'])
            require(initial['predictions']==old['predictions'],'parent generated predictions differ')
            save(folder/'parent-validation.json',initial)
            if args.phase=='preflight':
                runs.append(dict(arm=name,dimension=dimension,parent_tensor_sha256=parent_ref['tensor_sha256'],initial_predictions_equal=True));del model;continue
            states={'initial':lane['native_runner'].save_state(lane,model,arm,'initial',False,folder/'initial-state.json')}
            fit_start=time.monotonic()
            try:value=train_candidate(lane,model,arm)
            except Exception as error:
                save(folder/'failure.json',dict(exception_type=type(error).__name__,message_omitted=True,
                    traceback_frames=[dict(file=f.filename,line=f.lineno,function=f.name) for f in traceback.extract_tb(error.__traceback__)],
                    caller_tensor_unchanged=lane['core'].tensor_digest(model)==parent_ref['tensor_sha256'],completed_updates=None,**FALSE));raise
            fit_seconds=time.monotonic()-fit_start;report=value['report'];report_ref=save(folder/'training.json',report)
            validate_report(lane,report,arm,parent_ref['tensor_sha256']);panels={}
            for role,state,predictions in [('selected',value['state_dict'],value['predictions']),('last-attempt',value['last_complete_attempt_state_dict'],value['last_complete_attempt_predictions'])]:
                require(state is not None,'durable complete endpoint required');lane['native_runner'].validate_wrapper_state(lane,state);model.load_state_dict(state,strict=True)
                expected=report['selected_weights_sha256'] if role=='selected' else report['last_complete_attempt_weights_sha256']
                require(lane['core'].tensor_digest(model)==expected,'training endpoint hash differs')
                states[role]=lane['native_runner'].save_state(lane,model,arm,role,role=='selected' or report['last_complete_attempt_is_selected'],folder/(role+'-state.json'))
                compact=lane['continuation_runner'].evaluate_original_panels(lane,model,predictions,folder/role)
                panels[role]={label:dict(path=str(folder/role/('evaluation-'+label+'.json')),sha256=sha(folder/role/('evaluation-'+label+'.json')),
                    numerical=panel['numerical'],fidelity=panel['source_fidelity']) for label,panel in compact.items()}
            record=dict(arm=name,dimension=dimension,seed=1729,recipe=arm,parent_endpoint=choice,parent_state=parent_ref,states=states,
                training_ref=report_ref,postfit=panels,budget_completed=True,fresh_optimizer=True,fresh_scheduler=True,exact_optimizer_resume=False,
                parent_optimizer_state_restored=False,training_call_elapsed_seconds=fit_seconds,**FALSE)
            ref=save(folder/'summary.json',record);runs.append(dict(arm=name,summary_path=ref['path'],summary_sha256=ref['sha256']))
            print(json.dumps(dict(arm=name,steps=report['optimizer_steps'],selected_epoch=report['selected_epoch'],
                final_exact=report['last_complete_attempt']['fidelity']['metrics']['ordered_exact'],fit_seconds=fit_seconds)),flush=True)
            del model,value,report,compact
    after=inventory();require(all(after.get(k)==v for k,v in before.items()),'source changed during continuation')
    for path,wanted in ctx['continuation_manifest']['inputs'].items():require(sha(path)==wanted,'sealed input changed')
    for relative,wanted in ctx['continuation_manifest']['extensions'].items():require(sha(args.extension_root/relative)==wanted,'frozen runner changed')
    require(time.monotonic()<deadline,'continuation deadline exceeded')
    summary=dict(schema='formula-checkpoint-continuation-comparison/v1',complete=len(runs)==6,phase=args.phase,runs=runs,
        source_dependencies=after,dimensions_actually_trained=[8,384,768] if args.phase=='training' else [],
        fresh_optimizer=True,fresh_scheduler=True,exact_optimizer_resume=False,elapsed_seconds=time.monotonic()-started,**FALSE)
    save(args.output/'summary.json',summary);return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('dependency-root','extension-root','manifest','plan','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--phase',choices=['preflight','training'],required=True);execute(parser.parse_args())


if __name__=='__main__':main()
