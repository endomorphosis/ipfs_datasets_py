#!/usr/bin/env python3
"""Paired cached-input Legal formula-sidecar training at 8, 384 and 768 dimensions.

4096D is recorded as blocked by its unchanged native-owner gate. Historical 8D
linguistic weights are never loaded or changed; this is a distinct formula head.
"""
import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import time
import traceback
from types import SimpleNamespace

PARENT_RUNNER = 'scripts/ops/autoencoder/benchmark_content_matched_modality_training.py'
FALSE = {'qualified': False,
 'admitted': False,
 'proof_authority': False,
 'source_semantics_verified': False,
 'checkpoint_promoted': False,
 'convergence_proven': False,
 'fresh_holdout': False,
 'fresh_authored_holdout': False,
 'lake_executed': False,
 'native_validation_executed': False,
 'formalized': False,
 'roundtrip_ok': False}
ARMS = [{'name': 'source-head-lr10',
  'bank_kind': None,
  'auxiliary_source_modality_weight': 0.0,
  'generated_boundary_retry_on_mismatch': False},
 {'name': 'aux-used113',
  'bank_kind': 'used113',
  'auxiliary_source_modality_weight': 0.05,
  'generated_boundary_retry_on_mismatch': True}]
CONTROLS = [['validation', 'validation', 'conditioned'],
 ['training', 'train', 'conditioned'],
 ['zero-condition', 'validation', 'zero_condition'],
 ['source-shuffle', 'validation', 'source_shuffle'],
 ['cross-length-shuffle', 'validation', 'cross_length_shuffle'],
 ['context-only-shuffle', 'validation', 'context_only_shuffle'],
 ['context-reverse', 'validation', 'context_reverse'],
 ['context-rotate', 'validation', 'context_rotate']]
