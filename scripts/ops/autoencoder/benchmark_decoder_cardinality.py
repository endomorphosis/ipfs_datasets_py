#!/usr/bin/env python3
"""Matched reference-supervised source-count ablation; development evidence only."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

AUTO = 'ipfs_datasets_py/logic/formalization/autoencoder/'
PREFIX = 'ipfs_datasets_py.logic.formalization.autoencoder.'
FALSE = dict(qualified=False, admitted=False, proof_authority=False, source_semantics_verified=False,
    checkpoint_promoted=False, convergence_proven=False, fresh_holdout=False,
    lake_executed=False, formalized=False, roundtrip_ok=False)


def validate_plan(plan):
    fixed = dict(schema='decoder-cardinality-ablation-plan/v1',representation_dimension=384,
        arms=[dict(name='no_count',guide_boundary=False,cardinality_weight=0.),
              dict(name='aux_count',guide_boundary=False,cardinality_weight=.25),
              dict(name='guided_count',guide_boundary=True,cardinality_weight=.25)],
        seed_order=[1729,2718],conditioning='every_step',loss='semantic_fields',epochs_per_source_stage=20,
        expected_optimizer_steps_per_arm=340,expected_training_token_presentations_per_arm=225840,
        batch_size=8,learning_rate=.001,max_seconds_per_arm=60,validation_interval=4,
        fixed_encoder_context_tokens=512,fixed_decoder_output_limit=512,projection_frozen=True,
        teacher_distillation_used=False,selection_unchanged=True,no_downloads=True,
        generation_reference_count_access=False,native_qualification=False)
    if type(plan) is not dict or any(json.dumps(plan.get(k),sort_keys=True,allow_nan=False)!=
            json.dumps(v,sort_keys=True,allow_nan=False) for k,v in fixed.items()):
        raise ValueError('unsupported cardinality experiment plan')


def derive_budget(stages, training_rows, plan):
    """Check the replayed curriculum's work before running any training arm."""
    def require(condition, reason):
        if not condition:
            raise ValueError(reason)
    require(type(training_rows) is list and 1 <= len(training_rows) <= 4096,
            'bounded nonempty training rows required for budget derivation')
    require(type(stages) is list and 1 <= len(stages) <= 16,
            'bounded nonempty source curriculum required for budget derivation')
    batch_size, expected_epochs = plan['batch_size'], plan['epochs_per_source_stage']
    require(type(batch_size) is int and batch_size > 0 and type(expected_epochs) is int and expected_epochs > 0,
            'exact positive batch and stage epoch counts required')
    rows = {}
    for row in training_rows:
        require(type(row) is dict and type(row.get('id')) is str and row['id'] and row['id'] not in rows,
                'unique bound training IDs required for budget derivation')
        target = row.get('target_ids')
        require(type(target) is list and 3 <= len(target) <= plan['fixed_decoder_output_limit']
                and target[0] == 1 and target[-1] == 2 and all(type(token) is int for token in target)
                and all(token >= 3 for token in target[1:-1]),
                'complete untruncated target IDs required for budget derivation')
        rows[row['id']] = row
    previous, names, details = set(), set(), []
    for stage in stages:
        require(type(stage) is dict and set(stage) == {'name', 'training_ids', 'epochs'},
                'closed source stage required for budget derivation')
        require(type(stage['name']) is str and stage['name'] and stage['name'] not in names,
                'unique source stage name required')
        names.add(stage['name'])
        ids = stage['training_ids']
        require(type(ids) is list and ids and all(type(identity) is str and identity in rows for identity in ids)
                and len(set(ids)) == len(ids), 'source stage must reference unique existing training IDs')
        require(previous <= set(ids), 'source curriculum must retain previous training IDs')
        require(type(stage['epochs']) is int and stage['epochs'] == expected_epochs,
                'source stage epoch budget differs from sealed plan')
        previous = set(ids)
        updates_per_epoch = (len(ids) + batch_size - 1)//batch_size
        tokens_per_epoch = sum(len(rows[identity]['target_ids']) - 1 for identity in ids)
        details.append(dict(name=stage['name'], training_rows=len(ids), epochs=stage['epochs'],
            optimizer_steps=stage['epochs']*updates_per_epoch,
            valid_target_token_presentations=stage['epochs']*tokens_per_epoch,
            row_presentations=stage['epochs']*len(ids)))
    require(previous == set(rows), 'final source stage must include all training IDs')
    steps = sum(stage['optimizer_steps'] for stage in details)
    tokens = sum(stage['valid_target_token_presentations'] for stage in details)
    require(steps == plan['expected_optimizer_steps_per_arm'],
            'derived optimizer update budget differs from sealed plan')
    require(tokens == plan['expected_training_token_presentations_per_arm'],
            'derived target token presentation budget differs from sealed plan')
    return dict(schema='cardinality-prefit-budget/v1', optimizer_steps=steps,
        valid_target_token_presentations=tokens, row_presentations=sum(stage['row_presentations'] for stage in details),
        stages=details, token_scope='complete target includes EOS, excludes BOS and batch padding',
        training_executed=False, deadline_completion_guaranteed=False)


