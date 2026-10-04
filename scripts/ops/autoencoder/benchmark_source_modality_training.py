#!/usr/bin/env python3
"""Six matched384D fits with auxiliary supervision from existing training sources.

The formerly fresh R6 cohort is an exposed regression set. No result in this
private formula-sidecar experiment grants qualification or Lake admission.
"""
import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import traceback
from types import SimpleNamespace
import time

AUTO = 'ipfs_datasets_py/logic/formalization/autoencoder/'
PREFIX = 'ipfs_datasets_py.logic.formalization.autoencoder.'
TRAINER = AUTO+'long_span_source_value_training.py'
HELPER = AUTO+'source_modality_auxiliary_training.py'
PARENT_RUNNER = 'scripts/ops/autoencoder/benchmark_source_margin_training.py'
EVALUATOR = 'scripts/ops/autoencoder/evaluate_source_margin_holdout.py'
FALSE = dict(qualified=False, admitted=False, proof_authority=False,
    source_semantics_verified=False, checkpoint_promoted=False, convergence_proven=False,
    fresh_holdout=False, fresh_authored_holdout=False, lake_executed=False,
    native_validation_executed=False, formalized=False, roundtrip_ok=False)
ARMS = [dict(name='source-head-lr10', bank_kind=None, auxiliary_source_modality_weight=0.,generated_boundary_retry_on_mismatch=False),
    dict(name='aux-used113', bank_kind='used113', auxiliary_source_modality_weight=.05,generated_boundary_retry_on_mismatch=True),
    dict(name='aux-full180', bank_kind='full180', auxiliary_source_modality_weight=.05,generated_boundary_retry_on_mismatch=True)]
CONTROLS = [['validation','validation','conditioned'], ['training','train','conditioned'],
    ['zero-condition','validation','zero_condition'], ['source-shuffle','validation','source_shuffle'],
    ['cross-length-shuffle','validation','cross_length_shuffle'],
    ['context-only-shuffle','validation','context_only_shuffle'],
    ['context-reverse','validation','context_reverse'], ['context-rotate','validation','context_rotate']]
ROLES = ['selected','last-attempt']
FIXED = dict(schema='source-modality-training-plan/v1', dimensions=[384], seed_order=[1729,2718],
    arms=ARMS, fit_count=6, original_training_rows=48, exposed_validation_rows=48,
    original_training_clause_occurrences=180, original_used_training_clauses=113,
    original_available_training_clauses=180, auxiliary_batch_size=6,
    auxiliary_strata=['O:0','O:1','P:0','P:1','F:0','F:1'],
    auxiliary_examples_per_stratum_per_update=1, auxiliary_positive_presentations_per_fit=2040,
    auxiliary_field='modality', auxiliary_full_vocabulary_size=32,
    auxiliary_normalization='mean_six_full_vocabulary_cross_entropies',
    auxiliary_source_only_head=True, auxiliary_extra_decoder_rollouts=0,
    auxiliary_sampler_uses_decoder_rng=False, auxiliary_used_for_selection=False,
    boundary_retry_positive_arms_only=True, boundary_retry_limit_per_original_batch=1,
    boundary_replay_atol=2e-5,boundary_replay_rtol=2e-5,
    boundary_replay_policy='bulk_parity_precheck;on_mismatch_original_batch_causal_incremental_retry;unchanged_tolerance',
    boundary_replay_actual_argmax_prefixes_only=True,boundary_replay_reference_prefixes_used=False,
    baseline_boundary_retry_flag_omitted=True,
    contextual_boundary_producer='revised_canonical_module;baseline_default_branch_unchanged',
    auxiliary_bank_prepared_once=True, clause_normalization_refitted=False,
    positive_comparison='aux-full180_vs_aux-used113',
    training_data_scope='original48paragraphs_unchanged;positive_arms_add_declared_auxiliary_training_sources',
    foundation='source-head-lr10', generated_source_margin_weight=0., generated_source_margin_replay=False,
    generated_field_weight=0., joint_generated_replay=False,
    non_action_learning_rate_multiplier=10., learning_rate=.001, batch_size=8,
    epochs_per_source_stage=20, validation_interval=4, expected_optimizer_steps_per_arm=340,
    expected_training_token_presentations_per_arm=225840, expected_row_presentations_per_arm=2440,
    expected_count_presentations_per_arm=2440, expected_source_value_presentations_per_arm=25600,
    expected_balanced_count_presentations={'1':610,'2':610,'4':610,'8':610},
    cardinality_weight=.25, source_value_weight=.25, action_contrastive_weight=.05,
    generated_boundary_weight=.05, generated_boundary_site_policy='first_last',
    fixed_encoder_context_tokens=512, fixed_decoder_output_limit=512, temperature=0,
    fresh_initialization=True, selection_unchanged=True, full_vocabulary_retained=True,
    syntax_forced=False, closure_forced=False, production_promotion_allowed=False,
    historical_linguistic_teacher_modified=False, teacher_distillation_used=False,
    identity_projection_frozen=True, identity_mse_is_not_learned_reconstruction=True,
    architecture_changed=False, baseline_replay_required=True,
    baseline_equivalence_exclusions=['elapsed_seconds','committed_updates[*].generated_boundary.elapsed_seconds',
        'committed_updates[*].generated_boundary.generation.elapsed_seconds',
        'committed_updates[*].generated_boundary.collection_sha256'],
    postfit_controls=CONTROLS, additional_candidate_control='recurrent-residual-off',
    exposed_r6_rows=48, exposed_r6_panel_count=12, exposed_r6_roles=ROLES,
    exposed_r6_role='previously_exposed_postfit_regression;not_selection_or_fresh_holdout',
    all_exposed_predictions_before_reference_load=True, exposed_generation_reference_access=False,
    max_seconds_per_arm=180, max_seconds_per_postfit=30, max_seconds_entire_run=1500,
    baseline_memory_bytes=1073741824, positive_memory_bytes=1073741824,
    workers=1, bridge_names=[], legal_ir_evaluate_provers=False, metric_disk_cache_used=False,
    no_downloads=True, encoder_executed_during_training=False)


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1048576), b''):
            value.update(block)
    return value.hexdigest()