ROLES = ['selected', 'last-attempt']
FIXED = {'schema': 'multidimension-source-modality-training-plan/v1',
 'dimensions': [8, 384, 768],
 'seed_order': [1729],
 'arms': [{'name': 'source-head-lr10',
           'bank_kind': None,
           'auxiliary_source_modality_weight': 0.0,
           'generated_boundary_retry_on_mismatch': False},
          {'name': 'aux-used113',
           'bank_kind': 'used113',
           'auxiliary_source_modality_weight': 0.05,
           'generated_boundary_retry_on_mismatch': True}],
 'fit_count': 6,
 'original_training_rows': 48,
 'original_training_clause_occurrences': 180,
 'original_used_training_clauses': 113,
 'original_available_training_clauses': 180,
 'auxiliary_batch_size': 6,
 'auxiliary_strata': ['O:0', 'O:1', 'P:0', 'P:1', 'F:0', 'F:1'],
 'auxiliary_examples_per_stratum_per_update': 1,
 'auxiliary_positive_presentations_per_fit': 2040,
 'auxiliary_field': 'modality',
 'auxiliary_full_vocabulary_size': 32,
 'auxiliary_normalization': 'mean_six_full_vocabulary_cross_entropies',
 'auxiliary_source_only_head': True,
 'auxiliary_extra_decoder_rollouts': 0,
 'auxiliary_sampler_uses_decoder_rng': False,
 'auxiliary_used_for_selection': False,
 'boundary_retry_positive_arms_only': True,
 'boundary_retry_limit_per_original_batch': 1,
 'boundary_replay_atol': 2e-05,
 'boundary_replay_rtol': 2e-05,
 'boundary_replay_policy': 'bulk_parity_precheck;on_mismatch_original_batch_causal_incremental_retry;unchanged_tolerance',
 'boundary_replay_actual_argmax_prefixes_only': True,
 'boundary_replay_reference_prefixes_used': False,
 'baseline_boundary_retry_flag_omitted': True,
 'contextual_boundary_producer': 'revised_canonical_module;baseline_default_branch_unchanged',
 'auxiliary_bank_prepared_once': True,
 'clause_normalization_refitted': False,
 'positive_comparison': 'aux-used113_vs_source-head-lr10_within_each_dimension',
 'training_data_scope': 'same_original48paragraphs;auxiliary_repeats_only_existing113clauses',
 'foundation': 'source-head-lr10',
 'generated_source_margin_weight': 0.0,
 'generated_source_margin_replay': False,
 'generated_field_weight': 0.0,
 'joint_generated_replay': False,
 'non_action_learning_rate_multiplier': 10.0,
 'learning_rate': 0.001,
 'batch_size': 8,
 'epochs_per_source_stage': 20,
 'validation_interval': 4,
 'expected_optimizer_steps_per_arm': 340,
 'expected_training_token_presentations_per_arm': 225840,
 'expected_row_presentations_per_arm': 2440,
 'expected_count_presentations_per_arm': 2440,
 'expected_source_value_presentations_per_arm': 25600,
 'expected_balanced_count_presentations': {'1': 610, '2': 610, '4': 610, '8': 610},
 'cardinality_weight': 0.25,
 'source_value_weight': 0.25,
 'action_contrastive_weight': 0.05,
 'generated_boundary_weight': 0.05,
 'generated_boundary_site_policy': 'first_last',
 'fixed_encoder_context_tokens': 512,
 'fixed_decoder_output_limit': 512,
 'temperature': 0,
 'fresh_initialization': True,
 'selection_unchanged': True,
 'full_vocabulary_retained': True,
 'syntax_forced': False,
 'closure_forced': False,
 'production_promotion_allowed': False,
 'historical_linguistic_teacher_modified': False,
 'teacher_distillation_used': False,
 'identity_projection_frozen': True,
 'identity_mse_is_not_learned_reconstruction': True,
 'architecture_changed': False,
 'baseline_replay_required': True,
 'baseline_equivalence_exclusions': ['elapsed_seconds',
                                     'committed_updates[*].generated_boundary.elapsed_seconds',
                                     'committed_updates[*].generated_boundary.generation.elapsed_seconds',
                                     'committed_updates[*].generated_boundary.collection_sha256'],
 'postfit_controls': [['validation', 'validation', 'conditioned'],
                      ['training', 'train', 'conditioned'],
                      ['zero-condition', 'validation', 'zero_condition'],
                      ['source-shuffle', 'validation', 'source_shuffle'],
                      ['cross-length-shuffle', 'validation', 'cross_length_shuffle'],
                      ['context-only-shuffle', 'validation', 'context_only_shuffle'],
                      ['context-reverse', 'validation', 'context_reverse'],
                      ['context-rotate', 'validation', 'context_rotate']],
 'additional_candidate_control': 'recurrent-residual-off',
 'max_seconds_per_arm': 180,
 'max_seconds_per_postfit': 30,
 'max_seconds_entire_run': 1800,
 'baseline_memory_bytes': 1073741824,
 'positive_memory_bytes': 1073741824,
 'workers': 1,
 'bridge_names': [],
 'legal_ir_evaluate_provers': False,
 'metric_disk_cache_used': False,
 'no_downloads': True,
 'encoder_executed_during_training': False,
 'requested_dimensions': [8, 384, 768, 4096],
 'blocked_dimensions': {'4096': 'trusted_native_owner_integration_required'},
 'additional_encoder_execution': False,
 'auxiliary_sampler': 'independent',
 'auxiliary_source_vectors': 'exact_existing_width_specific_cache;no_width_conversion',
 'bank_derivation': 'original384_full180_metadata;only113_selected_vectors_at_actual_width',
 'forbidden_vector_coverage': 'actual_training_validation_and_available_exposed_same_width;old_test_canary_vectors_only384',
 'fresh_holdout_claim_allowed': False}

def require(value, message):
    if not value:
        raise ValueError(message)


def validate_plan(plan):
    require(type(plan) is dict and all(type(plan.get(k)) is type(v)
        and json.dumps(plan[k],sort_keys=True,allow_nan=False)==json.dumps(v,sort_keys=True,allow_nan=False)
        for k,v in FIXED.items()), 'fixed multidimension comparison differs')


def jobs():
    return [(dimension,1729,deepcopy(arm)) for dimension in FIXED['dimensions'] for arm in ARMS]


def readiness():
    return dict(schema='multidimension-modality-readiness/v1',requested_dimensions=[8,384,768,4096],
        executable_dimensions=[8,384,768],blocked_dimensions={'4096':dict(
            reason='trusted_native_owner_integration_required',training_executed=False,
            architecture='separate_legal_span_4096',embedding_throughput_is_not_training=True)},
        historical8_teacher_distinct_from_native8_formula_sidecar=True,**FALSE)

def sha(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1048576), b''):
            value.update(block)
    return value.hexdigest()

