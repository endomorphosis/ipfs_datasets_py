#!/usr/bin/env python3
"""Paired native-width TRAIN mixture experiment on authenticated cached sources.

The two arms change TRAIN presentation distribution, including rule packing.
They retain original preprocessing and development selection. Old parent setup
reads historical references; no encoder is executed and no proof is admitted.
"""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

AUTO = 'ipfs_datasets_py/logic/formalization/autoencoder/'
PREFIX = 'ipfs_datasets_py.logic.formalization.autoencoder.'
RUNNER = 'scripts/ops/autoencoder/benchmark_training_paraphrase_mixture.py'
PARENT_RUNNER = 'scripts/ops/autoencoder/benchmark_selected_checkpoint_continuation.py'
ARMS = [dict(name='original-only', policy='original_only'),
        dict(name='half-paraphrases', policy='half_paraphrases')]
FALSE = dict(qualified=False, admitted=False, proof_authority=False, formalized=False,
    roundtrip_ok=False, source_semantics_verified=False, checkpoint_promoted=False,
    convergence_proven=False, lake_executed=False, native_validation_executed=False,
    fresh_holdout=False, historical_linguistic_teacher_modified=False)
FIXED = dict(schema='training-paraphrase-mixture-plan/v1', dimensions=[384,768],
    seed=1729, arms=ARMS, fit_count=4, fits_per_dimension=2,
    parent='R13/selected-followup-lr0001-1729/selected', epochs_per_stage=10,
    optimizer_steps_per_fit=170, row_presentations=1220, count_presentations=1220,
    valid_target_token_presentations=112920, source_value_presentations=12800,
    balanced_counts={'1':305,'2':305,'4':305,'8':305}, learning_rate=.0001,
    non_action_learning_rate_multiplier=10., cardinality_weight=.25,
    source_value_weight=.25, action_contrastive_weight=.05, generated_boundary_weight=.05,
    generated_boundary_site_policy='first_last', strict_boundary_retry=True,
    boundary_atol=2e-5, boundary_rtol=2e-5, auxiliary384='original_used113_modality.05',
    auxiliary768=None, auxiliary_presentations384=1020, fresh_optimizer=True,
    fresh_scheduler=True, exact_optimizer_resume=False, selection_unchanged=True,
    preprocessing_refitted=False, architecture_changed=False, context_tokens=512,
    max_target_tokens=512, temperature=0, full_vocabulary_size=32, batch_size=8,
    candidate_original_presentations=610, candidate_augmented_presentations=610,
    candidate_augmented_by_count={'1':240,'2':180,'4':130,'8':60},
    max_seconds_per_fit=180, max_seconds_entire_width=900, max_seconds_per_postfit=30,
    memory_bytes_per_fit=1073741824, cpu_slots_per_width=1, memory_mb_per_width=1536,
    storage_bytes_per_width=400000000, encoder_executed=False, downloads_performed=False,
    preprocessing_owner='original48_train_paragraphs', count_owner='original48_train_paragraphs',
    experiment_scope='TRAIN distribution and rule-packing mixture;not wording-only ablation',
    cache_scope='warm authenticated local vectors;metric disk cache disabled',
    bridge_names=[], legal_ir_evaluate_provers=False, metric_disk_cache_used=False)
PARENT_HASHES = {
 '384': ('0ac5c21656187d1d8040a02bcc0b4716a8093db17f05adc9a22e99d5b6b2cc00',
         '6a527b568c1ec834fc6704a9d12a17532840076432a93dc1390c59c92d483ec3'),
 '768': ('8892a3261c0750a6247ba5400069ed18cad3354426e2095ed1d295287e3559b4',
         '8900d69fb00c17a54b7d3cbe6fbd2c24651b614839ad57c588d0f04dc308fada')}
EVALUATION_DATASETS = ('paragraph_validation','raw_validation','raw_test','raw_canary',
                       'exposed_r6','exposed_r8','exposed_v3')


def require(value, message):
    if not value: raise ValueError(message)


def check_deadline(deadline):
    if time.monotonic() >= deadline: raise TimeoutError('entire-width mixture deadline')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''): h.update(block)
    return h.hexdigest()