def control_scope(kind):
    if kind not in ('conditioned', 'zero_condition', 'source_shuffle'):
        raise ValueError('unsupported cardinality evaluation control')
    return dict(shuffle_preserves_reference_clause_count=kind == 'source_shuffle',
        independent_count_generalization_test=False,
        diagnostic_scope={'conditioned': 'ordinary fixed-state source-conditioned readout',
            'zero_condition': 'remove decoder and count-head source features; learned count bias remains',
            'source_shuffle': 'within-clause-count source-fidelity control; count labels deliberately preserved'}[kind])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('dependency-root','extension-root','manifest','plan','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    manifest=json.loads(args.manifest.read_bytes())
    helper_path=args.extension_root/'scripts/ops/autoencoder/decoder_fidelity_replay.py'
    if hashlib.sha256(helper_path.read_bytes()).hexdigest()!=manifest['extensions'].get('scripts/ops/autoencoder/decoder_fidelity_replay.py'):
        raise ValueError('frozen replay helper differs')
    spec=importlib.util.spec_from_file_location('_cardinality_replay',helper_path)
    replay=importlib.util.module_from_spec(spec);spec.loader.exec_module(replay)
    ctx=replay.load_context(args,validate_plan=validate_plan)
    helpers,core,plan=ctx['helpers'],ctx['core'],ctx['plan']
    require,save=helpers.require,helpers.save
    prefit_budget=derive_budget(ctx['stages'],ctx['rows']['train'],plan)
    count_model=helpers.extension(args.extension_root,AUTO+'decoder_cardinality_experiment.py',PREFIX+'decoder_cardinality_experiment',ctx['pins'])
    trainer=helpers.extension(args.extension_root,AUTO+'long_span_cardinality_training.py',PREFIX+'long_span_cardinality_training',ctx['pins'])
    import torch
    source_before=helpers.inventory(args.dependency_root,args.extension_root,ctx['pins'])
    args.output.mkdir(parents=True)
    save(args.output/'sealed-recipe.json',dict(plan=plan,manifest=manifest,prefit_budget=prefit_budget,tree_pin=ctx['tree'],**FALSE))
    lineage=dict(ctx['lineage'])

    def evaluate(model, split, control):
        evaluation_started=time.monotonic()
        actual=ctx['rows'][split]
        scope=control_scope(control)
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
        value['execution']={**execution,'training_performed':False,'selection_performed':False,
            'provenance_breaking_negative_control':control=='source_shuffle',**scope}
        value['timing']=dict(postfit_evaluation_elapsed_seconds=time.monotonic()-evaluation_started,
            numerical_api_elapsed_seconds=value['report']['elapsed_seconds'],
            scope='control construction, numerical readout, source-fidelity scoring and source-count evaluation; excludes output file write')
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
            lineage['student_lineage']='cardinality_v1:'+name
            training_started=time.monotonic()
            result=trainer.train(model,ctx['rows']['train'],ctx['rows']['validation'],
                training_references=ctx['references']['train'],validation_references=ctx['references']['validation'],
                codec=ctx['donor']['codec'],input_transform=ctx['donor']['input_transform'],lineage=lineage,
                validate_rule=ctx['validate_rule'],validator_id=ctx['validator_id'],curriculum=ctx['stages'],
                strategy='semantic_fields',cardinality_weight=recipe['cardinality_weight'],
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
                receipt=save(folder/(role+'-state.json'),dict(schema='private-cardinality-state/v1',recipe=recipe,
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
                        ('zero-condition','validation','zero_condition'),('source-shuffle','validation','source_shuffle')]:
                    value=evaluate(model,split,control)
                    if label=='validation':require(value['predictions']==predictions,'saved state generation mismatch')
                    save(folder/role/('evaluation-'+label+'.json'),value)
                    postfit[role][label]=dict(numerical=value['report'],source_count=value['source_count'],
                        timing=value['timing'],execution=value['execution'],
                        source_fidelity={k:v for k,v in value['source_fidelity'].items() if k!='rows'})
            postfit_elapsed_seconds=time.monotonic()-postfit_started
            completed=(report['optimizer_steps']==prefit_budget['optimizer_steps']
                and report['valid_target_token_presentations']==prefit_budget['valid_target_token_presentations']
                and report['stopped_reason']=='epochs_completed')
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
    save(args.output/'summary.json',dict(schema='decoder-cardinality-comparison/v1',runs=summaries,
        complete=len(summaries)==6 and all(x['budget_completed'] for x in summaries),source_dependencies=after,
        dimensions_actually_trained=[384],training_executed=any(x['training']['optimizer_steps']>0 for x in summaries),
        workers=1,bridge_names=[],legal_ir_evaluate_provers=False,metric_disk_cache_used=False,
        paragraph_embedding_cache_used=True,encoder_executed=False,encoder_context_changed=False,
        output_limit_changed=False,downloads_performed=False,**FALSE))


if __name__=='__main__':
    main()