def bound_json(manifest, path, expected=None):
    path=Path(path).resolve(); wanted=manifest['inputs'].get(str(path))
    require(wanted is not None and (expected is None or wanted==expected), 'unbound artifact: '+str(path))
    data=path.read_bytes()
    require(hashlib.sha256(data).hexdigest()==wanted, 'sealed artifact differs: '+str(path))
    return json.loads(data)


def load_context(args):
    manifest=json.loads(args.manifest.read_bytes());plan=json.loads(args.plan.read_bytes());validate_plan(plan)
    require(sha(args.plan)==manifest['plan_sha256'] and plan['input_sha256']==manifest['inputs'],'sealed plan differs')
    for path,wanted in manifest['inputs'].items():require(sha(path)==wanted,'sealed input differs: '+path)
    parent=bound_json(manifest,manifest['parent_manifest']);bound_json(manifest,manifest['parent_plan'])
    root=Path(manifest['parent_extension_root']).resolve()
    require(parent['plan_sha256']==sha(manifest['parent_plan']),'parent plan differs')
    for relative,wanted in parent['extensions'].items():require(sha(root/relative)==wanted,'parent source differs: '+relative)
    spec=importlib.util.spec_from_file_location('_multidimension_frozen_parent',root/PARENT_RUNNER)
    owner=importlib.util.module_from_spec(spec);spec.loader.exec_module(owner)
    prior_args=SimpleNamespace(**vars(args));prior_args.extension_root=root
    prior_args.manifest=Path(manifest['parent_manifest']);prior_args.plan=Path(manifest['parent_plan'])
    ctx=owner.load_context(prior_args)
    expected={f'{d}-source-head-lr10-1729' for d in FIXED['dimensions']}
    require(set(manifest['baseline_summaries'])==expected,'exact three width-specific baseline summaries required')
    require(type(manifest.get('additional_forbidden_source_inputs')) is list
        and manifest['additional_forbidden_source_inputs'],'known later exposed sources required')
    ctx.update(comparison_manifest=manifest,comparison_plan=plan,comparison_owner=owner,comparison_parent_args=prior_args)
    for relative,wanted in manifest['extensions'].items():require(sha(args.extension_root/relative)==wanted,'new runner source differs')
    return ctx


def load_baseline(ctx,dimension):
    manifest=ctx['comparison_manifest'];name=f'{dimension}-source-head-lr10-1729'
    run=bound_json(manifest,manifest['baseline_summaries'][name])
    require(run['arm']==name and run['dimension']==dimension and run['seed']==1729
        and run['budget_completed'] is True and run['recipe']==ctx['prior_margin'].ARMS[0],
        'original width-specific baseline identity differs')
    for ref in run['states'].values():
        require(manifest['inputs'].get(str(Path(ref['path']).resolve()))==ref['sha256'],'unbound baseline state')
    run['training']=bound_json(manifest,run['training_ref']['path'],run['training_ref']['sha256'])
    run['postfit']={role:{label:bound_json(manifest,ref['path'],ref['sha256']) for label,ref in panels.items()}
        for role,panels in run['postfit'].items()}
    return {name:run}


def forbidden_inputs(ctx):
    """Only source-only containers enter the auxiliary exclusion boundary."""
    manifest=ctx['comparison_manifest'];paths=[ctx['manifest']['exposed_source_inputs'],
        *manifest['additional_forbidden_source_inputs']];result=[]
    for path in dict.fromkeys(paths):
        value=bound_json(manifest,path)
        require(value.get('schema') in ('fresh-scalar-source-inputs/v1','fresh-scalar-source-inputs-single/v1')
            and value.get('complete') is True and value.get('inputs_sha256')==ctx['core'].digest(
                {k:v for k,v in value.items() if k!='inputs_sha256'}),'authenticated source-only exclusion required')
        dimensions=value.get('dimensions') if value['schema']=='fresh-scalar-source-inputs/v1' else {str(value.get('dimension')):value}
        require(type(dimensions) is dict and dimensions and set(dimensions)<={'8','384','768'},'unsupported exclusion width')
        for width,lane in dimensions.items():
            require(type(lane.get('rows')) is list and type(lane.get('clause_cache')) is list,'source exclusion row/cache lists required')
            for row in lane['rows']+lane['clause_cache']:
                require(type(row) is dict and set(row)=={'id','source_text','input'},'closed source-only exclusion row required')
                ctx['core']._vector(row['input'],int(width));result.append(deepcopy(row))
    return result


