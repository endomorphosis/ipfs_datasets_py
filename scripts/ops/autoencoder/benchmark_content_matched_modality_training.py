#!/usr/bin/env python3
"""Four exposure-matched384D fits; only auxiliary minibatch grouping changes.

The old R6 cohort remains exposed postfit development. Frozen R7 helpers keep
all original model, optimizer, source normalization and selection policies.
"""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys
import time
import traceback
from types import SimpleNamespace

AUTO='ipfs_datasets_py/logic/formalization/autoencoder/'
PREFIX='ipfs_datasets_py.logic.formalization.autoencoder.'
PARENT_RUNNER='scripts/ops/autoencoder/benchmark_source_modality_training.py'
TRAINER=AUTO+'long_span_source_value_training.py'
HELPER=AUTO+'source_modality_auxiliary_training.py'
FALSE={'qualified': False,
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
ARMS=[{'name': 'aux-full180',
  'bank_kind': 'full180',
  'auxiliary_source_modality_weight': 0.05,
  'generated_boundary_retry_on_mismatch': True},
 {'name': 'content-matched-cycles',
  'bank_kind': 'full180',
  'auxiliary_source_modality_weight': 0.05,
  'generated_boundary_retry_on_mismatch': True,
  'auxiliary_source_modality_sampler': 'content_matched_cycles'}]
ROLES=['selected', 'last-attempt']
CONTROLS=[['validation', 'validation', 'conditioned'],
 ['training', 'train', 'conditioned'],
 ['zero-condition', 'validation', 'zero_condition'],
 ['source-shuffle', 'validation', 'source_shuffle'],
 ['cross-length-shuffle', 'validation', 'cross_length_shuffle'],
 ['context-only-shuffle', 'validation', 'context_only_shuffle'],
 ['context-reverse', 'validation', 'context_reverse'],
 ['context-rotate', 'validation', 'context_rotate']]
FIXED={'schema': 'content-matched-source-modality-training-plan/v1',
 'dimensions': [384],
 'seed_order': [1729, 2718],
 'arms': [{'name': 'aux-full180',
           'bank_kind': 'full180',
           'auxiliary_source_modality_weight': 0.05,
           'generated_boundary_retry_on_mismatch': True},
          {'name': 'content-matched-cycles',
           'bank_kind': 'full180',
           'auxiliary_source_modality_weight': 0.05,
           'generated_boundary_retry_on_mismatch': True,
           'auxiliary_source_modality_sampler': 'content_matched_cycles'}],
 'fit_count': 4,
 'original_training_rows': 48,
 'exposed_validation_rows': 48,
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
 'baseline_boundary_retry_flag_omitted': False,
 'contextual_boundary_producer': 'revised_canonical_module;baseline_default_branch_unchanged',
 'auxiliary_bank_prepared_once': True,
 'clause_normalization_refitted': False,
 'positive_comparison': 'content_matched_cycles_vs_independent_full180',
 'training_data_scope': 'identical_original48paragraphs_plus_same_full180_auxiliary_sources',
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
 'expected_balanced_count_presentations': {'1': 610,
                                           '2': 610,
                                           '4': 610,
                                           '8': 610},
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
                                     'auxiliary_source_modality_preparation_elapsed_seconds',
                                     'auxiliary_source_modality_bank_receipt.elapsed_seconds',
                                     'committed_updates[*].auxiliary_source_modality.receipt.elapsed_seconds',
                                     'committed_updates[*].generated_boundary.elapsed_seconds',
                                     'committed_updates[*].generated_boundary.generation.elapsed_seconds',
                                     'committed_updates[*].generated_boundary.collection_sha256',
                                     'committed_updates[*].generated_boundary.replay_attempts[*].elapsed_seconds'],
 'postfit_controls': [['validation', 'validation', 'conditioned'],
                      ['training', 'train', 'conditioned'],
                      ['zero-condition', 'validation', 'zero_condition'],
                      ['source-shuffle', 'validation', 'source_shuffle'],
                      ['cross-length-shuffle',
                       'validation',
                       'cross_length_shuffle'],
                      ['context-only-shuffle',
                       'validation',
                       'context_only_shuffle'],
                      ['context-reverse', 'validation', 'context_reverse'],
                      ['context-rotate', 'validation', 'context_rotate']],
 'additional_candidate_control': 'recurrent-residual-off',
 'exposed_r6_rows': 48,
 'exposed_r6_panel_count': 8,
 'exposed_r6_roles': ['selected', 'last-attempt'],
 'exposed_r6_role': 'previously_exposed_postfit_regression;not_selection_or_fresh_holdout',
 'all_exposed_predictions_before_reference_load': True,
 'exposed_generation_reference_access': False,
 'max_seconds_per_arm': 180,
 'max_seconds_per_postfit': 30,
 'max_seconds_entire_run': 1200,
 'baseline_memory_bytes': 1073741824,
 'positive_memory_bytes': 1073741824,
 'workers': 1,
 'bridge_names': [],
 'legal_ir_evaluate_provers': False,
 'metric_disk_cache_used': False,
 'no_downloads': True,
 'encoder_executed_during_training': False,
 'control_sampler_keyword_omitted': True,
 'auxiliary_content_group_count': 30,
 'matched_optimizer_updates': 330,
 'independent_remainder_updates': 10,
 'per_source_auxiliary_exposure_identical': True,
 'content_matched_loss_unchanged': True,
 'exposed_r6_used_for_training': False}

