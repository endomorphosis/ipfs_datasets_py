#!/usr/bin/env python3
"""Paired training-only count exposure; unchanged decoder curriculum and gates."""
import argparse
import hashlib
import importlib.util
import json
import math
from fractions import Fraction
from pathlib import Path
import sys
import time

AUTO = 'ipfs_datasets_py/logic/formalization/autoencoder/'
PREFIX = 'ipfs_datasets_py.logic.formalization.autoencoder.'
FALSE = dict(qualified=False, admitted=False, proof_authority=False, source_semantics_verified=False,
    checkpoint_promoted=False, convergence_proven=False, fresh_holdout=False,
    lake_executed=False, formalized=False, roundtrip_ok=False)


def validate_plan(plan):
    fixed = dict(schema='decoder-count-exposure-plan/v1',representation_dimension=384,
        arms=[dict(name='current_stage',count_exposure='current_stage',guide_boundary=False,cardinality_weight=.25),
              dict(name='balanced_all',count_exposure='balanced_all',guide_boundary=False,cardinality_weight=.25)],
        seed_order=[1729,2718],conditioning='every_step',loss='semantic_fields',epochs_per_source_stage=20,
        expected_optimizer_steps_per_arm=340,expected_training_token_presentations_per_arm=225840,
        expected_count_presentations_per_arm=2440,
        batch_size=8,learning_rate=.001,max_seconds_per_arm=60,validation_interval=4,
        fixed_encoder_context_tokens=512,fixed_decoder_output_limit=512,projection_frozen=True,
        teacher_distillation_used=False,selection_unchanged=True,no_downloads=True,
        generation_reference_count_access=False,native_qualification=False)
    if type(plan) is not dict or any(json.dumps(plan.get(k),sort_keys=True,allow_nan=False)!=
            json.dumps(v,sort_keys=True,allow_nan=False) for k,v in fixed.items()):
        raise ValueError('unsupported count exposure experiment plan')