def derive_used_bank(ctx,original_bank,lane,forbidden,deadline):
    """Authenticate metadata in384D, replace only selected113 actual-width vectors.

    This deliberately does not attest the67 unused vectors in another width.
    The original bank remains unchanged and separately retained as evidence.
    """
    require(time.monotonic()<deadline,'bank derivation deadline exceeded')
    owner=ctx['owners']['source_modality_auxiliary_training'];digest=ctx['core'].digest;dimension=lane['dimension']
    require(type(dimension) is int and dimension in FIXED['dimensions'],'supported actual source width required')
    require(original_bank['bank_sha256']==digest({k:v for k,v in original_bank.items() if k!='bank_sha256'})
        and original_bank['dimension']==384 and original_bank['bank_kind']=='used113'
        and original_bank['selected_rows']==113,'authenticated original384 used113 bank required')
    actual={}
    for row in lane['clause_cache']['train']:
        require(type(row) is dict and set(row)=={'id','source_text','input'},'closed actual cached clause required')
        owner._vector(row['input']);require(len(row['input'])==dimension,'actual auxiliary cache width differs')
        key=hashlib.sha256(row['source_text'].encode()).hexdigest()
        require(key not in actual,'duplicate actual cached literal');actual[key]=row
    require(len(actual)==113 and set(actual)=={r['source_sha256'] for r in original_bank['rows']},
        'exact original113 clause/vector coverage required')
    blocked_ids={r['id'] for r in forbidden};blocked_text={owner._normal(r['source_text']) for r in forbidden}
    blocked_text.update(owner._normal(piece) for r in forbidden for piece in r['source_text'].split('\n\n'))
    blocked_vectors={digest(r['input']) for r in forbidden if len(r['input'])==dimension}
    bank=deepcopy(original_bank);bank.pop('bank_sha256');bank['dimension']=dimension
    for row in bank['rows']:
        require(time.monotonic()<deadline,'bank derivation deadline exceeded')
        source=actual[row['source_sha256']]
        require(source['source_text']==row['source_text'] and row['source_sha256']==hashlib.sha256(row['source_text'].encode()).hexdigest(),
            'selected source identity differs')
        rule=owner._source(row['source_text'],row['wording_style'])
        require(rule['modality']==row['modality'] and row['target_sha256']==digest({'rules':[rule]})
            and lane['donor']['codec']['target_vocabulary'][row['modality_token_id']]=='"'+rule['modality']+'"',
            'complete selected target/style/modality alignment differs')
        require(row['id'] not in blocked_ids and source['id'] not in blocked_ids
            and owner._normal(row['source_text']) not in blocked_text and digest(source['input']) not in blocked_vectors,
            'selected auxiliary source overlaps forbidden identity/text/vector')
        row['input']=deepcopy(source['input']);row['input_sha256']=digest(source['input'])
    bank['source_inventory']=[{k:r[k] for k in ('id','source_sha256','input_sha256','target_sha256','modality','wording_style')} for r in bank['rows']]
    # input_sha256 identifies the original384 metadata preparation, rather than
    # falsely naming nonexistent180 native vectors. The derivation is explicit.
    bank['preparation_scope']='original384 full180 metadata; exact113 selected cached actual-width vectors; no unused-width-vector claim'
    bank['cached_used113_derivation']=dict(original384_bank_sha256=original_bank['bank_sha256'],actual_dimension=dimension,
        actual_training_clause_cache_sha256=digest(lane['clause_cache']['train']),
        forbidden_source_inventory_sha256=digest(forbidden),same_width_forbidden_vectors=sum(len(r['input'])==dimension for r in forbidden),
        full180_native_vectors_authenticated=False,unused67_vectors_materialized=False,
        old_test_canary_vector_coverage='verified384_only;source_identity_and_text_checked_all_widths',
        vector_conversion_performed=False,encoder_executed=False,normalization_refitted=False)
    bank['bank_sha256']=digest(bank)
    binding=owner.validate_training_binding(bank,lane['rows']['train'],lane['rows']['validation'],
        source_contexts=lane['source_contexts'],codec=lane['donor']['codec'],deadline=deadline)
    require(time.monotonic()<deadline,'bank derivation deadline exceeded')
    return bank,dict(schema='multidimension-used113-derivation/v1',complete=True,dimension=dimension,
        original384_bank_sha256=original_bank['bank_sha256'],derived_bank_sha256=bank['bank_sha256'],
        actual_binding=binding,derivation=deepcopy(bank['cached_used113_derivation']),**FALSE)


