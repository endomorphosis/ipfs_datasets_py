#!/usr/bin/env python3
"""Independent saved-input, replay and scoring checks for paired owner types.

The independent replay phase denies current fresh semantic files. Scoring
reconciles admitted metrics and selection before releasing those references.
Ownership types never authorize an owner anchor, attachment or formal output.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys

os.environ['CUDA_VISIBLE_DEVICES'] = '-1'
os.environ['OMP_NUM_THREADS'] = '1'
os.environ['OPENBLAS_NUM_THREADS'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from ipfs_datasets_py.logic.autoformal import legal_temporal_ownership_metrics as metric
from ipfs_datasets_py.logic.autoformal import legal_paired_temporal_ownership_corpus as corpus
from ipfs_datasets_py.logic.autoformal import legal_temporal_owner_candidates as candidates
from scripts.ops.legal_ir import qualify_legal_temporal_ownership_head_v2 as old
from scripts.ops.legal_ir import run_legal_paired_temporal_ownership as runner

SCHEMA = 'legal-paired-owner-type-independent-qualification/v1'
ARMS = ('single_replay', 'mixed_occurrences', 'ambiguity_weighted')
SEEDS = (1730, 1731)
STEPS = (0, 50, 100, 200)
CHECKPOINT_SCHEMA = 'legal-paired-temporal-owner-type-checkpoint/v1'
ADMITTED = ('single_training', 'paired_training', 'single_tuning', 'paired_tuning')
PANELS = ('fresh_lexical', 'fresh_structural', 'old_single_fresh', 'old_multi_fresh')
COUNTS = dict(zip((*ADMITTED, *PANELS), (768, 864, 144, 288, 144, 144, 192, 96)))
require = metric.require


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(wire(value)).hexdigest()


def reference(path):
    path = Path(path).resolve(); raw = path.read_bytes()
    return {'path': str(path), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def read_producer(pin):
    fields = {'path', 'bytes', 'sha256'}
    require(type(pin) is dict and (set(pin) == fields or set(pin) == fields | {'schema'}) and
            type(pin['path']) is str and Path(pin['path']).is_absolute() and
            type(pin['bytes']) is int and pin['bytes'] >= 0 and type(pin['sha256']) is str and
            re.fullmatch(r'[0-9a-f]{64}', pin['sha256']) is not None, 'closed type-strict byte reference required')
    require(wire(reference(pin['path'])) == wire({k: pin[k] for k in fields}), 'saved evidence bytes changed')
    if 'schema' in pin:
        require(pin['schema'] in (CHECKPOINT_SCHEMA, 'legal-temporal-owner-type-checkpoint/v1') and
                json.loads(Path(pin['path']).read_bytes())['schema'] == pin['schema'], 'typed checkpoint schema differs')


def read(pin):
    read_producer(pin)
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON member')
            result[key] = value
        return result
    return json.loads(Path(pin['path']).read_bytes(), object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as handle:
        json.dump(value, handle, sort_keys=True, indent=2, allow_nan=False); handle.write('\n')
    return reference(path)


def phase_guard(manifest, sealed_keys):
    """Deny OS-level opens until the explicit checked release transition."""
    paths = {str(Path(manifest['artifacts'][key]['path']).resolve()) for key in sealed_keys}
    require(len(paths) == len(sealed_keys) == 4, 'four distinct fresh reference seals required')
    state = {'sealed_paths': sorted(paths), 'released': False, 'premature_read_attempts': [], 'postrelease_reads': []}
    def audit(event, args):
        if event != 'open' or not args or not isinstance(args[0], (str, bytes, os.PathLike)):
            return
        path = str(Path(os.fsdecode(args[0])).resolve())
        if path in paths:
            if not state['released']:
                state['premature_read_attempts'].append(path)
                raise PermissionError('current fresh reference remains sealed: '+path)
            state['postrelease_reads'].append(path)
    sys.addaudithook(audit)
    return state


def independent_selection(scores):
    """Unchanged parent retention on old tuning; rank only new tuning."""
    require(type(scores) is dict and set(scores) == set(STEPS) and
            all(type(k) is int for k in scores), 'parent and all prospective stages required')
    parent = scores[0]['single_tuning']; eligible = {}; ranks = {}
    for step in STEPS:
        single, paired = scores[step]['single_tuning'], scores[step]['paired_tuning']
        for value, count in ((single, 144), (paired, 288)):
            require(type(value['count']) is int and value['count'] == count and
                    type(value['correct']) is int and 0 <= value['correct'] <= count and
                    type(value['accepted_type_errors']) is int and 0 <= value['accepted_type_errors'] <= count-value['correct'] and
                    type(value['macro_f1']) in (int, float) and math.isfinite(value['macro_f1']) and 0 <= value['macro_f1'] <= 1 and
                    type(value['mean_nll']) in (int, float) and math.isfinite(value['mean_nll']) and value['mean_nll'] >= 0,
                    'closed finite selection count/range contract required')
        eligible[step] = single['correct'] >= parent['correct'] and single['accepted_type_errors'] <= parent['accepted_type_errors']
        ranks[step] = (-paired['macro_f1'], paired['mean_nll'], step)
    chosen = min((s for s in STEPS if eligible[s]), key=ranks.__getitem__)
    return {'selected_steps': chosen, 'eligible_steps': [s for s in STEPS if eligible[s]],
            'ranking': {str(s): list(ranks[s]) for s in STEPS},
            'old_single_correct_floor': parent['correct'], 'old_single_accepted_error_ceiling': parent['accepted_type_errors'],
            'fresh_results_used': False, 'coverage_gate_applied': False, 'pipeline_promotion': False}


def generation(value, checkpoint, sources_pin, sources, *, arm, seed, step, decoder_kind='paired_owner_type'):
    require(value['schema'] == 'legal-temporal-owner-type-source-generation/v1', 'generation schema differs')
    require(wire(value['model']) == wire({'checkpoint': checkpoint, 'decoder_kind': decoder_kind,
                                        'arm': arm, 'seed': seed, 'steps': step}),
            'generation model differs')
    require(wire(value['sources']) == wire(sources_pin), 'generation source binding differs')
    require(value['class_order'] == list(metric.CLASSES) and type(value['threshold']) is float and value['threshold'] == .8,
            'fixed taxonomy/threshold differs')
    require(all(value[key] is False for key in metric.FALSE_FIELDS | {'labels_supplied', 'source_id_used_as_feature', 'owner_or_cue_spans_supplied'}),
            'generation authority/input flags differ')
    require(value['source_text_conditioned'] is True and value['time_occurrence_conditioned'] is True,
            'occurrence conditioning required for every continuation arm')
    require(type(value['encoder_batch_forwards']) is int and value['encoder_batch_forwards'] == math.ceil(len(sources)/48) and
            type(value['encoder_source_evaluations']) is int and value['encoder_source_evaluations'] == len(sources),
            'generation actual counters differ')
    require(type(value['rows']) is list and len(value['rows']) == len(sources) and
            [r['id'] for r in value['rows']] == [s['id'] for s in sources], 'complete ordered source inventory required')
    for source, row in zip(sources, value['rows']): metric.checked_prediction(source, row)
    return value['rows']


def reconcile_metrics(actual, reported):
    old.reconcile_metrics(actual, reported)


def paired_comparison(baseline, treatment):
    before = {row['id']: row for row in baseline['rows']}
    require(len(before) == len(baseline['rows']) == len(treatment['rows']) and
            set(before) == {row['id'] for row in treatment['rows']}, 'paired metrics require identical complete query IDs')
    fixed = lost = 0
    for row in treatment['rows']:
        left = before[row['id']]
        require(all(wire(left[k]) == wire(row[k]) for k in ('source_sha256', 'proposed_time_span', 'target')),
                'paired source occurrence/reference binding differs')
        fixed += not left['correct'] and row['correct']; lost += left['correct'] and not row['correct']
    require(fixed-lost == treatment['correct']-baseline['correct'], 'paired correctness arithmetic differs')
    return {'count': len(before), 'correct_delta': fixed-lost, 'fixed': fixed, 'regressed': lost,
            'accepted_type_error_delta': treatment['accepted_type_errors']-baseline['accepted_type_errors']}


def producer_pins():
    paths = set(runner.producer_pins()) | set(candidates.producer_pins())
    paths.update(str(Path(m.__file__).resolve()) for m in (sys.modules[__name__], metric, corpus, old))
    return [reference(path) for path in sorted(paths)]


def physical_metadata(slot):
    return {'arm': 'finetune_occurrence' if slot['decoder_kind'] == 'old_owner_type' else slot['arm'],
            'seed': slot['seed'], 'step': 200 if slot['decoder_kind'] == 'old_owner_type' else slot['additional_steps'],
            'decoder_kind': slot['decoder_kind']}


def load_inputs(freeze):
    config = read(freeze['config']); manifest = read(config['corpus_manifest'])
    guard = phase_guard(manifest, runner.SEALED_KEYS)
    runner.load_config(freeze['config']['path'])
    data = corpus.load_training_inputs(config['corpus_manifest']['path'])
    return data, guard


def inventory(freeze, data):
    require(freeze['schema'] == runner.SCHEMA and freeze['all_training_selection_and_generation_complete'] is True and
            freeze['fresh_references_opened'] is False and freeze['fresh_reference_guard']['premature_read_attempts'] == 0,
            'complete source-only experiment freeze required')
    require(wire(freeze['producer_pins']) == wire(runner.producer_pins()), 'fitting producer closure differs')
    config = read(freeze['config']); selection = read(freeze['selections']); initials = read(freeze['initialization_freeze'])
    parents = read(freeze['parent_evaluations'])
    require(wire(selection['config']) == wire(initials['config']) == wire(freeze['config']) and
            wire(selection['initialization_freeze']) == wire(freeze['initialization_freeze']) and
            wire(selection['parent_evaluations']) == wire(freeze['parent_evaluations']), 'freeze lineage differs')
    require(selection['fresh_references_opened'] is False and selection['no_pipeline_promotion'] is True and
            parents['fresh_references_opened'] is False and parents['fresh_reference_guard']['premature_read_attempts'] == 0 and
            initials['fresh_references_opened'] is False and initials['fresh_reference_guard']['premature_read_attempts'] == 0,
            'parent/initial/selection seals differ')
    require(wire(parents['parents']) == wire(config['parents']) == wire(initials['parents']), 'parent references differ')
    require(wire(data['manifest_ref']) == wire(config['corpus_manifest']), 'admitted loader manifest differs')
    for seed in SEEDS:
        pin = config['parents'][str(seed)]; read_producer(pin)
        require(pin['sha256'] == runner.PARENT_SHAS[seed], 'fixed preceding parent differs')
    trials = {t['name']: t for t in selection['trials']}
    names = {f'{arm}-{seed}' for arm in ARMS for seed in SEEDS}
    require(set(trials) == names and len(selection['trials']) == len(selection['trial_references']) == 6,
            'six unique matched trials required')
    actual = [read(pin) for pin in selection['trial_references']]
    require(len({t['name'] for t in actual}) == 6 and wire({t['name']: t for t in actual}) == wire(trials), 'trial file differs')
    for name, trial in trials.items():
        require(type(trial['seed']) is int and name == f"{trial['arm']}-{trial['seed']}" and
                trial['fresh_references_opened'] is False and trial['fresh_reference_guard']['premature_read_attempts'] == 0 and
                trial['selected_is_pipeline_promotion'] is False, 'trial identity/seals differ')
        seed = trial['seed']; parent_pin = config['parents'][str(seed)]
        require(wire(trial['parent_checkpoint']) == wire(parent_pin) and wire(trial['initial_checkpoint']) == wire(initials['models'][name]),
                'trial initial/parent checkpoint differs')
        cp = read(trial['initial_checkpoint']); parent_cp = read(parent_pin)
        require(cp['schema'] == CHECKPOINT_SCHEMA and type(cp['optimizer_steps']) is int and cp['optimizer_steps'] == 0 and
                cp['config']['arm'] == trial['arm'] and cp['config']['seed'] == seed and
                wire(cp['model_state']) == wire(parent_cp['model_state']) and
                wire(cp['parent']) == wire(parent_cp) and cp['parent_file_sha256'] == parent_pin['sha256'] and
                cp['optimizer_state']['parameters'] == {}, 'initial tensor/parent/fresh optimizer contract differs')
        require(wire(trial['initial_evaluation']) == wire(parents['evaluations'][str(seed)]), 'shared parent evaluation differs')
        parent_candidate = trial['parent_candidate']
        require(type(parent_candidate['steps']) is int and parent_candidate['steps'] == 0 and
                parent_candidate['decoder_kind'] == 'old_owner_type' and wire(parent_candidate['checkpoint']) == wire(parent_pin),
                'candidate zero must be the exact parent')
        for panel in ADMITTED:
            e = parents['evaluations'][str(seed)][panel]
            require(wire(parent_candidate[panel+'_generation']) == wire(e['generation']) and
                    wire(parent_candidate[panel+'_metrics']) == wire(e['metrics']), 'parent candidate score binding differs')
        require(wire([s['steps'] for s in trial['stages']]) == wire(list(STEPS[1:])), 'all prospective stages required')
        for stage in trial['stages']:
            read_producer(stage['checkpoint']); read_producer(stage['training_report'])
            require(stage['decoder_kind'] == 'paired_owner_type' and type(stage['eligible']) is bool, 'stage kind/eligibility differs')
        chosen = [s for s in [parent_candidate, *trial['stages']] if s['steps'] == trial['selected_steps']]
        require(len(chosen) == 1 and type(trial['selected_steps']) is int and
                wire(chosen[0]['checkpoint']) == wire(trial['selected_checkpoint']) and
                chosen[0]['decoder_kind'] == trial['selected_decoder_kind'] and
                trial['selected_parent_fallback'] is (trial['selected_steps'] == 0), 'selected checkpoint/parent alias differs')
    sources = {k: read(v) for k, v in freeze['sources'].items()}
    authoritative = {k: [corpus.source_row(r) for r in data[k]] for k in ADMITTED}
    authoritative.update({k: data[k+'_sources'] for k in PANELS[:2]})
    authoritative.update({'old_single_fresh': data['regression_sources']['single'], 'old_multi_fresh': data['regression_sources']['multi']})
    require(set(sources) == set(COUNTS), 'complete eight-panel source inventory required')
    for panel, values in sources.items():
        corpus.validate_query_inventory(values, expected=COUNTS[panel])
        require(wire(values) == wire(authoritative[panel]), 'saved sources differ from authoritative source pack')
    expected = {(f'parent-{seed}', panel) for seed in SEEDS for panel in PANELS}
    expected |= {(name+'__'+role, panel) for name in names for role in ('selected', 'final200') for panel in PANELS}
    seen = set(); unique = {}; physical = []
    for slot in freeze['logical_generations']:
        identity = (slot['slot'], slot['panel']); seed = slot['seed']
        require(identity in expected and identity not in seen and type(seed) is int and seed in SEEDS, 'duplicate/unknown logical slot')
        seen.add(identity)
        if slot['role'] == 'parent':
            require(slot['slot'] == f'parent-{seed}' and slot['arm'] == 'parent', 'parent slot differs')
            cp, kind, steps = config['parents'][str(seed)], 'old_owner_type', 0
        else:
            name = f"{slot['arm']}-{seed}"; trial = trials[name]
            require(slot['slot'] == name+'__'+slot['role'], 'trial slot differs')
            if slot['role'] == 'selected': cp, kind, steps = trial['selected_checkpoint'], trial['selected_decoder_kind'], trial['selected_steps']
            else:
                require(slot['role'] == 'final200', 'unknown stage role')
                cp, kind, steps = trial['stages'][-1]['checkpoint'], 'paired_owner_type', 200
        require(wire(cp) == wire(slot['checkpoint']) and kind == slot['decoder_kind'] and type(slot['additional_steps']) is int and
                steps == slot['additional_steps'], 'logical slot checkpoint/kind/relative step differs')
        key = digest({'checkpoint': cp['sha256'], 'sources': freeze['sources'][slot['panel']]['sha256']})
        require(key == slot['generation_key'] and slot['executed_here'] is (key not in unique), 'alias identity or execution flag differs')
        if key in unique:
            require(wire(unique[key]['generation']) == wire(slot['generation']) and unique[key]['decoder_kind'] == kind, 'alias payload/kind differs')
        else:
            unique[key] = slot
            physical.append({'key': key, 'generation': slot['generation'], 'encoder_batch_forwards': math.ceil(COUNTS[slot['panel']]/48),
                             'encoder_source_evaluations': COUNTS[slot['panel']]})
    require(seen == expected and wire(physical) == wire(freeze['executed_generations']), 'full physical/logical generation inventory required')
    counts = {'logical_generation_slots': 56, 'logical_fresh_query_rows': 8064, 'physical_generation_files': len(physical),
              'physical_fresh_query_rows': sum(p['encoder_source_evaluations'] for p in physical),
              'physical_fresh_encoder_batch_forwards': sum(p['encoder_batch_forwards'] for p in physical),
              'total_optimizer_updates': 1200, 'training_encoder_batch_forwards': 1200, 'training_encoder_source_evaluations': 28800}
    for key, value in counts.items():require(type(freeze[key]) is int and freeze[key] == value, 'saved counter differs: '+key)
    require(wire(freeze['admitted_generation_counters']) == wire({'encoder_batch_forwards':860,'encoder_source_evaluations':41280}),
            'parent/stage physical admitted counters differ')
    return config, trials, sources, unique, counts
