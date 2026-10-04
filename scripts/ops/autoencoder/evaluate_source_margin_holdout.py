#!/usr/bin/env python3
"""Evaluate all sealed source-margin states on authored postfit sources once.

All36 source-only prediction files are persisted before holdout references are
opened. Label scoring and teacher-forced CE never repeat greedy generation and
never select or update a model. This authored fixture is not Lake admission.
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
ARMS = ['source-head-lr10', 'source-margin-zero', 'source-margin-001']
ROLES = ['last-attempt', 'selected']
FALSE = dict(training_executed=False, encoder_executed=False, downloads_performed=False,
    qualified=False, admitted=False, proof_authority=False, source_semantics_verified=False,
    checkpoint_promoted=False, convergence_proven=False, lake_executed=False,
    native_validation_executed=False, formalized=False, roundtrip_ok=False,
    selection_performed=False, historical_linguistic_teacher_modified=False)
FIXED = dict(schema='source-margin-holdout-evaluation-plan/v1', dimensions=[8,384,768],
    seed_order=[1729,2718], arms=ARMS, roles=ROLES, fit_count=18, state_count=36,
    panel_count=36, samples_per_panel=48, batch_size=8, workers=1,
    fixed_encoder_context_tokens=512, fixed_decoder_output_limit=512, temperature=0,
    vocabulary_size=32, greedy_passes_per_panel=1, optimizer_steps=0,
    primary_endpoint='last-attempt', secondary_endpoint='existing_development_selected',
    all_predictions_persisted_before_reference_load=True, generation_reference_access=False,
    posthoc_reference_scoring=True, teacher_forced_ce_is_not_generated_fidelity=True,
    preprocessing='reuse_saved_training_only_transform_and_normalization',
    comparison_scope='new_authored_templates_and_pairs;not_statutory_or_corpus_qualification',
    preserve_weights=True, selection_unchanged=True, max_seconds_per_panel=30,
    max_seconds_entire_run=600, bridge_names=[], legal_ir_evaluate_provers=False,
    metric_disk_cache_used=False, **FALSE)


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            value.update(block)
    return value.hexdigest()


def validate_plan(plan):
    require(type(plan) is dict and all(type(plan.get(k)) is type(v) and
        json.dumps(plan[k], sort_keys=True, allow_nan=False) == json.dumps(v, sort_keys=True, allow_nan=False)
        for k,v in FIXED.items()), 'fixed source-margin holdout evaluation plan differs')


def jobs():
    return [(dimension, seed, arm) for dimension in FIXED['dimensions']
        for seed in FIXED['seed_order'] for arm in ARMS]


def load_helper(root, pins, path, name):
    require(sha(root/path) == pins[path], 'frozen helper differs: '+path)
    spec = importlib.util.spec_from_file_location(name, root/path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bound_json(manifest, path, expected=None):
    path = Path(path).resolve()
    wanted = manifest['inputs'].get(str(path))
    require(wanted is not None and (expected is None or wanted == expected), 'unbound artifact alias: '+str(path))
    require(sha(path) == wanted, 'sealed artifact differs: '+str(path))
    return json.loads(path.read_bytes())


def validate_saved_runs(manifest, summary):
    require(summary.get('schema') == 'source-margin-training-comparison/v1' and summary.get('complete') is True
        and summary.get('training_executed') is True and summary.get('all_six_published_source_head_lr10_baselines_replayed') is True,
        'complete eighteen-fit training comparison required')
    expected = [f'{d}-{arm}-{seed}' for d,seed,arm in jobs()]
    records = summary.get('runs')
    require(type(records) is list and [r.get('arm') for r in records] == expected
        and set(manifest['saved_summaries']) == set(expected), 'exact eighteen saved run identities required')
    runs = {}
    for item,(dimension,seed,arm) in zip(records,jobs()):
        name = item['arm']
        require(Path(manifest['saved_summaries'][name]).resolve() == Path(item['summary_path']).resolve(),
            'saved run alias differs')
        run = bound_json(manifest, item['summary_path'], item['summary_sha256'])
        require(run.get('arm') == name and run.get('dimension') == dimension and run.get('seed') == seed
            and run.get('recipe',{}).get('name') == arm and run.get('budget_completed') is True, 'incomplete saved run')
        training = bound_json(manifest, run['training_ref']['path'], run['training_ref']['sha256'])
        require(training.get('stopped_reason') == 'epochs_completed' and training.get('optimizer_steps') == 340,
            'incomplete saved training exposure')
        for role in ROLES:
            ref = run['states'][role]
            require(manifest['inputs'].get(str(Path(ref['path']).resolve())) == ref['sha256']
                and sha(ref['path']) == ref['sha256'], 'unbound saved state')
        runs[name] = run
    return runs


def _source_only(value):
    """Reject embedded reference material, even in unused source metadata."""
    if type(value) is dict:
        require(not {'target', 'target_ids', 'target_token_ids', 'rules', 'references', 'components',
            'training_pair_seen'} & set(value), 'reference material in source-only inputs')
        for child in value.values():
            _source_only(child)
    elif type(value) is list:
        for child in value:
            _source_only(child)


def load_context(args):
    manifest = json.loads(args.manifest.read_bytes())
    plan = json.loads(args.plan.read_bytes())
    validate_plan(plan)
    require(sha(args.plan) == manifest['plan_sha256'] and plan['input_sha256'] == manifest['inputs'],
        'sealed evaluation inputs differ')
    for path,wanted in manifest['inputs'].items():
        require(sha(path) == wanted, 'sealed input changed: '+path)
    for path,wanted in manifest['extensions'].items():
        require(sha(args.extension_root/path) == wanted, 'frozen extension differs: '+path)
    for key in ('parent_manifest', 'parent_plan', 'training_summary', 'source_inputs', 'references', 'holdout_receipt'):
        require(str(Path(manifest[key]).resolve()) in manifest['inputs'], 'unbound manifest alias: '+key)
    require(len({str(Path(manifest[k]).resolve()) for k in ('source_inputs','references','holdout_receipt')}) == 3,
        'source and label artifacts must be separate')
    parent = bound_json(manifest, manifest['parent_manifest'])
    require(sha(manifest['parent_plan']) == parent['plan_sha256'] == manifest['comparison_seal'],
        'training comparison seal differs')
    parent_plan = bound_json(manifest, manifest['parent_plan'])
    for path,wanted in parent['extensions'].items():
        require(manifest['extensions'].get(path) == wanted, 'saved training producer differs: '+path)
    runner = load_helper(args.extension_root, manifest['extensions'],
        'scripts/ops/autoencoder/benchmark_source_margin_training.py', '_margin_training_runner')
    runner.validate_plan(parent_plan)
    runs = validate_saved_runs(manifest, bound_json(manifest, manifest['training_summary']))
    native = load_helper(args.extension_root, manifest['extensions'],
        'scripts/ops/autoencoder/benchmark_native_dimension_source_training.py', '_holdout_native_runner')
    # Only the original training/development labels are available in this loader.
    # Fresh reference and holdout-receipt bytes have only been hashed above.
    oldargs = SimpleNamespace(**vars(args))
    oldargs.manifest = Path(parent['parent_manifest']); oldargs.plan = Path(parent['parent_plan'])
    bound_json(manifest, oldargs.manifest); bound_json(manifest, oldargs.plan)
    ctx = native.load_context(oldargs)
    for name in ('action_factorized_clause_decoder_experiment', 'ordered_clause_recurrent_decoder_experiment'):
        ctx['owners'][name] = ctx['helpers'].extension(args.extension_root, AUTO+name+'.py', PREFIX+name,
            manifest['extensions'])
    source_inputs = bound_json(manifest, manifest['source_inputs'])
    _source_only(source_inputs)
    require(source_inputs.get('schema') == 'fresh-scalar-source-inputs/v1'
        and source_inputs.get('complete') is True and set(source_inputs.get('dimensions', {})) == {'8','384','768'}
        and source_inputs.get('inputs_sha256') == ctx['core'].digest({k:v for k,v in source_inputs.items() if k != 'inputs_sha256'}),
        'complete authenticated holdout source inputs required')
    source_order = [[{k:r[k] for k in ('id','source_text')} for r in source_inputs['dimensions'][str(d)]['rows']]
        for d in FIXED['dimensions']]
    require(source_order[0] == source_order[1] == source_order[2], 'holdout sources differ across dimensions')
    ctx.update(manifest=manifest, plan=plan, pins=manifest['extensions'], training_runner=runner,
        native_runner=native, saved_runs=runs, fresh_inputs=source_inputs)
    return ctx


def prepare_lane(ctx, dimension):
    lane = ctx['native_runner'].prepare_dimension(ctx, dimension)
    first = ctx['saved_runs'][f'{dimension}-{ARMS[0]}-{FIXED["seed_order"][0]}']
    folder = Path(ctx['manifest']['saved_summaries'][first['arm']]).parent.parent/str(dimension)
    for name,value in [('preprocessing.json', lane['preparation']), ('source-contexts.json', lane['source_contexts']),
        ('training-rows.json', lane['rows'])]:
        require(bound_json(ctx['manifest'], folder/name) == value, 'saved training preprocessing differs: '+name)
    data = ctx['fresh_inputs']['dimensions'][str(dimension)]
    rows = data['rows']
    require(type(rows) is list and len(rows) == 48 and all(type(r) is dict and
        set(r) == {'id','input','source_text'} for r in rows), 'closed48 holdout sources required')
    for row in rows:
        ctx['core']._vector(row['input'], dimension)
    owner = ctx['owners']['clause_source_context']
    contexts = owner.build_source_contexts([{k:r[k] for k in ('id','source_text')} for r in rows], data['clause_cache'])
    require(contexts == data['source_contexts'], 'holdout context reconstruction differs')
    binding = owner.validate_contexts(rows, contexts)
    require(binding['dimension'] == dimension, 'holdout source dimension differs')
    normalize = lambda text: ' '.join(text.casefold().split())
    old = [row for split in ('train','validation') for row in lane['rows'][split]]
    require(not {r['id'] for r in rows} & {r['id'] for r in old}
        and not {normalize(r['source_text']) for r in rows} & {normalize(r['source_text']) for r in old},
        'holdout paragraph overlaps training/development')
    old_clauses = {normalize(piece) for r in old for piece in r['source_text'].split('\n\n')}
    require(not {normalize(piece) for r in rows for piece in r['source_text'].split('\n\n')} & old_clauses,
        'holdout clause overlaps training/development')
    lane.update(fresh_rows=rows, fresh_contexts=contexts, fresh_source_binding=binding)
    return lane


def restore_state(ctx, lane, run, role):
    require(role in ROLES and run['dimension'] == lane['dimension'] and run['seed'] in FIXED['seed_order'],
        'unregistered saved role or dimension')
    recipes = {r['name']:r for r in ctx['training_runner'].ARMS}
    require(run['recipe'] == recipes.get(run['recipe']['name']), 'saved recipe differs')
    ref = run['states'][role]
    state = bound_json(ctx['manifest'], ref['path'], ref['sha256'])
    require(state.get('schema') == 'private-native-dimension-source-state/v1' and state.get('role') == role
        and state.get('dimension') == run['dimension'] and state.get('recipe') == run['recipe']
        and state.get('codec') == lane['donor']['codec'] and state.get('input_transform') == lane['donor']['input_transform']
        and state.get('weights_sha256') == ctx['core'].digest(state['model_state'])
        and state.get('tensor_sha256') == ref['tensor_sha256'], 'saved state metadata or weights differ')
    require(all(state.get(flag) is False for flag in ('qualified','admitted','proof_authority','checkpoint_promoted')),
        'unqualified saved state authority differs')
    model = ctx['training_runner'].bind_candidate(lane, run['recipe'], run['seed'])
    require(model.describe() == state['architecture'], 'saved decoder architecture differs')
    restored = ctx['clause_runner'].restored_tensors(lane, state['model_state'], model.state_dict())
    ctx['native_runner'].validate_wrapper_state(lane, restored)
    model.load_state_dict(restored, strict=True)
    require(ctx['core'].tensor_digest(model) == state['tensor_sha256'], 'restored tensor digest differs')
    return model, state


def generate_panel(ctx, lane, model, deadline):
    torch = ctx['core']._torch(); core = ctx['core']; started = time.monotonic()
    require(started < deadline, 'generation deadline exceeded')
    rows = lane['fresh_rows']; contexts = lane['fresh_contexts']; transform = lane['donor']['input_transform']
    require(all(set(row) == {'id','input','source_text'} for row in rows), 'generation sources contain labels')
    before = core.tensor_digest(model); modes = {name:m.training for name,m in model.named_modules()}
    predictions = []; reconstruction_sum = 0.
    try:
        model.eval()
        with torch.inference_mode():
            for offset in range(0,len(rows),8):
                require(time.monotonic() < deadline, 'generation deadline exceeded')
                part = rows[offset:offset+8]
                data = ctx['native_runner'].transformed_rows(torch, part, transform)
                generated = core._greedy(torch, model, data, 512, len(lane['donor']['codec']['target_vocabulary']),
                    deadline, **core._source_context_kwargs(torch, part, contexts, transform))
                require(generated is not None, 'incomplete holdout generation')
                reconstruction_sum += float((generated[0]-data).square().sum())*transform['scale']**2
                predictions.extend(dict(id=row['id'], token_ids=tokens, generation_status=status,
                    eos_reached=status == 'eos') for row,tokens,status in zip(part, generated[1], generated[2]))
    finally:
        for name,part in model.named_modules():
            part.training = modes[name]
    require(core.tensor_digest(model) == before, 'generation changed saved model')
    require(time.monotonic() < deadline and len(predictions) == len(rows), 'incomplete timed generation')
    return dict(schema='source-margin-holdout-predictions/v1', complete=True, predictions=predictions,
        source_rows_sha256=core.digest(rows), source_contexts_sha256=core.digest(contexts),
        model_tensor_sha256=before, generation_temperature=0, max_target_tokens=512, batch_size=8,
        reconstructed_input_mse=reconstruction_sum/(len(rows)*model.dimension),
        identity_projection_is_not_learned_reconstruction=True, generation_reference_access=False,
        greedy_passes_per_row=1, elapsed_seconds=time.monotonic()-started, **FALSE)


def load_fresh_references(ctx, prediction_records):
    """The single reference-material entry point, gated by every saved prediction."""
    require(len(prediction_records) == FIXED['panel_count'] and
        {(r['arm'],r['role']) for r in prediction_records} ==
        {(f'{d}-{arm}-{seed}',role) for d,seed,arm in jobs() for role in ROLES},
        'all36 predictions must exist before references are opened')
    expected_ids = [r['id'] for r in ctx['fresh_inputs']['dimensions']['8']['rows']]
    for record in prediction_records:
        require(sha(record['predictions_ref']['path']) == record['predictions_ref']['sha256'],
            'persisted predictions changed before label load')
        saved = json.loads(Path(record['predictions_ref']['path']).read_bytes())
        require(saved.get('complete') is True and [r.get('id') for r in saved.get('predictions',[])] == expected_ids
            and saved.get('model_tensor_sha256') == record['state_ref']['tensor_sha256']
            and saved.get('generation_reference_access') is False, 'incomplete or mismatched persisted predictions')
    references = bound_json(ctx['manifest'], ctx['manifest']['references'])
    receipt = bound_json(ctx['manifest'], ctx['manifest']['holdout_receipt'])
    core = ctx['core']; rows = ctx['fresh_inputs']['dimensions']['8']['rows']
    source_rows = [{k:r[k] for k in ('id','source_text')} for r in rows]
    require(type(references) is list and len(references) == 48 and receipt.get('complete') is True
        and receipt.get('schema') == 'authored-scalar-holdout/v1'
        and receipt.get('receipt_sha256') == core.digest({k:v for k,v in receipt.items() if k != 'receipt_sha256'})
        and receipt.get('references_sha256') == core.digest(references)
        and receipt.get('source_rows_sha256') == core.digest(source_rows)
        and receipt.get('sealed_comparison_sha256') == ctx['manifest']['comparison_seal']
        and receipt.get('codec_sha256') == core.digest(ctx['donor']['codec']), 'holdout references or comparison binding differs')
    require([r['id'] for r in references] == [r['id'] for r in rows], 'holdout reference identities differ')
    for reference,source in zip(references, rows):
        ids = reference['target_ids']; vocabulary = ctx['donor']['codec']['target_vocabulary']
        require(reference['source_text'] == source['source_text'] and reference['source_sha256'] ==
            hashlib.sha256(source['source_text'].encode()).hexdigest() and reference.get('split') == 'fresh_authored_holdout'
            and reference.get('codec_sha256') == core.digest(ctx['donor']['codec'])
            and reference.get('target_sha256') == core.digest(reference['target']), 'holdout reference provenance differs')
        require(type(ids) is list and 3 <= len(ids) <= 512 and ids[0] == 1 and ids[-1] == 2
            and all(type(token) is int and 3 <= token < len(vocabulary) for token in ids[1:-1])
            and json.loads(''.join(vocabulary[token] for token in ids[1:-1])) == reference['target'],
            'complete unchanged-vocabulary holdout targets required')
    return references, receipt


def score_panel(ctx, lane, model, prediction, references, deadline):
    core = ctx['core']; torch = core._torch(); started = time.monotonic()
    require(started < deadline, 'posthoc panel deadline exceeded')
    before = core.tensor_digest(model)
    require(len(references) == len(lane['fresh_rows']) and all(reference['id'] == source['id']
        and reference['source_text'] == source['source_text'] for reference,source in zip(references,lane['fresh_rows'])),
        'posthoc references differ from source rows')
    require(prediction['complete'] is True and prediction['model_tensor_sha256'] == before
        and prediction['source_rows_sha256'] == core.digest(lane['fresh_rows'])
        and prediction['source_contexts_sha256'] == core.digest(lane['fresh_contexts']), 'saved prediction binding differs')
    fidelity = ctx['scorer'].score_predictions(references, prediction['predictions'],
        codec=lane['donor']['codec'], validate_rule=lane['validate_rule'], output_limit=512,
        validator_id=lane['validator_id'])
    by_family = {}
    for family in sorted({r['template_family'] for r in references}):
        subset = [r for r in references if r['template_family'] == family]; identities = {r['id'] for r in subset}
        by_family[family] = ctx['scorer'].score_predictions(subset,
            [p for p in prediction['predictions'] if p['id'] in identities], codec=lane['donor']['codec'],
            validate_rule=lane['validate_rule'], output_limit=512, validator_id=lane['validator_id'])
    by_pair_stratum = {}
    pair_groups = {}
    for reference in references:
        components = reference.get('components')
        require(type(components) is list and len(components) == reference['clause_count']
            and [c.get('slot') for c in components] == list(range(reference['clause_count']))
            and all(type(c.get('training_pair_seen')) is bool for c in components),
            'complete authored pair strata required')
        seen = [c['training_pair_seen'] for c in components]
        stratum = 'all_seen' if all(seen) else 'all_unseen' if not any(seen) else 'mixed'
        pair_groups.setdefault(stratum, []).append(reference)
    for stratum,subset in sorted(pair_groups.items()):
        identities = {r['id'] for r in subset}
        by_pair_stratum[stratum] = ctx['scorer'].score_predictions(subset,
            [p for p in prediction['predictions'] if p['id'] in identities], codec=lane['donor']['codec'],
            validate_rule=lane['validate_rule'], output_limit=512, validator_id=lane['validator_id'])
    rows = [dict(source, target_ids=reference['target_ids']) for source,reference in zip(lane['fresh_rows'],references)]
    core._rows(rows, lane['dimension'], lane['donor']['codec']['target_vocabulary'], 512)
    modes = {name:part.training for name,part in model.named_modules()}; measured = []; loss_sum = 0.; count = 0
    try:
        model.eval()
        with torch.inference_mode():
            for offset in range(0,len(rows),8):
                require(time.monotonic() < deadline, 'posthoc panel deadline exceeded')
                part = rows[offset:offset+8]
                data,labels = core._batch(torch, part, lane['donor']['input_transform'])
                _, logits = core._logits(torch, model, data, labels[:,:-1], len(lane['donor']['codec']['target_vocabulary']),
                    **core._source_context_kwargs(torch, part, lane['fresh_contexts'], lane['donor']['input_transform']))
                losses = torch.nn.functional.cross_entropy(logits.flatten(0,1), labels[:,1:].flatten(),
                    ignore_index=0, reduction='none').reshape(len(part),-1)
                require(core._finite(torch, losses), 'nonfinite heldout teacher-forced CE')
                for index,row in enumerate(part):
                    n = len(row['target_ids'])-1; values = losses[index,:n].tolist()
                    measured.append(dict(id=row['id'], target_token_ids=row['target_ids'][1:],
                        token_cross_entropies=values, token_count=n, cross_entropy=sum(values)/n))
                    loss_sum += sum(values); count += n
    finally:
        for name,part in model.named_modules():
            part.training = modes[name]
    require(core.tensor_digest(model) == before, 'posthoc scoring changed saved model')
    require(time.monotonic() < deadline, 'posthoc panel deadline exceeded')
    return dict(schema='source-margin-holdout-score/v1', complete=True, fidelity=fidelity,
        by_template_family=by_family, by_training_pair_stratum=by_pair_stratum,
        pair_stratum_scope='whole_paragraph_all_seen_or_all_unseen_or_mixed;original_rule_order',
        teacher_forced=dict(token_cross_entropy=loss_sum/count,
            valid_target_tokens=count, rows=measured, full_vocabulary_size=len(lane['donor']['codec']['target_vocabulary']),
            reference_prefixes_used=True, greedy_repeated=False, used_for_selection=False),
        model_tensor_sha256=before, predictions_sha256=core.digest(prediction),
        references_sha256=core.digest(references), source_rows_sha256=core.digest(lane['fresh_rows']),
        elapsed_seconds=time.monotonic()-started, **FALSE)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('dependency-root','extension-root','manifest','plan','output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--phase', choices=['evaluation'], required=True)
    args = parser.parse_args(); started = time.monotonic(); deadline = started+FIXED['max_seconds_entire_run']
    ctx = load_context(args); h = ctx['helpers']; args.output.mkdir(parents=True)
    before = h.inventory(args.dependency_root,args.extension_root,ctx['pins'])
    h.save(args.output/'sealed-recipe.json', dict(manifest=ctx['manifest'], plan=ctx['plan'], tree_pin=ctx['tree'], **FALSE))
    predictions = []
    for dimension in FIXED['dimensions']:
        lane = prepare_lane(ctx,dimension)
        for seed in FIXED['seed_order']:
            for arm in ARMS:
                name = f'{dimension}-{arm}-{seed}'; run = ctx['saved_runs'][name]
                for role in ROLES:
                    require(time.monotonic() < deadline, 'entire holdout deadline exceeded')
                    model,state = restore_state(ctx,lane,run,role)
                    panel = generate_panel(ctx,lane,model,min(deadline,time.monotonic()+FIXED['max_seconds_per_panel']))
                    ref = h.save(args.output/name/(role+'-predictions.json'),panel)
                    predictions.append(dict(arm=name,dimension=dimension,seed=seed,role=role,
                        state_ref=run['states'][role],predictions_ref=ref,generation_seconds=panel['elapsed_seconds']))
                    del model,state,panel
    h.save(args.output/'predictions-complete.json', dict(complete=True, panels=predictions,
        all_predictions_persisted_before_reference_load=True, reference_json_loaded=False, **FALSE))
    references,receipt = load_fresh_references(ctx,predictions)
    results = []
    for dimension in FIXED['dimensions']:
        lane = prepare_lane(ctx,dimension)
        for record in [item for item in predictions if item['dimension'] == dimension]:
            require(time.monotonic() < deadline, 'entire holdout deadline exceeded')
            require(sha(record['predictions_ref']['path']) == record['predictions_ref']['sha256'], 'saved prediction changed')
            prediction = json.loads(Path(record['predictions_ref']['path']).read_bytes())
            model,state = restore_state(ctx,lane,ctx['saved_runs'][record['arm']],record['role'])
            panel_deadline = min(deadline,time.monotonic()+FIXED['max_seconds_per_panel']-record['generation_seconds'])
            score = score_panel(ctx,lane,model,prediction,references,panel_deadline)
            ref = h.save(args.output/record['arm']/(record['role']+'-score.json'),score)
            results.append(dict(record,score_ref=ref,scoring_seconds=score['elapsed_seconds'],
                ordered_exact=score['fidelity']['metrics']['ordered_exact'],
                syntax_valid=score['fidelity']['metrics']['syntax_valid'],
                teacher_forced_cross_entropy=score['teacher_forced']['token_cross_entropy']))
            del model,state,score,prediction
    after = h.inventory(args.dependency_root,args.extension_root,ctx['pins'])
    require(all(after.get(k) == v for k,v in before.items()), 'loaded producer changed')
    for path,wanted in ctx['manifest']['inputs'].items():
        require(sha(path) == wanted, 'sealed input changed after evaluation')
    for path,wanted in ctx['pins'].items():
        require(sha(args.extension_root/path) == wanted, 'frozen producer changed after evaluation')
    require(sha(args.plan) == ctx['manifest']['plan_sha256'], 'evaluation plan changed')
    require(time.monotonic() < deadline, 'entire holdout deadline exceeded')
    h.save(args.output/'summary.json', dict(schema='source-margin-holdout-evaluation/v1', complete=len(results)==36,
        panels=results, source_dependencies=after, fresh_authored_holdout=True, comparison_seal=ctx['manifest']['comparison_seal'],
        references_sha256=ctx['core'].digest(references), holdout_receipt_sha256=ctx['core'].digest(receipt),
        authored_modal_assumption=receipt['authored_modal_assumption'], target_provenance=receipt['target_provenance'],
        all_predictions_persisted_before_reference_load=True, fresh_holdout_exposed_after_this_evaluation=True,
        generated_predictions_reused_for_all_posthoc_scoring=True, elapsed_seconds=time.monotonic()-started,
        workers=1, bridge_names=[], legal_ir_evaluate_provers=False, metric_disk_cache_used=False, **FALSE))


if __name__ == '__main__':
    main()
