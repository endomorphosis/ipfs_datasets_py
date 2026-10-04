#!/usr/bin/env python3
"""Evaluate eight saved384D endpoints before exposing any fresh reference JSON.

Generation and posthoc scoring reuse the authenticated historical kernels.
Reference-conditioned cross entropy is reported separately from saved greedy
fidelity. No training, selection, encoder execution or proof admission occurs.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import time
from types import SimpleNamespace

AUTO = 'ipfs_datasets_py/logic/formalization/autoencoder/'
PREFIX = 'ipfs_datasets_py.logic.formalization.autoencoder.'
RUNNER = 'scripts/ops/autoencoder/benchmark_content_matched_modality_training.py'
PREPARER = 'scripts/ops/autoencoder/prepare_content_matched_holdout.py'
ARMS = ['aux-full180', 'content-matched-cycles']
ROLES = ['last-attempt', 'selected']
FALSE = dict(training_executed=False, encoder_executed=False, downloads_performed=False,
    qualified=False, admitted=False, proof_authority=False, source_semantics_verified=False,
    checkpoint_promoted=False, convergence_proven=False, lake_executed=False,
    native_validation_executed=False, formalized=False, roundtrip_ok=False,
    selection_performed=False, historical_linguistic_teacher_modified=False)
FIXED = dict(schema='content-matched-holdout-evaluation-plan/v1', dimensions=[384],
    seed_order=[1729, 2718], arms=ARMS, roles=ROLES, fit_count=4, state_count=8,
    panel_count=8, samples_per_panel=48, batch_size=8, workers=1,
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
    require(type(plan) is dict and all(type(plan.get(k)) is type(v)
        and json.dumps(plan[k], sort_keys=True, allow_nan=False) == json.dumps(v, sort_keys=True, allow_nan=False)
        for k, v in FIXED.items()), 'fixed content-matched fresh evaluation policy differs')


def jobs():
    return [(384, seed, arm) for seed in FIXED['seed_order'] for arm in ARMS]


def bound_json(manifest, path, expected=None):
    path = Path(path).resolve()
    wanted = manifest['inputs'].get(str(path))
    require(wanted is not None and (expected is None or expected == wanted), 'unbound input: ' + str(path))
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == wanted, 'sealed input changed: ' + str(path))
    return json.loads(raw)


def bound_ref(manifest, reference):
    value = bound_json(manifest, reference['path'], reference['sha256'])
    require('bytes' not in reference or Path(reference['path']).stat().st_size == reference['bytes'],
        'saved reference byte count differs')
    return value


def load_script(args, manifest, relative, name):
    path = args.extension_root / relative
    require(sha(path) == manifest['extensions'][relative], 'frozen script differs: ' + relative)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_saved_runs(manifest, summary, recipes):
    require(summary.get('schema') == 'content-matched-modality-training-comparison/v1'
        and summary.get('complete') is True and summary.get('training_executed') is True
        and summary.get('all_two_published_384_full180_controls_replayed') is True
        and summary.get('per_source_auxiliary_exposure_identical') is True,
        'complete four-fit matched training comparison required')
    records = summary.get('runs')
    require(type(records) is list and [r.get('arm') for r in records] ==
        [f'{d}-{arm}-{seed}' for d, seed, arm in jobs()], 'exact four saved run identities required')
    recipes = {r['name']:r for r in recipes}
    require(set(recipes) == set(ARMS), 'comparison recipes differ')
    runs = {}
    for item, (dimension, seed, arm) in zip(records, jobs()):
        run = bound_json(manifest, item['summary_path'], item['summary_sha256'])
        require(run.get('arm') == item['arm'] and run.get('dimension') == dimension
            and run.get('seed') == seed and run.get('recipe') == recipes[arm]
            and run.get('budget_completed') is True, 'incomplete or mismatched saved run')
        training = bound_ref(manifest, run['training_ref'])
        require(training.get('stopped_reason') == 'epochs_completed' and training.get('optimizer_steps') == 340,
            'complete unchanged training exposure required')
        for role, key in [('selected', 'selected_weights_sha256'), ('last-attempt', 'last_complete_attempt_weights_sha256')]:
            reference = run['states'][role]
            require(manifest['inputs'].get(str(Path(reference['path']).resolve())) == reference['sha256']
                and sha(reference['path']) == reference['sha256']
                and reference.get('tensor_sha256') == training.get(key), 'unbound or mismatched saved endpoint')
        runs[item['arm']] = run
    return runs


def validate_preparation(ctx, manifest, preparation):
    require(preparation.get('schema') == 'content-matched-fresh-preparation/v1'
        and preparation.get('complete') is True and preparation.get('dimension') == 384
        and preparation.get('comparison_seal') == manifest['comparison_seal']
        and all(preparation.get(k) is False for k in ('training_executed', 'downloads_performed',
            'qualified', 'admitted', 'lake_executed', 'formalized', 'roundtrip_ok', 'checkpoint_promoted')),
        'bound complete384D source preparation required')
    for name in ('dimension_inputs', 'source_rows', 'source_plan', 'production', 'references', 'holdout_receipt'):
        ref = preparation[name]
        require(manifest['inputs'].get(str(Path(ref['path']).resolve())) == ref['sha256']
            and sha(ref['path']) == ref['sha256'], 'unbound preparation component: ' + name)
    require(len({str(Path(preparation[k]['path']).resolve()) for k in
        ('dimension_inputs', 'source_rows', 'source_plan', 'production', 'references', 'holdout_receipt')}) == 6,
        'preparation sources and reference artifacts must be separate')
    inputs = bound_ref(manifest, preparation['dimension_inputs'])
    source_plan = bound_ref(manifest, preparation['source_plan'])
    report = bound_ref(manifest, preparation['production'])
    source_rows = bound_ref(manifest, preparation['source_rows'])
    for value in (inputs, source_plan, report, source_rows):
        ctx['exposed_evaluator']._source_only(value)
    require(inputs.get('schema') == 'fresh-scalar-source-inputs-single/v1'
        and inputs.get('dimension') == 384 and inputs.get('complete') is True,
        'explicit single-width384D source schema required')
    require(source_plan.get('source_rows') == source_rows
        and source_plan.get('sealed_comparison_sha256') == manifest['comparison_seal'],
        'prepared sources or comparison seal differs')
    assembled = ctx['fresh_owners']['fresh_scalar_source_inputs_single'].assemble(source_plan, report, dimension=384)
    require(inputs == assembled, 'saved source vectors/contexts differ from native production')
    return inputs


def load_context(args):
    manifest = json.loads(args.manifest.read_bytes()); plan = json.loads(args.plan.read_bytes())
    validate_plan(plan)
    require(sha(args.plan) == manifest['plan_sha256'] and plan['input_sha256'] == manifest['inputs'],
        'sealed evaluation plan differs')
    # Hashing reference bytes authenticates them without parsing their labels.
    for path, wanted in manifest['inputs'].items():
        require(sha(path) == wanted, 'sealed evaluation input changed: ' + path)
    for path, wanted in manifest['extensions'].items():
        require(sha(args.extension_root / path) == wanted, 'frozen evaluation source changed: ' + path)
    for key in ('comparison_manifest', 'comparison_plan', 'training_summary', 'preparation_summary',
                'preparation_manifest', 'preparation_plan'):
        require(str(Path(manifest[key]).resolve()) in manifest['inputs'], 'unbound evaluation alias: ' + key)
    require(sha(manifest['comparison_plan']) == manifest['comparison_seal'], 'training comparison seal differs')
    comparison = bound_json(manifest, manifest['comparison_manifest'])
    require(comparison['plan_sha256'] == manifest['comparison_seal'], 'comparison manifest seal differs')
    runner = load_script(args, manifest, RUNNER, '_content_matched_fresh_training')
    comparison_args = SimpleNamespace(**dict(vars(args), manifest=Path(manifest['comparison_manifest']),
        plan=Path(manifest['comparison_plan'])))
    ctx = runner.load_context(comparison_args)
    preparer = load_script(args, manifest, PREPARER, '_content_matched_fresh_preparer')
    prep_manifest = bound_json(manifest, manifest['preparation_manifest'])
    prep_plan = bound_json(manifest, manifest['preparation_plan'])
    preparer.validate_plan(prep_plan)
    require(sha(manifest['preparation_plan']) == prep_manifest['plan_sha256']
        and prep_plan['input_sha256'] == prep_manifest['inputs']
        and prep_manifest['comparison_seal'] == manifest['comparison_seal'], 'preparation recipe binding differs')
    for path, wanted in prep_manifest['inputs'].items():
        require(manifest['inputs'].get(path) == wanted, 'preparation input closure absent from evaluation')
    owners = {}
    for name in ('authored_modality_holdout_v2', 'fresh_scalar_source_inputs', 'fresh_scalar_source_inputs_single'):
        owners[name] = ctx['helpers'].extension(args.extension_root, AUTO + name + '.py', PREFIX + name,
            manifest['extensions'])
    runtime = 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_embedding_runtime.py'
    ctx['helpers'].extension(args.extension_root, runtime,
        'ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_embedding_runtime', manifest['extensions'])
    summary = bound_json(manifest, manifest['training_summary'])
    saved_runs = validate_saved_runs(manifest, summary, runner.ARMS)
    preparation = bound_json(manifest, manifest['preparation_summary'])
    ctx.update(evaluation_manifest=manifest, evaluation_plan=plan, comparison_runner=runner,
        comparison_args=comparison_args, fresh_owners=owners, saved_runs=saved_runs,
        preparation=preparation, preparation_plan=prep_plan,
        prior_inventory=preparer.prior_inventory(prep_manifest))
    ctx['fresh_inputs'] = validate_preparation(ctx, manifest, preparation)
    return ctx


def validate_source_exclusion(ctx, lane, fresh):
    core = ctx['core']; normalized = lambda text: ' '.join(text.casefold().split())
    old_ids, old_literals, old_vectors = set(), set(), set()
    def vector_hash(value):
        core._vector(value, 384)
        return hashlib.sha256(struct.pack('<384f', *value)).hexdigest()
    def consume(rows):
        for row in rows:
            old_ids.add(row['id'])
            old_literals.update(normalized(x) for x in [row['source_text'], *row['source_text'].split('\n\n')])
            if 'input' in row:old_vectors.add(vector_hash(row['input']))
    for rows in ctx['prior_inventory'].values():consume(rows)
    for split in ('train', 'validation'):
        consume(lane['rows'][split]); consume(lane['clause_cache'][split])
    original = ctx['manifest']['auxiliary_sources']
    for split, path in [('train', original['original_training']), *original['forbidden'].items()]:
        raw = bound_json(ctx['manifest'], path)
        consume(ctx['parent_runner'].source_only_original_rows(raw, split))
    exposed = bound_json(ctx['manifest'], ctx['manifest']['exposed_source_inputs'])['dimensions']['384']
    consume(exposed['rows']); consume(exposed['clause_cache'])
    for row in [*fresh['rows'], *fresh['clause_cache']]:
        require(row['id'] not in old_ids
            and all(normalized(text) not in old_literals for text in
                [row['source_text'], *row['source_text'].split('\n\n')])
            and vector_hash(row['input']) not in old_vectors, 'fresh source identity/literal/vector overlaps prior data')
    return dict(prior_id_count=len(old_ids), prior_normalized_literal_count=len(old_literals),
        prior_float32_vector_count=len(old_vectors), checked_paragraphs=48, checked_clauses=180,
        vector_comparison='exact_raw_float32_bytes;not_a_separability_claim', no_prior_overlap=True)


def prepare_lane(ctx):
    lane = ctx['native_runner'].prepare_dimension(ctx, 384)
    folder = Path(ctx['evaluation_manifest']['training_summary']).parent / '384'
    for name, value in [('preprocessing.json', lane['preparation']), ('source-contexts.json', lane['source_contexts']),
                        ('training-rows.json', lane['rows'])]:
        require(bound_json(ctx['evaluation_manifest'], folder / name) == value,
            'saved training-only preprocessing differs: ' + name)
    fresh = ctx['fresh_inputs']; rows = fresh['rows']; owner = ctx['owners']['clause_source_context']
    require(type(rows) is list and len(rows) == 48 and all(set(r) == {'id', 'source_text', 'input'} for r in rows),
        'closed48 source-only rows required')
    contexts = owner.build_source_contexts([{k:r[k] for k in ('id', 'source_text')} for r in rows], fresh['clause_cache'])
    require(contexts == fresh['source_contexts'] and owner.validate_contexts(rows, contexts)['dimension'] == 384,
        'fresh source context binding differs')
    exclusion = validate_source_exclusion(ctx, lane, fresh)
    lane.update(fresh_rows=rows, fresh_contexts=contexts, fresh_source_exclusion=exclusion)
    return lane


def restore_state(ctx, lane, run, role):
    require(role in ROLES and run['arm'] in ctx['saved_runs']
        and run == ctx['saved_runs'][run['arm']], 'unregistered saved endpoint')
    ref = run['states'][role]
    require(ctx['evaluation_manifest']['inputs'].get(str(Path(ref['path']).resolve())) == ref['sha256']
        and sha(ref['path']) == ref['sha256'], 'saved endpoint bytes changed')
    return ctx['comparison_runner'].restore_endpoint(lane, run, role)


def generate_panel(ctx, lane, model, deadline):
    result = ctx['exposed_evaluator'].generate_panel(ctx, lane, model, deadline)
    result['schema'] = 'content-matched-fresh-predictions/v1'
    return result


def load_fresh_references(ctx, lane, records):
    expected = {(f'{d}-{arm}-{seed}', role) for d, seed, arm in jobs() for role in ROLES}
    require(len(records) == 8 and {(r['arm'], r['role']) for r in records} == expected,
        'all8 predictions required before references are opened')
    core = ctx['core']; rows = ctx['fresh_inputs']['rows']; expected_ids = [r['id'] for r in rows]
    for record in records:
        ref = record['predictions_ref']; data = Path(ref['path']).read_bytes()
        require(hashlib.sha256(data).hexdigest() == ref['sha256'], 'persisted predictions changed')
        saved = json.loads(data)
        require(record['state_ref'] == ctx['saved_runs'][record['arm']]['states'][record['role']]
            and saved.get('complete') is True and [p.get('id') for p in saved.get('predictions', [])] == expected_ids
            and saved.get('model_tensor_sha256') == record['state_ref']['tensor_sha256']
            and saved.get('source_rows_sha256') == core.digest(rows)
            and saved.get('source_contexts_sha256') == core.digest(lane['fresh_contexts'])
            and saved.get('generation_reference_access') is False, 'incomplete or mismatched persisted predictions')
    manifest = ctx['evaluation_manifest']; preparation = ctx['preparation']
    references = bound_ref(manifest, preparation['references'])
    receipt = bound_ref(manifest, preparation['holdout_receipt'])
    aligned = {r['id']:r['target'] for r in lane['references']['train']}
    training = [dict(id=r['id'], source_text=r['source_text'], target=aligned[r['id']]) for r in lane['rows']['train']]
    # Pure deterministic validation only, after all generation is durably saved.
    expected = ctx['fresh_owners']['authored_modality_holdout_v2'].build_holdout(
        training_rows=training, prior_sources_by_dataset=ctx['prior_inventory'],
        family_roles=ctx['preparation_plan']['family_roles'], codec=lane['donor']['codec'],
        sealed_comparison_sha256=manifest['comparison_seal'], seed=ctx['preparation_plan']['seed'],
        validate_rule=lane['validate_rule'])
    require(expected['source_rows'] == [{k:r[k] for k in ('id', 'source_text')} for r in rows]
        and expected['references'] == references and expected['receipt'] == receipt,
        'authored references/source/sealed recipe differ from pure construction')
    return references, receipt


def score_panel(ctx, lane, model, prediction, references, deadline):
    result = ctx['exposed_evaluator'].score_panel(ctx, lane, model, prediction, references, deadline)
    result['schema'] = 'content-matched-fresh-score/v1'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('dependency-root', 'extension-root', 'manifest', 'plan', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--phase', choices=['evaluation'], required=True)
    args = parser.parse_args(); started = time.monotonic(); deadline = started + FIXED['max_seconds_entire_run']
    ctx = load_context(args); h = ctx['helpers']; args.output.mkdir(parents=True, exist_ok=False)
    runner = ctx['comparison_runner']; before = runner.source_inventory(ctx['comparison_args'], ctx)
    h.save(args.output / 'sealed-recipe.json', dict(manifest=ctx['evaluation_manifest'],
        plan=ctx['evaluation_plan'], tree_pin=ctx['tree'], **FALSE))
    lane = prepare_lane(ctx); h.save(args.output / 'source-exclusion.json', lane['fresh_source_exclusion'])
    predictions = []
    for dimension, seed, arm in jobs():
        name = f'{dimension}-{arm}-{seed}'; run = ctx['saved_runs'][name]
        for role in ROLES:
            require(time.monotonic() < deadline, 'entire fresh evaluation deadline exceeded')
            model = restore_state(ctx, lane, run, role)
            panel = generate_panel(ctx, lane, model, min(deadline, time.monotonic() + 30))
            ref = h.save(args.output / name / (role + '-predictions.json'), panel)
            predictions.append(dict(arm=name, dimension=dimension, seed=seed, role=role,
                state_ref=run['states'][role], predictions_ref=ref, generation_seconds=panel['elapsed_seconds']))
            del model, panel
    h.save(args.output / 'predictions-complete.json', dict(complete=True, panels=predictions,
        all_predictions_persisted_before_reference_load=True, reference_json_loaded=False, **FALSE))
    references, receipt = load_fresh_references(ctx, lane, predictions)
    results = []
    for record in predictions:
        require(time.monotonic() < deadline, 'entire fresh evaluation deadline exceeded')
        reference = record['predictions_ref']
        require(sha(reference['path']) == reference['sha256'], 'saved fresh prediction changed')
        prediction = json.loads(Path(reference['path']).read_bytes())
        model = restore_state(ctx, lane, ctx['saved_runs'][record['arm']], record['role'])
        score = score_panel(ctx, lane, model, prediction, references,
            min(deadline, time.monotonic() + 30 - record['generation_seconds']))
        ref = h.save(args.output / record['arm'] / (record['role'] + '-score.json'), score)
        results.append(dict(record, score_ref=ref, scoring_seconds=score['elapsed_seconds'],
            ordered_exact=score['fidelity']['metrics']['ordered_exact'],
            syntax_valid=score['fidelity']['metrics']['syntax_valid'],
            teacher_forced_cross_entropy=score['teacher_forced']['token_cross_entropy']))
        del model, prediction, score
    after = runner.source_inventory(ctx['comparison_args'], ctx)
    require(all(after.get(k) == v for k, v in before.items()), 'loaded evaluation producer changed')
    for path, wanted in ctx['evaluation_manifest']['inputs'].items():
        require(sha(path) == wanted, 'sealed evaluation input changed')
    for relative, wanted in ctx['evaluation_manifest']['extensions'].items():
        require(sha(args.extension_root / relative) == wanted, 'frozen evaluation producer changed')
    require(sha(args.plan) == ctx['evaluation_manifest']['plan_sha256'] and time.monotonic() < deadline,
        'evaluation plan changed or deadline exceeded')
    h.save(args.output / 'summary.json', dict(schema='content-matched-fresh-evaluation/v1', complete=len(results) == 8,
        panels=results, source_dependencies=after, fresh_authored_holdout=True,
        comparison_seal=ctx['evaluation_manifest']['comparison_seal'], samples_per_panel=48, panel_count=8,
        references_sha256=ctx['core'].digest(references), holdout_receipt_sha256=ctx['core'].digest(receipt),
        authored_modal_assumption=receipt['authored_modal_assumption'], target_provenance=receipt['target_provenance'],
        all_predictions_persisted_before_reference_load=True, fresh_holdout_exposed_after_this_evaluation=True,
        generated_predictions_reused_for_all_posthoc_scoring=True, elapsed_seconds=time.monotonic() - started,
        workers=1, bridge_names=[], legal_ir_evaluate_provers=False, metric_disk_cache_used=False, **FALSE))


if __name__ == '__main__':
    main()