def bound(manifest, path, expected=None):
    path = Path(path).resolve(); wanted = manifest['inputs'].get(str(path))
    require(wanted is not None and (expected is None or wanted == expected), 'unbound input: '+str(path))
    raw = path.read_bytes(); require(hashlib.sha256(raw).hexdigest() == wanted, 'changed input: '+str(path))
    return json.loads(raw)


def validate_plan(plan):
    require(type(plan) is dict and all(type(plan.get(k)) is type(v) and
        json.dumps(plan[k],sort_keys=True,allow_nan=False) == json.dumps(v,sort_keys=True,allow_nan=False)
        for k,v in FIXED.items()), 'fixed mixture recipe differs')


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name,path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def package_inventory():
    return {str(Path(module.__file__).resolve()):sha(module.__file__)
        for name,module in list(sys.modules.items())
        if (name == 'ipfs_datasets_py' or name.startswith('ipfs_datasets_py.'))
        and getattr(module,'__file__',None)}


def source_inventory(args, ctx):
    allowed = dict(ctx['mixture_manifest']['producer_pins'])
    allowed.update({str((args.extension_root/rel).resolve()):value
        for rel,value in ctx['mixture_manifest']['extensions'].items()})
    found = package_inventory()
    for path,value in found.items(): require(allowed.get(path) == value, 'unbound resident producer: '+path)
    return found


def recheck(args, manifest, manifest_sha, deadline):
    check_deadline(deadline)
    require(sha(args.manifest) == manifest_sha and sha(args.plan) == manifest['plan_sha256'], 'changed plan/manifest')
    for path,wanted in manifest['inputs'].items():
        check_deadline(deadline); require(sha(path) == wanted, 'changed sealed input: '+path)
    for rel,wanted in manifest['extensions'].items():
        require(sha(args.extension_root/rel) == wanted, 'changed frozen extension: '+rel)
    check_deadline(deadline)


def load_context(args, deadline):
    require(not args.output.exists(), 'fresh output must remain absent through parent context initialization')
    manifest = json.loads(args.manifest.read_bytes()); plan = json.loads(args.plan.read_bytes())
    validate_plan(plan); require(plan['input_sha256'] == manifest['inputs'], 'input plan differs')
    manifest_sha = sha(args.manifest); recheck(args,manifest,manifest_sha,deadline)
    parent = bound(manifest,manifest['parent_manifest']); bound(manifest,manifest['parent_plan'])
    root = Path(manifest['parent_extension_root'])
    require(sha(root/PARENT_RUNNER) == parent['extensions'][PARENT_RUNNER], 'parent runner differs')
    owner = load_module('_mixture_selected_parent',root/PARENT_RUNNER)
    previous = SimpleNamespace(**vars(args)); previous.manifest = Path(manifest['parent_manifest'])
    previous.plan = Path(manifest['parent_plan']); previous.extension_root = root
    ctx = owner.load_context(previous)
    ctx['comparison_owner'].source_inventory(ctx['comparison_parent_args'],ctx)
    # Import the exact R4 native-validation closure before the new trainer overlay.
    preparation = bound(manifest,manifest['preparation_manifest'])
    fresh_manifest = bound(manifest,preparation['parent_manifest'])
    fresh_root = Path(preparation['parent_extension_root'])
    fresh_owner = load_module('_mixture_preparation_parent',fresh_root/'scripts/ops/autoencoder/observe_fresh_normative_style.py')
    fresh_args = SimpleNamespace(**vars(previous)); fresh_args.extension_root = fresh_root
    fresh_ctx = dict(ctx,fresh_manifest=fresh_manifest)
    fresh_owner.load_producers(fresh_args,fresh_ctx)
    package = sys.modules[PREFIX[:-1]]
    for name in ('authored_training_paraphrases','training_paraphrase_source_inputs','contextual_training_mixture'):
        module = ctx['helpers'].extension(args.extension_root,AUTO+name+'.py',PREFIX+name,manifest['extensions'])
        setattr(package,name,module)
        if name == 'contextual_training_mixture': helper = module
    trainer = ctx['helpers'].extension(args.extension_root,AUTO+'long_span_source_value_training.py',
        PREFIX+'_mixture_training_owner',manifest['extensions'])
    ctx['owners']['long_span_source_value_training'] = trainer
    runs = {}
    for width in ('384','768'):
        run = bound(manifest,manifest['endpoint_summaries'][width])
        require(run['arm'] == width+'-selected-followup-lr0001-1729' and run['dimension'] == int(width)
            and run['budget_completed'] is True and run['recipe'] == dict(name='continue-lr0001',learning_rate=.0001), 'selected R13 parent differs')
        ref = run['states']['selected']; require((ref['sha256'],ref['tensor_sha256']) == PARENT_HASHES[width], 'selected parent identity differs')
        bound(manifest,ref['path'],ref['sha256']); runs[width] = run
    ctx.update(mixture_manifest=manifest,mixture_plan=plan,mixture_owner=owner,
        mixture_helper=helper,mixture_preparation=preparation,mixture_parents=runs,
        mixture_manifest_sha=manifest_sha)
    source_inventory(args,ctx); check_deadline(deadline)
    return ctx