def prepare_original_bank(ctx,deadline):
    lane=ctx['native_runner'].prepare_dimension(ctx,384);parent=ctx['parent_runner']
    exposed=parent.prepare_exposed_sources(ctx,lane)
    evidence=parent.prepare_banks(ctx,lane,exposed,deadline)
    blocked=[]
    for split,path in ctx['manifest']['auxiliary_sources']['forbidden'].items():
        blocked+=parent.source_only_original_rows(bound_json(ctx['comparison_manifest'],path),split)
    blocked+=forbidden_inputs(ctx)
    return lane,evidence,blocked


def prepare_lane(ctx,dimension,original_bank,forbidden,deadline,preprepared=None):
    lane=ctx['native_runner'].prepare_dimension(ctx,dimension) if preprepared is None else preprepared
    require(lane['dimension']==dimension,'prepared lane width differs')
    lane['baseline_runs']=load_baseline(ctx,dimension)
    closed_validation=[{k:r[k] for k in ('id','source_text','input')} for r in lane['rows']['validation']]
    blocked=forbidden+closed_validation+lane['clause_cache']['validation']
    bank,derivation=derive_used_bank(ctx,original_bank,lane,blocked,deadline)
    lane['modality_banks']={'used113':bank};lane['bank_derivation']=derivation
    return lane