FIXED.update(fresh_evaluation_seed=20261005,
    fresh_evaluation_families=['expletive_infinitival','fronted_infinitival','rule_subject_infinitival'],
    fresh_evaluation_dimensions=[384],fresh_evaluation_endpoint_roles=['selected','last-attempt'],
    fresh_evaluation_used_for_selection=False,
    control_panel_numerical_equivalence_exclusions=['elapsed_seconds','spans_per_wall_second','wall_seconds_per_span'])


def require(value,message):
    if not value: raise ValueError(message)


def sha(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):value.update(block)
    return value.hexdigest()


def validate_plan(plan):
    require(type(plan) is dict and all(type(plan.get(k)) is type(v)
        and json.dumps(plan[k],sort_keys=True,allow_nan=False)==json.dumps(v,sort_keys=True,allow_nan=False)
        for k,v in FIXED.items()),'fixed content-matched comparison differs')


def jobs():return [(384,seed,deepcopy(arm)) for seed in FIXED['seed_order'] for arm in ARMS]


def bound_json(manifest,path,expected=None):
    path=Path(path).resolve();wanted=manifest['inputs'].get(str(path));require(wanted is not None and (expected is None or wanted==expected),'unbound artifact: '+str(path))
    data=path.read_bytes();require(hashlib.sha256(data).hexdigest()==wanted,'sealed artifact differs: '+str(path));return json.loads(data)


