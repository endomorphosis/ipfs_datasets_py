#!/usr/bin/env python3
"""Paired source-value autoregressive training with unchanged strict gates."""
import argparse
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
ARMS=[dict(name='unchanged',feature_kind=None,source_value_weight=0.,count_exposure='balanced_all',guide_boundary=False,cardinality_weight=.25),
    dict(name='conditioning48',feature_kind='inherited_conditioning',source_value_weight=.25,count_exposure='balanced_all',guide_boundary=False,cardinality_weight=.25),
    dict(name='projected384',feature_kind='projected_source',source_value_weight=.25,count_exposure='balanced_all',guide_boundary=False,cardinality_weight=.25)]
CONTROLS=[['validation','validation','conditioned'],['training','train','conditioned'],
    ['zero-condition','validation','zero_condition'],['source-shuffle','validation','source_shuffle'],
    ['training-source-shuffle','train','source_shuffle']]
FIXED=dict(schema='decoder-source-value-training-plan/v1',representation_dimension=384,arms=ARMS,
    seed_order=[1729,2718],conditioning='every_step',loss='semantic_fields',epochs_per_source_stage=20,
    expected_optimizer_steps_per_arm=340,expected_training_token_presentations_per_arm=225840,
    expected_count_presentations_per_arm=2440,expected_source_value_presentations_per_candidate=25600,
    batch_size=8,learning_rate=.001,max_seconds_per_arm=90,validation_interval=4,
    fixed_encoder_context_tokens=512,fixed_decoder_output_limit=512,source_value_max_rules=8,
    source_value_fields=['actor','action','modality','object'],source_value_full_vocabulary=True,
    source_value_guidance=True,projection_frozen=True,inherited_decoder_and_count_trainable=True,
    teacher_distillation_used=False,selection_unchanged=True,no_downloads=True,temperature=0,
    generation_reference_count_access=False,generation_reference_prefix_access=False,native_qualification=False,
    expected_balanced_count_presentations={'1':610,'2':610,'4':610,'8':610},postfit_controls=CONTROLS,
    max_seconds_per_postfit=30,max_seconds_per_numerical_evaluation=20,full_gradient_packets_retained=False,
    optimizer_updates_only_when_deadline_allows=True,production_promotion_allowed=False)


def validate_plan(plan):
    if type(plan) is not dict or any(json.dumps(plan.get(k),sort_keys=True,allow_nan=False)!=
        json.dumps(v,sort_keys=True,allow_nan=False) for k,v in FIXED.items()):
        raise ValueError('unsupported fixed source-value training plan')


def load_helper(root,pins,relative,name):
    path=root/relative
    if hashlib.sha256(path.read_bytes()).hexdigest()!=pins.get(relative):
        raise ValueError('frozen benchmark helper differs: '+relative)
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


