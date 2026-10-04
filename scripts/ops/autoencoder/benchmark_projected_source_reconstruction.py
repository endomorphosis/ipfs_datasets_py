#!/usr/bin/env python3
"""Fixed projected-source reconstruction comparison with unchanged strict gates.

All preprocessing is fitted on original training inputs only. Postfit negative
controls cannot alter training, checkpoint selection, or reference targets.
"""
import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import time

AUTO='ipfs_datasets_py/logic/formalization/autoencoder/'
PREFIX='ipfs_datasets_py.logic.formalization.autoencoder.'
FALSE=dict(qualified=False,admitted=False,proof_authority=False,source_semantics_verified=False,
    checkpoint_promoted=False,convergence_proven=False,fresh_holdout=False,lake_executed=False,
    formalized=False,roundtrip_ok=False)
ARMS = [dict(name=mode+('-boundary' if guided else '-unguided'), normalization=mode,
    guide_boundary=guided, source_value_weight=.25, count_exposure='balanced_all', cardinality_weight=.25)
    for mode in ('none', 'center_rms') for guided in (False, True)]
CONTROLS = [['validation', 'validation', 'conditioned'], ['training', 'train', 'conditioned'],
    ['zero-condition', 'validation', 'zero_condition'], ['source-shuffle', 'validation', 'source_shuffle'],
    ['cross-length-shuffle', 'validation', 'cross_length_shuffle']]
FIXED = dict(schema='projected-source-reconstruction-plan/v1', representation_dimension=384, arms=ARMS,
    seed_order=[1729,2718], conditioning='every_step', loss='semantic_fields', epochs_per_source_stage=20,
    expected_optimizer_steps_per_arm=340, expected_training_token_presentations_per_arm=225840,
    expected_count_presentations_per_arm=2440, expected_source_value_presentations_per_candidate=25600,
    batch_size=8, learning_rate=.001, max_seconds_per_arm=90, validation_interval=4,
    fixed_encoder_context_tokens=512, fixed_decoder_output_limit=512, source_value_max_rules=8,
    source_value_fields=['actor','action','modality','object'], source_value_full_vocabulary=True,
    source_value_guidance=True, projection_frozen=True, inherited_decoder_and_count_trainable=True,
    projected_count_features=True, normalization_fit_split='train', normalization_scale='global_rms_row_l2',
    count_prior_fit_split='train', count_prior_classes=list(range(1,33)),
    count_prior_smoothing='symmetric_dirichlet_total_concentration', count_prior_total_concentration=1.,
    count_prior_alpha_per_class=1./32, boundary_correction='posterior_log_odds_minus_training_prior_log_odds',
    initial_greedy_invariance_required=True, teacher_distillation_used=False, selection_unchanged=True,
    no_downloads=True, temperature=0, generation_reference_count_access=False,
    generation_reference_prefix_access=False, native_qualification=False,
    expected_balanced_count_presentations={'1':610,'2':610,'4':610,'8':610}, postfit_controls=CONTROLS,
    max_seconds_per_postfit=30, max_seconds_per_numerical_evaluation=20,
    max_seconds_per_preprocessing=30, full_gradient_packets_retained=False,
    optimizer_updates_only_when_deadline_allows=True, production_promotion_allowed=False)


def validate_plan(plan):
    if type(plan) is not dict or any(json.dumps(plan.get(k),sort_keys=True,allow_nan=False)!=
        json.dumps(v,sort_keys=True,allow_nan=False) for k,v in FIXED.items()):
        raise ValueError('unsupported fixed projected-source reconstruction plan')


def load_helper(root,pins,relative,name):
    path=root/relative
    if hashlib.sha256(path.read_bytes()).hexdigest()!=pins.get(relative):
        raise ValueError('frozen benchmark helper differs: '+relative)
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