def bind_candidate(ctx,recipe,seed):
    require(recipe in ARMS and seed==1729,'unplanned multidimension candidate')
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
        ctx['helpers'].save(folder/'training-failure.json',dict(schema='multidimension-modality-training-failure/v1',
            seed=seed,dimension=ctx['dimension'],recipe=recipe,stage='trainer_call',exception_type=type(error).__name__,
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
        and cache.get('bank_kind')==recipe['bank_kind'] and cache.get('dimension')==ctx['dimension']
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
        and binding.get('dimension')==ctx['dimension'] and binding.get('codec_sha256')==digest(ctx['donor']['codec'])
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
        ctx['parent_runner'].validate_boundary_retry_receipt(update.get('generated_boundary'))
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


def execute(args):
    started=time.monotonic();deadline=started+FIXED['max_seconds_entire_run'];ctx=load_context(args)
    parent=ctx['comparison_owner'];parent_args=ctx['comparison_parent_args']
    before=parent.source_inventory(parent_args,ctx);save=ctx['helpers'].save
    args.output.mkdir(parents=True)
    save(args.output/'readiness.json',readiness())
    save(args.output/'sealed-recipe.json',dict(plan=ctx['comparison_plan'],manifest=ctx['comparison_manifest'],tree_pin=ctx['tree'],**FALSE))
    prepared384,bank_evidence,forbidden=prepare_original_bank(ctx,deadline)
    save(args.output/'original384-bank-evidence.json',bank_evidence)
    original_bank=bank_evidence['banks']['used113'];runs=[];preflights=[]
    for dimension in FIXED['dimensions']:
        require(time.monotonic()<deadline,'comparison deadline exceeded')
        lane=prepare_lane(ctx,dimension,original_bank,forbidden,deadline,prepared384 if dimension==384 else None)
        for name,value in [('preprocessing',lane['preparation']),('source-contexts',lane['source_contexts']),
                ('training-rows',lane['rows']),('auxiliary-bank',lane['modality_banks']['used113']),('bank-derivation',lane['bank_derivation'])]:
            save(args.output/str(dimension)/(name+'.json'),value)
        if args.phase=='preflight':
            model=bind_candidate(lane,ARMS[0],1729)
            initial=lane['prior_margin'].validate_initial(lane,model,1729,lane['prior_margin'].ARMS[0])
            ref=save(args.output/str(dimension)/'initial-parity.json',initial)
            preflights.append(dict(dimension=dimension,initial_parity_ref=ref,bank_derivation=lane['bank_derivation'],optimizer_executed=False))
            del model,lane
            continue
        for recipe in ARMS:
            require(time.monotonic()<deadline,'comparison deadline exceeded')
            arm_started=time.monotonic();name=f'{dimension}-{recipe["name"]}-1729';folder=args.output/name
            lane['lineage']['student_lineage']=('source_head_learning_rate_formula_sidecar:' if recipe==ARMS[0]
                else 'source_modality_auxiliary_formula_sidecar:')+name
            model=bind_candidate(lane,recipe,1729)
            initial=lane['prior_margin'].validate_initial(lane,model,1729,lane['prior_margin'].ARMS[0])
            save(folder/'initial-parity.json',initial)
            states={'initial':lane['native_runner'].save_state(lane,model,recipe,'initial',False,folder/'initial-state.json')}
            value,fit_seconds=fit_and_record(lane,model,1729,recipe,folder,states['initial']['tensor_sha256'])
            report=value['report'];save(folder/'training.json',report);validate_auxiliary_report(lane,report,recipe)
            postfit={}
            for role,state,predictions in [('selected',value['state_dict'],value['predictions']),
                    ('last-attempt',value['last_complete_attempt_state_dict'],value['last_complete_attempt_predictions'])]:
                require(time.monotonic()<deadline and state is not None,'complete selected/final state within deadline required')
                lane['native_runner'].validate_wrapper_state(lane,state);model.load_state_dict(state,strict=True)
                expected=report['selected_weights_sha256'] if role=='selected' else report['last_complete_attempt_weights_sha256']
                require(lane['core'].tensor_digest(model)==expected,'training state digest differs')
                states[role]=lane['native_runner'].save_state(lane,model,recipe,role,
                    role=='selected' or report['last_complete_attempt_is_selected'],folder/(role+'-state.json'))
                postfit[role]=evaluate_original_panels(lane,model,predictions,folder/role)
            replay=lane['prior_margin'].validate_baseline(lane,report,postfit,1729) if recipe==ARMS[0] else None
            record=dict(arm=name,dimension=dimension,seed=1729,recipe=recipe,states=states,initial_parity=initial,
                baseline_replay=replay,budget_completed=True,training_call_elapsed_seconds=fit_seconds,
                elapsed_seconds=time.monotonic()-arm_started,
                trainable_parameter_count=sum(p.numel() for p in model.parameters() if p.requires_grad),
                training_ref=dict(path=str(folder/'training.json'),sha256=sha(folder/'training.json')),
                postfit={role:{label:dict(path=str(folder/role/('evaluation-'+label+'.json')),
                    sha256=sha(folder/role/('evaluation-'+label+'.json')),fidelity=panel['source_fidelity'],numerical=panel['numerical'])
                    for label,panel in panels.items()} for role,panels in postfit.items()},**FALSE)
            ref=save(folder/'summary.json',record);runs.append(dict(arm=name,summary_path=ref['path'],summary_sha256=ref['sha256']))
            print(json.dumps(dict(arm=name,steps=report['optimizer_steps'],selected_epoch=report['selected_epoch'],
                final_exact=report['last_complete_attempt']['fidelity']['metrics']['ordered_exact'],fit_seconds=fit_seconds)),flush=True)
            del model,value,report,postfit
        del lane
    after=parent.source_inventory(parent_args,ctx)
    require(all(after.get(k)==v for k,v in before.items()),'loaded producer changed')
    manifest=ctx['comparison_manifest']
    for path,wanted in manifest['inputs'].items():require(sha(path)==wanted,'sealed input changed')
    for relative,wanted in manifest['extensions'].items():require(sha(args.extension_root/relative)==wanted,'new source changed')
    require(sha(args.plan)==manifest['plan_sha256'] and time.monotonic()<deadline,'plan changed or deadline exceeded')
    summary=dict(schema='multidimension-modality-training-comparison/v1',phase=args.phase,
        complete=len(runs)==6 if args.phase=='training' else len(preflights)==3,runs=runs,preflights=preflights,
        requested_dimensions=[8,384,768,4096],dimensions_actually_trained=[8,384,768] if args.phase=='training' else [],
        blocked_dimensions=readiness()['blocked_dimensions'],training_executed=args.phase=='training',source_dependencies=after,
        elapsed_seconds=time.monotonic()-started,workers=1,bridge_names=[],legal_ir_evaluate_provers=False,
        metric_disk_cache_used=False,encoder_executed=False,downloads_performed=False,
        all_three_original_baselines_replayed=args.phase=='training',**FALSE)
    save(args.output/'summary.json',summary)
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('dependency-root','extension-root','manifest','plan','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--phase',choices=['preflight','training'],required=True)
    execute(parser.parse_args())


if __name__=='__main__':main()