def validate_plan(plan):
    require(type(plan) is dict and all(type(plan.get(key)) is type(value)
        and json.dumps(plan[key],sort_keys=True,allow_nan=False)==json.dumps(value,sort_keys=True,allow_nan=False)
        for key,value in FIXED.items()), 'fixed source-modality comparison differs')


def jobs():
    return [(384,seed,deepcopy(arm)) for seed in FIXED['seed_order'] for arm in ARMS]


def bound_json(manifest, path, expected=None):
    path=Path(path).resolve(); wanted=manifest['inputs'].get(str(path))
    require(wanted is not None and (expected is None or wanted==expected), 'unbound artifact: '+str(path))
    data=path.read_bytes()
    require(hashlib.sha256(data).hexdigest()==wanted, 'sealed artifact differs: '+str(path))
    return json.loads(data)


def load_helper(root, pins, path, name):
    require(sha(root/path)==pins.get(path), 'frozen helper differs: '+path)
    spec=importlib.util.spec_from_file_location(name,root/path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def source_inventory(args, ctx):
    """Authenticate the deliberately separate old and new package snapshots."""
    roots=[('dependency',args.dependency_root.resolve(),None),
        ('parent_extension',Path(ctx['manifest']['parent_extension_root']).resolve(),ctx['parent_manifest']['extensions']),
        ('extension',args.extension_root.resolve(),ctx['pins'])]
    result={}
    for name,module in list(sys.modules.items()):
        if name!='ipfs_datasets_py' and not name.startswith('ipfs_datasets_py.'):
            continue
        filename=getattr(module,'__file__',None)
        if filename is None:
            continue
        path=Path(filename).resolve()
        require(path.is_file() and path.suffix=='.py', 'unbound package source')
        matches=[(scope,root,pins) for scope,root,pins in roots if path.is_relative_to(root)]
        require(len(matches)==1, 'package source outside isolated roots: '+str(path))
        scope,root,pins=matches[0]; relative=str(path.relative_to(root)); digest=sha(path)
        require(pins is None or pins.get(relative)==digest, 'unregistered package source: '+str(path))
        result[scope+':'+relative]=digest
    return result


def load_intervention_extensions(ctx, parent_root, extension_root, parent_pins, pins):
    """Explicit closure; the canonical historical trainer remains authenticated."""
    h=ctx['helpers']
    ctx['owners']['authored_scalar_holdout']=h.extension(parent_root,AUTO+'authored_scalar_holdout.py',
        PREFIX+'authored_scalar_holdout',parent_pins)
    helper=h.extension(extension_root,HELPER,PREFIX+'source_modality_auxiliary_training',pins)
    trainer=h.extension(extension_root,TRAINER,PREFIX+'_source_modality_training_owner',pins)
    ctx['owners'].update(source_modality_auxiliary_training=helper,long_span_source_value_training=trainer)


def load_context(args):
    manifest=json.loads(args.manifest.read_bytes()); plan=json.loads(args.plan.read_bytes()); validate_plan(plan)
    require(sha(args.plan)==manifest['plan_sha256'] and plan['input_sha256']==manifest['inputs'], 'sealed plan differs')
    for path,digest in manifest['inputs'].items():
        require(sha(path)==digest, 'sealed input changed: '+path)
    parent=bound_json(manifest,manifest['parent_manifest'])
    parent_plan=bound_json(manifest,manifest['parent_plan'])
    require(sha(manifest['parent_plan'])==parent['plan_sha256'], 'parent training plan differs')
    parent_root=Path(manifest['parent_extension_root'])
    for relative,digest in parent['extensions'].items():
        require(sha(parent_root/relative)==digest, 'parent producer changed: '+relative)
    prior=load_helper(parent_root,parent['extensions'],PARENT_RUNNER,'_modality_prior_margin_runner')
    prior.validate_plan(parent_plan)
    native=load_helper(parent_root,parent['extensions'],
        'scripts/ops/autoencoder/benchmark_native_dimension_source_training.py','_modality_native_runner')
    oldargs=SimpleNamespace(**vars(args)); oldargs.extension_root=parent_root
    oldargs.manifest=Path(parent['parent_manifest']); oldargs.plan=Path(parent['parent_plan'])
    bound_json(manifest,oldargs.manifest); bound_json(manifest,oldargs.plan)
    ctx=native.load_context(oldargs)
    for name in ('action_factorized_clause_decoder_experiment','action_contrastive_decoder_training',
            'ordered_clause_recurrent_decoder_experiment'):
        ctx['owners'][name]=ctx['helpers'].extension(parent_root,AUTO+name+'.py',PREFIX+name,parent['extensions'])
    for relative,digest in manifest['extensions'].items():
        require(sha(args.extension_root/relative)==digest, 'new producer changed: '+relative)
    load_boundary_extensions(ctx,parent_root,args.extension_root,parent['extensions'],manifest['extensions'])
    load_intervention_extensions(ctx,parent_root,args.extension_root,parent['extensions'],manifest['extensions'])
    evaluator=load_helper(parent_root,parent['extensions'],EVALUATOR,'_modality_exposed_evaluator')
    ctx.update(manifest=manifest,plan=plan,pins=manifest['extensions'],parent_manifest=parent,
        prior_margin=prior,native_runner=native,exposed_evaluator=evaluator,baseline_runs={})
    expected={f'384-source-head-lr10-{seed}' for seed in FIXED['seed_order']}
    require(set(manifest['baseline_summaries'])==expected, 'exact two384D baseline summaries required')
    for name,path in manifest['baseline_summaries'].items():
        run=bound_json(manifest,path)
        require(run['arm']==name and run['dimension']==384 and run['budget_completed'] is True
            and run['recipe']==prior.ARMS[0], 'historical baseline identity differs')
        run['training']=bound_json(manifest,run['training_ref']['path'],run['training_ref']['sha256'])
        run['postfit']={role:{label:bound_json(manifest,ref['path'],ref['sha256'])
            for label,ref in panels.items()} for role,panels in run['postfit'].items()}
        ctx['baseline_runs'][name]=run
    return ctx


def load_boundary_extensions(ctx, parent_root, extension_root, parent_pins, pins):
    """Load revised default-compatible boundary before its historical consumers."""
    name='contextual_generated_boundary_training'
    ctx['owners'][name]=ctx['helpers'].extension(extension_root,AUTO+name+'.py',PREFIX+name,pins)
    for name in ('generated_field_training','generated_source_margin_training'):
        ctx['owners'][name]=ctx['helpers'].extension(parent_root,AUTO+name+'.py',PREFIX+name,parent_pins)


def source_only_original_rows(value, split):
    require(type(value) is dict and type(value.get('rows')) is list and value['rows'], 'original source rows required')
    result=[]
    for row in value['rows']:
        require(row.get('split')==split and row.get('source_sha256')==
            hashlib.sha256(row['source_text'].encode()).hexdigest(), 'original split/source binding differs')
        result.append(dict(id=row['id'],source_text=row['source_text'],input=row['embedding']))
    return result


def prepare_exposed_sources(ctx, lane):
    data=bound_json(ctx['manifest'],ctx['manifest']['exposed_source_inputs'])
    ctx['exposed_evaluator']._source_only(data)
    require(data.get('schema')=='fresh-scalar-source-inputs/v1' and data.get('complete') is True
        and set(data.get('dimensions',{}))=={'8','384','768'} and data.get('inputs_sha256')==
        ctx['core'].digest({k:v for k,v in data.items() if k!='inputs_sha256'}), 'bound R6 source inputs required')
    source=data['dimensions']['384']; rows=source['rows']
    require(type(rows) is list and len(rows)==48 and all(set(r)=={'id','input','source_text'} for r in rows),
        'closed48 exposed source rows required')
    owner=ctx['owners']['clause_source_context']
    contexts=owner.build_source_contexts([{k:r[k] for k in ('id','source_text')} for r in rows],source['clause_cache'])
    require(contexts==source['source_contexts'] and owner.validate_contexts(rows,contexts)['dimension']==384,
        'exposed source context differs')
    lane.update(fresh_rows=rows,fresh_contexts=contexts)
    return source


def prepare_banks(ctx, lane, exposed, deadline):
    manifest=ctx['manifest']; inputs=manifest['auxiliary_sources']; owner=ctx['owners']['source_modality_auxiliary_training']
    require(set(inputs)=={'original_training','prepared_training','forbidden'}, 'closed auxiliary provenance required')
    require(set(inputs['forbidden'])=={'validation','test','canary'}, 'all original forbidden splits required')
    original=bound_json(manifest,inputs['original_training']); cache=bound_json(manifest,inputs['prepared_training'])
    source_only_original_rows(original,'train')
    adapted=owner.adapt_original_training_bank(original['rows'],cache,codec=lane['donor']['codec'],deadline=deadline)
    forbidden={split:source_only_original_rows(bound_json(manifest,path),split)
        for split,path in inputs['forbidden'].items()}
    # Include every observed development paragraph and source clause, not just
    # the original single-clause validation bank.
    forbidden['validation'] += [{k:r[k] for k in ('id','source_text','input')} for r in lane['rows']['validation']]
    forbidden['validation'] += [{k:r[k] for k in ('id','source_text','input')} for r in lane['clause_cache']['validation']]
    forbidden['exposed_holdout']=deepcopy(exposed['rows']+exposed['clause_cache'])
    paragraphs=[{k:r[k] for k in ('id','source_text')} for r in lane['rows']['train']]
    sources=adapted['source_rows']; references=adapted['references']
    hashes={key:ctx['core'].digest(value) for key,value in dict(source_rows=sources,references=references,
        paragraph_training_rows=paragraphs,forbidden_rows_by_split=forbidden,codec=lane['donor']['codec']).items()}
    banks={kind:owner.prepare_bank(sources,references,paragraph_training_rows=paragraphs,
        forbidden_rows_by_split=forbidden,codec=lane['donor']['codec'],bank_kind=kind,input_sha256=hashes,
        validate_rule=lane['validate_rule'],deadline=deadline) for kind in ('used113','full180')}
    lane['modality_banks']=banks
    return dict(banks=banks,original_adapter_receipt=adapted['receipt'],input_sha256=hashes,
        raw_artifacts={str(Path(p).resolve()):manifest['inputs'][str(Path(p).resolve())]
            for p in [inputs['original_training'],inputs['prepared_training'],*inputs['forbidden'].values(),
                manifest['exposed_source_inputs']]},prepared_once=True,**FALSE)


def bind_candidate(ctx, recipe, seed):
    require(recipe in ARMS and seed in FIXED['seed_order'], 'unplanned source-modality candidate')
    return ctx['prior_margin'].bind_candidate(ctx,ctx['prior_margin'].ARMS[0],seed)


def train_candidate(ctx, model, seed, recipe):
    require(recipe in ARMS and seed in FIXED['seed_order'], 'unplanned source-modality fit')
    auxiliary={} if recipe['bank_kind'] is None else dict(
        auxiliary_source_modality_bank=ctx['modality_banks'][recipe['bank_kind']],
        auxiliary_source_modality_weight=recipe['auxiliary_source_modality_weight'],
        generated_boundary_retry_on_mismatch=recipe['generated_boundary_retry_on_mismatch'])
    return ctx['owners']['long_span_source_value_training'].train(model,ctx['rows']['train'],ctx['rows']['validation'],
        training_references=ctx['references']['train'],validation_references=ctx['references']['validation'],
        codec=ctx['donor']['codec'],input_transform=ctx['donor']['input_transform'],lineage=ctx['lineage'],
        validate_rule=ctx['validate_rule'],validator_id=ctx['validator_id'],curriculum=ctx['stages'],
        strategy='semantic_fields',cardinality_weight=.25,count_exposure='balanced_all',source_value_weight=.25,
        source_contexts=ctx['source_contexts'],action_contrastive_weight=.05,generated_boundary_weight=.05,
        generated_boundary_site_policy='first_last',generated_source_margin_weight=0.,generated_source_margin_replay=False,
        non_action_learning_rate_multiplier=10., config=dict(seed=seed,max_seconds=180,max_target_tokens=512,
            batch_size=8,learning_rate=.001,max_optimizer_steps=1000,patience=0,validation_interval=4,alpha=0.,
            max_memory_bytes=FIXED['baseline_memory_bytes'] if recipe['bank_kind'] is None else FIXED['positive_memory_bytes']),
        **auxiliary)


def fit_and_record(ctx, model, seed, recipe, folder, initial_tensor_sha256):
    """Retain an exception without claiming unavailable completed-update counts."""
    started=time.monotonic()
    try:
        value=train_candidate(ctx,model,seed,recipe)
    except Exception as error:
        observed=ctx['core'].tensor_digest(model)
        ctx['helpers'].save(folder/'training-failure.json',dict(schema='source-modality-training-failure/v1',
            seed=seed,dimension=384,recipe=recipe,stage='trainer_call',exception_type=type(error).__name__,
            exception_message_omitted=True,
            traceback_frames=[dict(file=f.filename,line=f.lineno,function=f.name)
                for f in traceback.extract_tb(error.__traceback__)],
            initial_caller_tensor_sha256=initial_tensor_sha256,observed_caller_tensor_sha256=observed,
            caller_tensor_unchanged=observed==initial_tensor_sha256,completed_training_report_available=False,
            completed_optimizer_steps=None,private_training_state_available=False,training_call_failed=True,
            elapsed_seconds=time.monotonic()-started,**FALSE))
        raise
    return value,time.monotonic()-started


def validate_auxiliary_report(ctx, report, recipe):
    """Validate declared work before postfit model comparisons."""
    require(report['stopped_reason']=='epochs_completed' and report['optimizer_steps']==340
        and report['row_presentations']==2440 and report['valid_target_token_presentations']==225840
        and report['source_value_presentations']==25600 and report['count_training_row_presentations']==2440
        and report['count_training_presentations_by_class']==FIXED['expected_balanced_count_presentations'],
        'incomplete original training exposure')
    require(not any(k.startswith('generated_source_margin_') for k in report), 'R6 source-margin path must remain disabled')
    if recipe['bank_kind'] is None:
        require(not any(k.startswith('auxiliary_source_modality_') for k in report)
            and not any(k.startswith('generated_boundary_retry_') for k in report)
            and all('auxiliary_source_modality' not in u for u in report['committed_updates']),
            'baseline unexpectedly used auxiliary modality path')
        return
    require(report.get('generated_boundary_retry_on_mismatch') is True
        and report.get('generated_boundary_retry_policy')=='bulk_then_original_batch_incremental_retry_on_logit_mismatch'
        and report.get('generated_boundary_retry_limit_per_original_batch')==1
        and report.get('generated_boundary_retry_tolerance_changed') is False
        and report.get('generated_boundary_retry_max_updates_estimated')==340,
        'positive arm omitted strict boundary retry policy')
    prefix='auxiliary_source_modality_'
    require(report.get(prefix+'weight')==.05 and report.get(prefix+'used_for_selection') is False
        and report.get(prefix+'committed_updates')==340 and report.get(prefix+'presentations')==2040
        and report.get(prefix+'presentations_per_stratum')==340 and report.get(prefix+'strata_count')==6
        and report.get(prefix+'presentations_per_class')=={'O':680,'P':680,'F':680}
        and report.get(prefix+'training_only') is True and report.get(prefix+'normalization_refitted') is False
        and report.get(prefix+'encoder_executed') is False and report.get(prefix+'zero_weight_graph_attached') is False,
        'auxiliary modality policy or exposure differs')
    bank=ctx['modality_banks'][recipe['bank_kind']]; cache=report.get(prefix+'bank_receipt')
    require(type(cache) is dict and cache.get('bank_sha256')==bank['bank_sha256']
        and cache.get('bank_kind')==recipe['bank_kind'] and cache.get('dimension')==384
        and cache.get('selected_rows')==bank['selected_rows'] and cache.get('batch_size')==6
        and cache.get('seed')==report['config']['seed'] and cache.get('full_vocabulary_size')==32
        and cache.get('input_transform_sha256')==ctx['core'].digest(ctx['donor']['input_transform'])
        and cache.get('codec_sha256')==ctx['core'].digest(ctx['donor']['codec'])
        and cache.get('normalization_fitted') is False and cache.get('encoder_executed') is False,
        'auxiliary bank cache binding differs')
    binding=report.get(prefix+'binding_receipt'); digest=ctx['core'].digest
    closed={split:[{k:r[k] for k in ('id','source_text','input')} for r in ctx['rows'][split]]
        for split in ('train','validation')}
    actual_used={segment['source_sha256']:segment['embedding_sha256']
        for r in ctx['rows']['train'] for segment in ctx['source_contexts']['train'][r['id']]['segments']}
    require(type(binding) is dict and binding.get('schema')=='source-modality-training-binding/v1'
        and binding.get('bank_sha256')==bank['bank_sha256'] and binding.get('bank_kind')==recipe['bank_kind']
        and binding.get('dimension')==384 and binding.get('codec_sha256')==digest(ctx['donor']['codec'])
        and binding.get('training_rows_sha256')==digest(closed['train'])
        and binding.get('validation_rows_sha256')==digest(closed['validation'])
        and binding.get('training_paragraph_sources_sha256')==digest([{k:r[k] for k in ('id','source_text')} for r in closed['train']])
        and binding.get('training_contexts_sha256')==digest(ctx['source_contexts']['train'])
        and binding.get('validation_contexts_sha256')==digest(ctx['source_contexts']['validation'])
        and binding.get('actual_training_clause_vectors_sha256')==digest(actual_used)
        and binding.get('actual_training_unique_clauses')==len(actual_used)==113
        and binding.get('selected_bank_rows')==bank['selected_rows']
        and binding.get('externally_declared_extra_training_sources')==bank['selected_rows']-113
        and binding.get('validation_labels_accessed') is False and binding.get('training_reference_labels_accessed') is False,
        'auxiliary actual training binding differs')
    require(len(report['committed_updates'])==340, 'auxiliary update inventory differs')
    for i,update in enumerate(report['committed_updates']):
        validate_boundary_retry_receipt(update.get('generated_boundary'))
        value=update.get('auxiliary_source_modality')
        require(type(value) is dict and value.get('weight')==.05 and
            type(value.get('zero_based_committed_step')) is int and value['zero_based_committed_step']==i,
            'auxiliary modality update binding differs')
        for name in ('base_objective','weighted_loss'):
            require(type(value.get(name)) in (int,float) and math.isfinite(value[name]), 'nonfinite auxiliary objective')
        receipt=value.get('receipt')
        require(type(receipt) is dict and receipt.get('schema')=='training-source-modality-auxiliary/v1'
            and receipt.get('bank_sha256')==bank['bank_sha256'] and receipt.get('bank_kind')==recipe['bank_kind']
            and receipt.get('committed_step')==i and receipt.get('sampler_seed')==report['config']['seed']
            and receipt.get('batch_size')==6 and receipt.get('loss_field')=='modality'
            and receipt.get('source_slot')==0 and receipt.get('full_vocabulary_size')==32
            and receipt.get('source_head_forward_calls')==1 and receipt.get('recurrent_forward_calls')==0
            and receipt.get('count_forward_calls')==0 and receipt.get('encoder_forward_calls')==0
            and receipt.get('labels_passed_to_model') is False and receipt.get('validation_labels_used') is False
            and receipt.get('normalization_fitted') is False and receipt.get('sampler_state_advanced') is False,
            'auxiliary receipt scope differs')
        require(receipt.get('strata')==[dict(modality=s.split(':')[0],wording_style=int(s[-1]))
            for s in FIXED['auxiliary_strata']], 'auxiliary balanced strata differ')
        indices=receipt.get('indices')
        require(type(indices) is list and len(indices)==len(set(indices))==6
            and all(type(j) is int and 0<=j<len(bank['rows']) for j in indices), 'auxiliary row selection differs')
        selected=[bank['rows'][j] for j in indices]
        require(receipt.get('row_ids')==[r['id'] for r in selected]
            and receipt.get('source_sha256')==[r['source_sha256'] for r in selected]
            and receipt.get('target_token_ids')==[r['modality_token_id'] for r in selected], 'auxiliary row binding differs')
        logits=receipt.get('full_vocabulary_logits'); losses=receipt.get('per_row_cross_entropy')
        require(type(logits) is list and len(logits)==6 and all(type(row) is list and len(row)==32
            and all(type(v) in (int,float) and math.isfinite(v) for v in row) for row in logits)
            and type(losses) is list and len(losses)==6 and all(type(v) in (int,float) and math.isfinite(v) and v>=0 for v in losses)
            and type(receipt.get('mean_cross_entropy')) in (int,float) and math.isfinite(receipt['mean_cross_entropy'])
            and receipt['mean_cross_entropy']>=0, 'auxiliary full-vocabulary losses missing')


def validate_boundary_retry_receipt(receipt):
    """Fail fast on replay scope/work; independent audits reconstruct CE/parity."""
    require(type(receipt) is dict
        and receipt.get('schema')=='contextual-generated-source-boundary-loss/v2'
        and receipt.get('retry_enabled') is True
        and receipt.get('replay_strategy')=='bulk_then_original_batch_incremental_retry_on_logit_mismatch'
        and receipt.get('retry_limit_per_original_batch')==1
        and receipt.get('replay_logits_atol')==2e-5 and receipt.get('replay_logits_rtol')==2e-5
        and receipt.get('replay_logits_match_collection') is True
        and receipt.get('full_vocabulary_cross_entropy') is True and receipt.get('vocabulary_size')==32
        and receipt.get('reference_counts_used_only_in_loss') is True
        and receipt.get('target_prefixes_used') is False
        and receipt.get('student_generated_prefix_replay') is True
        and receipt.get('additional_optimizer_steps')==0
        and receipt.get('selection_policy')=='first_last' and receipt.get('site_cap_per_row')==2
        and receipt.get('one_gradient_replay_per_active_row') is True
        and receipt.get('bulk_grouping')=='active_rows_within_original_collection_batch'
        and receipt.get('successful_bulk_ce_gather')=='original_advanced_indexing',
        'strict boundary retry scope differs')
    generation=receipt.get('generation')
    require(type(generation) is dict and generation.get('max_target_tokens')==512
        and generation.get('batch_size')==8 and generation.get('source_only') is True
        and generation.get('reference_count_access') is False and generation.get('site_policy_access') is False
        and generation.get('complete_rollout_before_site_selection') is True,
        'boundary collection scope differs')
    rows=generation.get('rows');attempts=receipt.get('replay_attempts');events=receipt.get('events')
    require(type(rows) is list and 1<=len(rows)<=8 and type(attempts) is list and type(events) is list,
        'boundary replay inventory missing')
    require(len({row['id'] for row in rows})==len(rows)
        and all(type(row.get('batch_offset')) is int and row['batch_offset']==(i//8)*8
            for i,row in enumerate(rows)), 'boundary original batch inventory differs')
    active=[row for row in rows if row['selected_sites']]
    require(receipt.get('rows')==len(rows) and receipt.get('active_rows')==len(active)
        and receipt.get('selected_sites')==sum(len(row['selected_sites']) for row in active)
        and all(1<=len(row['selected_sites'])<=2
            and row['replay_prefix_tokens']==row['selected_sites'][-1]['position']+1 for row in active),
        'boundary selected rows differ')
    grouped={offset:[r for r in active if r['batch_offset']==offset]
        for offset in sorted({r['batch_offset'] for r in active})}
    totals=dict(bulk_replay_batch_count=0,discarded_bulk_batch_count=0,incremental_retry_batch_count=0,
        incremental_retry_forward_steps=0,bulk_attempted_row_tokens=0,retry_attempted_row_tokens=0,
        physical_replay_forward_calls=0,physical_replay_row_tokens=0)
    accepted={};cursor=0
    for offset,part in grouped.items():
        original=[r for r in rows if r['batch_offset']==offset]
        lengths=[r['replay_prefix_tokens'] for r in part];steps=max(lengths)
        for kind in ('bulk','incremental_retry'):
            require(cursor<len(attempts), 'missing required boundary replay attempt')
            attempt=attempts[cursor];cursor+=1
            physical=part if kind=='bulk' else original
            calls=1 if kind=='bulk' else steps
            require(attempt.get('kind')==kind and attempt.get('original_batch_offset')==offset
                and attempt.get('row_ids')==[r['id'] for r in physical]
                and attempt.get('active_row_ids')==[r['id'] for r in part]
                and attempt.get('prefix_lengths')==lengths and attempt.get('prefix_steps')==steps
                and attempt.get('physical_row_tokens')==len(physical)*steps
                and attempt.get('forward_calls')==calls
                and attempt.get('before_component_cross_entropy') is True
                and attempt.get('original_batch_membership_preserved') is (kind=='incremental_retry')
                and attempt.get('collected_prefix_checked') is (kind=='incremental_retry')
                and type(attempt.get('elapsed_seconds')) in (int,float)
                and math.isfinite(attempt['elapsed_seconds']) and attempt['elapsed_seconds']>=0,
                'boundary replay geometry or work differs')
            records=attempt.get('selected_logits');mismatches=attempt.get('mismatches')
            keys=[(r['id'],s['position']) for r in part for s in r['selected_sites']]
            require(type(records) is list and [(v['id'],v['position']) for v in records]==keys
                and all(type(v.get('logits')) is list and len(v['logits'])==32
                    and all(type(x) in (int,float) and math.isfinite(x) for x in v['logits']) for v in records)
                and type(mismatches) is list and attempt.get('parity_passed') is (not mismatches)
                and attempt.get('used_for_loss') is (not mismatches),
                'boundary replay parity or accepted-logit inventory differs')
            totals['physical_replay_forward_calls']+=calls
            totals['physical_replay_row_tokens']+=len(physical)*steps
            if kind=='bulk':
                totals['bulk_replay_batch_count']+=1;totals['bulk_attempted_row_tokens']+=len(physical)*steps
                totals['discarded_bulk_batch_count']+=int(bool(mismatches))
            else:
                totals['incremental_retry_batch_count']+=1;totals['incremental_retry_forward_steps']+=calls
                totals['retry_attempted_row_tokens']+=len(physical)*steps
                require(not mismatches, 'strict boundary retry still differs')
            if not mismatches:
                accepted.update({(v['id'],v['position']):v['logits'] for v in records})
                break
    require(cursor==len(attempts) and all(receipt.get(k)==v for k,v in totals.items())
        and receipt.get('replay_batch_count')==len(grouped)
        and receipt.get('rows_replayed_once') is (totals['incremental_retry_batch_count']==0)
        and receipt.get('replay_prefix_tokens')==sum(r['replay_prefix_tokens'] for r in active),
        'boundary retry work totals differ')
    require([(e['id'],e['position']) for e in events]==list(accepted)
        and all(e.get('replay_logits')==accepted[(e['id'],e['position'])] for e in events),
        'boundary loss used discarded or unbound replay logits')


def evaluate_original_panels(ctx, model, predictions, folder):
    panels={}; prior=ctx['prior_margin']; save=ctx['helpers'].save
    for label,split,control in CONTROLS:
        panel=ctx['clause_runner'].evaluate(ctx,model,split,control)
        if label=='validation':
            require(panel['predictions']==predictions, 'saved endpoint generation differs')
        panel['recurrent_residual_diagnostic']=prior.recurrent_residual_diagnostic(ctx,model,split,control)
        save(folder/('evaluation-'+label+'.json'),panel)
        panels[label]=ctx['prior'].compact_panel(panel,retain_predictions=True)
    disabled=ctx['owners']['ordered_clause_recurrent_decoder_experiment'].bind_residual_off_model(model)
    panel=ctx['clause_runner'].evaluate(ctx,disabled,'validation','conditioned')
    panel['execution'].update(kind='recurrent_residual_off',recurrent_residual_disabled=True,selection_performed=False,training_performed=False)
    panel['recurrent_residual_diagnostic']=prior.recurrent_residual_diagnostic(ctx,disabled,'validation','conditioned')
    save(folder/'evaluation-recurrent-residual-off.json',panel)
    panels['recurrent-residual-off']=ctx['prior'].compact_panel(panel,retain_predictions=True)
    return panels


def restore_endpoint(ctx, run, role):
    ref=run['states'][role]; data=Path(ref['path']).read_bytes()
    require(hashlib.sha256(data).hexdigest()==ref['sha256'], 'new saved endpoint changed')
    state=json.loads(data)
    require(state['schema']=='private-native-dimension-source-state/v1' and state['dimension']==384
        and state['role']==role and state['recipe']==run['recipe'] and state['codec']==ctx['donor']['codec']
        and state['input_transform']==ctx['donor']['input_transform'] and state['weights_sha256']==
        ctx['core'].digest(state['model_state']) and state['tensor_sha256']==ref['tensor_sha256']
        and all(state.get(k) is False for k in ('qualified','admitted','proof_authority','checkpoint_promoted')),
        'saved endpoint provenance differs')
    model=bind_candidate(ctx,run['recipe'],run['seed'])
    require(model.describe()==state['architecture'], 'endpoint architecture differs')
    values=ctx['clause_runner'].restored_tensors(ctx,state['model_state'],model.state_dict())
    ctx['native_runner'].validate_wrapper_state(ctx,values); model.load_state_dict(values,strict=True)
    require(ctx['core'].tensor_digest(model)==ref['tensor_sha256'], 'restored endpoint digest differs')
    return model


def load_exposed_references(ctx, records):
    """Open previously exposed labels only after all12 predictions are saved."""
    expected={(f'{d}-{arm["name"]}-{seed}',role) for d,seed,arm in jobs() for role in ROLES}
    require(len(records)==12 and {(r['arm'],r['role']) for r in records}==expected,
        'all12 exposed predictions required before reference load')
    identities=[r['id'] for r in ctx['fresh_rows']]
    for record in records:
        data=Path(record['predictions_ref']['path']).read_bytes()
        require(hashlib.sha256(data).hexdigest()==record['predictions_ref']['sha256'], 'saved exposed prediction changed')
        value=json.loads(data)
        require(value.get('complete') is True and [r.get('id') for r in value.get('predictions',[])]==identities
            and value.get('model_tensor_sha256')==record['state_ref']['tensor_sha256']
            and value.get('generation_reference_access') is False, 'incomplete exposed prediction')
    manifest=ctx['manifest']; refs=bound_json(manifest,manifest['exposed_references'])
    receipt=bound_json(manifest,manifest['exposed_holdout_receipt']); digest=ctx['core'].digest
    require(receipt.get('schema')=='authored-scalar-holdout/v1' and receipt.get('complete') is True
        and receipt.get('receipt_sha256')==digest({k:v for k,v in receipt.items() if k!='receipt_sha256'})
        and receipt.get('references_sha256')==digest(refs) and receipt.get('codec_sha256')==digest(ctx['donor']['codec'])
        and receipt.get('source_rows_sha256')==digest([{k:r[k] for k in ('id','source_text')} for r in ctx['fresh_rows']])
        and receipt.get('sealed_comparison_sha256')==ctx['parent_manifest']['plan_sha256'], 'original R6 reference binding differs')
    require(type(refs) is list and len(refs)==48 and [r['id'] for r in refs]==identities, 'exposed reference identities differ')
    vocabulary=ctx['donor']['codec']['target_vocabulary']
    for ref,row in zip(refs,ctx['fresh_rows']):
        ids=ref['target_ids']
        require(ref['source_text']==row['source_text'] and ref['source_sha256']==hashlib.sha256(row['source_text'].encode()).hexdigest()
            and ref.get('split')=='fresh_authored_holdout' and ref.get('codec_sha256')==digest(ctx['donor']['codec'])
            and ref.get('target_sha256')==digest(ref['target']) and type(ids) is list and 3<=len(ids)<=512
            and ids[0]==1 and ids[-1]==2 and all(type(t) is int and 3<=t<len(vocabulary) for t in ids[1:-1])
            and json.loads(''.join(vocabulary[t] for t in ids[1:-1]))==ref['target'], 'invalid original exposed reference')
    return refs,receipt


def evaluate_exposed(ctx, runs, output, deadline):
    records=[]; owner=ctx['exposed_evaluator']; save=ctx['helpers'].save
    for run in runs:
        for role in ROLES:
            require(time.monotonic()<deadline, 'comparison deadline exceeded')
            model=restore_endpoint(ctx,run,role)
            panel=owner.generate_panel(ctx,ctx,model,min(deadline,time.monotonic()+30))
            panel.update(schema='source-modality-exposed-r6-predictions/v1',fresh_holdout=False,
                fresh_authored_holdout=False,previously_exposed=True,used_for_selection=False)
            ref=save(output/run['arm']/(role+'-predictions.json'),panel)
            records.append(dict(arm=run['arm'],seed=run['seed'],dimension=384,role=role,
                state_ref=run['states'][role],predictions_ref=ref,generation_seconds=panel['elapsed_seconds']))
            del model,panel
    save(output/'predictions-complete.json',dict(complete=True,panels=records,
        all_predictions_persisted_before_reference_load=True,reference_json_loaded=False,**FALSE))
    references,receipt=load_exposed_references(ctx,records); results=[]; by_name={r['arm']:r for r in runs}
    for record in records:
        require(time.monotonic()<deadline, 'comparison deadline exceeded')
        ref=record['predictions_ref']; require(sha(ref['path'])==ref['sha256'], 'exposed prediction changed')
        prediction=json.loads(Path(ref['path']).read_bytes()); model=restore_endpoint(ctx,by_name[record['arm']],record['role'])
        score=owner.score_panel(ctx,ctx,model,prediction,references,
            min(deadline,time.monotonic()+30-record['generation_seconds']))
        score.update(schema='source-modality-exposed-r6-score/v1',fresh_holdout=False,
            fresh_authored_holdout=False,previously_exposed=True,used_for_selection=False)
        score_ref=save(output/record['arm']/(record['role']+'-score.json'),score)
        results.append(dict(record,score_ref=score_ref,scoring_seconds=score['elapsed_seconds'],
            ordered_exact=score['fidelity']['metrics']['ordered_exact'],syntax_valid=score['fidelity']['metrics']['syntax_valid'],
            teacher_forced_cross_entropy=score['teacher_forced']['token_cross_entropy']))
        del model,prediction,score
    return dict(schema='source-modality-exposed-r6-evaluation/v1',complete=len(results)==12,panels=results,
        references_sha256=ctx['core'].digest(references),original_holdout_receipt_sha256=ctx['core'].digest(receipt),
        all_predictions_persisted_before_reference_load=True,encoder_executed=False,downloads_performed=False,
        previously_exposed=True,used_for_selection=False,**FALSE)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('dependency-root','extension-root','manifest','plan','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--phase',choices=['training'],required=True); args=parser.parse_args()
    started=time.monotonic(); deadline=started+FIXED['max_seconds_entire_run']; ctx=load_context(args)
    before=source_inventory(args,ctx); save=ctx['helpers'].save; args.output.mkdir(parents=True)
    save(args.output/'sealed-recipe.json',dict(plan=ctx['plan'],manifest=ctx['manifest'],tree_pin=ctx['tree'],**FALSE))
    lane=ctx['native_runner'].prepare_dimension(ctx,384)
    for name,value in [('preprocessing',lane['preparation']),('source-contexts',lane['source_contexts']),('training-rows',lane['rows'])]:
        save(args.output/'384'/(name+'.json'),value)
    exposed=prepare_exposed_sources(ctx,lane); save(args.output/'auxiliary-banks.json',prepare_banks(ctx,lane,exposed,deadline))
    runs=[]; indices=[]
    for dimension,seed,recipe in jobs():
        require(time.monotonic()<deadline, 'comparison deadline exceeded')
        arm_started=time.monotonic(); name=f'{dimension}-{recipe["name"]}-{seed}'; folder=args.output/name
        lane['lineage']['student_lineage']=('source_head_learning_rate_formula_sidecar:' if recipe==ARMS[0]
            else 'source_modality_auxiliary_formula_sidecar:')+name
        model=bind_candidate(lane,recipe,seed)
        initial=lane['prior_margin'].validate_initial(lane,model,seed,lane['prior_margin'].ARMS[0])
        save(folder/'initial-parity.json',initial)
        states={'initial':lane['native_runner'].save_state(lane,model,recipe,'initial',False,folder/'initial-state.json')}
        value,fit_seconds=fit_and_record(lane,model,seed,recipe,folder,states['initial']['tensor_sha256'])
        report=value['report']; save(folder/'training.json',report); validate_auxiliary_report(lane,report,recipe)
        postfit={}
        for role,state,predictions in [('selected',value['state_dict'],value['predictions']),
                ('last-attempt',value['last_complete_attempt_state_dict'],value['last_complete_attempt_predictions'])]:
            require(state is not None, 'complete selected/final state required')
            lane['native_runner'].validate_wrapper_state(lane,state); model.load_state_dict(state,strict=True)
            expected=report['selected_weights_sha256'] if role=='selected' else report['last_complete_attempt_weights_sha256']
            require(lane['core'].tensor_digest(model)==expected, 'training state digest differs')
            states[role]=lane['native_runner'].save_state(lane,model,recipe,role,
                role=='selected' or report['last_complete_attempt_is_selected'],folder/(role+'-state.json'))
            postfit[role]=evaluate_original_panels(lane,model,predictions,folder/role)
        replay=lane['prior_margin'].validate_baseline(lane,report,postfit,seed) if recipe==ARMS[0] else None
        record=dict(arm=name,dimension=384,seed=seed,recipe=recipe,states=states,initial_parity=initial,
            baseline_replay=replay,training_call_elapsed_seconds=fit_seconds,elapsed_seconds=time.monotonic()-arm_started,
            budget_completed=True,trainable_parameter_count=sum(p.numel() for p in model.parameters() if p.requires_grad),
            training_ref=dict(path=str(folder/'training.json'),sha256=sha(folder/'training.json')),
            postfit={role:{label:dict(path=str(folder/role/('evaluation-'+label+'.json')),
                sha256=sha(folder/role/('evaluation-'+label+'.json')),fidelity=panel['source_fidelity'],numerical=panel['numerical'])
                for label,panel in panels.items()} for role,panels in postfit.items()},**FALSE)
        summary_ref=save(folder/'summary.json',record); runs.append(record)
        indices.append(dict(arm=name,summary_path=summary_ref['path'],summary_sha256=summary_ref['sha256']))
        print(json.dumps(dict(arm=name,steps=340,selected_epoch=report['selected_epoch'],
            final_exact=report['last_complete_attempt']['fidelity']['metrics']['ordered_exact'],fit_seconds=fit_seconds)),flush=True)
        del model,value,postfit,report
    exposed_result=evaluate_exposed(lane,runs,args.output/'exposed-r6',deadline)
    exposed_ref=save(args.output/'exposed-r6'/'summary.json',exposed_result)
    after=source_inventory(args,ctx); require(all(after.get(k)==v for k,v in before.items()), 'loaded producer changed')
    for path,digest in ctx['manifest']['inputs'].items():
        require(sha(path)==digest, 'sealed input changed')
    for root,pins in [(args.extension_root,ctx['pins']),
            (Path(ctx['manifest']['parent_extension_root']),ctx['parent_manifest']['extensions'])]:
        for relative,digest in pins.items():
            require(sha(root/relative)==digest, 'frozen producer changed')
    require(sha(args.plan)==ctx['manifest']['plan_sha256'] and time.monotonic()<deadline, 'plan changed or deadline exceeded')
    save(args.output/'summary.json',dict(schema='source-modality-training-comparison/v1',complete=len(runs)==6,
        runs=indices,exposed_r6_summary_ref=exposed_ref,training_executed=True,dimensions_actually_trained=[384],
        source_dependencies=after,all_two_published_384_baselines_replayed=True,
        historical_linguistic_teacher_modified=False,identity_projection_is_not_learned_reconstruction=True,
        elapsed_seconds=time.monotonic()-started,workers=1,bridge_names=[],legal_ir_evaluate_provers=False,
        metric_disk_cache_used=False,encoder_executed=False,downloads_performed=False,**FALSE))


if __name__=='__main__':
    main()
