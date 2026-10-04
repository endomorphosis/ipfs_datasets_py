#!/usr/bin/env python3
"""Matched independent-affine versus shared-slot Legal source reconstruction.

This private experiment preserves the original source-only generation, complete
output support, exposure, and qualification gates. Parameter sharing is an
inductive-bias test, not evidence that pooled embeddings recover clause order.
"""
import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import time

AUTO='ipfs_datasets_py/logic/formalization/autoencoder/'
PREFIX='ipfs_datasets_py.logic.formalization.autoencoder.'
FALSE=dict(qualified=False,admitted=False,proof_authority=False,source_semantics_verified=False,
    checkpoint_promoted=False,convergence_proven=False,fresh_holdout=False,lake_executed=False,
    formalized=False,roundtrip_ok=False)
CONTROLS=[['validation','validation','conditioned'],['training','train','conditioned'],
    ['zero-condition','validation','zero_condition'],['source-shuffle','validation','source_shuffle'],
    ['cross-length-shuffle','validation','cross_length_shuffle']]
ARMS=[dict(name=name,head_kind=kind,hidden_width=width,scalar_mode='raw',normalization='center_rms',
    guide_boundary=True,source_value_weight=.25,count_exposure='balanced_all',cardinality_weight=.25)
    for name,kind,width in [('independent','independent_affine',None),('shared','shared_slot_tanh',64)]]
FIXED=dict(schema='shared-slot-source-reconstruction-plan/v1',representation_dimension=384,arms=ARMS,
    seed_order=[1729,2718],head_initialization_seed_policy='same_as_fit_seed',
    conditioning='every_step',loss='semantic_fields',epochs_per_source_stage=20,
    expected_optimizer_steps_per_arm=340,expected_training_token_presentations_per_arm=225840,
    expected_count_presentations_per_arm=2440,expected_source_value_presentations_per_candidate=25600,
    expected_balanced_count_presentations={'1':610,'2':610,'4':610,'8':610},
    fixed_encoder_context_tokens=512,fixed_decoder_output_limit=512,batch_size=8,
    learning_rate=.001,max_seconds_per_arm=90,validation_interval=4,temperature=0,
    source_value_max_rules=8,source_value_fields=['actor','action','modality','object'],
    source_value_full_vocabulary=True,source_value_guidance=True,projection_frozen=True,
    inherited_decoder_and_count_trainable=True,normalization_fit_split='train',
    normalization_scale='global_rms_row_l2',count_prior_classes=list(range(1,33)),
    count_prior_total_concentration=1.,count_prior_alpha_per_class=1./32,
    scalar_auxiliary_readout='raw_head_logits',scalar_generation_guidance='raw_head_logits',
    shared_slot_formula='field_readout(tanh(source_projection(x)+slot_embeddings))',
    shared_slot_hidden_width=64,shared_readout_zero_initialized=True,
    generation_reference_count_access=False,generation_reference_prefix_access=False,
    source_segment_offsets_used=False,source_component_metadata_used_for_generation=False,
    initial_greedy_invariance_required=True,raw_training_replay_parity_required=True,
    no_downloads=True,teacher_distillation_used=False,selection_unchanged=True,
    native_qualification=False,production_promotion_allowed=False,
    postfit_controls=CONTROLS,max_seconds_per_postfit=30,max_seconds_per_numerical_evaluation=20,
    max_seconds_per_preprocessing=30,input_bindings_required=True,
    cached_source_order_recoverability_claimed=False)


def require(condition,message):
    if not condition:raise ValueError(message)


def validate_plan(plan):
    require(type(plan) is dict and all(json.dumps(plan.get(k),sort_keys=True,allow_nan=False)==
        json.dumps(v,sort_keys=True,allow_nan=False) for k,v in FIXED.items()),
        'fixed shared-slot reconstruction recipe differs')


def load_helper(root,pins,relative,name):
    path=root/relative
    require(hashlib.sha256(path.read_bytes()).hexdigest()==pins.get(relative),'frozen helper differs: '+relative)
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def validate_input_bindings(plan,manifest):
    bindings=plan.get('input_sha256')
    require(type(bindings) is dict and bindings and bindings==manifest.get('inputs')
        and all(type(path) is str and type(digest) is str and len(digest)==64
            and all(c in '0123456789abcdef' for c in digest) for path,digest in bindings.items()),
        'predeclared exact input hash inventory differs')


def selected_evaluation_paths(parent_summary,seeds=(1729,2718)):
    return {'center_rms-boundary-'+str(seed):str(Path(parent_summary).parent/
        ('center_rms-boundary-'+str(seed))/'selected'/'evaluation-validation.json') for seed in seeds}