def cross_length_shuffle(rows, references):
    """A fixed bijection changes every source length without changing targets."""
    if (type(rows) is not list or type(references) is not list or
            any(type(row) is not dict or type(row.get('id')) is not str for row in rows+references) or
            any(type(row.get('clause_count')) is not int for row in references)):
        raise ValueError('cross-length shuffle requires explicit source and length identities')
    ids = [row['id'] for row in rows]
    by_id = {row['id']: row for row in rows}
    by_ref = {row['id']: row for row in references}
    if (len(ids) != 48 or len(by_id) != 48 or len(by_ref) != 48
            or len(references) != 48 or set(ids) != set(by_ref)):
        raise ValueError('cross-length shuffle requires unique balanced48 inventories')
    groups = {length: sorted(identity for identity in ids if by_ref[identity].get('clause_count') == length)
              for length in (1,2,4,8)}
    if any(len(group) != 12 for group in groups.values()):
        raise ValueError('cross-length shuffle requires twelve rows per length')
    order = [identity for group in groups.values() for identity in group]
    assignment = {identity: order[(index+12)%48] for index, identity in enumerate(order)}
    actual = []
    substitutions = {}
    raw = lambda value: json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
    for row in rows:
        donor = by_id[assignment[row['id']]]
        if (row['input'] == donor['input'] or by_ref[row['id']]['clause_count'] == by_ref[donor['id']]['clause_count']):
            raise ValueError('ineffective cross-length source substitution')
        actual.append({**deepcopy(row), 'input':deepcopy(donor['input'])})
        substitutions[row['id']] = dict(original_input_sha256=hashlib.sha256(raw(row['input'])).hexdigest(),
            substituted_input_sha256=hashlib.sha256(raw(donor['input'])).hexdigest())
    return actual, dict(kind='source_shuffle', shuffle_policy='cross_length', source_assignment=assignment,
        input_substitutions=substitutions)


def control_scope(kind):
    if kind not in ('conditioned','zero_condition','source_shuffle','cross_length_shuffle'):
        raise ValueError('unsupported projected-source evaluation control')
    return dict(shuffle_preserves_reference_clause_count=kind=='source_shuffle',
        independent_count_generalization_test=False,
        diagnostic_scope={'conditioned':'ordinary fixed-state source-conditioned readout',
            'zero_condition':'zero initial/persistent recurrent source and normalized scalar/count features; retain learned biases and fixed count prior',
            'source_shuffle':'within-length source derangement; postfit only',
            'cross_length_shuffle':'cross-length source derangement; diagnostic comparison against original targets only'}[kind])


def boundary_diagnostics(source_count, prior):
    """Read fixed hypothetical boundaries; no reference counts or generation."""
    def odds(logits, completed):
        tail=logits[completed:]
        maximum=max(tail)
        return logits[completed-1]-(maximum+math.log(sum(math.exp(value-maximum) for value in tail)))
    baseline=prior.get('log_prior')
    rows=source_count.get('predictions')
    if (type(baseline) is not list or len(baseline)!=32 or
            any(type(x) not in (int,float) or not math.isfinite(x) for x in baseline) or
            type(rows) is not list or not rows):
        raise ValueError('finite count prior and predictions required')
    result=[];seen=set()
    for row in rows:
        identity=row.get('id');logits=row.get('logits')
        if (type(identity) is not str or not identity or identity in seen or
                type(logits) is not list or len(logits)!=32 or
                any(type(x) not in (int,float) or not math.isfinite(x) for x in logits)):
            raise ValueError('unique finite32 count logits required')
        seen.add(identity)
        result.append(dict(id=identity,boundaries={str(k):dict(
            posterior_stop_tail_log_odds=odds(logits,k),prior_stop_tail_log_odds=odds(baseline,k),
            hypothetical_logit_correction=odds(logits,k)-odds(baseline,k)) for k in (1,2,4,8)}))
    return dict(schema='hypothetical-prior-centered-boundary-diagnostics/v1',rows=result,
        applied_to_generation=False,observed_generation_boundaries=False,reference_clause_count_used=False,
        count_prior_receipt_sha256=prior['receipt_sha256'],
        formula='log p(k)-log sum_{j>k}p(j)-log prior(k)+log sum_{j>k}prior(j)',
        scope='fixed hypothetical k=1,2,4,8; float64 readout of stored float32 logits, not actual prefix decisions')