def evaluation_vectors(manifest, preparation, width, prior):
    """Declare all named inventories; absent vectors remain explicit empty lists."""
    def normal(text): return ' '.join(text.split()).casefold()
    sets = {name:{normal(text) for row in prior[name] for text in
        [row['source_text'],*row['source_text'].split('\n\n')]} for name in EVALUATION_DATASETS}
    result = {name:[] for name in EVALUATION_DATASETS}; seen = {name:set() for name in result}
    for descriptor in preparation['prior_vector_rows'][str(width)]:
        rows = bound(manifest,descriptor['path'])
        for key in descriptor['keys']: rows = rows[key]
        for row in rows:
            value = {k:row[k] for k in ('id','source_text','input')}
            require(len(value['input']) == width, 'prior vector width differs')
            key = json.dumps(value,sort_keys=True,allow_nan=False)
            for name,texts in sets.items():
                if normal(value['source_text']) in texts and key not in seen[name]:
                    seen[name].add(key); result[name].append(value)
    return result


def envelope(ctx, width, policy):
    manifest = ctx['mixture_manifest']; artifacts = manifest['preparation_artifacts']
    read = lambda name:bound(manifest,artifacts[name])
    prior = read('prior-source-inventories.json')
    result = dict(policy=policy,training_bank=read('original-training-bank-used.json'),
        prior_sources_by_dataset=prior,corpus=dict(source_rows=read('source-rows.json'),
        references=read('training-references.json'),receipt=read('training-corpus-receipt.json')),
        source_plan=read('source-plan.json'),source_inputs=read(f'dimension-inputs-{width}.json'),
        production_report=read(f'production-{width}.json'),
        evaluation_vectors_by_dataset=evaluation_vectors(manifest,ctx['mixture_preparation'],width,prior))
    result['payload_sha256'] = ctx['mixture_helper'].digest(result)
    return result


def prepare_selector(ctx, lane, mixture, deadline):
    return ctx['mixture_helper'].prepare(lane['rows']['train'],lane['rows']['validation'],
        training_references=lane['references']['train'],validation_references=lane['references']['validation'],
        source_contexts=lane['source_contexts'],codec=lane['donor']['codec'],
        validate_rule=lane['validate_rule'],mixture=mixture,deadline=deadline)


def schedule_receipt(lane, selector, deadline):
    """Replay only the inherited private permutation stream; no fitting/forward."""
    torch = lane['core']._torch(); generator = torch.Generator().manual_seed(1729)
    by_id = {r['id']:r for r in lane['rows']['train']}; draws = []; exposures = Counter(); count_rows = []
    trainer = lane['owners']['long_span_source_value_training']
    counts = trainer._BalancedCountSelector(lane['rows']['train'],trainer._count_labels(lane['references']['train']),1729)
    for stage in lane['stages']:
        rows = [by_id[identity] for identity in stage['training_ids']]
        for _ in range(stage['epochs']):
            order = torch.randperm(len(rows),generator=generator).tolist()
            for offset in range(0,len(rows),8):
                check_deadline(deadline)
                effective = selector.select([rows[i] for i in order[offset:offset+8]],deadline=deadline)
                item = selector.record_commit(len(draws)); draws.append(item)
                count_rows.append([row['id'] for row in counts.take(len(effective))])
                for parent,row,count in zip(item['parent_ids'],effective,item['clause_counts']):
                    if parent != row['id']: exposures[str(count)] += 1
    snapshot = selector.snapshot()
    require(len(draws) == 170 and snapshot['committed_rows'] == 1220
        and sum(d['target_token_presentations'] for d in draws) == 112920
        and sum(d['source_value_presentations'] for d in draws) == 12800, 'preflight work budget differs')
    replaced = 610 if snapshot['policy'] == 'half_paraphrases' else 0
    require(snapshot['committed_replacements'] == replaced, 'mixture replacement budget differs')
    if replaced: require(dict(exposures) == FIXED['candidate_augmented_by_count'], 'count mixture exposures differ')
    return dict(snapshot=snapshot,draws=draws,count_row_ids=count_rows,augmented_by_count=dict(exposures),
        optimizer_executed=False,model_forward_executed=False,**FALSE)