def load_intervention_extensions(ctx, previous_root, extension_root, previous_pins, pins):
    """Replace only the authenticated previous helper; preserve both old trainers.

    The historical loader owns canonical trainer registration.  Its helper is
    the one deliberate override needed by the new trainer's lazy relative
    import; an unrelated module or package attribute is never displaced.
    """
    canonical=PREFIX+'source_modality_auxiliary_training'
    alias=PREFIX+'_r7_modality_helper_before_content_matched'
    trainer_name=PREFIX+'_content_matched_modality_training_owner'
    package=sys.modules.get(PREFIX.rstrip('.'))
    require(package is not None,'canonical autoencoder package is not loaded')
    previous_root=Path(previous_root).resolve();extension_root=Path(extension_root).resolve()
    previous_path=(previous_root/HELPER).resolve()
    old=sys.modules.get(canonical)
    require(old is not None and ctx['owners'].get('source_modality_auxiliary_training') is old,
        'previous modality helper owner differs')
    require(Path(getattr(old,'__file__','')).resolve()==previous_path
        and Path(getattr(getattr(old,'__spec__',None),'origin','')).resolve()==previous_path
        and getattr(old,'__name__',None)==canonical,
        'previous modality helper origin differs')
    require(previous_pins.get(HELPER)==sha(previous_path),'previous modality helper source differs')
    missing=object();attribute=getattr(package,'source_modality_auxiliary_training',missing)
    require(attribute is missing or attribute is old,'foreign modality helper package attribute')
    require(alias not in sys.modules and trainer_name not in sys.modules,
        'content-matched extensions must be loaded exactly once')
    for relative in (HELPER,TRAINER):
        require(pins.get(relative)==sha(extension_root/relative),'new intervention source differs: '+relative)
    historical_trainer=sys.modules.get(PREFIX+'long_span_source_value_training')
    previous_trainer=ctx['owners'].get('long_span_source_value_training')
    require(historical_trainer is not None and previous_trainer is not None,
        'historical trainer registrations required')
    try:
        sys.modules[alias]=old
        del sys.modules[canonical]
        helper=ctx['helpers'].extension(extension_root,HELPER,canonical,pins)
        setattr(package,'source_modality_auxiliary_training',helper)
        trainer=ctx['helpers'].extension(extension_root,TRAINER,trainer_name,pins)
        require(sys.modules.get(PREFIX+'long_span_source_value_training') is historical_trainer,
            'historical canonical trainer was replaced')
        require(sys.modules.get(PREFIX+'_source_modality_training_owner') is previous_trainer,
            'previous sibling trainer was replaced')
    except BaseException:
        sys.modules.pop(trainer_name,None)
        sys.modules.pop(alias,None)
        sys.modules[canonical]=old
        if attribute is missing:
            if hasattr(package,'source_modality_auxiliary_training'):
                delattr(package,'source_modality_auxiliary_training')
        else:setattr(package,'source_modality_auxiliary_training',attribute)
        raise
    ctx['owners'].update(source_modality_auxiliary_training=helper,long_span_source_value_training=trainer)
    ctx['source_overlay']=dict(schema='authenticated-content-matched-source-overlay/v1',
        canonical_helper=canonical,retained_previous_alias=alias,new_trainer_name=trainer_name,
        previous_helper=dict(path=str(previous_path),sha256=previous_pins[HELPER]),
        new_helper=dict(path=str(extension_root/HELPER),sha256=pins[HELPER]),
        new_trainer=dict(path=str(extension_root/TRAINER),sha256=pins[TRAINER]),
        historical_canonical_trainer_preserved=True,previous_sibling_trainer_preserved=True,
        previous_package_attribute_present=attribute is not missing)


def load_context(args):
    manifest=json.loads(args.manifest.read_bytes());plan=json.loads(args.plan.read_bytes());validate_plan(plan)
    require(sha(args.plan)==manifest['plan_sha256'] and plan['input_sha256']==manifest['inputs'],'sealed plan differs')
    for name,wanted in manifest['inputs'].items():require(sha(name)==wanted,'sealed input differs: '+name)
    parent=bound_json(manifest,manifest['parent_manifest']);parent_plan=bound_json(manifest,manifest['parent_plan']);root=Path(manifest['parent_extension_root']).resolve()
    require(parent['plan_sha256']==sha(manifest['parent_plan']),'R7 plan differs')
    for name,wanted in parent['extensions'].items():require(sha(root/name)==wanted,'R7 frozen source differs: '+name)
    require(sha(root/PARENT_RUNNER)==parent['extensions'][PARENT_RUNNER],'R7 runner differs')
    spec=importlib.util.spec_from_file_location('_content_matched_frozen_r7_runner',root/PARENT_RUNNER);prior=importlib.util.module_from_spec(spec);spec.loader.exec_module(prior)
    prior.validate_plan(parent_plan)
    oldargs=SimpleNamespace(**vars(args));oldargs.extension_root=root;oldargs.manifest=Path(manifest['parent_manifest']);oldargs.plan=Path(manifest['parent_plan'])
    ctx=prior.load_context(oldargs)
    # The inherited initial-parity gate still consumes these predictions.
    # Drop the large later reports, retaining its authenticated inputs.
    ctx['baseline_runs']={name:{'initial_parity':record['initial_parity']}
        for name,record in ctx['baseline_runs'].items()}
    for name,wanted in manifest['extensions'].items():require(sha(args.extension_root/name)==wanted,'new frozen source differs: '+name)
    load_intervention_extensions(ctx,root,args.extension_root,parent['extensions'],manifest['extensions'])
    expected={f'384-aux-full180-{seed}' for seed in FIXED['seed_order']}
    require(set(manifest['baseline_summaries'])==expected,'exact two R7 full180 controls required')
    controls={}
    for name,path in manifest['baseline_summaries'].items():
        run=bound_json(manifest,path)
        require(run['arm']==name and run['dimension']==384 and run['budget_completed'] is True and run['recipe']==ARMS[0],'R7 control identity differs')
        refs=[run['training_ref'],*run['states'].values(),*[r for panels in run['postfit'].values() for r in panels.values()]]
        for ref in refs:require(manifest['inputs'].get(str(Path(ref['path']).resolve()))==ref['sha256'],'unbound R7 control component')
        controls[name]=run
    ctx.update(outer_manifest=manifest,outer_plan=plan,outer_pins=manifest['extensions'],extension_root=args.extension_root.resolve(),
        parent_runner=prior,previous_manifest=parent,previous_extension_root=root,control_runs=controls)
    return ctx