def authenticate_raw_controls(ctx):
    manifest=ctx['manifest'];paths=selected_evaluation_paths(manifest['parent_summary'])
    require(manifest.get('prior_selected_evaluations')==paths,'exact two prior selected evaluation bindings required')
    controls={}
    for arm,path in paths.items():
        catalog=next(c for c in manifest['state_catalog'] if c['name']==arm)
        controls[arm]={role:ctx['archives'].read_bound(p,manifest,ctx['public']) for role,p in (
            ('selected',path),('last-attempt',catalog['archived_evaluations']['validation']))}
    return controls


def load_context(args):
    manifest=json.loads(args.manifest.read_bytes());pins=manifest['extensions']
    validate_input_bindings(json.loads(args.plan.read_bytes()),manifest)
    replay=load_helper(args.extension_root,pins,'scripts/ops/autoencoder/decoder_fidelity_replay.py','_shared_slot_replay')
    ctx=replay.load_context(args,validate_plan=validate_plan);helpers=ctx['helpers']
    prior=load_helper(args.extension_root,pins,'scripts/ops/autoencoder/benchmark_mean_centered_source_reconstruction.py','_shared_slot_prior')
    old=load_helper(args.extension_root,pins,'scripts/ops/autoencoder/benchmark_projected_source_reconstruction.py','_shared_slot_projected')
    archives=load_helper(args.extension_root,pins,'scripts/ops/autoencoder/benchmark_decoder_prefix_diagnostics.py','_shared_slot_archives')
    public,runs,preprocessing=prior.authenticate_predecessor(manifest,archives)
    names=['decoder_cardinality_experiment','long_span_cardinality_training','long_span_count_exposure_training',
        'source_value_decoder_experiment','projected_source_decoder_experiment','mean_centered_source_decoder_experiment',
        'shared_slot_source_decoder_experiment','long_span_source_value_training']
    owners={name:helpers.extension(args.extension_root,AUTO+name+'.py',PREFIX+name,pins) for name in names}
    exposure=load_helper(args.extension_root,pins,'scripts/ops/autoencoder/benchmark_decoder_count_exposure.py','_shared_slot_exposure')
    ctx.update(manifest=manifest,old=old,prior=prior,archives=archives,public=public,prior_runs=runs,
        preprocessing=preprocessing,owners=owners,exposure=exposure)
    ctx['raw_controls']=authenticate_raw_controls(ctx)
    return ctx


def bind_candidate(ctx,recipe,seed):
    require(recipe in ARMS and seed in FIXED['seed_order'],'unplanned shared-slot candidate')
    base=ctx['prior'].fresh_base(ctx,'center_rms',True)
    if recipe['head_kind']=='independent_affine':return ctx['prior'].wrap(ctx,base,'raw')
    return ctx['owners']['shared_slot_source_decoder_experiment'].bind_shared_slot_source_model(
        base,head_seed=seed,hidden_width=64)


def evaluate(ctx,model,split,control):
    # Reuse the unchanged full numerical/fidelity/head scorer. Only zero-source
    # construction dispatches by the explicitly described architecture.
    adapted=dict(ctx);adapted['owners']=dict(ctx['owners'])
    if model.describe().get('schema')=='shared-slot-source-decoder-development/v1':
        adapted['owners']['mean_centered_source_decoder_experiment']=SimpleNamespace(
            bind_zero_condition_model=ctx['owners']['shared_slot_source_decoder_experiment'].bind_zero_condition_model)
    return ctx['prior'].evaluate(adapted,model,split,control)


def train_candidate(ctx,model,seed):
    return ctx['owners']['long_span_source_value_training'].train(model,ctx['rows']['train'],ctx['rows']['validation'],
        training_references=ctx['references']['train'],validation_references=ctx['references']['validation'],
        codec=ctx['donor']['codec'],input_transform=ctx['donor']['input_transform'],lineage=ctx['lineage'],
        validate_rule=ctx['validate_rule'],validator_id=ctx['validator_id'],curriculum=ctx['stages'],
        strategy='semantic_fields',cardinality_weight=.25,count_exposure='balanced_all',source_value_weight=.25,
        config=dict(seed=seed,max_seconds=90,max_target_tokens=512,batch_size=8,learning_rate=.001,
            max_optimizer_steps=1000,patience=0,validation_interval=4,alpha=0.))


