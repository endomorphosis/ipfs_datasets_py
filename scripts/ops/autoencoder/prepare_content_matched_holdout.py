#!/usr/bin/env python3
"""Prepare a separate, sealed authored cohort using only the local384 encoder."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import time

AUTO = 'ipfs_datasets_py/logic/formalization/autoencoder/'
PREFIX = 'ipfs_datasets_py.logic.formalization.autoencoder.'
RUNNER = 'scripts/ops/autoencoder/benchmark_content_matched_modality_training.py'
FIXED = dict(schema='content-matched-holdout-preparation-plan/v1', dimensions=[384],
    samples=48, clauses=180, unique_sources=216, seed=20261005, max_tokens=512,
    batch_size=4, max_seconds_entire_run=800, max_seconds_encoder=600,
    temperature=0, downloads_performed=False, training_executed=False,
    holdout_used_for_selection=False)
PRIOR_NAMES = {'raw_train', 'raw_validation', 'raw_test', 'raw_canary',
               'paragraph_train', 'paragraph_validation', 'exposed_r6'}


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_plan(plan):
    require(type(plan) is dict and all(type(plan.get(k)) is type(v) and plan[k] == v
        for k, v in FIXED.items()), 'fixed fresh preparation policy differs')


def bound_json(manifest, path):
    path = Path(path).resolve()
    data = path.read_bytes()
    require(manifest['inputs'].get(str(path)) == hashlib.sha256(data).hexdigest(),
            'unbound or changed input: ' + str(path))
    return json.loads(data)


def load_runner(args, manifest):
    path = args.extension_root / RUNNER
    require(sha(path) == manifest['extensions'][RUNNER], 'frozen comparison runner differs')
    spec = importlib.util.spec_from_file_location('_content_matched_preparation_context', path)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    older = SimpleNamespace(**dict(vars(args),
        manifest=Path(manifest['comparison_manifest']), plan=Path(manifest['comparison_plan'])))
    return runner, older, runner.load_context(older)


def prior_inventory(manifest):
    require(set(manifest['prior_sources']) == PRIOR_NAMES, 'complete prior dataset inventory required')
    result = {}
    for name, spec in manifest['prior_sources'].items():
        require(type(spec) is dict and set(spec) == {'path', 'keys'}, 'closed prior source descriptor required')
        rows = bound_json(manifest, spec['path'])
        require(type(spec['keys']) is list and all(type(k) is str for k in spec['keys']), 'literal JSON keys required')
        for key in spec['keys']:
            rows = rows[key]
        require(type(rows) is list and rows, 'nonempty prior rows required')
        result[name] = [{k: row[k] for k in ('id', 'source_text')} for row in rows]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('dependency-root', 'extension-root', 'manifest', 'plan', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--phase', choices=['preparation'], required=True)
    args = parser.parse_args()
    started = time.monotonic()
    manifest = json.loads(args.manifest.read_bytes())
    plan = json.loads(args.plan.read_bytes())
    validate_plan(plan)
    require(sha(args.plan) == manifest['plan_sha256'] and plan['input_sha256'] == manifest['inputs'],
            'sealed preparation plan differs')
    for path, digest in manifest['inputs'].items():
        require(sha(path) == digest, 'sealed preparation input changed: ' + path)
    for relative, digest in manifest['extensions'].items():
        require(sha(args.extension_root / relative) == digest, 'frozen source changed: ' + relative)
    require(sha(manifest['comparison_plan']) == manifest['comparison_seal'], 'comparison seal differs')
    runner, comparison_args, ctx = load_runner(args, manifest)
    h = ctx['helpers']
    owners = {}
    for name in ('authored_modality_holdout_v2', 'fresh_scalar_source_inputs', 'fresh_scalar_source_inputs_single'):
        owners[name] = h.extension(args.extension_root, AUTO + name + '.py', PREFIX + name,
                                   manifest['extensions'])
    runtime = 'ipfs_datasets_py/optimizers/logic_theorem_optimizer/autoencoder_embedding_runtime.py'
    h.extension(args.extension_root, runtime,
                'ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_embedding_runtime',
                manifest['extensions'])
    before = runner.source_inventory(comparison_args, ctx)
    args.output.mkdir(parents=True, exist_ok=False)
    h.save(args.output / 'sealed-recipe.json', dict(plan=plan, manifest=manifest, tree_pin=ctx['tree']))
    paragraphs = bound_json(manifest, manifest['training_paragraphs'])
    training = [{k: row[k] for k in ('id', 'source_text', 'target')} for row in paragraphs['train']]
    aligned = {row['id']: row['target'] for row in ctx['references']['train']}
    require(training == [dict(id=row['id'], source_text=row['source_text'], target=aligned[row['id']])
        for row in ctx['rows']['train']], 'fresh strata differ from actual original training rows')
    cohort = owners['authored_modality_holdout_v2'].build_holdout(
        training_rows=training, prior_sources_by_dataset=prior_inventory(manifest),
        family_roles=plan['family_roles'], codec=ctx['donor']['codec'],
        sealed_comparison_sha256=manifest['comparison_seal'], seed=FIXED['seed'],
        validate_rule=ctx['validate_rule'])
    sources = h.save(args.output / 'source-rows.json', cohort['source_rows'])
    references = h.save(args.output / 'references.json', cohort['references'])
    receipt = h.save(args.output / 'holdout-receipt.json', cohort['receipt'])
    producer = owners['fresh_scalar_source_inputs']
    source_plan = producer.source_plan(cohort['source_rows'],
        expected_source_rows_sha256=cohort['receipt']['source_rows_sha256'],
        sealed_comparison_sha256=manifest['comparison_seal'])
    source_plan_ref = h.save(args.output / 'source-plan.json', source_plan)
    assets = bound_json(manifest, manifest['asset_config'])
    report = producer.produce_width(source_plan, dimension=384, asset_config=assets['384'],
        source_artifact_directory=args.output / 'source384-artifacts', batch_size=4, max_seconds=600)
    produced = h.save(args.output / 'production-384.json', report)
    assembled = owners['fresh_scalar_source_inputs_single'].assemble(source_plan, report, dimension=384)
    inputs = h.save(args.output / 'dimension-inputs-384.json', assembled)
    after = runner.source_inventory(comparison_args, ctx)
    require(all(after.get(k) == v for k, v in before.items()), 'loaded preparation producer changed')
    for path, digest in manifest['inputs'].items():
        require(sha(path) == digest, 'sealed preparation input changed: ' + path)
    for relative, digest in manifest['extensions'].items():
        require(sha(args.extension_root / relative) == digest, 'frozen preparation source changed: ' + relative)
    require(sha(args.plan) == manifest['plan_sha256'], 'preparation recipe changed')
    require(time.monotonic() - started < FIXED['max_seconds_entire_run'], 'preparation deadline exceeded')
    h.save(args.output / 'summary.json', dict(schema='content-matched-fresh-preparation/v1',
        complete=True, dimension_inputs=inputs, source_rows=sources, references=references,
        holdout_receipt=receipt, production=produced, source_plan=source_plan_ref,
        comparison_seal=manifest['comparison_seal'],
        source_dependencies=after, elapsed_seconds=time.monotonic() - started,
        workers=1, dimension=384, device='cpu', batch_size=4, max_tokens=512,
        samples=48, unique_sources=216, encoder_cache='new literal source texts',
        bridge_names=[], legal_ir_evaluate_provers=False, metric_disk_cache_used=False,
        training_executed=False, downloads_performed=False, qualified=False, admitted=False,
        lake_executed=False, formalized=False, roundtrip_ok=False, checkpoint_promoted=False))


if __name__ == '__main__':
    main()