def source_inventory(args,ctx):
    roots=[('dependency',args.dependency_root.resolve(),None),
        ('parent_extension',Path(ctx['manifest']['parent_extension_root']).resolve(),ctx['parent_manifest']['extensions']),
        ('previous_extension',ctx['previous_extension_root'],ctx['previous_manifest']['extensions']),
        ('extension',args.extension_root.resolve(),ctx['outer_pins'])]
    result={}
    for name,module in list(sys.modules.items()):
        if name!='ipfs_datasets_py' and not name.startswith('ipfs_datasets_py.'):continue
        filename=getattr(module,'__file__',None)
        if filename is None:continue
        path=Path(filename).resolve();require(path.is_file() and path.suffix=='.py','unbound package source')
        matches=[(scope,root,pins) for scope,root,pins in roots if path.is_relative_to(root)]
        require(len(matches)==1,'package source outside four isolated roots: '+str(path))
        scope,root,pins=matches[0];relative=str(path.relative_to(root));value=sha(path)
        require(pins is None or pins.get(relative)==value,'unregistered package source: '+str(path));result[scope+':'+relative]=value
    return result


def prepare_lane(ctx,output_dir,deadline):
    lane=ctx['native_runner'].prepare_dimension(ctx,384);save=ctx['helpers'].save
    for name,value in [('preprocessing',lane['preparation']),('source-contexts',lane['source_contexts']),('training-rows',lane['rows'])]:save(output_dir/'384'/(name+'.json'),value)
    exposed=ctx['parent_runner'].prepare_exposed_sources(ctx,lane)
    save(output_dir/'auxiliary-banks.json',ctx['parent_runner'].prepare_banks(ctx,lane,exposed,deadline))
    return lane


def bind_candidate(ctx,recipe,seed):
    require(recipe in ARMS and seed in FIXED['seed_order'],'unplanned content-matched candidate')
    return ctx['prior_margin'].bind_candidate(ctx,ctx['prior_margin'].ARMS[0],seed)


def train_candidate(ctx,model,seed,recipe):
    require(recipe in ARMS and seed in FIXED['seed_order'],'unplanned content-matched fit')
    extra={} if recipe==ARMS[0] else {'auxiliary_source_modality_sampler':'content_matched_cycles'}
    return ctx['owners']['long_span_source_value_training'].train(model,ctx['rows']['train'],ctx['rows']['validation'],
        training_references=ctx['references']['train'],validation_references=ctx['references']['validation'],
        codec=ctx['donor']['codec'],input_transform=ctx['donor']['input_transform'],lineage=ctx['lineage'],
        validate_rule=ctx['validate_rule'],validator_id=ctx['validator_id'],curriculum=ctx['stages'],
        strategy='semantic_fields',cardinality_weight=.25,count_exposure='balanced_all',source_value_weight=.25,
        source_contexts=ctx['source_contexts'],action_contrastive_weight=.05,generated_boundary_weight=.05,
        generated_boundary_site_policy='first_last',generated_source_margin_weight=0.,generated_source_margin_replay=False,
        non_action_learning_rate_multiplier=10.,auxiliary_source_modality_bank=ctx['modality_banks']['full180'],
        auxiliary_source_modality_weight=.05,generated_boundary_retry_on_mismatch=True,
        config=dict(seed=seed,max_seconds=180,max_target_tokens=512,batch_size=8,learning_rate=.001,max_optimizer_steps=1000,
            patience=0,validation_interval=4,alpha=0.,max_memory_bytes=FIXED['positive_memory_bytes']),**extra)