def restored_tensors(ctx,state,template):
    """Preserve float32 parameters and the one authenticated integer seed buffer."""
    import torch
    require(type(state) is dict and set(state)==set(template),'persisted state inventory differs')
    restored={}
    for name,value in template.items():
        if value.dtype==torch.float32:
            restored[name]=ctx['numerical']._tensor(state[name],value,name)
        else:
            require(name=='head_initialization_seed' and value.dtype==torch.long
                and value.device.type=='cpu' and tuple(value.shape)==()
                and type(state[name]) is int and state[name]==int(value),
                'persisted integer initialization seed differs')
            restored[name]=torch.tensor(state[name],dtype=torch.long)
    return restored


def capture_initial_state(ctx,model,recipe,folder):
    """Persist the actual prefit parameters without restoring or modifying them."""
    core=ctx['core'];before=core.tensor_digest(model)
    state={name:value.tolist() for name,value in model.state_dict().items()}
    artifact=ctx['helpers'].save(folder/'initial-state.json',dict(schema='private-shared-slot-source-state/v1',
        recipe=recipe,architecture=model.describe(),lineage=deepcopy(ctx['lineage']),codec=ctx['donor']['codec'],
        model_state=state,weights_sha256=core.digest(state),tensor_sha256=before,
        underlying_body_tensor_sha256=core.tensor_digest(model.body),role='initial',selected=False,
        optimizer_resumable=False,**FALSE))
    require(core.tensor_digest(model)==before,'initial state capture changed model')
    return {**artifact,'tensor_sha256':before}