def train_candidate(lane, model, mixture, deadline):
    check_deadline(deadline)
    auxiliary = {} if lane['dimension'] != 384 else dict(
        auxiliary_source_modality_bank=lane['modality_banks']['used113'],auxiliary_source_modality_weight=.05)
    return lane['owners']['long_span_source_value_training'].train(model,lane['rows']['train'],lane['rows']['validation'],
        training_references=lane['references']['train'],validation_references=lane['references']['validation'],
        codec=lane['donor']['codec'],input_transform=lane['donor']['input_transform'],lineage=lane['lineage'],
        validate_rule=lane['validate_rule'],validator_id=lane['validator_id'],curriculum=lane['stages'],
        strategy='semantic_fields',cardinality_weight=.25,count_exposure='balanced_all',source_value_weight=.25,
        source_contexts=lane['source_contexts'],action_contrastive_weight=.05,generated_boundary_weight=.05,
        generated_boundary_site_policy='first_last',generated_boundary_retry_on_mismatch=True,
        generated_source_margin_weight=0.,generated_source_margin_replay=False,
        non_action_learning_rate_multiplier=10.,source_training_mixture=mixture,training_deadline=deadline,
        config=dict(seed=1729,max_seconds=min(180.,deadline-time.monotonic()),max_target_tokens=512,batch_size=8,
            learning_rate=.0001,max_optimizer_steps=1000,patience=0,validation_interval=4,alpha=0.,
            max_memory_bytes=1073741824),**auxiliary)


def bounded_evaluate(lane, model, split, control, deadline):
    check_deadline(deadline)
    local = dict(lane,plan=dict(lane['plan'],max_seconds_per_postfit=min(30.,deadline-time.monotonic())))
    result = lane['clause_runner'].evaluate(local,model,split,control)
    check_deadline(deadline)
    return result


def original_panels(lane, model, predictions, folder, deadline):
    """Keep inherited panel math; propagate the enclosing deadline per panel.

    The legacy diagnostic owns a fixed thirty-second cooperative bound. Refuse
    to begin it without that entire remaining allowance; the guardian handles
    a kernel that fails to return. Saving is checked before and after as well.
    """
    panels = {}; owner = lane['continuation_runner']; save = lane['helpers'].save
    controls = [(label,split,control,model) for label,split,control in owner.CONTROLS]
    controls.append(('recurrent-residual-off','validation','conditioned',None))
    for label,split,control,working in controls:
        if working is None:
            check_deadline(deadline)
            working = lane['owners']['ordered_clause_recurrent_decoder_experiment'].bind_residual_off_model(model)
            check_deadline(deadline)
        panel = bounded_evaluate(lane,working,split,control,deadline)
        if label == 'validation': require(panel['predictions'] == predictions, 'saved endpoint generation differs')
        if label == 'recurrent-residual-off':
            panel['execution'].update(kind='recurrent_residual_off',recurrent_residual_disabled=True,
                selection_performed=False,training_performed=False)
        require(deadline-time.monotonic() >= 30., 'insufficient deadline for inherited residual diagnostic')
        panel['recurrent_residual_diagnostic'] = lane['prior_margin'].recurrent_residual_diagnostic(lane,working,split,control)
        check_deadline(deadline); save(folder/('evaluation-'+label+'.json'),panel); check_deadline(deadline)
        panels[label] = lane['prior'].compact_panel(panel,retain_predictions=True)
    require(set(panels) == {'training','validation','zero-condition','source-shuffle','cross-length-shuffle',
        'context-only-shuffle','context-reverse','context-rotate','recurrent-residual-off'}, 'complete original panel inventory required')
    return panels