def fit_and_record(ctx,model,seed,recipe,folder,initial_tensor_sha256):
    started=time.monotonic()
    try:return train_candidate(ctx,model,seed,recipe),time.monotonic()-started
    except Exception as error:
        observed=ctx['core'].tensor_digest(model)
        ctx['helpers'].save(folder/'training-failure.json',dict(schema='content-matched-modality-training-failure/v1',
            seed=seed,dimension=384,recipe=recipe,exception_type=type(error).__name__,exception_message_omitted=True,
            traceback_frames=[dict(file=f.filename,line=f.lineno,function=f.name) for f in traceback.extract_tb(error.__traceback__)],
            initial_caller_tensor_sha256=initial_tensor_sha256,observed_caller_tensor_sha256=observed,
            caller_tensor_unchanged=observed==initial_tensor_sha256,completed_training_report_available=False,
            completed_optimizer_steps=None,elapsed_seconds=time.monotonic()-started,**FALSE));raise


def sampler_inventory(bank,seed,digest):
    strata=[(s.split(':')[0],int(s[-1])) for s in FIXED['auxiliary_strata']];rows=bank['rows'];groups={}
    for index,row in enumerate(rows):
        match=re.fullmatch(r'The (\w+) (?:must not|must|may|is required to|is allowed to|is forbidden to) (\w+) the (\w+)\.',row['source_text'])
        require(match is not None,'unrecognized authenticated training literal')
        content=match.groups();members=groups.setdefault(content,{})
        key=(row['modality'],row['wording_style']);require(key not in members,'duplicate content stratum');members[key]=index
    require(len(rows)==180 and len(groups)==30 and all(set(v)==set(strata) for v in groups.values()),'complete thirty source-content groups required')
    group_order=[dict(actor=key[0],action=key[1],object=key[2],indices=[groups[key][s] for s in strata])
        for key in sorted(groups,key=lambda key:digest([seed,'content_matched_cycles',key]))]
    orders=[sorted([i for i,r in enumerate(rows) if (r['modality'],r['wording_style'])==s],
        key=lambda i:digest([seed,s,rows[i]['source_sha256'],rows[i]['id']])) for s in strata]
    independent=[[order[step%len(order)] for order in orders] for step in range(340)]
    matched=[group_order[step%30]['indices'] if step<330 else independent[step] for step in range(340)]
    require(Counter(i for row in independent for i in row)==Counter(i for row in matched for i in row),'per-source exposure changed')
    return group_order,independent,matched


