#!/usr/bin/env python3
"""Fixed-budget order substitution and actual-prefix stopping ablation.

The shared model and all source-fidelity selection gates are unchanged. Optional
training supervision never enters source-only generation or native admission.
"""
import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import time

AUTO='ipfs_datasets_py/logic/formalization/autoencoder/'
PREFIX='ipfs_datasets_py.logic.formalization.autoencoder.'
FALSE=dict(qualified=False,admitted=False,proof_authority=False,source_semantics_verified=False,
    checkpoint_promoted=False,convergence_proven=False,fresh_holdout=False,lake_executed=False,
    formalized=False,roundtrip_ok=False)
CONTROLS=[['validation','validation','conditioned'],['training','train','conditioned'],
    ['zero-condition','validation','zero_condition'],['source-shuffle','validation','source_shuffle'],
    ['cross-length-shuffle','validation','cross_length_shuffle']]
ARMS=[dict(name=name,order_augmentation=order,generated_boundary_weight=weight)
    for name,order,weight in [('baseline',False,0.),('order',True,0.),('boundary',False,.25),('both',True,.25)]]
FIXED=dict(schema='order-boundary-source-training-plan/v1',representation_dimension=384,
    seed_order=[1729,2718],arms=ARMS,head='shared_slot_tanh',hidden_width=64,
    epochs_per_source_stage=20,expected_optimizer_steps_per_arm=340,
    expected_training_token_presentations_per_arm=225840,expected_count_presentations_per_arm=2440,
    expected_source_value_presentations_per_candidate=25600,expected_balanced_count_presentations={'1':610,'2':610,'4':610,'8':610},
    fixed_encoder_context_tokens=512,fixed_decoder_output_limit=512,temperature=0,batch_size=8,
    learning_rate=.001,max_seconds_per_arm=180,validation_interval=4,source_value_weight=.25,
    cardinality_weight=.25,count_exposure='balanced_all',strategy='semantic_fields',
    order_policy='parent_local_unique_original_reverse_rotate_cycle',order_policy_uses_rng=False,
    order_extra_decoder_presentations=0,order_normalization_refitted=False,order_count_stream_changed=False,
    boundary_site_cap_per_row=2,boundary_site_policy='first_and_last_distinct_actual_boundary',
    boundary_refresh_policy='every_current_effective_training_batch_before_update',
    boundary_site_labels='continue_if_completed_less_than_training_count_else_close',
    boundary_loss='full_vocabulary_CE_mean_per_active_row_then_active_rows',
    boundary_extra_computation_reported_separately=True,
    source_only_generation=True,generation_reference_count_access=False,generation_reference_prefix_access=False,
    full_vocabulary_retained=True,syntax_forced=False,closure_forced=False,
    original_training_rows=48,exposed_validation_rows=48,order_unique_training_sources=108,
    no_downloads=True,encoder_executed=False,verified_cached_embeddings=True,
    selection_unchanged=True,baseline_training_replay_required=True,native_qualification=False,
    production_promotion_allowed=False,postfit_controls=CONTROLS,max_seconds_per_postfit=30,
    max_seconds_per_numerical_evaluation=20,max_seconds_entire_run=2400,
    max_memory_bytes=536870912,postfit_order_sources=108,postfit_boundary_splits=['train','validation'])


def require(condition,message):
    if not condition:raise ValueError(message)


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_plan(plan):
    require(type(plan) is dict and all(json.dumps(plan.get(k),sort_keys=True,allow_nan=False)==
        json.dumps(v,sort_keys=True,allow_nan=False) for k,v in FIXED.items()),'fixed training recipe differs')