def greedy_inventory(torch,core,model,rows_by_split,donor,*,max_seconds):
    """Target-free original-policy replay, preserving modes and bounded by one deadline."""
    if type(max_seconds) not in (int,float) or not math.isfinite(max_seconds) or max_seconds<=0:
        raise ValueError('positive bounded generation deadline required')
    started=time.monotonic();deadline=started+max_seconds
    modes={name:module.training for name,module in model.named_modules()}
    before=core.tensor_digest(model);predictions={}
    transform=donor['input_transform'];size=len(donor['codec']['target_vocabulary'])
    try:
        model.eval()
        with torch.inference_mode():
            for split,rows in rows_by_split.items():
                predictions[split]=[]
                for offset in range(0,len(rows),8):
                    if time.monotonic()>=deadline:
                        raise ValueError('initial generation deadline exceeded')
                    part=rows[offset:offset+8]
                    inputs=torch.tensor([row['input'] for row in part],dtype=torch.float32)
                    data=(inputs-torch.tensor(transform['mean'],dtype=torch.float32))/transform['scale']
                    result=core._greedy(torch,model,data,512,size,deadline)
                    if result is None:
                        raise ValueError('initial generation deadline exceeded')
                    for row,tokens,status in zip(part,result[1],result[2]):
                        predictions[split].append(dict(id=row['id'],token_ids=tokens,
                            generation_status=status,eos_reached=status=='eos'))
    finally:
        for name,module in model.named_modules():
            module.training=modes[name]
    if core.tensor_digest(model)!=before:
        raise ValueError('initial generation changed model tensors')
    if time.monotonic()>=deadline:
        raise ValueError('initial generation deadline exceeded')
    return dict(schema='projected-source-initial-greedy/v1',predictions=predictions,
        model_tensor_sha256=before,reference_documents_passed_to_model=False,
        target_tokens_passed_to_model=False,max_target_tokens=512,temperature=0,
        elapsed_seconds=time.monotonic()-started,**FALSE)