def historical_parity(actual,prior):
    """Unchanged-arm identity is judged on numeric states and original gates."""
    fixed=['optimizer_steps','row_presentations','valid_target_token_presentations',
        'selected_epoch','initial_weights_sha256','selected_weights_sha256','last_complete_attempt_weights_sha256',
        'count_training_row_presentations','count_training_presentations_by_class',
        'count_mean_loss_exposure_by_class','committed_count_batch_ids_sha256','stopped_reason']
    checks={key:actual[key]==prior[key] for key in fixed}
    fields=['epoch','stage','stage_epoch','optimizer_steps','learning_rate','numerical','source_count',
        'source_fidelity','accepted','rejection_reasons','selected_epoch']
    checks['validation_and_selection_history']=(len(actual['history'])==len(prior['history']) and
        all(all(a[key]==b[key] for key in fields) for a,b in zip(actual['history'],prior['history'])))
    if not all(checks.values()):
        raise ValueError('unchanged arm differs from historical control: '+','.join(k for k,v in checks.items() if not v))
    return dict(complete=True,checks=checks,scope='exact numeric state, exposure, validation and original selection; timing excluded')


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
    parent=load_helper(args.extension_root,ctx['pins'],'scripts/ops/autoencoder/benchmark_decoder_prefix_diagnostics.py','_source_value_parent')
    published,prior_runs,baseline_dedup=parent.authenticate_predecessor(manifest)
    previous=exposure.load_control_helper(args.extension_root,ctx['pins'])
    prefit_budget=exposure.derive_count_budget(ctx['stages'],ctx['rows']['train'],ctx['references']['train'],plan,previous)
    counts={r['id']:r['clause_count'] for r in ctx['references']['train']}
    source_budget=sum(stage['epochs']*sum(4*counts[i] for i in stage['training_ids']) for stage in ctx['stages'])
    require(source_budget==plan['expected_source_value_presentations_per_candidate'],'source auxiliary exposure differs')
    prefit_budget['source_value_presentations_per_candidate']=source_budget
    count_model=helpers.extension(args.extension_root,AUTO+'decoder_cardinality_experiment.py',PREFIX+'decoder_cardinality_experiment',ctx['pins'])
    helpers.extension(args.extension_root,AUTO+'long_span_cardinality_training.py',PREFIX+'long_span_cardinality_training',ctx['pins'])
    exposure_trainer=helpers.extension(args.extension_root,AUTO+'long_span_count_exposure_training.py',PREFIX+'long_span_count_exposure_training',ctx['pins'])
    value_model=helpers.extension(args.extension_root,AUTO+'source_value_decoder_experiment.py',PREFIX+'source_value_decoder_experiment',ctx['pins'])
    trainer=helpers.extension(args.extension_root,AUTO+'long_span_source_value_training.py',PREFIX+'long_span_source_value_training',ctx['pins'])
    import torch
    source_before=helpers.inventory(args.dependency_root,args.extension_root,ctx['pins'])
    args.output.mkdir(parents=True)
    save(args.output/'sealed-recipe.json',dict(plan=plan,manifest=manifest,prefit_budget=prefit_budget,tree_pin=ctx['tree'],selected_baseline_deduplication=baseline_dedup,**FALSE))
    lineage=dict(ctx['lineage'])

    def evaluate(model, split, control):
        evaluation_started=time.monotonic()
        actual=ctx['rows'][split]
        scope=previous.control_scope(control)
        execution=dict(kind=control,source_assignment={row['id']:row['id'] for row in actual})
        if control=='source_shuffle':
            actual,execution=helpers.shuffle_inputs(actual,ctx['references'][split])
        elif control=='zero_condition':
            model=(value_model.bind_zero_condition_model(model) if callable(getattr(model,'source_value_logits',None))
                else count_model.bind_zero_condition_model(model))
            scope['diagnostic_scope']='remove initial, persistent, count and optional source-value features; learned head biases remain'
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
        value['hypothetical_boundary_diagnostics']=exposure.hypothetical_boundary_diagnostics(value['source_count'])
        value['source_values']=None
        if callable(getattr(model,'source_value_logits',None)):
            labels=value_model.reference_source_values(actual,ctx['references'][split],ctx['donor']['codec'],validate_rule=ctx['validate_rule'])
            value['source_values']=trainer._source_value_evaluation(torch,model,actual,labels,ctx['donor']['input_transform'],
                dict(batch_size=8),ctx['donor']['codec'],deadline)
            require(value['source_values'] is not None,'incomplete source-value readout')
        require(time.monotonic()<deadline,'postfit deadline exceeded')
        value['execution']={**execution,'training_performed':False,'selection_performed':False,
            'provenance_breaking_negative_control':control=='source_shuffle',**scope}
        value['timing']=dict(postfit_evaluation_elapsed_seconds=time.monotonic()-evaluation_started,
            numerical_api_elapsed_seconds=value['report']['elapsed_seconds'],
            scope='control construction, numerical readout, source-fidelity scoring, source-count and source-value evaluation and hypothetical boundary diagnostics; excludes output file write')
        return value

    summaries=[];initial_digest=None
    for seed in plan['seed_order']:
        for recipe in plan['arms']:
            arm_started=time.monotonic()
            name=recipe['name']+'-'+str(seed)
            persistent=ctx['adapter'].bind_persistent_model(ctx['base_model'].body,dimension=384,conditioning='every_step')
            for parameter_name,parameter in persistent.named_parameters():
                if parameter_name.startswith(('body.projection_down.','body.projection_up.')):
                    parameter.requires_grad_(False)
            model=count_model.bind_cardinality_model(persistent,codec=ctx['donor']['codec'],guide_boundary=recipe['guide_boundary'])
            digest=core.tensor_digest(model)
            if initial_digest is None:initial_digest=digest
            require(digest==initial_digest,'initial parameter tensors differ between arms')
            require(digest==baseline_dedup['tensor_sha256'],'initial cardinality model differs from historical selected baseline')
            inherited_digest=digest
            if recipe['feature_kind'] is not None:
                model=value_model.bind_source_value_model(model,codec=ctx['donor']['codec'],feature_kind=recipe['feature_kind'],max_rules=8,guidance=True)
                require(core.tensor_digest(model.body)==inherited_digest,'new head binding changed inherited tensors')
            lineage['student_lineage']='source_value_v1:'+name
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
                values={k:v.tolist() for k,v in model.state_dict().items()}
                receipt=save(folder/(role+'-state.json'),dict(schema='private-source-value-state/v1',recipe=recipe,
                    architecture=model.describe(),lineage=dict(lineage),codec=ctx['donor']['codec'],model_state=values,
                    weights_sha256=core.digest(values),tensor_sha256=core.tensor_digest(model),role=role,
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
                and report['valid_target_token_presentations']==prefit_budget['valid_target_token_presentations']
                and report['stopped_reason']=='epochs_completed'
                and report['count_training_row_presentations']==prefit_budget['count_presentations']
                and report['source_value_presentations']==(source_budget if recipe['source_value_weight'] else 0))
            if completed:
                exposure.validate_completed_exposure(report,prefit_budget,recipe)
            parity=None
            if recipe['name']=='unchanged' and completed:
                parity=historical_parity(report,prior_runs['unchanged-'+str(seed)]['training'])
            summary=dict(arm=name,recipe=recipe,seed=seed,budget_completed=completed,training=report,postfit=postfit,
                initial_inherited_tensor_sha256=inherited_digest,historical_parity=parity,
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
    save(args.output/'summary.json',dict(schema='decoder-source-value-training-comparison/v1',runs=summaries,
        complete=len(summaries)==6 and all(x['budget_completed'] for x in summaries),source_dependencies=after,
        dimensions_actually_trained=[384],training_executed=any(x['training']['optimizer_steps']>0 for x in summaries),
        workers=1,bridge_names=[],legal_ir_evaluate_provers=False,metric_disk_cache_used=False,
        paragraph_embedding_cache_used=True,encoder_executed=False,encoder_context_changed=False,
        output_limit_changed=False,downloads_performed=False,**FALSE))


if __name__=='__main__':
    main()