def load_helper(root,pins,path,name):
    require(sha(root/path)==pins.get(path),'frozen helper differs: '+path)
    spec=importlib.util.spec_from_file_location(name,root/path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def load_context(args):
    manifest=json.loads(args.manifest.read_bytes());pins=manifest['extensions']
    plan=json.loads(args.plan.read_bytes());validate_plan(plan)
    require(plan.get('input_sha256')==manifest['inputs'],'training input bindings differ')
    replay=load_helper(args.extension_root,pins,'scripts/ops/autoencoder/decoder_fidelity_replay.py','_order_training_replay')
    ctx=replay.load_context(args,validate_plan=validate_plan);h=ctx['helpers']
    shared=load_helper(args.extension_root,pins,'scripts/ops/autoencoder/benchmark_shared_slot_source_reconstruction.py','_order_training_shared')
    prior=load_helper(args.extension_root,pins,'scripts/ops/autoencoder/benchmark_mean_centered_source_reconstruction.py','_order_training_prior')
    old=load_helper(args.extension_root,pins,'scripts/ops/autoencoder/benchmark_projected_source_reconstruction.py','_order_training_projected')
    diagnostic=load_helper(args.extension_root,pins,'scripts/ops/autoencoder/benchmark_decoder_order_boundaries.py','_order_training_diagnostic')
    names=['decoder_cardinality_experiment','long_span_cardinality_training','long_span_count_exposure_training',
        'source_value_decoder_experiment','projected_source_decoder_experiment','mean_centered_source_decoder_experiment',
        'shared_slot_source_decoder_experiment','order_source_diagnostic','boundary_source_diagnostic',
        'order_training_augmentation','generated_boundary_training','long_span_source_value_training']
    owners={name:h.extension(args.extension_root,AUTO+name+'.py',PREFIX+name,pins) for name in names}
    exposure=load_helper(args.extension_root,pins,'scripts/ops/autoencoder/benchmark_decoder_count_exposure.py','_order_training_exposure')
    public=json.loads(Path(manifest['shared_public_manifest']).read_bytes())
    result=json.loads(Path(manifest['shared_public_results']).read_bytes())
    require(public['schema']=='decoder-shared-slot-source-archive/v1' and result['schema']=='decoder-shared-slot-source-results/v1'
        and public['archive']==result['archive'],'shared predecessor publication differs')
    read=lambda path,pub:diagnostic.read_published(path,manifest,pub)
    summary=read(manifest['shared_summary'],public)
    require(summary['complete'] is True and summary['raw_training_replay_parity'] is True,'complete prior fits required')
    for key in ('donor','paragraphs','embeddings','curriculum','curriculum_inputs'):read(manifest[key],public)
    preprocessing=read(manifest['parent_preprocessing'],public)
    opub=json.loads(Path(manifest['order_public_manifest']).read_bytes())
    ores=json.loads(Path(manifest['order_public_results']).read_bytes())
    require(opub['schema']=='decoder-order-boundary-archive/v1' and ores['schema']=='decoder-order-boundary-results/v1'
        and opub['archive']==ores['archive'] and ores['training_executed'] is False,'published diagnostic differs')
    preparation=read(manifest['order_preparation'],opub)
    require(preparation==owners['order_source_diagnostic'].build_order_variants(ctx['corpus'],
        json.loads(Path(manifest['curriculum_inputs']).read_bytes()),codec=ctx['donor']['codec']),
        'source permutations differ from original training components')
    encoded=read(manifest['order_embeddings'],opub)
    require(encoded['producer']['asset_manifest']==ctx['embeddings']['producer']['asset_manifest']
        and encoded['producer']['actual_forward_tokens_checked'] is True and encoded['producer']['encoder_context_tokens']==512,
        'verified complete prior encoder observations required')
    ctx.update(manifest=manifest,owners=owners,shared=shared,prior=prior,old=old,diagnostic=diagnostic,exposure=exposure,
        preprocessing=preprocessing,prior_runs={r['arm']:r for r in summary['runs']},
        order_preparation=preparation,order_embeddings=encoded,public=public)
    return ctx


def validate_baseline(report,prior,postfit,core):
    old=prior['training']
    require(set(report)==set(old),'baseline report inventory differs')
    fields=sorted(set(old)-{'elapsed_seconds','config'})
    for field in fields:require(core.digest(report[field])==core.digest(old[field]),'baseline replay differs: '+field)
    require({k:v for k,v in report['config'].items() if k!='max_seconds'}==
        {k:v for k,v in old['config'].items() if k!='max_seconds'}
        and report['config']['max_seconds']==180 and old['config']['max_seconds']==90,'baseline optimizer config differs')
    for role in ('selected','last-attempt'):
        for label,_,_ in CONTROLS:
            require(postfit[role][label]['predictions']==prior['postfit'][role][label]['predictions'],
                'baseline full source-control predictions differ')
    return dict(complete=True,compared_training_fields=fields,all_tensors_and_predictions_equal=True,
        prior_timeout_seconds=90,current_timeout_seconds=180,timing_equality_claimed=False,
        scope='same shared model, optimizer trajectory, selection and five controls; only wall headroom differs')


def train_candidate(ctx,model,seed,recipe):
    augmentation=(dict(preparation=ctx['order_preparation'],embedding_observations=ctx['order_embeddings'])
        if recipe['order_augmentation'] else None)
    return ctx['owners']['long_span_source_value_training'].train(model,ctx['rows']['train'],ctx['rows']['validation'],
        training_references=ctx['references']['train'],validation_references=ctx['references']['validation'],
        codec=ctx['donor']['codec'],input_transform=ctx['donor']['input_transform'],lineage=ctx['lineage'],
        validate_rule=ctx['validate_rule'],validator_id=ctx['validator_id'],curriculum=ctx['stages'],
        strategy='semantic_fields',cardinality_weight=.25,count_exposure='balanced_all',source_value_weight=.25,
        order_augmentation=augmentation,generated_boundary_weight=recipe['generated_boundary_weight'],
        config=dict(seed=seed,max_seconds=180,max_target_tokens=512,batch_size=8,learning_rate=.001,
            max_optimizer_steps=1000,patience=0,validation_interval=4,alpha=0.))


def save_state(ctx,model,recipe,role,selected,path):
    core=ctx['core'];digest=core.tensor_digest(model);state={key:value.tolist() for key,value in model.state_dict().items()}
    receipt=ctx['helpers'].save(path,dict(schema='private-order-boundary-source-state/v1',recipe=recipe,
        architecture=model.describe(),lineage=deepcopy(ctx['lineage']),codec=ctx['donor']['codec'],model_state=state,
        weights_sha256=core.digest(state),tensor_sha256=digest,role=role,selected=selected,optimizer_resumable=False,**FALSE))
    saved=json.loads(Path(receipt['path']).read_bytes())
    require(core.digest(saved['model_state'])==saved['weights_sha256'],'saved state differs')
    model.load_state_dict(ctx['shared'].restored_tensors(ctx,saved['model_state'],model.state_dict()),strict=True)
    require(core.tensor_digest(model)==digest,'persisted typed state differs')
    return dict(receipt,tensor_sha256=digest)


def postfit_mechanisms(ctx,model,folder):
    save=ctx['helpers'].save;order=ctx['owners']['order_source_diagnostic'];diagnostic=ctx['diagnostic']
    preparation=ctx['order_preparation']
    vectors={r['input_id']:r['vector'] for r in ctx['order_embeddings']['observations']['main']}
    sources=[dict(id=r['id'],input=vectors[r['id']]) for r in preparation['rows']]
    observed=diagnostic.greedy_source_panel(ctx,model,sources);save(folder/'order-observations.json',observed)
    paired=dict(projection=order.paired_vector_metrics(preparation,observed['projected_vectors'],space='decoder_projection'),
        scalars=order.paired_scalar_metrics(preparation,observed['scalar_logits'],codec=ctx['donor']['codec']),
        generated=order.paired_prediction_metrics(preparation,{r['id']:r for r in observed['predictions']},codec=ctx['donor']['codec']))
    save(folder/'order-pairs.json',paired)
    for split in ('train','validation'):
        trace=ctx['owners']['boundary_source_diagnostic'].trace_boundary_generation(model,
            [dict(id=r['id'],input=r['input']) for r in ctx['rows'][split]],codec=ctx['donor']['codec'],
            input_transform=ctx['donor']['input_transform'],max_target_tokens=512,batch_size=8,max_seconds=120)
        save(folder/('boundary-'+split+'.json'),trace)
    return dict(order_rows=108,boundary_rows=96,order_wall_seconds_per_span=observed['wall_seconds_per_span'],**FALSE)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('dependency-root','extension-root','manifest','plan','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--phase',choices=['training'],required=True)
    args=parser.parse_args();started=time.monotonic();ctx=load_context(args);h=ctx['helpers'];core=ctx['core'];save=h.save
    before=h.inventory(args.dependency_root,args.extension_root,ctx['pins']);args.output.mkdir(parents=True)
    save(args.output/'sealed-recipe.json',dict(plan=ctx['plan'],manifest=ctx['manifest'],tree_pin=ctx['tree'],**FALSE))
    save(args.output/'preprocessing-replay.json',ctx['prior'].validate_preprocessing(ctx))
    selector=ctx['owners']['order_training_augmentation'].prepare(ctx['rows']['train'],ctx['rows']['validation'],
        training_references=ctx['references']['train'],preparation=ctx['order_preparation'],
        embedding_observations=ctx['order_embeddings'],codec=ctx['donor']['codec'])
    save(args.output/'augmentation-preflight.json',selector.snapshot())
    runs=[];head_recipe=ctx['shared'].ARMS[1]
    for seed in FIXED['seed_order']:
        for recipe in ARMS:
            require(time.monotonic()-started<2400,'training comparison deadline exceeded')
            arm_started=time.monotonic()
            name=recipe['name']+'-'+str(seed);folder=args.output/name
            model=ctx['shared'].bind_candidate(ctx,head_recipe,seed)
            expected=ctx['prior_runs']['shared-'+str(seed)]
            ctx['lineage']=deepcopy(expected['training']['lineage'])
            if recipe['name']!='baseline':ctx['lineage']['student_lineage']='order_boundary_source_v1:'+name
            initial=save_state(ctx,model,recipe,'initial',False,folder/'initial-state.json')
            require(initial['tensor_sha256']==expected['training']['initial_weights_sha256'],'original shared initialization differs')
            fit_started=time.monotonic();value=train_candidate(ctx,model,seed,recipe);fit_seconds=time.monotonic()-fit_started
            report=value['report'];save(folder/'training.json',report)
            require(report['stopped_reason']=='epochs_completed' and report['optimizer_steps']==340
                and report['valid_target_token_presentations']==225840 and report['source_value_presentations']==25600
                and report['count_training_row_presentations']==2440
                and report['count_training_presentations_by_class']==FIXED['expected_balanced_count_presentations'],
                'incomplete or changed training exposure')
            postfit={};states={};post_started=time.monotonic()
            for role,state,predictions in [('selected',value['state_dict'],value['predictions']),
                ('last-attempt',value['last_complete_attempt_state_dict'],value['last_complete_attempt_predictions'])]:
                require(state is not None,'complete selected/final state required');model.load_state_dict(state,strict=True)
                expected_digest=report['selected_weights_sha256'] if role=='selected' else report['last_complete_attempt_weights_sha256']
                require(core.tensor_digest(model)==expected_digest,'trained state differs')
                states[role]=save_state(ctx,model,recipe,role,role=='selected' or report['last_complete_attempt_is_selected'],folder/(role+'-state.json'))
                postfit[role]={}
                for label,split,control in CONTROLS:
                    panel=ctx['shared'].evaluate(ctx,model,split,control)
                    if label=='validation':require(panel['predictions']==predictions,'persisted generation differs')
                    save(folder/role/('evaluation-'+label+'.json'),panel)
                    postfit[role][label]=ctx['prior'].compact_panel(panel,retain_predictions=True)
            parity=validate_baseline(report,expected,postfit,core) if recipe['name']=='baseline' else None
            mechanisms=postfit_mechanisms(ctx,model,folder/'last-attempt')
            require(core.tensor_digest(model)==report['last_complete_attempt_weights_sha256'],'postfit diagnostics changed state')
            record=dict(arm=name,seed=seed,recipe=recipe,training=report,initial_state=initial,states=states,
                postfit=postfit,baseline_replay=parity,mechanisms=mechanisms,budget_completed=True,
                training_call_elapsed_seconds=fit_seconds,postfit_elapsed_seconds=time.monotonic()-post_started,
                elapsed_seconds=time.monotonic()-arm_started,
                trainable_parameter_count=sum(p.numel() for p in model.parameters() if p.requires_grad),**FALSE)
            save(folder/'summary.json',record);runs.append(record)
            print(json.dumps(dict(arm=name,steps=report['optimizer_steps'],selected_epoch=report['selected_epoch'],
                last_exact=report['last_complete_attempt']['fidelity']['metrics']['ordered_exact'],fit_seconds=fit_seconds)),flush=True)
    after=h.inventory(args.dependency_root,args.extension_root,ctx['pins']);require(all(after.get(k)==v for k,v in before.items()),'loaded producer changed')
    h.validate_manifest_inputs(ctx['manifest'])
    for relative,digest in ctx['pins'].items():require(sha(args.extension_root/relative)==digest,'frozen extension changed')
    require(sha(args.plan)==ctx['manifest']['plan_sha256'],'training plan changed')
    require(time.monotonic()-started<2400,'training comparison deadline exceeded')
    save(args.output/'summary.json',dict(schema='order-boundary-source-training-comparison/v1',complete=len(runs)==8,runs=runs,
        training_executed=True,dimensions_actually_trained=[384],baseline_replay_parity=all(r['baseline_replay']['complete'] for r in runs if r['recipe']['name']=='baseline'),
        source_dependencies=after,elapsed_seconds=time.monotonic()-started,workers=1,bridge_names=[],legal_ir_evaluate_provers=False,
        metric_disk_cache_used=False,encoder_executed=False,verified_cached_embeddings=True,downloads_performed=False,**FALSE))


if __name__=='__main__':main()
