#!/usr/bin/env python3
"""Fresh 8D/384D/768D source-margin preservation comparison on exposed Legal development rows.

The historical linguistic teacher is untouched. New candidates remain private
formula sidecars; numerical or syntax results never grant Lake admission.
"""
import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
from types import SimpleNamespace
import time

AUTO = 'ipfs_datasets_py/logic/formalization/autoencoder/'
PREFIX = 'ipfs_datasets_py.logic.formalization.autoencoder.'
FALSE = dict(qualified=False, admitted=False, proof_authority=False, source_semantics_verified=False,
    checkpoint_promoted=False, convergence_proven=False, fresh_holdout=False, lake_executed=False,
    formalized=False, roundtrip_ok=False)
ARMS = [dict(name='source-head-lr10', generated_source_margin_weight=0., generated_source_margin_replay=False),
        dict(name='source-margin-zero', generated_source_margin_weight=0., generated_source_margin_replay=True),
        dict(name='source-margin-001', generated_source_margin_weight=.01, generated_source_margin_replay=True)]
for _arm in ARMS:
    _arm.update(non_action_learning_rate_multiplier=10., head_kind='clauses', factorized=True, recurrent=True, order_augmentation=False,
        action_contrastive_weight=.05, generated_boundary_weight=.05, generated_boundary_site_policy='first_last')
CONTROLS = [['validation','validation','conditioned'], ['training','train','conditioned'],
    ['zero-condition','validation','zero_condition'], ['source-shuffle','validation','source_shuffle'],
    ['cross-length-shuffle','validation','cross_length_shuffle'],
    ['context-only-shuffle','validation','context_only_shuffle'],
    ['context-reverse','validation','context_reverse'], ['context-rotate','validation','context_rotate']]
FIXED = dict(schema='source-margin-training-plan/v1', dimensions=[8,384,768], seed_order=[1729,2718],
    arms=ARMS, fit_count=18, original_training_rows=48, exposed_validation_rows=48,
    fixed_encoder_context_tokens=512, fixed_decoder_output_limit=512, temperature=0,
    action_contrastive_temperature=.1, contrastive_positive_policy='same_action_different_actor',
    contrastive_negative_policy='different_action', contrastive_unique_source_clauses=True,
    fresh_initialization=True, selection_unchanged=True, validation_pairs_added_to_training=False,
    teacher_distillation_used=False, historical_linguistic_teacher_modified=False,
    identity_projection_frozen=True, identity_mse_is_not_learned_reconstruction=True,
    source_independent_donor_tensors_copied=True, dimension_only_ablation=False,
    learning_rate=.001, batch_size=8, epochs_per_source_stage=20, max_seconds_per_arm=180,
    validation_interval=4, expected_optimizer_steps_per_arm=340,
    expected_training_token_presentations_per_arm=225840, expected_row_presentations_per_arm=2440,
    expected_count_presentations_per_arm=2440, expected_source_value_presentations_per_arm=25600,
    expected_balanced_count_presentations={'1':610,'2':610,'4':610,'8':610},
    cardinality_weight=.25, source_value_weight=.25, count_exposure='balanced_all', strategy='semantic_fields',
    baseline_replay_required=True, full_vocabulary_retained=True, syntax_forced=False, closure_forced=False,
    production_promotion_allowed=False, generation_reference_count_access=False, postfit_controls=CONTROLS, additional_candidate_control='recurrent-residual-off',
    recurrent_parameter_delta=0, generated_boundary_vocabulary_policy='full_vocabulary',
    boundary_labels_after_source_only_rollout=True, source_margin_labels_after_source_only_rollout=True,
    source_margin_replay_arms=['source-margin-zero','source-margin-001'],
    source_margin_objective_arms=['source-margin-001'], zero_weight_auxiliary_graph_attached=False,
    source_margin_ratio=1., source_margin_cap=None,
    source_margin_gradient_scope='recurrent_path_only;shared_global_clipping',
    source_margin_eligibility='source_full_vocabulary_argmax_equals_training_label;positive_source_margin',
    source_margin_site_policy='first_eroded_eligible_per_field', source_margin_site_cap_per_row=4,
    source_margin_normalization='mean_selected_sites_per_active_row;mean_active_rows',
    source_margin_objective='relu(detached_source_target_vs_best_other_margin-combined_target_vs_best_other_margin)',
    generated_replay_strategy='baseline_original_boundary;controls_joint_boundary_and_source_margin_sites',
    generated_replay_retry_limit_per_original_batch=1, generated_replay_atol=2e-5, generated_replay_rtol=2e-5,
    auxiliary_interval_phase='zero_based_committed_optimizer_step_mod_interval_equals_zero',
    baseline_equivalence_exclusions=['elapsed_seconds','committed_updates[*].generated_boundary.elapsed_seconds',
        'committed_updates[*].generated_boundary.generation.elapsed_seconds','committed_updates[*].generated_boundary.collection_sha256'], generated_boundary_gradient_scope='all_trainable', source_segmentation_availability_is_an_inference_feature=True,
    max_seconds_per_postfit=30, max_seconds_per_numerical_evaluation=20,
    max_seconds_entire_run=4200, max_memory_bytes=536870912, boundary_max_memory_bytes=1073741824, generated_fields_max_memory_bytes=2147483648,
    non_action_learning_rate_multiplier_all_arms=10.,
    non_action_fields=['actor','modality','object'], architecture_changed=False,
    source_margin_fields=['actor','action','modality','object'],
    fresh_test_rows=48,fresh_test_template_families=3,fresh_test_lengths=[1,2,4,8],
    fresh_test_role='postfit_only_after_all_registered_fits;not_selection',
    fresh_test_endpoint='last_complete_attempt;all_arms_all_seeds_once',
    fresh_test_secondary_endpoint='existing_development_selected;all_arms_all_seeds_once',
    intervention_is_fresh_training_trajectory_not_endpoint_repair=True,
    higher_lr_also_increases_AdamW_per_step_decay=True,
    no_downloads=True, encoder_executed_during_training=False)


