#!/usr/bin/env python3
"""Independent old-TRAIN teacher-cache replay; current references stay sealed.

This checker never calls the new runtime's cache builder or cache validator.
It reconstructs source membership and correctness from authenticated old TRAIN
rows, then obtains exact logits through the frozen paired-parent decoder.
"""
from __future__ import annotations

import argparse
import math
import os
from pathlib import Path
import struct
import sys

os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
os.environ['OMP_NUM_THREADS'] = '1'
os.environ['OPENBLAS_NUM_THREADS'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from scripts.ops.legal_ir import qualify_legal_temporal_placement_head as frozen
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_paired_temporal_ownership as parent_runtime
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import legal_temporal_stability as runtime

SCHEMA = 'legal-temporal-stability-independent-teacher-replay/v1'
SEEDS = (1730, 1731)
SEALED_KEYS = ('fresh_lexical_targets', 'fresh_structural_targets', 'fresh_annotation_ledger', 'exposure_audit')
SOURCE_KEYS = ('id', 'source_text', 'source_sha256', 'proposed_time_span')
ROW_KEYS = {'id', 'source_sha256', 'proposed_time_span', 'label', 'logits', 'correct'}
CACHE_KEYS = {'schema', 'implementation', 'seed', 'parent_file_sha256', 'parent_payload_sha256',
    'training_manifests', 'sources_sha256', 'class_order', 'batch_size', 'rows',
    'teacher_state_before_sha256', 'teacher_state_after_sha256', 'teacher_requires_grad',
    'teacher_gradients_absent', 'encoder_batch_forwards', 'encoder_source_evaluations',
    'labels_used_only_for_correctness_mask', 'new_placement_rows_included', *frozen.metric.FALSE_FIELDS}
require, wire, digest = frozen.require, frozen.wire, frozen.digest
read, reference, write = frozen.read, frozen.reference, frozen.write


def producer_pins():
    from ipfs_datasets_py.logic.autoformal import legal_temporal_stability_corpus as corpus
    paths = set(runtime.producer_pins())
    paths.update(str(Path(m.__file__).resolve()) for m in
                 (frozen, frozen.metric, frozen.gates, corpus, sys.modules[__name__]))
    paths.update(pin['path'] for pin in corpus.producers())
    return [reference(path) for path in sorted(paths)]


def verify_teacher_freeze(freeze, config_pin, config):
    fields = {'schema', 'config', 'parents', 'models', 'producer_pins', 'encoder_batch_forwards',
              'encoder_source_evaluations', 'optimizer_updates', 'fresh_references_opened', 'fresh_reference_guard'}
    require(type(freeze) is dict and set(freeze) == fields and
            freeze['schema'] == 'legal-temporal-stability-teacher-cache-freeze/v1' and
            wire(freeze['config']) == wire(config_pin) and wire(freeze['parents']) == wire(config['parents']) and
            set(freeze['models']) == {str(seed) for seed in SEEDS}, 'complete two-parent teacher freeze required')
    require(freeze['fresh_references_opened'] is False and
            type(freeze['fresh_reference_guard']['premature_read_attempts']) is int and
            freeze['fresh_reference_guard']['premature_read_attempts'] == 0, 'teacher cache seal violated')
    require(type(freeze['optimizer_updates']) is int and freeze['optimizer_updates'] == 0 and
            type(freeze['encoder_batch_forwards']) is int and freeze['encoder_batch_forwards'] == 68 and
            type(freeze['encoder_source_evaluations']) is int and freeze['encoder_source_evaluations'] == 3264,
            'teacher cache wrapper work counters differ')


def verify_cache(cache, parent, single, paired, *, seed, parent_pin, expected_implementation):
    """Pure independent membership, mask, dtype, lineage and counter checks."""
    require(type(cache) is dict and set(cache) == CACHE_KEYS and
            cache['schema'] == 'legal-temporal-stability-teacher-cache/v1', 'closed teacher cache required')
    require(type(seed) is int and seed in SEEDS and type(cache['seed']) is int and cache['seed'] == seed,
            'teacher seed differs')
    require(wire(cache['implementation']) == wire(expected_implementation), 'teacher producer differs')
    require(parent['config']['arm'] == 'mixed_occurrences' and parent['config']['seed'] == seed and
            type(parent['optimizer_steps']) is int and parent['optimizer_steps'] == 200,
            'exact paired mixed200 parent required')
    require(cache['parent_file_sha256'] == parent_pin['sha256'] and cache['parent_payload_sha256'] == digest(parent),
            'teacher parent binding differs')
    require(len(single) == 768 and len(paired) == 864, 'exact old TRAIN panel sizes required')
    targets = [*single, *paired]
    sources = [{key: row[key] for key in SOURCE_KEYS} for row in targets]
    require(len({row['id'] for row in sources}) == 1632, 'teacher old TRAIN IDs must be unique')
    for row in sources:
        frozen.metric.validate_source(row)
    expected = {key: {'sha256': digest(rows), 'count': len(rows)}
                for key, rows in (('single_training', single), ('prior_paired_training', paired))}
    require(wire(cache['training_manifests']) == wire(expected) and cache['sources_sha256'] == digest(sources),
            'teacher exact ordered old TRAIN inventory differs')
    require(cache['class_order'] == list(frozen.metric.CLASSES) and type(cache['batch_size']) is int and
            cache['batch_size'] == 48, 'teacher taxonomy/batching differs')
    require(cache['teacher_state_before_sha256'] == cache['teacher_state_after_sha256'] == digest(parent['model_state'])
            and cache['teacher_requires_grad'] is False and cache['teacher_gradients_absent'] is True,
            'teacher immutability evidence differs')
    require(type(cache['encoder_batch_forwards']) is int and cache['encoder_batch_forwards'] == 34 and
            type(cache['encoder_source_evaluations']) is int and cache['encoder_source_evaluations'] == 1632,
            'teacher complete numerical counters differ')
    require(cache['labels_used_only_for_correctness_mask'] is True and cache['new_placement_rows_included'] is False
            and all(cache[key] is False for key in frozen.metric.FALSE_FIELDS), 'teacher authority/input scope differs')
    require(type(cache['rows']) is list and len(cache['rows']) == 1632, 'complete teacher rows required')
    counts = {name: 0 for name in frozen.metric.CLASSES}
    for target, row in zip(targets, cache['rows']):
        require(type(row) is dict and set(row) == ROW_KEYS, 'closed teacher row required')
        require(wire({k: row[k] for k in ROW_KEYS-{'logits', 'correct'}}) ==
                wire({k: target[k] for k in ROW_KEYS-{'logits', 'correct'}}), 'teacher source/target/order differs')
        values = row['logits']
        require(type(values) is list and len(values) == 4 and all(type(v) is float and math.isfinite(v) for v in values),
                'finite four float logits required')
        try:
            exact = [struct.unpack('!f', struct.pack('!f', value))[0] for value in values]
        except OverflowError as error:
            raise ValueError('teacher logits exceed float32') from error
        require(wire(exact) == wire(values), 'teacher logits are not exact serialized float32')
        predicted = frozen.metric.CLASSES[max(range(4), key=values.__getitem__)]
        require(type(row['correct']) is bool and row['correct'] == (predicted == target['label']),
                'teacher correctness is not TRAIN argmax correctness')
        if row['correct']:
            counts[target['label']] += 1
    return sources, counts


def replay_cache_logits(cache, sources, model):
    """One independent parent inference per exact cache chunk; no label input."""
    before_batches, before_rows = model.encoder_batch_forwards, model.encoder_source_evaluations
    actual = []
    for start in range(0, len(sources), 48):
        predictions = model.predict_many(sources[start:start+48])
        frozen.gates.source_only_predictions(sources[start:start+48], predictions)
        actual.extend({k: row[k] for k in ('id', 'source_sha256', 'proposed_time_span', 'logits')} for row in predictions)
    expected = [{k: row[k] for k in ('id', 'source_sha256', 'proposed_time_span', 'logits')} for row in cache['rows']]
    require(wire(actual) == wire(expected), 'independent teacher logits differ from exact saved cache')
    batches, rows = model.encoder_batch_forwards-before_batches, model.encoder_source_evaluations-before_rows
    require(batches == 34 and rows == 1632, 'independent teacher replay counters differ')
    return {'exact_rows': rows, 'logits_and_sources_sha256': digest(actual),
            'encoder_batch_forwards': batches, 'encoder_source_evaluations': rows}


def run(config_path, cache_freeze_path, output):
    # Importing the corpus does not read any of its materialized references.
    from ipfs_datasets_py.logic.autoformal import legal_temporal_stability_corpus as corpus
    config_pin, freeze_pin = reference(config_path), reference(cache_freeze_path)
    config, freeze = read(config_pin), read(freeze_pin)
    manifest = read(config['corpus_manifest'])
    guard = frozen.phase_guard(manifest, SEALED_KEYS)
    data = corpus.load_training_inputs(config['corpus_manifest']['path'])
    require(wire(data['manifest_ref']) == wire(config['corpus_manifest']), 'teacher loader corpus binding differs')
    verify_teacher_freeze(freeze, config_pin, config)
    pinned = {pin['path']: pin['sha256'] for pin in config['producer_files']}
    for path, sha in freeze['producer_pins'].items():
        require(pinned.get(path) == sha and reference(path)['sha256'] == sha, 'teacher freeze producer bytes differ')
    initial_pins = producer_pins()
    reports = []
    for seed in SEEDS:
        parent_pin, cache_pin = config['parents'][str(seed)], freeze['models'][str(seed)]
        require(parent_pin['sha256'] == frozen.runner.PARENT_SHAS[seed], 'preselected original parent changed')
        parent, cache = read(parent_pin), read(cache_pin)
        single = [{k: row[k] for k in (*SOURCE_KEYS, 'label', 'group_id')} for row in data['single_training']]
        paired = [{k: row[k] for k in (*SOURCE_KEYS, 'label', 'group_id')} for row in data['prior_paired_training']]
        sources, correct_counts = verify_cache(cache, parent, single, paired,
            seed=seed, parent_pin=parent_pin, expected_implementation=runtime.producer_pins())
        model = parent_runtime.PairedTemporalOwnershipHead(parent)
        model.model.requires_grad_(False); model.model.eval()
        before = digest({name: value.detach().tolist() for name, value in model.model.state_dict().items()})
        replayed = replay_cache_logits(cache, sources, model)
        after = digest({name: value.detach().tolist() for name, value in model.model.state_dict().items()})
        require(before == after == digest(parent['model_state']) and
                all(p.grad is None and not p.requires_grad for p in model.model.parameters()), 'independent teacher state changed')
        reports.append({'seed': seed, 'parent': parent_pin, 'cache': cache_pin,
            'cache_payload_sha256': digest(cache), 'sources_sha256': digest(sources),
            'correct_training_rows_by_class': correct_counts, 'model_state_before_sha256': before,
            'model_state_after_sha256': after, **replayed})
        print(wire({'phase': 'independent_teacher_replay', 'seed': seed, **replayed}).decode(), flush=True)
    require(producer_pins() == initial_pins and not guard['released'] and not guard['premature_read_attempts'],
            'teacher checker producer drift or fresh reference access')
    return write(output, {'schema': SCHEMA, 'config': config_pin, 'teacher_cache_freeze': freeze_pin,
        'producer_files': initial_pins, 'teachers': reports, 'exact_replay': True,
        'encoder_batch_forwards': 68, 'encoder_source_evaluations': 3264,
        'fresh_references_opened': False, 'fresh_reference_guard': guard,
        'optimizer_updates': 0, 'training_labels_used_only_for_cache_correctness_audit': True,
        'current_fresh_results_used': False, 'owner_occurrence_resolved': False, 'pipeline_promotion': False})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--teacher-cache-freeze', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(wire(run(args.config, args.teacher_cache_freeze, args.output)).decode(), flush=True)


if __name__ == '__main__':
    main()