def validate_auxiliary_report(ctx,report,recipe):
    ctx['parent_runner'].validate_auxiliary_report(ctx,report,ARMS[0])
    digest=ctx['core'].digest;bank=ctx['modality_banks']['full180'];seed=report['config']['seed']
    groups,independent,matched=sampler_inventory(bank,seed,digest);candidate=recipe==ARMS[1]
    cache=report['auxiliary_source_modality_bank_receipt']
    extra={'auxiliary_source_modality_sampler':'content_matched_cycles','auxiliary_source_modality_matched_update_bound':330,
        'auxiliary_source_modality_independent_remainder_updates_planned':10,'auxiliary_source_modality_matched_committed_updates':330,
        'auxiliary_source_modality_independent_remainder_committed_updates':10,'auxiliary_source_modality_full_budget_exposure_equivalence_reached':True}
    if candidate:
        require(all(type(report.get(k)) is type(v) and report[k]==v for k,v in extra.items()),'matched exposure/report differs')
        expected=dict(sampler_policy='content_matched_cycles',content_group_count=30,content_group_order=groups,
            content_group_order_sha256=digest(groups),matched_update_bound=330,independent_remainder_updates=10,
            full_budget_per_source_exposure_matches_independent=True)
        require(all(type(cache.get(k)) is type(v) and cache[k]==v for k,v in expected.items()),'matched cache/group order differs')
    else:require(not any(k in report for k in extra) and 'sampler_policy' not in cache,'default sampler reporting changed')
    observed=Counter()
    for step,update in enumerate(report['committed_updates']):
        value=update['auxiliary_source_modality']['receipt'];expected=(matched if candidate else independent)[step]
        require(value['indices']==expected,'auxiliary source order differs at step '+str(step));observed.update(expected)
        if candidate:
            require(value.get('sampler_policy')=='content_matched_cycles' and value.get('matched_update_bound')==330
                and value.get('sampling_mode')==('content_matched' if step<330 else 'independent_remainder'),'matched cadence differs')
            if step<330:
                g=groups[step%30];require(value.get('content_group_index')==step%30 and value.get('content_cycle_index')==step//30
                    and value.get('content_group')=={k:g[k] for k in ('actor','action','object')},'matched content binding differs')
            else:require(not any(k in value for k in ('content_group_index','content_cycle_index','content_group')),'remainder falsely reports matched content')
        else:require('sampler_policy' not in value,'default per-update receipt changed')
    require(observed==Counter(i for row in independent for i in row) and sorted(observed.values())==[11]*120+[12]*60,'exact11/12 source exposure differs')
    return dict(complete=True,sampler='content_matched_cycles' if candidate else 'independent',
        per_source_presentations={bank['rows'][i]['id']:observed[i] for i in range(180)},
        independent_full_budget_exposure_sha256=digest({bank['rows'][i]['id']:observed[i] for i in range(180)}),
        matched_updates=330 if candidate else 0,independent_updates=10 if candidate else 340,
        compared_to_pure_independent_counter=True,used_for_selection=False)


def baseline_comparable(report):
    value=deepcopy(report);value.pop('elapsed_seconds');value.pop('auxiliary_source_modality_preparation_elapsed_seconds');value['auxiliary_source_modality_bank_receipt'].pop('elapsed_seconds')
    for update in value['committed_updates']:
        update['auxiliary_source_modality']['receipt'].pop('elapsed_seconds');receipt=update['generated_boundary']
        receipt.pop('elapsed_seconds');receipt['generation'].pop('elapsed_seconds');receipt.pop('collection_sha256')
        for attempt in receipt['replay_attempts']:attempt.pop('elapsed_seconds')
    return value


def numerical_comparable(report):
    return {key:value for key,value in report.items()
        if key not in FIXED['control_panel_numerical_equivalence_exclusions']}