def source_value_diagnostic(torch,model,rows,references,codec,transform,deadline,*,
                            scalar_owner,trainer,validate_rule):
    """Postfit labels are passed to scoring only, after a state has been frozen."""
    labels=scalar_owner.reference_source_values(rows,references,codec,validate_rule=validate_rule)
    result=trainer._source_value_evaluation(torch,model,rows,labels,transform,
        dict(batch_size=8),codec,deadline)
    if result is None or time.monotonic()>=deadline:
        raise ValueError('incomplete source-value readout')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('dependency-root','extension-root','manifest','plan','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    manifest=json.loads(args.manifest.read_bytes())
    helper_path=args.extension_root/'scripts/ops/autoencoder/decoder_fidelity_replay.py'
    if hashlib.sha256(helper_path.read_bytes()).hexdigest()!=manifest['extensions'].get('scripts/ops/autoencoder/decoder_fidelity_replay.py'):
        raise ValueError('frozen replay helper differs')
    spec=importlib.util.spec_from_file_location('_count_exposure_replay',helper_path)
    replay=importlib.util.module_from_spec(spec);spec.loader.exec_module(replay)
    ctx=replay.load_context(args,validate_plan=validate_plan)
    helpers,core,plan=ctx['helpers'],ctx['core'],ctx['plan']
    require,save=helpers.require,helpers.save
    exposure=load_helper(args.extension_root,ctx['pins'],'scripts/ops/autoencoder/benchmark_decoder_count_exposure.py','_source_value_exposure')
    previous=exposure.load_control_helper(args.extension_root,ctx['pins'])
    prefit_budget=exposure.derive_count_budget(ctx['stages'],ctx['rows']['train'],ctx['references']['train'],plan,previous)
    counts={r['id']:r['clause_count'] for r in ctx['references']['train']}
    source_budget=sum(stage['epochs']*sum(4*counts[i] for i in stage['training_ids']) for stage in ctx['stages'])
    require(source_budget==plan['expected_source_value_presentations_per_candidate'],'source auxiliary exposure differs')
    prefit_budget['source_value_presentations_per_candidate']=source_budget
    helpers.extension(args.extension_root,AUTO+'decoder_cardinality_experiment.py',PREFIX+'decoder_cardinality_experiment',ctx['pins'])
    helpers.extension(args.extension_root,AUTO+'long_span_cardinality_training.py',PREFIX+'long_span_cardinality_training',ctx['pins'])
    exposure_trainer=helpers.extension(args.extension_root,AUTO+'long_span_count_exposure_training.py',PREFIX+'long_span_count_exposure_training',ctx['pins'])
    scalar_owner=helpers.extension(args.extension_root,AUTO+'source_value_decoder_experiment.py',PREFIX+'source_value_decoder_experiment',ctx['pins'])
    value_model=helpers.extension(args.extension_root,AUTO+'projected_source_decoder_experiment.py',PREFIX+'projected_source_decoder_experiment',ctx['pins'])
    trainer=helpers.extension(args.extension_root,AUTO+'long_span_source_value_training.py',PREFIX+'long_span_source_value_training',ctx['pins'])
    import torch
    source_before=helpers.inventory(args.dependency_root,args.extension_root,ctx['pins'])
    args.output.mkdir(parents=True)
    save(args.output/'sealed-recipe.json',dict(plan=plan,manifest=manifest,prefit_budget=prefit_budget,tree_pin=ctx['tree'],
        initializer='original_authenticated_donor_only',historical_fitted_states_loaded=False,**FALSE))
    lineage=dict(ctx['lineage'])

    def evaluate(model, split, control):
        evaluation_started=time.monotonic()
        actual=ctx['rows'][split]
        scope=control_scope(control)
        execution=dict(kind=control,source_assignment={row['id']:row['id'] for row in actual})
        if control=='source_shuffle':
            actual,execution=helpers.shuffle_inputs(actual,ctx['references'][split])
            execution['shuffle_policy']='within_length'
        elif control=='cross_length_shuffle':
            actual,execution=cross_length_shuffle(actual,ctx['references'][split])
        elif control=='zero_condition':
            model=value_model.bind_zero_condition_model(model)
        deadline=evaluation_started+plan['max_seconds_per_postfit']
        value=core.evaluate_model(model,actual,codec=ctx['donor']['codec'],input_transform=ctx['donor']['input_transform'],
            lineage=lineage,max_target_tokens=512,max_seconds=min(plan['max_seconds_per_numerical_evaluation'],deadline-time.monotonic()),batch_size=8)
        require(value['report']['complete'],'incomplete postfit evaluation')
        value['source_fidelity']=ctx['scorer'].score_predictions(ctx['references'][split],value['predictions'],
            codec=ctx['donor']['codec'],validate_rule=ctx['validate_rule'],validator_id=ctx['validator_id'],output_limit=512,
            control={k:execution[k] for k in ('kind','source_assignment')})
        value['source_count']=exposure_trainer._count_evaluation(torch,model,actual,ctx['references'][split],
            ctx['donor']['input_transform'],dict(batch_size=8),deadline)
        require(value['source_count'] is not None,'incomplete postfit count evaluation')
        value['hypothetical_boundary_diagnostics']=boundary_diagnostics(value['source_count'],count_prior)
        value['source_values']=source_value_diagnostic(torch,model,actual,ctx['references'][split],
            ctx['donor']['codec'],ctx['donor']['input_transform'],deadline,
            scalar_owner=scalar_owner,trainer=trainer,validate_rule=ctx['validate_rule'])
        require(time.monotonic()<deadline,'postfit deadline exceeded')
        value['execution']={**execution,'training_performed':False,'selection_performed':False,
            'provenance_breaking_negative_control':control in ('source_shuffle','cross_length_shuffle'),**scope}
        value['timing']=dict(postfit_evaluation_elapsed_seconds=time.monotonic()-evaluation_started,
            numerical_api_elapsed_seconds=value['report']['elapsed_seconds'],
            scope='control construction, numerical readout, source-fidelity scoring, source-count and source-value evaluation and hypothetical boundary diagnostics; excludes output file write')
        return value

    # Extract frozen projected TRAIN features exactly once. Validation vectors
    # are not passed to either fitting helper; their IDs are exclusion guards.
    preparation_started=time.monotonic()
    deadline=preparation_started+plan['max_seconds_per_preprocessing']
    persistent=ctx['adapter'].bind_persistent_model(ctx['base_model'].body,dimension=384,conditioning='every_step')
    for name,parameter in persistent.named_parameters():
        if name.startswith(('body.projection_down.','body.projection_up.')):
            parameter.requires_grad_(False)
    inherited_initial_digest=core.tensor_digest(persistent)
    feature_rows=[]
    train_reference_by_id={row['id']:row for row in ctx['references']['train']}
    with torch.inference_mode():
        for offset in range(0,len(ctx['rows']['train']),8):
            require(time.monotonic()<deadline,'training preprocessing deadline exceeded')
            part=ctx['rows']['train'][offset:offset+8]
            projected=persistent.project(exposure_trainer._source_batch(torch,part,ctx['donor']['input_transform']))
            for row,features in zip(part,projected.tolist()):
                reference=train_reference_by_id[row['id']]
                require(reference['source_sha256']==hashlib.sha256(row['source_text'].encode()).hexdigest(),
                    'training feature source hash differs')
                feature_rows.append(dict(id=row['id'],source_sha256=reference['source_sha256'],features=features))
    identities=dict(expected_training_ids=[row['id'] for row in ctx['rows']['train']],
        forbidden_validation_ids=[row['id'] for row in ctx['rows']['validation']],
        training_rows_sha256=core.digest(ctx['rows']['train']))
    count_rows=[dict(id=row['id'],source_sha256=row['source_sha256'],
        count=train_reference_by_id[row['id']]['clause_count']) for row in feature_rows]
    normalizations={mode:value_model.fit_source_normalization(feature_rows,kind=mode,**identities)
        for mode in ('none','center_rms')}
    count_prior=value_model.fit_source_count_prior(count_rows,**identities)
    require(time.monotonic()<deadline,'training preprocessing deadline exceeded')
    require(core.tensor_digest(persistent)==inherited_initial_digest,'preprocessing mutated original initializer')
    preprocessing=dict(schema='projected-source-reconstruction-preprocessing/v1',feature_rows=feature_rows,
        count_rows=count_rows,normalizations=normalizations,count_prior=count_prior,
        initializer_tensor_sha256=inherited_initial_digest,identities=identities,
        original_inputs={name:manifest[name] for name in ('donor','paragraphs','embeddings','curriculum','curriculum_inputs')},
        validation_vectors_used=False,validation_targets_used=False,
        elapsed_seconds=time.monotonic()-preparation_started,**FALSE)
    save(args.output/'preprocessing.json',preprocessing)
    # No references, target IDs or text are supplied to these parity rollouts.
    initial_predictions=greedy_inventory(torch,core,persistent,ctx['rows'],ctx['donor'],
        max_seconds=plan['max_seconds_per_preprocessing'])
    save(args.output/'original-initial-generation.json',initial_predictions)
    summaries=[];initial_states={}
    for seed in plan['seed_order']:
        for recipe in plan['arms']:
            arm_started=time.monotonic()
            name=recipe['name']+'-'+str(seed)
            persistent=ctx['adapter'].bind_persistent_model(ctx['base_model'].body,dimension=384,conditioning='every_step')
            for parameter_name,parameter in persistent.named_parameters():
                if parameter_name.startswith(('body.projection_down.','body.projection_up.')):
                    parameter.requires_grad_(False)
            inherited_digest=core.tensor_digest(persistent)
            require(inherited_digest==inherited_initial_digest,'original donor initializer differs between arms')
            model=value_model.bind_projected_source_model(persistent,codec=ctx['donor']['codec'],
                normalization_receipt=normalizations[recipe['normalization']],count_prior_receipt=count_prior,
                guide_boundary=recipe['guide_boundary'],scalar_guidance=True)
            require(core.tensor_digest(model.body)==inherited_digest,'new source heads changed inherited tensors')
            mode=recipe['normalization']
            if mode not in initial_states:
                tensors={key:value.tolist() for key,value in model.state_dict().items()}
                initial_states[mode]=save(args.output/('initial-state-'+mode+'.json'),dict(
                    schema='private-projected-source-initial-state/v1',architecture=model.describe(),
                    model_state=tensors,weights_sha256=core.digest(tensors),tensor_sha256=core.tensor_digest(model),
                    inherited_tensor_sha256=inherited_digest,original_donor_sha256=lineage['teacher_checkpoint_sha256'],
                    optimizer_resumable=False,**FALSE))
            initial_state=json.loads(Path(initial_states[mode]['path']).read_bytes())
            require(core.tensor_digest(model)==initial_state['tensor_sha256'],
                'initial head tensors differ between seed or boundary arms')
            initialization=greedy_inventory(torch,core,model,ctx['rows'],ctx['donor'],
                max_seconds=plan['max_seconds_per_preprocessing'])
            require(initialization['predictions']==initial_predictions['predictions'],
                'zero source residuals changed initial actual-greedy generation')
            initialization.update(identical_to_original_greedy=True,
                original_tensor_sha256=inherited_digest,model_tensor_sha256=core.tensor_digest(model),
                initial_state=initial_states[mode])
            save(args.output/name/'initial-generation.json',initialization)
            lineage['student_lineage']='projected_source_v1:'+name
            training_started=time.monotonic()
            result=trainer.train(model,ctx['rows']['train'],ctx['rows']['validation'],
                training_references=ctx['references']['train'],validation_references=ctx['references']['validation'],
                codec=ctx['donor']['codec'],input_transform=ctx['donor']['input_transform'],lineage=lineage,
                validate_rule=ctx['validate_rule'],validator_id=ctx['validator_id'],curriculum=ctx['stages'],
                strategy='semantic_fields',cardinality_weight=recipe['cardinality_weight'],count_exposure=recipe['count_exposure'],
                source_value_weight=recipe['source_value_weight'],
                config=dict(seed=seed,max_seconds=plan['max_seconds_per_arm'],max_target_tokens=512,batch_size=8,learning_rate=.001,
                    max_optimizer_steps=1000,patience=0,validation_interval=4,alpha=0.))
            training_call_elapsed_seconds=time.monotonic()-training_started
            report=result['report'];folder=args.output/name
            save(folder/'training.json',report)
            save(folder/'selected-predictions.json',result['predictions'])
            save(folder/'last-attempt-predictions.json',result['last_complete_attempt_predictions'])
            postfit={}
            postfit_started=time.monotonic()
            for role,state,predictions in [('selected',result['state_dict'],result['predictions']),
                    ('last-attempt',result['last_complete_attempt_state_dict'],result['last_complete_attempt_predictions'])]:
                if state is None or (role=='selected' and report['selected'] is None):
                    continue
                model.load_state_dict(state,strict=True)
                expected_digest=report['selected_weights_sha256'] if role=='selected' else report['last_complete_attempt_weights_sha256']
                require(core.tensor_digest(model)==expected_digest,'returned state differs from recorded role digest')
                state_values={k:v.tolist() for k,v in model.state_dict().items()}
                receipt=save(folder/(role+'-state.json'),dict(schema='private-projected-source-state/v1',recipe=recipe,
                    architecture=model.describe(),lineage=dict(lineage),codec=ctx['donor']['codec'],model_state=state_values,
                    weights_sha256=core.digest(state_values),tensor_sha256=core.tensor_digest(model),role=role,
                    selected=role=='selected' or report['last_complete_attempt_is_selected'],optimizer_resumable=False,**FALSE))
                persisted=json.loads(Path(receipt['path']).read_bytes())
                require(core.digest(persisted['model_state'])==persisted['weights_sha256'],'private state JSON digest differs')
                model.load_state_dict({k:ctx['numerical']._tensor(persisted['model_state'][k],v,k)
                    for k,v in model.state_dict().items()},strict=True)
                require(core.tensor_digest(model)==persisted['tensor_sha256']==expected_digest,'private reload tensor digest differs')
                postfit[role]={}
                for label,split,control in plan['postfit_controls']:
                    value=evaluate(model,split,control)
                    if label=='validation':require(value['predictions']==predictions,'saved state generation mismatch')
                    save(folder/role/('evaluation-'+label+'.json'),value)
                    postfit[role][label]=dict(numerical=value['report'],source_count=value['source_count'],
                        timing=value['timing'],execution=value['execution'],
                        source_values=None if value['source_values'] is None else {k:v for k,v in value['source_values'].items() if k!='predictions'},
                        hypothetical_boundary_diagnostics=value['hypothetical_boundary_diagnostics'],
                        source_fidelity={k:v for k,v in value['source_fidelity'].items() if k!='rows'})
            postfit_elapsed_seconds=time.monotonic()-postfit_started
            completed=(report['optimizer_steps']==prefit_budget['optimizer_steps']
                and report['row_presentations']==prefit_budget['row_presentations']
                and report['valid_target_token_presentations']==prefit_budget['valid_target_token_presentations']
                and report['stopped_reason']=='epochs_completed'
                and report['count_training_row_presentations']==prefit_budget['count_presentations']
                and report['source_value_presentations']==(source_budget if recipe['source_value_weight'] else 0))
            if completed:
                exposure.validate_completed_exposure(report,prefit_budget,recipe)
            summary=dict(arm=name,recipe=recipe,seed=seed,budget_completed=completed,training=report,postfit=postfit,
                initial_inherited_tensor_sha256=inherited_digest,initial_greedy_invariance=initialization,
                trainable_parameter_count=sum(p.numel() for p in model.parameters() if p.requires_grad),
                prefit_budget=prefit_budget,training_call_elapsed_seconds=training_call_elapsed_seconds,
                postfit_elapsed_seconds=postfit_elapsed_seconds,
                postfit_timing_scope='selected and available last-attempt state persistence, reloads, all evaluation controls and evaluation-file writes',
                elapsed_seconds=time.monotonic()-arm_started,
                timing_scope='whole arm: model construction, training, artifact writes, state replay and postfit evaluations; excludes this summary write and console print')
            save(folder/'summary.json',summary);summaries.append(summary)
            last=report['last_complete_attempt']
            print(json.dumps(dict(arm=name,steps=report['optimizer_steps'],elapsed=report['elapsed_seconds'],
                selected_epoch=report['selected_epoch'],last_count=last['source_count']['correct'] if last else None,
                last_source_values=None if not last or last['source_values'] is None else last['source_values']['correct'],
                last_exact=last['fidelity']['metrics']['ordered_exact'] if last else None,
                last_eos=last['fidelity']['metrics']['eos_count'] if last else None)),flush=True)
    after=helpers.inventory(args.dependency_root,args.extension_root,ctx['pins'])
    require(all(after.get(path)==expected for path,expected in source_before.items()),'loaded source changed')
    helpers.validate_manifest_inputs(manifest)
    for path,expected in ctx['pins'].items():require(helpers.sha(args.extension_root/path)==expected,'frozen extension changed')
    require(helpers.sha(args.plan)==manifest['plan_sha256'],'sealed plan changed')
    save(args.output/'summary.json',dict(schema='projected-source-reconstruction-comparison/v1',runs=summaries,
        complete=len(summaries)==8 and all(x['budget_completed'] for x in summaries),source_dependencies=after,
        preprocessing_sha256=helpers.sha(args.output/'preprocessing.json'),
        source_preprocessing_fit_split='train',historical_fitted_states_loaded=False,
        original_initializer_tensor_sha256=inherited_initial_digest,
        dimensions_actually_trained=[384],training_executed=any(x['training']['optimizer_steps']>0 for x in summaries),
        workers=1,bridge_names=[],legal_ir_evaluate_provers=False,metric_disk_cache_used=False,
        paragraph_embedding_cache_used=True,encoder_executed=False,encoder_context_changed=False,
        output_limit_changed=False,downloads_performed=False,**FALSE))


if __name__=='__main__':
    main()