def validate_report(lane, report, parent_sha, expected_schedule):
    lane['selected_runner'].validate_report(lane,report,dict(name='continue-lr0001',learning_rate=.0001),parent_sha)
    actual = [update['source_training_mixture'] for update in report['committed_updates']]
    require(actual == expected_schedule['draws'], 'committed mixture draws differ from predeclared schedule')
    require([u['count_row_ids'] for u in report['committed_updates']] == expected_schedule['count_row_ids'],
        'original count stream differs from predeclared schedule')
    if lane.get('dimension') == 384:
        require([u['auxiliary_source_modality']['receipt']['row_ids'] for u in report['committed_updates']]
            == expected_schedule['original_auxiliary_row_ids'], 'original384 auxiliary stream changed')


def bind_independent_schedule(ctx, lane, schedule, parent):
    manifest = ctx['mixture_manifest']; width = str(lane['dimension'])
    expected = bound(manifest,manifest['independent_schedules'][width])
    require(len(expected) == len(schedule['draws']) == 170, 'independent schedule length differs')
    for index,(item,other) in enumerate(zip(schedule['draws'],expected)):
        require(item['parent_ids'] == other['parent_ids'] and schedule['count_row_ids'][index] == other['count_ids'],
            'independent original/count schedule differs')
        wanted = other['effective_ids'] if schedule['snapshot']['policy'] == 'half_paraphrases' else other['parent_ids']
        require(item['effective_ids'] == wanted, 'independent effective schedule differs')
    old = bound(manifest,parent['training_ref']['path'],parent['training_ref']['sha256'])
    if lane['dimension'] == 384:
        schedule['original_auxiliary_row_ids'] = [u['auxiliary_source_modality']['receipt']['row_ids'] for u in old['committed_updates']]
        require(len(schedule['original_auxiliary_row_ids']) == 170, 'original384 auxiliary schedule absent')
    schedule['independent_schedule_sha256'] = manifest['inputs'][manifest['independent_schedules'][width]]
    schedule['independent_schedule_equal'] = True