def load_control_helper(extension_root, pins):
    relative='scripts/ops/autoencoder/benchmark_decoder_cardinality.py'
    path=extension_root/relative
    if hashlib.sha256(path.read_bytes()).hexdigest()!=pins.get(relative):
        raise ValueError('frozen cardinality budget helper differs')
    spec=importlib.util.spec_from_file_location('_count_exposure_budget',path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


def derive_count_budget(stages, training_rows, references, plan, previous):
    result=previous.derive_budget(stages,training_rows,plan)
    def require(condition,reason):
        if not condition:raise ValueError(reason)
    by_id={row['id']:row for row in training_rows}
    require(type(references) is list and len(references)==len(by_id), 'complete training count references required')
    counts={}
    for row in references:
        require(type(row) is dict and row.get('id') in by_id and row['id'] not in counts,
            'unique bound training count references required')
        count=row.get('clause_count')
        require(type(count) is int and 1<=count<=32, 'bounded exact training clause counts required')
        counts[row['id']]=count
    total=result['row_presentations']
    require(total==plan['expected_count_presentations_per_arm'],
        'derived count presentation budget differs from sealed plan')
    exposure={count:0 for count in sorted(set(counts.values()))}
    for stage in stages:
        for identity in stage['training_ids']:exposure[counts[identity]]+=stage['epochs']
    require(set(exposure)=={1,2,4,8}, 'original four count classes required')
    require(total%len(exposure)==0, 'exact class-balanced total required')
    classes=sorted(exposure);cursor=0
    loss_mass={key:Fraction(0) for key in classes}
    for stage in stages:
        for _ in range(stage['epochs']):
            for offset in range(0,len(stage['training_ids']),plan['batch_size']):
                size=min(plan['batch_size'],len(stage['training_ids'])-offset)
                for _ in range(size):
                    loss_mass[classes[cursor]]+=Fraction(1,size)
                    cursor=(cursor+1)%len(classes)
    require(sum(loss_mass.values())==result['optimizer_steps'],
        'balanced inverse-batch count exposure differs from optimizer budget')
    return {**result,'schema':'count-exposure-prefit-budget/v1','count_presentations':total,
        'current_stage_count_presentations_by_class':exposure,
        'balanced_all_count_presentations_by_class':{key:total//len(exposure) for key in exposure},
        'balanced_all_count_inverse_batch_mass_by_class':{key:float(value) for key,value in loss_mass.items()},
        'inverse_batch_mass_scope':'sum1/actual_count_minibatch_size per presented row; class cursor persists across all batches, epochs and stages; excludes auxiliary loss coefficient',
        'count_examples_per_update':'same as actual decoder minibatch, including partial batches',
        'balanced_gradient_scope':'all-length training-only auxiliary sources update shared conditioner and count head; decoder-token rows keep their original curriculum'}


def validate_completed_exposure(report, budget, recipe):
    expected=budget[recipe['count_exposure']+'_count_presentations_by_class']
    if report.get('count_training_presentations_by_class')!={str(key):value for key,value in expected.items()}:
        raise ValueError('actual count class exposure differs from prefit plan')
    if recipe['count_exposure']=='balanced_all':
        expected_mass=budget['balanced_all_count_inverse_batch_mass_by_class']
        actual=report.get('count_mean_loss_exposure_by_class')
        if type(actual) is not dict or set(actual)!={str(key) for key in expected_mass} or any(
                type(actual[str(key)]) not in (int,float) or not math.isfinite(actual[str(key)]) or
                not math.isclose(actual[str(key)],mass,rel_tol=0.,abs_tol=1e-10)
                for key,mass in expected_mass.items()):
            raise ValueError('actual count inverse-batch loss exposure differs from prefit plan')


def hypothetical_boundary_diagnostics(source_count):
    """Inspect the count distribution without applying guidance or parsing generated boundaries."""
    rows=source_count.get('predictions')
    if type(rows) is not list or not rows:
        raise ValueError('count probability predictions required for boundary diagnostics')
    result=[];seen=set()
    for row in rows:
        identity=row.get('id');probabilities=row.get('probabilities')
        if not isinstance(identity,str) or not identity or identity in seen:
            raise ValueError('unique count probability IDs required')
        seen.add(identity)
        if type(probabilities) is not list or len(probabilities)!=32 or any(
                type(p) not in (int,float) or not math.isfinite(p) or p<0 or p>1 for p in probabilities):
            raise ValueError('32 finite count probabilities required')
        if not math.isclose(sum(probabilities),1.,abs_tol=1e-5,rel_tol=0.):
            raise ValueError('normalized count probabilities required')
        values={}
        for k in (1,2,4,8):
            selected=probabilities[k-1];tail=sum(probabilities[k:])
            valid=selected>0 and tail>0
            values[str(k)]=dict(stop_probability=selected,continuation_probability=tail,
                hypothetical_logit_correction=math.log(selected)-math.log(tail)+math.log(32-k) if valid else None,
                finite=valid,undefined_reason=None if valid else 'zero probability from numerical support')
        result.append(dict(id=identity,boundaries=values))
    return dict(schema='hypothetical-count-boundary-diagnostics/v1',guidance_enabled=False,
        applied_to_generation=False,observed_generation_boundaries=False,
        reference_clause_count_used=False,uniform_reference_count_classes=32,
        formula='log p(k) - log sum_{j>k} p(j) + log(32-k)',
        scope='fixed hypothetical k=1,2,4,8 evaluated on source-head probabilities; not actual generated-prefix decisions',
        rows=result)


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
    previous=load_control_helper(args.extension_root,ctx['pins'])
    prefit_budget=derive_count_budget(ctx['stages'],ctx['rows']['train'],ctx['references']['train'],plan,previous)
    count_model=helpers.extension(args.extension_root,AUTO+'decoder_cardinality_experiment.py',PREFIX+'decoder_cardinality_experiment',ctx['pins'])
    helpers.extension(args.extension_root,AUTO+'long_span_cardinality_training.py',PREFIX+'long_span_cardinality_training',ctx['pins'])
    trainer=helpers.extension(args.extension_root,AUTO+'long_span_count_exposure_training.py',PREFIX+'long_span_count_exposure_training',ctx['pins'])
    import torch
    source_before=helpers.inventory(args.dependency_root,args.extension_root,ctx['pins'])
    args.output.mkdir(parents=True)
    save(args.output/'sealed-recipe.json',dict(plan=plan,manifest=manifest,prefit_budget=prefit_budget,tree_pin=ctx['tree'],**FALSE))
    lineage=dict(ctx['lineage'])

    def evaluate(model, split, control):
        evaluation_started=time.monotonic()
        actual=ctx['rows'][split]
        scope=previous.control_scope(control)
        execution=dict(kind=control,source_assignment={row['id']:row['id'] for row in actual})
        if control=='source_shuffle':
            actual,execution=helpers.shuffle_inputs(actual,ctx['references'][split])
        elif control=='zero_condition':
            model=count_model.bind_zero_condition_model(model)
        deadline=time.monotonic()+30
        value=core.evaluate_model(model,actual,codec=ctx['donor']['codec'],input_transform=ctx['donor']['input_transform'],
            lineage=lineage,max_target_tokens=512,max_seconds=20,batch_size=8)
        require(value['report']['complete'],'incomplete postfit evaluation')
        value['source_fidelity']=ctx['scorer'].score_predictions(ctx['references'][split],value['predictions'],
            codec=ctx['donor']['codec'],validate_rule=ctx['validate_rule'],validator_id=ctx['validator_id'],output_limit=512,
            control={k:execution[k] for k in ('kind','source_assignment')})
        value['source_count']=trainer._count_evaluation(torch,model,actual,ctx['references'][split],
            ctx['donor']['input_transform'],dict(batch_size=8),deadline)
        require(value['source_count'] is not None,'incomplete postfit count evaluation')
        value['hypothetical_boundary_diagnostics']=hypothetical_boundary_diagnostics(value['source_count'])
        value['execution']={**execution,'training_performed':False,'selection_performed':False,
            'provenance_breaking_negative_control':control=='source_shuffle',**scope}
        value['timing']=dict(postfit_evaluation_elapsed_seconds=time.monotonic()-evaluation_started,
            numerical_api_elapsed_seconds=value['report']['elapsed_seconds'],
            scope='control construction, numerical readout, source-fidelity scoring, source-count evaluation and hypothetical boundary diagnostics; excludes output file write')
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
            lineage['student_lineage']='count_exposure_v1:'+name
            training_started=time.monotonic()
            result=trainer.train(model,ctx['rows']['train'],ctx['rows']['validation'],
                training_references=ctx['references']['train'],validation_references=ctx['references']['validation'],
                codec=ctx['donor']['codec'],input_transform=ctx['donor']['input_transform'],lineage=lineage,
                validate_rule=ctx['validate_rule'],validator_id=ctx['validator_id'],curriculum=ctx['stages'],
                strategy='semantic_fields',cardinality_weight=recipe['cardinality_weight'],count_exposure=recipe['count_exposure'],
                config=dict(seed=seed,max_seconds=60,max_target_tokens=512,batch_size=8,learning_rate=.001,
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
                receipt=save(folder/(role+'-state.json'),dict(schema='private-count-exposure-state/v1',recipe=recipe,
                    architecture=model.describe(),lineage=dict(lineage),codec=ctx['donor']['codec'],model_state=values,
                    weights_sha256=core.digest(values),tensor_sha256=core.tensor_digest(model),role=role,
                    selected=role=='selected' or report['last_complete_attempt_is_selected'],optimizer_resumable=False,**FALSE))
                persisted=json.loads(Path(receipt['path']).read_bytes())
                require(core.digest(persisted['model_state'])==persisted['weights_sha256'],'private state JSON digest differs')
                model.load_state_dict({k:ctx['numerical']._tensor(persisted['model_state'][k],v,k)
                    for k,v in model.state_dict().items()},strict=True)
                require(core.tensor_digest(model)==persisted['tensor_sha256']==expected_digest,'private reload tensor digest differs')
                postfit[role]={}
                for label,split,control in [('validation','validation','conditioned'),('training','train','conditioned'),
                        ('zero-condition','validation','zero_condition'),('source-shuffle','validation','source_shuffle'),
                        ('training-source-shuffle','train','source_shuffle')]:
                    value=evaluate(model,split,control)
                    if label=='validation':require(value['predictions']==predictions,'saved state generation mismatch')
                    save(folder/role/('evaluation-'+label+'.json'),value)
                    postfit[role][label]=dict(numerical=value['report'],source_count=value['source_count'],
                        timing=value['timing'],execution=value['execution'],
                        hypothetical_boundary_diagnostics=value['hypothetical_boundary_diagnostics'],
                        source_fidelity={k:v for k,v in value['source_fidelity'].items() if k!='rows'})
            postfit_elapsed_seconds=time.monotonic()-postfit_started
            completed=(report['optimizer_steps']==prefit_budget['optimizer_steps']
                and report['valid_target_token_presentations']==prefit_budget['valid_target_token_presentations']
                and report['stopped_reason']=='epochs_completed'
                and report['count_training_row_presentations']==prefit_budget['count_presentations'])
            if completed:
                validate_completed_exposure(report,prefit_budget,recipe)
            summary=dict(arm=name,recipe=recipe,seed=seed,budget_completed=completed,training=report,postfit=postfit,
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
                last_exact=last['fidelity']['metrics']['ordered_exact'] if last else None,
                last_eos=last['fidelity']['metrics']['eos_count'] if last else None)),flush=True)
    after=helpers.inventory(args.dependency_root,args.extension_root,ctx['pins'])
    require(all(after.get(path)==expected for path,expected in source_before.items()),'loaded source changed')
    helpers.validate_manifest_inputs(manifest)
    for path,expected in ctx['pins'].items():require(helpers.sha(args.extension_root/path)==expected,'frozen extension changed')
    require(helpers.sha(args.plan)==manifest['plan_sha256'],'sealed plan changed')
    save(args.output/'summary.json',dict(schema='decoder-count-exposure-comparison/v1',runs=summaries,
        complete=len(summaries)==4 and all(x['budget_completed'] for x in summaries),source_dependencies=after,
        dimensions_actually_trained=[384],training_executed=any(x['training']['optimizer_steps']>0 for x in summaries),
        workers=1,bridge_names=[],legal_ir_evaluate_provers=False,metric_disk_cache_used=False,
        paragraph_embedding_cache_used=True,encoder_executed=False,encoder_context_changed=False,
        output_limit_changed=False,downloads_performed=False,**FALSE))


if __name__=='__main__':
    main()