def training_phase(args,ctx):
    import torch
    save=ctx['helpers'].save;core=ctx['core'];plan=ctx['plan'];exposure=ctx['exposure'];prior=ctx['prior']
    previous=exposure.load_control_helper(args.extension_root,ctx['pins'])
    budget=exposure.derive_count_budget(ctx['stages'],ctx['rows']['train'],ctx['references']['train'],plan,previous)
    counts={r['id']:r['clause_count'] for r in ctx['references']['train']}
    source_budget=sum(stage['epochs']*sum(4*counts[i] for i in stage['training_ids']) for stage in ctx['stages'])
    require(source_budget==plan['expected_source_value_presentations_per_candidate'],'scalar exposure differs')
    baseline=ctx['adapter'].bind_persistent_model(ctx['base_model'].body,dimension=384,conditioning='every_step')
    initial=ctx['old'].greedy_inventory(torch,core,baseline,ctx['rows'],ctx['donor'],max_seconds=30)
    save(args.output/'original-initial-generation.json',initial);summaries=[]
    for seed in plan['seed_order']:
        for recipe in plan['arms']:
            started=time.monotonic();name=recipe['name']+'-'+str(seed);folder=args.output/name
            model=bind_candidate(ctx,recipe,seed)
            ctx['lineage']['student_lineage']='shared_slot_source_v1:'+name
            initial_state=capture_initial_state(ctx,model,recipe,folder)
            initial_replay=ctx['old'].greedy_inventory(torch,core,model,ctx['rows'],ctx['donor'],max_seconds=30)
            require(initial_replay['predictions']==initial['predictions'],'initial shared-slot architecture changed greedy output')
            initial_replay['initial_state']=initial_state
            initial_replay['identical_to_original_greedy']=True;save(folder/'initial-generation.json',initial_replay)
            before=time.monotonic();result=train_candidate(ctx,model,seed)
            fit_seconds=time.monotonic()-before;report=result['report']
            save(folder/'training.json',report);save(folder/'selected-predictions.json',result['predictions'])
            save(folder/'last-attempt-predictions.json',result['last_complete_attempt_predictions'])
            postfit={};body_digests={};post_started=time.monotonic()
            for role,state,predictions in [('selected',result['state_dict'],result['predictions']),
                ('last-attempt',result['last_complete_attempt_state_dict'],result['last_complete_attempt_predictions'])]:
                require(state is not None,'complete selected and final states required')
                model.load_state_dict(state,strict=True)
                expected=report['selected_weights_sha256'] if role=='selected' else report['last_complete_attempt_weights_sha256']
                require(core.tensor_digest(model)==expected,'state role tensor digest differs')
                state_values={key:value.tolist() for key,value in model.state_dict().items()}
                receipt=save(folder/(role+'-state.json'),dict(schema='private-shared-slot-source-state/v1',
                    recipe=recipe,architecture=model.describe(),lineage=deepcopy(ctx['lineage']),codec=ctx['donor']['codec'],
                    model_state=state_values,weights_sha256=core.digest(state_values),tensor_sha256=expected,role=role,
                    selected=role=='selected' or report['last_complete_attempt_is_selected'],optimizer_resumable=False,**FALSE))
                persisted=json.loads(Path(receipt['path']).read_bytes())
                require(core.digest(persisted['model_state'])==persisted['weights_sha256'],'persisted state JSON differs')
                model.load_state_dict(restored_tensors(ctx,persisted['model_state'],model.state_dict()),strict=True)
                require(core.tensor_digest(model)==expected,'persisted tensor reload differs')
                body_digests[role]=core.tensor_digest(model.body);postfit[role]={}
                for label,split,control in plan['postfit_controls']:
                    value=evaluate(ctx,model,split,control)
                    if label=='validation':require(value['predictions']==predictions,'persisted state generation differs')
                    save(folder/role/('evaluation-'+label+'.json'),value)
                    postfit[role][label]=prior.compact_panel(value,retain_predictions=True)
            replay=None
            if recipe['head_kind']=='independent_affine':
                arm='center_rms-boundary-'+str(seed);controls=ctx['raw_controls'][arm]
                replay=prior.validate_training_parity(report,ctx['prior_runs'][arm],body_digests,postfit,core,
                    archived_selected=controls['selected'])
                require(postfit['last-attempt']['validation']['predictions']==controls['last-attempt']['predictions'],
                    'raw trained final generation differs from original fit')
                save(folder/'raw-training-replay.json',replay)
            completed=(report['optimizer_steps']==budget['optimizer_steps']
                and report['valid_target_token_presentations']==budget['valid_target_token_presentations']
                and report['count_training_row_presentations']==budget['count_presentations']
                and report['source_value_presentations']==source_budget and report['stopped_reason']=='epochs_completed')
            if completed:exposure.validate_completed_exposure(report,budget,recipe)
            summary=dict(arm=name,seed=seed,recipe=recipe,budget_completed=completed,training=report,
                postfit=postfit,initial_greedy_invariance=initial_replay,raw_training_replay=replay,
                underlying_state_tensor_sha256=body_digests,training_call_elapsed_seconds=fit_seconds,
                postfit_elapsed_seconds=time.monotonic()-post_started,elapsed_seconds=time.monotonic()-started,
                trainable_parameter_count=sum(p.numel() for p in model.parameters() if p.requires_grad),
                actual_parameter_count=sum(p.numel() for p in model.parameters()),
                prefit_budget=budget,**FALSE)
            save(folder/'summary.json',summary);summaries.append(summary)
            print(json.dumps(dict(arm=name,steps=report['optimizer_steps'],selected_epoch=report['selected_epoch'],
                last_exact=report['last_complete_attempt']['fidelity']['metrics']['ordered_exact'],
                trainable_parameter_count=summary['trainable_parameter_count'],elapsed=fit_seconds)),flush=True)
    return dict(schema='shared-slot-source-training-comparison/v1',runs=summaries,
        complete=len(summaries)==4 and all(run['budget_completed'] for run in summaries),
        raw_training_replay_parity=all(run['raw_training_replay']['complete'] for run in summaries
            if run['recipe']['head_kind']=='independent_affine'),dimensions_actually_trained=[384],
        training_executed=True,cached_source_order_recoverability_claimed=False,**FALSE)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('dependency-root','extension-root','manifest','plan','output'):
        parser.add_argument('--'+key,type=Path,required=True)
    parser.add_argument('--phase',choices=['training'],required=True)
    args=parser.parse_args();ctx=load_context(args);helpers=ctx['helpers']
    before=helpers.inventory(args.dependency_root,args.extension_root,ctx['pins']);args.output.mkdir(parents=True)
    helpers.save(args.output/'sealed-recipe.json',dict(plan=ctx['plan'],manifest=ctx['manifest'],tree_pin=ctx['tree'],**FALSE))
    helpers.save(args.output/'preprocessing-replay.json',ctx['prior'].validate_preprocessing(ctx))
    summary=training_phase(args,ctx);after=helpers.inventory(args.dependency_root,args.extension_root,ctx['pins'])
    require(all(after.get(path)==digest for path,digest in before.items()),'loaded source changed')
    helpers.validate_manifest_inputs(ctx['manifest']);validate_input_bindings(ctx['plan'],ctx['manifest'])
    for path,digest in ctx['pins'].items():require(helpers.sha(args.extension_root/path)==digest,'frozen extension changed')
    require(helpers.sha(args.plan)==ctx['manifest']['plan_sha256'],'sealed plan changed')
    summary.update(source_dependencies=after,workers=1,bridge_names=[],legal_ir_evaluate_provers=False,
        metric_disk_cache_used=False,paragraph_embedding_cache_used=True,encoder_executed=False,
        encoder_context_changed=False,output_limit_changed=False,downloads_performed=False)
    helpers.save(args.output/'summary.json',summary)


if __name__=='__main__':main()
