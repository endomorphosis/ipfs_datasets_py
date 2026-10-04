#!/usr/bin/env python3
"""Bounded training-only diagnosis of an 8D clause head, never a formula admit."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

HELPER = 'ipfs_datasets_py/logic/formalization/autoencoder/source_field_readout_probe.py'
RUNNER = 'scripts/ops/autoencoder/benchmark_source_field_readout_probe.py'
FALSE = dict(qualified=False, admitted=False, checkpoint_promoted=False, production_checkpoint=False,
    convergence_proven=False, fresh_holdout=False, lake_executed=False, native_validation_executed=False,
    encoder_executed=False, compiler_executed=False, formula_decoder_executed=False,
    historical_linguistic_teacher_modified=False, formalized=False, roundtrip_ok=False)
FIXED = dict(schema='source-field-head-probe-plan/v1', dimension=8, seeds=[1729, 2718],
    modes=['shared_non_action', 'isolated_object'], learning_rates=[.001, .01], fit_count=8,
    training_occurrences=180, unique_training_clauses=113, training_paragraphs=48,
    vocabulary_size=32, hidden_width=64, updates=1000, checkpoints=[0,1,10,25,100,340,1000],
    full_batch=True, field_coefficient=.0625, optimizer='AdamW', betas=[.9,.999], epsilon=1e-8,
    weight_decay=.01, max_grad_norm=1., scheduler=None, validation_selection=False,
    input_representation='nonsemantic_historical_linguistic_feature_hash',
    context_tokens_unchanged=512, output_limit_unchanged=512, generation_temperature_unchanged=0,
    max_seconds_per_fit=60, max_seconds_entire_run=540, worker_count=1,
    bridge_names=[], legal_ir_evaluate_provers=False, metric_disk_cache_used=False,
    source_inputs_cached=True, weights_downloaded=False,
    original_curriculum_replayed=False, original_decoder_optimizer_replayed=False,
    full_vocabulary_retained=True, new_architecture_selected=False, **FALSE)


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def validate_plan(plan):
    require(type(plan) is dict and set(plan) == set(FIXED) | {'input_sha256'}, 'closed probe plan required')
    for key, value in FIXED.items():
        require(type(plan[key]) is type(value) and digest(plan[key]) == digest(value), 'fixed probe plan differs: '+key)
    require(type(plan['input_sha256']) is dict, 'explicit input pins required')


def bound_json(path, inputs):
    path = Path(path).resolve()
    require(str(path) in inputs and sha(path) == inputs[str(path)], 'unbound probe input: '+str(path))
    return json.loads(path.read_bytes())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n').encode()
    with path.open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    return dict(path=str(path.resolve()), sha256=sha(path), bytes=path.stat().st_size)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('dependency-root','extension-root','manifest','plan','output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--phase', choices=['training'], required=True)
    args = parser.parse_args()
    started = time.monotonic()
    require(not args.output.exists(), 'new private diagnostic directory required')
    manifest = json.loads(args.manifest.read_bytes()); plan = json.loads(args.plan.read_bytes())
    validate_plan(plan)
    require(sha(args.plan) == manifest['plan_sha256'] and plan['input_sha256'] == manifest['inputs'], 'sealed probe plan differs')
    for path, expected in manifest['inputs'].items():
        require(sha(path) == expected, 'probe input changed: '+path)
    sources = manifest['extensions']
    require(set(sources) == {HELPER, RUNNER}, 'exact standalone probe producers required')
    for relative, expected in sources.items():
        require(sha(args.extension_root/relative) == expected, 'frozen producer changed: '+relative)
    require(Path(__file__).resolve() == (args.extension_root/RUNNER).resolve(), 'run the frozen benchmark')
    training = bound_json(manifest['training_input'], manifest['inputs'])
    require(set(manifest['initial_heads']) == {str(seed) for seed in FIXED['seeds']}, 'both paired initial heads required')
    heads = {int(seed): bound_json(path, manifest['inputs']) for seed,path in manifest['initial_heads'].items()}
    require(len(training['rows']) == 180 and len({row['source_sha256'] for row in training['rows']}) == 113,
        'complete training occurrence inventory required')
    spec = importlib.util.spec_from_file_location('_frozen_source_field_readout_probe', args.extension_root/HELPER)
    helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
    # This diagnostic executes only the isolated numerical head. Loading the
    # project package, parser or a different editable checkout is unnecessary.
    require(not any(name == 'ipfs_datasets_py' or name.startswith('ipfs_datasets_py.') for name in sys.modules),
        'standalone diagnostic must not import a project parser or runtime')
    import torch
    torch.set_num_threads(1)
    save(args.output/'sealed-plan.json', dict(plan=plan, manifest=manifest,
        source_dependencies=sources, torch_version=torch.__version__, torch_path=torch.__file__, **FALSE))
    runs = []
    for seed in FIXED['seeds']:
        for mode in FIXED['modes']:
            for rate in FIXED['learning_rates']:
                require(time.monotonic()-started < FIXED['max_seconds_entire_run'], 'whole diagnostic deadline')
                name = str(seed)+'-'+mode+'-lr'+str(rate)
                call_started = time.monotonic()
                result = helper.run_source_field_readout_probe(torch, training, heads[seed],
                    expected_training_sha256=digest(training), expected_initial_head_sha256=digest(heads[seed]),
                    mode=mode, learning_rate=rate, max_updates=FIXED['updates'], checkpoints=FIXED['checkpoints'],
                    deadline=min(started+FIXED['max_seconds_entire_run'], call_started+FIXED['max_seconds_per_fit']))
                call_seconds = time.monotonic()-call_started
                ref = save(args.output/name/'probe.json', result)
                require(result['complete'] and result['completed_updates'] == 1000
                    and result['stopped_reason'] == 'updates_completed', 'incomplete diagnostic: '+name)
                require(result['training_occurrences'] == 180 and result['training_unique_clauses'] == 113,
                    'training cohort changed')
                endpoint = result['checkpoints'][-1]['fields']['object']
                entry = dict(name=name, seed=seed, mode=mode, learning_rate=rate,
                    report=ref, call_elapsed_seconds=call_seconds, object_correct=endpoint['correct'],
                    object_cross_entropy=endpoint['cross_entropy'], **FALSE)
                runs.append(entry)
                print(json.dumps(entry), flush=True)
    for path, expected in manifest['inputs'].items():
        require(sha(path) == expected, 'probe input changed during fitting: '+path)
    for relative, expected in sources.items():
        require(sha(args.extension_root/relative) == expected, 'frozen producer changed during fitting: '+relative)
    require(not any(name == 'ipfs_datasets_py' or name.startswith('ipfs_datasets_py.') for name in sys.modules),
        'project runtime was unexpectedly imported')
    save(args.output/'summary.json', dict(schema='source-field-head-probe-results/v1', complete=True,
        runs=runs, plan_sha256=sha(args.plan), manifest_sha256=sha(args.manifest), source_dependencies=sources,
        training_input_sha256=manifest['inputs'][str(Path(manifest['training_input']).resolve())],
        elapsed_seconds=time.monotonic()-started, worker_count=1, device='cpu', training_only=True,
        sample_count=180, unique_clause_count=113, source_paragraph_count=48,
        bridge_names=[], legal_ir_evaluate_provers=False, metric_disk_cache_used=False,
        source_inputs_cached=True, cold_parser_measurement=False, bridge_on_timing=False,
        no_project_runtime_imported=True, original_curriculum_replayed=False,
        semantics='raw source-field training probes; no generated formulas or generalization evaluation', **FALSE))


if __name__ == '__main__':
    main()