def require(value, message):
    if not value: raise ValueError(message)


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_plan(plan):
    require(type(plan) is dict and all(type(plan.get(k)) is type(v)
        and json.dumps(plan[k],sort_keys=True,allow_nan=False)==json.dumps(v,sort_keys=True,allow_nan=False)
        for k,v in FIXED.items()), 'fixed generated-replay consistency comparison differs')


def jobs():
    return [(dimension,seed,deepcopy(arm)) for dimension in FIXED['dimensions']
        for seed in FIXED['seed_order'] for arm in ARMS]


def load_helper(root, pins, path, name):
    require(sha(root/path)==pins[path], 'frozen helper differs: '+path)
    spec=importlib.util.spec_from_file_location(name,root/path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


def load_context(args):
    manifest=json.loads(args.manifest.read_bytes()); plan=json.loads(args.plan.read_bytes()); validate_plan(plan)
    require(sha(args.plan)==manifest['plan_sha256'] and plan['input_sha256']==manifest['inputs'], 'fixed inputs differ')
    for path,digest in manifest['inputs'].items(): require(sha(path)==digest, 'input changed: '+path)
    for key in ('parent_manifest','parent_plan'):
        require(str(Path(manifest[key]).resolve()) in manifest['inputs'], 'unbound manifest alias: '+key)
    paths=manifest['baseline_summaries']
    require(set(paths)=={str(d)+'-source-head-lr10-'+str(seed) for d in FIXED['dimensions']
        for seed in FIXED['seed_order']}, 'exact six predecessor baseline summaries required')
    require(all(str(Path(p).resolve()) in manifest['inputs'] for p in paths.values()), 'unbound baseline alias')
    native=load_helper(args.extension_root,manifest['extensions'],
        'scripts/ops/autoencoder/benchmark_native_dimension_source_training.py','_action_native_runner')
    oldargs=SimpleNamespace(**vars(args)); oldargs.manifest=Path(manifest['parent_manifest']); oldargs.plan=Path(manifest['parent_plan'])
    ctx=native.load_context(oldargs)
    ctx.update(plan=plan,manifest=manifest,pins=manifest['extensions'],native_runner=native)
    for name in ('action_factorized_clause_decoder_experiment','action_contrastive_decoder_training',
                 'ordered_clause_recurrent_decoder_experiment','contextual_generated_boundary_training','generated_field_training','generated_source_margin_training'):
        ctx['owners'][name]=ctx['helpers'].extension(args.extension_root,AUTO+name+'.py',PREFIX+name,ctx['pins'])
    ctx['baseline_runs']={name:json.loads(Path(path).read_bytes()) for name,path in paths.items()}
    for name, record in ctx['baseline_runs'].items():
        require(record['arm']==name and record.get('budget_completed') is True, 'complete prior source-head-lr10 comparison required')
        def bound_read(ref):
            path=Path(ref['path'])
            require(str(path.resolve()) in manifest['inputs'] and sha(path)==ref['sha256'], 'unbound prior numerical evidence')
            return json.loads(path.read_bytes())
        record['training']=bound_read(record['training_ref'])
        record['postfit']={role:{label:bound_read(ref) for label,ref in panels.items()} for role,panels in record['postfit'].items()}
    return ctx


def bind_candidate(ctx, recipe, seed):
    require(recipe in ARMS and seed in FIXED['seed_order'], 'unplanned recurrent candidate')
    model=ctx['native_runner'].bind_candidate(ctx,ctx['native_runner'].ARMS[1],seed)
    model=ctx['owners']['action_factorized_clause_decoder_experiment'].bind_action_factorized_clause_model(
        model,codec=ctx['donor']['codec'])
    if recipe['recurrent']:
        model=ctx['owners']['ordered_clause_recurrent_decoder_experiment'].bind_ordered_clause_recurrent_model(
            model,codec=ctx['donor']['codec'])
    return model


def validate_initial(ctx, model, seed, recipe):
    import torch
    baseline=bind_candidate(ctx,ARMS[0],seed); core=ctx['core']; count=lambda m:sum(p.numel() for p in m.parameters() if p.requires_grad)
    expected=0
    require(count(model)-count(baseline)==expected, 'recurrent parameter delta differs')
    for name,value in baseline.state_dict().items():
        require(name in model.state_dict() and torch.equal(model.state_dict()[name],value), 'inherited initial tensor differs')
    predictions=[]
    with torch.inference_mode():
        for split in ('train','validation'):
            outputs=[]
            for offset in range(0,48,8):
                part=ctx['rows'][split][offset:offset+8]
                data=ctx['native_runner'].transformed_rows(torch,part,ctx['donor']['input_transform'])
                kw=core._source_context_kwargs(torch,part,ctx['source_contexts'][split],ctx['donor']['input_transform'])
                require(torch.equal(model.source_value_logits(data,**kw),baseline.source_value_logits(data,**kw)),
                    'initial scalar logits differ')
                observed=core._greedy(torch,model,data,512,len(ctx['donor']['codec']['target_vocabulary']),time.monotonic()+30,**kw)
                require(observed is not None and torch.equal(observed[0],data), 'initial projection/generation differs')
                outputs.extend(dict(id=r['id'],token_ids=t,generation_status=s) for r,t,s in zip(part,observed[1],observed[2]))
            predictions.append(dict(split=split,predictions=outputs))
    prior=ctx['baseline_runs'][str(ctx['dimension'])+'-source-head-lr10-'+str(seed)]['initial_parity']
    require(predictions==prior['predictions'], 'initial generation differs from original immutable baseline')
    return dict(complete=True,dimension=ctx['dimension'],predictions=predictions,
        baseline_trainable_parameters=count(baseline),trainable_parameters=count(model),parameter_delta=expected,
        inherited_initial_tensors_equal=True,initial_scalar_logits_equal=True,prior_initial_generation_equal=True,**FALSE)


def train_candidate(ctx, model, seed, recipe):
    return ctx['owners']['long_span_source_value_training'].train(model,ctx['rows']['train'],ctx['rows']['validation'],
        training_references=ctx['references']['train'],validation_references=ctx['references']['validation'],
        codec=ctx['donor']['codec'],input_transform=ctx['donor']['input_transform'],lineage=ctx['lineage'],
        validate_rule=ctx['validate_rule'],validator_id=ctx['validator_id'],curriculum=ctx['stages'],
        strategy='semantic_fields',cardinality_weight=.25,count_exposure='balanced_all',source_value_weight=.25,
        source_contexts=ctx['source_contexts'],action_contrastive_weight=recipe['action_contrastive_weight'],
        generated_boundary_weight=recipe['generated_boundary_weight'],
        generated_boundary_site_policy=recipe['generated_boundary_site_policy'],
        generated_source_margin_weight=recipe['generated_source_margin_weight'],
        generated_source_margin_replay=recipe['generated_source_margin_replay'],
        non_action_learning_rate_multiplier=recipe['non_action_learning_rate_multiplier'],
        config=dict(seed=seed,max_seconds=180,max_target_tokens=512,batch_size=8,learning_rate=.001,
            max_optimizer_steps=1000,patience=0,validation_interval=4,alpha=0.,
            max_memory_bytes=FIXED['generated_fields_max_memory_bytes'] if recipe['generated_source_margin_replay'] else FIXED['boundary_max_memory_bytes']))


def validate_margin_report(ctx, report, recipe):
    """Reject omitted, mislabeled or nontraining auxiliary execution."""
    if not recipe['generated_source_margin_replay']:
        require(not any(k.startswith('generated_source_margin_') for k in report),
            'baseline unexpectedly used source-margin path')
        return
    expected=dict(generated_source_margin_replay=True,
        generated_source_margin_weight=recipe['generated_source_margin_weight'],
        generated_source_margin_objective_enabled=recipe['generated_source_margin_weight'] != 0.,
        generated_source_margin_used_for_selection=False,
        generated_source_margin_scheduled_updates=340,
        generated_source_margin_zero_weight_graph_attached=False,
        generated_source_margin_shared_clip_can_change_other_parameter_updates=True,
        generated_source_margin_gradient_scope='explicit_recurrent_parameters_only_before_shared_global_clip')
    require(all(type(report.get(k)) is type(v) and report[k]==v for k,v in expected.items()),
        'source-margin objective policy differs')
    names=report.get('generated_source_margin_parameter_names')
    require(names==list(ctx['owners']['generated_source_margin_training'].RECURRENT_PARAMETER_NAMES),
        'source-margin exact parameter inventory differs')
    inventory=report.get('generated_source_margin_inventory'); rows=ctx['rows']['train']; digest=ctx['core'].digest
    require(type(inventory) is dict and inventory.get('validation_rows_used') is False
        and inventory.get('reference_documents_passed_to_model') is False
        and inventory.get('source_alignment_inferred') is False
        and inventory.get('fields')==FIXED['source_margin_fields']
        and inventory.get('training_rows_sha256')==digest(rows)
        and inventory.get('training_references_sha256')==digest(ctx['references']['train'])
        and inventory.get('training_contexts_sha256')==digest(ctx['source_contexts']['train'])
        and inventory.get('codec_sha256')==digest(ctx['donor']['codec']),
        'source-margin training inventory differs')
    updates=report.get('committed_updates')
    require(type(updates) is list and len(updates)==340,'source-margin committed inventory differs')
    identities={r['id'] for r in rows}; backwards=0
    for index,update in enumerate(updates):
        envelope=update.get('generated_source_margin')
        require(type(envelope) is dict and type(envelope.get('interval')) is int and envelope['interval']==1
            and type(envelope.get('zero_based_committed_step')) is int
            and envelope['zero_based_committed_step']==index,'source-margin cadence differs')
        gradient=envelope.get('gradient'); receipt=envelope.get('receipt')
        require(type(gradient) is dict and gradient.get('parameter_names')==names
            and type(gradient.get('backward_executed')) is bool
            and gradient.get('parameter_count')==report['generated_source_margin_parameter_count'],
            'source-margin derivative inventory differs')
        for key in ('unscaled_l2_norm','scaled_l2_norm','backward_elapsed_seconds','combined_preclip_norm','shared_clip_factor'):
            require(type(gradient.get(key)) in (int,float) and math.isfinite(gradient[key]) and gradient[key]>=0.,
                'source-margin gradient telemetry missing or nonfinite')
        require(gradient['combined_preclip_norm']==update['preclip_norm'] and
            math.isclose(gradient['shared_clip_factor'],min(1.,1./(update['preclip_norm']+1e-6)),rel_tol=2e-7,abs_tol=1e-12),
            'source-margin shared clipping accounting differs')
        if recipe['generated_source_margin_weight']==0.:
            require(gradient['backward_executed'] is False and gradient['scaled_l2_norm']==0.
                and gradient['unscaled_l2_norm']==0. and gradient['backward_elapsed_seconds']==0.
                and gradient['none_gradient_parameter_names']==names
                and update['objective']==update['ordinary_objective'],
                'zero source-margin control performed auxiliary backward')
        backwards+=int(gradient['backward_executed'])
        require(type(receipt) is dict and receipt.get('reference_labels_used_only_after_rollout') is True
            and receipt.get('reference_documents_passed_to_model') is False
            and receipt.get('target_prefixes_used') is False and receipt.get('validation_rows_used') is False,
            'source-margin reference boundary differs')
        generation=receipt.get('generation')
        require(type(generation) is dict and generation.get('source_only') is True
            and generation.get('reference_count_access') is False
            and generation.get('inventory_access',False) is False
            and generation.get('complete_rollout_before_site_selection') is True
            and [r.get('id') for r in generation.get('rows',[])]==update.get('decoder_row_ids')
            and set(update['decoder_row_ids'])<=identities,'source-margin generation differs from training batch')
    require(report.get('generated_source_margin_auxiliary_backward_updates')==backwards,
        'source-margin backward count differs')


def baseline_comparable(report):
    """Keep raw receipts; remove only time fields and their dependent digest."""
    value=deepcopy(report);value.pop('elapsed_seconds')
    for update in value['committed_updates']:
        receipt=update['generated_boundary']
        receipt.pop('elapsed_seconds');receipt['generation'].pop('elapsed_seconds')
        # Collection digest includes the collection's elapsed_seconds. Every
        # retained decision, logit, source/model hash and selection stays exact.
        receipt.pop('collection_sha256')
    return value


def validate_baseline(ctx, report, panels, seed):
    previous=ctx['baseline_runs'][str(ctx['dimension'])+'-source-head-lr10-'+str(seed)]
    old=previous['training']; require(set(report)==set(old), 'baseline report inventory differs')
    require(ctx['core'].digest(baseline_comparable(report))==ctx['core'].digest(baseline_comparable(old)),
        'baseline numerical report replay differs')
    for role in ('selected','last-attempt'):
        for label in [*[row[0] for row in CONTROLS], 'recurrent-residual-off']:
            require(panels[role][label]['predictions']==previous['postfit'][role][label]['predictions'], 'baseline control predictions differ')
    return dict(complete=True,compared_training_fields=sorted(set(old)),
        excluded_fields=deepcopy(FIXED['baseline_equivalence_exclusions']),
        all_tensors_and_predictions_equal=True,timing_equality_claimed=False,
        collection_digest_exclusion_reason='digest includes measured collection elapsed time; retained rollout evidence compared exactly')


def recurrent_residual_diagnostic(ctx, model, split, control):
    """Observe potential per-source-clause residuals, not actual generated routes."""
    import torch
    core=ctx['core'];started=time.monotonic();before=core.tensor_digest(model)
    original=ctx['rows'][split]
    rows,contexts,execution=ctx['owners']['clause_source_controls'].prepare_control(
        original,ctx['source_contexts'][split],'conditioned' if control=='zero_condition' else control)
    working=model
    if control=='zero_condition':
        working=ctx['owners']['ordered_clause_recurrent_decoder_experiment'].bind_zero_condition_model(model)
    projection=getattr(working,'clause_to_embedding',None)
    if projection is None:projection=working.body.clause_to_embedding
    records=[];modes={name:part.training for name,part in working.named_modules()}
    try:
        working.eval()
        with torch.inference_mode():
            for offset in range(0,len(rows),8):
                require(time.monotonic()-started<30,'recurrent diagnostic deadline exceeded')
                part=rows[offset:offset+8];transform=ctx['donor']['input_transform']
                data=ctx['native_runner'].transformed_rows(torch,part,transform)
                kw=core._source_context_kwargs(torch,part,contexts,transform)
                features=working.source_recurrent_features(working.project(data),**kw)
                residual=projection(features)
                require(tuple(residual.shape)==(len(part),8,16) and bool(torch.isfinite(residual).all()),
                    'invalid potential recurrent residual')
                for row,mask,values in zip(part,kw['source_context']['mask'].tolist(),residual.tolist()):
                    records.append(dict(id=row['id'],source_mask=mask,potential_residuals=values))
    finally:
        for name,part in working.named_modules():part.training=modes[name]
    require(core.tensor_digest(model)==before,'recurrent observation changed model')
    require(time.monotonic()-started<30,'recurrent diagnostic deadline exceeded')
    return dict(schema='potential-source-clause-recurrent-residuals/v1',rows=records,
        model_tensor_sha256=before,source_contexts_sha256=core.digest(contexts),
        control=control,residual_disabled=working.describe().get('only_recurrent_clause_residual_zeroed',False),
        all_source_routes_removed=control=='zero_condition',source_only=True,
        reference_documents_passed_to_model=False,actual_prefix_routes_observed=False,
        timing_scope='additional potential-residual observation, excluded from panel numerical timing',
        elapsed_seconds=time.monotonic()-started,**FALSE)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('dependency-root','extension-root','manifest','plan','output'): parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--phase',choices=['training'],required=True); args=parser.parse_args()
    started=time.monotonic(); ctx=load_context(args); h=ctx['helpers']; core=ctx['core']; save=h.save
    before=h.inventory(args.dependency_root,args.extension_root,ctx['pins']); args.output.mkdir(parents=True)
    save(args.output/'sealed-recipe.json',dict(plan=ctx['plan'],manifest=ctx['manifest'],tree_pin=ctx['tree'],**FALSE))
    runs=[]
    for dimension in FIXED['dimensions']:
        lane=ctx['native_runner'].prepare_dimension(ctx,dimension)
        save(args.output/str(dimension)/'preprocessing.json',lane['preparation'])
        save(args.output/str(dimension)/'source-contexts.json',lane['source_contexts'])
        save(args.output/str(dimension)/'training-rows.json',lane['rows'])
        for seed in FIXED['seed_order']:
            for recipe in ARMS:
                require(time.monotonic()-started<FIXED['max_seconds_entire_run'], 'comparison deadline exceeded')
                arm_started=time.monotonic(); name=str(dimension)+'-'+recipe['name']+'-'+str(seed); folder=args.output/name
                lane['lineage']['student_lineage']=('source_head_learning_rate_formula_sidecar:' if recipe==ARMS[0] else 'source_margin_formula_sidecar:')+name
                model=bind_candidate(lane,recipe,seed); initial=validate_initial(lane,model,seed,recipe)
                save(folder/'initial-parity.json',initial)
                states={'initial':ctx['native_runner'].save_state(lane,model,recipe,'initial',False,folder/'initial-state.json')}
                fit_started=time.monotonic(); value=train_candidate(lane,model,seed,recipe)
                fit_seconds=time.monotonic()-fit_started; report=value['report']; save(folder/'training.json',report)
                require(report['stopped_reason']=='epochs_completed' and report['optimizer_steps']==340
                    and report['row_presentations']==2440 and report['valid_target_token_presentations']==225840
                    and report['source_value_presentations']==25600 and report['count_training_row_presentations']==2440
                    and report['count_training_presentations_by_class']==FIXED['expected_balanced_count_presentations'],
                    'incomplete ordered-clause-recurrent training exposure')
                validate_margin_report(lane,report,recipe)
                postfit={}
                for role,state,predictions in [('selected',value['state_dict'],value['predictions']),
                    ('last-attempt',value['last_complete_attempt_state_dict'],value['last_complete_attempt_predictions'])]:
                    require(state is not None, 'complete selected/final state required')
                    ctx['native_runner'].validate_wrapper_state(lane,state); model.load_state_dict(state,strict=True)
                    expected=report['selected_weights_sha256'] if role=='selected' else report['last_complete_attempt_weights_sha256']
                    require(core.tensor_digest(model)==expected, 'training state hash differs')
                    states[role]=ctx['native_runner'].save_state(lane,model,recipe,role,
                        role=='selected' or report['last_complete_attempt_is_selected'],folder/(role+'-state.json'))
                    postfit[role]={}
                    for label,split,control in CONTROLS:
                        panel=ctx['clause_runner'].evaluate(lane,model,split,control)
                        if label=='validation': require(panel['predictions']==predictions, 'saved state generation differs')
                        if recipe['recurrent']:
                            panel['recurrent_residual_diagnostic']=recurrent_residual_diagnostic(lane,model,split,control)
                        save(folder/role/('evaluation-'+label+'.json'),panel)
                        postfit[role][label]=ctx['prior'].compact_panel(panel,retain_predictions=True)
                    if recipe['recurrent']:
                        disabled=ctx['owners']['ordered_clause_recurrent_decoder_experiment'].bind_residual_off_model(model)
                        panel=ctx['clause_runner'].evaluate(lane,disabled,'validation','conditioned')
                        panel['execution'].update(kind='recurrent_residual_off', recurrent_residual_disabled=True,
                            selection_performed=False, training_performed=False)
                        panel['recurrent_residual_diagnostic']=recurrent_residual_diagnostic(lane,disabled,'validation','conditioned')
                        save(folder/role/'evaluation-recurrent-residual-off.json',panel)
                        postfit[role]['recurrent-residual-off']=ctx['prior'].compact_panel(panel,retain_predictions=True)
                replay=validate_baseline(lane,report,postfit,seed) if recipe==ARMS[0] else None
                record=dict(arm=name,dimension=dimension,seed=seed,recipe=recipe,training=report,states=states,
                    postfit=postfit,initial_parity=initial,baseline_replay=replay,training_call_elapsed_seconds=fit_seconds,
                    elapsed_seconds=time.monotonic()-arm_started,budget_completed=True,
                    trainable_parameter_count=sum(p.numel() for p in model.parameters() if p.requires_grad),**FALSE)
                # Full numerical panels and training history already have authenticated
                # standalone files. Avoid repeating their large arrays in every index.
                record['training_ref']=dict(path=str(folder/'training.json'),sha256=sha(folder/'training.json'))
                record.pop('training')
                record['postfit']={role:{label:dict(path=str(folder/role/('evaluation-'+label+'.json')),
                    sha256=sha(folder/role/('evaluation-'+label+'.json')),
                    fidelity=panel['source_fidelity'], numerical=panel['numerical'])
                    for label,panel in panels.items()} for role,panels in postfit.items()}
                save(folder/'summary.json',record)
                runs.append(dict(arm=name,summary_path=str(folder/'summary.json'),summary_sha256=sha(folder/'summary.json')))

                print(json.dumps(dict(arm=name,steps=340,selected_epoch=report['selected_epoch'],
                    final_exact=report['last_complete_attempt']['fidelity']['metrics']['ordered_exact'],fit_seconds=fit_seconds)),flush=True)
    after=h.inventory(args.dependency_root,args.extension_root,ctx['pins'])
    require(all(after.get(k)==v for k,v in before.items()), 'loaded producer changed')
    for path,digest in ctx['manifest']['inputs'].items(): require(sha(path)==digest, 'sealed input changed')
    for relative,digest in ctx['pins'].items(): require(sha(args.extension_root/relative)==digest, 'frozen extension changed')
    require(sha(args.plan)==ctx['manifest']['plan_sha256'], 'plan changed')
    require(time.monotonic()-started<FIXED['max_seconds_entire_run'], 'comparison deadline exceeded')
    save(args.output/'summary.json',dict(schema='source-margin-training-comparison/v1',complete=len(runs)==18,
        runs=runs,training_executed=True,dimensions_actually_trained=[8,384,768],source_dependencies=after,
        all_six_published_source_head_lr10_baselines_replayed=True,historical_linguistic_teacher_modified=False,
        identity_projection_is_not_learned_reconstruction=True,dimension_only_ablation=False,
        elapsed_seconds=time.monotonic()-started,workers=1,bridge_names=[],legal_ir_evaluate_provers=False,
        metric_disk_cache_used=False,encoder_executed=False,downloads_performed=False,**FALSE))


if __name__=='__main__': main()