def execute(args):
    started = time.monotonic(); deadline = started+FIXED['max_seconds_entire_width']
    require(args.dimension in (384,768), 'explicit native width required')
    ctx = load_context(args,deadline); before = source_inventory(args,ctx); save = ctx['helpers'].save
    args.output.mkdir(parents=True)
    save(args.output/'sealed-recipe.json',dict(plan=ctx['mixture_plan'],manifest=ctx['mixture_manifest'],**FALSE))
    lane = ctx['mixture_owner'].prepare_lane(ctx,args.dimension)
    lane['continuation_manifest'] = ctx['mixture_manifest']; check_deadline(deadline)
    parent = ctx['mixture_parents'][str(args.dimension)]; ref = parent['states']['selected']
    for label,value in [('preprocessing',lane['preparation']),('source-contexts',lane['source_contexts']),('training-rows',lane['rows'])]:
        save(args.output/(label+'.json'),value)
    runs = []
    for arm in ARMS:
        check_deadline(deadline); folder = args.output/arm['name']
        mixture = envelope(ctx,args.dimension,arm['policy']); mixture_ref = save(folder/'mixture-inputs.json',mixture)
        schedule = schedule_receipt(lane,prepare_selector(ctx,lane,mixture,deadline),deadline)
        bind_independent_schedule(ctx,lane,schedule,parent)
        schedule_ref = save(folder/'predeclared-schedule.json',schedule)
        model = ctx['mixture_owner'].restore_endpoint(lane,parent,'selected')
        require(lane['core'].tensor_digest(model) == ref['tensor_sha256'], 'exact parent tensor parity required')
        initial = bounded_evaluate(lane,model,'validation','conditioned',deadline)
        oldref = parent['postfit']['selected']['validation']; old = bound(ctx['mixture_manifest'],oldref['path'],oldref['sha256'])
        require(initial['predictions'] == old['predictions'], 'original development prediction parity differs')
        initial_ref = save(folder/'parent-validation.json',initial)
        parity = dict(predictions_equal=True,rows=len(initial['predictions']),parent_tensor_sha256=ref['tensor_sha256'],
            restored_tensor_sha256=lane['core'].tensor_digest(model),parent_prediction_ref=oldref,restored_prediction_ref=initial_ref)
        if args.phase == 'preflight':
            runs.append(dict(arm=arm['name'],dimension=args.dimension,initial_parity=parity,
                mixture_inputs=mixture_ref,schedule=schedule_ref)); del model; continue
        states = {'initial':lane['native_runner'].save_state(lane,model,arm,'initial',False,folder/'initial-state.json')}
        fit_started = time.monotonic()
        try:
            value = train_candidate(lane,model,mixture,deadline)
        except BaseException as error:
            save(folder/'training-failure.json',dict(error_type=type(error).__name__,
                caller_tensor_sha256=lane['core'].tensor_digest(model),parent_tensor_sha256=ref['tensor_sha256'],
                initial_state=states['initial'],complete=False,partial_internal_state_available=False,**FALSE))
            raise
        fit_seconds = time.monotonic()-fit_started; report = value['report']
        report_ref = save(folder/'training.json',report)
        # Retain both available endpoints even when full-budget/deadline validation
        # rejects the comparison. A selected-within-partial-fit flag is not acceptance.
        for role,state in [('selected',value['state_dict']),('last-attempt',value['last_complete_attempt_state_dict'])]:
            if state is None: continue
            lane['native_runner'].validate_wrapper_state(lane,state); model.load_state_dict(state,strict=True)
            states[role] = lane['native_runner'].save_state(lane,model,arm,role,
                role == 'selected' or report['last_complete_attempt_is_selected'],folder/(role+'-state.json'))
        save(folder/'retained-endpoints.json',dict(states=states,training_ref=report_ref,
            full_budget_validation_completed=False,comparison_accepted=False,**FALSE))
        check_deadline(deadline); validate_report(lane,report,ref['tensor_sha256'],schedule)
        panels = {}
        for role,state,predictions in [('selected',value['state_dict'],value['predictions']),
            ('last-attempt',value['last_complete_attempt_state_dict'],value['last_complete_attempt_predictions'])]:
            check_deadline(deadline); require(state is not None,'complete endpoint required')
            lane['native_runner'].validate_wrapper_state(lane,state); model.load_state_dict(state,strict=True)
            expected = report['selected_weights_sha256'] if role == 'selected' else report['last_complete_attempt_weights_sha256']
            require(lane['core'].tensor_digest(model) == expected, 'endpoint tensor differs')
            compact = original_panels(lane,model,predictions,folder/role,deadline)
            require(len(compact) == 9, 'all nine original panels required'); check_deadline(deadline)
            panels[role] = {label:dict(path=str(folder/role/('evaluation-'+label+'.json')),
                sha256=sha(folder/role/('evaluation-'+label+'.json')),numerical=p['numerical'],fidelity=p['source_fidelity'])
                for label,p in compact.items()}
        record = dict(arm=arm['name'],dimension=args.dimension,seed=1729,recipe=arm,parent_state=ref,
            initial_parity=parity,mixture_inputs=mixture_ref,schedule=schedule_ref,states=states,
            training_ref=report_ref,postfit=panels,budget_completed=True,fresh_optimizer=True,
            exact_optimizer_resume=False,encoder_executed=False,training_call_elapsed_seconds=fit_seconds,
            training_rows_per_second=1220/fit_seconds,**FALSE)
        saved = save(folder/'summary.json',record); runs.append(dict(arm=arm['name'],summary_path=saved['path'],summary_sha256=saved['sha256']))
        print(json.dumps(dict(dimension=args.dimension,arm=arm['name'],steps=report['optimizer_steps'],fit_seconds=fit_seconds)),flush=True)
        del model,value,report,compact,initial,old,mixture,schedule
    after = source_inventory(args,ctx)
    require(all(after.get(k) == v for k,v in before.items()), 'resident source changed')
    recheck(args,ctx['mixture_manifest'],ctx['mixture_manifest_sha'],deadline)
    result = dict(schema='training-paraphrase-mixture-comparison/v1',complete=len(runs)==2,
        phase=args.phase,dimension=args.dimension,runs=runs,source_dependencies=after,
        elapsed_seconds=time.monotonic()-started,encoder_executed=False,cache_scope=FIXED['cache_scope'],
        timing_scope='sequential arms within width; other width may share host under separate scheduler lease',**FALSE)
    save(args.output/'summary.json',result); return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('dependency-root','extension-root','manifest','plan','output'): parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--phase',choices=['preflight','training'],required=True)
    parser.add_argument('--dimension',type=int,choices=[384,768],required=True)
    execute(parser.parse_args())


if __name__ == '__main__': main()
