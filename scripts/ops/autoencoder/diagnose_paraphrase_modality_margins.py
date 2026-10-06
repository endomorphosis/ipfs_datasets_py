#!/usr/bin/env python3
"""Observe four saved selected decoder states before loading exposed v3 labels.

The original numerical producers and their later boundary repair stay frozen.
This driver adds observation only: no training, encoder, solver or Lake run.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

AUTO = 'ipfs_datasets_py/logic/formalization/autoencoder/'
PREFIX = 'ipfs_datasets_py.logic.formalization.autoencoder.'
TRAINER = 'scripts/ops/autoencoder/benchmark_paraphrase_modality_training.py'
OBSERVER = AUTO + 'generated_scalar_observation.py'
OBSERVER_SHA256 = '1f1d35f7fd90df0396f3222676f2ffd11f17e2b1b2c79c0a79f1600488eb08d8'
ARMS = ('paraphrase-modality-zero', 'paraphrase-modality-ce')
ROLES = ('selected',)
FALSE = dict(qualified=False, admitted=False, proof_authority=False, formalized=False,
    roundtrip_ok=False, checkpoint_promoted=False, convergence_proven=False,
    lake_executed=False, fresh_holdout=False, source_semantics_verified=False,
    encoder_executed=False, training_executed=False, downloads_performed=False,
    used_for_selection=False, native_validation_executed=False)
TRACE_FALSE_FLAGS = ('qualified', 'admitted', 'proof_authority',
    'source_semantics_verified', 'production_checkpoint',
    'native_family_validation_performed', 'lake_executed',
    'checkpoint_promoted', 'convergence_proven', 'fresh_holdout')
FIXED = dict(schema='paraphrase-modality-margin-diagnostic-plan/v1',
    dimensions=[384, 768], arms=list(ARMS), roles=list(ROLES), panel_count=4,
    samples_per_panel=48, seed=1729, previously_exposed=True,
    all_predictions_before_reference_load=True, archived_generation_parity_required=True,
    greedy_passes_per_model=1, context_tokens=512, output_tokens=512,
    temperature=0, vocabulary_size=32, batch_size=8, workers=1,
    max_seconds_per_panel=30, max_seconds_entire_run=600,
    max_trace_memory_bytes=134217728, model_copies_during_observation=0,
    extra_forward_passes_for_decomposition=0, optimizer_steps=0,
    distribution='previously_exposed_authored_modality_holdout_v3',
    comparison_seal='4e09fd75f40e410d1a53f7f13d01c034c1b0bcae5254a5f7f195754d7db16eac',
    observer_sha256=OBSERVER_SHA256, bridge_names=[], legal_ir_evaluate_provers=False,
    metric_disk_cache_used=False,
    cache_scope='warm authenticated source vectors; no encoder forward', **FALSE)


def require(value, message):
    if not value:
        raise ValueError(message)


def check_deadline(deadline):
    if time.monotonic() >= deadline:
        raise TimeoutError('shared scalar observation deadline')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def bound(manifest, path, expected=None):
    path = Path(path).resolve()
    wanted = manifest['inputs'].get(str(path))
    require(wanted is not None and (expected is None or wanted == expected), 'unbound diagnostic input')
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == wanted, 'changed diagnostic input')
    return json.loads(raw)


def validate_plan(plan):
    require(type(plan) is dict and all(type(plan.get(k)) is type(v)
        and json.dumps(plan[k], sort_keys=True, allow_nan=False)
        == json.dumps(v, sort_keys=True, allow_nan=False) for k, v in FIXED.items()),
        'fixed scalar diagnostic recipe differs')


def key(dimension, arm, role='selected'):
    return f'{dimension}-{arm}-{role}'


def generation_predictions(rows):
    require(type(rows) is list, 'complete saved predictions required')
    fields = ('id', 'token_ids', 'generation_status', 'eos_reached')
    require(all(type(row) is dict and all(k in row for k in fields) for row in rows),
        'complete saved generation envelopes required')
    return [{k: row[k] for k in fields} for row in rows]


def durable_save(save, path, value):
    """Flush the closed payload and directory entries before the label barrier."""
    reference = save(path, value)
    path = Path(reference['path']).resolve()
    require(sha(path) == reference['sha256'], 'saved diagnostic payload differs')
    with path.open('rb') as stream:
        os.fsync(stream.fileno())
    for directory in (path.parent, path.parent.parent):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    return reference


def frozen_observer(ctx, manifest):
    """Load only the already sealed observer; never replace resident consumers."""
    candidates = sorted(path for path, wanted in manifest['inputs'].items()
        if path.endswith('/' + OBSERVER) and wanted == OBSERVER_SHA256)
    require(candidates, 'existing authenticated scalar observer required')
    path = Path(candidates[0]).resolve()
    require(sha(path) == OBSERVER_SHA256, 'scalar observer source pin differs')
    # The producer path must also be authorized by the saved training owner.
    require(ctx['paraphrase_manifest']['producer_pins'].get(str(path)) == OBSERVER_SHA256,
        'observer absent from original producer closure')
    owners = ctx['owners']
    boundary = owners['contextual_generated_boundary_training']
    fields = owners['generated_field_training']
    require(sys.modules.get(PREFIX + 'contextual_generated_boundary_training') is boundary
        and sys.modules.get(PREFIX + 'generated_field_training') is fields,
        'resident frozen observer dependencies differ')
    observer = ctx['helpers'].extension(path.parents[4], OBSERVER,
        PREFIX + 'generated_scalar_observation', {OBSERVER: OBSERVER_SHA256})
    require(observer.boundary is boundary and observer.fields is fields
        and observer.core is ctx['core'], 'observer changed numerical dependency identities')
    owners['generated_scalar_observation'] = observer
    return observer


def verify_traces(manifest, records, runs, lanes, digest):
    """All durable traces and archived greedy parity precede any v3 labels."""
    expected = {(d, a, 'selected') for d in FIXED['dimensions'] for a in ARMS}
    require(type(records) is list and len(records) == 4
        and {(r['dimension'], r['arm'], r['role']) for r in records} == expected,
        'all four unique selected traces required before v3 references')
    require(set(manifest['archived_predictions']) == {key(*item) for item in expected},
        'exact four archived selected prediction identities required')
    for record in records:
        lane = lanes[record['dimension']]
        state = runs[record['dimension'], record['arm']]['states']['selected']
        reference = record['trace_ref']
        raw = Path(reference['path']).read_bytes()
        require(hashlib.sha256(raw).hexdigest() == reference['sha256'], 'durable trace changed')
        trace = json.loads(raw)
        require(record['state_ref'] == state and trace.get('schema') == 'generated-contextual-scalar-trace/v1'
            and trace.get('complete') is True
            and trace.get('trace_sha256') == digest({k: v for k, v in trace.items() if k != 'trace_sha256'})
            and trace.get('model_tensor_sha256') == state['tensor_sha256']
            and type(trace.get('dimension')) is int and trace['dimension'] == record['dimension']
            and trace.get('model_schema') == 'ordered-clause-recurrent-source-decoder-development/v1'
            and trace.get('source_rows_sha256') == digest(lane['fresh_rows'])
            and trace.get('source_contexts_sha256') == digest(lane['fresh_contexts'])
            and trace.get('codec_sha256') == digest(lane['donor']['codec'])
            and trace.get('input_transform_sha256') == digest(lane['donor']['input_transform'])
            and trace.get('sample_count') == 48 and trace.get('batch_size') == 8
            and type(trace.get('vocabulary_size')) is int and trace['vocabulary_size'] == 32
            and trace.get('max_target_tokens') == 512 and trace.get('generation_temperature') == 0,
            'complete source-bound selected trace required')
        require(all(trace.get(k) is True for k in ('source_only', 'full_vocabulary_retained',
            'decomposition_exact', 'caller_state_preserved', 'hooks_removed',
            'complete_rollout_before_reference_scoring'))
            and all(trace.get(k) is False for k in ('reference_count_access', 'reference_prefix_access',
                'reference_documents_passed_to_model', 'inventory_access', 'source_context_target_access',
                'syntax_mask', 'forced_closure', 'model_copied', *TRACE_FALSE_FLAGS))
            and all(type(trace.get(k)) is int and trace[k] == 0 for k in
                ('extra_model_passes', 'source_head_extra_evaluations', 'optimizer_steps')),
            'trace reference, generation or authority policy differs')
        archived_ref = manifest['archived_predictions'][key(record['dimension'], record['arm'])]
        archived = bound(manifest, archived_ref['path'], archived_ref['sha256'])
        require('bytes' not in archived_ref or Path(archived_ref['path']).stat().st_size == archived_ref['bytes'],
            'archived prediction byte count differs')
        require(archived.get('complete') is True and archived.get('model_tensor_sha256') == state['tensor_sha256']
            and archived.get('source_rows_sha256') == digest(lane['fresh_rows'])
            and archived.get('source_contexts_sha256') == digest(lane['fresh_contexts'])
            and archived.get('generation_reference_access') is False
            and archived.get('generation_temperature') == 0 and archived.get('max_target_tokens') == 512,
            'archived source-only generation identity differs')
        require([r['id'] for r in trace['predictions']] == [r['id'] for r in lane['fresh_rows']]
            and generation_predictions(trace['predictions']) == generation_predictions(archived['predictions']),
            'observed generation differs from archived predictions')


def load_references(manifest, records, runs, lanes, codec, digest):
    verify_traces(manifest, records, runs, lanes, digest)
    refs = bound(manifest, manifest['references'])
    receipt = bound(manifest, manifest['holdout_receipt'])
    source = [{k: r[k] for k in ('id', 'source_text')} for r in lanes[384]['fresh_rows']]
    require(source == [{k: r[k] for k in ('id', 'source_text')} for r in lanes[768]['fresh_rows']],
        'v3 source ordering differs by width')
    require(type(refs) is list and len(refs) == 48 and len(codec['target_vocabulary']) == 32
        and receipt.get('complete') is True and receipt.get('schema') == 'authored-modality-holdout/v3'
        and receipt.get('receipt_sha256') == digest({k: v for k, v in receipt.items() if k != 'receipt_sha256'})
        and receipt.get('references_sha256') == digest(refs) and receipt.get('source_rows_sha256') == digest(source)
        and receipt.get('codec_sha256') == digest(codec)
        and receipt.get('sealed_comparison_sha256') == FIXED['comparison_seal'],
        'authenticated unchanged v3 references required')
    for ref, row in zip(refs, source):
        ids = ref['target_ids']
        require(ref['id'] == row['id'] and ref['source_text'] == row['source_text']
            and ref['source_sha256'] == hashlib.sha256(row['source_text'].encode()).hexdigest()
            and ref['target_sha256'] == digest(ref['target']) and ref['codec_sha256'] == digest(codec)
            and type(ids) is list and 3 <= len(ids) <= 512 and ids[0] == 1 and ids[-1] == 2
            and all(type(t) is int and 3 <= t < 32 for t in ids[1:-1])
            and json.loads(''.join(codec['target_vocabulary'][t] for t in ids[1:-1])) == ref['target'],
            'complete unchanged v3 source/target binding required')
    return refs, receipt


def execute(args):
    started = time.monotonic()
    deadline = started + FIXED['max_seconds_entire_run']
    manifest = json.loads(args.manifest.read_bytes())
    plan = json.loads(args.plan.read_bytes())
    validate_plan(plan)
    manifest_sha = sha(args.manifest)
    require(manifest.get('schema') == 'paraphrase-modality-margin-diagnostic-manifest/v1'
        and plan['input_sha256'] == manifest['inputs'], 'diagnostic manifest or input seal differs')

    def recheck():
        check_deadline(deadline)
        require(sha(args.manifest) == manifest_sha and sha(args.plan) == manifest['plan_sha256'],
            'diagnostic deadline or seal differs')
        for path, wanted in manifest['inputs'].items():
            check_deadline(deadline)
            require(sha(path) == wanted, 'sealed diagnostic input changed')
        for relative, wanted in manifest['extensions'].items():
            check_deadline(deadline)
            require(sha(args.extension_root / relative) == wanted, 'frozen diagnostic source changed')
        check_deadline(deadline)

    recheck()
    require(not args.output.exists(), 'fresh diagnostic output required')
    parent = bound(manifest, manifest['training_manifest'])
    root = Path(manifest['training_extension_root'])
    require(sha(root / TRAINER) == parent['extensions'][TRAINER], 'frozen training runner differs')
    spec = importlib.util.spec_from_file_location('_margin_modality_training_owner', root / TRAINER)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    previous = SimpleNamespace(**vars(args), dimension=384)
    previous.manifest = Path(manifest['training_manifest'])
    previous.plan = Path(manifest['training_plan'])
    previous.extension_root = root
    ctx = runner.load_context(previous, deadline)
    before = runner.source_inventory(previous, ctx)
    observer = frozen_observer(ctx, manifest)
    require(all(runner.source_inventory(previous, ctx).get(k) == v for k, v in before.items()),
        'observer replaced original numerical producers')
    style_manifest = bound(manifest, manifest['style_manifest'])
    bound(manifest, manifest['style_plan'])
    style_summary = bound(manifest, manifest['style_summary'])
    require(style_summary.get('complete') is True and style_summary.get('all_predictions_persisted_before_reference_load') is True
        and style_summary.get('schema') == 'paraphrase-modality-exposed-v3-results/v1'
        and style_manifest['source_inputs'] == manifest['source_inputs']
        and style_manifest['references'] == manifest['references']
        and style_manifest['holdout_receipt'] == manifest['holdout_receipt'], 'original v3 observer binding differs')
    runs, lanes = {}, {}
    for d in FIXED['dimensions']:
        terminal = manifest['training_terminals'][str(d)]
        require(bound(manifest, terminal['child_exit'])['returncode'] == 0
            and bound(manifest, terminal['resources_final'])['status'] == 'released', 'released completed training required')
        summary = bound(manifest, manifest['training_summaries'][str(d)])
        require(summary.get('complete') is True and summary.get('phase') == 'training' and summary.get('dimension') == d
            and len(summary['runs']) == 2 and {r['arm'] for r in summary['runs']} == set(ARMS), 'both complete arms required')
        for item in summary['runs']:
            run = bound(manifest, item['summary_path'], item['summary_sha256'])
            require(run['dimension'] == d and run['arm'] == item['arm'] and run['budget_completed'] is True
                and run['seed'] == 1729 and all(run[k] is False for k in ('qualified', 'admitted', 'checkpoint_promoted')),
                'selected endpoint identity differs')
            ref = run['states']['selected']
            require(manifest['inputs'].get(str(Path(ref['path']).resolve())) == ref['sha256'], 'unbound selected endpoint')
            panels = [p for p in style_summary['panels'] if p['dimension'] == d and p['arm'] == item['arm'] and p['role'] == 'selected']
            require(len(panels) == 1 and panels[0]['state_ref'] == ref
                and panels[0]['predictions_ref'] == manifest['archived_predictions'][key(d, item['arm'])],
                'archived selected generation binding differs')
            runs[d, item['arm']] = run
        check_deadline(deadline)
        lane = ctx['mixture_owner'].prepare_lane(ctx, d)
        lane['continuation_manifest'] = manifest
        data = bound(manifest, manifest['source_inputs'][str(d)])
        digest = ctx['core'].digest
        require(data.get('schema') == 'fresh-scalar-source-inputs-single/v1' and data.get('complete') is True
            and data.get('dimension') == d and data.get('inputs_sha256') == digest({k: v for k, v in data.items() if k != 'inputs_sha256'}),
            'authenticated v3 source-only cache required')
        rows = data['rows']
        require(len(rows) == 48 and all(set(row) == {'id', 'source_text', 'input'} for row in rows), 'closed v3 source rows required')
        for row in rows:
            ctx['core']._vector(row['input'], d)
        owner = ctx['owners']['clause_source_context']
        contexts = owner.build_source_contexts([{k: r[k] for k in ('id', 'source_text')} for r in rows], data['clause_cache'])
        require(contexts == data['source_contexts'] and owner.validate_contexts(rows, contexts)['dimension'] == d, 'v3 source contexts differ')
        lane.update(fresh_rows=rows, fresh_contexts=contexts)
        lanes[d] = lane
    args.output.mkdir(parents=True)
    save = ctx['helpers'].save
    save(args.output / 'sealed-recipe.json', dict(manifest=manifest, plan=plan, **FALSE))
    records = []
    for d in FIXED['dimensions']:
        for arm in ARMS:
            lane, run = lanes[d], runs[d, arm]
            check_deadline(deadline)
            model = ctx['mixture_owner'].restore_endpoint(lane, run, 'selected')
            check_deadline(deadline)
            panel_deadline = min(deadline, time.monotonic() + FIXED['max_seconds_per_panel'])
            trace = observer.collect_source_scalar_trace(model, lane['fresh_rows'], codec=lane['donor']['codec'],
                input_transform=lane['donor']['input_transform'], source_contexts=lane['fresh_contexts'],
                max_target_tokens=512, batch_size=8, deadline=panel_deadline,
                max_memory_bytes=FIXED['max_trace_memory_bytes'])
            require(ctx['core'].tensor_digest(model) == run['states']['selected']['tensor_sha256'], 'observed checkpoint changed')
            reference = durable_save(save, args.output / key(d, arm) / 'trace.json', trace)
            records.append(dict(dimension=d, arm=arm, role='selected', state_ref=run['states']['selected'], trace_ref=reference,
                generation_seconds=trace['elapsed_seconds'], last_attempt_alias_tensor_equal=
                    run['states']['last-attempt']['tensor_sha256'] == run['states']['selected']['tensor_sha256']))
            del model, trace
            check_deadline(deadline)
    verify_traces(manifest, records, runs, lanes, ctx['core'].digest)
    durable_save(save, args.output / 'traces-complete.json',
        dict(complete=True, records=records, v3_reference_json_loaded=False, **FALSE))
    references, receipt = load_references(manifest, records, runs, lanes, ctx['donor']['codec'], ctx['core'].digest)
    panels = []
    for record in records:
        check_deadline(deadline)
        lane = lanes[record['dimension']]
        raw = Path(record['trace_ref']['path']).read_bytes()
        require(hashlib.sha256(raw).hexdigest() == record['trace_ref']['sha256'], 'durable trace changed before scoring')
        trace = json.loads(raw)
        rows = [dict(row, target_ids=ref['target_ids']) for row, ref in zip(lane['fresh_rows'], references)]
        score_started = time.monotonic()
        score = observer.score_scalar_trace(trace, rows, references, split='exposed_development', codec=lane['donor']['codec'],
            input_transform=lane['donor']['input_transform'], source_contexts=lane['fresh_contexts'],
            validate_rule=lane['validate_rule'], deadline=min(deadline, time.monotonic() + max(0., 30 - record['generation_seconds'])))
        scoring_seconds = time.monotonic() - score_started
        score_ref = save(args.output / key(record['dimension'], record['arm']) / 'score.json', score)
        panels.append(dict(record, score_ref=score_ref, scoring_seconds=scoring_seconds, scored_sites=score['scored_sites'],
            per_field=score['per_field'], unscored_sites=len(score['unscored_sites']),
            unvisited_reference_sites=len(score['unvisited_reference_sites'])))
        del trace, score
    after = runner.source_inventory(previous, ctx)
    require(all(after.get(k) == v for k, v in before.items()), 'original diagnostic producers changed')
    recheck()
    save(args.output / 'summary.json', dict(schema='paraphrase-modality-margin-diagnostic-results/v1', complete=True,
        panels=panels, source_dependencies=after, elapsed_seconds=time.monotonic() - started, previously_exposed=True,
        references_sha256=ctx['core'].digest(references), holdout_receipt_sha256=ctx['core'].digest(receipt),
        all_traces_persisted_before_reference_load=True, archived_generation_parity_verified=True,
        formal_status=dict(generated_scalar_observation='complete', compiler_output='not_executed',
            family_semantic_validation='not_executed', lean_lake_admission='not_executed'),
        recipe=FIXED, **FALSE))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('dependency-root', 'extension-root', 'manifest', 'plan', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--phase', choices=['diagnostic'], required=True)
    execute(parser.parse_args())


if __name__ == '__main__':
    main()