def validate_control(ctx,report,panels,states,seed):
    previous=ctx['control_runs'][f'384-aux-full180-{seed}'];manifest=ctx['outer_manifest']
    old=bound_json(manifest,previous['training_ref']['path'],previous['training_ref']['sha256'])
    require(set(old)==set(report) and baseline_comparable(old)==baseline_comparable(report),'R7 full180 numerical control report differs')
    for role in ('initial',*ROLES):
        oldstate=bound_json(manifest,previous['states'][role]['path'],previous['states'][role]['sha256'])
        newstate=json.loads(Path(states[role]['path']).read_bytes())
        require(oldstate['model_state']==newstate['model_state'] and oldstate['tensor_sha256']==newstate['tensor_sha256']
            and oldstate['input_transform']==newstate['input_transform'] and oldstate['codec']==newstate['codec'],'R7 full180 control tensors/preprocessing differ')
    for role in ROLES:
        for label in [*[r[0] for r in CONTROLS],'recurrent-residual-off']:
            ref=previous['postfit'][role][label];oldpanel=bound_json(manifest,ref['path'],ref['sha256']);panel=panels[role][label]
            require(panel['predictions']==oldpanel['predictions'] and numerical_comparable(panel['numerical'])==numerical_comparable(oldpanel['report']), 'R7 full180 control predictions/numerics differ')
    return dict(complete=True,all_tensors_and_predictions_equal=True,numerical_reports_equal=True,
        timing_equality_claimed=False,excluded_fields=deepcopy(FIXED['baseline_equivalence_exclusions']),
        excluded_panel_numerical_fields=deepcopy(FIXED['control_panel_numerical_equivalence_exclusions']),
        collection_digest_exclusion_reason='collection digest includes measured elapsed time; retained rollout evidence compared exactly')


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
    """Open previously exposed labels only after all8 predictions are saved."""
    expected={(f'{d}-{arm["name"]}-{seed}',role) for d,seed,arm in jobs() for role in ROLES}
    require(len(records)==8 and {(r['arm'],r['role']) for r in records}==expected,
        'all8 exposed predictions required before reference load')
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
    return dict(schema='source-modality-exposed-r6-evaluation/v1',complete=len(results)==8,panels=results,
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
    save(args.output/'sealed-recipe.json',dict(plan=ctx['outer_plan'],manifest=ctx['outer_manifest'],tree_pin=ctx['tree'],**FALSE))
    lane=prepare_lane(ctx,args.output,deadline)
    runs=[]; indices=[]
    for dimension,seed,recipe in jobs():
        require(time.monotonic()<deadline, 'comparison deadline exceeded')
        arm_started=time.monotonic(); name=f'{dimension}-{recipe["name"]}-{seed}'; folder=args.output/name
        lane['lineage']['student_lineage']='source_modality_auxiliary_formula_sidecar:'+name
        model=bind_candidate(lane,recipe,seed)
        initial=lane['prior_margin'].validate_initial(lane,model,seed,lane['prior_margin'].ARMS[0])
        save(folder/'initial-parity.json',initial)
        states={'initial':lane['native_runner'].save_state(lane,model,recipe,'initial',False,folder/'initial-state.json')}
        value,fit_seconds=fit_and_record(lane,model,seed,recipe,folder,states['initial']['tensor_sha256'])
        report=value['report']; save(folder/'training.json',report); sampler_validation=validate_auxiliary_report(lane,report,recipe)
        postfit={}
        for role,state,predictions in [('selected',value['state_dict'],value['predictions']),
                ('last-attempt',value['last_complete_attempt_state_dict'],value['last_complete_attempt_predictions'])]:
            require(state is not None, 'complete selected/final state required')
            lane['native_runner'].validate_wrapper_state(lane,state); model.load_state_dict(state,strict=True)
            expected=report['selected_weights_sha256'] if role=='selected' else report['last_complete_attempt_weights_sha256']
            require(lane['core'].tensor_digest(model)==expected, 'training state digest differs')
            states[role]=lane['native_runner'].save_state(lane,model,recipe,role,
                role=='selected' or report['last_complete_attempt_is_selected'],folder/(role+'-state.json'))
            postfit[role]=ctx['parent_runner'].evaluate_original_panels(lane,model,predictions,folder/role)
        replay=validate_control(lane,report,postfit,states,seed) if recipe==ARMS[0] else None
        record=dict(arm=name,dimension=384,seed=seed,recipe=recipe,states=states,initial_parity=initial,
            baseline_replay=replay,sampler_validation=sampler_validation,training_call_elapsed_seconds=fit_seconds,elapsed_seconds=time.monotonic()-arm_started,
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
    for path,digest in ctx['outer_manifest']['inputs'].items():
        require(sha(path)==digest, 'sealed input changed')
    for root,pins in [(args.extension_root,ctx['outer_pins']),(ctx['previous_extension_root'],ctx['previous_manifest']['extensions']),
            (Path(ctx['manifest']['parent_extension_root']),ctx['parent_manifest']['extensions'])]:
        for relative,digest in pins.items():
            require(sha(root/relative)==digest, 'frozen producer changed')
    require(sha(args.plan)==ctx['outer_manifest']['plan_sha256'] and time.monotonic()<deadline, 'plan changed or deadline exceeded')
    save(args.output/'summary.json',dict(schema='content-matched-modality-training-comparison/v1',complete=len(runs)==4,
        runs=indices,exposed_r6_summary_ref=exposed_ref,training_executed=True,dimensions_actually_trained=[384],
        source_dependencies=after,source_overlay=ctx['source_overlay'],all_two_published_384_full180_controls_replayed=True,per_source_auxiliary_exposure_identical=True,
        historical_linguistic_teacher_modified=False,identity_projection_is_not_learned_reconstruction=True,
        elapsed_seconds=time.monotonic()-started,workers=1,bridge_names=[],legal_ir_evaluate_provers=False,
        metric_disk_cache_used=False,encoder_executed=False,downloads_performed=False,**FALSE))


if __name__=='__main__':
    main()
